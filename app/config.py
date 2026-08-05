from __future__ import annotations

import os
import threading
from pathlib import Path

import yaml
from pydantic import BaseModel

CONFIG_PATH = Path(os.environ.get("CONFIG_PATH", "config.yaml")).resolve()

_lock = threading.Lock()


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class OutputConfig(BaseModel):
    good_dir: str = "./data/output/good"
    maybe_dir: str = "./data/output/maybe"
    no_detect_dir: str = "./data/output/no_detect"
    trash_dir: str = "./data/output/trash"


class EventGroupingConfig(BaseModel):
    overlap_tolerance_seconds: float = 5


class DetectionConfig(BaseModel):
    min_frames: int = 5
    min_size_ratio: float = 0.01
    max_size_ratio: float = 0.9
    min_duration_seconds: float = 0.5
    ambiguous_band: list[float] = [0.35, 0.65]


class YoloConfig(BaseModel):
    enabled: bool = True
    model: str = "yolov8n.pt"
    device: str = "auto"
    confidence_threshold: float = 0.4
    classes: list[str] = [
        "person", "dog", "cat", "deer", "horse", "cow", "bird",
        "car", "truck", "bus", "motorcycle", "bicycle",
    ]


class AppConfig(BaseModel):
    server: ServerConfig = ServerConfig()
    watch_directories: list[str] = []
    scan_interval_seconds: int = 60
    min_file_age_seconds: int = 30
    processing_timeout_seconds: int = 120
    output: OutputConfig = OutputConfig()
    database_path: str = "./data/app.db"
    event_grouping: EventGroupingConfig = EventGroupingConfig()
    detection: DetectionConfig = DetectionConfig()
    yolo: YoloConfig = YoloConfig()
    json_field_map: dict[str, str] = {
        "event_id": "event_id",
        "camera_id": "camera_id",
        "start_time": "start_time",
        "end_time": "end_time",
        "video_path": "video_path",
    }


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    with _lock:
        if not path.exists():
            cfg = AppConfig()
            save_config(cfg, path)
            return cfg
        with open(path, "r") as f:
            raw = yaml.safe_load(f) or {}
        return AppConfig.model_validate(raw)


def save_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.safe_dump(config.model_dump(), f, sort_keys=False)


def get_config() -> AppConfig:
    """Always reload from disk so worker/web stay in sync without a restart
    (host/port excepted, which only take effect on process start)."""
    return load_config()
