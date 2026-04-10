from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.db.models import Enrollment, Group, MessageEvent, Streak, User


class IdentityRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_group_by_chat_id(self, chat_id: str) -> Group | None:
        async with self._session_factory() as session:
            return await session.scalar(select(Group).where(Group.chat_id == chat_id))

    async def get_user_by_open_id(self, open_id: str) -> User | None:
        async with self._session_factory() as session:
            return await session.scalar(select(User).where(User.open_id == open_id))

    async def ensure_group(self, chat_id: str, name: str = "") -> Group:
        async with self._session_factory() as session:
            group = await session.scalar(select(Group).where(Group.chat_id == chat_id))
            if group is None:
                group = Group(chat_id=chat_id, name=name)
                session.add(group)
                await session.commit()
                await session.refresh(group)
            elif name and group.name != name:
                group.name = name
                await session.commit()
            return group

    async def ensure_user(self, open_id: str, nickname: str = "") -> User:
        async with self._session_factory() as session:
            user = await session.scalar(select(User).where(User.open_id == open_id))
            now = datetime.now(UTC)
            if user is None:
                user = User(
                    open_id=open_id,
                    nickname=nickname,
                    joined_at=now,
                    last_active_at=now,
                )
                session.add(user)
                await session.commit()
                await session.refresh(user)
            else:
                user.nickname = nickname or user.nickname
                user.last_active_at = now
                await session.commit()
            return user

    async def enroll_user(self, user_id: int, group_id: int) -> Enrollment:
        async with self._session_factory() as session:
            enrollment = await session.scalar(
                select(Enrollment).where(
                    Enrollment.user_id == user_id,
                    Enrollment.group_id == group_id,
                )
            )
            if enrollment is None:
                enrollment = Enrollment(user_id=user_id, group_id=group_id, status="active")
                session.add(enrollment)
                await session.commit()
                await session.refresh(enrollment)
            else:
                enrollment.status = "active"
                await session.commit()
            streak = await session.scalar(select(Streak).where(Streak.user_id == user_id))
            if streak is None:
                session.add(Streak(user_id=user_id, current_days=0, max_days=0))
                await session.commit()
            return enrollment

    async def is_enrolled(self, user_id: int, group_id: int) -> bool:
        async with self._session_factory() as session:
            enrollment = await session.scalar(
                select(Enrollment).where(
                    Enrollment.user_id == user_id,
                    Enrollment.group_id == group_id,
                    Enrollment.status == "active",
                )
            )
            return enrollment is not None

    async def list_enrolled_users(self, group_id: int) -> list[User]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(User)
                .join(Enrollment, Enrollment.user_id == User.id)
                .where(
                    Enrollment.group_id == group_id,
                    Enrollment.status == "active",
                )
                .order_by(User.last_active_at.desc())
            )
            return list(rows)

    async def list_group_active_users(self, group_id: int) -> list[User]:
        """获取群内所有发过消息的用户（不依赖报名）。"""
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(User)
                .join(MessageEvent, MessageEvent.user_id == User.id)
                .where(MessageEvent.group_id == group_id)
                .distinct()
                .order_by(User.last_active_at.desc())
            )
            return list(rows)
