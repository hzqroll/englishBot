from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.application.admin_usecases import (
    _is_feishu_group_id,
    _is_onebot_group_id,
    _is_supported_group_id,
)
from src.infrastructure.settings.models import AppRuntimeSettings, EffectiveSettings, StaticConfig
from src.infrastructure.settings.runtime import RuntimeConfigService


class _LearningRepoStub:
    async def list_runtime_settings(self):
        return [
            SimpleNamespace(key="bot.enabled_group_ids", value='["204257012"]'),
            SimpleNamespace(key="feishu.enabled_group_ids", value='["oc_test_group"]'),
        ]


class _AdminRepoStub:
    async def list_all_group_configs(self):
        return []


@pytest.mark.asyncio
async def test_runtime_config_handles_onebot_and_feishu_groups(tmp_path: Path) -> None:
    settings = EffectiveSettings(
        runtime=AppRuntimeSettings(),
        static=StaticConfig(),
        project_root=tmp_path,
        template_dir=tmp_path,
        static_dir=tmp_path,
    )
    runtime_config = RuntimeConfigService(
        settings=settings,
        learning_repo=_LearningRepoStub(),
        admin_repo=_AdminRepoStub(),
    )

    await runtime_config.refresh()

    assert runtime_config.enabled_group_ids() == ["204257012"]
    assert runtime_config.feishu_enabled_group_ids() == ["oc_test_group"]
    assert runtime_config.is_enabled_chat("204257012") is True
    assert runtime_config.is_enabled_chat("oc_test_group") is True
    assert runtime_config.is_enabled_chat("999999999") is False


def test_group_identifier_helpers_support_feishu_and_onebot() -> None:
    assert _is_onebot_group_id("204257012")
    assert not _is_onebot_group_id("oc_test_group")
    assert _is_feishu_group_id("oc_test_group")
    assert not _is_feishu_group_id("204257012")
    assert _is_supported_group_id("204257012")
    assert _is_supported_group_id("oc_test_group")
    assert not _is_supported_group_id("chat_test_group")
