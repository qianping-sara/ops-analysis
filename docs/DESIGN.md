# Claude Agent Platform 设计文档

> ODI Knowledge AI 多 Agent 平台 — 基于 Claude Agent SDK 的后台分析与对话服务  
> 版本：v0.9  
> 最后更新：2026-05-30

---

## 1. 背景与目标

### 1.1 背景

ODI Knowledge AI 为销售团队提供知识问答，目前运营端需要对知识库中的对话、用户信息、动作事件、知识覆盖等数据进行后台分析，因此需要构建针对会话分析的Chat Analysis Agent

同时，期望能有统一的agent平台未来支持多种 Agent 能力（分析、问答、标题生成、PPT 等），对接不同前端服务与业务场景。

**当前阶段（Phase 1）** 仅实现 **`analysis` Agent**，首个落地场景为 **ChatTopicDaily 主题分析**（热点议题、漂移、区域/服务线、会话反查等）。架构仍按多 Agent 平台设计，便于后续在同一代码库扩展 `qa` / `title` / `ppt` 等 Profile。

### 1.2 目标

| 目标 | Phase 1 状态 |
|------|----------------|
| **数据分析** | ✅ `analysis`：ReAct + NL2SQL，只读 `POSTGRES_URL` 业务库 |
| **多 Agent 矩阵** | 🔲 架构预留；Phase 1 仅实现 `analysis` Profile |
| **流式对话** | ✅ SSE API，消息持久化至 `DATABASE_URL` |
| **短期记忆** | ✅ 热路径靠 SDK session + auto-compact；冷继续靠 payload 投影 + Redis（§6.6） |
| **云原生部署** | 🔲 Docker → Azure Container Apps（后续） |
| **模型灵活** | ✅ Profile 指定模型；默认 `claude-sonnet-4-6`（Foundry） |
| **Subagent 演进** | 🔲 Profile 字段预留 |

### 1.3 非目标（Phase 1）

- `qa` / `title` / `ppt` Agent 实现
- `generate_chart` Tool / E2B 沙箱
- POC 中的 `topic-daily-query.ts` CLI（可后续移植为 Python Tool；Agent 路径以 MCP SQL + Skill 为主）
- 长期记忆 / 向量检索
- Managed Agents 迁移

---

## 2. 技术选型

| 组件 | 选型 | Phase 1 实例 |
|------|------|----------------|
| 语言 | Python 3.11+ | |
| Agent 运行时 | Claude Agent SDK | 内置 ReAct、MCP、Hooks、Skills |
| LLM | Azure AI Foundry（Claude） | `claude-sonnet-4-6` |
| Web 框架 | FastAPI | SSE Streaming |
| **平台 DB** | PostgreSQL（Neon） | `DATABASE_URL` — chat / message / user |
| **分析目标 DB** | PostgreSQL（Azure） | `POSTGRES_URL` — `odi_knowledge_ai`，MCP 只读 |
| 短期记忆 | Redis（Redis Cloud） | `REDIS_URL` |
| 部署 | Azure Container Apps | 后续 |

### 2.1 双库架构（重要）

```
┌─────────────────────────────────────────────────────────────┐
│  Claude Agent Platform                                         │
├─────────────────────────────┬───────────────────────────────┤
│  DATABASE_URL (Neon)        │  POSTGRES_URL (Azure PG)      │
│  平台自有库                  │  业务库 odi_knowledge_ai       │
│  · platform_users           │  · ChatTopicDaily（主分析表）  │
│  · agent_chats              │  · Chat / Message_v2 / User   │
│  · agent_messages           │  · InternalUser（过滤用）      │
│  读写                        │  MCP 只读 SELECT              │
└─────────────────────────────┴───────────────────────────────┘
         ▲                                    ▲
         │                                    │
    SQLAlchemy                          Postgres MCP
    SessionManager                      (analysis Agent)
    Redis 不存业务数据
```

**原则：** 平台库与业务库**物理隔离**；分析 Agent 通过 MCP 访问业务库，平台层 ORM 只连 `DATABASE_URL`。二者不得混用连接串。

### 2.2 Agent 模式：单 ReAct Agent，不用 Subagent

分析任务为串行 ReAct：理解意图 → 多轮 SQL（JOIN / 窗口对比）→ 语义归并（必要时）→ 报告。主 Agent 在 `max_turns` 内完成即可。Subagent 与 `delegates` 留作 P3+。

---

## 3. 架构总览

### 3.1 分层模型

```
前端（分析后台）
       │ HTTP / SSE
       ▼
/api/v1/agents/analysis/chats/...          ← Phase 1 仅 analysis
       │
Platform：Registry · Runtime · Session · Streaming · Hooks
       │ 装配 analysis Profile
       ▼
agents/analysis/
  profile.yaml · system_prompt.md · skills/topic-daily-analysis/
       │
       ├── Azure Foundry (CLAUDE_AZURE_*)
       ├── POSTGRES_URL  → MCP postgres
       ├── DATABASE_URL  → 平台 ORM
       └── REDIS_URL     → working memory
```

### 3.2 核心设计原则

1. **Profile = 能力单元** — Prompt、Model、Skills、Tools、MCP、Hooks 均通过 Profile 声明。
2. **Platform = 零件库** — Tool / MCP / Hook 注册一次，Profile 白名单启用。
3. **Phase 1 单 Agent、多 Agent 就绪** — Registry 扫描 `agents/` 下全部 Profile；各 Agent 独立 API，是否对接由前端决定。
4. **数据带 `agent_type` 维度** — 为未来多 Agent 预留，避免串台。
5. **POC Skill 迁移** — `docs/topic-daily-analysis/` 作为参考源，落地至 `agents/analysis/skills/`。

### 3.3 analysis Agent 数据流

```
用户问题（例：「最近两周热点议题有哪些？」）
  → 加载 Skill：topic-daily-analysis（schema + SQL few-shot + 过滤惯例）
  → Thought：选工作流（hot / drift / regions / search …）
  → Action：LLM 生成 SQL，调用 mcp__postgres__run_query
  → ★ Guardrails（PreToolUse Hook → MCP 二次校验，见 §4.5）
  → Observation：查询结果（PostToolUse 可截断超大结果）
  → [可选] 多轮 SQL / JOIN Message_v2、Chat
  → [可选] 议题碎片化 → LLM 语义归并（Skill 指引，非重跑打标）
  → Final Answer：中文管理层报告（摘要 / 热点 / 趋势信号 / 方法说明）
```

---

## 4. Phase 1：analysis Agent 详细设计

### 4.1 业务域：ChatTopicDaily 主题分析

源自 POC Skill（`docs/topic-daily-analysis/`），面向 **`odi_knowledge_ai`** 库。

#### 主表

| 表 | 说明 |
|----|------|
| **`ChatTopicDaily`** | 每日会话主题 UPSERT；唯一键 `(analysis_date, chat_id)`；**分析主表** |

#### 核心字段

| 字段 | 用途 |
|------|------|
| `intent_theme` | 8–20 字议题短语；热点、漂移、新兴/消退 |
| `core_summary` | 语义检索、ILIKE、与 theme 交叉验证 |
| `primary_regions` | text[] 区域热度；`unnest` / `@>`；排除 `未提及` |
| `confidence` | 建议过滤 `>= 0.85` |
| `primary_service` | 服务线枚举（辅助） |
| `intent_type` | 意图枚举（辅助） |
| `analysis_date` | 批处理分析日 — **默认趋势分析时间轴** |
| `chat_created_at` | 会话真实创建时间 — 与 Chat 对齐时使用 |
| `chat_id`, `user_id`, `user_email` | 钻取、去重；**PII 脱敏输出** |

#### 关联表

| 表 | JOIN | 用途 |
|----|------|------|
| `Chat` | `chat_id = Chat.id` | title、visibility、createdAt |
| `Message_v2` | `chat_id = Message_v2.chatId` | 完整对话、`parts` JSON |
| `User` | `user_id = User.id` | 用户校验 |
| `InternalUser` | email | **分析时必须排除内部账号** |

#### 分析场景（工作流 → Skill 参考）

| 用户意图 | 方法 | Skill 参考 |
|----------|------|------------|
| 热点 / Top 议题 | 按 `intent_theme` 频次排行 | `references/hot-topics.md` |
| 周月漂移、份额变化 | 窗口对比、`date_trunc` | `references/drift-and-churn.md` |
| 新兴 / 消退主题 | 近窗口 vs 基线窗口 | `references/drift-and-churn.md` |
| 区域热度、服务×区域 | `unnest(primary_regions)`、矩阵 | `references/regions-and-services.md` |
| 反查会话、看 summary | `ILIKE` / 精确 theme / JOIN | `references/drilldown-and-joins.md` |
| 数据覆盖 | COUNT、`min/max(analysis_date)` | SKILL.md `stats` |

