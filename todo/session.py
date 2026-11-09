"""SQLAlchemy engine wired for Lakebase OAuth tokens.

The password (OAuth token) is short-lived, so a `do_connect` event rewrites it on every
new physical connection. That keeps long-lived pools working across the 1-hour token TTL.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from todo.config import get_settings


@lru_cache(maxsize=1)
def get_engine():
    settings = get_settings()
    engine = create_engine(
        settings.database_url(),
        pool_pre_ping=True,
        pool_recycle=1800,
    )

    @event.listens_for(engine, "do_connect")
    def _refresh_oauth_password(dialect, conn_rec, cargs, cparams):
        # Rewrite the password with a fresh (cached) OAuth token on each connect.
        cparams["password"] = settings.get_password()

    return engine


@lru_cache(maxsize=1)
def _session_factory():
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Session:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
