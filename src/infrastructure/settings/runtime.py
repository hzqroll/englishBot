from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from src.infrastructure.db.repositories.admin import AdminRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.settings.models import EffectiveSettings


@dataclass(slots=True)
class RuntimeConfigService:
    settings: EffectiveSettings
    learning_repo: LearningRepository
    admin_repo: AdminRepository
    _cache: dict[str, Any] = field(default_factory=dict, init=False)
    _group_cache: dict[int, dict[str, Any]] = field(default_factory=dict, init=False)

    async def refresh(self) -> None:
        rows = await self.learning_repo.list_runtime_settings()
        self._cache = {}
        for row in rows:
            self._cache[row.key] = self._parse_value(row.value)

        self._group_cache = {}
        group_configs = await self.admin_repo.list_all_group_configs()
        for gc in group_configs:
            if gc.group_id not in self._group_cache:
                self._group_cache[gc.group_id] = {}
            self._group_cache[gc.group_id][gc.key] = self._parse_value(gc.value)

    def is_feishu_enabled(self) -> bool:
        return self._get("feishu.enabled", self.settings.static.feishu.enabled)

    def feishu_enabled_group_ids(self) -> list[str]:
        return self._get("feishu.enabled_group_ids", self.settings.static.feishu.enabled_group_ids)

    def is_enabled_chat(self, chat_id: str) -> bool:
        enabled_ids = self.feishu_enabled_group_ids()
        return not enabled_ids or chat_id in enabled_ids

    def is_message_translation_enabled(self) -> bool:
        return self._get("message.translation_enabled", False)

    def daily_review_insert_count(self) -> int:
        return self._get("learning.daily_review_insert_count", self.settings.static.learning.daily_review_insert_count)

    def weekly_quiz_question_count(self) -> int:
        return self._get("learning.weekly_quiz_question_count", self.settings.static.learning.weekly_quiz_question_count)

    def weekly_quiz_review_ratio(self) -> float:
        return self._get("learning.weekly_quiz_review_ratio", self.settings.static.learning.weekly_quiz_review_ratio)

    def group_dialogue_trigger_min_sentences(self) -> int:
        return self._get(
            "message.group_dialogue_trigger_min_sentences",
            self.settings.static.feishu.context_ttl_minutes,
        )

    def cron(self, key: str) -> str:
        defaults = {
            "scheduler.daily_push_cron": self.settings.static.scheduler.daily_push_cron,
            "scheduler.midday_baton_cron": self.settings.static.scheduler.midday_baton_cron,
            "scheduler.evening_baton_cron": self.settings.static.scheduler.evening_baton_cron,
            "scheduler.daily_error_digest_cron": self.settings.static.scheduler.daily_error_digest_cron,
            "scheduler.daily_progress_cron": self.settings.static.scheduler.daily_progress_cron,
            "scheduler.daily_summary_cron": self.settings.static.scheduler.daily_summary_cron,
            "scheduler.weekly_report_cron": self.settings.static.scheduler.weekly_report_cron,
            "scheduler.weekly_quiz_cron": self.settings.static.scheduler.weekly_quiz_cron,
            "scheduler.nightly_backup_cron": self.settings.static.scheduler.nightly_backup_cron,
            "friends.daily_push_cron": self.settings.static.friends.daily_push_cron,
            "scheduler.sync_feishu_messages_cron": self.settings.static.scheduler.sync_feishu_messages_cron,
        }
        return self._get(key, defaults[key])

    def effective_settings(self) -> dict[str, Any]:
        return {
            "feishu.enabled": self.is_feishu_enabled(),
            "feishu.enabled_group_ids": self.feishu_enabled_group_ids(),
            "message.translation_enabled": self.is_message_translation_enabled(),
            "learning.daily_review_insert_count": self.daily_review_insert_count(),
            "learning.weekly_quiz_question_count": self.weekly_quiz_question_count(),
            "learning.weekly_quiz_review_ratio": self.weekly_quiz_review_ratio(),
            "scheduler.daily_push_cron": self.cron("scheduler.daily_push_cron"),
            "scheduler.midday_baton_cron": self.cron("scheduler.midday_baton_cron"),
            "scheduler.evening_baton_cron": self.cron("scheduler.evening_baton_cron"),
            "scheduler.daily_error_digest_cron": self.cron("scheduler.daily_error_digest_cron"),
            "scheduler.daily_progress_cron": self.cron("scheduler.daily_progress_cron"),
            "scheduler.daily_summary_cron": self.cron("scheduler.daily_summary_cron"),
            "scheduler.weekly_report_cron": self.cron("scheduler.weekly_report_cron"),
            "scheduler.weekly_quiz_cron": self.cron("scheduler.weekly_quiz_cron"),
            "scheduler.nightly_backup_cron": self.cron("scheduler.nightly_backup_cron"),
        }

    def _get(self, key: str, default: Any) -> Any:
        value = self._cache.get(key, default)
        if isinstance(default, tuple):
            return list(value)
        return value

    def _parse_value(self, value: str) -> Any:
        try:
            return yaml.safe_load(value)
        except Exception:
            return value