#### 过滤惯例（SQL Hook 与 Skill 一致）

```sql
-- 排除内部用户
AND NOT EXISTS (
  SELECT 1 FROM "InternalUser" iu
  WHERE lower(trim(iu.email)) = lower(trim(t.user_email))
)
-- 低置信
AND t.confidence >= 0.85
-- 区域分析排除无地理
AND NOT (t.primary_regions = ARRAY['未提及']::text[])
```

#### 语义归并（Agent 内 LLM 能力，非 SQL）

`intent_theme` 为开放标签，**字面相同才算同一主题**。当用户问「漂移 / 涌现」且 SQL 结果碎片化时：

1. 拉 Top 60–100 `intent_theme` + 样例 `core_summary`
2. LLM 归并成 12–20 个中文语义簇
3. 输出簇趋势 + 成员 theme 附录；反查仍用 ILIKE / search 模式

#### 输出格式（system_prompt + Skill）

- **摘要**（管理层 30 秒版）
- **大家在聊什么**（热点、区域、服务线 + 数字）
- **趋势与信号**（销售管理 / 知识运营视角，谨慎表述）
- **数据与方法**（时间轴、过滤、是否语义归并）
- **建议的下一步**
- PII：`abc***@domain.com`；禁止批量输出 `user_text` 全文

#### 禁止

- `UPDATE` / `INSERT` `ChatTopicDaily`（打标由 Function App 负责）
- 为分析目的重跑全量打标

### 4.2 Profile 配置（Phase 1 定稿）

路径：`agents/analysis/profile.yaml`

```yaml
id: analysis
name: "ODI Knowledge AI's Chat Analysis Agent"
description: "ChatTopicDaily 主题与会话数据分析（只读）"
version: "1.0.0"

# 模型：默认读 CLAUDE_AZURE_FOUNDRY_MODEL，Profile 可覆盖
model: ${CLAUDE_AZURE_FOUNDRY_MODEL}   # 当前：claude-sonnet-4-6
max_turns: 20

invocation_modes:
  - api
delegates: []

skills_dir: skills
setting_sources:
  - project

# MCP 连 POSTGRES_URL（业务库），非 DATABASE_URL
mcp_servers:
  - postgres

allowed_tools:
  - Skill
  - mcp__postgres__list_tables
  - mcp__postgres__describe_table
  - mcp__postgres__run_query
  # generate_chart — Phase 2

hooks:
  custom:
    - sql_validator

guardrails:
  sql:
    max_rows: 10000
    statement_timeout_ms: 30000

memory:
  enabled: true
  ttl_hours: 24
  working_set_turns: 20          # Redis 中保留最近 N 个 user turn 的 memory 视图
  cold_resume_max_turns: 10      # 冷继续时注入的最大 turn 数（见 §6.6.8）
  cold_resume_max_tokens: 32000  # 冷继续注入前缀的 token 预算上限（超出则减少 turn 数）

# Prompt Caching（见 §6.5）
prompt_caching:
  enabled: true
  mode: automatic              # automatic | explicit | off
  ttl: 5m                      # 5m | 1h（Foundry beta 支持情况以实现时为准）
  static_prefix:
    inline_skill_references: true   # 将 references/*.md 并入 system prompt 稳定前缀
```

### 4.3 Skills 落地计划

| 阶段 | 路径 | 说明 |
|------|------|------|
| **参考（保留）** | `docs/topic-daily-analysis/` | POC 原文，不删除 |
| **运行时** | `agents/analysis/skills/topic-daily-analysis/` | 迁移 SKILL.md + `references/` |

迁移时调整 POC 中已过时的路径描述（如 `src/agent/prompts.ts`、`.claude/skills/...`）→ 改为 `agents/analysis/system_prompt.md` + 本 Skill。

**Phase 1 不强制移植** `scripts/topic-daily-query.ts`；Agent 以 MCP SQL 为主。CLI 逻辑可作为 Phase 2 的 `run_topic_daily_query` Tool 参考。

### 4.4 system_prompt 要点

与 POC 分工一致：

| 层 | 文件 | 内容 |
|----|------|------|
| 角色与价值 | `agents/analysis/system_prompt.md` | 销售管理 / 知识运营读者、趋势与商机导向、只读约束 |
| 方法与数据 | Skill + references | 表结构、SQL、过滤、归并、报告骨架 |

### 4.5 SQL Guardrails（生成 → 执行前）

NL2SQL 的风险点在 **LLM 产出 SQL 之后、连接业务库之前**。analysis Agent 采用 **两道硬闸 + 一道软引导**，执行顺序固定：

```
LLM 生成 SQL
    │
    ▼
┌───────────────────────────────────────┐
│ ① PreToolUse Hook: sql_validator      │  ← Agent SDK，tool 调用前拦截
│    matcher: mcp__postgres__run_query  │
└─────────────────┬─────────────────────┘
                  │ deny → 返回 reason 给 LLM，不连 DB
                  │ allow
                  ▼
┌───────────────────────────────────────┐
│ ② MCP postgres_server.run_query       │  ← 进程内二次校验 + 只读连接
│    解析 / 改写 LIMIT / 执行 / 截断结果  │
└─────────────────┬─────────────────────┘
                  ▼
            结果 → LLM（Observation）

软引导（不拦截，仅影响生成质量）：
  Skill 过滤惯例、few-shot、system_prompt 只读约束
```

#### 4.5.1 第一道：`sql_validator`（PreToolUse Hook）

挂载在 analysis Profile 的 `hooks.custom`，**仅匹配** postgres 查数 tool：

```python
HookMatcher(
    matcher="mcp__postgres__run_query",
    hooks=[validate_sql_before_execute],
)
```

从 `input_data["tool_input"]` 取出 `query`（字段名以实现时 MCP schema 为准），校验失败返回 `permissionDecision: "deny"` 及可读 `permissionDecisionReason`，LLM 可据此改写 SQL 重试。

| # | 规则 | 失败处理 |
|---|------|----------|
| G1 | **非空** | deny |
| G2 | **单语句**：不含 `;`（注释剥离后检查） | deny |
| G3 | **语句类型**：解析后根节点仅为 `SELECT` 或 `WITH … SELECT` | deny |
| G4 | **关键字 blocklist**（整词，忽略大小写）：`INSERT` `UPDATE` `DELETE` `DROP` `TRUNCATE` `ALTER` `CREATE` `GRANT` `REVOKE` `COPY` `CALL` `DO` `EXECUTE` `VACUUM` `SET` `RESET` `LOAD` | deny |
| G5 | **危险函数 blocklist**：`pg_sleep` `pg_read_file` `pg_write_file` `lo_import` `lo_export` `dblink` | deny |
| G6 | **LIMIT**：缺 `LIMIT`/`FETCH` 时 Hook **放行**，由 MCP **注入** `LIMIT {max_rows}`；若 `LIMIT n` 且 `n > max_rows`，**改写**为 max_rows 并 log | pass / rewrite |
| G7 | **长度上限**：SQL 字符数 ≤ 32KB | deny |

解析库：`sqlparse`（Phase 1）；误报/漏报多时可换 `pglast`。

Hook 通过时：将规范化 SQL（含注入的 LIMIT）写回 `tool_input`，MCP 直接执行，与 MCP 规则一致。

#### 4.5.2 第二道：`postgres_server`（MCP 内，纵深防御）

MCP **重复校验 G2–G7**（调用共享 `sql_rules.py`），并负责执行层约束：

| # | 规则 | 实现 |
|---|------|------|
| M1 | **readonly session** | `conn.set_session(readonly=True)` |
| M2 | **statement_timeout** | 默认 30s（`SQL_STATEMENT_TIMEOUT_MS`） |
| M3 | **再次解析 + blocklist** | 同 G3–G5 |
| M4 | **LIMIT 注入** | 无 LIMIT 时追加；共用 `SQL_MAX_ROWS`（10000） |
| M5 | **结果集行数** | `fetchmany(max_rows + 1)`，超出则 `truncated: true` |
| M6 | **结果体积** | JSON 序列化 ≤ ~2MB（`SQL_MAX_RESULT_BYTES`） |
| M7 | **search_path** | 固定 schema，禁止 `SET search_path`（G4 已拦） |

