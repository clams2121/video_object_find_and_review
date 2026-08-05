from __future__ import annotations

import datetime as dt
import json
import logging
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.models import Camera, Clip, Event

logger = logging.getLogger(__name__)


def _to_utc_naive(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def _is_old_enough(path: Path, min_age_seconds: int) -> bool:
    try:
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age >= min_age_seconds


def iter_json_files(watch_directories: list[str]) -> list[Path]:
    files: list[Path] = []
    for d in watch_directories:
        root = Path(d)
        if not root.exists():
            continue
        files.extend(sorted(root.rglob("*.json")))
    return files


def find_video_for_json(json_path: Path, video_path_hint: str | None) -> Path | None:
    same_stem = json_path.with_suffix(".mp4")
    if same_stem.exists():
        return same_stem
    if video_path_hint:
        basename = Path(video_path_hint).name
        candidate = json_path.parent / basename
        if candidate.exists():
            return candidate
        for match in json_path.parent.rglob(basename):
            return match
    return None


def parse_event_json(json_path: Path, field_map: dict[str, str]) -> dict | None:
    try:
        with open(json_path, "r") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to parse %s: %s", json_path, exc)
        return None

    try:
        event_id = raw[field_map["event_id"]]
        camera_id = raw[field_map["camera_id"]]
        start_time = _to_utc_naive(raw[field_map["start_time"]])
        end_time = _to_utc_naive(raw[field_map["end_time"]])
    except (KeyError, ValueError) as exc:
        logger.warning("Missing/invalid required field in %s: %s", json_path, exc)
        return None

    video_path_hint = raw.get(field_map.get("video_path", "video_path"))

    motion_confidence = raw.get("motion_confidence") or {}
    return {
        "event_id": event_id,
        "camera_id": camera_id,
        "start_time": start_time,
        "end_time": end_time,
        "video_path_hint": video_path_hint,
        "upstream_mean_score": motion_confidence.get("mean_score"),
        "upstream_max_score": motion_confidence.get("max_score"),
        "upstream_motion_frame_ratio": motion_confidence.get("motion_frame_ratio"),
        "upstream_motion_time": raw.get("motion_time"),
        "upstream_detection_size": raw.get("detection_size"),
    }


def _upsert_camera(session: Session, camera_id: str) -> Camera:
    camera = session.get(Camera, camera_id)
    if camera is None:
        camera = Camera(id=camera_id, name=camera_id)
        session.add(camera)
        session.flush()
    return camera


def _find_or_create_event(
    session: Session, start_time: dt.datetime, end_time: dt.datetime, tolerance_seconds: float
) -> Event:
    tol = dt.timedelta(seconds=tolerance_seconds)
    stmt = select(Event).where(
        Event.start_time <= end_time + tol,
        Event.end_time >= start_time - tol,
    )
    existing = session.execute(stmt).scalars().first()
    if existing:
        existing.start_time = min(existing.start_time, start_time)
        existing.end_time = max(existing.end_time, end_time)
        return existing
    event = Event(start_time=start_time, end_time=end_time)
    session.add(event)
    session.flush()
    return event


def discover_and_register(session: Session, cfg: AppConfig) -> list[int]:
    """Scan watch_directories for new json/mp4 pairs old enough to process,
    register them as pending Clip rows, and return their new Clip ids."""
    new_clip_ids: list[int] = []
    field_map = cfg.json_field_map

    for json_path in iter_json_files(cfg.watch_directories):
        if not _is_old_enough(json_path, cfg.min_file_age_seconds):
            continue

        parsed = parse_event_json(json_path, field_map)
        if parsed is None:
            continue

        existing = session.execute(
            select(Clip).where(Clip.event_id_ext == str(parsed["event_id"]))
        ).scalars().first()
        if existing is not None:
            continue

        video_path = find_video_for_json(json_path, parsed["video_path_hint"])
        if video_path is None:
            continue
        if not _is_old_enough(video_path, cfg.min_file_age_seconds):
            continue

        camera = _upsert_camera(session, str(parsed["camera_id"]))
        event = _find_or_create_event(
            session, parsed["start_time"], parsed["end_time"],
            cfg.event_grouping.overlap_tolerance_seconds,
        )

        duration = (parsed["end_time"] - parsed["start_time"]).total_seconds()
        clip = Clip(
            event_id_ext=str(parsed["event_id"]),
            camera_id=camera.id,
            event_id=event.id,
            source_json_path=str(json_path),
            source_video_path=str(video_path),
            start_time=parsed["start_time"],
            end_time=parsed["end_time"],
            duration=duration,
            status="pending",
            upstream_mean_score=parsed["upstream_mean_score"],
            upstream_max_score=parsed["upstream_max_score"],
            upstream_motion_frame_ratio=parsed["upstream_motion_frame_ratio"],
            upstream_motion_time=parsed["upstream_motion_time"],
            upstream_detection_size=parsed["upstream_detection_size"],
        )
        session.add(clip)
        session.flush()
        new_clip_ids.append(clip.id)

    return new_clip_ids
