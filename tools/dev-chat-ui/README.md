# Dev Chat UI（后端联调页）

与 `src/claude_agent_platform` **完全解耦** 的静态前端，仅通过 [docs/API_SPEC.md](../../docs/API_SPEC.md) 中的 REST + SSE 调用后端，用于本地测试 `analysis` Agent。

## 能力

- **New Chat**：`POST /api/v1/agents/analysis/chats`
- **History 侧栏**：`GET .../chats`
- **加载历史**：`GET .../chats/{id}/messages`
- **流式对话**：`POST .../chats/{id}/messages`（SSE：`text_delta` / `tool_use` / `done` / `error`）

## 启动

**终端 1 — 后端**（项目根目录）：

```bash
uv run uvicorn claude_agent_platform.main:app --reload --port 8000
```

**终端 2 — 本 UI**：

```bash
cd tools/dev-chat-ui
npm install
npm run dev
```

浏览器打开：<http://localhost:5173>

Vite 会把 `/api` 和 `/health` 代理到 `http://127.0.0.1:8000`，**无需**在后端开 CORS。

## 环境变量（可选）

| 变量 | 说明 |
|------|------|
| `VITE_API_PROXY_TARGET` | Vite 代理目标，默认 `http://127.0.0.1:8000` |
| `VITE_API_BASE_URL` | 若设为非空（如 `http://localhost:8000`），浏览器直连后端，需后端配置 CORS |
| `VITE_AGENT_TYPE` | 默认 `analysis` |

示例：代理到远程 UAT

```bash
VITE_API_PROXY_TARGET=https://your-uat-host npm run dev
```

## 与正式前端的关系

- 不打包进 Python 镜像，不参与 `uv sync`
- 可整目录复制到其他仓库，只要 API 路径一致即可
- 生产「AI Analyst」应使用独立前端工程；本目录仅作 **API 冒烟 / 演示**
