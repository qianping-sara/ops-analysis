"""Probe available Foundry models for this deployment."""

from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, TextBlock

from claude_agent_platform.config import get_settings


async def try_model(model: str) -> bool:
    opts = ClaudeAgentOptions(model=model, max_turns=1, system_prompt="Reply OK only")
    ok = False
    async with ClaudeSDKClient(options=opts) as client:
        await client.query("Say OK")
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        print(f"{model!r} -> {b.text[:100]!r}")
                        ok = True
    return ok


async def main() -> None:
    get_settings.cache_clear()
    get_settings().apply_foundry_env()
    candidates = [
        "claude-sonnet-4",
        "claude-sonnet-4-20250514",
        "claude-3-5-sonnet-20241022",
        "claude-3-7-sonnet-20250219",
        "claude-haiku-4-5",
        "sonnet",
        "haiku",
    ]
    for m in candidates:
        try:
            if await try_model(m):
                print("WORKING:", m)
                return
        except Exception as exc:
            print(f"{m!r} failed: {exc}")
    print("No working model found")


if __name__ == "__main__":
    asyncio.run(main())
