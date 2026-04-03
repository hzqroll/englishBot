from __future__ import annotations

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

    async def list_settings(self):
        return await self._learning_repo.list_runtime_settings()

    async def update_setting(self, key: str, value: str) -> None:
        await self._learning_repo.upsert_runtime_setting(key=key, value=value)
        await self._runtime_config.refresh()

    async def effective_settings(self) -> dict:
        return self._runtime_config.effective_settings()
