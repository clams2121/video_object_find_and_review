from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> dt.datetime:
    return dt.datetime.utcnow()


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # camera_id, e.g. "camera1"
    name: Mapped[str] = mapped_column(String)
    first_seen: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    clips: Mapped[list["Clip"]] = relationship(back_populates="camera")


class Event(Base):
    """A cross-camera time-overlap grouping (future: correlate overlapping FOVs)."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    start_time: Mapped[dt.datetime] = mapped_column(DateTime)
    end_time: Mapped[dt.datetime] = mapped_column(DateTime)

    clips: Mapped[list["Clip"]] = relationship(back_populates="event")


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id_ext: Mapped[str] = mapped_column(String, unique=True, index=True)  # upstream event_id

    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    camera: Mapped["Camera"] = relationship(back_populates="clips")

    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), nullable=True)
    event: Mapped["Event | None"] = relationship(back_populates="clips")

    source_json_path: Mapped[str] = mapped_column(String)
    source_video_path: Mapped[str] = mapped_column(String)

    start_time: Mapped[dt.datetime] = mapped_column(DateTime)
    end_time: Mapped[dt.datetime] = mapped_column(DateTime)
    duration: Mapped[float] = mapped_column(Float)

    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    # pending | processing | good | maybe | no_detect | error | trashed

    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    tier_reached: Mapped[str | None] = mapped_column(String, nullable=True)  # motion | yolo
    object_class: Mapped[str | None] = mapped_column(String, nullable=True)
    object_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    motion_vector_dx: Mapped[float | None] = mapped_column(Float, nullable=True)
    motion_vector_dy: Mapped[float | None] = mapped_column(Float, nullable=True)
    path_straightness: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    motion_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    upstream_mean_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    upstream_max_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    upstream_motion_frame_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    upstream_motion_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    upstream_detection_size: Mapped[float | None] = mapped_column(Float, nullable=True)

    output_video_path: Mapped[str | None] = mapped_column(String, nullable=True)
    output_json_path: Mapped[str | None] = mapped_column(String, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)

    feedback: Mapped[list["Feedback"]] = relationship(back_populates="clip")


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clip_id: Mapped[int] = mapped_column(ForeignKey("clips.id"))
    clip: Mapped["Clip"] = relationship(back_populates="feedback")
    label: Mapped[str] = mapped_column(String)  # good | bad
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class LearnedThreshold(Base):
    __tablename__ = "learned_thresholds"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class WorkerEvent(Base):
    """Durable WARNING+ log record, so failures are visible on the /errors
    page even after a restart (in addition to the rotating log file)."""

    __tablename__ = "worker_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String)  # WARNING | ERROR | CRITICAL
    message: Mapped[str] = mapped_column(String)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
