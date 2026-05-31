"""API dependencies — no auth in Phase 1; fixed dev user."""

from __future__ import annotations

import uuid

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from claude_agent_platform.config import get_settings
from claude_agent_platform.db.engine import get_db_session
from claude_agent_platform.db.models import PlatformUser
from claude_agent_platform.db.repos import UserRepo


async def get_session() -> AsyncSession:
    async for session in get_db_session():
        yield session


async def get_dev_user(session: AsyncSession = Depends(get_session)) -> PlatformUser:
    settings = get_settings()
    repo = UserRepo(session)
    user = await repo.get_or_create_dev_user(settings.dev_user_email)
    await session.commit()
    return user
