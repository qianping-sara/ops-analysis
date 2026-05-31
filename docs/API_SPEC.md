# Claude Agent Platform — 前端集成 API 规范

> 版本：v1.0（对齐 Phase 1 实现）  
> Base URL 示例：`http://localhost:8000`  
> Phase 1 Agent：`analysis`（ChatTopicDaily 主题分析）

---

## 1. 概述

本服务提供 **REST + SSE** 接口，供「AI Analyst」类前端对接：

| 前端能力 | API |
|----------|-----|
| 左侧会话列表（History） | `GET .../chats` |
| New Chat | `POST .../chats` |
| 选中会话加载历史 | `GET .../chats/{chat_id}/messages` |
| 输入框发送 + 流式回复 | `POST .../chats/{chat_id}/messages`（SSE） |
| 同会话多轮 / 冷恢复续聊 | 同一 `chat_id` 再次 `POST .../messages`（服务端自动处理） |

**冷恢复对前端透明：** 用户点击历史会话 → 拉取 messages 展示 → 再发新消息时，后端根据 `sdk_session_id` / DB 历史自动选择热继续或冷继续，**前端无需额外参数**。

---

## 2. 通用约定

### 2.1 路径前缀

```
/api/v1/agents/{agent_type}/...
```

Phase 1 固定使用：`agent_type = analysis`

### 2.2 鉴权（Phase 1）

**当前未启用鉴权。** 所有请求由服务端映射到固定 dev 用户（`dev@claude-agent.local`）。

> **Phase 2 预留：** 将接入 SSO/JWT，`Authorization: Bearer <token>`，按登录用户隔离 chat。前端可先预留 Header 注入位。

### 2.3 内容类型

| 场景 | Header |
|------|--------|
| JSON 请求 | `Content-Type: application/json` |
| SSE 响应 | `Content-Type: text/event-stream` |

### 2.4 错误响应

| HTTP | 含义 |
|------|------|
| `404` | `agent_type` 不存在，或 `chat_id` 不属于当前用户 |
| `422` | 请求体校验失败 |
| `500` | 服务端未捕获异常 |

404 响应体（FastAPI 默认）：

```json
{ "detail": "Chat not found" }
```

SSE 流内错误见 §5.2 `error` 事件（HTTP 仍为 200，错误在流里）。

### 2.5 ID 与时间

- `chat_id`：UUID 字符串
- 时间字段：ISO 8601 UTC（如 `2026-05-30T15:25:55.035882+00:00`）

### 2.6 CORS

本地联调若前后端不同源，需在后端配置 CORS（当前 Phase 1 未默认开启；部署时按前端域名添加）。

---

