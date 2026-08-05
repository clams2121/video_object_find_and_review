from __future__ import annotations

import logging
import shutil
from pathlib import Path

import cv2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.db import session_scope
from app.models import Clip, Feedback
from app.worker import motion, scanner, yolo_detect
from app.worker.thresholds import get_effective_detection_config, recompute_thresholds

logger = logging.getLogger(__name__)

_OUTPUT_DIR_BY_STATUS = {
    "good": "good_dir",
    "maybe": "maybe_dir",
    "no_detect": "no_detect_dir",
}


def _destination_dir(cfg: AppConfig, status: str, start_time) -> Path:
    attr = _OUTPUT_DIR_BY_STATUS[status]
    base = getattr(cfg.output, attr)
    return Path(base) / start_time.strftime("%Y-%m-%d") / start_time.strftime("%H")


def _move_output_files(clip: Clip, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for attr, suffix in (
        ("output_video_path", ".mp4"),
        ("output_json_path", ".json"),
        ("thumbnail_path", ".jpg"),
    ):
        src = getattr(clip, attr)
        if src and Path(src).exists():
            dest = dest_dir / f"{clip.event_id_ext}{suffix}"
            shutil.move(src, dest)
            setattr(clip, attr, str(dest))


def _gather_candidate_frames(video_path: str, best_frame_index: int) -> list:
    frames = []
    for offset in (0, -2, 2):
        idx = max(0, best_frame_index + offset)
        frame = motion.extract_frame(video_path, idx)
        if frame is not None:
            frames.append(frame)
    return frames


def _process_clip(session: Session, clip: Clip, cfg: AppConfig) -> None:
    clip.status = "processing"
    session.flush()

    detection_cfg = get_effective_detection_config(session, cfg.detection)
    result = motion.analyze_motion(clip.source_video_path, detection_cfg)

    if result.error:
        logger.error("Motion analysis failed for clip %s: %s", clip.event_id_ext, result.error)
        clip.status = "no_detect"
        clip.tier_reached = "motion"
        return

    clip.size_min = result.size_min
    clip.size_max = result.size_max
    clip.frame_count = result.frame_count
    clip.active_duration_seconds = result.active_duration_seconds
    clip.motion_vector_dx = result.vector_dx
    clip.motion_vector_dy = result.vector_dy
    clip.path_straightness = result.path_straightness
    clip.motion_confidence = result.confidence
    clip.tier_reached = "motion"

    low, high = detection_cfg.ambiguous_band
    if result.is_flicker or result.confidence < low:
        status = "no_detect"
    elif result.confidence > high:
        status = "good"
    elif cfg.yolo.enabled and result.best_frame_index is not None:
        frames = _gather_candidate_frames(clip.source_video_path, result.best_frame_index)
        detection = yolo_detect.classify_frames(frames, cfg.yolo)
        clip.tier_reached = "yolo"
        if detection is not None:
            status = "good"
            clip.object_class = detection.class_name
            clip.object_confidence = detection.confidence
        else:
            status = "maybe"
    else:
        status = "maybe"

    thumb_frame_index = result.best_frame_index if result.best_frame_index is not None else 0
    thumb_frame = motion.extract_frame(clip.source_video_path, thumb_frame_index)

    dest_dir = _destination_dir(cfg, status, clip.start_time)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_video = dest_dir / f"{clip.event_id_ext}.mp4"
    dest_json = dest_dir / f"{clip.event_id_ext}.json"
    dest_thumb = dest_dir / f"{clip.event_id_ext}.jpg"

    if thumb_frame is not None:
        cv2.imwrite(str(dest_thumb), thumb_frame)
        clip.thumbnail_path = str(dest_thumb)

    shutil.move(clip.source_video_path, dest_video)
    shutil.move(clip.source_json_path, dest_json)
    clip.output_video_path = str(dest_video)
    clip.output_json_path = str(dest_json)

    clip.status = status


def move_clip_to_trash(clip: Clip, cfg: AppConfig) -> None:
    """Soft-delete: move a clip's files into the configured trash dir (mirroring
    the day/hour layout) rather than removing them from disk."""
    dest_dir = Path(cfg.output.trash_dir) / clip.start_time.strftime("%Y-%m-%d") / clip.start_time.strftime("%H")
    _move_output_files(clip, dest_dir)
    clip.status = "trashed"


def reclassify_clip(clip: Clip, new_status: str, cfg: AppConfig) -> None:
    """Move a clip's files into a different good/maybe/no_detect bucket, e.g.
    when user feedback overrides the automatic classification."""
    if new_status not in _OUTPUT_DIR_BY_STATUS:
        raise ValueError(f"invalid status for reclassify: {new_status}")
    dest_dir = _destination_dir(cfg, new_status, clip.start_time)
    _move_output_files(clip, dest_dir)
    clip.status = new_status


def record_feedback(session: Session, clip: Clip, label: str, cfg: AppConfig) -> None:
    session.add(Feedback(clip_id=clip.id, label=label))
    session.flush()
    reclassify_clip(clip, "good" if label == "good" else "no_detect", cfg)
    recompute_thresholds(session)


def run_scan_cycle() -> None:
    cfg = get_config()

    with session_scope() as session:
        new_ids = scanner.discover_and_register(session, cfg)
    if new_ids:
        logger.info("Registered %d new clip(s)", len(new_ids))

    with session_scope() as session:
        pending_ids = list(
            session.execute(select(Clip.id).where(Clip.status == "pending")).scalars()
        )

    for clip_id in pending_ids:
        try:
            with session_scope() as session:
                clip = session.get(Clip, clip_id)
                if clip is not None and clip.status in ("pending", "processing"):
                    _process_clip(session, clip, cfg)
        except Exception:
            logger.exception("Failed to process clip id=%s", clip_id)
