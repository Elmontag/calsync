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

    added_timestamp_column = False

    if "created_at" not in columns:
        logger.info("Adding created_at column to tracked_events table")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                ALTER TABLE tracked_events
                ADD COLUMN created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                """
            )
        added_timestamp_column = True

    if "updated_at" not in columns:
        logger.info("Adding updated_at column to tracked_events table")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                ALTER TABLE tracked_events
                ADD COLUMN updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                """
            )
        added_timestamp_column = True

    if added_timestamp_column:
        logger.info("Backfilling timestamp metadata on existing tracked events")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                UPDATE tracked_events
                SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP),
                    updated_at = COALESCE(updated_at, created_at)
                """
            )

    if "cancelled_by_organizer" not in columns:
        logger.info("Adding cancelled_by_organizer column to tracked_events table")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                ALTER TABLE tracked_events
                ADD COLUMN cancelled_by_organizer BOOLEAN NULL
                """
            )

    new_columns: dict[str, str] = {
        "caldav_etag": "ALTER TABLE tracked_events ADD COLUMN caldav_etag VARCHAR NULL",
        "local_version": "ALTER TABLE tracked_events ADD COLUMN local_version INTEGER NOT NULL DEFAULT 0",
        "synced_version": "ALTER TABLE tracked_events ADD COLUMN synced_version INTEGER NOT NULL DEFAULT 0",
        "remote_last_modified": "ALTER TABLE tracked_events ADD COLUMN remote_last_modified DATETIME NULL",
        "local_last_modified": "ALTER TABLE tracked_events ADD COLUMN local_last_modified DATETIME NULL",
        "last_modified_source": "ALTER TABLE tracked_events ADD COLUMN last_modified_source VARCHAR NULL",
        "sync_conflict": "ALTER TABLE tracked_events ADD COLUMN sync_conflict BOOLEAN NOT NULL DEFAULT 0",
        "sync_conflict_reason": "ALTER TABLE tracked_events ADD COLUMN sync_conflict_reason TEXT NULL",
        "sync_conflict_snapshot": "ALTER TABLE tracked_events ADD COLUMN sync_conflict_snapshot JSON NULL",
        "tracking_disabled": "ALTER TABLE tracked_events ADD COLUMN tracking_disabled BOOLEAN NOT NULL DEFAULT 0",
    }

    for column_name, ddl in new_columns.items():
        if column_name in columns:
            continue
        logger.info("Adding %s column to tracked_events table", column_name)
        with engine.begin() as connection:
            connection.exec_driver_sql(ddl)


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
