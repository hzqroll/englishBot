from __future__ import annotations

import yaml

from src.infrastructure.db.repositories.admin import AdminRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.settings.models import EffectiveSettings
from src.infrastructure.settings.runtime import RuntimeConfigService


class AdminUseCase:
    def __init__(
        self,
        *,
        admin_repo: AdminRepository,
        learning_repo: LearningRepository,
        runtime_config: RuntimeConfigService,
        settings: EffectiveSettings,
    ) -> None:
        self._admin_repo = admin_repo
        self._learning_repo = learning_repo
        self._runtime_config = runtime_config
        self._settings = settings

    async def bootstrap_admin(self) -> None:
        await self._admin_repo.ensure_admin_user(
            username=self._settings.runtime.admin_username,
            password=self._settings.runtime.admin_password,
        )

    async def dashboard(self) -> dict:
        metrics = await self._learning_repo.get_dashboard_metrics()
        jobs = await self._admin_repo.list_recent_jobs()
        return {
            "metrics": metrics,
            "jobs": jobs,
        }

    async def list_users(self):
        return await self._admin_repo.list_users()

    async def list_job_runs(self, *, limit: int = 100) -> list[dict]:
        return await self._admin_repo.list_job_runs(limit=limit)

    async def list_delivery_logs(self, *, limit: int = 100) -> list[dict]:
        return await self._admin_repo.list_delivery_logs(limit=limit)

    async def list_settings(self):
        return await self._learning_repo.list_runtime_settings()

    async def update_setting(self, key: str, value: str) -> None:
        await self._learning_repo.upsert_runtime_setting(key=key, value=value)
        await self._runtime_config.refresh()

    async def effective_settings(self) -> dict:
        return self._runtime_config.effective_settings()

    async def list_groups(self) -> list[dict]:
        await self._seed_groups_from_config()
        groups = await self._admin_repo.list_groups()
        admin_group_ids = set(self._runtime_config.admin_group_ids())
        group_configs = await self._admin_repo.list_all_group_configs()
        config_map: dict[int, dict[str, str]] = {}
        for gc in group_configs:
            config_map.setdefault(gc.group_id, {})[gc.key] = gc.value
        return [
            {
                "id": group.id,
                "qq_group_id": group.qq_group_id,
                "name": group.name,
                "enabled": group.enabled,
                "is_admin": group.qq_group_id in admin_group_ids if _is_onebot_group_id(group.qq_group_id) else False,
                "platform": "feishu" if _is_feishu_group_id(group.qq_group_id) else "onebot",
                "render_mode": config_map.get(group.id, {}).get("message.render_mode", ""),
                "updated_at": group.updated_at,
            }
            for group in groups
        ]

    async def save_group(
        self,
        *,
        group_id: int | None,
        qq_group_id: str,
        name: str,
        enabled: bool,
        is_admin: bool,
        render_mode: str = "",
    ) -> None:
        qq_group_id = qq_group_id.strip()
        if not _is_supported_group_id(qq_group_id):
            raise ValueError("群号必须是纯数字，或使用 oc_ 开头的飞书群 ID。")

        existing_groups = await self._admin_repo.list_groups()
        old_group_id = None
        if group_id is not None:
            for group in existing_groups:
                if group.id == group_id:
                    old_group_id = group.qq_group_id
                    break

        saved_group = await self._admin_repo.save_group(
            group_id=group_id,
            qq_group_id=qq_group_id,
            name=name.strip(),
            enabled=enabled,
        )
        all_groups = await self._admin_repo.list_groups()
        enabled_group_ids = [group.qq_group_id for group in all_groups if group.enabled and _is_onebot_group_id(group.qq_group_id)]
        feishu_enabled_group_ids = [
            group.qq_group_id for group in all_groups if group.enabled and _is_feishu_group_id(group.qq_group_id)
        ]

        admin_group_ids = set(self._runtime_config.admin_group_ids())
        if old_group_id:
            admin_group_ids.discard(old_group_id)
        admin_group_ids.discard(saved_group.qq_group_id)
        if is_admin and _is_onebot_group_id(saved_group.qq_group_id):
            admin_group_ids.add(saved_group.qq_group_id)
        known_group_ids = {group.qq_group_id for group in all_groups if _is_onebot_group_id(group.qq_group_id)}
        admin_group_ids &= known_group_ids

        await self._learning_repo.upsert_runtime_setting(
            key="bot.enabled_group_ids",
            value=self._dump_yaml(enabled_group_ids),
        )
        await self._learning_repo.upsert_runtime_setting(
            key="feishu.enabled_group_ids",
            value=self._dump_yaml(feishu_enabled_group_ids),
        )
        await self._learning_repo.upsert_runtime_setting(
            key="bot.admin_group_ids",
            value=self._dump_yaml(sorted(admin_group_ids)),
        )

        if render_mode:
            await self._admin_repo.upsert_group_config(
                group_id=saved_group.id, key="message.render_mode", value=render_mode,
            )
        else:
            await self._admin_repo.delete_group_config(
                group_id=saved_group.id, key="message.render_mode",
            )

        await self._runtime_config.refresh()

    async def _seed_groups_from_config(self) -> None:
        seed_ids = set(self._settings.static.bot.enabled_group_ids) | set(self._runtime_config.enabled_group_ids())
        seed_ids |= set(self._settings.static.bot.admin_group_ids) | set(self._runtime_config.admin_group_ids())
        seed_ids |= set(self._settings.static.feishu.enabled_group_ids) | set(self._runtime_config.feishu_enabled_group_ids())
        for qq_group_id in sorted(seed_ids):
            if qq_group_id:
                enabled = self._runtime_config.is_enabled_chat(qq_group_id)
                await self._admin_repo.ensure_group(qq_group_id=qq_group_id, enabled=enabled)

    @staticmethod
    def _dump_yaml(value) -> str:
        return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()


def _is_feishu_group_id(group_id: str) -> bool:
    return group_id.startswith("oc_")


def _is_onebot_group_id(group_id: str) -> bool:
    return group_id.isdigit()


def _is_supported_group_id(group_id: str) -> bool:
    return _is_onebot_group_id(group_id) or _is_feishu_group_id(group_id)
