from __future__ import annotations

from datetime import date

import pytest

from src.domain.value_objects.learning import ErrorPointPayload, LessonBundle, LessonTask
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
    error_points = await learning_repo.upsert_error_points(
        user_id=user.id,
        group_id=group.id,
        payloads=[
            ErrorPointPayload(
                error_type="word_choice",
                source_fragment="very like",
                correct_fragment="like ... very much",
                explanation="动词 like 不直接和 very 连用。",
            )
        ],
    )

    lesson = LessonBundle(
        source_name="ted-fallback",
        external_id="lesson-1",
        title="Daily Habit",
        url="https://example.com/lesson-1",
        transcript="Learning English every day helps vocabulary and confidence.",
        difficulty="beginner",
        biz_date=date.today(),
        tasks=[
            LessonTask(task_type="vocabulary", prompt="列出 3 个词汇", answer_key=None, score_weight=30),
            LessonTask(task_type="reading", prompt="总结核心观点", answer_key=None, score_weight=30),
        ],
    )
    await learning_repo.upsert_content_and_lesson(group.id, lesson)
    tasks = await learning_repo.get_today_tasks(group_id=group.id, biz_date=date.today())
    await learning_repo.submit_task(
        task_id=tasks[0].id,
        user_id=user.id,
        submission_text="habit, vocabulary, confidence",
        score=90,
        feedback="做得不错",
    )
    await learning_repo.award_points(user_id=user.id, points=10, reason="daily_task")
    await learning_repo.ensure_review_items(
        user_id=user.id,
        source_type="correction",
        source_ref_id="evt-2",
        error_point_ids=[error_points[0].id],
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
    recent_tasks = await learning_repo.get_recent_tasks_for_quiz(group_id=group.id, limit=5)

    assert evidence["translation_count"] == 1
    assert evidence["correction_count"] == 1
    assert evidence["task_completion_count"] == 1
    assert evidence["quiz_average_score"] == 88.0
    assert stats["learning_days"] >= 1
    assert stats["task_completion_rate"] == 0.5
    assert stats["weak_points"] == ["word_choice"]
    assert stats["points_earned"] == 10
    assert stats["current_streak"] == 1
    assert recent_tasks

    await engine.dispose()
