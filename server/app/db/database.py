import json
from datetime import datetime
from typing import Any

import asyncpg

from app.core.config import settings
from app.core.state import GraphState

_pool: asyncpg.Pool | None = None


def _parse_timestamptz(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _database_dsn() -> str:
    database_url = settings.database_url
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return database_url


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=_database_dsn(),
            min_size=1,
            max_size=10,
            timeout=10,
            command_timeout=30,
        )
    return _pool


async def init_db() -> None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS graph_threads (
                thread_id TEXT PRIMARY KEY,
                state JSONB NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS email_audit (
                thread_id TEXT PRIMARY KEY REFERENCES graph_threads(thread_id) ON DELETE CASCADE,
                incoming_sender TEXT,
                incoming_subject TEXT,
                attachment_file_names JSONB NOT NULL DEFAULT '[]'::jsonb,
                attachment_paths JSONB NOT NULL DEFAULT '[]'::jsonb,
                final_decision TEXT,
                human_review_status TEXT,
                validation_results JSONB,
                outgoing_to TEXT,
                outgoing_subject TEXT,
                outgoing_body TEXT,
                delivery TEXT,
                send_status TEXT,
                message_id TEXT,
                sent_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def save_graph_thread_state(thread_id: str, state: GraphState) -> None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO graph_threads (thread_id, state, updated_at)
            VALUES ($1, $2::jsonb, now())
            ON CONFLICT (thread_id)
            DO UPDATE SET state = EXCLUDED.state, updated_at = now()
            """,
            thread_id,
            json.dumps(state),
        )


async def load_graph_thread_state(thread_id: str) -> GraphState | None:
    pool = await get_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT state FROM graph_threads WHERE thread_id = $1",
            thread_id,
        )

    if row is None:
        return None

    state: Any = row["state"]
    if isinstance(state, str):
        state = json.loads(state)

    return state


async def list_graph_thread_states() -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT thread_id, state, updated_at
            FROM graph_threads
            ORDER BY updated_at DESC
            """
        )

    records: list[dict[str, Any]] = []
    for row in rows:
        state: Any = row["state"]
        if isinstance(state, str):
            state = json.loads(state)
        records.append({
            "thread_id": row["thread_id"],
            "state": state,
            "updated_at": row["updated_at"],
        })
    return records


async def save_email_audit_record(
    *,
    thread_id: str,
    incoming_sender: str | None,
    incoming_subject: str | None,
    attachment_file_names: list[str],
    attachment_paths: list[str],
    final_decision: str | None,
    human_review_status: str | None,
    validation_results: list[dict[str, Any]] | None,
    outgoing_to: str | None,
    outgoing_subject: str | None,
    outgoing_body: str | None,
    delivery: str | None,
    send_status: str | None,
    message_id: str | None,
    sent_at: str | datetime | None,
) -> None:
    parsed_sent_at = _parse_timestamptz(sent_at)
    pool = await get_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            """
            INSERT INTO email_audit (
                thread_id,
                incoming_sender,
                incoming_subject,
                attachment_file_names,
                attachment_paths,
                final_decision,
                human_review_status,
                validation_results,
                outgoing_to,
                outgoing_subject,
                outgoing_body,
                delivery,
                send_status,
                message_id,
                sent_at,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4::jsonb, $5::jsonb, $6, $7, $8::jsonb,
                $9, $10, $11, $12, $13, $14, $15::timestamptz, now()
            )
            ON CONFLICT (thread_id)
            DO UPDATE SET
                incoming_sender = EXCLUDED.incoming_sender,
                incoming_subject = EXCLUDED.incoming_subject,
                attachment_file_names = EXCLUDED.attachment_file_names,
                attachment_paths = EXCLUDED.attachment_paths,
                final_decision = EXCLUDED.final_decision,
                human_review_status = EXCLUDED.human_review_status,
                validation_results = EXCLUDED.validation_results,
                outgoing_to = EXCLUDED.outgoing_to,
                outgoing_subject = EXCLUDED.outgoing_subject,
                outgoing_body = EXCLUDED.outgoing_body,
                delivery = EXCLUDED.delivery,
                send_status = EXCLUDED.send_status,
                message_id = EXCLUDED.message_id,
                sent_at = EXCLUDED.sent_at,
                updated_at = now()
            """,
            thread_id,
            incoming_sender,
            incoming_subject,
            json.dumps(attachment_file_names),
            json.dumps(attachment_paths),
            final_decision,
            human_review_status,
            json.dumps(validation_results),
            outgoing_to,
            outgoing_subject,
            outgoing_body,
            delivery,
            send_status,
            message_id,
            parsed_sent_at,
        )
