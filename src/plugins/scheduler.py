from __future__ import annotations

from pathlib import Path
import shutil
from datetime import UTC, date, datetime, time

from nonebot import get_bots
from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler
from sqlalchemy.engine import make_url

from src.domain.value_objects.messaging import MessageEnvelope
from src.application.conversation_usecases import ConversationContext
from src.infrastructure.settings.container import get_container, get_or_init_container


def register_jobs() -> None:
    container = get_container()
    runtime_config = container.runtime_config

    logger.info("register_jobs: registering scheduled jobs...")

    scheduler.add_job(
        daily_push_job,
        "cron",
        id="daily_push",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.daily_push_cron")),
    )
    scheduler.add_job(
        midday_baton_job,
        "cron",
        id="midday_baton",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.midday_baton_cron")),
    )
    scheduler.add_job(
        evening_baton_job,
        "cron",
        id="evening_baton",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.evening_baton_cron")),
    )
    scheduler.add_job(
        daily_error_digest_job,
        "cron",
        id="daily_error_digest",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.daily_error_digest_cron")),
    )
    scheduler.add_job(
        daily_progress_job,
        "cron",
        id="daily_progress",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.daily_progress_cron")),
    )
    # Weekly report is kept as a manual action ("本周总结"/admin trigger) to avoid
    # interrupting daily execution with scheduled weekly cards.
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
    scheduler.add_job(
        daily_friends_job,
        "cron",
        id="daily_friends",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("friends.daily_push_cron")),
    )
    scheduler.add_job(
        sync_feishu_messages_job,
        "cron",
        id="sync_feishu_messages",
        replace_existing=True,
        **_cron_kwargs(runtime_config.cron("scheduler.sync_feishu_messages_cron")),
    )

    jobs = scheduler.get_jobs()
    logger.info("register_jobs: {} jobs registered", len(jobs))
    for j in jobs:
        logger.info("  job: {}", j.id)


