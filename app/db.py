from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
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
        connect_args={"check_same_thread": False},
    )
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine():
    if _engine is None:
        _init_engine()
    return _engine


def init_db():
    from app import models  # noqa: F401  (register models on Base)

    engine = get_engine()
    Base.metadata.create_all(engine)


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
