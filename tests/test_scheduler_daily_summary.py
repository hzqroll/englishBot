from __future__ import annotations

import sys
from datetime import date
from types import SimpleNamespace

import pytest

from src.domain.value_objects.messaging import MessageEnvelope

sys.modules.setdefault(
    "nonebot_plugin_apscheduler",
    SimpleNamespace(scheduler=SimpleNamespace(add_job=lambda *args, **kwargs: None)),
)

from src.plugins import scheduler


class _RuntimeConfigStub:
    async def refresh(self) -> None:
        return None

    def is_feishu_enabled(self) -> bool:
        return True

    def feishu_enabled_group_ids(self) -> list[str]:
        return ["oc_test"]


class _LearningRepoStub:
    def __init__(self) -> None:
        self.finish_calls: list[tuple[str, str, str]] = []

    async def acquire_job_lock(self, *, job_name: str, biz_key: str, force: bool = False) -> bool:
        return True

    async def finish_job_lock(self, *, job_name: str, biz_key: str, status: str) -> None:
        self.finish_calls.append((job_name, biz_key, status))


@pytest.mark.asyncio
async def test_daily_summary_job_sends_group_cards_without_mentions(monkeypatch) -> None:
    send_calls: list[dict] = []

    async def _ensure_group(chat_id: str):
        return SimpleNamespace(id=7, chat_id=chat_id)

    async def _list_group_active_users(group_id: int):
        assert group_id == 7
        return [SimpleNamespace(id=11, open_id="ou_user_1", nickname="User1")]

    async def _build_daily_summary_envelope(*, chat_id: str, open_id: str, nickname: str, target_date):
        assert chat_id == "oc_test"
        assert open_id == "ou_user_1"
        assert nickname == "User1"
        assert target_date == date(2026, 4, 14)
        return MessageEnvelope(plain_text="summary")

    async def _fake_get_or_init_container():
        return SimpleNamespace(
            runtime_config=_RuntimeConfigStub(),
            learning_repo=_LearningRepoStub(),
            identity_repo=SimpleNamespace(
                ensure_group=_ensure_group,
                list_group_active_users=_list_group_active_users,
            ),
            report_usecase=SimpleNamespace(build_daily_summary_envelope=_build_daily_summary_envelope),
        )

    async def _fake_send_group_envelope(**kwargs):
        send_calls.append(kwargs)
        return True

    monkeypatch.setattr(scheduler, "get_or_init_container", _fake_get_or_init_container)
    monkeypatch.setattr(scheduler, "_send_group_envelope", _fake_send_group_envelope)

    await scheduler.daily_summary_job(target_date=date(2026, 4, 14), force_run=True)

    assert len(send_calls) == 1
    assert send_calls[0]["group_id"] == "oc_test"
    assert send_calls[0]["mention_user_id"] is None
    assert send_calls[0]["job_name"] == "daily_summary"
    assert send_calls[0]["user_id"] == 11
