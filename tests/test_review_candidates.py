from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.application.learning_usecases import EnrollmentContext, LearningUseCase
from src.application.report_usecases import ReportUseCase
from src.domain.services.leveling import LevelService
from src.domain.services.review import ReviewScheduler
from src.domain.value_objects.conversation import ConversationEvidencePayload
from src.domain.value_objects.learning import ErrorPointPayload
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.db.session import create_engine, create_session_factory, init_db
from src.infrastructure.providers.curriculum_static import StaticCurriculumProvider
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider


@pytest.mark.asyncio
async def test_review_candidates_are_generated_and_reflected_in_progress(tmp_path):
    db_path = tmp_path / "review-candidates.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)
    project_root = Path(__file__).resolve().parents[1]
    curriculum_provider = StaticCurriculumProvider(
        lexicon_path=project_root / "resources" / "lexicon" / "bec_advanced.yaml",
        theme_path=project_root / "resources" / "themes" / "office_scenarios.yaml",
    )
    feedback_provider = OpenAICompatibleProvider(api_key="", base_url="", model="")
    level_service = LevelService()
    review_scheduler = ReviewScheduler()
    learning_usecase = LearningUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        level_service=level_service,
        review_scheduler=review_scheduler,
        content_provider=curriculum_provider,
        feedback_provider=feedback_provider,
        points_per_task=10,
        points_per_review=6,
    )
    report_usecase = ReportUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        summary_provider=feedback_provider,
        level_service=level_service,
    )

    group_id = "204257012"
    user_id = "472583006"
    nickname = "Rainbow"
    await learning_usecase.enroll(
        EnrollmentContext(
            chat_id=group_id,
            group_name="英语学习群",
            open_id=user_id,
            nickname=nickname,
        )
    )
    group = await identity_repo.ensure_group(group_id, "英语学习群")
    user = await identity_repo.ensure_user(user_id, nickname)

    today = datetime.now().astimezone().date()
    yesterday = today.fromordinal(today.toordinal() - 1)

    await learning_usecase.build_today_lesson(chat_id=group_id, biz_date=yesterday)
    yesterday_event = await learning_repo.create_message_event(
        raw_event_id="yesterday-correction",
        group_id=group.id,
        session_id=None,
        user_id=user.id,
        message_text="I very like speak English.",
        event_type="at_message",
        source_type="at_message",
        is_to_bot=True,
        is_command=False,
        language_guess="english",
        analysis_status="summarized",
        biz_date_local=yesterday,
    )
    payloads = [
        ErrorPointPayload(
            error_type="word_choice",
            source_fragment="very like",
            correct_fragment="like ... very much",
            explanation="更自然的搭配应使用 like very much。",
        ),
        ErrorPointPayload(
            error_type="grammar",
            source_fragment="speak English",
            correct_fragment="speak English fluently",
            explanation="补足语义会更完整。",
        ),
    ]
    stored = await learning_repo.upsert_error_points(
        user_id=user.id,
        group_id=group.id,
        payloads=payloads,
    )
    await learning_repo.create_error_occurrences(
        event_id=yesterday_event.id,
        user_id=user.id,
        group_id=group.id,
        payloads=payloads,
        error_point_ids=[item.id for item in stored],
        created_at=datetime.combine(yesterday, datetime.min.time(), tzinfo=UTC),
    )

    await learning_usecase.build_today_lesson(chat_id=group_id, biz_date=today)
    today_lesson = await learning_repo.get_today_lesson_detail(group_id=group.id, biz_date=today)
    assert today_lesson is not None
    lesson, _ = today_lesson
    assert lesson.package_snapshot_json["yesterday_review"]
    assert len(lesson.package_snapshot_json["yesterday_review"]) == 3

    review_candidates = await learning_repo.list_review_candidates(
        user_id=user.id,
        group_id=group.id,
        biz_date=today,
    )
    assert len(review_candidates) == 3
    assert any(item.source_type == "error_occurrence" for item in review_candidates)
    assert any(item.used_in_next_day_task for item in review_candidates)

    tasks = await learning_repo.get_tasks_for_lesson(lesson_id=lesson.id)
    assert any("请至少复用昨日回顾中的 1 个表达" in task.prompt for task in tasks)

    await learning_repo.submit_task(
        task_id=tasks[-1].id,
        user_id=user.id,
        submission_text="I like English very much. Also, could we reschedule the meeting?",
        score=90,
        feedback="很好，已经开始复用昨日表达。",
    )
    passive_event = await learning_repo.create_message_event(
        raw_event_id="today-passive-1",
        group_id=group.id,
        session_id=None,
        user_id=user.id,
        message_text="Could we reschedule the meeting? This time works better for me.",
        event_type="group_message",
        source_type="passive_group_message",
        is_to_bot=False,
        is_command=False,
        language_guess="english",
        analysis_status="tagged",
        biz_date_local=today,
    )
    await learning_repo.create_conversation_evidences(
        message_event_id=passive_event.id,
        user_id=user.id,
        group_id=group.id,
        biz_date=today,
        payloads=[
            ConversationEvidencePayload(
                evidence_type="english_attempt",
                evidence_score=2,
                payload_json={"text": "Could we reschedule the meeting?"},
            ),
            ConversationEvidencePayload(
                evidence_type="target_hit",
                evidence_score=3,
                payload_json={"token": "reschedule the meeting"},
            ),
            ConversationEvidencePayload(
                evidence_type="question_asked",
                evidence_score=1,
                payload_json={"text": "Could we reschedule the meeting?"},
            ),
        ],
    )

    envelope = await report_usecase.build_daily_progress_envelope(
        chat_id=group_id,
        open_id=user_id,
        nickname=nickname,
        target_date=today,
    )
    assert envelope is not None
    assert "今晚进展" in envelope.plain_text
    assert envelope.card_document is not None
    assert any(section.title == "学习证据" for section in envelope.card_document.sections)
    assert any(section.title == "下一步" for section in envelope.card_document.sections)
    assert envelope.card_snapshot_id is not None

    evaluated = await learning_repo.list_review_candidates(
        user_id=user.id,
        group_id=group.id,
        biz_date=today,
    )
    assert any(item.recalled_successfully is True for item in evaluated)

    snapshot = await learning_repo.get_daily_learning_snapshot(
        user_id=user.id,
        group_id=group.id,
        biz_date=today,
    )
    assert snapshot is not None
    assert snapshot.mastery_level in {"started_using", "basically_mastered", "needs_strengthening"}
    assert snapshot.summary_json["evidence_stats"]["target_hit_count"] >= 1
    assert snapshot.summary_json["recall_results"]

    card_snapshot = await learning_repo.get_daily_card_snapshot(
        biz_date=today,
        group_id=group.id,
        user_id=user.id,
        card_type="progress",
    )
    assert card_snapshot is not None
    assert card_snapshot.card_document_json["title"] == "今晚进展"

    await engine.dispose()