#### 4.5.3 执行后：`result_truncator`（PostToolUse，可选）

| 规则 | 默认 |
|------|------|
| 返回 LLM 的 tool result | > 50KB 则摘要 + 「已截断」 |
| `agent_messages.payload` | 仍存 MCP 完整返回 |

#### 4.5.4 与 Skill 层的关系

| 层 | 类型 | 作用 |
|----|------|------|
| Skill / system_prompt | **软** | InternalUser 过滤、confidence 等惯例 |
| `sql_validator` Hook | **硬** | 执行前拦截非法语句 |
| MCP server | **硬** | 二次校验 + 只读连接 + 超时 + 结果上限 |
| DB 只读账号（Prod） | **硬** | 最后一道 |

Skill **不会自动注入** SQL 片段；LLM 漏写 InternalUser 过滤时 Guardrails **不拒绝**（G8 默认关闭）。

#### 4.5.5 可选规则（后续）

| 规则 | 说明 | Phase 1 |
|------|------|---------|
| G8 | 强制含 InternalUser 排除子查询 | 🔲 默认关 |
| G9 | 表 allowlist | 🔲 可选 env 开启 |
| G10 | 限制 `"Message_v2"` 的 `SELECT *` | 🔲 P2 |

#### 4.5.6 拒绝时的行为

- **Hook deny** → `permissionDecisionReason` 回 LLM，**不连 DB**，可改 SQL 重试（计 `max_turns`）
- **MCP reject** → `tool_result.error` + `SQL_GUARD_REJECTED`，同样回到 ReAct

#### 4.5.7 实现文件

```
src/claude_agent_platform/guardrails/sql_rules.py   # 共享规则（Hook + MCP）
src/claude_agent_platform/hooks/sql_validator.py
src/claude_agent_platform/hooks/result_truncator.py   # 可选
src/claude_agent_platform/mcp/postgres_server.py
```

---

## 5. 环境与配置

### 5.1 环境变量契约（项目 `.env`）

> **安全：** 密钥仅放 `.env` / Azure Secrets，勿提交 Git。下文为变量名说明，不含真实值。

```bash
# --- Azure Foundry（Claude）---
CLAUDE_AZURE_API_KEY=<foundry-api-key>
CLAUDE_AZURE_FOUNDRY_ENDPOINT=<foundry-messages-endpoint-url>
CLAUDE_AZURE_FOUNDRY_MODEL=claude-sonnet-4-6

# --- 分析目标 DB（业务库，MCP 只读）---
POSTGRES_URL=postgresql://...@.../odi_knowledge_ai?sslmode=require

# --- 平台自有 DB（chat / message / user）---
DATABASE_URL=postgresql://...@.../neondb?sslmode=require

# --- 平台 Redis（短期记忆）---
REDIS_URL=redis://...

SQL_MAX_ROWS=10000
SQL_STATEMENT_TIMEOUT_MS=30000
SQL_MAX_RESULT_BYTES=2097152

# --- Prompt Caching（可选，默认开启）---
PROMPT_CACHING_ENABLED=true
```

### 5.2 Platform `config.py` 职责

| 变量 | 用途 | 注入目标 |
|------|------|----------|
| `CLAUDE_AZURE_*` | LLM | 启动时映射为 Agent SDK / Foundry 所需配置（含 `CLAUDE_CODE_USE_FOUNDRY=1` 等） |
| `DATABASE_URL` | 平台 ORM | SQLAlchemy async engine |
| `POSTGRES_URL` | 业务分析 | **仅** MCP `postgres` server 的 `env` |
| `REDIS_URL` | 记忆 | SessionManager / RedisStore |
| `PROMPT_CACHING_ENABLED` | 全局缓存开关 | `options_builder` / 网关层（默认 `true`） |

### 5.3 业务库只读与 SQL Guardrails

执行前/执行时 guardrails 完整规格见 **§4.5**。此处仅摘要：

| 层级 | 机制 |
|------|------|
| PreToolUse Hook | `sql_validator`，matcher `mcp__postgres__run_query` |
| MCP Server | `postgres_server` 二次校验 + readonly + timeout + 结果截断 |
| 共享逻辑 | `guardrails/sql_rules.py` |
| DB 账号 | Prod 前换 `POSTGRES_URL` 只读用户（仅改 env） |

### 5.4 MCP Registry

```python
MCP_REGISTRY = {
    "postgres": {
        "type": "stdio",
        "command": "python",
        "args": ["-m", "claude_agent_platform.mcp.postgres_server"],
        "env": {
            # 业务库 — 与平台 DATABASE_URL 严格分离
            "DATABASE_URL": os.environ["POSTGRES_URL"],
        },
    },
}
```

---

## 6. Platform 层设计

（多 Agent 架构不变；Phase 1 仅实例化 `analysis`。）

### 6.1 Agent Registry

```python
class AgentRegistry:
    def register(agent_id: str, profile: AgentProfile): ...
    def get(agent_id: str) -> AgentProfile: ...
    def list_agents() -> list[AgentProfile]: ...

# 启动：扫描 agents/*/profile.yaml，全部注册
# GET /agents 返回已注册列表；未知 agent_type → 404
# Phase 1 目录里只有 analysis/，但机制对所有未来 Agent 通用
```

### 6.2 Tool Registry（Phase 1 最小）

| Tool | Phase |
|------|-------|
| — | Phase 1 无 custom tool，仅 Skill + MCP |
| `generate_chart` | Phase 2 |
| `run_topic_daily_query` | Phase 2 可选（移植 POC CLI） |

### 6.3 Hook Registry

| Hook | 事件 | 说明 |
|------|------|------|
| `sql_validator` | PreToolUse | 见 **§4.5.1** |
| `result_truncator` | PostToolUse | 见 **§4.5.3**，可选 |

### 6.4 Runtime · Session

- `ClaudeSDKClient`：每 `(agent_type, chat_id)` 隔离；`async with` 释放。
- **同一 client 存活时**：直接 `client.query()` 即可多轮，**无需** `resume` 或平台 memory 配置（见 **§6.6.0**）。
- **跨 HTTP 请求 / Pod 重启**：需 `resume=sdk_session_id` 或平台冷继续（见 **§6.6.5–6.6.8**）。

### 6.5 Prompt Caching

分析 Agent 的 system prompt + Skill references（schema、SQL few-shot）体积大且**跨请求高度重复**，适合 Prompt Caching。Microsoft Foundry 对 Claude 支持 **Automatic Caching（beta）**；`claude-sonnet-4-6` 最低可缓存前缀约 **1024 tokens**（本项目的 references 远超此阈值）。

#### 6.5.1 设计目标

| 目标 | 说明 |
|------|------|
| 降本 | 缓存命中 token 约为输入价的 10% |
| 降延迟 | 跳过重算大段 schema / SQL 示例 |
| 多轮对话 | 同一 chat 内 ReAct 多 turn，前缀复用 |
| 多 Agent | 各 Profile 独立静态前缀，互不影响 |

#### 6.5.2 静态前缀 vs 动态后缀

Prompt 按变更频率拆分，缓存收益来自**稳定前缀**：

```
┌─────────────────────────────────────────────────────────┐
│  静态前缀（可缓存）                                        │
│  · tools 定义（MCP postgres tool schema）                 │
│  · system_prompt.md                                     │
│  · topic-daily-analysis references/*.md（inline）         │
│  · Skill 工作流骨架（不含随请求变化的数据）                  │
├─────────────────────────────────────────────────────────┤
│  动态后缀（不缓存 / automatic 模式下随对话增长）            │
│  · 用户消息                                               │
│  · assistant tool_use / tool_result（SQL 结果等）         │
│  · Redis 注入的会话摘要（若有）                            │
└─────────────────────────────────────────────────────────┘
```

**实现要点：** `options_builder.build_system_prompt(profile)` 在启动或 Profile 加载时，若 `prompt_caching.static_prefix.inline_skill_references: true`，将 `agents/analysis/skills/topic-daily-analysis/references/*.md` **拼入 system prompt**，而非依赖首次 `Skill` tool 调用才注入。Skill tool 仍保留，用于工作流路由与后续扩展。

**版本戳：** 静态前缀末尾附加 `<!-- prompt_bundle_version: {hash} -->`（对 references 文件内容 hash）。Skill 更新后 hash 变化，自然失效旧缓存。

#### 6.5.3 缓存模式（Profile + 全局开关）

