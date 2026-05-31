# 反查会话、关联 Message_v2

## 按 intent_theme 精确反查

```sql
SELECT
  t.analysis_date,
  t.chat_id,
  left(t.user_email, 2) || '***@' || split_part(t.user_email, '@', 2) AS email_masked,
  t.intent_theme,
  t.primary_regions,
  t.core_summary,
  t.message_count,
  t.confidence
FROM "ChatTopicDaily" t
WHERE t.intent_theme = '越南公司运营合规要求'
  AND t.analysis_date >= CURRENT_DATE - 30
ORDER BY t.analysis_date DESC;
```

## 模糊 / 多字段检索

```sql
SELECT t.chat_id, t.intent_theme, left(t.core_summary, 160) AS summary
FROM "ChatTopicDaily" t
WHERE t.analysis_date >= CURRENT_DATE - 30
  AND (
    t.intent_theme ILIKE '%原产地%'
    OR t.core_summary ILIKE '%原产地%'
    OR t.primary_regions && ARRAY['越南']::text[]
  )
ORDER BY t.confidence DESC, t.message_count DESC
LIMIT 30;
```

## 关联完整对话（Message_v2）

```sql
SELECT
  t.chat_id,
  t.intent_theme,
  t.core_summary,
  m.role,
  m.parts,
  m."createdAt"
FROM "ChatTopicDaily" t
JOIN "Message_v2" m ON m."chatId" = t.chat_id
WHERE t.intent_theme ILIKE '%ODI%'
  AND t.analysis_date >= CURRENT_DATE - 14
ORDER BY t.chat_id, m."createdAt"
LIMIT 200;
```

`parts` 为 JSON：文本块 `type=text` 的 `text` 字段为用户/助手正文（与 `topic-export-bucket.ts` 提取逻辑一致）。

## 关联 Chat 元数据

```sql
SELECT
  t.chat_id,
  c.title,
  c."createdAt",
  c.visibility,
  t.intent_theme,
  t.core_summary
FROM "ChatTopicDaily" t
JOIN "Chat" c ON c.id = t.chat_id
WHERE t.user_id = '<uuid>'::uuid
ORDER BY c."createdAt" DESC;
```

## 某议题下的用户列表（脱敏）

```sql
SELECT
  COUNT(DISTINCT t.user_id)::int AS users,
  array_agg(DISTINCT left(t.user_email, 2) || '***@' || split_part(t.user_email, '@', 2)) AS emails_sample
FROM "ChatTopicDaily" t
WHERE t.intent_theme ILIKE '%预扣税%'
  AND t.analysis_date >= CURRENT_DATE - 30;
```

## 报告中的 PII 规则

- 禁止批量输出 `user_text` 全文；抽样 ≤5 条 summary 预览