async def daily_push_job(force_run: bool = False) -> None:
    container = await get_or_init_container()
    await container.runtime_config.refresh()
    biz_key = datetime.now(UTC).strftime("%Y-%m-%d")
    if not await container.learning_repo.acquire_job_lock(job_name="daily_push", biz_key=biz_key, force=force_run):
        return
    try:
        if container.runtime_config.is_feishu_enabled():
            for chat_id in container.runtime_config.feishu_enabled_group_ids():
                await container.learning_usecase.build_today_lesson(chat_id=chat_id)
                envelope = await container.daily_session_usecase.build_execution_envelope(chat_id=chat_id)
                sent = await _send_group_envelope(
                    container=container,
                    group_id=chat_id,
                    envelope=envelope,
                    job_name="daily_push",
                )
                group = await container.identity_repo.ensure_group(chat_id)
                await container.learning_repo.update_lesson_push_status(
                    group_id=group.id,
                    biz_date=date.today(),
                    channel="feishu",
                    push_status="sent" if sent else "failed",
                )
        await container.learning_repo.finish_job_lock(job_name="daily_push", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("daily push job failed")
        await container.learning_repo.finish_job_lock(job_name="daily_push", biz_key=biz_key, status="failed")


async def midday_baton_job(target_date: date | None = None, force_run: bool = False) -> None:
    await _run_baton_job(job_name="midday_baton", phase="midday", target_date=target_date, force_run=force_run)


async def evening_baton_job(target_date: date | None = None, force_run: bool = False) -> None:
    await _run_baton_job(job_name="evening_baton", phase="evening", target_date=target_date, force_run=force_run)


async def daily_error_digest_job(target_date: date | None = None, force_run: bool = False) -> None:
    container = await get_or_init_container()
    await container.runtime_config.refresh()
    target_date = target_date or datetime.now().astimezone().date()
    biz_key = target_date.isoformat()
    if not await container.learning_repo.acquire_job_lock(
        job_name="daily_error_digest",
        biz_key=biz_key,
        force=force_run,
    ):
        return
    try:
        if container.runtime_config.is_feishu_enabled():
            for chat_id in container.runtime_config.feishu_enabled_group_ids():
                group = await container.identity_repo.ensure_group(chat_id)
                users = await container.identity_repo.list_group_active_users(group.id)
                for user in users:
                    digest = await container.report_usecase.build_daily_error_digest_envelope(
                        chat_id=chat_id,
                        open_id=user.open_id,
                        nickname=user.nickname,
                        target_date=target_date,
                    )
                    if digest is None:
                        continue
                    await _send_group_envelope(
                        container=container,
                        group_id=chat_id,
                        envelope=digest,
                        mention_user_id=user.open_id,
                        job_name="daily_error_digest",
                        user_id=user.id,
                    )
        await container.learning_repo.finish_job_lock(job_name="daily_error_digest", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("daily error digest job failed")
        await container.learning_repo.finish_job_lock(job_name="daily_error_digest", biz_key=biz_key, status="failed")


async def daily_progress_job(target_date: date | None = None, force_run: bool = False) -> None:
    container = await get_or_init_container()
    await container.runtime_config.refresh()
    target_date = target_date or datetime.now().astimezone().date()
    biz_key = target_date.isoformat()
    if not await container.learning_repo.acquire_job_lock(
        job_name="daily_progress",
        biz_key=biz_key,
        force=force_run,
    ):
        return
    try:
        if container.runtime_config.is_feishu_enabled():
            for chat_id in container.runtime_config.feishu_enabled_group_ids():
                group = await container.identity_repo.ensure_group(chat_id)
                users = await container.identity_repo.list_group_active_users(group.id)
                for user in users:
                    progress = await container.report_usecase.build_daily_progress_envelope(
                        chat_id=chat_id,
                        open_id=user.open_id,
                        nickname=user.nickname,
                        target_date=target_date,
                    )
                    if progress is None:
                        continue
                    await _send_group_envelope(
                        container=container,
                        group_id=chat_id,
                        envelope=progress,
                        mention_user_id=user.open_id,
                        job_name="daily_progress",
                        user_id=user.id,
                    )
        await container.learning_repo.finish_job_lock(job_name="daily_progress", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("daily progress job failed")
        await container.learning_repo.finish_job_lock(job_name="daily_progress", biz_key=biz_key, status="failed")


async def weekly_report_job(target_date: date | None = None, force_run: bool = False) -> None:
    container = await get_or_init_container()
    await container.runtime_config.refresh()
    target_date = target_date or datetime.now().astimezone().date()
    biz_key = target_date.strftime("%G-W%V")
    if not await container.learning_repo.acquire_job_lock(
        job_name="weekly_report",
        biz_key=biz_key,
        force=force_run,
    ):
        return
    try:
        if container.runtime_config.is_feishu_enabled():
            for chat_id in container.runtime_config.feishu_enabled_group_ids():
                group = await container.identity_repo.ensure_group(chat_id)
                users = await container.identity_repo.list_group_active_users(group.id)
                for user in users:
                    report = await container.report_usecase.build_weekly_report_envelope(
                        chat_id=chat_id,
                        open_id=user.open_id,
                        nickname=user.nickname,
                        target_date=target_date,
                    )
                    await _send_group_envelope(
                        container=container,
                        group_id=chat_id,
                        envelope=report,
                        mention_user_id=user.open_id,
                        job_name="weekly_report",
                        user_id=user.id,
                    )
        await container.learning_repo.finish_job_lock(job_name="weekly_report", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("weekly report job failed")
        await container.learning_repo.finish_job_lock(job_name="weekly_report", biz_key=biz_key, status="failed")


async def weekly_quiz_job(target_date: date | None = None, force_run: bool = False) -> None:
    container = await get_or_init_container()
    await container.runtime_config.refresh()
    target_date = target_date or datetime.now().astimezone().date()
    biz_key = target_date.strftime("%G-W%V")
    if not await container.learning_repo.acquire_job_lock(
        job_name="weekly_quiz",
        biz_key=biz_key,
        force=force_run,
    ):
        return
    try:
        if container.runtime_config.is_feishu_enabled():
            for chat_id in container.runtime_config.feishu_enabled_group_ids():
                group = await container.identity_repo.ensure_group(chat_id)
                users = await container.identity_repo.list_group_active_users(group.id)
                for user in users:
                    quiz = await container.quiz_usecase.start_weekly_quiz_envelope(
                        chat_id=chat_id,
                        open_id=user.open_id,
                        nickname=user.nickname,
                        target_date=target_date,
                    )
                    await _send_group_envelope(
                        container=container,
                        group_id=chat_id,
                        envelope=quiz,
                        mention_user_id=user.open_id,
                        job_name="weekly_quiz",
                        user_id=user.id,
                    )
        await container.learning_repo.finish_job_lock(job_name="weekly_quiz", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("weekly quiz job failed")
        await container.learning_repo.finish_job_lock(job_name="weekly_quiz", biz_key=biz_key, status="failed")


async def nightly_backup_job() -> None:
    container = await get_or_init_container()
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


async def _send_group_envelope(
    *,
    container,
    group_id: str,
    envelope: MessageEnvelope,
    mention_user_id: str | None = None,
    job_name: str,
    user_id: int | None = None,
) -> bool:
    group = await container.identity_repo.ensure_group(group_id)
    try:
        channel = container.channels.get("feishu")
        if channel is None:
            logger.warning("feishu channel not registered, skip group %s", group_id)
            return False
        result = await channel.send_envelope(chat_id=group_id, envelope=envelope, mention_user=mention_user_id)
        if envelope.card_snapshot_id is not None and result.image_paths:
            await container.learning_repo.update_daily_card_snapshot_images(
                snapshot_id=envelope.card_snapshot_id,
                image_paths_json=result.image_paths,
            )
        await container.learning_repo.create_message_delivery_log(
            group_id=group.id,
            user_id=user_id,
            job_name=job_name,
            card_snapshot_id=envelope.card_snapshot_id,
            delivery_mode=result.delivery_mode,
            success=True,
            provider_response="sent",
        )
        # 发送后归档到飞书文档（非阻塞）— 跳过 Friends 内容（使用独立文档）
        if container.feishu_docs_service is not None and job_name != "friends_dialogue":
            await _save_to_feishu_docs(
                container=container,
                envelope=envelope,
                card_type=job_name,
                target_date=date.today(),
            )
        return True
    except Exception:
        logger.exception("failed to send message to group %s", group_id)
        await container.learning_repo.create_message_delivery_log(
            group_id=group.id,
            user_id=user_id,
            job_name=job_name,
            card_snapshot_id=envelope.card_snapshot_id,
            delivery_mode="failed",
            success=False,
            provider_response="send_failed",
        )
        return False


async def _run_baton_job(
    *,
    job_name: str,
    phase: str,
    target_date: date | None = None,
    force_run: bool = False,
) -> None:
    container = await get_or_init_container()
    await container.runtime_config.refresh()
    target_date = target_date or datetime.now().astimezone().date()
    biz_key = target_date.isoformat()
    if not await container.learning_repo.acquire_job_lock(job_name=job_name, biz_key=biz_key, force=force_run):
        return
    try:
        if container.runtime_config.is_feishu_enabled():
            for chat_id in container.runtime_config.feishu_enabled_group_ids():
                reminder = await container.daily_session_usecase.build_baton_reminder(
                    chat_id=chat_id,
                    biz_date=target_date,
                    phase=phase,
                )
                if reminder is None:
                    continue
                await _send_group_envelope(
                    container=container,
                    group_id=chat_id,
                    envelope=reminder.envelope,
                    mention_user_id=reminder.mention_open_id,
                    user_id=reminder.mention_user_id,
                    job_name=job_name,
                )
        await container.learning_repo.finish_job_lock(job_name=job_name, biz_key=biz_key, status="success")
    except Exception:
        logger.exception("%s job failed", job_name)
        await container.learning_repo.finish_job_lock(job_name=job_name, biz_key=biz_key, status="failed")


async def _save_to_feishu_docs(
    *,
    container,
    envelope: MessageEnvelope,
    card_type: str,
    target_date: date,
) -> None:
    """非阻塞：将内容写入飞书文档，失败只记日志。"""
    if envelope.card_document is None:
        return
    try:
        await container.feishu_docs_service.append_content(
            envelope=envelope,
            card_type=card_type,
            target_date=target_date,
        )
    except Exception:
        logger.exception("feishu docs save failed for card_type=%s", card_type)


async def daily_friends_job(force_run: bool = False) -> None:
    container = await get_or_init_container()
    if container.friends_usecase is None:
        return
    await container.runtime_config.refresh()
    biz_date = datetime.now(UTC).strftime("%Y-%m-%d")
    if not await container.learning_repo.acquire_job_lock(job_name="daily_friends", biz_key=biz_date, force=force_run):
        return
    try:
        friends_cfg = container.settings.static.friends
        start_date = date.fromisoformat(friends_cfg.start_date) if friends_cfg.start_date else date.today()
        target_date = datetime.now().astimezone().date()
        if target_date < start_date:
            logger.info(
                "daily friends job skipped before start_date: target_date=%s start_date=%s",
                target_date,
                start_date,
            )
            await container.learning_repo.finish_job_lock(job_name="daily_friends", biz_key=biz_date, status="success")
            return

        envelope = await container.friends_usecase.build_daily_friends_envelope(
            biz_date=target_date,
            start_date=start_date,
        )
        segment = container.friends_usecase.provider.get_segment(target_date, start_date)

        if container.channels.get("feishu") is not None:
            doc_url: str | None = None
            if container.feishu_docs_service is not None:
                doc_url = await _save_friends_to_docs(
                    container=container,
                    envelope=envelope,
                    season=segment.season,
                    episode=segment.episode,
                    episode_title=segment.title,
                    target_date=target_date,
                )

            if doc_url:
                doc_title = f"S{segment.season:02d}E{segment.episode:02d} - {segment.title}"
                delivery_envelope = MessageEnvelope(
                    plain_text=f"Friends {doc_title} 今日学习内容已更新：{doc_url}",
                )
            else:
                delivery_envelope = envelope

            for chat_id in container.runtime_config.feishu_enabled_group_ids():
                await _send_group_envelope(
                    container=container,
                    group_id=chat_id,
                    envelope=delivery_envelope,
                    job_name="friends_dialogue",
                )
        await container.learning_repo.finish_job_lock(job_name="daily_friends", biz_key=biz_date, status="success")
    except Exception:
        logger.exception("daily friends job failed")
        await container.learning_repo.finish_job_lock(job_name="daily_friends", biz_key=biz_date, status="failed")


async def _save_friends_to_docs(
    *,
    container,
    envelope: MessageEnvelope,
    season: int,
    episode: int,
    episode_title: str,
    target_date: date,
) -> str | None:
    """将 Friends 内容写入按集飞书文档，返回文档 URL。"""
    try:
        return await container.feishu_docs_service.append_friends_content(
            envelope=envelope,
            season=season,
            episode=episode,
            episode_title=episode_title,
            target_date=target_date,
        )
    except Exception:
        logger.exception("feishu docs save failed for friends S%02dE%02d", season, episode)
        return None


async def sync_feishu_messages_job(target_date: date | None = None, force_run: bool = False) -> None:
    container = await get_or_init_container()
    if not container.runtime_config.is_feishu_enabled():
        return

    target_date = target_date or datetime.now().astimezone().date()
    biz_key = target_date.isoformat()
    if not await container.learning_repo.acquire_job_lock(job_name="sync_feishu_messages", biz_key=biz_key, force=force_run):
        return
    try:
        feishu_channel = container.channels.get("feishu")
        if feishu_channel is None:
            logger.warning("feishu channel not registered, skip sync")
            await container.learning_repo.finish_job_lock(job_name="sync_feishu_messages", biz_key=biz_key, status="failed")
            return

        for chat_id in container.runtime_config.feishu_enabled_group_ids():
            since = datetime.combine(target_date, time.min)
            messages = await feishu_channel.get_chat_messages(chat_id, since=since)
            synced = 0
            for msg in messages:
                if msg.user_id.startswith("cli_") or not msg.message_text.strip():
                    continue
                await container.conversation_usecase.observe_passive_group_message(
                    ConversationContext(
                        raw_event_id=msg.raw_event_id,
                        group_id=msg.chat_id,
                        group_name=msg.chat_name,
                        user_id=msg.user_id,
                        nickname=msg.nickname,
                        message_text=msg.message_text,
                    )
                )
                synced += 1
            logger.info("sync_feishu_messages: chat_id=%s total=%d synced=%d", chat_id, len(messages), synced)

        await container.learning_repo.finish_job_lock(job_name="sync_feishu_messages", biz_key=biz_key, status="success")
    except Exception:
        logger.exception("sync feishu messages job failed")
        await container.learning_repo.finish_job_lock(job_name="sync_feishu_messages", biz_key=biz_key, status="failed")
