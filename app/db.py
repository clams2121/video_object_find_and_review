from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_config


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def _init_engine():
    global _engine, _SessionLocal
    cfg = get_config()
    db_path = Path(cfg.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(
        f"sqlite:///{db_path}",
        # timeout: how long a connection retries before raising "database is
        # locked" instead of failing immediately, so brief overlap between
        # the worker thread and a web request thread writing at the same
        # moment doesn't error out. Not a fix for same-thread nested writes
        # against an uncommitted transaction - that's a deadlock, not
        # contention, and busy_timeout only makes it hang before failing
        # (see logging_utils.attach_db_log_handler for how that's avoided).
        connect_args={"check_same_thread": False, "timeout": 10},
    )

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine():
    if _engine is None:
        _init_engine()
    return _engine


def init_db():
    from app import models  # noqa: F401  (register models on Base)

    engine = get_engine()
    Base.metadata.create_all(engine)
    _migrate_missing_columns(engine)


def _migrate_missing_columns(engine) -> None:
    """create_all only adds missing tables, not missing columns on tables that
    already existed from an older version of this app. Ad-hoc ALTER TABLE for
    the handful of columns added since the schema was first shipped, so
    upgrading in place doesn't require wiping the database."""
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(clips)"))}
        if existing and "error_message" not in existing:
            conn.execute(text("ALTER TABLE clips ADD COLUMN error_message VARCHAR"))
            conn.commit()


@contextmanager
def session_scope():
    global _SessionLocal
    if _SessionLocal is None:
        _init_engine()
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
