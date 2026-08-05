from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from app.config import YoloConfig

logger = logging.getLogger(__name__)

_model_cache: dict[str, object] = {}


@dataclass
class Detection:
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2


def _resolve_device(device_cfg: str) -> str:
    if device_cfg != "auto":
        return device_cfg
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _load_model(model_name: str):
    if model_name not in _model_cache:
        from ultralytics import YOLO

        logger.info("Loading YOLO model %s", model_name)
        _model_cache[model_name] = YOLO(model_name)
    return _model_cache[model_name]


def classify_frames(frames: list[np.ndarray], cfg: YoloConfig) -> Detection | None:
    """Run YOLO on a small set of representative frames (not the whole clip) and
    return the single highest-confidence detection matching the configured classes.
    NOTE: classes without a COCO equivalent (e.g. "deer") will only match if a
    custom-trained model is configured via yolo.model."""
    if not cfg.enabled or not frames:
        return None

    model = _load_model(cfg.model)
    device = _resolve_device(cfg.device)

    best: Detection | None = None
    results = model.predict(source=frames, device=device, verbose=False)
    for result in results:
        names = result.names
        for box in result.boxes:
            class_name = names[int(box.cls[0])]
            confidence = float(box.conf[0])
            if class_name not in cfg.classes:
                continue
            if confidence < cfg.confidence_threshold:
                continue
            if best is None or confidence > best.confidence:
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
                best = Detection(class_name=class_name, confidence=confidence, bbox=(x1, y1, x2, y2))

    return best
