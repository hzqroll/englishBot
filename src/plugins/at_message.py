from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.params import EventPlainText
from nonebot.rule import to_me

from src.application.message_usecases import MessageCommandContext
from src.infrastructure.settings.container import get_or_init_container
from src.plugins.command_catalog import is_fixed_command_text, render_help_text


at_message = on_message(rule=to_me(), priority=10, block=True)


@at_message.handle()
async def handle_at_message(bot: Bot, event: GroupMessageEvent, text: str = EventPlainText()) -> None:
    container = await get_or_init_container()
    enabled_group_ids = container.runtime_config.enabled_group_ids()
    if enabled_group_ids and str(event.group_id) not in enabled_group_ids:
        return

    cleaned = text.strip()
    if not cleaned:
        await at_message.finish("可以直接发英文让我纠错，或者发中文让我帮你翻成更自然的英文。")
    if is_fixed_command_text(cleaned):
        await at_message.finish(
            "学习系统命令请直接发送，不需要 @机器人。\n\n"
            f"{render_help_text()}"
        )

    reply = await container.message_usecase.handle_at_message(
        MessageCommandContext(
            raw_event_id=str(event.message_id),
            group_id=str(event.group_id),
            group_name="",
            user_id=str(event.user_id),
            nickname=event.sender.card or event.sender.nickname or "",
            message_text=cleaned,
        )
    )
    await at_message.finish(reply)
