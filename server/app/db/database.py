import json
from typing import Any

import asyncpg

from app.core.config import settings
from app.core.state import GraphState

_pool: asyncpg.Pool | None = None


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