@pytest.mark.asyncio
async def test_daily_progress_uses_passive_conversation_activity(tmp_path):
    db_path = tmp_path / "daily-progress-passive.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)
    feedback_provider = OpenAICompatibleProvider(api_key="", base_url="", model="")
    report_usecase = ReportUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        summary_provider=feedback_provider,
        level_service=LevelService(),
    )

    group = await identity_repo.ensure_group("204257012", "英语学习群")
    user = await identity_repo.ensure_user("472583006", "Rainbow")
    await identity_repo.enroll_user(user.id, group.id)
    today = datetime.now().astimezone().date()

    passive_event = await learning_repo.create_message_event(
        raw_event_id="passive-progress-1",
        group_id=group.id,
        session_id=None,
        user_id=user.id,
        message_text="Could we move the meeting to Friday morning?",
        event_type="group_message",
        source_type="passive_group_message",
        is_to_bot=False,
        is_command=False,
        language_guess="english",
        analysis_status="tagged",
        biz_date_local=today,
    )
    await learning_repo.create_conversation_evidences(
        message_event_id=passive_event.id,
        user_id=user.id,
        group_id=group.id,
        biz_date=today,
        payloads=[
            ConversationEvidencePayload(
                evidence_type="english_attempt",
                evidence_score=2,
                payload_json={"text": "Could we move the meeting to Friday morning?"},
            ),
            ConversationEvidencePayload(
                evidence_type="question_asked",
                evidence_score=1,
                payload_json={"text": "Could we move the meeting to Friday morning?"},
            ),
        ],
    )

    envelope = await report_usecase.build_daily_progress_envelope(
        chat_id="204257012",
        open_id="472583006",
        nickname="Rainbow",
        target_date=today,
    )

    assert envelope is not None
    assert "今晚进展" in envelope.plain_text
    assert envelope.card_document is not None
    assert any(section.title == "今天到了哪" for section in envelope.card_document.sections)

    await engine.dispose()


