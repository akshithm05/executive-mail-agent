"""Async database engine and session management.

The :class:`Database` object owns the SQLAlchemy async engine and session
factory for the application's lifetime. It is created during application
startup, stored on ``app.state``, disposed on shutdown, and injected into
request handlers via the dependency in :mod:`app.api.deps`.

Encapsulating the engine in an object (rather than a module-level global) makes
the wiring explicit and lets tests substitute an in-memory database cleanly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.logging import get_logger

logger = get_logger(__name__)


class Database:
    """Owns the async engine and session factory.

    Args:
        dsn: SQLAlchemy async connection string.
        echo: When True, SQLAlchemy logs all emitted SQL.
        pool_size: Number of persistent connections in the pool.
        max_overflow: Number of connections allowed beyond ``pool_size``.
        pool_pre_ping: When True, test connections for liveness before use.
    """

    def __init__(
        self,
        dsn: str,
        *,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_pre_ping: bool = True,
    ) -> None:
        # SQLite (used in tests) does not accept pool sizing arguments.
        engine_kwargs: dict[str, object] = {"echo": echo, "future": True}
        if not dsn.startswith("sqlite"):
            engine_kwargs.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_pre_ping=pool_pre_ping,
            )
        self._engine: AsyncEngine = create_async_engine(dsn, **engine_kwargs)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            autoflush=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        """Return the underlying async engine."""
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Return the async session factory."""
        return self._session_factory

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield a session, committing on success and rolling back on error.

        Yields:
            An :class:`AsyncSession` bound to the engine.
        """
        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def ping(self) -> bool:
        """Return True if the database answers a trivial query.

        Never raises; connection failures are logged and reported as ``False``
        so the caller (typically the readiness probe) can decide how to react.
        """
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            logger.warning("database_ping_failed", error=str(exc))
            return False

    async def dispose(self) -> None:
        """Dispose of the engine and close all pooled connections."""
        await self._engine.dispose()
        logger.info("database_disposed")
