from __future__ import annotations

import datetime as dt
import threading
from collections import deque
from dataclasses import dataclass


@dataclass
class ErrorEntry:
    message: str
    clip_event_id: str | None
    at: dt.datetime


class WorkerStatus:
    """In-memory, thread-safe snapshot of what the background worker is doing
    right now. Written by the worker thread, read by web request threads to
    power the live status bar - not persisted (see WorkerEvent for durable
    error history across restarts)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.state = "idle"  # idle | scanning | processing
        self.total = 0
        self.current_index = 0
        self.current_event_id: str | None = None
        self.current_started_at: dt.datetime | None = None
        self.last_cycle_started_at: dt.datetime | None = None
        self.last_cycle_finished_at: dt.datetime | None = None
        self.last_error: ErrorEntry | None = None
        self.recent_errors: deque[ErrorEntry] = deque(maxlen=20)

    def begin_cycle(self) -> None:
        with self._lock:
            self.state = "scanning"
            self.last_cycle_started_at = dt.datetime.utcnow()
            self.total = 0
            self.current_index = 0
            self.current_event_id = None
            self.current_started_at = None

    def begin_batch(self, total: int) -> None:
        with self._lock:
            self.state = "processing" if total else "idle"
            self.total = total
            self.current_index = 0

    def set_current(self, index: int, event_id: str) -> None:
        with self._lock:
            self.current_index = index
            self.current_event_id = event_id
            self.current_started_at = dt.datetime.utcnow()

    def record_error(self, message: str, clip_event_id: str | None = None) -> None:
        with self._lock:
            entry = ErrorEntry(message=message, clip_event_id=clip_event_id, at=dt.datetime.utcnow())
            self.last_error = entry
            self.recent_errors.appendleft(entry)

    def finish_cycle(self) -> None:
        with self._lock:
            self.state = "idle"
            self.last_cycle_finished_at = dt.datetime.utcnow()
            self.current_index = 0
            self.current_event_id = None
            self.current_started_at = None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "state": self.state,
                "total": self.total,
                "current_index": self.current_index,
                "current_event_id": self.current_event_id,
                "current_started_at": self.current_started_at.isoformat() if self.current_started_at else None,
                "last_cycle_started_at": self.last_cycle_started_at.isoformat() if self.last_cycle_started_at else None,
                "last_cycle_finished_at": self.last_cycle_finished_at.isoformat() if self.last_cycle_finished_at else None,
                "last_error": (
                    {
                        "message": self.last_error.message,
                        "clip_event_id": self.last_error.clip_event_id,
                        "at": self.last_error.at.isoformat(),
                    }
                    if self.last_error
                    else None
                ),
            }


status = WorkerStatus()
