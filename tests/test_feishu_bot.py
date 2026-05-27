from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.domain.value_objects.messaging import MessageEnvelope
from src.infrastructure.channels.feishu_bot import FeishuBot


class _RuntimeConfigStub:
    def __init__(self, *, enabled: bool = True, translation_enabled: bool = True) -> None:
        self.enabled = enabled
        self.translation_enabled = translation_enabled
        self.calls: list[str] = []

    def is_enabled_chat(self, group_id: str) -> bool:
        self.calls.append(group_id)
        return self.enabled

    def is_feishu_enabled(self) -> bool:
        return True

    def is_message_translation_enabled(self) -> bool:
        return self.translation_enabled


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
    def __init__(self, *, enabled: bool = True, translation_enabled: bool = True, at_reply: str | None = "mock reply") -> None:
        self.runtime_config = _RuntimeConfigStub(enabled=enabled, translation_enabled=translation_enabled)
        self.channels = {"feishu": _FakeFeishuChannel()}
        self.group_dialogue_appends: list[dict] = []
        self.group_dialogue_store = SimpleNamespace(append_group_message=lambda **kw: self.group_dialogue_appends.append(kw))
        self.at_calls: list[dict] = []
        self.passive_calls: list[dict] = []
        self.card_actions: list[tuple[str, str, str, object]] = []

        async def _handle_at_message(ctx, *, stream_callback=None, translation_enabled=True):
            self.at_calls.append(
                {
                    "raw_event_id": ctx.raw_event_id,
                    "group_id": ctx.group_id,
                    "user_id": ctx.user_id,
                    "message_text": ctx.message_text,
                    "translation_enabled": translation_enabled,
                    "streaming": stream_callback is not None,
                }
            )
            return at_reply

        self.message_usecase = SimpleNamespace(handle_at_message=_handle_at_message)

        async def _observe_passive_group_message(ctx):
            self.passive_calls.append(
                {
                    "raw_event_id": ctx.raw_event_id,
                    "group_id": ctx.group_id,
                    "user_id": ctx.user_id,
                    "message_text": ctx.message_text,
                    "message_type": ctx.message_type,
                }
            )

        self.conversation_usecase = SimpleNamespace(observe_passive_group_message=_observe_passive_group_message)

        async def _claim_baton(*, chat_id: str, actor_open_id: str, biz_date):
            self.card_actions.append(("claim_baton", chat_id, actor_open_id, biz_date))
            return f"claim:{chat_id}:{actor_open_id}:{biz_date.isoformat()}"

        async def _enter_rescue_mode(*, chat_id: str, actor_open_id: str, biz_date):
            self.card_actions.append(("enter_rescue", chat_id, actor_open_id, biz_date))
            return f"rescue:{chat_id}:{actor_open_id}:{biz_date.isoformat()}"

        async def _remind_later(*, chat_id: str, actor_open_id: str, biz_date):
            self.card_actions.append(("remind_later", chat_id, actor_open_id, biz_date))
            return f"later:{chat_id}:{actor_open_id}:{biz_date.isoformat()}"

        async def _weekly_doc_url(*, target_date):
            return f"https://example.com/week-{target_date.isoformat()}"

        self.daily_session_usecase = SimpleNamespace(
            claim_baton=_claim_baton,
            enter_rescue_mode=_enter_rescue_mode,
            remind_later=_remind_later,
        )
        self.feishu_docs_service = SimpleNamespace(get_weekly_doc_url=_weekly_doc_url)


def _build_bot(*, enabled_chat_ids: list[str] | None = None, main_loop=None) -> FeishuBot:
    bot = object.__new__(FeishuBot)
    bot._enabled_chat_ids = set(enabled_chat_ids) if enabled_chat_ids else None
    bot._main_loop = main_loop
    return bot


@pytest.mark.asyncio
async def test_analysis_control_text_without_mention_routes_to_at_message(monkeypatch) -> None:
    import src.infrastructure.channels.feishu_bot as module

    container = _ContainerStub()

    monkeypatch.setattr(module, "get_container", lambda: container)
    monkeypatch.setattr(module, "FeishuChannel", _FakeFeishuChannel)

    bot = _build_bot()

    await bot._dispatch(
        raw_event_id="evt-1",
        chat_id="oc_chat_1",
        user_id="u1",
        nickname="tester",
        text="分析最近聊天内容",
        is_mention=False,
        message_type="text",
    )

    assert container.at_calls == [
        {
            "raw_event_id": "evt-1",
            "group_id": "oc_chat_1",
            "user_id": "u1",
            "message_text": "分析最近聊天内容",
            "translation_enabled": True,
            "streaming": False,
        }
    ]
    assert container.channels["feishu"].sent_texts == [("oc_chat_1", "mock reply")]
    assert container.group_dialogue_appends == [
        {
            "group_id": "oc_chat_1",
            "user_id": "u1",
            "nickname": "tester",
            "text": "分析最近聊天内容",
        }
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
        message_type="text",
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
        message_type="text",
    )

    assert submitted["loop"] is bot._main_loop
    assert submitted["coro_name"] == "_dispatch"
    assert submitted["future"].callback == bot._log_dispatch_failure


