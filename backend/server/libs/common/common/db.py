"""PostgreSQL: у каждого сервиса своя схема. Таблицы создаются при старте (create_all) —
для хакатона без миграций Alembic."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from common.logging import get_logger

log = get_logger(__name__)


class Database:
    def __init__(self, url: str, schema: str):
        self.schema = schema
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=10)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def init(self, metadata: MetaData, attempts: int = 60) -> None:
        for i in range(attempts):
            try:
                async with self.engine.begin() as conn:
                    await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"'))
                    await conn.run_sync(metadata.create_all)
                return
            except Exception as e:  # БД ещё поднимается или гонка двух экземпляров
                if i == attempts - 1:
                    raise
                log.warning("db_not_ready", error=str(e)[:200])
                await asyncio.sleep(1)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as s:
            yield s

    async def close(self) -> None:
        await self.engine.dispose()
