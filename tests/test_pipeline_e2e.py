import datetime as dt
from pathlib import Path

from sqlalchemy import select

from app.config import AppConfig, DetectionConfig, OutputConfig
from app.models import Clip
from app.worker import scanner
from app.worker.pipeline import _process_clip, reprocess_clip
from scripts.synthetic_clips import make_clean_motion_clip, make_flicker_clip


def _make_cfg(tmp_path, watch_dir):
    return AppConfig(
        watch_directories=[str(watch_dir)],
        min_file_age_seconds=0,
        output=OutputConfig(
            good_dir=str(tmp_path / "good"),
            maybe_dir=str(tmp_path / "maybe"),
            no_detect_dir=str(tmp_path / "no_detect"),
            trash_dir=str(tmp_path / "trash"),
        ),
        detection=DetectionConfig(),
    )


def _run_pipeline_for_all_pending(db_session, cfg):
    scanner.discover_and_register(db_session, cfg)
    db_session.flush()
    pending = db_session.execute(select(Clip).where(Clip.status == "pending")).scalars().all()
    for clip in pending:
        cfg_for_yolo_off = cfg.model_copy(deep=True)
        cfg_for_yolo_off.yolo.enabled = False  # keep the e2e test fast/deterministic, no model download
        _process_clip(db_session, clip, cfg_for_yolo_off)
    return pending


def test_clean_motion_clip_is_classified_good_and_moved(tmp_path, db_session):
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    make_clean_motion_clip(watch_dir, "camera1_clean", "camera1", dt.datetime(2026, 8, 4, 19, 0, 0))

    cfg = _make_cfg(tmp_path, watch_dir)
    clips = _run_pipeline_for_all_pending(db_session, cfg)

    assert len(clips) == 1
    clip = clips[0]
    assert clip.status == "good"
    assert clip.output_video_path is not None
    assert "good" in clip.output_video_path
    assert Path(clip.output_video_path).exists()
    assert Path(clip.thumbnail_path).exists()
    # source files should have been moved out of the watch directory
    assert not (watch_dir / "camera1_clean.mp4").exists()


def test_flicker_clip_is_classified_no_detect(tmp_path, db_session):
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    make_flicker_clip(watch_dir, "camera1_flicker", "camera1", dt.datetime(2026, 8, 4, 19, 5, 0))

    cfg = _make_cfg(tmp_path, watch_dir)
    clips = _run_pipeline_for_all_pending(db_session, cfg)

    assert len(clips) == 1
    clip = clips[0]
    assert clip.status == "no_detect"
    assert "no_detect" in clip.output_video_path


def test_rescanning_does_not_reregister_processed_clips(tmp_path, db_session):
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    make_clean_motion_clip(watch_dir, "camera1_clean2", "camera1", dt.datetime(2026, 8, 4, 19, 10, 0))

    cfg = _make_cfg(tmp_path, watch_dir)
    _run_pipeline_for_all_pending(db_session, cfg)

    new_ids = scanner.discover_and_register(db_session, cfg)
    assert new_ids == []


def test_reprocess_rereads_the_already_moved_clip(tmp_path, db_session):
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    make_clean_motion_clip(watch_dir, "camera1_clean3", "camera1", dt.datetime(2026, 8, 4, 19, 15, 0))

    cfg = _make_cfg(tmp_path, watch_dir)
    cfg.yolo.enabled = False
    clips = _run_pipeline_for_all_pending(db_session, cfg)
    clip = clips[0]
    assert clip.status == "good"
    first_video_path = clip.output_video_path
    first_thumb_path = clip.thumbnail_path
    assert Path(first_video_path).exists()
    assert Path(first_thumb_path).exists()

    reprocess_clip(db_session, clip, cfg)

    assert clip.status == "good"
    # file moved back to the (same) good/ folder, not lost or left in limbo
    assert clip.output_video_path == first_video_path
    assert Path(clip.output_video_path).exists()
    assert Path(clip.thumbnail_path).exists()