## 3. 端点一览

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/v1/agents` | 列出可用 Agent |
| `GET` | `/api/v1/agents/analysis` | Agent 详情 |
| `POST` | `/api/v1/agents/analysis/chats` | 创建会话 |
| `GET` | `/api/v1/agents/analysis/chats` | 会话列表（History） |
| `GET` | `/api/v1/agents/analysis/chats/{chat_id}` | 会话详情 |
| `GET` | `/api/v1/agents/analysis/chats/{chat_id}/messages` | 历史消息 |
| `POST` | `/api/v1/agents/analysis/chats/{chat_id}/messages` | 发送消息（**SSE**） |

交互式文档：`GET /docs`（Swagger UI）

---

## 4. REST API 详情

### 4.1 健康检查

```
GET /health
```

**Response 200**

```json
{
  "status": "ok",
  "platform_db": "ok",
  "redis": "ok"
}
```

---

### 4.2 列出 Agent

```
GET /api/v1/agents
```

**Response 200**

```json
{
  "agents": [
    {
      "id": "analysis",
      "name": "ODI Knowledge AI's Chat Analysis Agent",
      "description": "ChatTopicDaily 主题与会话数据分析（只读）",
      "version": "1.0.0"
    }
  ]
}
```

---

### 4.3 创建会话（New Chat）

```
POST /api/v1/agents/analysis/chats
```

**Request body**

```json
{
  "title": "Last week's hot topic"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `title` | string \| null | 否 | 会话标题；可空，后续可用首条用户消息摘要更新（前端自行处理） |

**Response 201/200**

```json
{
  "id": "79c008f0-feff-4fef-bebe-839cfe5f5370",
  "agent_type": "analysis",
  "title": "Last week's hot topic",
  "sdk_session_id": null,
  "total_input_tokens": 0,
  "total_output_tokens": 0,
  "total_cost_usd": 0.0,
  "created_at": "2026-05-30T15:25:55.035882+00:00",
  "updated_at": "2026-05-30T15:25:55.035882+00:00"
}
```

---

### 4.4 会话列表（History 侧栏）

```
GET /api/v1/agents/analysis/chats
```

按 `updated_at` **降序**，默认最多 **50** 条。

**Response 200**

```json
{
  "chats": [
    {
      "id": "79c008f0-feff-4fef-bebe-839cfe5f5370",
      "agent_type": "analysis",
      "title": "Last week's hot topic",
      "sdk_session_id": "sess_abc123",
      "total_input_tokens": 12000,
      "total_output_tokens": 3500,
      "total_cost_usd": 0.042,
      "created_at": "2026-05-30T15:25:55.035882+00:00",
      "updated_at": "2026-05-30T15:30:12.123456+00:00"
    }
  ]
}
```

**前端建议**

- 侧栏展示 `title`（空则显示首条消息摘要或 "New Chat"）
- 按 `updated_at` 排序（服务端已排好）
- `total_cost_usd` 可用于管理端展示，用户 UI 可选

---

### 4.5 会话详情

```
GET /api/v1/agents/analysis/chats/{chat_id}
```

**Response 200** — 同 §4.3 单条 chat 对象。

**Response 404** — chat 不存在或无权访问。

---

### 4.6 历史消息（选中会话 / 冷恢复展示）

```
GET /api/v1/agents/analysis/chats/{chat_id}/messages
```

返回 **UI 投影后** 的消息列表（非 SDK 原始 payload）。

**Response 200**

```json
{
  "messages": [
    {
      "role": "user",
      "content": "What was last week's hot topic?"
    },
    {
      "role": "assistant",
      "content": "根据 ChatTopicDaily 数据，上周热点议题为…",
      "tools": [
        {
          "name": "mcp__postgres__run_query",
          "input": { "query": "SELECT ..." }
        }
      ]
    },
    {
      "role": "system",
      "content": "已查询数据库",
      "collapsed": true
    }
  ]
}
```

**Message 对象**

| 字段 | 类型 | 说明 |
|------|------|------|
| `role` | `"user"` \| `"assistant"` \| `"system"` | 气泡角色 |
| `content` | string | 展示文本 |
| `tools` | array? | 仅 assistant；本轮调用的工具（可选展开 SQL） |
| `tools[].name` | string | 如 `mcp__postgres__run_query` |
| `tools[].input` | object | 工具输入（SQL 在 `input.query`） |
| `collapsed` | boolean? | `true` 表示折叠的系统提示（tool 中间步骤） |

**不返回的内容**

- SDK `result` / token 统计（在 SSE `usage` 与 chat 级累计）
- 原始 tool result 大 JSON

---

## 5. 发送消息 — SSE 流式

```
POST /api/v1/agents/analysis/chats/{chat_id}/messages
```

**Request body**

```json
{
  "content": "What was last week's hot topic, and how did it change compared to previous weeks?"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `content` | string | 是 | 用户输入，不能为空 |

**Response**

- `Content-Type: text/event-stream`
- 连接保持至本轮 Agent 完成或出错

### 5.1 SSE 格式

每条事件：

```
event: <event_name>
data: <json>

```

`<event_name>` 与 JSON 内 `type` 字段一致。

### 5.2 事件类型

#### `text_delta` — 助手文本增量

```
event: text_delta
data: {"type":"text_delta","content":"根据"}
```

前端：追加到当前 assistant 气泡。

#### `tool_use` — 工具调用开始

```
event: tool_use
data: {"type":"tool_use","tool":"mcp__postgres__run_query","input":{"query":"SELECT COUNT(*) ..."}}
```

前端建议：

- 展示「正在查询数据库…」或折叠展示 SQL
- 常见 `tool` 值：
  - `mcp__postgres__run_query`
  - `mcp__postgres__list_tables`
  - `mcp__postgres__describe_table`
  - `Skill` / `ToolSearch`（Skill 加载，可忽略或显示「加载分析技能…」）

#### `usage` — 本轮 token 统计

```
event: usage
data: {"type":"usage","input_tokens":7,"output_tokens":281,"cache_read_input_tokens":50133,"cache_creation_input_tokens":922,"cost_usd":0.0242154}
```

| 字段 | 说明 |
|------|------|
| `input_tokens` | 输入 token |
| `output_tokens` | 输出 token |
| `cache_read_input_tokens` | Prompt cache 命中 |
| `cache_creation_input_tokens` | Prompt cache 写入 |
| `cost_usd` | 本轮美元成本 |

#### `done` — 本轮结束

```
event: done
data: {"type":"done","chat_id":"79c008f0-feff-4fef-bebe-839cfe5f5370"}
```

前端：标记流结束、允许下一次输入；可选刷新 chat 列表 `updated_at`。

#### `error` — 本轮失败

```
event: error
data: {"type":"error","message":"..."}
```

前端：展示错误、停止 loading；已产生的 `text_delta` 可保留。

### 5.3 典型事件顺序

```
tool_use (Skill/ToolSearch，可选)
tool_use (run_query，可多次)
text_delta (多次)
usage
done
```

首轮可能 **20–90 秒**（Skill + 多轮 SQL + 报告生成）。

### 5.4 前端 SSE 示例（浏览器）

```typescript
async function sendMessage(chatId: string, content: string, onEvent: (e: unknown) => void) {
  const res = await fetch(`/api/v1/agents/analysis/chats/${chatId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });

  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  if (!res.body) throw new Error("No stream body");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      const lines = part.split("\n");
      let eventType = "message";
      let data = "";
      for (const line of lines) {
        if (line.startsWith("event:")) eventType = line.slice(6).trim();
        if (line.startsWith("data:")) data = line.slice(5).trim();
      }
      if (data) onEvent(JSON.parse(data));
    }
  }
}
```

也可使用 `EventSource`：**不适用**于 POST；请用 `fetch` + ReadableStream 或 `@microsoft/fetch-event-source`。

---

## 6. 前端集成流程（对照 UI）

### 6.1 页面初始化

```
GET /api/v1/agents/analysis/chats  →  填充 History 列表
```

### 6.2 New Chat

```
POST /api/v1/agents/analysis/chats  { "title": null }
→ 获得 chat_id
→ 清空右侧消息区
→ 可选：立即聚焦输入框
```

### 6.3 发送第一条 / 后续消息

```
POST .../chats/{chat_id}/messages  { "content": "..." }
→ 本地先插入 user 气泡
→ 创建空 assistant 气泡，监听 text_delta 追加
→ tool_use 时显示 loading / SQL 折叠区
→ usage 可选展示
→ done 后启用输入
```

**同一会话内连续提问：** 复用同一 `chat_id` 重复 POST 即可（服务端 Client 池 + session 恢复）。

### 6.4 点击 History 某条（冷恢复 / 历史查看）

```
GET .../chats/{chat_id}/messages  →  渲染完整历史
```

用户再输入并 POST messages：

- **热继续**（服务未重启、session 仍在）：无感，上下文连贯
- **冷继续**（服务重启等）：后端从 DB 投影最近 N 轮注入，**前端仍只需 POST**，无需额外 API

### 6.5 刷新页面后

1. `GET /chats` 恢复列表  
2. 选中 `chat_id` → `GET /messages` 恢复对话  
3. 继续 `POST /messages` 续聊  

---

## 7. TypeScript 类型（建议）

```typescript
export type AgentType = "analysis";

export interface Chat {
  id: string;
  agent_type: AgentType;
  title: string | null;
  sdk_session_id: string | null;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  created_at: string;
  updated_at: string;
}

export interface UiMessage {
  role: "user" | "assistant" | "system";
  content: string;
  tools?: { name: string; input: Record<string, unknown> }[];
  collapsed?: boolean;
}

export type SseEvent =
  | { type: "text_delta"; content: string }
  | { type: "tool_use"; tool: string; input: Record<string, unknown> }
  | { type: "usage"; input_tokens: number; output_tokens: number; cache_read_input_tokens: number; cache_creation_input_tokens: number; cost_usd: number }
  | { type: "done"; chat_id: string }
  | { type: "error"; message: string };
```

---

## 8. 环境变量（前端联调）

| 变量 | 示例 |
|------|------|
| `VITE_API_BASE_URL` | `http://localhost:8000` |

开发时通过 Vite proxy 转发 `/api` 可避免 CORS：

```typescript
// vite.config.ts
server: {
  proxy: {
    "/api": "http://localhost:8000",
    "/health": "http://localhost:8000",
  },
}
```

---

## 9. 限制与后续

| 项 | Phase 1 | 说明 |
|----|---------|------|
| 鉴权 | 无 | Phase 2 JWT |
| 删除/重命名 chat | 无 | 可后续加 PATCH/DELETE |
| 上传附件 | 无 | 输入框 `+` 暂未对接 |
| 中止生成 | 无 | 可后续加 cancel API |
| `tool_result` SSE | 未实现 | 仅 `tool_use`；结果在 assistant 文本中 |
| 多 Agent | 仅 `analysis` | 路径已预留 `{agent_type}` |

---

## 10. 快速 curl 自测

```bash
# 创建
CHAT=$(curl -s -X POST http://localhost:8000/api/v1/agents/analysis/chats \
  -H 'Content-Type: application/json' -d '{"title":"Demo"}' | jq -r .id)

# 流式提问
curl -N -X POST "http://localhost:8000/api/v1/agents/analysis/chats/$CHAT/messages" \
  -H 'Content-Type: application/json' \
  -d '{"content":"ChatTopicDaily 有多少行？"}'

# 历史
curl -s "http://localhost:8000/api/v1/agents/analysis/chats/$CHAT/messages" | jq
```

---

## 附录：与设计文档差异（以实现为准）

| DESIGN §8.2 | 当前实现 |
|-------------|----------|
| `tool_result` SSE | **未发送** |
| `done.message_id` | **`done.chat_id`** |
| 鉴权 | Phase 1 无，固定 dev 用户 |

完整架构见 [DESIGN.md](./DESIGN.md) §6.6（会话恢复）、§8（API）、§9.4（历史投影）。
