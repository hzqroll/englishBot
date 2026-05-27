from __future__ import annotations

import sys
from datetime import date, datetime, timezone
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
        return ["oc_guardian_test"]


class _LearningRepoStub:
    def __init__(self) -> None:
        self.finish_calls: list[tuple[str, str, str]] = []
        self.lesson_detail = None
        self.lock_calls: list[tuple[str, str, bool]] = []

    async def acquire_job_lock(self, *, job_name: str, biz_key: str, force: bool = False) -> bool:
        self.lock_calls.append((job_name, biz_key, force))
        return True

    async def finish_job_lock(self, *, job_name: str, biz_key: str, status: str) -> None:
        self.finish_calls.append((job_name, biz_key, status))

    async def get_today_lesson_detail(self, *, group_id: int, biz_date: date):
        return self.lesson_detail


@pytest.mark.asyncio
async def test_dialogue_guardian_job_sends_envelope(monkeypatch) -> None:
    send_calls: list[dict] = []
    build_lesson_calls: list[tuple[str, date]] = []
    guardian_calls: list[tuple[str, datetime]] = []
    learning_repo = _LearningRepoStub()

    async def _ensure_group(chat_id: str):
        return SimpleNamespace(id=17, chat_id=chat_id)

    async def _build_today_lesson(*, chat_id: str, biz_date: date | None = None):
        build_lesson_calls.append((chat_id, biz_date or date.today()))

    async def _build_conversation_guardian_envelope(*, chat_id: str, now: datetime | None = None):
        assert now is not None
        guardian_calls.append((chat_id, now))
        return MessageEnvelope(plain_text="Story paragraph.\n\nHow would you continue this scene?")

    async def _fake_get_or_init_container():
        return SimpleNamespace(
            runtime_config=_RuntimeConfigStub(),
            learning_repo=learning_repo,
            identity_repo=SimpleNamespace(ensure_group=_ensure_group),
            learning_usecase=SimpleNamespace(build_today_lesson=_build_today_lesson),
            daily_session_usecase=SimpleNamespace(build_conversation_guardian_envelope=_build_conversation_guardian_envelope),
        )

    async def _fake_send_group_envelope(**kwargs):
        send_calls.append(kwargs)
        return True

    monkeypatch.setattr(scheduler, "get_or_init_container", _fake_get_or_init_container)
    monkeypatch.setattr(scheduler, "_send_group_envelope", _fake_send_group_envelope)

    run_now = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    await scheduler.dialogue_guardian_job(now=run_now, force_run=True)

    assert build_lesson_calls == [("oc_guardian_test", date(2026, 4, 20))]
    assert guardian_calls == [("oc_guardian_test", run_now)]
    assert len(send_calls) == 1
    assert send_calls[0]["group_id"] == "oc_guardian_test"
    assert send_calls[0]["job_name"] == "dialogue_guardian"
    assert send_calls[0]["mention_user_id"] is None
    assert learning_repo.lock_calls[0][0] == "dialogue_guardian"
    assert learning_repo.finish_calls[0][0] == "dialogue_guardian"
    assert learning_repo.finish_calls[0][2] == "success"


@pytest.mark.asyncio
async def test_dialogue_guardian_job_skips_when_no_envelope(monkeypatch) -> None:
    send_calls: list[dict] = []
    learning_repo = _LearningRepoStub()

    async def _ensure_group(chat_id: str):
        return SimpleNamespace(id=17, chat_id=chat_id)

    async def _build_today_lesson(*, chat_id: str, biz_date: date | None = None):
        return None

    async def _build_conversation_guardian_envelope(*, chat_id: str, now: datetime | None = None):
        return None

    async def _fake_get_or_init_container():
        return SimpleNamespace(
            runtime_config=_RuntimeConfigStub(),
            learning_repo=learning_repo,
            identity_repo=SimpleNamespace(ensure_group=_ensure_group),
            learning_usecase=SimpleNamespace(build_today_lesson=_build_today_lesson),
            daily_session_usecase=SimpleNamespace(build_conversation_guardian_envelope=_build_conversation_guardian_envelope),
        )

    async def _fake_send_group_envelope(**kwargs):
        send_calls.append(kwargs)
        return True

    monkeypatch.setattr(scheduler, "get_or_init_container", _fake_get_or_init_container)
    monkeypatch.setattr(scheduler, "_send_group_envelope", _fake_send_group_envelope)

    await scheduler.dialogue_guardian_job(now=datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc), force_run=True)

    assert send_calls == []
    assert learning_repo.finish_calls[0][0] == "dialogue_guardian"
    assert learning_repo.finish_calls[0][2] == "success"
