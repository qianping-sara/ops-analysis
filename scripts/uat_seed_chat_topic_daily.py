#!/usr/bin/env python3
"""
UAT-only seed script for ChatTopicDaily test data.

SAFETY:
  - Requires --confirm-uat
  - Refuses URLs containing 'prod' (case-insensitive)
  - Only INSERT into ChatTopicDaily

Usage:
  uv run python scripts/uat_seed_chat_topic_daily.py --confirm-uat
  uv run python scripts/uat_seed_chat_topic_daily.py --confirm-uat --rows 50
  uv run python scripts/uat_seed_chat_topic_daily.py --confirm-uat --clear
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import asyncpg
from dotenv import load_dotenv

THEMES = [
    ("ODI 备案流程咨询", "用户询问 ODI Outbound 投资备案材料与时效"),
    ("新加坡公司秘书服务", "讨论 corporate secretarial 年度合规与费用"),
    ("越南设厂税务问题", "咨询越南工厂设立与 transfer pricing"),
    ("香港银行开户", "香港公司银行开户所需文件与周期"),
    ("红筹架构设计", "VIE 与红筹架构比较及最新监管"),
    ("Transfer Pricing 文档", "关联交易同期文档准备要求"),
    ("跨境电商合规", "跨境平台税务与海关合规咨询"),
    ("员工股权激励", "期权池设计与 ESOP 税务"),
]

REGIONS = [
    ["新加坡"],
    ["越南"],
    ["香港"],
    ["新加坡", "越南"],
    ["未提及"],
]


async def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Seed UAT ChatTopicDaily")
    parser.add_argument("--confirm-uat", action="store_true", help="Required safety flag")
    parser.add_argument("--rows", type=int, default=80, help="Number of rows to insert")
    parser.add_argument("--clear", action="store_true", help="Delete existing seed rows first")
    args = parser.parse_args()

    if not args.confirm_uat:
        print("ERROR: Pass --confirm-uat to acknowledge UAT-only seeding")
        return 1

    url = os.environ.get("POSTGRES_URL", "")
    if not url:
        print("ERROR: POSTGRES_URL not set")
        return 1

    if "prod" in url.lower():
        print("ERROR: POSTGRES_URL appears to be PROD — refusing to seed")
        return 1

    print(f"Target: {url.split('@')[-1] if '@' in url else '[redacted]'}")
    pool = await asyncpg.create_pool(url, min_size=1, max_size=2)

    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = 'ChatTopicDaily'
            )
            """
        )
        if not exists:
            print('ERROR: Table "ChatTopicDaily" not found')
            await pool.close()
            return 1

        if args.clear:
            deleted = await conn.execute(
                """
                DELETE FROM "ChatTopicDaily"
                WHERE user_email LIKE 'uat-seed-%@example.com'
                """
            )
            print(f"Cleared seed rows: {deleted}")

        base_date = date.today() - timedelta(days=14)
        inserted = 0
        for i in range(args.rows):
            theme, summary = THEMES[i % len(THEMES)]
            regions = REGIONS[i % len(REGIONS)]
            analysis_day = base_date + timedelta(days=i % 14)
            chat_id = uuid.uuid4()
            user_id = uuid.uuid4()
            email = f"uat-seed-{i % 20}@example.com"
            chat_created = datetime.combine(analysis_day, datetime.min.time(), tzinfo=timezone.utc)

            await conn.execute(
                """
                INSERT INTO "ChatTopicDaily" (
                    analysis_date, chat_id, user_id, user_email,
                    chat_created_at, chat_title, user_text, message_count,
                    intent_theme, core_summary, primary_regions,
                    confidence, primary_service, intent_type
                ) VALUES (
                    $1, $2, $3, $4,
                    $5, $6, $7, $8,
                    $9, $10, $11,
                    $12, $13, $14
                )
                ON CONFLICT (analysis_date, chat_id) DO NOTHING
                """,
                analysis_day,
                chat_id,
                user_id,
                email,
                chat_created,
                f"UAT seed chat {i}",
                f"Sample user message for {theme}",
                3 + (i % 5),
                theme,
                summary,
                regions,
                0.9,
                "corporate_secretarial",
                "process",
            )
            inserted += 1

        count = await conn.fetchval('SELECT COUNT(*) FROM "ChatTopicDaily"')
        print(f"Inserted/attempted {inserted} rows; table total: {count}")

    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
