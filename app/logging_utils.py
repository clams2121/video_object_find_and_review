from __future__ import annotations

import logging
import logging.handlers
import queue
import sys
from pathlib import Path

from app.config import get_config


def log_file_path() -> Path:
    cfg = get_config()
    return Path(cfg.database_path).resolve().parent / "logs" / "app.log"


_configured = False


def setup_console_and_file_logging() -> None:
    """Console + rotating file handlers. Runs at import time, before the
    database exists, so failures during startup itself are still captured.
    Idempotent: safe to call more than once (e.g. if this module ends up
    imported under two different names), which would otherwise double-attach
    handlers and duplicate every log line."""
    global _configured
    if _configured:
        return
    _configured = True

    log_path = log_file_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    logging.getLogger("app.logging_utils").info("Logging to %s", log_path)


class DBLogHandler(logging.Handler):
    """Persists WARNING+ records from this app's own loggers (name prefix
    'app.') to the worker_events table, so failures show up on the /errors
    page even if nobody is tailing the log file. Never raises - a logging
    failure must not crash the app it's trying to report on."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("app."):
            return
        try:
            from app.db import session_scope
            from app.models import WorkerEvent

            with session_scope() as session:
                session.add(WorkerEvent(level=record.levelname, message=self.format(record)))
        except Exception as exc:
            # The log file handler already has this record; stderr is the
            # last resort so a DB-write failure here isn't invisible too.
            print(f"DBLogHandler failed to persist log record: {exc}", file=sys.stderr)


_log_queue: "queue.Queue" = queue.Queue(-1)
_queue_listener: logging.handlers.QueueListener | None = None
_db_handler_attached = False


def attach_db_log_handler() -> None:
    """Call once the database schema exists (after init_db()). Idempotent.

    The actual DB write happens on a dedicated QueueListener thread, not on
    the thread that logged the record. Pipeline errors are logged from
    inside an already-open, uncommitted DB session (see _process_clip); a
    synchronous write here would open a second SQLite connection wanting the
    same write lock on the same thread's call stack - a guaranteed deadlock,
    not just contention, since the outer transaction can't commit until this
    call returns. Queuing it for another thread avoids that entirely."""
    global _db_handler_attached, _queue_listener
    if _db_handler_attached:
        return
    _db_handler_attached = True

    queue_handler = logging.handlers.QueueHandler(_log_queue)
    queue_handler.setLevel(logging.WARNING)
    logging.getLogger().addHandler(queue_handler)

    _queue_listener = logging.handlers.QueueListener(_log_queue, DBLogHandler(), respect_handler_level=True)
    _queue_listener.start()
