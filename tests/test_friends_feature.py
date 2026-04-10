from __future__ import annotations

import sys
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from src.application.friends_usecases import FriendsUseCase
from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
from src.infrastructure.providers.friends_transcript import DialogueLine, FriendsSegment

sys.modules.setdefault(
    "nonebot_plugin_apscheduler",
    SimpleNamespace(scheduler=SimpleNamespace(add_job=lambda *args, **kwargs: None)),
)

from src.plugins import scheduler


class _FriendsProviderStub:
    def __init__(self) -> None:
        self.calls: list[tuple[date, date]] = []
        self.segment = FriendsSegment(
            season=1,
            episode=1,
            title="Pilot",
            lines=[
                DialogueLine(speaker="Monica", text="Welcome."),
                DialogueLine(speaker="Rachel", text="Hi!"),
            ],
        )

    def get_segment(self, biz_date: date, start_date: date) -> FriendsSegment:
        self.calls.append((biz_date, start_date))
        return self.segment


class _LLMStub:
    def __init__(
        self,
        *,
        api_key: str = "key",
        base_url: str = "https://example.test/v1",
        model: str = "demo-model",
        response: dict | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._model = model
        self.calls: list[dict] = []
        self.response = response or {}

    async def _chat_json(
        self,
        *,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        timeout: float | None = None,
    ) -> dict:
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": timeout,
            }
        )
        return self.response


class _LearningRepoStub:
    def __init__(self) -> None:
        self.finish_calls: list[tuple[str, str, str]] = []

    async def acquire_job_lock(self, *, job_name: str, biz_key: str, force: bool = False) -> bool:
        return True

    async def finish_job_lock(self, *, job_name: str, biz_key: str, status: str) -> None:
        self.finish_calls.append((job_name, biz_key, status))


class _RuntimeConfigStub:
    def __init__(self, chat_ids: list[str]) -> None:
        self._chat_ids = chat_ids

    async def refresh(self) -> None:
        return None

    def feishu_enabled_group_ids(self) -> list[str]:
        return list(self._chat_ids)


class _FriendsUseCaseStub:
    def __init__(self, envelope: MessageEnvelope, provider: _FriendsProviderStub) -> None:
        self.envelope = envelope
        self.provider = provider
        self.calls: list[tuple[date, date]] = []

    async def build_daily_friends_envelope(self, *, biz_date: date, start_date: date) -> MessageEnvelope:
        self.calls.append((biz_date, start_date))
        return self.envelope


def _build_container(
    *,
    docs_service: object | None,
    start_date: str,
    envelope: MessageEnvelope | None = None,
    chat_ids: list[str] | None = None,
):
    provider = _FriendsProviderStub()
    friends_envelope = envelope or MessageEnvelope(
        plain_text="friends content",
        card_document=CardDocument(
            title="Friends S01E01 - Pilot",
            sections=[CardSection(title="Dialogue", lines=["Monica: Welcome."])],
        ),
        card_type="friends_dialogue",
    )
    friends_usecase = _FriendsUseCaseStub(friends_envelope, provider)
    return SimpleNamespace(
        friends_usecase=friends_usecase,
        runtime_config=_RuntimeConfigStub(chat_ids or ["oc_1", "oc_2"]),
        learning_repo=_LearningRepoStub(),
        channels={"feishu": object()},
        feishu_docs_service=docs_service,
        settings=SimpleNamespace(
            static=SimpleNamespace(
                friends=SimpleNamespace(start_date=start_date),
            )
        ),
    )


@pytest.mark.asyncio
async def test_build_daily_friends_envelope_uses_provider_timeout() -> None:
    provider = _FriendsProviderStub()
    llm = _LLMStub(
        response={
            "translation": "Monica: 欢迎。\nRachel: 你好！",
            "vocabulary": ["welcome /welkəm/ - 欢迎"],
            "grammar": ["祈使句: welcome 用于招呼"],
            "culture": ["朋友见面时会用简短寒暄开场"],
        }
    )
    usecase = FriendsUseCase(
        friends_provider=provider,
        llm_provider=llm,
    )

    envelope = await usecase.build_daily_friends_envelope(
        biz_date=date(2026, 4, 8),
        start_date=date(2026, 4, 8),
    )

    assert llm.calls and llm.calls[0]["timeout"] == 60.0
    assert envelope.card_document is not None
    assert [section.title for section in envelope.card_document.sections] == [
        "Dialogue",
        "中文翻译",
        "重点词汇",
        "语法解析",
        "文化背景",
    ]


