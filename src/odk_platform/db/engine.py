"""Async SQLAlchemy engine."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from odk_platform.config import get_settings

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    if _engine is None:
        raise RuntimeError("Database not initialized")
    return _engine


def _to_async_url(url: str) -> str:
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    parsed = urlparse(url)
    scheme = "postgresql+asyncpg"
    netloc = parsed.netloc
    path = parsed.path

    drop_keys = {"channel_binding", "options", "sslmode"}
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k not in drop_keys]
    new_query = urlencode(query)

    return urlunparse((scheme, netloc, path, parsed.params, new_query, parsed.fragment))


def _ssl_connect_arg(url: str) -> bool | None:
    from urllib.parse import parse_qsl, urlparse

    q = dict(parse_qsl(urlparse(url).query))
    mode = q.get("sslmode")
    if mode in ("require", "verify-ca", "verify-full"):
        return True
    if mode == "disable":
        return False
    return None


def init_db() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    settings = get_settings()
    connect_args: dict = {}
    ssl = _ssl_connect_arg(settings.database_url)
    if ssl is not None:
        connect_args["ssl"] = ssl

    _engine = create_async_engine(
        _to_async_url(settings.database_url),
        echo=False,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
