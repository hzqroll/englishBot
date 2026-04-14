from __future__ import annotations

import pytest

from src.plugins.command_handlers import handle_fixed_command_text


class _ConversationUseCaseStub:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def record_command_message(self, ctx):
        self.calls.append(
            {
                "raw_event_id": ctx.raw_event_id,
                "group_id": ctx.group_id,
                "user_id": ctx.user_id,
                "message_text": ctx.message_text,
            }
        )


class _RuntimeConfigStub:
    def is_enabled_chat(self, group_id: str) -> bool:
        return True


class _ContainerStub:
    def __init__(self) -> None:
        self.runtime_config = _RuntimeConfigStub()
        self.conversation_usecase = _ConversationUseCaseStub()


@pytest.mark.asyncio
async def test_help_command_uses_fixed_command_handler() -> None:
    container = _ContainerStub()

    envelope = await handle_fixed_command_text(
        group_id="g1",
        group_name="demo",
        user_id="u1",
        nickname="tester",
        text="帮助",
        raw_event_id="evt-1",
        container=container,
    )

    assert "今日任务" in envelope.plain_text
    assert "报名学习" not in envelope.plain_text
    assert container.conversation_usecase.calls == [
        {
            "raw_event_id": "evt-1",
            "group_id": "g1",
            "user_id": "u1",
            "message_text": "帮助",
        }
    ]