@pytest.mark.asyncio
async def test_daily_summary_generates_xhs_payload_and_card(tmp_path):
    db_path = tmp_path / "daily-summary.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)
    project_root = Path(__file__).resolve().parents[1]
    curriculum_provider = StaticCurriculumProvider(
        lexicon_path=project_root / "resources" / "lexicon" / "bec_advanced.yaml",
        theme_path=project_root / "resources" / "themes" / "office_scenarios.yaml",
    )
    feedback_provider = OpenAICompatibleProvider(api_key="", base_url="", model="")
    level_service = LevelService()
    review_scheduler = ReviewScheduler()
    learning_usecase = LearningUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        level_service=level_service,
        review_scheduler=review_scheduler,
        content_provider=curriculum_provider,
        feedback_provider=feedback_provider,
        points_per_task=10,
        points_per_review=6,
    )
    report_usecase = ReportUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        summary_provider=feedback_provider,
        level_service=level_service,
    )

    group_id = "204257012"
    user_id = "472583006"
    nickname = "Rainbow"
    await learning_usecase.enroll(
        EnrollmentContext(
            chat_id=group_id,
            group_name="英语学习群",
            open_id=user_id,
            nickname=nickname,
        )
    )
    group = await identity_repo.ensure_group(group_id, "英语学习群")
    user = await identity_repo.ensure_user(user_id, nickname)
    today = datetime.now().astimezone().date()

    await learning_usecase.build_today_lesson(chat_id=group_id, biz_date=today)
    event = await learning_repo.create_message_event(
        raw_event_id="daily-summary-1",
        group_id=group.id,
        session_id=None,
        user_id=user.id,
        message_text="Could we wrap up this task by Friday?",
        event_type="group_message",
        source_type="passive_group_message",
        is_to_bot=False,
        is_command=False,
        language_guess="english",
        analysis_status="tagged",
        biz_date_local=today,
    )
    await learning_repo.create_conversation_evidences(
        message_event_id=event.id,
        user_id=user.id,
        group_id=group.id,
        biz_date=today,
        payloads=[
            ConversationEvidencePayload(
                evidence_type="english_attempt",
                evidence_score=2,
                payload_json={"text": "Could we wrap up this task by Friday?"},
            ),
        ],
    )
    await learning_repo.upsert_daily_user_words(
        biz_date=today,
        user_id=user.id,
        group_id=group.id,
        words=["resilient", "align"],
    )

    envelope = await report_usecase.build_daily_summary_envelope(
        chat_id=group_id,
        open_id=user_id,
        nickname=nickname,
        target_date=today,
    )

    assert envelope is not None
    assert envelope.card_type == "daily_summary"
    assert envelope.card_document is not None
    assert envelope.card_snapshot_id is not None
    assert any(section.title == "小红书发布文案" for section in envelope.card_document.sections)

    snapshot = await learning_repo.get_daily_learning_snapshot(
        user_id=user.id,
        group_id=group.id,
        biz_date=today,
    )
    assert snapshot is not None
    payload = snapshot.summary_json["xhs_payload"]
    assert "图片生成提示词" in payload
    assert payload["图片生成提示词"]["今日目标图"]
    assert payload["小红书发布文案"]["标签"]

    await engine.dispose()
