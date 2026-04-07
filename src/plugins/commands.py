from __future__ import annotations

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Bot, Event, GroupMessageEvent
from nonebot.rule import Rule

from src.application.conversation_usecases import ConversationContext
from src.application.learning_usecases import EnrollmentContext
from src.domain.value_objects.messaging import MessageEnvelope
from src.infrastructure.settings.container import ServiceContainer, get_or_init_container
from src.plugins.command_catalog import is_fixed_command_text, match_fixed_command, render_help_text


def _get_identity(event: GroupMessageEvent) -> tuple[str, str]:
    return str(event.user_id), event.sender.card or event.sender.nickname or ""


def _command_text(event: GroupMessageEvent) -> str:
    return event.get_plaintext().strip()


def _matches_learning_command(event: Event) -> bool:
    if not isinstance(event, GroupMessageEvent):
        return False
    return is_fixed_command_text(_command_text(event))


group_command = on_message(rule=Rule(_matches_learning_command), priority=5, block=True)


def _to_envelope(message: str | MessageEnvelope) -> MessageEnvelope:
    if isinstance(message, MessageEnvelope):
        return message
    return MessageEnvelope(plain_text=message)


async def _handle_enroll(
    *,
    container: ServiceContainer,
    group_id: str,
    group_name: str,
    user_id: str,
    nickname: str,
) -> str:
    if not container.runtime_config.is_enabled_chat(group_id):
        return "当前群未启用学习功能。"
    return await container.learning_usecase.enroll(
        EnrollmentContext(
            qq_group_id=group_id,
            group_name=group_name,
            qq_user_id=user_id,
            nickname=nickname,
        )
    )


async def _handle_today_task(
    *,
    container: ServiceContainer,
    group_id: str,
    user_id: str,
    nickname: str,
) -> MessageEnvelope:
    return await container.learning_usecase.get_today_task_envelope(
        qq_group_id=group_id,
        qq_user_id=user_id,
        nickname=nickname,
    )


async def _handle_submit_task(
    *,
    container: ServiceContainer,
    group_id: str,
    user_id: str,
    nickname: str,
    text: str,
) -> str:
    args = text.removeprefix("提交任务").strip()
    if " " not in args:
        return "格式示例：提交任务 123 这里写你的回答"
    task_id_text, content = args.split(" ", 1)
    if not task_id_text.isdigit():
        return "任务 ID 必须是数字。"
    return await container.learning_usecase.submit_task(
        qq_group_id=group_id,
        qq_user_id=user_id,
        nickname=nickname,
        task_id=int(task_id_text),
        content=content,
    )


async def _handle_review_now(
    *,
    container: ServiceContainer,
    group_id: str,
    user_id: str,
    nickname: str,
) -> str:
    return await container.learning_usecase.review_now(
        qq_group_id=group_id,
        qq_user_id=user_id,
        nickname=nickname,
        limit=container.runtime_config.daily_review_insert_count(),
    )


async def _handle_user_level(
    *,
    container: ServiceContainer,
    group_id: str,
    user_id: str,
    nickname: str,
) -> str:
    return await container.learning_usecase.refresh_user_level(
        qq_group_id=group_id,
        qq_user_id=user_id,
        nickname=nickname,
    )


async def _handle_weekly_quiz(
    *,
    container: ServiceContainer,
    group_id: str,
    user_id: str,
    nickname: str,
) -> MessageEnvelope:
    return await container.quiz_usecase.start_weekly_quiz_envelope(
        qq_group_id=group_id,
        qq_user_id=user_id,
        nickname=nickname,
    )


async def _handle_submit_quiz(
    *,
    container: ServiceContainer,
    group_id: str,
    user_id: str,
    nickname: str,
    text: str,
) -> str:
    args = text.removeprefix("答题").strip()
    parts = args.split()
    if len(parts) < 2 or not parts[0].isdigit():
        return "格式示例：答题 10 1:A 2:B 3:C"
    session_id = int(parts[0])
    answers: dict[int, str] = {}
    for chunk in parts[1:]:
        if ":" not in chunk:
            continue
        index_text, answer = chunk.split(":", 1)
        if index_text.isdigit():
            answers[int(index_text)] = answer.strip().upper()
    return await container.quiz_usecase.submit_weekly_quiz(
        qq_group_id=group_id,
        qq_user_id=user_id,
        nickname=nickname,
        session_id=session_id,
        answers=answers,
    )


async def _handle_weekly_report(
    *,
    container: ServiceContainer,
    group_id: str,
    user_id: str,
    nickname: str,
) -> MessageEnvelope:
    return await container.report_usecase.build_weekly_report_envelope(
        qq_group_id=group_id,
        qq_user_id=user_id,
        nickname=nickname,
    )


async def handle_fixed_command_text(
    *,
    group_id: str,
    group_name: str,
    user_id: str,
    nickname: str,
    text: str,
    raw_event_id: str = "",
    container: ServiceContainer | None = None,
) -> MessageEnvelope:
    container = container or await get_or_init_container()
    if not container.runtime_config.is_enabled_chat(group_id):
        return MessageEnvelope(plain_text="当前群未启用学习功能。")

    await container.conversation_usecase.record_command_message(
        ConversationContext(
            raw_event_id=raw_event_id,
            group_id=group_id,
            group_name=group_name,
            user_id=user_id,
            nickname=nickname,
            message_text=text,
        )
    )
    command_name = match_fixed_command(text)
    if command_name == "报名学习":
        message = await _handle_enroll(
            container=container,
            group_id=group_id,
            group_name=group_name,
            user_id=user_id,
            nickname=nickname,
        )
    elif command_name == "今日任务":
        message = await _handle_today_task(
            container=container,
            group_id=group_id,
            user_id=user_id,
            nickname=nickname,
        )
    elif command_name == "提交任务":
        message = await _handle_submit_task(
            container=container,
            group_id=group_id,
            user_id=user_id,
            nickname=nickname,
            text=text,
        )
    elif command_name == "复习一下":
        message = await _handle_review_now(
            container=container,
            group_id=group_id,
            user_id=user_id,
            nickname=nickname,
        )
    elif command_name == "我的等级":
        message = await _handle_user_level(
            container=container,
            group_id=group_id,
            user_id=user_id,
            nickname=nickname,
        )
    elif command_name == "开始周测":
        message = await _handle_weekly_quiz(
            container=container,
            group_id=group_id,
            user_id=user_id,
            nickname=nickname,
        )
    elif command_name == "答题":
        message = await _handle_submit_quiz(
            container=container,
            group_id=group_id,
            user_id=user_id,
            nickname=nickname,
            text=text,
        )
    elif command_name == "本周总结":
        message = await _handle_weekly_report(
            container=container,
            group_id=group_id,
            user_id=user_id,
            nickname=nickname,
        )
    elif command_name == "帮助":
        message = render_help_text()
    else:
        message = "暂不支持这个命令。"
    return _to_envelope(message)


@group_command.handle()
async def handle_group_command(bot: Bot, event: GroupMessageEvent) -> None:
    container = await get_or_init_container()
    text = _command_text(event)
    qq_user_id, nickname = _get_identity(event)
    envelope = await handle_fixed_command_text(
        group_id=str(event.group_id),
        group_name="",
        user_id=qq_user_id,
        nickname=nickname,
        text=text,
        raw_event_id=str(event.message_id),
        container=container,
    )
    await container.message_delivery_service.reply_group_envelope(
        bot=bot,
        group_id=str(event.group_id),
        envelope=envelope,
    )
    await group_command.finish()
