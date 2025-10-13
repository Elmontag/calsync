"""Database configuration module."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./data/calsync.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

logger = logging.getLogger(__name__)


def apply_schema_upgrades() -> None:
    """Perform lightweight, in-app schema migrations for SQLite deployments."""

    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info('tracked_events')").fetchall()
        }

    if not columns:
        # Table does not exist yet; the regular metadata.create_all call will create it.
        return

    if "response_status" not in columns:
        logger.info("Adding response_status column to tracked_events table")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                ALTER TABLE tracked_events
                ADD COLUMN response_status VARCHAR NOT NULL DEFAULT 'none'
                """
            )


@contextmanager
def session_scope() -> Iterator[sessionmaker]:
    """Provide a transactional scope around a series of operations."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
