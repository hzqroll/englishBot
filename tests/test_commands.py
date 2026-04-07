from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.plugins.commands import handle_fixed_command_text


class _MessageUseCaseStub:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def handle_at_message(self, ctx):
        self.calls.append(
            {
                "raw_event_id": ctx.raw_event_id,
                "group_id": ctx.group_id,
                "user_id": ctx.user_id,
                "message_text": ctx.message_text,
            }
        )
        return "analysis result"


class _ConversationUseCaseStub:
    async def record_command_message(self, ctx):  # pragma: no cover - defensive
        raise AssertionError("analysis control text should bypass command recording")


class _RuntimeConfigStub:
    def is_enabled_chat(self, group_id: str) -> bool:
        return True


class _ContainerStub:
    def __init__(self) -> None:
        self.runtime_config = _RuntimeConfigStub()
        self.message_usecase = _MessageUseCaseStub()
        self.conversation_usecase = _ConversationUseCaseStub()


@pytest.mark.asyncio
async def test_analysis_control_text_can_be_sent_without_at() -> None:
    container = _ContainerStub()

    envelope = await handle_fixed_command_text(
        group_id="g1",
        group_name="demo",
        user_id="u1",
        nickname="tester",
        text="分析最近聊天内容",
        raw_event_id="evt-1",
        container=container,
    )

    assert envelope.plain_text == "analysis result"
    assert container.message_usecase.calls == [
        {
            "raw_event_id": "evt-1",
            "group_id": "g1",
            "user_id": "u1",
            "message_text": "分析最近聊天内容",
        }
    ]
