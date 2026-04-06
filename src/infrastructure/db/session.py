from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from src.infrastructure.db.base import Base


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, future=True, echo=False)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(_upgrade_sqlite_schema)


def _upgrade_sqlite_schema(connection: Any) -> None:
    if connection.dialect.name != "sqlite":
        return

    message_event_columns = _table_columns(connection, "message_events")
    add_column_statements: list[str] = []

    if "source_type" not in message_event_columns:
        add_column_statements.append(
            "ALTER TABLE message_events ADD COLUMN source_type VARCHAR(32) NOT NULL DEFAULT 'unknown'"
        )
    if "is_to_bot" not in message_event_columns:
        add_column_statements.append(
            "ALTER TABLE message_events ADD COLUMN is_to_bot BOOLEAN NOT NULL DEFAULT 0"
        )
    if "is_command" not in message_event_columns:
        add_column_statements.append(
            "ALTER TABLE message_events ADD COLUMN is_command BOOLEAN NOT NULL DEFAULT 0"
        )
    if "language_guess" not in message_event_columns:
        add_column_statements.append(
            "ALTER TABLE message_events ADD COLUMN language_guess VARCHAR(16) NOT NULL DEFAULT 'unknown'"
        )
    if "analysis_status" not in message_event_columns:
        add_column_statements.append(
            "ALTER TABLE message_events ADD COLUMN analysis_status VARCHAR(16) NOT NULL DEFAULT 'pending'"
        )
    if "biz_date_local" not in message_event_columns:
        add_column_statements.append(
            "ALTER TABLE message_events ADD COLUMN biz_date_local DATE"
        )

    for statement in add_column_statements:
        connection.exec_driver_sql(statement)

    daily_lesson_columns = _table_columns(connection, "daily_lessons")
    if "theme_key" not in daily_lesson_columns:
        connection.exec_driver_sql(
            "ALTER TABLE daily_lessons ADD COLUMN theme_key VARCHAR(64) NOT NULL DEFAULT ''"
        )
    if "title" not in daily_lesson_columns:
        connection.exec_driver_sql(
            "ALTER TABLE daily_lessons ADD COLUMN title VARCHAR(255) NOT NULL DEFAULT ''"
        )
    if "package_snapshot_json" not in daily_lesson_columns:
        connection.exec_driver_sql(
            "ALTER TABLE daily_lessons ADD COLUMN package_snapshot_json JSON"
        )

    connection.exec_driver_sql(
        "UPDATE message_events SET biz_date_local = date(created_at) WHERE biz_date_local IS NULL"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_message_events_group_user_biz_date "
        "ON message_events (group_id, user_id, biz_date_local)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_conversation_evidences_user_group_biz_type "
        "ON conversation_evidences (user_id, group_id, biz_date, evidence_type)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_daily_target_items_lesson_sort "
        "ON daily_target_items (lesson_id, sort_order)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_review_candidates_user_group_biz "
        "ON review_candidates (user_id, group_id, biz_date)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_daily_learning_snapshots_user_group_biz "
        "ON daily_learning_snapshots (user_id, group_id, biz_date)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_daily_card_snapshots_user_group_biz_type "
        "ON daily_card_snapshots (user_id, group_id, biz_date, card_type)"
    )
    connection.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_message_delivery_logs_group_user_job "
        "ON message_delivery_logs (group_id, user_id, job_name)"
    )


def _table_columns(connection: Any, table_name: str) -> set[str]:
    rows = connection.exec_driver_sql(f"PRAGMA table_info('{table_name}')").fetchall()
    return {row[1] for row in rows}