```yaml
# agents/analysis/profile.yaml
prompt_caching:
  enabled: true
  mode: automatic        # 推荐：多轮 ReAct 对话
  ttl: 5m                # 5m 默认；高频分析台可考虑 1h（成本更高）
  static_prefix:
    inline_skill_references: true
```

| 模式 | 适用 | 说明 |
|------|------|------|
| `automatic` | **默认推荐** | 请求级 `cache_control: {type: ephemeral}`，断点随对话前移 |
| `explicit` | 细粒度控制 | 在 system 块末显式 `cache_control`（SDK/网关支持时） |
| `off` | 调试 | `PROMPT_CACHING_ENABLED=false` 或 Profile 覆盖 |

全局开关 `PROMPT_CACHING_ENABLED` 与 Profile `prompt_caching.enabled` **与**关系。

#### 6.5.4 与 Agent SDK 的集成路径

Claude Agent SDK 通过 bundled CLI 调用 Foundry Messages API，**应用层不直接组 HTTP body**。集成分三阶段：

| 阶段 | 做法 | 优先级 |
|------|------|--------|
| **P1-c** | 静态/动态 prompt 拆分；`build_system_prompt()` inline references | 必做（为缓存做准备，无缓存也受益） |
| **P1-d** | 调研 SDK/CLI 是否暴露 `cache_control` 或已内置 automatic caching；若支持则在 `ClaudeAgentOptions` 传入 | 实现时验证 |
| **P2** | 若 SDK 未暴露：在 Foundry 前加 **LLM Gateway**（透传 `cache_control`）或等待 SDK 升级 | 备选 |

`build_options()` 伪代码：

```python
def build_options(profile: AgentProfile) -> ClaudeAgentOptions:
    system = build_system_prompt(profile)  # 含 inline references + version hash
    opts = ClaudeAgentOptions(
        system_prompt=system,
        ...
    )
    if settings.prompt_caching_enabled and profile.prompt_caching.enabled:
        opts = apply_prompt_caching(opts, profile.prompt_caching)  # mode / ttl
    return opts
```

#### 6.5.5 多 Agent 与多轮会话

| 场景 | 缓存行为 |
|------|----------|
| 不同 `agent_type` | 不同 system prompt + tools → **独立缓存键** |
| 同一 chat 多 turn | automatic 模式：前缀随 messages 增长，断点前移，命中 earlier prefix |
| 新 chat 同 Agent | 静态前缀相同 → **跨 chat 命中**（5m TTL 内） |
| Skill 文件更新 | version hash 变 → 新 cache write |

#### 6.5.6 观测

在 SDK 返回的 `usage`（或 Gateway 日志）中记录：

- `cache_creation_input_tokens`
- `cache_read_input_tokens`

写入 **metrics / 日志**（按 `agent_type` 聚合），用于验证缓存命中率与成本。若两者均为 0，可能是前缀未达最低 token 或 caching 未生效。

#### 6.5.7 注意点

- **勿把 per-request 动态内容放进静态前缀**（时间戳、用户 id 等），否则每次 cache miss。
- Foundry automatic caching 为 **beta**，实现前在目标 endpoint 上做一次验证请求。
- ReAct 每 turn 追加 tool 结果；automatic 模式在 `<20 blocks` 窗口内仍可命中 earlier prefix，极长会话可考虑 explicit 第二断点（P2）。
- Prompt caching **与短期记忆互补**（见 §6.6）：缓存降静态前缀成本；memory 是对 payload 的**按需投影**，非 DB 第二份摘要。

---

### 6.6 短期记忆与会话恢复

#### 6.6.0 SDK 默认多轮与 auto-compact（开箱即用）

Claude Agent SDK **没有**独立的「短期 memory」配置项（Profile 里 `memory:` 是**平台层**配置，见 §6.6.1）。SDK 侧与续聊相关的机制如下：

| SDK 机制 | 配置 | 作用 |
|----------|------|------|
| **同一 `ClaudeSDKClient` 连续 `query()`** | 无（默认行为） | 进程内 session 自动累积历史；简单 demo 多轮对话即此路径 |
| **`resume=session_id`** | `ClaudeAgentOptions(resume=...)` | 新建 client 时从 JSONL session 恢复 full history |
| **`session_store`** | 可选 Redis / Postgres / S3（SDK examples） | 跨 Pod 镜像 session transcript，配合 `resume` |
| **`max_turns`** | 默认 `None`（不限制） | 限制**单次** `query()` 内 ReAct 循环轮数，**不是** chat 总轮数上限 |
| **`AgentDefinition.memory`** | `"user"\|"project"\|"local"` | 加载 CLAUDE.md 设置文件，**与对话历史无关** |
| **auto-compact** | CLI **默认开启**，无需配置 | context 接近模型窗口上限时自动摘要旧历史 |

**默认能聊多久？** 无固定轮数上限，实际上限是**模型 context window**（如 Sonnet ~200K tokens）。每轮叠加 user/assistant 文本及 tool 输入输出；analysis Agent 因 SQL result 较大，更容易触顶。

**auto-compact 行为（CLI 内置，非平台实现）：**

```
对话 token 累积 → 约 80% 起可能警告 → 接近窗口上限（常见 ~95%）触发 auto-compact
              → CLI 将旧消息送模型做通用摘要
              → JSONL 写入 compact_boundary
              → 后续续聊 = 摘要 + 最近消息（非全量 replay）
```

- 也可手动：`client.query("/compact")`；SDK 有 `PreCompact` hook、`compact_boundary` 系统消息（`trigger: manual | auto`）。
- auto-compact 是**通用 LLM 摘要**，可能丢失完整 SQL、大 result、中间步骤；**payload 仍存全量**供前端与排错。
- **与平台 memory 投影分工**：热路径靠 SDK session + auto-compact；平台投影只在 **冷继续**（session 丢失）时使用，且可按 tool 定制压缩策略。

**三档续聊路径：**

```
档 1  同一 client 存活     → client.query()           【零配置，与简单 demo 相同】
档 2  client 重建 + resume  → resume=sdk_session_id    【SDK JSONL / session_store】
档 3  resume 失败          → payload → memory 投影注入  【平台 §6.6.3–6.6.8】
```

`build_options()` 中与 session 相关的伪代码：

```python
def build_options(profile: AgentProfile, chat: AgentChat, *, cold_prefix: str | None) -> ClaudeAgentOptions:
    opts = ClaudeAgentOptions(
        system_prompt=build_system_prompt(profile),
        allowed_tools=profile.allowed_tools,
        ...
    )
    if chat.sdk_session_id and not cold_prefix:
        opts = replace(opts, resume=chat.sdk_session_id)  # 档 2
    elif cold_prefix:
        # 档 3：冷继续前缀拼入首条 user 消息或 initial context（实现时二选一，保持前端不可见）
        ...
    return opts
```

#### 6.6.1 概念：Memory 不是单独存的「摘要」

| | Postgres `payload` | Memory（运行时视图） |
|--|-------------------|---------------------|
| **是什么** | 每条 SDK 消息的**全量**存档 | 从 payload **按需投影**、给 Agent 续聊用的**压缩上下文** |
| **何时写** | 每条 yield 实时写入 | turn 结束时由 projector **计算**（或冷读时现算） |
| **是否落库** | ✅ 唯一 transcript 表 | ❌ 不单独建列；可选缓存于 Redis |
| **谁看** | 前端历史、排错 | SDK 冷继续、Redis working set |

**Thin 的正确含义：** 不是「再写一份摘要字段」，而是 **memory 里对 tool/MCP/Skill 只保留「调了什么 + 最终结果」**，过程细节（中间 SQL 尝试、describe 步骤、大段 result 原文）不进入 memory。

热继续时 SDK Session 自带完整 ReAct 上下文，**不需要**平台投影；长会话 token 由 CLI **auto-compact** 在 session 内处理（§6.6.0）。平台 memory 投影主要用于 **Redis 缓存** 与 **冷继续**（§6.6.8）。

#### 6.6.2 四层职责（修订）

```
┌─────────────────────────────────────────────────────────────────┐
│ ① SDK Session（热继续 / 档 1–2）                                  │
│    同一 client 或 resume 成功 → full history                      │
│    过长时 CLI auto-compact（通用摘要），非平台 memory 投影         │
├─────────────────────────────────────────────────────────────────┤
│ ② Postgres agent_messages.payload                               │
│    全量 msg；历史 API / 排错 / memory 投影的**唯一数据源**         │
├─────────────────────────────────────────────────────────────────┤
│ ③ Redis working_set（可选，TTL）                                 │
│    最近 N turn 的 **memory 视图**（由 payload 投影得到，可重建）   │
├─────────────────────────────────────────────────────────────────┤
│ ④ 平台冷继续注入（档 3）                                          │
│    仅最近 cold_resume_max_turns 个 frame + token 预算（§6.6.8）  │
└─────────────────────────────────────────────────────────────────┘
```

