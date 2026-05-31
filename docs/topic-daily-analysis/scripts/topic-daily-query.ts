#!/usr/bin/env node
/**
 * ChatTopicDaily 主题分析 CLI（只读 PG）
 *
 * 用法:
 *   npm run topic:daily -- hot --days 14
 *   npm run topic:daily -- drift --weeks 6
 *   npm run topic:daily -- emerging --recent 7 --baseline 28
 *   npm run topic:daily -- fading --recent 7 --baseline 28
 *   npm run topic:daily -- search --q "越南设厂" --days 30
 *   npm run topic:daily -- regions --days 14
 *   npm run topic:daily -- matrix --days 30
 *   npm run topic:daily -- stats
 */
import pg from "pg";
import { getConfig } from "../../../../src/config/env.js";

const { Client } = pg;

type Row = Record<string, unknown>;

function parseArgs(argv: string[]): {
  cmd: string;
  flags: Record<string, string | boolean>;
} {
  const rest = argv.slice(2);
  const cmd = rest[0] ?? "stats";
  const flags: Record<string, string | boolean> = {};
  for (let i = 1; i < rest.length; i++) {
    const a = rest[i]!;
    if (a.startsWith("--")) {
      const key = a.slice(2);
      const next = rest[i + 1];
      if (!next || next.startsWith("--")) {
        flags[key] = true;
      } else {
        flags[key] = next;
        i++;
      }
    }
  }
  return { cmd, flags };
}

