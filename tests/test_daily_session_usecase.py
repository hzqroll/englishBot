from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.application.daily_session_usecases import DailySessionUseCase
from src.domain.value_objects.learning import LessonBundle, LessonTargetItem, LessonTask
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.db.session import create_engine, create_session_factory, init_db


@pytest.mark.asyncio
async def test_daily_session_usecase_rotates_roles_and_enters_rescue_mode(tmp_path):
    db_path = tmp_path / "daily-session-usecase.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)
    usecase = DailySessionUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        voice_required_weekdays=(1, 4),
        monthly_benchmark_weekday=6,
        rescue_lookback_days=2,
    )

    group = await identity_repo.ensure_group("oc_test_group", "英语学习群")
    alice = await identity_repo.ensure_user("u-alice", "Alice")
    bob = await identity_repo.ensure_user("u-bob", "Bob")
    await identity_repo.enroll_user(alice.id, group.id)
    await identity_repo.enroll_user(bob.id, group.id)

    target_date = date(2026, 4, 14)
    previous_date = target_date - timedelta(days=1)
    lesson = LessonBundle(
        source_name="ted-fallback",
        external_id="session-plan-1",
        title="Delay Update",
        url="https://example.com/delay-update",
        transcript="We are currently blocked by a dependency issue and need to reschedule the release.",
        difficulty="beginner",
        biz_date=target_date,
        package_snapshot={
            "yesterday_review": [
                {
                    "content_text": "follow up",
                    "correct_text": "follow up on",
                }
            ]
        },
        target_items=[
            LessonTargetItem(
                entry_key="blocked_by",
                entry_type="chunk",
                text="blocked by",
                phonetic="",
                meaning_zh="被...卡住",
                usage_scene="项目阻塞",
                example="We are blocked by a dependency issue.",
                target_role="core_chunk",
            ),
            LessonTargetItem(
                entry_key="reschedule",
                entry_type="word",
                text="reschedule",
                phonetic="",
                meaning_zh="改期",
                usage_scene="会议和发布",
                example="We need to reschedule the release.",
                target_role="support_word",
            ),
        ],
        tasks=[LessonTask(task_type="scenario_reply", prompt="说明延期原因", answer_key=None, score_weight=10)],
    )
    stored_lesson = await learning_repo.upsert_content_and_lesson(group.id, lesson)
    await learning_repo.upsert_daily_session(
        group_id=group.id,
        biz_date=previous_date,
        lesson_id=stored_lesson.id,
        title="Yesterday Session",
        role_a_user_id=alice.id,
        role_a_label="Alice",
        role_a_status="pending",
        role_b_user_id=bob.id,
        role_b_label="Bob",
        role_b_status="pending",
        required_chunks_json=["blocked by"],
        capture_prompt="昨日任务",
        rescue_mode=False,
        voice_required=False,
        benchmark_required=False,
        status="active",
        summary_json={"evidences": []},
    )

    session, _, _, _ = await usecase.ensure_daily_session(chat_id="oc_test_group", biz_date=target_date)
    envelope = await usecase.build_execution_envelope(chat_id="oc_test_group", biz_date=target_date)
    reminder = await usecase.build_baton_reminder(chat_id="oc_test_group", biz_date=target_date, phase="midday")

    assert session.rescue_mode is True
    assert session.role_a_user_id == bob.id
    assert session.role_b_user_id == alice.id
    assert session.voice_required is True
    assert session.required_chunks_json[:2] == ["blocked by", "follow up on"]
    assert envelope.card_document is not None
    assert envelope.card_document.sections[0].title == "今日目标"
    assert any("恢复模式" in (envelope.card_document.subtitle or "") for _ in [0])
    assert envelope.card_document.metadata["chat_id"] == "oc_test_group"
    assert envelope.card_document.metadata["biz_date"] == target_date.isoformat()
    assert reminder is not None
    assert reminder.envelope.card_document is not None
    assert reminder.envelope.card_document.title == "中午接棒提醒"
    assert reminder.envelope.card_document.metadata["chat_id"] == "oc_test_group"

    await engine.dispose()


@pytest.mark.asyncio
async def test_daily_session_actions_update_state(tmp_path):
    db_path = tmp_path / "daily-session-action.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)
    usecase = DailySessionUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
    )

    group = await identity_repo.ensure_group("oc_action_group", "Action Group")
    alice = await identity_repo.ensure_user("u-alice", "Alice")
    bob = await identity_repo.ensure_user("u-bob", "Bob")
    target_date = date(2026, 4, 15)

    lesson = LessonBundle(
        source_name="ted-fallback",
        external_id="session-plan-action",
        title="Action Session",
        url="https://example.com/action",
        transcript="Action transcript",
        difficulty="beginner",
        biz_date=target_date,
        package_snapshot={},
        target_items=[
            LessonTargetItem(
                entry_key="follow_up",
                entry_type="chunk",
                text="follow up",
                phonetic="",
                meaning_zh="跟进",
                usage_scene="项目跟进",
                example="I will follow up tomorrow.",
                target_role="core_chunk",
            )
        ],
        tasks=[LessonTask(task_type="scenario_reply", prompt="先发起", answer_key=None, score_weight=10)],
    )
    stored_lesson = await learning_repo.upsert_content_and_lesson(group.id, lesson)
    session = await learning_repo.upsert_daily_session(
        group_id=group.id,
        biz_date=target_date,
        lesson_id=stored_lesson.id,
        title="Action Session",
        role_a_user_id=alice.id,
        role_a_label="Alice",
        role_a_status="pending",
        role_b_user_id=bob.id,
        role_b_label="Bob",
        role_b_status="pending",
        required_chunks_json=["follow up"],
        capture_prompt="action",
        rescue_mode=False,
        voice_required=False,
        benchmark_required=False,
        status="active",
        summary_json={"evidences": []},
    )

    claim_text = await usecase.claim_baton(
        chat_id="oc_action_group",
        actor_open_id="u-alice",
        biz_date=target_date,
    )
    assert "第一棒" in claim_text

    rescue_text = await usecase.enter_rescue_mode(
        chat_id="oc_action_group",
        actor_open_id="u-alice",
        biz_date=target_date,
    )
    assert "保底版" in rescue_text

    remind_text = await usecase.remind_later(
        chat_id="oc_action_group",
        actor_open_id="u-bob",
        biz_date=target_date,
    )
    assert "再提醒" in remind_text

    refreshed = await learning_repo.get_daily_session(group_id=group.id, biz_date=target_date)
    assert refreshed is not None
    assert refreshed.id == session.id
    assert refreshed.rescue_mode is True
    assert refreshed.status == "rescue"
    assert "last_claim" in refreshed.summary_json
    assert "remind_later_requests" in refreshed.summary_json

    await engine.dispose()
