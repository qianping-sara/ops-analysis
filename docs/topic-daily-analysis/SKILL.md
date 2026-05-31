---
name: topic-daily-analysis
description: 分析 odi-knowledge-ai 内部销售问答会话（ChatTopicDaily）：热点议题、周月漂移、新兴/消退主题、区域与服务线、反查会话。面向销售管理与知识运营，提炼趋势与商机/知识缺口信号。用户问最近聊什么、热点、主题变化、新兴话题、区域热度、商机趋势、ChatTopicDaily 时使用。只读 DB。
---

# ChatTopicDaily 主题分析

## 与 Agent 系统 Prompt 的分工

| 层 | 位置 | 内容 |
|----|------|------|
| **角色与价值** | `src/agent/prompts.ts` | 分析 odi-knowledge-ai 会话、读者（销售管理/知识运营）、趋势与商机导向 |
| **运行时** | `src/agent/prompts.ts` | 只读 MCP、禁用 Bash/Write、**必须加载本 Skill** |
| **方法与数据** | 本 Skill + `references/` | 表结构、SQL、过滤、语义归并、报告骨架 |

触发本 Skill 后，查询与拆解步骤以本文与 references 为准。

## 数据源

- **主表**：`"ChatTopicDaily"`（每日 UPSERT，唯一键 `analysis_date + chat_id`）
- **重点字段（LLM 开放）**：`intent_theme`、`core_summary`、`primary_regions`
- **辅助字段（枚举）**：`primary_service`、`intent_type`
- **钻取**：`chat_id` → `"Chat"` / `"Message_v2"` / `"User"`

Schema 与维度矩阵见 [references/schema-and-dimensions.md](references/schema-and-dimensions.md)。

## 工作流选择

| 用户意图 | 第一步 | 参考 |
|----------|--------|------|
| 最近热点 / Top 议题 | `npm run topic:daily -- hot` | [hot-topics.md](references/hot-topics.md) |
| 几周/一月主题变化、新兴、消退 | `drift` / `emerging` / `fading` | [drift-and-churn.md](references/drift-and-churn.md) |
| 某主题有哪些会话、summary | `search` 或 SQL 反查 | [drilldown-and-joins.md](references/drilldown-and-joins.md) |
| 区域热点、服务×区域 | `regions` / `matrix` | [regions-and-services.md](references/regions-and-services.md) |
| 数据覆盖情况 | `stats` | — |

## 执行顺序

1. **Agent**：postgres MCP 只读 SQL（复用 reference 片段）
2. **本地/人工**：`npm run topic:daily -- <子命令>`（不经 Agent，确定性输出）
3. **议题过于分散时**：对 Top theme + summary 做 **语义归并**（见下），勿重跑打标任务

### 子命令

```bash
npm run topic:daily -- stats
npm run topic:daily -- hot --days 14 --limit 25
npm run topic:daily -- drift --weeks 6
npm run topic:daily -- emerging --recent 7 --baseline 28
npm run topic:daily -- fading --recent 7 --baseline 28
npm run topic:daily -- search --q "越南" --days 30
npm run topic:daily -- regions --days 14
npm run topic:daily -- matrix --days 30
```

脚本路径：`.claude/skills/topic-daily-analysis/scripts/topic-daily-query.ts`

## 语义归并（开放标签漂移）

`intent_theme` 字面唯一才算同一主题。用户问「漂移」「涌现」且 SQL 结果碎片化时：

1. 拉取目标窗口内 Top 60–100 个 `intent_theme` 及 1 条 `core_summary` 样例
2. LLM 归并成 12–20 个中文语义簇
3. 输出：簇趋势、新簇、弱簇；附「成员 intent_theme」附录
4. 反查仍用 `search --q` 或 `ILIKE` 各成员关键词

## 过滤惯例

- 排除 `"InternalUser"`（与 export 一致，CLI 已内置）
- 默认 `confidence >= 0.85`（hot 可用 `--min-confidence`）
- `primary_regions` 含 `未提及` 时区域分析需排除

## 输出格式

中文。在系统 Prompt 的角色框架下组织，建议结构：

### 摘要（给管理层 30 秒版）
- 时间范围、会话量量级、最值得关注的 2–3 条结论

### 大家在聊什么
- 热点议题、区域、服务线（附关键数字）；新兴 / 消退主题

### 趋势与信号
- **销售管理**：需求升温领域、跨同事复现的议题、潜在商机或大单前置问题（谨慎表述，注明依据）
- **知识运营**：高频但未覆盖好的主题、建议补充的知识/FAQ/培训

### 数据与方法
- `analysis_date` 或 `chat_created_at`、过滤条件、是否语义归并

### 建议的下一步
- 可执行动作（例：某区域税务专题复盘会、补充某国 ODI 指引）

技术说明：区分字面 `intent_theme` 与语义归并；邮箱脱敏；`chat_id` 仅在被要求复盘时列出。

## 禁止

- 不要 `UPDATE`/`INSERT` ChatTopicDaily（打标由 Function App 负责）
- 不要为分析目的重跑全量打标