function flagInt(
  flags: Record<string, string | boolean>,
  key: string,
  fallback: number,
): number {
  const v = flags[key];
  if (v === undefined || v === true) return fallback;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function flagStr(
  flags: Record<string, string | boolean>,
  key: string,
  fallback: string,
): string {
  const v = flags[key];
  if (v === undefined || v === true) return fallback;
  return String(v);
}

function printTable(rows: Row[]): void {
  if (rows.length === 0) {
    console.log("(无数据)");
    return;
  }
  console.log(JSON.stringify(rows, null, 2));
}

async function withClient<T>(
  fn: (client: pg.Client) => Promise<T>,
): Promise<T> {
  const cfg = getConfig();
  if (!cfg.postgresUrl) {
    throw new Error("需要 POSTGRES_URL 或 POSTGRES_URL_NEW");
  }
  const client = new Client({ connectionString: cfg.postgresUrl });
  await client.connect();
  try {
    return await fn(client);
  } finally {
    await client.end();
  }
}

/** 排除内部用户（与 topic-export 一致） */
const EXCLUDE_INTERNAL = `
  AND NOT EXISTS (
    SELECT 1 FROM "InternalUser" iu
    WHERE lower(trim(iu.email)) = lower(trim(t.user_email))
  )
`;

async function cmdStats(): Promise<void> {
  const rows = await withClient((c) =>
    c.query<Row>(
      `
      SELECT
        COUNT(*)::int AS total_rows,
        COUNT(DISTINCT chat_id)::int AS distinct_chats,
        COUNT(DISTINCT user_id)::int AS distinct_users,
        MIN(analysis_date)::text AS min_analysis_date,
        MAX(analysis_date)::text AS max_analysis_date,
        ROUND(AVG(confidence)::numeric, 3) AS avg_confidence
      FROM "ChatTopicDaily" t
      WHERE 1=1 ${EXCLUDE_INTERNAL}
      `,
    ),
  );
  printTable(rows.rows);
}

async function cmdHot(flags: Record<string, string | boolean>): Promise<void> {
  const days = flagInt(flags, "days", 14);
  const limit = flagInt(flags, "limit", 25);
  const minConf = flagStr(flags, "min-confidence", "0.85");

  const rows = await withClient((c) =>
    c.query<Row>(
      `
      SELECT
        t.intent_theme,
        COUNT(*)::int AS sessions,
        COUNT(DISTINCT t.user_id)::int AS users,
        ROUND(AVG(t.confidence)::numeric, 3) AS avg_confidence,
        ROUND(AVG(t.message_count)::numeric, 1) AS avg_messages
      FROM "ChatTopicDaily" t
      WHERE t.analysis_date >= CURRENT_DATE - $1::int
        ${EXCLUDE_INTERNAL}
      GROUP BY t.intent_theme
      HAVING AVG(t.confidence) >= $3::numeric
      ORDER BY sessions DESC, avg_confidence DESC
      LIMIT $2
      `,
      [days, limit, minConf],
    ),
  );
  console.log(`# 热点议题 (近 ${days} 天, confidence >= ${minConf})`);
  printTable(rows.rows);
}

async function cmdDrift(flags: Record<string, string | boolean>): Promise<void> {
  const weeks = flagInt(flags, "weeks", 6);
  const limit = flagInt(flags, "limit", 30);

  const rows = await withClient((c) =>
    c.query<Row>(
      `
      WITH weekly AS (
        SELECT
          date_trunc('week', analysis_date)::date AS week_start,
          intent_theme,
          COUNT(*)::int AS cnt
        FROM "ChatTopicDaily" t
        WHERE analysis_date >= CURRENT_DATE - ($1::int * 7)
          ${EXCLUDE_INTERNAL}
        GROUP BY 1, 2
      ),
      ranked AS (
        SELECT
          week_start,
          intent_theme,
          cnt,
          ROW_NUMBER() OVER (PARTITION BY week_start ORDER BY cnt DESC) AS rn
        FROM weekly
      ),
      pivot AS (
        SELECT
          intent_theme,
          jsonb_object_agg(week_start::text, cnt ORDER BY week_start) AS weekly_counts,
          SUM(cnt)::int AS total
        FROM ranked
        WHERE rn <= $2
        GROUP BY intent_theme
      )
      SELECT * FROM pivot
      ORDER BY total DESC
      LIMIT $2
      `,
      [weeks, limit],
    ),
  );
  console.log(`# 周度议题趋势 (近 ${weeks} 周, 每周 Top 主题聚合)`);
  printTable(rows.rows);
}

async function cmdEmerging(
  flags: Record<string, string | boolean>,
  mode: "emerging" | "fading",
): Promise<void> {
  const recentDays = flagInt(flags, "recent", 7);
  const baselineDays = flagInt(flags, "baseline", 28);
  const minRecent = flagInt(flags, "min-recent", 2);

  const order =
    mode === "emerging"
      ? "recent_cnt DESC, baseline_cnt ASC"
      : "baseline_cnt DESC, recent_cnt ASC";

  const having =
    mode === "emerging"
      ? `recent_cnt >= $3 AND baseline_cnt = 0`
      : `baseline_cnt >= $3 AND recent_cnt = 0`;

  const rows = await withClient((c) =>
    c.query<Row>(
      `
      WITH tagged AS (
        SELECT intent_theme, analysis_date
        FROM "ChatTopicDaily" t
        WHERE analysis_date >= CURRENT_DATE - $1::int
          ${EXCLUDE_INTERNAL}
      ),
      agg AS (
        SELECT
          intent_theme,
          COUNT(*) FILTER (
            WHERE analysis_date >= CURRENT_DATE - $2::int
          )::int AS recent_cnt,
          COUNT(*) FILTER (
            WHERE analysis_date < CURRENT_DATE - $2::int
          )::int AS baseline_cnt
        FROM tagged
        GROUP BY intent_theme
      )
      SELECT
        intent_theme,
        recent_cnt,
        baseline_cnt,
        ROUND(100.0 * recent_cnt / NULLIF(recent_cnt + baseline_cnt, 0), 1) AS recent_share_pct
      FROM agg
      WHERE ${having}
      ORDER BY ${order}
      LIMIT 40
      `,
      [baselineDays, recentDays, minRecent],
    ),
  );
  const label = mode === "emerging" ? "新兴" : "消退";
  console.log(
    `# ${label}议题 (近 ${recentDays} 天 vs 前 ${baselineDays - recentDays} 天, min=${minRecent})`,
  );
  printTable(rows.rows);
}

async function cmdSearch(flags: Record<string, string | boolean>): Promise<void> {
  const q = flagStr(flags, "q", "");
  if (!q.trim()) throw new Error("search 需要 --q <关键词>");
  const days = flagInt(flags, "days", 30);
  const limit = flagInt(flags, "limit", 20);

  const rows = await withClient((c) =>
    c.query<Row>(
      `
      SELECT
        t.analysis_date,
        t.chat_id,
        left(t.user_email, 3) || '***' || split_part(t.user_email, '@', 2) AS user_email_masked,
        t.intent_theme,
        t.primary_regions,
        t.primary_service,
        t.confidence,
        left(t.core_summary, 200) AS core_summary_preview,
        t.message_count
      FROM "ChatTopicDaily" t
      WHERE t.analysis_date >= CURRENT_DATE - $1::int
        ${EXCLUDE_INTERNAL}
        AND (
          t.intent_theme ILIKE '%' || $2 || '%'
          OR t.core_summary ILIKE '%' || $2 || '%'
          OR EXISTS (
            SELECT 1 FROM unnest(t.primary_regions) r
            WHERE r ILIKE '%' || $2 || '%'
          )
        )
      ORDER BY t.analysis_date DESC, t.confidence DESC
      LIMIT $3
      `,
      [days, q, limit],
    ),
  );
  console.log(`# 主题反查 "${q}" (近 ${days} 天)`);
  printTable(rows.rows);
}

async function cmdRegions(flags: Record<string, string | boolean>): Promise<void> {
  const days = flagInt(flags, "days", 14);
  const limit = flagInt(flags, "limit", 25);

  const rows = await withClient((c) =>
    c.query<Row>(
      `
      SELECT
        region,
        COUNT(*)::int AS sessions,
        COUNT(DISTINCT user_id)::int AS users,
        COUNT(DISTINCT intent_theme)::int AS distinct_themes
      FROM (
        SELECT t.user_id, t.intent_theme, unnest(t.primary_regions) AS region
        FROM "ChatTopicDaily" t
        WHERE t.analysis_date >= CURRENT_DATE - $1::int
          ${EXCLUDE_INTERNAL}
      ) x
      WHERE region IS NOT NULL AND region <> '未提及'
      GROUP BY region
      ORDER BY sessions DESC
      LIMIT $2
      `,
      [days, limit],
    ),
  );
  console.log(`# 区域热度 (近 ${days} 天)`);
  printTable(rows.rows);
}

async function cmdMatrix(flags: Record<string, string | boolean>): Promise<void> {
  const days = flagInt(flags, "days", 30);
  const limit = flagInt(flags, "limit", 40);

  const rows = await withClient((c) =>
    c.query<Row>(
      `
      SELECT
        primary_service,
        region,
        COUNT(*)::int AS sessions
      FROM (
        SELECT
          t.primary_service,
          unnest(t.primary_regions) AS region
        FROM "ChatTopicDaily" t
        WHERE t.analysis_date >= CURRENT_DATE - $1::int
          ${EXCLUDE_INTERNAL}
      ) x
      WHERE region IS NOT NULL AND region <> '未提及'
      GROUP BY primary_service, region
      ORDER BY sessions DESC
      LIMIT $2
      `,
      [days, limit],
    ),
  );
  console.log(`# 服务 × 区域 (近 ${days} 天, 辅助维度)`);
  printTable(rows.rows);
}

async function main(): Promise<void> {
  const { cmd, flags } = parseArgs(process.argv);

  switch (cmd) {
    case "stats":
      await cmdStats();
      break;
    case "hot":
      await cmdHot(flags);
      break;
    case "drift":
      await cmdDrift(flags);
      break;
    case "emerging":
      await cmdEmerging(flags, "emerging");
      break;
    case "fading":
      await cmdEmerging(flags, "fading");
      break;
    case "search":
      await cmdSearch(flags);
      break;
    case "regions":
      await cmdRegions(flags);
      break;
    case "matrix":
      await cmdMatrix(flags);
      break;
    default:
      console.error(`未知子命令: ${cmd}`);
      console.error(
        "可用: stats | hot | drift | emerging | fading | search | regions | matrix",
      );
      process.exit(1);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
