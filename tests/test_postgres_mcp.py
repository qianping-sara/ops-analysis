"""Integration tests for postgres MCP tools (requires POSTGRES_URL)."""

import os

import pytest

from claude_agent_platform.mcp import postgres_tools

pytestmark = pytest.mark.skipif(
    not os.environ.get("POSTGRES_URL"),
    reason="POSTGRES_URL not set",
)


@pytest.fixture(autouse=True)
async def _reset_postgres_pool():
    yield
    await postgres_tools.close_pool()


@pytest.mark.asyncio
async def test_list_tables():
    result = await postgres_tools.list_tables()
    assert "tables" in result
    assert isinstance(result["tables"], list)


@pytest.mark.asyncio
async def test_run_query_select_one():
    result = await postgres_tools.run_query("SELECT 1 AS n")
    assert "rows" in result
    assert result["rows"][0]["n"] == 1


@pytest.mark.asyncio
async def test_run_query_rejects_delete():
    result = await postgres_tools.run_query('DELETE FROM "ChatTopicDaily"')
    assert result.get("error") == "SQL_GUARD_REJECTED"
