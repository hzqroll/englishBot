from __future__ import annotations

from datetime import date, datetime

import pytest

from src.domain.value_objects.learning import ErrorPointPayload, LessonBundle, LessonTargetItem, LessonTask
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.db.session import create_engine, create_session_factory, init_db


@pytest.mark.asyncio
async def test_learning_repository_builds_real_weekly_stats(tmp_path):
    db_path = tmp_path / "learning-test.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)

    group = await identity_repo.ensure_group("10001", "英语群")
    user = await identity_repo.ensure_user("20001", "Alice")
    await identity_repo.enroll_user(user.id, group.id)

    translation_event = await learning_repo.create_message_event(
        raw_event_id="evt-1",
        group_id=group.id,
        user_id=user.id,
        message_text="你好，世界",
        event_type="at_message",
    )
    await learning_repo.create_interaction_result(
        event_id=translation_event.id,
        action_type="chinese_translation",
        provider="google+doubao",
        reply_text="Hello, world",
    )
    correction_event = await learning_repo.create_message_event(
        raw_event_id="evt-2",
        group_id=group.id,
        user_id=user.id,
        message_text="I very like English.",
        event_type="at_message",
    )
    await learning_repo.create_interaction_result(
        event_id=correction_event.id,
        action_type="english_correction",
        provider="doubao",
        reply_text="I like English very much.",
    )
    payloads = [
        ErrorPointPayload(
            error_type="word_choice",
            source_fragment="very like",
            correct_fragment="like ... very much",
            explanation="动词 like 不直接和 very 连用。",
        ),
        ErrorPointPayload(
            error_type="tense",
            source_fragment="He go to school",
            correct_fragment="He goes to school",
            explanation="一般现在时第三人称单数动词要加 s。",
        ),
    ]
    error_points = await learning_repo.upsert_error_points(
        user_id=user.id,
        group_id=group.id,
        payloads=payloads,
    )
    await learning_repo.create_error_occurrences(
        event_id=correction_event.id,
        user_id=user.id,
        group_id=group.id,
        payloads=payloads,
        error_point_ids=[item.id for item in error_points],
    )

    lesson = LessonBundle(
        source_name="ted-fallback",
        external_id="lesson-1",
        title="Daily Habit",
        url="https://example.com/lesson-1",
        transcript="Learning English every day helps vocabulary and confidence.",
        difficulty="beginner",
        biz_date=date.today(),
        theme_key="daily_habit",
        package_snapshot={"title": "Daily Habit", "targets": ["habit", "confidence"]},
        target_items=[
            LessonTargetItem(
                entry_key="habit",
                entry_type="word",
                text="habit",
                phonetic="/ˈhæbɪt/",
                meaning_zh="习惯",
                usage_scene="描述学习方式",
                example="A daily habit helps you improve.",
                target_role="support_word",
            ),
            LessonTargetItem(
                entry_key="build_confidence",
                entry_type="chunk",
                text="build confidence",
                phonetic="/bɪld ˈkɒnfɪdəns/",
                meaning_zh="建立信心",
                usage_scene="鼓励学习者",
                example="Practice every day to build confidence.",
                target_role="core_chunk",
            ),
        ],
        tasks=[
            LessonTask(task_type="vocabulary", prompt="列出 3 个词汇", answer_key=None, score_weight=30),
            LessonTask(task_type="reading", prompt="总结核心观点", answer_key=None, score_weight=30),
        ],
    )
    await learning_repo.upsert_content_and_lesson(group.id, lesson)
    tasks = await learning_repo.get_today_tasks(group_id=group.id, biz_date=date.today())
    lesson_detail = await learning_repo.get_today_lesson_detail(group_id=group.id, biz_date=date.today())
    target_items = await learning_repo.get_target_items_for_lesson(lesson_id=lesson_detail[0].id)
    target_terms = await learning_repo.get_target_terms_for_group_date(group_id=group.id, biz_date=date.today())
    await learning_repo.submit_task(
        task_id=tasks[0].id,
        user_id=user.id,
        submission_text="habit, vocabulary, confidence",
        score=90,
        feedback="做得不错",
    )
    await learning_repo.award_points(user_id=user.id, points=10, reason="daily_task")
    await learning_repo.award_points(user_id=user.id, points=6, reason="review_session")
    await learning_repo.ensure_review_items(
        user_id=user.id,
        source_type="correction",
        source_ref_id="evt-2",
        error_point_ids=[item.id for item in error_points],
        interval_days=1,
        next_review_at=error_points[0].last_seen_at,
        status="pending",
    )

    quiz_session = await learning_repo.create_quiz_session(
        biz_week="2026-W14",
        group_id=group.id,
        user_id=user.id,
    )
    await learning_repo.add_quiz_questions(
        session_id=quiz_session.id,
        questions=[
            {
                "source_type": "review:error_point:1",
                "stem": "Which phrase is better?",
                "options": ["very like", "like ... very much"],
                "answer_key": "B",
                "explanation": "固定搭配更自然。",
            }
        ],
    )
    await learning_repo.save_quiz_answers(
        session_id=quiz_session.id,
        answers=[
            {
                "question_id": (await learning_repo.get_quiz_questions(session_id=quiz_session.id))[0].id,
                "user_answer": "B",
                "is_correct": True,
                "score": 10,
            }
        ],
        total_score=88,
    )

    evidence = await learning_repo.get_learning_evidence(user_id=user.id, group_id=group.id)
    stats = await learning_repo.get_weekly_report_stats(user_id=user.id, group_id=group.id)
    daily_digest = await learning_repo.get_daily_error_digest(
        user_id=user.id,
        group_id=group.id,
        target_date=datetime.now().astimezone().date(),
    )
    daily_progress = await learning_repo.get_daily_progress_stats(
        user_id=user.id,
        group_id=group.id,
        target_date=datetime.now().astimezone().date(),
    )
    recent_tasks = await learning_repo.get_recent_tasks_for_quiz(group_id=group.id, limit=5)
    evidence_stats = await learning_repo.get_daily_conversation_evidence_stats(
        user_id=user.id,
        group_id=group.id,
        target_date=datetime.now().astimezone().date(),
    )
    snapshot = await learning_repo.upsert_daily_learning_snapshot(
        biz_date=datetime.now().astimezone().date(),
        user_id=user.id,
        group_id=group.id,
        lesson_id=lesson_detail[0].id,
        summary_json={
            "stats": {
                "translation_count": 1,
                "correction_count": 1,
                "today_task_total": 2,
                "today_task_completed": 1,
                "points_earned": 16,
                "level": "beginner",
            }
        },
        mastery_level="started_using",
        mastery_reason="今天已经开始尝试使用英语表达。",
        model_summary="继续保持，明天继续复用核心词块。",
        activity_score=5,
        evidence_score=3,
    )
    card_snapshot = await learning_repo.upsert_daily_card_snapshot(
        biz_date=datetime.now().astimezone().date(),
        user_id=user.id,
        group_id=group.id,
        card_type="progress",
        plain_text="今日学习进度",
        card_document_json={"title": "今日学习进度"},
    )
    await learning_repo.update_daily_card_snapshot_images(
        snapshot_id=card_snapshot.id,
        image_paths_json=["/tmp/demo-card.png"],
    )
    delivery_log = await learning_repo.create_message_delivery_log(
        group_id=group.id,
        user_id=user.id,
        job_name="daily_progress",
        card_snapshot_id=card_snapshot.id,
        delivery_mode="image_single",
        success=True,
        provider_response="sent",
    )
    stored_snapshot = await learning_repo.get_daily_learning_snapshot(
        user_id=user.id,
        group_id=group.id,
        biz_date=datetime.now().astimezone().date(),
    )
    stored_card_snapshot = await learning_repo.get_daily_card_snapshot(
        biz_date=datetime.now().astimezone().date(),
        group_id=group.id,
        user_id=user.id,
        card_type="progress",
    )

    assert evidence["translation_count"] == 1
    assert evidence["correction_count"] == 1
    assert evidence["task_completion_count"] == 1
    assert evidence["quiz_average_score"] == 88.0
    assert lesson_detail[0].theme_key == "daily_habit"
    assert lesson_detail[0].package_snapshot_json["title"] == "Daily Habit"
    assert len(target_items) == 2
    assert "habit" in target_terms
    assert "confidence" in target_terms
    assert daily_digest["word_total"] == 1
    assert daily_digest["grammar_total"] == 1
    assert daily_progress["word_error_count"] == 1
    assert daily_progress["grammar_error_count"] == 1
    assert daily_progress["today_task_completed"] == 1
    assert daily_progress["points_earned"] == 16
    assert daily_progress["has_activity"] is True
    assert stats["learning_days"] >= 1
    assert stats["task_completion_rate"] == 0.5
    assert "word_choice" in stats["weak_points"]
    assert stats["points_earned"] == 16
    assert stats["current_streak"] == 1
    assert recent_tasks
    assert evidence_stats["total_messages"] >= 2
    assert snapshot.id == stored_snapshot.id
    assert stored_snapshot.mastery_level == "started_using"
    assert stored_card_snapshot is not None
    assert stored_card_snapshot.image_paths_json == ["/tmp/demo-card.png"]
    assert delivery_log.delivery_mode == "image_single"

    await engine.dispose()


@pytest.mark.asyncio
async def test_learning_repository_force_rerun_job_lock(tmp_path):
    db_path = tmp_path / "job-lock-test.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    learning_repo = LearningRepository(session_factory)

    assert await learning_repo.acquire_job_lock(job_name="weekly_report", biz_key="2026-W15") is True
    await learning_repo.finish_job_lock(job_name="weekly_report", biz_key="2026-W15", status="success")
    assert await learning_repo.acquire_job_lock(job_name="weekly_report", biz_key="2026-W15") is False
    assert await learning_repo.acquire_job_lock(
        job_name="weekly_report",
        biz_key="2026-W15",
        force=True,
    ) is True

    await engine.dispose()
