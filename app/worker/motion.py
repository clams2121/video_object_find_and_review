from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np

from app.config import DetectionConfig

logger = logging.getLogger(__name__)

_ANALYSIS_WIDTH = 320  # downscale target for cheap analysis
_NOISE_AREA_RATIO = 0.0005  # contours smaller than this fraction of frame are ignored as noise
_FLICKER_BRIGHTNESS_DELTA = 40.0  # mean-gray jump considered a day/night IR switch


@dataclass
class FrameObservation:
    frame_index: int
    area_ratio: float
    centroid: tuple[float, float]  # normalized 0..1
    bbox: tuple[int, int, int, int]  # x, y, w, h in analysis-resolution pixels
    mean_brightness: float


@dataclass
class MotionResult:
    frame_count: int = 0
    size_min: float | None = None
    size_max: float | None = None
    vector_dx: float | None = None
    vector_dy: float | None = None
    path_straightness: float | None = None
    active_duration_seconds: float = 0.0
    confidence: float = 0.0
    is_flicker: bool = False
    best_frame_index: int | None = None
    best_frame_bbox: tuple[int, int, int, int] | None = None
    analysis_scale: float = 1.0  # multiply bbox coords by this to map back to original resolution
    error: str | None = None


def _detect_flicker(observations: list[FrameObservation], total_frames: int) -> bool:
    if len(observations) == 0:
        return False
    # A day/night IR switch shows up as a near-full-frame "motion" blob confined to
    # one or two frames with a large brightness jump, surrounded by otherwise-quiet frames.
    if len(observations) > max(3, total_frames * 0.15):
        return False
    for obs in observations:
        if obs.area_ratio > 0.5:
            return True
    return False


def analyze_motion(video_path: str, detection_cfg: DetectionConfig) -> MotionResult:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return MotionResult(error=f"could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or _ANALYSIS_WIDTH
    scale = _ANALYSIS_WIDTH / width if width > _ANALYSIS_WIDTH else 1.0

    subtractor = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=24, detectShadows=False)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    observations: list[FrameObservation] = []
    frame_index = 0
    total_frames = 0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        total_frames += 1
        if scale != 1.0:
            frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        fgmask = subtractor.apply(frame)
        _, fgmask = cv2.threshold(fgmask, 200, 255, cv2.THRESH_BINARY)
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_OPEN, kernel)
        fgmask = cv2.morphologyEx(fgmask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        frame_area = frame.shape[0] * frame.shape[1]

        if contours:
            largest = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest)
            area_ratio = area / frame_area
            if area_ratio >= _NOISE_AREA_RATIO:
                x, y, w, h = cv2.boundingRect(largest)
                cx = (x + w / 2) / frame.shape[1]
                cy = (y + h / 2) / frame.shape[0]
                observations.append(
                    FrameObservation(
                        frame_index=frame_index,
                        area_ratio=area_ratio,
                        centroid=(cx, cy),
                        bbox=(x, y, w, h),
                        mean_brightness=float(np.mean(gray)),
                    )
                )
        frame_index += 1

    cap.release()

    result = MotionResult(analysis_scale=1.0 / scale if scale != 0 else 1.0)

    if not observations:
        result.confidence = 0.0
        return result

    result.is_flicker = _detect_flicker(observations, total_frames)
    if result.is_flicker:
        result.confidence = 0.0
        result.frame_count = len(observations)
        return result

    areas = [o.area_ratio for o in observations]
    result.size_min = min(areas)
    result.size_max = max(areas)
    result.frame_count = len(observations)
    result.active_duration_seconds = len(observations) / fps

    best_obs = max(observations, key=lambda o: o.area_ratio)
    result.best_frame_index = best_obs.frame_index
    result.best_frame_bbox = best_obs.bbox

    if len(observations) >= 2:
        first_c = observations[0].centroid
        last_c = observations[-1].centroid
        net_dx = last_c[0] - first_c[0]
        net_dy = last_c[1] - first_c[1]
        net_displacement = math.hypot(net_dx, net_dy)

        path_length = 0.0
        for a, b in zip(observations, observations[1:]):
            path_length += math.hypot(b.centroid[0] - a.centroid[0], b.centroid[1] - a.centroid[1])

        result.vector_dx = net_dx
        result.vector_dy = net_dy
        result.path_straightness = (net_displacement / path_length) if path_length > 1e-6 else 0.5
    else:
        result.vector_dx = 0.0
        result.vector_dy = 0.0
        result.path_straightness = 0.5

    result.confidence = _score_confidence(result, detection_cfg)
    return result


def _clamped_ratio(value: float, target: float) -> float:
    if target <= 0:
        return 1.0
    return max(0.0, min(1.0, value / target))


def _size_score(size_max: float, min_ratio: float, max_ratio: float) -> float:
    if size_max < min_ratio:
        return _clamped_ratio(size_max, min_ratio)
    if size_max > max_ratio:
        return max(0.0, 1.0 - (size_max - max_ratio) / max_ratio)
    return 1.0


def _score_confidence(result: MotionResult, cfg: DetectionConfig) -> float:
    frames_score = _clamped_ratio(result.frame_count, cfg.min_frames)
    size_score = _size_score(result.size_max, cfg.min_size_ratio, cfg.max_size_ratio)
    duration_score = _clamped_ratio(result.active_duration_seconds, cfg.min_duration_seconds)
    straightness_score = result.path_straightness if result.path_straightness is not None else 0.5

    return (
        0.25 * frames_score
        + 0.25 * size_score
        + 0.2 * duration_score
        + 0.3 * straightness_score
    )


def extract_frame(video_path: str, frame_index: int) -> np.ndarray | None:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None
