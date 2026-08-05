from __future__ import annotations

import logging
import shutil
import threading
from pathlib import Path

import cv2
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.db import session_scope
from app.models import Clip, Feedback
from app.worker import motion, scanner, yolo_detect
from app.worker.status import status as worker_status
from app.worker.thresholds import get_effective_detection_config, recompute_thresholds

logger = logging.getLogger(__name__)

_OUTPUT_DIR_BY_STATUS = {
    "good": "good_dir",
    "maybe": "maybe_dir",
    "no_detect": "no_detect_dir",
}


def _run_with_timeout(fn, timeout_seconds, *args, **kwargs):
    """Runs fn in a daemon thread and raises TimeoutError if it doesn't finish
    in time, instead of letting a hung cv2/YOLO call block the whole worker
    loop forever. Python can't force-kill a thread, so a timed-out call is
    abandoned (not joined) rather than awaited - the caller must treat the
    clip as failed and move on. The thread is daemonized (unlike
    ThreadPoolExecutor's workers) so a call that never returns can't prevent
    the process itself from shutting down."""
    box: dict = {}

    def _target():
        try:
            box["value"] = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - re-raised on the caller's thread below
            box["exc"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout_seconds)

    if thread.is_alive():
        name = getattr(fn, "__name__", "operation")
        raise TimeoutError(f"{name} exceeded {timeout_seconds}s timeout")
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


def _destination_dir(cfg: AppConfig, status: str, start_time) -> Path:
    attr = _OUTPUT_DIR_BY_STATUS[status]
    base = getattr(cfg.output, attr)
    return Path(base) / start_time.strftime("%Y-%m-%d") / start_time.strftime("%H")


def _move_output_files(clip: Clip, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    # Clips that errored out before the normal move step still have their
    # files at source_*_path rather than output_*_path - fall back so they
    # can still be reclassified or trashed from the UI.
    candidates = (
        (clip.output_video_path or clip.source_video_path, ".mp4", "output_video_path"),
        (clip.output_json_path or clip.source_json_path, ".json", "output_json_path"),
        (clip.thumbnail_path, ".jpg", "thumbnail_path"),
    )
    for src, suffix, attr in candidates:
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
    result = _run_with_timeout(
        motion.analyze_motion, cfg.processing_timeout_seconds, clip.source_video_path, detection_cfg
    )

    if result.error:
        logger.error("Motion analysis could not read clip %s: %s", clip.event_id_ext, result.error)
        clip.status = "error"
        clip.error_message = result.error
        clip.tier_reached = "motion"
        worker_status.record_error(f"{clip.event_id_ext}: {result.error}", clip.event_id_ext)
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
        final_status = "no_detect"
    elif result.confidence > high:
        final_status = "good"
    elif cfg.yolo.enabled and result.best_frame_index is not None:
        frames = _gather_candidate_frames(clip.source_video_path, result.best_frame_index)
        detection = _run_with_timeout(
            yolo_detect.classify_frames, cfg.processing_timeout_seconds, frames, cfg.yolo
        )
        clip.tier_reached = "yolo"
        if detection is not None:
            final_status = "good"
            clip.object_class = detection.class_name
            clip.object_confidence = detection.confidence
        else:
            final_status = "maybe"
    else:
        final_status = "maybe"

    thumb_frame_index = result.best_frame_index if result.best_frame_index is not None else 0
    thumb_frame = motion.extract_frame(clip.source_video_path, thumb_frame_index)

    dest_dir = _destination_dir(cfg, final_status, clip.start_time)
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

    clip.status = final_status


def _process_clip_safely(session: Session, clip: Clip, cfg: AppConfig) -> None:
    try:
        _process_clip(session, clip, cfg)
    except Exception as exc:
        logger.exception("Failed to process clip %s (id=%s)", clip.event_id_ext, clip.id)
        clip.status = "error"
        clip.error_message = str(exc)[:2000]
        worker_status.record_error(f"{clip.event_id_ext}: {exc}", clip.event_id_ext)


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
    worker_status.begin_cycle()

    try:
        with session_scope() as session:
            new_ids = scanner.discover_and_register(session, cfg)
        if new_ids:
            logger.info("Registered %d new clip(s)", len(new_ids))
    except Exception:
        logger.exception("Directory scan failed")
        worker_status.record_error("Directory scan failed - see log for details")
        worker_status.finish_cycle()
        return

    with session_scope() as session:
        pending_ids = list(
            session.execute(select(Clip.id).where(Clip.status == "pending")).scalars()
        )

    worker_status.begin_batch(len(pending_ids))

    for i, clip_id in enumerate(pending_ids, start=1):
        with session_scope() as session:
            clip = session.get(Clip, clip_id)
            if clip is None or clip.status != "pending":
                continue
            worker_status.set_current(i, clip.event_id_ext)
            _process_clip_safely(session, clip, cfg)

    worker_status.finish_cycle()
