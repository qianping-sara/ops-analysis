# 区域热度与服务交叉（辅助维度）

## 区域热度（展开 primary_regions）

```sql
SELECT
  r AS region,
  COUNT(*)::int AS sessions,
  COUNT(DISTINCT t.user_id)::int AS users
FROM "ChatTopicDaily" t
CROSS JOIN LATERAL unnest(t.primary_regions) AS r
WHERE t.analysis_date >= CURRENT_DATE - 14
  AND r IS NOT NULL AND r <> '未提及'
GROUP BY r
ORDER BY sessions DESC
LIMIT 25;
```

## 某区域 Top 议题

```sql
SELECT
  t.intent_theme,
  COUNT(*)::int AS sessions
FROM "ChatTopicDaily" t
WHERE t.analysis_date >= CURRENT_DATE - 30
  AND t.primary_regions @> ARRAY['新加坡']::text[]
GROUP BY t.intent_theme
ORDER BY sessions DESC
LIMIT 15;
```

## 服务线分布（辅助）

```sql
SELECT
  t.primary_service,
  COUNT(*)::int AS sessions,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM "ChatTopicDaily" t
WHERE t.analysis_date >= CURRENT_DATE - 30
GROUP BY t.primary_service
ORDER BY sessions DESC;
```

## 服务 × 区域矩阵

```sql
SELECT
  t.primary_service,
  r AS region,
  COUNT(*)::int AS sessions
FROM "ChatTopicDaily" t
CROSS JOIN LATERAL unnest(t.primary_regions) AS r
WHERE t.analysis_date >= CURRENT_DATE - 30
  AND r <> '未提及'
GROUP BY 1, 2
ORDER BY sessions DESC
LIMIT 50;
```

## 区域 × 意图类型（看咨询形态）

```sql
SELECT
  r AS region,
  t.intent_type,
  COUNT(*)::int AS sessions
FROM "ChatTopicDaily" t
CROSS JOIN LATERAL unnest(t.primary_regions) AS r
WHERE t.analysis_date >= CURRENT_DATE - 14
  AND r <> '未提及'
GROUP BY 1, 2
ORDER BY sessions DESC;
```

## primary_service 枚举（当前库样本）

| 值 | 含义（展示用） |
|----|----------------|
| corporate_secretarial | 公司秘书 / 注册 |
| tax | 税务 |
| odi_outbound_investment | ODI 出境投资 |
| entry_strategy_advisory | 入市战略 |
| hr_payroll_visa | 人力 / 薪酬 / 签证 |
| audit_assurance | 审计 |
| accounting_operations | 会计运营 |
| legal_and_ma | 法务与并购 |
| technology_digital | 数字化 |
| due_diligence | 尽职调查 |
| intellectual_property | 知识产权 |
| financial_reporting_cfo | 财务报告 / CFO |
| transfer_pricing | 转让定价 |
| esg_sustainability | ESG |
| other | 其他 |

## intent_type 枚举

| 值 | 含义 |
|----|------|
| policy_interpretation | 政策解读 |
| process | 流程办事 |
| comparison_selection | 对比选型 |
| compliance_risk | 合规风险 |
| cost_timeline | 成本与时效 |
| other | 其他 |

枚举由打标管道映射，**不能**覆盖开放议题的全部语义；交叉分析时以 `intent_theme` 为主、`primary_service` / `intent_type` 为辅。
