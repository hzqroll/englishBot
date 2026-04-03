from __future__ import annotations

from pathlib import Path
import shutil
from datetime import UTC, datetime

from nonebot import get_bots
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler
from sqlalchemy.engine import make_url

from src.infrastructure.settings.container import get_container


def register_jobs() -> None:
    container = get_container()
    runtime_config = container.runtime_config

    scheduler.add_job(
        daily_push_job,
        "cron",
        id="daily_push",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.daily_push_cron")),
    )
    scheduler.add_job(
        daily_reminder_job,
        "cron",
        id="daily_reminder",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.daily_reminder_cron")),
    )
    scheduler.add_job(
        weekly_report_job,
        "cron",
        id="weekly_report",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.weekly_report_cron")),
    )
    scheduler.add_job(
        weekly_quiz_job,
        "cron",
        id="weekly_quiz",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.weekly_quiz_cron")),
    )
    scheduler.add_job(
        nightly_backup_job,
        "cron",
        id="nightly_backup",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.nightly_backup_cron")),
    )


async def daily_push_job() -> None:
    container = get_container()
    await container.runtime_config.refresh()
    biz_key = datetime.now(UTC).strftime("%Y-%m-%d")
    if not await container.learning_repo.acquire_job_lock(job_name="daily_push", biz_key=biz_key):
        return
    try:
        bots = list(get_bots().values())
        for group_id in container.runtime_config.enabled_group_ids():
            await container.learning_usecase.build_today_lesson(qq_group_id=group_id)
            message = await container.learning_usecase.get_today_task_message(qq_group_id=group_id)
            await _send_group_message(bots=bots, group_id=group_id, message=message)
        await container.learning_repo.finish_job_lock(job_name="daily_push", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("daily push job failed")
        await container.learning_repo.finish_job_lock(job_name="daily_push", biz_key=biz_key, status="failed")


async def daily_reminder_job() -> None:
    container = get_container()
    await container.runtime_config.refresh()
    biz_key = datetime.now(UTC).strftime("%Y-%m-%d")
    if not await container.learning_repo.acquire_job_lock(job_name="daily_reminder", biz_key=biz_key):
        return
    try:
        bots = list(get_bots().values())
        if container.runtime_config.daily_reminder_enabled():
            for group_id in container.runtime_config.enabled_group_ids():
                reminder = "今晚记得完成今日任务。如果已经完成，可以发送“复习一下”巩固旧错误点。"
                await _send_group_message(bots=bots, group_id=group_id, message=reminder)
        await container.learning_repo.finish_job_lock(job_name="daily_reminder", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("daily reminder job failed")
        await container.learning_repo.finish_job_lock(job_name="daily_reminder", biz_key=biz_key, status="failed")


async def weekly_report_job() -> None:
    container = get_container()
    await container.runtime_config.refresh()
    biz_key = datetime.now(UTC).strftime("%G-W%V")
    if not await container.learning_repo.acquire_job_lock(job_name="weekly_report", biz_key=biz_key):
        return
    try:
        bots = list(get_bots().values())
        for group_id in container.runtime_config.enabled_group_ids():
            group = await container.identity_repo.ensure_group(group_id)
            users = await container.identity_repo.list_enrolled_users(group.id)
            for user in users:
                report = await container.report_usecase.build_weekly_report(
                    qq_group_id=group_id,
                    qq_user_id=user.qq_user_id,
                    nickname=user.nickname,
                )
                message = f"[CQ:at,qq={user.qq_user_id}] \n{report}"
                await _send_group_message(bots=bots, group_id=group_id, message=message)
        await container.learning_repo.finish_job_lock(job_name="weekly_report", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("weekly report job failed")
        await container.learning_repo.finish_job_lock(job_name="weekly_report", biz_key=biz_key, status="failed")


async def weekly_quiz_job() -> None:
    container = get_container()
    await container.runtime_config.refresh()
    biz_key = datetime.now(UTC).strftime("%G-W%V")
    if not await container.learning_repo.acquire_job_lock(job_name="weekly_quiz", biz_key=biz_key):
        return
    try:
        bots = list(get_bots().values())
        for group_id in container.runtime_config.enabled_group_ids():
            group = await container.identity_repo.ensure_group(group_id)
            users = await container.identity_repo.list_enrolled_users(group.id)
            for user in users:
                quiz = await container.quiz_usecase.start_weekly_quiz(
                    qq_group_id=group_id,
                    qq_user_id=user.qq_user_id,
                    nickname=user.nickname,
                )
                message = f"[CQ:at,qq={user.qq_user_id}] \n{quiz}"
                await _send_group_message(bots=bots, group_id=group_id, message=message)
        await container.learning_repo.finish_job_lock(job_name="weekly_quiz", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("weekly quiz job failed")
        await container.learning_repo.finish_job_lock(job_name="weekly_quiz", biz_key=biz_key, status="failed")


async def nightly_backup_job() -> None:
    container = get_container()
    await container.runtime_config.refresh()
    biz_key = datetime.now(UTC).strftime("%Y-%m-%d")
    if not await container.learning_repo.acquire_job_lock(job_name="nightly_backup", biz_key=biz_key):
        return
    try:
        url = make_url(container.settings.runtime.database_url)
        if url.drivername.startswith("sqlite"):
            db_path = Path(url.database or "")
            if not db_path.is_absolute():
                db_path = container.settings.project_root / db_path
            backup_dir = container.settings.data_dir / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            if db_path.exists():
                shutil.copy2(db_path, backup_dir / f"{db_path.stem}-{biz_key}{db_path.suffix}")
        await container.learning_repo.finish_job_lock(job_name="nightly_backup", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("nightly backup job failed")
        await container.learning_repo.finish_job_lock(job_name="nightly_backup", biz_key=biz_key, status="failed")


def _cron_kwargs(expression: str) -> dict[str, str]:
    minute, hour, day, month, day_of_week = expression.split()
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": day_of_week,
    }


async def _send_group_message(*, bots: list, group_id: str, message: str) -> None:
    for bot in bots:
        try:
            await bot.send_group_msg(group_id=int(group_id), message=message)
            return
        except Exception:
            logger.exception("failed to send message to group %s", group_id)
