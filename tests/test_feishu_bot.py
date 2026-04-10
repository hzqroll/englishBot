from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.domain.value_objects.messaging import MessageEnvelope
from src.infrastructure.channels.feishu_bot import FeishuBot


class _RuntimeConfigStub:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self.calls: list[str] = []

    def is_enabled_chat(self, group_id: str) -> bool:
        self.calls.append(group_id)
        return self.enabled

    def is_feishu_enabled(self) -> bool:
        return True


class _FakeFeishuChannel:
    def __init__(self) -> None:
        self.sent_envelopes: list[tuple[str, MessageEnvelope]] = []
        self.sent_texts: list[tuple[str, str]] = []

    async def send_envelope(self, chat_id: str, envelope: MessageEnvelope) -> None:
        self.sent_envelopes.append((chat_id, envelope))

    async def send_text(self, chat_id: str, text: str) -> None:
        self.sent_texts.append((chat_id, text))

    def create_streaming_card_sync(self, chat_id: str, *, title: str = "English Bot") -> str | None:
        return None  # streaming not available in test stub

    def update_streaming_card_sync(self, card_id: str, content: str, sequence: int) -> bool:
        return False

    async def finalize_streaming_card(self, card_id: str, reply: str, sequence: int) -> bool:
        return False


class _ContainerStub:
    def __init__(self, *, enabled: bool = True) -> None:
        self.runtime_config = _RuntimeConfigStub(enabled=enabled)
        self.channels = {"feishu": _FakeFeishuChannel()}
        self.group_dialogue_store = SimpleNamespace(append_group_message=lambda **kw: None)

        async def _handle_at_message(ctx, *, stream_callback=None):
            return "mock reply"

        self.message_usecase = SimpleNamespace(handle_at_message=_handle_at_message)
        self.conversation_usecase = SimpleNamespace(observe_passive_group_message=lambda *a, **kw: None)


def _build_bot(*, enabled_chat_ids: list[str] | None = None, main_loop=None) -> FeishuBot:
    bot = object.__new__(FeishuBot)
    bot._enabled_chat_ids = set(enabled_chat_ids) if enabled_chat_ids else None
    bot._main_loop = main_loop
    return bot


@pytest.mark.asyncio
async def test_analysis_control_text_without_mention_routes_to_command_handler(monkeypatch) -> None:
    import src.infrastructure.channels.feishu_bot as module

    container = _ContainerStub()
    command_calls: list[dict] = []

    async def _fake_handle_fixed_command_text(**kwargs):
        command_calls.append(kwargs)
        return MessageEnvelope(plain_text="analysis result")

    monkeypatch.setattr(module, "get_container", lambda: container)
    monkeypatch.setattr(module, "FeishuChannel", _FakeFeishuChannel)
    monkeypatch.setattr(module, "handle_fixed_command_text", _fake_handle_fixed_command_text)

    bot = _build_bot()

    await bot._dispatch(
        raw_event_id="evt-1",
        chat_id="oc_chat_1",
        user_id="u1",
        nickname="tester",
        text="分析最近聊天内容",
        is_mention=False,
    )

    assert command_calls == [
        {
            "group_id": "oc_chat_1",
            "group_name": "",
            "user_id": "u1",
            "nickname": "tester",
            "text": "分析最近聊天内容",
            "raw_event_id": "evt-1",
            "container": container,
        }
    ]
    assert container.channels["feishu"].sent_envelopes == [
        ("oc_chat_1", MessageEnvelope(plain_text="analysis result"))
    ]
    assert container.runtime_config.calls == ["oc_chat_1"]


@pytest.mark.asyncio
async def test_dispatch_ignores_disabled_chat_id(monkeypatch) -> None:
    import src.infrastructure.channels.feishu_bot as module

    container = _ContainerStub()
    command_calls: list[dict] = []

    async def _fake_handle_fixed_command_text(**kwargs):
        command_calls.append(kwargs)
        return MessageEnvelope(plain_text="should not send")

    monkeypatch.setattr(module, "get_container", lambda: container)
    monkeypatch.setattr(module, "FeishuChannel", _FakeFeishuChannel)
    monkeypatch.setattr(module, "handle_fixed_command_text", _fake_handle_fixed_command_text)

    bot = _build_bot(enabled_chat_ids=["oc_allowed"])

    await bot._dispatch(
        raw_event_id="evt-2",
        chat_id="oc_blocked",
        user_id="u1",
        nickname="tester",
        text="分析最近聊天内容",
        is_mention=False,
    )

    assert command_calls == []
    assert container.channels["feishu"].sent_envelopes == []
    assert container.runtime_config.calls == []


def test_dispatch_sync_submits_coroutine_to_main_loop(monkeypatch) -> None:
    import src.infrastructure.channels.feishu_bot as module

    submitted: dict[str, object] = {}

    class _LoopStub:
        def is_running(self) -> bool:
            return True

    class _FutureStub:
        def __init__(self) -> None:
            self.callback = None

        def add_done_callback(self, callback) -> None:
            self.callback = callback

    def _fake_run_coroutine_threadsafe(coro, loop):
        submitted["loop"] = loop
        submitted["coro_name"] = coro.cr_code.co_name
        coro.close()
        future = _FutureStub()
        submitted["future"] = future
        return future

    monkeypatch.setattr(module.asyncio, "run_coroutine_threadsafe", _fake_run_coroutine_threadsafe)

    bot = _build_bot(main_loop=_LoopStub())

    bot._dispatch_sync(
        raw_event_id="evt-3",
        chat_id="oc_chat_1",
        user_id="u1",
        nickname="tester",
        text="分析最近聊天内容",
        is_mention=False,
    )

    assert submitted["loop"] is bot._main_loop
    assert submitted["coro_name"] == "_dispatch"
    assert submitted["future"].callback == bot._log_dispatch_failure
