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
        self.learning_usecase = None


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


@pytest.mark.asyncio
async def test_add_new_words_command_routes_to_learning_usecase() -> None:
    container = _ContainerStub()

    class _LearningUseCaseStub:
        async def add_new_words(self, *, chat_id: str, open_id: str, nickname: str, words: list[str], biz_date):
            assert chat_id == "g1"
            assert open_id == "u1"
            assert nickname == "tester"
            assert words == ["resilient", "backlog", "align"]
            assert biz_date is not None
            return "ok"

    container.learning_usecase = _LearningUseCaseStub()

    envelope = await handle_fixed_command_text(
        group_id="g1",
        group_name="demo",
        user_id="u1",
        nickname="tester",
        text="添加新词 resilient, backlog; align",
        raw_event_id="evt-2",
        container=container,
    )

    assert envelope.plain_text == "ok"
