from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import cv2
import numpy as np

WIDTH, HEIGHT = 640, 360
FPS = 15.0


def _writer(path: Path) -> cv2.VideoWriter:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    return cv2.VideoWriter(str(path), fourcc, FPS, (WIDTH, HEIGHT))


def _write_json(json_path: Path, video_path: Path, event_id: str, camera_id: str,
                 start_time: dt.datetime, duration_seconds: float) -> None:
    end_time = start_time + dt.timedelta(seconds=duration_seconds)
    payload = {
        "event_id": event_id,
        "camera_id": camera_id,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "video_path": str(video_path),
        "motion_confidence": {"mean_score": 5000.0, "max_score": 7000.0, "motion_frame_ratio": 0.2},
        "motion_time": duration_seconds * 0.6,
        "detection_size": 0.05,
    }
    with open(json_path, "w") as f:
        json.dump(payload, f)


def make_clean_motion_clip(out_dir: Path, event_id: str, camera_id: str, start_time: dt.datetime) -> None:
    """A small square moving in a straight diagonal line - should read as
    confidently 'good' from the motion tier alone."""
    video_path = out_dir / f"{event_id}.mp4"
    json_path = out_dir / f"{event_id}.json"
    n_frames = 40
    vw = _writer(video_path)
    size = 50
    for i in range(n_frames):
        frame = np.full((HEIGHT, WIDTH, 3), 30, dtype=np.uint8)
        x = int(20 + (WIDTH - 2 * size - 20) * (i / (n_frames - 1)))
        y = int(20 + (HEIGHT - 2 * size - 20) * (i / (n_frames - 1)))
        cv2.rectangle(frame, (x, y), (x + size, y + size), (200, 200, 200), -1)
        vw.write(frame)
    vw.release()
    _write_json(json_path, video_path, event_id, camera_id, start_time, n_frames / FPS)


def make_flicker_clip(out_dir: Path, event_id: str, camera_id: str, start_time: dt.datetime) -> None:
    """A day/night IR-switch style full-frame brightness jump on a single frame,
    otherwise static - should be rejected as a flicker, not real motion."""
    video_path = out_dir / f"{event_id}.mp4"
    json_path = out_dir / f"{event_id}.json"
    n_frames = 30
    vw = _writer(video_path)
    for i in range(n_frames):
        brightness = 220 if i == 15 else 25
        frame = np.full((HEIGHT, WIDTH, 3), brightness, dtype=np.uint8)
        vw.write(frame)
    vw.release()
    _write_json(json_path, video_path, event_id, camera_id, start_time, n_frames / FPS)


def make_borderline_clip(out_dir: Path, event_id: str, camera_id: str, start_time: dt.datetime) -> None:
    """A tiny object jittering randomly for only a few frames - ambiguous size/
    duration/straightness, should land in the 'maybe' review band."""
    video_path = out_dir / f"{event_id}.mp4"
    json_path = out_dir / f"{event_id}.json"
    n_frames = 25
    vw = _writer(video_path)
    rng = np.random.default_rng(42)
    size = 8
    for i in range(n_frames):
        frame = np.full((HEIGHT, WIDTH, 3), 30, dtype=np.uint8)
        if 8 <= i <= 14:
            x = int(rng.integers(100, WIDTH - 100))
            y = int(rng.integers(100, HEIGHT - 100))
            cv2.rectangle(frame, (x, y), (x + size, y + size), (180, 180, 180), -1)
        vw.write(frame)
    vw.release()
    _write_json(json_path, video_path, event_id, camera_id, start_time, n_frames / FPS)


def generate_all(out_dir: Path, base_time: dt.datetime | None = None) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    base_time = base_time or dt.datetime(2026, 8, 4, 19, 0, 0)
    event_ids = []
    for i, (maker, label) in enumerate([
        (make_clean_motion_clip, "clean"),
        (make_flicker_clip, "flicker"),
        (make_borderline_clip, "borderline"),
    ]):
        event_id = f"camera1_synthetic_{label}"
        maker(out_dir, event_id, "camera1", base_time + dt.timedelta(minutes=i))
        event_ids.append(event_id)
    return event_ids


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/watch")
    ids = generate_all(target)
    print(f"Generated {len(ids)} synthetic clip(s) in {target}: {ids}")
