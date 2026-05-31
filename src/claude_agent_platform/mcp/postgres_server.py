"""In-process MCP server for postgres + stdio entry for subprocess mode."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool

from claude_agent_platform.mcp import postgres_tools


@tool("list_tables", "List public tables in the analysis database", {})
async def mcp_list_tables(args: dict[str, Any]) -> dict[str, Any]:
    result = await postgres_tools.list_tables()
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}


@tool("describe_table", "Describe columns of a table", {"name": str})
async def mcp_describe_table(args: dict[str, Any]) -> dict[str, Any]:
    result = await postgres_tools.describe_table(args["name"])
    return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}


@tool("run_query", "Run a read-only SELECT query", {"query": str})
async def mcp_run_query(args: dict[str, Any]) -> dict[str, Any]:
    result = await postgres_tools.run_query(args["query"])
    return {"content": [{"type": "text", "text": json.dumps(result, default=str, ensure_ascii=False)}]}


def create_postgres_mcp_server():
    return create_sdk_mcp_server(
        name="postgres",
        version="1.0.0",
        tools=[mcp_list_tables, mcp_describe_table, mcp_run_query],
    )


def build_postgres_mcp_config() -> dict[str, Any]:
    return {"postgres": create_postgres_mcp_server()}


async def _stdio_loop() -> None:
    """Minimal stdio MCP for subprocess invocation (optional)."""
    while True:
        line = await asyncio.get_event_loop().run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        req = json.loads(line)
        method = req.get("method", "")
        req_id = req.get("id")
        if method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [
                        {"name": "list_tables", "description": "List tables"},
                        {"name": "describe_table", "description": "Describe table"},
                        {"name": "run_query", "description": "Run SELECT"},
                    ]
                },
            }
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            arguments = params.get("arguments", {})
            if name == "list_tables":
                out = await postgres_tools.list_tables()
            elif name == "describe_table":
                out = await postgres_tools.describe_table(arguments.get("name", ""))
            elif name == "run_query":
                out = await postgres_tools.run_query(arguments.get("query", ""))
            else:
                out = {"error": f"Unknown tool: {name}"}
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(out, default=str)}]},
            }
        else:
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


def main() -> None:
    asyncio.run(_stdio_loop())


if __name__ == "__main__":
    main()
