"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from sqlalchemy import text

from claude_agent_platform.api.routes.agents import router as agents_router
from claude_agent_platform.config import get_settings
from claude_agent_platform.core.registry import init_registry
from claude_agent_platform.db.engine import get_engine, get_session_factory, init_db
from claude_agent_platform.db.models import Base
from claude_agent_platform.mcp.postgres_tools import close_pool
from claude_agent_platform.memory.redis_store import close_redis, init_redis
from claude_agent_platform.runtime.client_pool import get_client_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.apply_foundry_env()

    agents_dir = Path(settings.project_root) / settings.agents_dir
    init_registry(agents_dir)

    init_db()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        await init_redis()
    except Exception as exc:
        print(f"Warning: Redis init failed ({exc}); memory cache disabled")

    yield

    await get_client_pool().close_all()
    await close_pool()
    try:
        await close_redis()
    except Exception:
        pass


app = FastAPI(title="Claude Agent Platform", version="0.1.0", lifespan=lifespan)
app.include_router(agents_router)


@app.get("/health")
async def health():
    settings = get_settings()
    checks: dict[str, str] = {"status": "ok"}
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        checks["platform_db"] = "ok"
    except Exception as exc:
        checks["platform_db"] = f"error: {exc}"
        checks["status"] = "degraded"

    try:
        from claude_agent_platform.memory.redis_store import get_redis_store

        store = get_redis_store()
        await store._client.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"unavailable: {exc}"

    return checks


def run() -> None:
    import uvicorn

    uvicorn.run("claude_agent_platform.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    run()
