"""
Database engine + session factory. Everything else imports `get_session()`
from here rather than constructing its own engine — one connection pool,
one place to point at Postgres instead of SQLite later (just change
DATABASE_URL; the ORM code above doesn't change).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.utils.logger import get_logger

log = get_logger(__name__)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        database_url = settings.resolve_sqlite_url(settings.secrets.database_url)

        log.info("Creating database engine for {}", database_url)
        _engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
        )
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _SessionLocal


@contextmanager
def get_session() -> Iterator[Session]:
    """
    Usage:
        with get_session() as session:
            session.add(obj)
            session.commit()
    Rolls back automatically if the block raises.
    """
    session = get_session_factory()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
