from __future__ import annotations

from nonebot import on_command
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.params import CommandArg

from src.application.learning_usecases import EnrollmentContext
from src.infrastructure.settings.container import get_container


def _get_identity(event: GroupMessageEvent) -> tuple[str, str]:
    return str(event.user_id), event.sender.card or event.sender.nickname or ""


enroll = on_command("报名学习", priority=10, block=True)
today_task = on_command("今日任务", priority=10, block=True)
submit_task = on_command("提交任务", priority=10, block=True)
review_now = on_command("复习一下", priority=10, block=True)
user_level = on_command("我的等级", priority=10, block=True)
weekly_quiz = on_command("开始周测", priority=10, block=True)
submit_quiz = on_command("答题", priority=10, block=True)
weekly_report = on_command("本周总结", priority=10, block=True)


@enroll.handle()
async def handle_enroll(event: GroupMessageEvent) -> None:
    container = get_container()
    qq_user_id, nickname = _get_identity(event)
    message = await container.learning_usecase.enroll(
        EnrollmentContext(
            qq_group_id=str(event.group_id),
            group_name="",
            qq_user_id=qq_user_id,
            nickname=nickname,
        )
    )
    await enroll.finish(message)


@today_task.handle()
async def handle_today_task(event: GroupMessageEvent) -> None:
    container = get_container()
    message = await container.learning_usecase.get_today_task_message(
        qq_group_id=str(event.group_id),
    )
    await today_task.finish(message)


@submit_task.handle()
async def handle_submit_task(event: GroupMessageEvent, args=CommandArg()) -> None:
    container = get_container()
    qq_user_id, nickname = _get_identity(event)
    text = args.extract_plain_text().strip()
    if " " not in text:
        await submit_task.finish("格式示例：提交任务 123 这里写你的回答")
    task_id_text, content = text.split(" ", 1)
    if not task_id_text.isdigit():
        await submit_task.finish("任务 ID 必须是数字。")
    message = await container.learning_usecase.submit_task(
        qq_group_id=str(event.group_id),
        qq_user_id=qq_user_id,
        nickname=nickname,
        task_id=int(task_id_text),
        content=content,
    )
    await submit_task.finish(message)


@review_now.handle()
async def handle_review_now(event: GroupMessageEvent) -> None:
    container = get_container()
    qq_user_id, nickname = _get_identity(event)
    message = await container.learning_usecase.review_now(
        qq_group_id=str(event.group_id),
        qq_user_id=qq_user_id,
        nickname=nickname,
        limit=container.runtime_config.daily_review_insert_count(),
    )
    await review_now.finish(message)


@user_level.handle()
async def handle_user_level(event: GroupMessageEvent) -> None:
    container = get_container()
    qq_user_id, nickname = _get_identity(event)
    message = await container.learning_usecase.refresh_user_level(
        qq_group_id=str(event.group_id),
        qq_user_id=qq_user_id,
        nickname=nickname,
    )
    await user_level.finish(message)


@weekly_quiz.handle()
async def handle_weekly_quiz(event: GroupMessageEvent) -> None:
    container = get_container()
    qq_user_id, nickname = _get_identity(event)
    message = await container.quiz_usecase.start_weekly_quiz(
        qq_group_id=str(event.group_id),
        qq_user_id=qq_user_id,
        nickname=nickname,
    )
    await weekly_quiz.finish(message)


@submit_quiz.handle()
async def handle_submit_quiz(event: GroupMessageEvent, args=CommandArg()) -> None:
    container = get_container()
    qq_user_id, nickname = _get_identity(event)
    text = args.extract_plain_text().strip()
    parts = text.split()
    if len(parts) < 2 or not parts[0].isdigit():
        await submit_quiz.finish("格式示例：答题 10 1:A 2:B 3:C")
    session_id = int(parts[0])
    answers: dict[int, str] = {}
    for chunk in parts[1:]:
        if ":" not in chunk:
            continue
        index_text, answer = chunk.split(":", 1)
        if index_text.isdigit():
            answers[int(index_text)] = answer.strip().upper()
    message = await container.quiz_usecase.submit_weekly_quiz(
        qq_group_id=str(event.group_id),
        qq_user_id=qq_user_id,
        nickname=nickname,
        session_id=session_id,
        answers=answers,
    )
    await submit_quiz.finish(message)


@weekly_report.handle()
async def handle_weekly_report(event: GroupMessageEvent) -> None:
    container = get_container()
    qq_user_id, nickname = _get_identity(event)
    message = await container.report_usecase.build_weekly_report(
        qq_group_id=str(event.group_id),
        qq_user_id=qq_user_id,
        nickname=nickname,
    )
    await weekly_report.finish(message)
