import asyncpg

from app.config import settings
from app.sql_guard import validate_select_only

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=5,
        command_timeout=10,
    )


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()


async def run_select(sql: str, limit_rows: int = 20) -> list[dict]:
    safe_sql = validate_select_only(sql)
    assert _pool is not None, "DB pool not initialized"
    async with _pool.acquire() as conn:
        rows = await conn.fetch(safe_sql)
    return [dict(r) for r in rows[:limit_rows]]
