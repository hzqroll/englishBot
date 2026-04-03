from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.auth.security import hash_password
from src.infrastructure.db.models import AdminUser, JobRun, User


class AdminRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def ensure_admin_user(self, *, username: str, password: str) -> None:
        async with self._session_factory() as session:
            row = await session.scalar(select(AdminUser).where(AdminUser.username == username))
            if row is None:
                session.add(
                    AdminUser(
                        username=username,
                        password_hash=hash_password(password),
                        status="active",
                    )
                )
                await session.commit()

    async def get_admin_user(self, username: str) -> AdminUser | None:
        async with self._session_factory() as session:
            return await session.scalar(select(AdminUser).where(AdminUser.username == username))

    async def list_users(self) -> list[User]:
        async with self._session_factory() as session:
            rows = await session.scalars(select(User).order_by(User.last_active_at.desc()))
            return list(rows)

    async def list_recent_jobs(self) -> list[JobRun]:
        async with self._session_factory() as session:
            rows = await session.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(20))
            return list(rows)