#### 6.6.3 Memory 投影：按 Tool / MCP / Skill 定制

`MemoryProjectorRegistry`：按 `tool_name` / `skill_name` 注册投影器；**写入 payload 时不调用**，在 **turn 结束**或**冷继续读库**时对一组 payload 做 **Turn 级 compaction**。

**Turn 级 compaction 原则（一个 user 消息 → 一个 ResultMessage）：**

| 保留 | 丢弃或压缩 |
|------|------------|
| 用户原话 | — |
| 该 turn **最终** assistant 文本（合并多个 TextBlock） | 中间「我去查一下…」等过渡句（可选保留最后一段） |
| 每个 tool：**工具名 + memory 化结果** | tool 输入全文、多轮重试的中间失败、冗长 result |

**分工具 memory 策略（analysis Agent Phase 1）：**

| Tool / 事件 | Memory 中保留 | 不进入 memory |
|-------------|---------------|---------------|
| `mcp__postgres__run_query` | `tool`、压缩 SQL 意图（如「查 14 天热点 Top30」或 sql 前 120 字）、`row_count`、`truncated`、**聚合结论**（若 assistant 已解读则引用其一句） | 完整 SQL、完整 result 行集 |
| `mcp__postgres__describe_table` | `「已查看表 {name} 结构」` | 列定义明细 |
| `mcp__postgres__list_tables` | 表数量或表名列表（≤20） | — |
| `Skill`（topic-daily-analysis 等） | `「已加载 Skill: {name}」` | Skill 正文 / references |
| User / Assistant 文本 | 原文（assistant 单条 ≤2KB） | — |
| 失败 tool | 一行 `「{tool} 失败: {reason}」` | 完整 stack |

投影器接口示意：

```python
class MemoryProjector(Protocol):
    def project_tool_use(self, tool_name: str, tool_input: dict) -> dict: ...
    def project_tool_result(self, tool_name: str, tool_input: dict, tool_output: str | dict) -> dict: ...

# 注册
registry.register("mcp__postgres__run_query", PostgresQueryMemoryProjector())
registry.register("Skill", SkillMemoryProjector())
registry.register_default(DefaultToolMemoryProjector())  # 兜底：tool 名 + 输出前 200 字
```

**与 §4.5.3 `result_truncator` 的关系：**

| | result_truncator | Memory projector |
|--|------------------|------------------|
| 时机 | **当次** tool 返回给 LLM 的 observation | **跨 turn** 续聊上下文 |
| 目的 | 控制当前 ReAct 循环 token | 控制冷继续 / working set token |
| 实现 | 可**复用同一套** `MemoryProjectorRegistry` | 同上 |

同一条 tool result：payload 存全量 → 给 LLM 的 observation 用 truncator → turn 结束写入 Redis 的 memory frame 再用 projector。

#### 6.6.4 Memory frame 结构（Redis / 冷继续用）

每个 **user turn** 一个 frame（在 `ResultMessage` 后生成）：

```json
{
  "turn_index": 3,
  "user": "区域维度再细化一下",
  "assistant_final": "新加坡、越南会话量最高…",
  "tools": [
    {
      "tool": "mcp__postgres__run_query",
      "memory": {
        "intent": "14天区域 unnest 统计",
        "row_count": 12,
        "truncated": false
      }
    }
  ]
}
```

注意：`tools[]` 是 **compaction 后的清单**，不是 replay 每条 assistant/tool_use/user(tool_result) payload。

Redis Key：`{agent_type}:{chat_id}:working_set`（JSON array of frames）、`:meta`（sdk_session_id、turn_count）。TTL = `memory.ttl_hours`。miss 时从 Postgres 加载最近 N turn 的 **payload 序列**，重新跑 `TurnMemoryCompactor`。

#### 6.6.5 继续对话：热继续 vs 冷继续

```
POST .../chats/{chat_id}/messages
        │
        ▼
   内存中该 chat 的 ClaudeSDKClient 仍存活？
        │
   是 ──► client.query(用户消息)     【档 1：与简单 demo 相同】
        │
   否 ──► 新建 client
        │
        ▼
   SDK resume(sdk_session_id) 成功？
        │
   是 ──► client.query(用户消息)     【档 2：SDK full history + 必要时 auto-compact】
        │
   否（Pod 重启 / JSONL 丢失 / session_store 不可用）
        │
        ▼
   从 Postgres 读最近 cold_resume_max_turns 的 payload
        │
        ▼
   TurnMemoryCompactor + MemoryProjectorRegistry → memory frames
        │（或 Redis working_set 若命中且 seq 连续）
        ▼
   ContextBuilder：frames → 文本，并应用 cold_resume_max_tokens 预算（§6.6.8）
        │
        ▼
   新 SDK session + 注入冷继续前缀 + 当前用户消息，更新 sdk_session_id
```

**冷继续注入**（不展示给前端）— 由 **memory frames** 渲染，非 LLM 另写摘要：

```text
【会话续接 - 此前轮次】
Turn 1
  用户: 最近两周热点？
  工具: run_query → 25 行，意图=热点 intent_theme 统计
  助手: Top 议题为 …
Turn 2
  …
【当前消息】
{user_message}
```

**不**逐条 replay 全量 payload；**不**在 DB 预存上述文本。

#### 6.6.6 与 `GET .../messages` 的关系

| 场景 | 数据来源 | 形态 |
|------|----------|------|
| 用户浏览历史 | Postgres `payload` | **Full**（MessagePresenter，tool 可展开） |
| Agent 档 1–2（client / resume） | SDK Session | **Full**（SDK 内；过长时 CLI **auto-compact**） |
| Agent 档 3 冷继续 / Redis | payload → memory 投影 | **最近 N turn + token 预算**（§6.6.8） |

#### 6.6.7 实现模块

```
src/claude_agent_platform/memory/
  session_manager.py       # 热/冷分支
  redis_store.py           # meta + working_set(frames)
  turn_memory_compactor.py # 单 turn 多条 payload → 一个 frame
  projectors/
    registry.py
    postgres_query.py
    postgres_meta.py       # describe / list_tables
    skill.py
    default.py
  context_builder.py     # frames[] → 冷继续文本；cold_resume_max_tokens 预算裁剪
```

Profile 可扩展：`memory.projectors` 列出启用的投影器；新增 MCP/Tool 时 **加投影器**，而非改通用摘要逻辑。

#### 6.6.8 长会话冷恢复：策略与 Phase 1 是否足够

**问题：** chat 在 DB 里可能有几十、上百轮 user turn；Pod 重启后 resume 失败，平台只能冷注入。如何处理「很长」的历史？

**Phase 1 策略（有意截断 + 结构化压缩，非全量 replay）：**

| 步骤 | 行为 |
|------|------|
| 1. 只取最近 N turn | `cold_resume_max_turns`（默认 10）；**更早的 turn 不注入 Agent** |
| 2. 每 turn 做投影 | `TurnMemoryCompactor` + `MemoryProjectorRegistry`（§6.6.3），非 replay 原始 payload |
| 3. Token 预算 | `ContextBuilder` 渲染后若超过 `cold_resume_max_tokens`（默认 32K），**从最早 frame 起递减**直至 fit |
| 4. 用户可见历史 | `GET .../messages` 仍返回 **Postgres 全量 payload**，与 Agent 上下文解耦 |

**示例：** chat 共 80 轮，冷继续时 Agent 仅「看到」最近 10 轮的压缩 frame（约数千～2 万 tokens），而非 80 轮全量 SQL result。

**为何 Phase 1 足够（analysis Agent）：**

| 考量 | 说明 |
|------|------|
| 业务可重查 | 分析结论依赖 DB 数据；旧 turn 的细节可通过 **重新 run_query** 恢复，不必把 80 轮 SQL 结果塞进 context |
| 热路径不受影响 | 同一 Pod、client 存活或 `resume` 成功时，走 SDK **full history + auto-compact**，与简单 demo 一致 |
| 前端不受影响 | 用户滚动历史仍看全量；仅 **Agent 续聊上下文**被截断 |
| 10 turn 窗口 | 对「接着刚才的分析改口径」类追问通常够用；analysis 对话多为短链式 refinement |
| Token 双保险 | turn 数上限 + `cold_resume_max_tokens`，避免 10 轮里每轮 assistant 2KB + 多 tool 仍撑爆 context |