@pytest.mark.asyncio
async def test_build_daily_friends_envelope_skips_analysis_when_llm_config_incomplete() -> None:
    provider = _FriendsProviderStub()
    llm = _LLMStub(api_key="key", base_url="", model="")
    usecase = FriendsUseCase(
        friends_provider=provider,
        llm_provider=llm,
    )

    envelope = await usecase.build_daily_friends_envelope(
        biz_date=date(2026, 4, 8),
        start_date=date(2026, 4, 8),
    )

    assert llm.calls == []
    assert envelope.card_document is not None
    assert [section.title for section in envelope.card_document.sections] == ["Dialogue"]


@pytest.mark.asyncio
async def test_daily_friends_job_sends_doc_link_via_shared_delivery(monkeypatch) -> None:
    container = _build_container(
        docs_service=object(),
        start_date=date.today().isoformat(),
    )
    send_calls: list[dict] = []

    async def _fake_get_or_init_container():
        return container

    async def _fake_save_friends_to_docs(**kwargs):
        return "https://example.test/docx/abc123"

    async def _fake_send_group_envelope(**kwargs):
        send_calls.append(kwargs)

    monkeypatch.setattr(scheduler, "get_or_init_container", _fake_get_or_init_container)
    monkeypatch.setattr(scheduler, "get_bots", lambda: {})
    monkeypatch.setattr(scheduler, "_save_friends_to_docs", _fake_save_friends_to_docs)
    monkeypatch.setattr(scheduler, "_send_group_envelope", _fake_send_group_envelope)

    await scheduler.daily_friends_job()

    assert [call["group_id"] for call in send_calls] == ["oc_1", "oc_2"]
    assert all(call["job_name"] == "friends_dialogue" for call in send_calls)
    assert all(call["envelope"].card_document is None for call in send_calls)
    assert all("今日学习内容已更新" in call["envelope"].plain_text for call in send_calls)
    assert container.learning_repo.finish_calls[-1][2] == "success"


@pytest.mark.asyncio
async def test_daily_friends_job_falls_back_to_full_content_without_docs(monkeypatch) -> None:
    container = _build_container(
        docs_service=None,
        start_date=date.today().isoformat(),
    )
    send_calls: list[dict] = []

    async def _fake_get_or_init_container():
        return container

    async def _fake_send_group_envelope(**kwargs):
        send_calls.append(kwargs)

    monkeypatch.setattr(scheduler, "get_or_init_container", _fake_get_or_init_container)
    monkeypatch.setattr(scheduler, "get_bots", lambda: {})
    monkeypatch.setattr(scheduler, "_send_group_envelope", _fake_send_group_envelope)

    await scheduler.daily_friends_job()

    assert [call["group_id"] for call in send_calls] == ["oc_1", "oc_2"]
    assert all(call["envelope"] is container.friends_usecase.envelope for call in send_calls)
    assert container.learning_repo.finish_calls[-1][2] == "success"


@pytest.mark.asyncio
async def test_daily_friends_job_falls_back_to_full_content_when_doc_write_fails(monkeypatch) -> None:
    container = _build_container(
        docs_service=object(),
        start_date=date.today().isoformat(),
    )
    send_calls: list[dict] = []

    async def _fake_get_or_init_container():
        return container

    async def _fake_save_friends_to_docs(**kwargs):
        return None

    async def _fake_send_group_envelope(**kwargs):
        send_calls.append(kwargs)

    monkeypatch.setattr(scheduler, "get_or_init_container", _fake_get_or_init_container)
    monkeypatch.setattr(scheduler, "get_bots", lambda: {})
    monkeypatch.setattr(scheduler, "_save_friends_to_docs", _fake_save_friends_to_docs)
    monkeypatch.setattr(scheduler, "_send_group_envelope", _fake_send_group_envelope)

    await scheduler.daily_friends_job()

    assert [call["group_id"] for call in send_calls] == ["oc_1", "oc_2"]
    assert all(call["envelope"] is container.friends_usecase.envelope for call in send_calls)
    assert container.learning_repo.finish_calls[-1][2] == "success"


@pytest.mark.asyncio
async def test_daily_friends_job_skips_before_start_date(monkeypatch) -> None:
    container = _build_container(
        docs_service=None,
        start_date=(date.today() + timedelta(days=1)).isoformat(),
    )
    send_calls: list[dict] = []

    async def _fake_get_or_init_container():
        return container

    async def _fake_send_group_envelope(**kwargs):
        send_calls.append(kwargs)

    monkeypatch.setattr(scheduler, "get_or_init_container", _fake_get_or_init_container)
    monkeypatch.setattr(scheduler, "get_bots", lambda: {})
    monkeypatch.setattr(scheduler, "_send_group_envelope", _fake_send_group_envelope)

    await scheduler.daily_friends_job()

    assert send_calls == []
    assert container.learning_repo.finish_calls[-1][2] == "success"
