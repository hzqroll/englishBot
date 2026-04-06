from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.infrastructure.auth.security import hash_password
from src.infrastructure.db.models import AdminUser, DailyCardSnapshot, Group, JobRun, MessageDeliveryLog, User


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

    async def list_job_runs(self, *, limit: int = 100) -> list[dict]:
        async with self._session_factory() as session:
            rows = await session.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(limit))
            result = []
            for row in rows:
                duration_seconds = None
                if row.started_at and row.finished_at:
                    duration_seconds = round((row.finished_at - row.started_at).total_seconds(), 2)
                result.append(
                    {
                        "id": row.id,
                        "job_name": row.job_name,
                        "biz_key": row.biz_key,
                        "status": row.status,
                        "started_at": row.started_at,
                        "finished_at": row.finished_at,
                        "duration_seconds": duration_seconds,
                        "created_at": row.created_at,
                    }
                )
            return result

    async def list_delivery_logs(self, *, limit: int = 100) -> list[dict]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    MessageDeliveryLog,
                    Group.qq_group_id,
                    Group.name,
                    User.qq_user_id,
                    User.nickname,
                    DailyCardSnapshot.card_type,
                    DailyCardSnapshot.image_paths_json,
                )
                .join(Group, Group.id == MessageDeliveryLog.group_id)
                .outerjoin(User, User.id == MessageDeliveryLog.user_id)
                .outerjoin(DailyCardSnapshot, DailyCardSnapshot.id == MessageDeliveryLog.card_snapshot_id)
                .order_by(desc(MessageDeliveryLog.created_at))
                .limit(limit)
            )
            result = []
            for log, qq_group_id, group_name, qq_user_id, nickname, card_type, image_paths in rows.all():
                result.append(
                    {
                        "id": log.id,
                        "job_name": log.job_name,
                        "delivery_mode": log.delivery_mode,
                        "success": log.success,
                        "provider_response": log.provider_response,
                        "created_at": log.created_at,
                        "group_id": qq_group_id,
                        "group_name": group_name or "",
                        "user_id": qq_user_id or "",
                        "nickname": nickname or "",
                        "card_type": card_type or "",
                        "image_count": len(image_paths or []),
                        "card_snapshot_id": log.card_snapshot_id,
                    }
                )
            return result

    async def ensure_group(self, *, qq_group_id: str, name: str = "", enabled: bool = True) -> Group:
        async with self._session_factory() as session:
            group = await session.scalar(select(Group).where(Group.qq_group_id == qq_group_id))
            if group is None:
                group = Group(qq_group_id=qq_group_id, name=name, enabled=enabled)
                session.add(group)
                await session.commit()
                await session.refresh(group)
            else:
                if name and group.name != name:
                    group.name = name
                group.enabled = enabled if enabled is not None else group.enabled
                await session.commit()
                await session.refresh(group)
            return group

    async def list_groups(self) -> list[Group]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(Group).order_by(Group.enabled.desc(), Group.updated_at.desc(), Group.qq_group_id.asc())
            )
            return list(rows)

    async def save_group(
        self,
        *,
        group_id: int | None,
        qq_group_id: str,
        name: str,
        enabled: bool,
    ) -> Group:
        async with self._session_factory() as session:
            existing_by_qq = await session.scalar(select(Group).where(Group.qq_group_id == qq_group_id))
            if group_id is None:
                if existing_by_qq is not None:
                    group = existing_by_qq
                else:
                    group = Group(qq_group_id=qq_group_id, name=name, enabled=enabled)
                    session.add(group)
            else:
                group = await session.get(Group, group_id)
                if group is None:
                    raise ValueError("目标群不存在。")
                if existing_by_qq is not None and existing_by_qq.id != group_id:
                    raise ValueError("该群号已经存在。")
                group.qq_group_id = qq_group_id
                group.name = name
                group.enabled = enabled

            if group_id is None and existing_by_qq is not None:
                group.name = name
                group.enabled = enabled

            await session.commit()
            await session.refresh(group)
            return group