**已知局限（接受或 P2 增强）：**

| 局限 | 影响 | 缓解 |
|------|------|------|
| 冷继续后 Agent **不记得** N turn 之前的细节 | 用户说「回到第 5 轮那个区域结论」可能答不准 | 用户可粘贴原文；或 P2 加 `chat_rollup_summary` |
| 冷继续 **无法复现** SDK auto-compact 后的摘要链 | 与 IDE 里 resume JSONL 行为不完全一致 | P2 可选 `session_store` 镜像到 Redis，提高档 2 命中率 |
| 极长单 turn（一次 query 内大量 tool） | 1 个 frame 仍可能偏大 | `assistant_final` 2KB  cap + tool projector；仍超预算则只保留 user + assistant_final，drop tools 明细 |

**P2 可选增强（非 Phase 1 阻塞）：**

1. **`chat_rollup_summary`**：每 N turn 或 token 超阈值时，用 LLM 将**更早** turn 的 frames 滚成一段固定摘要，冷继续时注入 `【更早会话摘要】` + 最近 N frames。
2. **`session_store=RedisSessionStore`**：跨 Pod 档 2 resume，减少落入档 3 的概率。
3. **Profile 按场景调参**：`cold_resume_max_turns` / `cold_resume_max_tokens` per Agent（qa 可能需要更大窗口）。
4. **检测 payload 中的 `compact_boundary`**：若曾持久化 SDK 压缩事件，冷继续可优先用「边界后摘要 + 最近 frames」，更接近热路径语义（实现复杂度较高，P2）。

**结论：** Phase 1 **足够**支撑 analysis MVP——冷恢复是**有损但可控**的续聊，不是完整时间旅行；全量真相在 DB，Agent 侧只带「最近若干轮的决策摘要」。若上线后冷继续丢上下文成为高频投诉，优先加 **rollup summary** 或 **session_store**，而非无限增大 `cold_resume_max_turns`（会导致 token 与成本失控）。

---

## 7. 隔离设计

（与 v0.1 一致；Phase 1 仅 `agent_type=analysis` 有流量，但表结构与 Key 规范仍按多 Agent 设计。）

| 维度 | Phase 1 实际 | 隔离手段 |
|------|----------------|----------|
| 业务 DB vs 平台 DB | 两连接串 | MCP 只用 `POSTGRES_URL`；ORM 只用 `DATABASE_URL` |
| Skills | `agents/analysis/skills/` | Profile `cwd` |
| Redis | 单实例 | `analysis:{chat_id}:*` 前缀 |

---

## 8. API 设计

### 8.1 路由

Phase 1 对外主要使用（**所有 chat 操作按当前登录用户隔离**）：

```
GET  /api/v1/agents
GET  /api/v1/agents/analysis

POST /api/v1/agents/analysis/chats              # body 可选 title；user 来自鉴权
GET  /api/v1/agents/analysis/chats              # 当前用户的会话列表
GET  /api/v1/agents/analysis/chats/{chat_id}    # 校验 chat.user_id == 当前用户
POST /api/v1/agents/analysis/chats/{chat_id}/messages    # SSE
GET  /api/v1/agents/analysis/chats/{chat_id}/messages   # 历史（见 §9.4 投影）
```

鉴权上下文解析为 `platform_users.id`（见 §9.1）。`GET/POST .../chats/{id}` 必须校验 `(agent_type, chat_id, user_id)` 三元组，否则 404。未在 Registry 注册的 `agent_type` 亦返回 404。

### 8.2 SSE 事件

```json
{"type": "text_delta", "content": "..."}
{"type": "tool_use", "tool": "mcp__postgres__run_query", "input": {"query": "..."}}
{"type": "tool_result", "summary": "返回 25 行"}
{"type": "usage", "input_tokens": 1200, "output_tokens": 450, "cache_read_input_tokens": 8000, "cost_usd": 0.012}
{"type": "done", "message_id": "uuid"}
{"type": "error", "message": "..."}
```

`usage` 在当轮 `ResultMessage` 到达后发送（见 §9.5）。

---

## 9. 数据模型（平台库 `DATABASE_URL`）

> **与业务库 `"User"` 区分：** 平台 `platform_users` 是**使用分析 Agent 的内部用户**（销售管理、知识运营等）；`POSTGRES_URL` 里的 `"User"` 是 ODKnowledge 产品终端用户，二者不混用、不 FK。

### 9.1 ER 关系

```
platform_users (1) ──< (N) agent_chats (1) ──< (N) agent_messages
```

| 表 | 职责 |
|----|------|
| `platform_users` | 平台登录用户主数据 |
| `agent_chats` | 某用户 × 某 Agent 类型的一条会话 |
| `agent_messages` | SDK 消息流持久化（见 §9.3） |

### 9.2 DDL

```sql
-- 平台用户（多 user 支持）
CREATE TABLE platform_users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    department  TEXT,
    entity      TEXT,                    -- 法人实体 / 业务单元
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_platform_users_entity ON platform_users(entity);

-- 会话：去掉 status / metadata / source_service（YAGNI）
CREATE TABLE agent_chats (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES platform_users(id) ON DELETE CASCADE,
    agent_type      TEXT NOT NULL,       -- 'analysis' | 'qa' | ...
    title           TEXT,
    sdk_session_id  TEXT,                -- Claude SDK session，用于 resume
    -- 用量累计（每次 ResultMessage 后增量更新，见 §9.5）
    total_input_tokens              BIGINT NOT NULL DEFAULT 0,
    total_output_tokens             BIGINT NOT NULL DEFAULT 0,
    total_cache_read_input_tokens   BIGINT NOT NULL DEFAULT 0,
    total_cache_creation_input_tokens BIGINT NOT NULL DEFAULT 0,
    total_cost_usd                  NUMERIC(12, 6) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent_chats_user_agent ON agent_chats(user_id, agent_type, updated_at DESC);

-- 消息：对齐 SDK 流，不按 OpenAI 风格拆列
CREATE TABLE agent_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id         UUID NOT NULL REFERENCES agent_chats(id) ON DELETE CASCADE,
    seq             INT NOT NULL,        -- 会话内单调递增，保证顺序
    sdk_type        TEXT NOT NULL,       -- user | assistant | system | result
    payload         JSONB NOT NULL,      -- SDK 全量（见 §9.3）；memory 由 payload 投影，无单独摘要列
    -- 仅 sdk_type='result' 时填充（来自 ResultMessage.usage）
    turn_input_tokens               INT,
    turn_output_tokens              INT,
    turn_cache_read_input_tokens    INT,
    turn_cache_creation_input_tokens INT,
    turn_cost_usd                   NUMERIC(12, 6),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chat_id, seq)
);

CREATE INDEX idx_agent_messages_chat_seq ON agent_messages(chat_id, seq);
```

**`agent_chats` 为何去掉 `status` / `metadata`？**

- 会话是否「进行中」由是否存在未结束的 SSE / 最近 `updated_at` 推断即可。
- 扩展字段需要时再加列或单独关联表，避免空 JSONB 占位。

### 9.3 消息持久化：对齐 Claude Agent SDK

SDK 在 `client.receive_response()` 中 yield **多种类型**，而非单一 `messages[]` 里每条的 `{role, content, tool_calls}`：

| SDK 类型 | 典型内容 | 是否默认持久化 |
|----------|----------|----------------|
| `SystemMessage` | `session_id`、init | 可选（调试用）；至少把 `session_id` 写入 `agent_chats.sdk_session_id` |
| `UserMessage` | 用户文本，或 `ToolResultBlock[]` | ✅ |
| `AssistantMessage` | `TextBlock` + `ToolUseBlock` 混在同一 message | ✅ |
| `ResultMessage` | `usage`、`total_cost_usd`、`result`、turn 结束 | ✅（并更新 chat 累计用量） |

**因此不再使用** `content` / `tool_calls` / `tool_results` **分列**——那是 OpenAI Chat Completions 形状，与 SDK 不一致，且无法完整还原一条 `AssistantMessage`（text 与 tool_use 在同一条里）。

**做法：一行 = SDK 一次 yield**，整包进 `payload`：

