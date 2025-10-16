"""Tests for schema upgrade helpers."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import database


def test_apply_schema_upgrades_upgrades_status_enum(tmp_path) -> None:
    """Old tracked_events tables should accept the new failed status after upgrades."""

    db_path = tmp_path / "upgrade.db"
    test_engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )

    original_engine = database.engine
    original_session_local = database.SessionLocal

    database.engine = test_engine
    database.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    try:
        with test_engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE tracked_events (
                    id INTEGER PRIMARY KEY,
                    uid VARCHAR NOT NULL UNIQUE,
                    mailbox_message_id VARCHAR,
                    source_account_id INTEGER,
                    source_folder VARCHAR,
                    summary VARCHAR,
                    organizer VARCHAR,
                    start DATETIME,
                    "end" DATETIME,
                    status VARCHAR NOT NULL CHECK(status IN ('new','updated','cancelled','synced')),
                    response_status VARCHAR NOT NULL DEFAULT 'none',
                    cancelled_by_organizer BOOLEAN,
                    payload JSON,
                    last_synced DATETIME,
                    history JSON,
                    caldav_etag VARCHAR,
                    local_version INTEGER NOT NULL DEFAULT 0,
                    synced_version INTEGER NOT NULL DEFAULT 0,
                    remote_last_modified DATETIME,
                    local_last_modified DATETIME,
                    last_modified_source VARCHAR,
                    sync_conflict BOOLEAN NOT NULL DEFAULT 0,
                    sync_conflict_reason TEXT,
                    sync_conflict_snapshot JSON,
                    tracking_disabled BOOLEAN NOT NULL DEFAULT 0,
                    mail_error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.exec_driver_sql(
                """
                INSERT INTO tracked_events (id, uid, status, response_status)
                VALUES (1, 'event-1', 'new', 'none')
                """
            )

        database.apply_schema_upgrades()

        with test_engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE tracked_events SET status='failed' WHERE id = 1"
            )
            status = connection.exec_driver_sql(
                "SELECT status FROM tracked_events WHERE id = 1"
            ).scalar_one()

        assert status == "failed"
    finally:
        test_engine.dispose()
        database.engine = original_engine
        database.SessionLocal = original_session_local
