"""Postgres MCP tools — business DB (POSTGRES_URL) only."""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from claude_agent_platform.config import get_settings
from claude_agent_platform.guardrails.sql_rules import validate_sql

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            settings.postgres_url,
            min_size=1,
            max_size=5,
            command_timeout=settings.sql_statement_timeout_ms / 1000,
            server_settings={"default_transaction_read_only": "on"},
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def list_tables() -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        )
    tables = [r["tablename"] for r in rows]
    return {"tables": tables, "count": len(tables)}


async def describe_table(name: str) -> dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        cols = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = $1
            ORDER BY ordinal_position
            """,
            name,
        )
    if not cols:
        return {"error": f"Table not found: {name}"}
    return {
        "table": name,
        "columns": [
            {"name": c["column_name"], "type": c["data_type"], "nullable": c["is_nullable"]}
            for c in cols
        ],
    }


async def run_query(query: str) -> dict[str, Any]:
    settings = get_settings()
    result = validate_sql(query, max_rows=settings.sql_max_rows)
    if not result.ok:
        return {"error": "SQL_GUARD_REJECTED", "reason": result.reason}

    sql = result.normalized_sql
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"SET statement_timeout = {settings.sql_statement_timeout_ms}"
        )
        records = await conn.fetch(sql)

    rows = [dict(r) for r in records[: settings.sql_max_rows]]
    truncated = len(records) > settings.sql_max_rows
    payload = {"rows": rows, "row_count": len(rows), "truncated": truncated}
    encoded = json.dumps(payload, default=str)
    if len(encoded) > settings.sql_max_result_bytes:
        # Shrink rows until under byte limit
        while rows and len(json.dumps({"rows": rows}, default=str)) > settings.sql_max_result_bytes:
            rows = rows[: max(1, len(rows) // 2)]
        payload = {
            "rows": rows,
            "row_count": len(rows),
            "truncated": True,
            "note": "Result truncated due to size limit",
        }
    return payload