```python
# 伪代码：runtime 持久化（仅 payload；memory 在 turn 结束时投影）
seq = await repo.next_seq(chat_id)
await repo.insert_message(
    chat_id=chat_id,
    seq=seq,
    sdk_type=...,
    payload=serialize_sdk_message(message),
)

if isinstance(message, ResultMessage):
    await repo.apply_turn_usage(...)
    await repo.update_sdk_session_id(...)
    turn_payloads = await repo.get_turn_payloads(chat_id, this_turn)
    frame = turn_memory_compactor.compact(turn_payloads, registry)
    await redis_store.append_working_set(chat_id, agent_type, frame)
```

`payload` 示例（assistant，含 tool use）：

```json
{
  "type": "assistant",
  "content": [
    {"type": "text", "text": "我先查最近两周热点…"},
    {"type": "tool_use", "id": "toolu_01", "name": "mcp__postgres__run_query", "input": {"query": "SELECT ..."}}
  ],
  "parent_tool_use_id": null
}
```

`payload` 示例（user，tool result）：

```json
{
  "type": "user",
  "content": [
    {"type": "tool_result", "tool_use_id": "toolu_01", "content": "[{\"intent_theme\":\"...\"}]"}
  ]
}
```

**继续对话（热 / 冷）：** 见 **§6.6.5**。DB 仅存全量 `payload`；冷继续时对 payload 做 **按 tool 定制的 memory 投影**，不 replay 全量 msg。

### 9.4 对前端的「历史消息」投影

前端通常不需要 raw SDK 流。`GET .../messages` 由平台层 **投影**：

| 投影规则 | 说明 |
|----------|------|
| 合并连续 `AssistantMessage` 的 `TextBlock` | 展示 assistant 气泡 |
| `UserMessage` 仅含 `tool_result` | 默认**不展示**（或折叠为「已查询数据库」） |
| 用户输入的 `UserMessage` | 展示 user 气泡 |
| `ResultMessage` | 不展示；用量已在 chat 级累计 |

投影逻辑放 `MessagePresenter`，不强迫 DB 表结构迁就 UI。

### 9.5 Token 与成本统计

#### 需要额外的 token 统计 library 吗？

**不需要。** 不要用 tiktoken / 自算 tokenizer 去估算。

Token 与费用由 **Claude Agent SDK 在每轮结束时通过 `ResultMessage` 直接返回**——SDK 内部 CLI 已调用 Foundry Messages API，usage 来自 API 响应，平台层只做**读取 + 落库**。

| 方式 | 是否采用 |
|------|----------|
| `tiktoken` / 自算 prompt 长度 | ❌ 不准，且与账单不一致 |
| 解析 SSE 流自己累加 | ❌ 流式 chunk 不含 usage |
| **`ResultMessage.usage` + `total_cost_usd`** | ✅ SDK 内置，唯一来源 |

#### 平台代码怎么接（完整一轮）

```python
from claude_agent_sdk import (
    ClaudeSDKClient,
    AssistantMessage,
    ResultMessage,
    TextBlock,
)

async def run_one_turn(client: ClaudeSDKClient, chat_id: str, user_text: str):
    await client.query(user_text)

    async for message in client.receive_response():
        # 1. 照常持久化每条 SDK 消息 → agent_messages
        await persist_sdk_message(chat_id, message)

        # 2. 推 SSE 给前端
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    yield sse_text_delta(block.text)

        # 3. 一轮结束：SDK 抛出 ResultMessage，这里统计 token
        if isinstance(message, ResultMessage):
            await apply_turn_usage(chat_id, message)   # 写 DB
            yield sse_usage(message)                   # 通知前端
            # message.result 为本轮最终文本摘要（可选展示）
```

`ResultMessage` 是 SDK 类型（`claude_agent_sdk.types.ResultMessage`），关键字段：

```python
@dataclass
class ResultMessage:
    subtype: str
    duration_ms: int
    num_turns: int
    session_id: str
    total_cost_usd: float | None = None      # SDK 算好的美元成本
    usage: dict[str, Any] | None = None        # API usage 对象
    model_usage: dict[str, Any] | None = None  # 按 model 拆分（如有）
    result: str | None = None                  # 本轮 agent 最终输出
    is_error: bool
```

`usage` 字典常见键（以 Foundry/API 实际返回为准，用 `.get()` 防御性读取）：

```python
usage.get("input_tokens")
usage.get("output_tokens")
usage.get("cache_read_input_tokens")
usage.get("cache_creation_input_tokens")
```

#### 统计策略（三层落库）

| 层级 | 写入时机 | 存储位置 |
|------|----------|----------|
| **Turn** | 每个 `ResultMessage` | `agent_messages` 上 `turn_*` 列（该行的 `sdk_type='result'`） |
| **Chat** | 同上，事务内累加 | `agent_chats.total_*` |
| **User** | 查询时 `SUM(agent_chats.total_*)` | 暂不单独建表；需要账单报表时再加日汇总表 |

```python
async def apply_turn_usage(chat_id: UUID, result_msg: ResultMessage) -> None:
    u = result_msg.usage or {}
    await repo.update_message_turn_stats(
        chat_id=chat_id,
        input_tokens=u.get("input_tokens", 0),
        output_tokens=u.get("output_tokens", 0),
        cache_read=u.get("cache_read_input_tokens", 0),
        cache_creation=u.get("cache_creation_input_tokens", 0),
        cost_usd=result_msg.total_cost_usd or 0,
    )
    await repo.increment_chat_totals(chat_id, u, result_msg.total_cost_usd)
```

#### 注意

- **一轮用户消息** → `query()` + `receive_response()` 直到 **`ResultMessage`** = 一次 turn 计量。ReAct 里多次 tool call 仍算**同一 turn**，usage 是该 turn 的合计（SDK/CLI 汇总）。
- SSE 的 `text_delta` **没有** token 数；等 `ResultMessage` 后再发 `usage` 事件。
- 若 `total_cost_usd` 为空，仍存 token；费用可后续按 Foundry 价目补算。
- Prompt caching 是否命中：看 `cache_read_input_tokens > 0`（见 §6.5）。

---

### 9.6 用户与 Chat 的 API 约束

```python
# 创建 chat
chat = await chat_repo.create(user_id=current_user.id, agent_type="analysis", title=...)

# 列表：仅当前用户
chats = await chat_repo.list(user_id=current_user.id, agent_type="analysis")

# 发消息：三重校验
chat = await chat_repo.get(chat_id)
if chat.user_id != current_user.id or chat.agent_type != "analysis":
    raise HTTPException(404)
```

`platform_users` 可在首次鉴权登录时 **upsert**（email 来自 JWT / SSO），`department` / `entity` 由 IdP 同步或管理端维护。

---

## 10. 项目结构（Phase 1 目标）

```
odi-ops-analysis/
├── .env                          # 本地密钥（不提交）
├── .env.example                  # 变量名模板
├── pyproject.toml
├── Dockerfile
├── docs/
│   ├── DESIGN.md
│   └── topic-daily-analysis/     # POC 参考（保留）
│
├── agents/
│   └── analysis/                 # Phase 1 唯一实现
│       ├── profile.yaml
│       ├── system_prompt.md
│       └── skills/
│           └── topic-daily-analysis/
│               ├── SKILL.md
│               └── references/
│                   ├── schema-and-dimensions.md
│                   ├── hot-topics.md
│                   ├── drift-and-churn.md
│                   ├── regions-and-services.md
│                   └── drilldown-and-joins.md
│
└── src/claude_agent_platform/
    ├── main.py
    ├── config.py                 # 读取 CLAUDE_AZURE_* / DATABASE_URL / POSTGRES_URL / REDIS_URL
    ├── core/
    ├── hooks/
    │   ├── sql_validator.py
    │   └── result_truncator.py
    ├── guardrails/
    │   └── sql_rules.py
    ├── mcp/
    │   └── postgres_server.py    # env: POSTGRES_URL
    ├── memory/
    │   ├── session_manager.py
    │   ├── redis_store.py
    │   ├── turn_memory_compactor.py
    │   ├── projectors/
    │   └── context_builder.py
    ├── db/
    └── api/
        └── routes/
            └── agents.py
```

`agents/qa/`、`agents/title/` 等 **Phase 1 不创建**；Registry 支持未来直接添加。

---

## 11. 安全

### 11.1 Phase 1 Checklist

- [ ] §4.5 SQL Guardrails：`sql_rules.py` + `sql_validator` Hook + MCP 二次校验
- [ ] Skill + Hook 内置 InternalUser 过滤（Agent 层双保险）
- [ ] 报告与持久化数据按 Skill PII 规则脱敏（如 `user_email`）
- [ ] `.env` 加入 `.gitignore`；生产用 Azure Container Apps Secrets
- [ ] `max_turns: 20`
- [ ] `build_system_prompt()` 静态/动态拆分，为 Prompt Caching 做准备

