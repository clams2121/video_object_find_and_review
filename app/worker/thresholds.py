from __future__ import annotations

import copy
import logging

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DetectionConfig
from app.models import Clip, Feedback, LearnedThreshold

logger = logging.getLogger(__name__)

_MIN_SAMPLES = 3


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(values, pct))


def _set_threshold(session: Session, key: str, value: float) -> None:
    row = session.get(LearnedThreshold, key)
    if row is None:
        row = LearnedThreshold(key=key, value=value)
        session.add(row)
    else:
        row.value = value


def recompute_thresholds(session: Session) -> None:
    """Recompute learned min/max size and duration bounds from the good-labeled
    clip population. Pure percentile statistics, no model training."""
    good_clip_ids = (
        session.execute(select(Feedback.clip_id).where(Feedback.label == "good"))
        .scalars()
        .all()
    )
    if len(set(good_clip_ids)) < _MIN_SAMPLES:
        return

    good_clips = session.execute(select(Clip).where(Clip.id.in_(good_clip_ids))).scalars().all()
    sizes = [c.size_max for c in good_clips if c.size_max is not None]
    durations = [c.active_duration_seconds for c in good_clips if c.active_duration_seconds is not None]

    min_size = _percentile(sizes, 10)
    max_size = _percentile(sizes, 90)
    min_duration = _percentile(durations, 10)

    if min_size is not None:
        _set_threshold(session, "min_size_ratio", min_size)
    if max_size is not None:
        _set_threshold(session, "max_size_ratio", max_size)
    if min_duration is not None:
        _set_threshold(session, "min_duration_seconds", min_duration)


def get_effective_detection_config(session: Session, static_cfg: DetectionConfig) -> DetectionConfig:
    """Learned thresholds refine the static config but are clamped inside it
    (static values act as the outer safety envelope)."""
    effective = copy.deepcopy(static_cfg)
    learned = {row.key: row.value for row in session.execute(select(LearnedThreshold)).scalars()}

    if "min_size_ratio" in learned:
        effective.min_size_ratio = min(
            max(learned["min_size_ratio"], 0.0), static_cfg.max_size_ratio
        )
    if "max_size_ratio" in learned:
        effective.max_size_ratio = max(
            min(learned["max_size_ratio"], static_cfg.max_size_ratio), effective.min_size_ratio
        )
    if "min_duration_seconds" in learned:
        effective.min_duration_seconds = max(0.0, learned["min_duration_seconds"])

    return effective
