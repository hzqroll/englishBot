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

    def enabled_group_ids(self) -> list[str]:
        return self._get("bot.enabled_group_ids", self.settings.static.bot.enabled_group_ids)

    def admin_group_ids(self) -> list[str]:
        return self._get("bot.admin_group_ids", self.settings.static.bot.admin_group_ids)

    def feishu_enabled_group_ids(self) -> list[str]:
        return self._get("feishu.enabled_group_ids", self.settings.static.feishu.enabled_group_ids)

    def is_enabled_chat(self, group_id: str) -> bool:
        if group_id.startswith("oc_"):
            enabled_ids = self.feishu_enabled_group_ids()
        else:
            enabled_ids = self.enabled_group_ids()
        return not enabled_ids or group_id in enabled_ids

    def daily_review_insert_count(self) -> int:
        return self._get("learning.daily_review_insert_count", self.settings.static.learning.daily_review_insert_count)

    def weekly_quiz_question_count(self) -> int:
        return self._get("learning.weekly_quiz_question_count", self.settings.static.learning.weekly_quiz_question_count)

    def weekly_quiz_review_ratio(self) -> float:
        return self._get("learning.weekly_quiz_review_ratio", self.settings.static.learning.weekly_quiz_review_ratio)

    def render_mode(self) -> str:
        return self._get("message.render_mode", self.settings.static.message.render_mode)

    def enable_task_cards(self) -> bool:
        return self._get("message.enable_task_cards", self.settings.static.message.enable_task_cards)

    def card_fallback_to_text(self) -> bool:
        return self._get("message.card_fallback_to_text", self.settings.static.message.card_fallback_to_text)

    def group_dialogue_trigger_min_sentences(self) -> int:
        return self._get(
            "message.group_dialogue_trigger_min_sentences",
            self.settings.static.message.group_dialogue_trigger_min_sentences,
        )

    def render_mode_for_group(self, group_id: str) -> str:
        try:
            gid = int(group_id)
        except (ValueError, TypeError):
            return self.render_mode()
        group_overrides = self._group_cache.get(gid)
        if group_overrides and "message.render_mode" in group_overrides:
            return group_overrides["message.render_mode"]
        return self.render_mode()

    def cron(self, key: str) -> str:
        defaults = {
            "scheduler.daily_push_cron": self.settings.static.scheduler.daily_push_cron,
            "scheduler.daily_error_digest_cron": self.settings.static.scheduler.daily_error_digest_cron,
            "scheduler.daily_progress_cron": self.settings.static.scheduler.daily_progress_cron,
            "scheduler.weekly_report_cron": self.settings.static.scheduler.weekly_report_cron,
            "scheduler.weekly_quiz_cron": self.settings.static.scheduler.weekly_quiz_cron,
            "scheduler.nightly_backup_cron": self.settings.static.scheduler.nightly_backup_cron,
            "friends.daily_push_cron": self.settings.static.friends.daily_push_cron,
        }
        return self._get(key, defaults[key])

    def effective_settings(self) -> dict[str, Any]:
        return {
            "bot.enabled_group_ids": self.enabled_group_ids(),
            "bot.admin_group_ids": self.admin_group_ids(),
            "feishu.enabled_group_ids": self.feishu_enabled_group_ids(),
            "learning.daily_review_insert_count": self.daily_review_insert_count(),
            "learning.weekly_quiz_question_count": self.weekly_quiz_question_count(),
            "learning.weekly_quiz_review_ratio": self.weekly_quiz_review_ratio(),
            "message.render_mode": self.render_mode(),
            "message.enable_task_cards": self.enable_task_cards(),
            "message.card_fallback_to_text": self.card_fallback_to_text(),
            "message.group_dialogue_trigger_min_sentences": self.group_dialogue_trigger_min_sentences(),
            "scheduler.daily_push_cron": self.cron("scheduler.daily_push_cron"),
            "scheduler.daily_error_digest_cron": self.cron("scheduler.daily_error_digest_cron"),
            "scheduler.daily_progress_cron": self.cron("scheduler.daily_progress_cron"),
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