### 11.2 Prod 前 Checklist（仅改 env，不改代码）

- [ ] `POSTGRES_URL` 换只读 DB 用户（替换连接串即可）
- [ ] 验证 Foundry Prompt Caching 命中率与 `PROMPT_CACHING_ENABLED` 行为

### 11.3 禁止操作

- 对 `ChatTopicDaily` 及业务库任何 DML/DDL
- Bash / Write / Edit 等工具不加入 `allowed_tools`

---

## 12. 多 Agent 演进（未变，Phase 1 不实现）

| 能力 | 说明 |
|------|------|
| 新增 Agent | `agents/{type}/profile.yaml` + Registry 自动发现 |
| 不同模型 | Profile 级 `model`，读不同 env 或硬编码 |
| Tool / MCP | Platform 注册 + Profile 白名单 |
| Subagent | Profile `delegates` + `invocation_modes: [subagent]`（P3+） |

未来 Agent 示例：

| agent_type | 模型（示例） | MCP | Phase |
|------------|-------------|-----|-------|
| `analysis` | claude-sonnet-4-6 | postgres → POSTGRES_URL | **P1** |
| `qa` | claude-sonnet-4-6 | 待定 | P2 |
| `title` | claude-haiku-4-5 | — | P2 |
| `ppt` | claude-opus-4-7 | postgres（可选） | P3 |

---

## 13. 实施路线图（修订）

| 阶段 | 内容 | 产出 |
|------|------|------|
| **P1-a** | Platform 骨架、`config.py` 对接 `.env`、Registry、统一 API | 可启动服务 |
| **P1-b** | Postgres MCP + §4.5 Guardrails（`sql_rules` / Hook / MCP） | 安全只读查数 |
| **P1-c** | 迁移 Skill、`system_prompt.md`、`build_system_prompt()` 静态前缀 inline references | Agent 懂 ChatTopicDaily + 缓存就绪 |
| **P1-d** | SSE、DB 仅 payload、§6.6 memory 投影 + Redis、Prompt Caching | 可对话 + 旧会话继续 |
| **P2** | Prod 只读 DB 账号（env）、`generate_chart`、缓存观测面板、POC CLI → Tool | 生产加固 + 可视化 |
| **P3** | `qa` / `title` Profile、Subagent `delegates` | 多 Agent 矩阵 |
| **P4** | Azure Container Apps 部署、监控 | 上线 |

---

## 14. 待确认事项（更新）

| 项 | 状态 |
|----|------|
| 业务库 Schema | ✅ POC `schema-and-dimensions.md` 已覆盖 ChatTopicDaily 主场景 |
| 分析场景优先级 | ✅ Phase 1 = ChatTopicDaily 主题分析全流程 |
| 平台 DB / Redis | ✅ `DATABASE_URL`（Neon）+ `REDIS_URL` 已配置 |
| Foundry 模型 | ✅ `claude-sonnet-4-6` |
| 分析库连接 | ✅ `POSTGRES_URL` → `odi_knowledge_ai` |
| 只读 DB 账号 | ⏳ Prod 前替换 `POSTGRES_URL`；P1 靠代码层只读 |
| Prompt Caching | ⏳ P1-c 结构准备 + P1-d Foundry 验证 |
| 与 ODI Knowledge 前端集成 / 鉴权 | ⏳ 待定 |
| 触发方式（仅对话 vs 定时报告） | ⏳ Phase 1 仅对话 API |

---

## 15. 术语表

| 术语 | 含义 |
|------|------|
| **POSTGRES_URL** | 业务分析库（ChatTopicDaily 等） |
| **DATABASE_URL** | 平台自有库（用户、会话、消息） |
| **Profile** | Agent 能力定义（YAML + skills + prompt） |
| **topic-daily-analysis** | Phase 1 核心 Skill，POC 迁移而来 |
| **语义归并** | 对开放标签 `intent_theme` 的 LLM 二次聚类 |
| **Prompt Caching** | 复用 LLM 请求稳定前缀，降本提速；见 §6.5 |
| **platform_users** | 平台登录用户（email / department / entity） |
| **payload** | `agent_messages` 中整包 SDK 消息的 JSON |
| **ResultMessage** | SDK 一轮结束消息，含 `usage` 与 `total_cost_usd` |
| **auto-compact** | Claude Code CLI 在 context 接近上限时自动摘要旧历史（§6.6.0） |
| **冷继续（档 3）** | resume 失败后，从 payload 投影最近 N turn 注入新 session（§6.6.8） |

## 附录 A：Design Review 变更摘要

### v0.8 → v0.9

1. **新增 §6.6.0**：SDK 默认多轮、`resume`、`max_turns` 与 **auto-compact** 分工；三档续聊路径；`build_options()` session 伪代码。
2. **§6.6.2** 扩为四层（SDK session / payload / Redis / 冷继续注入）。
3. **§6.6.5** 流程区分档 1（存活 client）/ 档 2（resume）/ 档 3（冷继续）。
4. **新增 §6.6.8**：长会话冷恢复策略、token 预算、`cold_resume_max_tokens`；Phase 1 足够性评估与 P2 增强项。
5. Profile `memory` 增加 `cold_resume_max_tokens`。

### v0.7 → v0.8

1. **修订 §6.6**：memory 不是 DB 摘要列；从全量 `payload` 按 **Tool/MCP/Skill 定制投影**；`MemoryProjectorRegistry` + turn 级 compaction。

### v0.6 → v0.7

1. **新增 §6.6 短期记忆**（v0.7 已修订，见 v0.8）：热/冷继续；Redis working_set。

### v0.5 → v0.6

1. **新增 §4.5 SQL Guardrails**：生成→执行前两道硬闸（PreToolUse + MCP）、规则 G1–G7 / M1–M7、共享 `sql_rules.py`。

### v0.4 → v0.5

1. **移除 `agent_audit_logs` 设计**：SQL/tool 等信息仅保留在 `agent_messages.payload`。
2. **新增 `platform_users`** 等 DB 修订见 v0.3 → v0.4。

### v0.3 → v0.4

1. **新增 `platform_users`**（id, email, department, entity）；`agent_chats.user_id` 必填 FK。
2. **简化 `agent_chats`**：移除 `status`、`metadata`、`source_service`；用量累计列放 chat 级。
3. **重写 `agent_messages`**：一行对应 SDK 一次 yield，`payload JSONB` + `seq`；不再拆 `content`/`tool_calls`/`tool_results`。
4. **§9.5 Token 统计**：以 `ResultMessage.usage` 为准，turn 写 message 行、累计写 chat；SSE 末尾发 `usage` 事件。
5. **§9.4 历史投影**：DB 存 SDK 真相，API 层投影给前端。

### v0.2 → v0.3

1. **移除 `ENABLED_AGENTS`**：Registry 注册全部 Profile；各 Agent 独立 API，前端按需对接。
2. **只读策略**：P1 以 Hook + MCP 代码层严格只读为主；Prod 前仅换 `POSTGRES_URL` 只读账号。
3. **新增 §6.5 Prompt Caching**：静态/动态 prompt 拆分、Profile 配置、SDK/Gateway 集成路径、观测。
4. **Profile 增加 `prompt_caching`** 与 `PROMPT_CACHING_ENABLED`  env。

### v0.1 → v0.2

1. **Phase 1 范围收敛**为单一 `analysis` Agent，架构仍为多 Agent Platform。
2. **双库分离**：`DATABASE_URL`（平台）vs `POSTGRES_URL`（分析 MCP）；修正 v0.1 中「业务 DB 与对话 DB 混谈」。
3. **环境变量**与项目 `.env` 对齐（`CLAUDE_AZURE_*`，非泛化 `ANTHROPIC_FOUNDRY_*`）。
4. **Skill** 从泛化 `db-schema` / `nl2sql-examples` 改为 POC **`topic-daily-analysis`** + references。
5. **分析域** 具化为 ChatTopicDaily、过滤惯例、工作流、语义归并、报告格式、PII 规则。
6. **Redis** 在 Phase 1 启用（非可选）。
7. **POC CLI**（`topic-daily-query.ts`）不纳入 P1；Agent 路径 = MCP SQL + Skill。
8. **安全**：标注 `POSTGRES_URL` 需只读账号。
9. **路线图** 按 P1-a～d 拆分，对接现有 env 与 POC 资产。

---

*文档随实现迭代更新。*
