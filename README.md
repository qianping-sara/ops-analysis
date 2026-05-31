# Claude Agent Platform

ODI Knowledge AI 多 Agent 平台 — Phase 1：`analysis` Agent（ChatTopicDaily 主题分析）。

## 双库说明

| 变量 | 用途 |
|------|------|
| `DATABASE_URL` | 平台库（chat / message / user） |
| `POSTGRES_URL` | 业务分析库（MCP 只读） |

**开发请使用 UAT 的 `POSTGRES_URL`，勿指向 Prod。**

## 本地启动

```bash
uv sync
# 平台库迁移
psql "$DATABASE_URL" -f src/claude_agent_platform/db/migrations/001_init.sql
uv run uvicorn claude_agent_platform.main:app --reload --port 8000
```

## UAT 测试数据（可选）

```bash
# 仅 UAT — 需 POSTGRES_URL 指向 UAT 且显式确认
uv run python scripts/uat_seed_chat_topic_daily.py --confirm-uat
```

## 联调前端（可选）

与后端解耦的极简对话页，用于测试 New Chat / History / SSE 流式回复：

```bash
# 终端 1
uv run uvicorn claude_agent_platform.main:app --reload --port 8000

# 终端 2
cd tools/dev-chat-ui && npm install && npm run dev
# → http://localhost:5173
```

详见 [tools/dev-chat-ui/README.md](tools/dev-chat-ui/README.md)，API 约定见 [docs/API_SPEC.md](docs/API_SPEC.md)。

## 文档

见 [docs/DESIGN.md](docs/DESIGN.md)
