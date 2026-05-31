# ChatTopicDaily  schema 与分析维度

## 表定位

`ChatTopicDaily` 是**每日会话主题分析的唯一落库表**（Function App 定时任务 UPSERT）。一行 = 一个 `chat_id` 在某一 `analysis_date` 上的主题快照。

| 约束/索引 | 说明 |
|-----------|------|
| `uq_chat_topic_daily_date_chat` | `(analysis_date, chat_id)` 唯一 |
| `idx_chat_topic_daily_analysis_date` | 按分析日落库时间筛选 |
| `idx_chat_topic_daily_primary_regions_gin` | 区域数组 GIN，支持 `@>` / `&&` |
| `idx_chat_topic_daily_primary_service` | 辅助：按日 + 服务枚举 |

**时间轴选择：**

| 字段 | 含义 | 典型用途 |
|------|------|----------|
| `analysis_date` | 批处理分析日（T 日分析 T-1 会话） | 热点、周/月趋势、新兴/消退 |
| `chat_created_at` | 会话真实创建时间 | 与 Chat 对齐、用户行为时段 |

默认趋势分析用 **`analysis_date`**；需要与会话创建时间一致时用 `chat_created_at`。

---

## 字段分层

### 主分析（LLM 开放挖掘）

| 字段 | 类型 | 分析方式 |
|------|------|----------|
| `intent_theme` | varchar(64) | **核心维度**：8–20 字议题短语；频次、周环比、新兴/消退、反查会话 |
| `core_summary` | text | 议题语义检索、`ILIKE`、与 theme 交叉验证；抽样阅读 |
| `primary_regions` | text[] | 区域热度、`unnest` 展开、多区域共现；过滤 `未提及` |
| `confidence` | numeric(4,3) | 过滤低质量行（建议 ≥ 0.85）；加权统计 |

**注意：** `intent_theme` 为开放标签，**字面相同才归为同一主题**。跨周「语义相近但措辞不同」的议题需 Agent 二次聚类（见 SKILL.md §语义归并）。

### 辅助分析（枚举映射）

| 字段 | 典型值示例 | 用途 |
|------|------------|------|
| `primary_service` | corporate_secretarial, tax, odi_outbound_investment, … | topic关联服务分布、与区域交叉矩阵 |
| `intent_type` | policy_interpretation, process, comparison_selection, … | 意图结构、辅助解释热点成因 |

### Ingest / 钻取

| 字段 | 用途 |
|------|------|
| `chat_id`, `user_id`, `user_email` | 反查会话、用户、去重统计 |
| `chat_title`, `user_text`, `message_count` | 轻量预览；深度内容 JOIN Message_v2 |
| `user_email` | 用户基础信息 |

---

## 可分析维度矩阵

### 1. 时间

- 日趋势：`analysis_date` + COUNT
- 周/月：`date_trunc('week'|'month', analysis_date)`
- 窗口对比：近 7 天 vs 前 21 天（新兴/消退/份额变化）
- 季节性：多周并列（drift 子命令）

### 2. 议题（intent_theme + core_summary）

- **热点排行**：频次、独立用户数、平均 message_count
- **持续性热点**：两窗口均 ≥ 阈值
- **新兴议题**：近期出现、基线期为 0（字面匹配）
- **消退议题**：基线期有、近期为 0
- **主题漂移**：周度计数 JSON / 份额变化率
- **语义聚类**（Agent）：对 Top N theme 或 summary 做 LLM 归并（非 SQL 默认）

### 3. 地理（primary_regions）

- 区域会话量、独立用户数
- 区域 × 议题 Top N
- 区域 × `primary_service` 矩阵
- 多区域会话占比：`cardinality(primary_regions) > 1`

### 4. 服务与意图（辅助）

- `primary_service` 分布、时序
- `intent_type` 分布
- 三维切片：区域 + 服务 + 议题（Top K）

### 5. 用户与会话

- 每议题独立 `user_id` 数
- 高价值会话：`message_count` 或 `confidence` 排序
- 重复咨询：同一 `user_id` + 相似 `intent_theme`（需模糊或 Agent）

### 6. 关联表扩展

| 关联 | JOIN 键 | 扩展维度 |
|------|---------|----------|
| `"Chat"` | `chat_id` = `Chat.id` | visibility、title 更新 |
| `"Message_v2"` | `chat_id` = `"chatId"` | 完整对话、工具调用、附件 |
| `"User"` | `user_id` = `User.id` | 邮箱（与落库 email 校验） |
| `"InternalUser"` | email | **分析时排除内部账号** |

---

## 数据质量与过滤惯例

```sql
-- 排除内部用户（与 export 脚本一致）
AND NOT EXISTS (
  SELECT 1 FROM "InternalUser" iu
  WHERE lower(trim(iu.email)) = lower(trim(t.user_email))
)

-- 低置信过滤
AND t.confidence >= 0.85

-- 无地理信息
AND NOT (t.primary_regions = ARRAY['未提及']::text[])
```
