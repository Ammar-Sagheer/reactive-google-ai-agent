import asyncio

import asyncpg

from app.config import settings
from app.sql_guard import validate_select_only

_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        async with _pool_lock:
            if _pool is None:
                _pool = await asyncpg.create_pool(
                    settings.database_url,
                    min_size=1,
                    max_size=5,
                    command_timeout=10,
                )
    return _pool


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()


async def run_select(sql: str, limit_rows: int = 20) -> list[dict]:
    safe_sql = validate_select_only(sql)
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(safe_sql)
    return [dict(r) for r in rows[:limit_rows]]
