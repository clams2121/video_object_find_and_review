import datetime as dt
import time

import pytest

from app.config import AppConfig, OutputConfig
from app.models import Camera, Clip
from app.worker import motion
from app.worker.pipeline import _process_clip_safely, _run_with_timeout
from app.worker.status import status as worker_status


def _slow(n):
    time.sleep(n)
    return "done"


def test_run_with_timeout_raises_promptly_instead_of_hanging():
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        _run_with_timeout(_slow, 0.2, 2)
    elapsed = time.monotonic() - start
    assert elapsed < 1.0  # should fail fast at ~0.2s, not wait for the full 2s hang


def _make_clip(db_session, tmp_path, event_id="camera1_error_test"):
    camera = Camera(id="camera1", name="camera1")
    db_session.add(camera)
    db_session.flush()

    video = tmp_path / f"{event_id}.mp4"
    json_file = tmp_path / f"{event_id}.json"
    video.write_bytes(b"fake")
    json_file.write_text("{}")

    start_time = dt.datetime(2026, 8, 4, 19, 0, 0)
    clip = Clip(
        event_id_ext=event_id,
        camera_id=camera.id,
        source_json_path=str(json_file),
        source_video_path=str(video),
        start_time=start_time,
        end_time=start_time + dt.timedelta(seconds=10),
        duration=10.0,
        status="pending",
    )
    db_session.add(clip)
    db_session.flush()
    return clip


def _cfg(tmp_path):
    return AppConfig(
        output=OutputConfig(
            good_dir=str(tmp_path / "good"),
            maybe_dir=str(tmp_path / "maybe"),
            no_detect_dir=str(tmp_path / "no_detect"),
            trash_dir=str(tmp_path / "trash"),
        ),
    )


def test_unreadable_video_is_marked_error_not_silently_reclassified(tmp_path, db_session):
    # source_video_path points at 4 garbage bytes, not a real mp4 - cv2 can't open it
    clip = _make_clip(db_session, tmp_path)
    cfg = _cfg(tmp_path)

    _process_clip_safely(db_session, clip, cfg)

    assert clip.status == "error"
    assert clip.error_message
    # file must NOT have been silently moved into no_detect/ - it's still where it was
    assert clip.output_video_path is None


def test_exception_during_processing_marks_clip_error_and_updates_worker_status(tmp_path, db_session, monkeypatch):
    clip = _make_clip(db_session, tmp_path, event_id="camera1_boom")
    cfg = _cfg(tmp_path)

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(motion, "analyze_motion", _boom)

    _process_clip_safely(db_session, clip, cfg)

    assert clip.status == "error"
    assert "boom" in clip.error_message
    assert worker_status.last_error is not None
    assert worker_status.last_error.clip_event_id == "camera1_boom"
    assert "boom" in worker_status.last_error.message


def test_timeout_during_processing_marks_clip_error(tmp_path, db_session, monkeypatch):
    clip = _make_clip(db_session, tmp_path, event_id="camera1_hang")
    cfg = _cfg(tmp_path)
    cfg.processing_timeout_seconds = 0.2

    def _hang(*args, **kwargs):
        time.sleep(5)

    monkeypatch.setattr(motion, "analyze_motion", _hang)

    start = time.monotonic()
    _process_clip_safely(db_session, clip, cfg)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0  # proves the worker did not block for the full 5s hang
    assert clip.status == "error"
    assert "timeout" in clip.error_message.lower()
