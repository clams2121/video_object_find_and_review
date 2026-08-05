import datetime as dt
import json

from app.worker.scanner import find_video_for_json, parse_event_json


def test_find_video_by_same_stem(tmp_path):
    json_path = tmp_path / "camera1_20260804_193709.json"
    video_path = tmp_path / "camera1_20260804_193709.mp4"
    json_path.write_text("{}")
    video_path.write_bytes(b"fake")

    found = find_video_for_json(json_path, None)
    assert found == video_path


def test_find_video_by_video_path_hint(tmp_path):
    json_path = tmp_path / "metadata.json"
    video_path = tmp_path / "actual_video.mp4"
    json_path.write_text("{}")
    video_path.write_bytes(b"fake")

    found = find_video_for_json(json_path, "/some/other/machine/path/actual_video.mp4")
    assert found == video_path


def test_find_video_missing_returns_none(tmp_path):
    json_path = tmp_path / "metadata.json"
    json_path.write_text("{}")
    assert find_video_for_json(json_path, None) is None
    assert find_video_for_json(json_path, "nope.mp4") is None


def test_parse_event_json_reads_sample_schema(tmp_path):
    sample = {
        "event_id": "camera1_20260804_193709",
        "camera_id": "camera1",
        "start_time": "2026-08-04T19:37:09.029817-04:00",
        "end_time": "2026-08-04T19:37:42.330666-04:00",
        "video_path": "/home/adam/camera_watcher/data/clips/camera1_20260804_193709.mp4",
        "motion_confidence": {"mean_score": 5754.3243, "max_score": 7147, "motion_frame_ratio": 0.1574},
        "motion_time": 3.6896,
        "detection_size": 0.2534,
    }
    json_path = tmp_path / "camera1_20260804_193709.json"
    json_path.write_text(json.dumps(sample))

    field_map = {
        "event_id": "event_id", "camera_id": "camera_id",
        "start_time": "start_time", "end_time": "end_time", "video_path": "video_path",
    }
    parsed = parse_event_json(json_path, field_map)

    assert parsed["event_id"] == "camera1_20260804_193709"
    assert parsed["camera_id"] == "camera1"
    # -04:00 offset converted to UTC naive
    assert parsed["start_time"] == dt.datetime(2026, 8, 4, 23, 37, 9, 29817)
    assert parsed["upstream_mean_score"] == 5754.3243
    assert parsed["upstream_motion_frame_ratio"] == 0.1574
    assert parsed["upstream_detection_size"] == 0.2534


def test_parse_event_json_missing_field_returns_none(tmp_path):
    json_path = tmp_path / "bad.json"
    json_path.write_text(json.dumps({"camera_id": "camera1"}))
    field_map = {
        "event_id": "event_id", "camera_id": "camera_id",
        "start_time": "start_time", "end_time": "end_time", "video_path": "video_path",
    }
    assert parse_event_json(json_path, field_map) is None
