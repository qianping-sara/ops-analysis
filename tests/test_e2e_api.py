"""E2E API smoke test (requires running server + .env)."""

from __future__ import annotations

import json
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000")


def main() -> int:
    with httpx.Client(timeout=300.0) as client:
        health = client.get(f"{BASE}/health").json()
        assert health.get("status") == "ok", health
        assert health.get("platform_db") == "ok", health

        agents = client.get(f"{BASE}/api/v1/agents").json()
        assert any(a["id"] == "analysis" for a in agents["agents"])

        chat = client.post(
            f"{BASE}/api/v1/agents/analysis/chats",
            json={"title": "pytest e2e"},
        ).json()
        chat_id = chat["id"]

        events: list[dict] = []
        with client.stream(
            "POST",
            f"{BASE}/api/v1/agents/analysis/chats/{chat_id}/messages",
            json={"content": "ChatTopicDaily 有多少行？只回答数字和方法。"},
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))

        types = {e.get("type") for e in events}
        assert "text_delta" in types or any(
            e.get("type") == "text_delta" for e in events
        ), f"no text_delta in {types}"
        assert "done" in types, f"no done in {types}"
        assert "error" not in types, events

        msgs = client.get(f"{BASE}/api/v1/agents/analysis/chats/{chat_id}/messages").json()
        assert len(msgs["messages"]) >= 1

        print("E2E OK turn1", chat_id, "events=", len(events))

        # Multi-turn (same chat, pooled client)
        events2: list[dict] = []
        with client.stream(
            "POST",
            f"{BASE}/api/v1/agents/analysis/chats/{chat_id}/messages",
            json={"content": "再按 primary_regions 统计会话数，简要回答。"},
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    events2.append(json.loads(line[6:]))

        types2 = {e.get("type") for e in events2}
        assert "done" in types2, f"turn2 no done: {types2}"
        assert "error" not in types2, events2
        print("E2E OK turn2", chat_id)
        return 0


if __name__ == "__main__":
    sys.exit(main())
