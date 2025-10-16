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
        table_definition = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='tracked_events'"
        ).scalar_one_or_none()
        ignored_mail_columns = {
            row[1]
            for row in connection.exec_driver_sql(
                "PRAGMA table_info('ignored_mail_imports')"
            ).fetchall()
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
        "mail_error": "ALTER TABLE tracked_events ADD COLUMN mail_error TEXT NULL",
    }

    for column_name, ddl in new_columns.items():
        if column_name in columns:
            continue
        logger.info("Adding %s column to tracked_events table", column_name)
        with engine.begin() as connection:
            connection.exec_driver_sql(ddl)

    needs_status_enum_upgrade = (
        "status" in columns
        and table_definition is not None
        and "failed" not in table_definition.lower()
    )

    if ignored_mail_columns and "max_uid" not in ignored_mail_columns:
        logger.info("Adding max_uid column to ignored_mail_imports table")
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                ALTER TABLE ignored_mail_imports
                ADD COLUMN max_uid INTEGER NULL
                """
            )

    if needs_status_enum_upgrade:
        logger.info(
            "Rebuilding tracked_events table to allow the failed status in enum constraint"
        )
        from .models import TrackedEvent

        tracked_events_table = TrackedEvent.__table__
        column_names = [column.name for column in tracked_events_table.columns]
        quoted_columns = ", ".join(f'"{name}"' for name in column_names)

        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS tracked_events_old")
            connection.exec_driver_sql("ALTER TABLE tracked_events RENAME TO tracked_events_old")
            old_indexes = connection.exec_driver_sql(
                "PRAGMA index_list('tracked_events_old')"
            ).fetchall()
            for index in old_indexes:
                origin = index[3] if len(index) > 3 else None
                if origin != "c":
                    continue
                index_name = index[1]
                connection.exec_driver_sql(f'DROP INDEX IF EXISTS "{index_name}"')
            tracked_events_table.create(bind=connection)
            connection.exec_driver_sql(
                f"INSERT INTO tracked_events ({quoted_columns}) "
                f"SELECT {quoted_columns} FROM tracked_events_old"
            )
            connection.exec_driver_sql("DROP TABLE tracked_events_old")


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
