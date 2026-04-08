from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, Event, GroupMessageEvent
from nonebot.params import EventPlainText
from nonebot.rule import Rule

from src.application.message_usecases import MessageCommandContext
from src.infrastructure.settings.container import get_or_init_container
from src.plugins.command_catalog import is_fixed_command_text, render_help_text


def _matches_at_message(bot: Bot, event: Event) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    if event.is_tome():
        return True

    bot_id = str(getattr(bot, "self_id", ""))
    for segment in event.message:
        if segment.type != "at":
            continue
        target = str(segment.data.get("qq", ""))
        if target and target == bot_id:
            return True
    return False


at_message = on_message(rule=Rule(_matches_at_message), priority=10, block=True)


@at_message.handle()
async def handle_at_message(bot: Bot, event: GroupMessageEvent, text: str = EventPlainText()) -> None:
    container = await get_or_init_container()
    enabled_group_ids = container.runtime_config.enabled_group_ids()
    if enabled_group_ids and str(event.group_id) not in enabled_group_ids:
        return

    cleaned = text.strip()
    if not cleaned:
        await at_message.finish(
            "发英文→纠错 | 发中文→翻译\n"
            "大模型润色：<对话> → 整体分析\n"
            "分析最近聊天内容 → 群聊分析\n\n"
            '输入"帮助"查看完整命令列表'
        )
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