@pytest.mark.asyncio
async def test_audio_message_routes_to_passive_observer(monkeypatch) -> None:
    import src.infrastructure.channels.feishu_bot as module

    container = _ContainerStub()

    monkeypatch.setattr(module, "get_container", lambda: container)
    monkeypatch.setattr(module, "FeishuChannel", _FakeFeishuChannel)

    bot = _build_bot()

    await bot._dispatch(
        raw_event_id="evt-audio",
        chat_id="oc_chat_1",
        user_id="u1",
        nickname="tester",
        text="",
        is_mention=False,
        message_type="audio",
    )

    assert container.passive_calls == [
        {
            "raw_event_id": "evt-audio",
            "group_id": "oc_chat_1",
            "user_id": "u1",
            "message_text": "",
            "message_type": "audio",
        }
    ]


@pytest.mark.asyncio
async def test_dispatch_passes_translation_toggle_to_at_message(monkeypatch) -> None:
    import src.infrastructure.channels.feishu_bot as module

    container = _ContainerStub(translation_enabled=False)

    monkeypatch.setattr(module, "get_container", lambda: container)
    monkeypatch.setattr(module, "FeishuChannel", _FakeFeishuChannel)

    bot = _build_bot()

    await bot._dispatch(
        raw_event_id="evt-translate-off",
        chat_id="oc_chat_1",
        user_id="u1",
        nickname="tester",
        text="你好",
        is_mention=True,
        message_type="text",
    )

    assert container.at_calls == [
        {
            "raw_event_id": "evt-translate-off",
            "group_id": "oc_chat_1",
            "user_id": "u1",
            "message_text": "你好",
            "translation_enabled": False,
            "streaming": False,
        }
    ]
    assert container.channels["feishu"].sent_texts == [("oc_chat_1", "mock reply")]
    assert container.group_dialogue_appends == [
        {
            "group_id": "oc_chat_1",
            "user_id": "u1",
            "nickname": "tester",
            "text": "你好",
        }
    ]


@pytest.mark.asyncio
async def test_dispatch_skips_send_when_at_message_returns_none(monkeypatch) -> None:
    import src.infrastructure.channels.feishu_bot as module

    container = _ContainerStub(translation_enabled=False, at_reply=None)

    monkeypatch.setattr(module, "get_container", lambda: container)
    monkeypatch.setattr(module, "FeishuChannel", _FakeFeishuChannel)

    bot = _build_bot()

    await bot._dispatch(
        raw_event_id="evt-silent",
        chat_id="oc_chat_1",
        user_id="u1",
        nickname="tester",
        text="你好",
        is_mention=True,
        message_type="text",
    )

    assert container.channels["feishu"].sent_texts == []
    assert container.group_dialogue_appends == []


@pytest.mark.asyncio
async def test_dispatch_card_action_routes_to_daily_session_usecase(monkeypatch) -> None:
    import src.infrastructure.channels.feishu_bot as module

    container = _ContainerStub()
    monkeypatch.setattr(module, "get_container", lambda: container)

    bot = _build_bot()
    result = await bot._dispatch_card_action(
        action="claim_baton",
        chat_id="oc_chat_1",
        actor_open_id="u1",
        biz_date=date(2026, 4, 13),
    )

    assert result.toast_type == "success"
    assert result.toast_content.startswith("claim:oc_chat_1:u1:2026-04-13")
    assert container.card_actions == [("claim_baton", "oc_chat_1", "u1", date(2026, 4, 13))]


def test_on_card_action_trigger_parses_payload_and_returns_toast(monkeypatch) -> None:
    import src.infrastructure.channels.feishu_bot as module

    captured: dict[str, object] = {}

    def _fake_dispatch_card_action_sync(
        *,
        action: str,
        chat_id: str,
        actor_open_id: str,
        biz_date,
        card_snapshot_id=None,
        target_open_id=None,
    ):
        captured.update(
            {
                "action": action,
                "chat_id": chat_id,
                "actor_open_id": actor_open_id,
                "biz_date": biz_date,
                "card_snapshot_id": card_snapshot_id,
                "target_open_id": target_open_id,
            }
        )
        return module.FeishuBot._build_card_action_response("success", "ok")

    bot = _build_bot()
    monkeypatch.setattr(bot, "_dispatch_card_action_sync", _fake_dispatch_card_action_sync)

    data = SimpleNamespace(
        event=SimpleNamespace(
            action=SimpleNamespace(
                value={
                    "action": "copy_goal_image_prompt",
                    "chat_id": "oc_chat_1",
                    "biz_date": "2026-04-13",
                    "card_snapshot_id": "18",
                    "target_open_id": "test_user",
                }
            ),
            operator=SimpleNamespace(open_id="u1"),
            context=SimpleNamespace(open_chat_id="oc_fallback"),
        )
    )
    response = bot._on_card_action_trigger(data)

    assert captured["action"] == "copy_goal_image_prompt"
    assert captured["chat_id"] == "oc_chat_1"
    assert captured["actor_open_id"] == "u1"
    assert str(captured["biz_date"]) == "2026-04-13"
    assert captured["card_snapshot_id"] == 18
    assert captured["target_open_id"] == "test_user"
    assert response.toast.type == "success"
    assert response.toast.content == "ok"
