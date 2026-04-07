from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.db.models import RuntimeSetting


class FeishuDocsRepository:
    """使用 RuntimeSetting 表存储飞书文档的 folder_token 和每周文档 ID。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_value(self, key: str) -> str | None:
        async with self._session_factory() as session:
            row = await session.scalar(select(RuntimeSetting).where(RuntimeSetting.key == key))
            return row.value if row else None

    async def save_value(self, key: str, value: str) -> None:
        async with self._session_factory() as session:
            existing = await session.scalar(select(RuntimeSetting).where(RuntimeSetting.key == key))
            if existing:
                existing.value = value
            else:
                session.add(RuntimeSetting(key=key, value=value))
            await session.commit()
