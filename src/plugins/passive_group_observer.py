from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, Event, GroupMessageEvent
from nonebot.params import EventPlainText
from nonebot.rule import Rule

from src.application.conversation_usecases import ConversationContext
from src.infrastructure.settings.container import get_or_init_container
from src.plugins.command_catalog import is_fixed_command_text


def _matches_passive_observer(event: Event) -> bool:
    return isinstance(event, GroupMessageEvent)


passive_group_observer = on_message(rule=Rule(_matches_passive_observer), priority=30, block=False)


@passive_group_observer.handle()
async def handle_passive_group_observer(bot: Bot, event: GroupMessageEvent, text: str = EventPlainText()) -> None:
    if str(event.user_id) == str(bot.self_id):
        return

    cleaned = text.strip()
    if not cleaned:
        return
    if is_fixed_command_text(cleaned):
        return

    container = await get_or_init_container()
    enabled_group_ids = container.runtime_config.enabled_group_ids()
    if enabled_group_ids and str(event.group_id) not in enabled_group_ids:
        return

    await container.conversation_usecase.observe_passive_group_message(
        ConversationContext(
            raw_event_id=str(event.message_id),
            group_id=str(event.group_id),
            group_name="",
            user_id=str(event.user_id),
            nickname=event.sender.card or event.sender.nickname or "",
            message_text=cleaned,
        )
    )
