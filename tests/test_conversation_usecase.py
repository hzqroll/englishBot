from __future__ import annotations

from datetime import date

import pytest

from src.application.conversation_usecases import ConversationContext, ConversationUseCase
from src.application.daily_session_usecases import DailySessionUseCase
from src.domain.services.conversation_analysis import ConversationAnalysisService
from src.domain.value_objects.learning import LessonBundle, LessonTask
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.db.session import create_engine, create_session_factory, init_db


@pytest.mark.asyncio
async def test_conversation_usecase_observes_passive_messages_and_commands(tmp_path):
    db_path = tmp_path / "conversation-usecase.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)
    usecase = ConversationUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        analysis_service=ConversationAnalysisService(),
    )

    group = await identity_repo.ensure_group("204257012", "英语学习群")
    lesson = LessonBundle(
        source_name="ted-fallback",
        external_id="conversation-lesson",
        title="Reschedule the Meeting",
        url="https://example.com/lesson",
        transcript="We need to reschedule the meeting before the deadline tomorrow morning.",
        difficulty="beginner",
        biz_date=date.today(),
        tasks=[LessonTask(task_type="scenario_reply", prompt="回复一句改会表达", answer_key=None, score_weight=10)],
    )
    await learning_repo.upsert_content_and_lesson(group.id, lesson)

    await usecase.observe_passive_group_message(
        ConversationContext(
            raw_event_id="passive-1",
            group_id="204257012",
            group_name="英语学习群",
            user_id="472583006",
            nickname="Rainbow",
            message_text="Can we reschedule the meeting before the deadline?",
        )
    )

    passive_event = await learning_repo.get_message_event_by_raw_event_id(raw_event_id="passive-1")
    assert passive_event is not None
    assert passive_event.source_type == "passive_group_message"
    assert passive_event.is_command is False
    assert passive_event.is_to_bot is False
    assert passive_event.language_guess == "english"
    assert passive_event.analysis_status == "tagged"
    assert passive_event.biz_date_local == date.today()

    passive_evidences = await learning_repo.list_conversation_evidences_for_message(
        message_event_id=passive_event.id
    )
    evidence_types = {item.evidence_type for item in passive_evidences}
    assert "english_attempt" in evidence_types
    assert "question_asked" in evidence_types
    assert "target_hit" in evidence_types
    materials = await learning_repo.get_user_day_conversation_materials(
        user_id=passive_event.user_id,
        group_id=passive_event.group_id,
        target_date=date.today(),
    )
    passive_material = next(item for item in materials if item["event_id"] == passive_event.id)
    assert passive_material["source_type"] == "passive_group_message"
    assert {item["evidence_type"] for item in passive_material["evidences"]} >= {
        "english_attempt",
        "question_asked",
        "target_hit",
    }

    await usecase.record_command_message(
        ConversationContext(
            raw_event_id="command-1",
            group_id="204257012",
            group_name="英语学习群",
            user_id="472583006",
            nickname="Rainbow",
            message_text="今日任务",
        )
    )

    command_event = await learning_repo.get_message_event_by_raw_event_id(raw_event_id="command-1")
    assert command_event is not None
    assert command_event.source_type == "learning_command"
    assert command_event.is_command is True
    assert command_event.analysis_status == "pending"

    command_evidences = await learning_repo.list_conversation_evidences_for_message(
        message_event_id=command_event.id
    )
    assert command_evidences == []
    materials = await learning_repo.get_user_day_conversation_materials(
        user_id=command_event.user_id,
        group_id=command_event.group_id,
        target_date=date.today(),
    )
    command_material = next(item for item in materials if item["event_id"] == command_event.id)
    assert command_material["source_type"] == "learning_command"
    assert command_material["evidences"] == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_conversation_usecase_binds_messages_to_daily_session_and_advances_roles(tmp_path):
    db_path = tmp_path / "conversation-session.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)
    daily_session_usecase = DailySessionUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
    )
    usecase = ConversationUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        analysis_service=ConversationAnalysisService(),
        daily_session_usecase=daily_session_usecase,
    )

    group = await identity_repo.ensure_group("204257012", "英语学习群")
    alice = await identity_repo.ensure_user("u-alice", "Alice")
    bob = await identity_repo.ensure_user("u-bob", "Bob")
    lesson = LessonBundle(
        source_name="ted-fallback",
        external_id="session-lesson",
        title="Project Delay Update",
        url="https://example.com/session-lesson",
        transcript="We are currently blocked by a dependency issue and need to reschedule the release.",
        difficulty="beginner",
        biz_date=date.today(),
        tasks=[LessonTask(task_type="scenario_reply", prompt="说明项目延期原因", answer_key=None, score_weight=10)],
    )
    stored_lesson = await learning_repo.upsert_content_and_lesson(group.id, lesson)
    await learning_repo.upsert_daily_session(
        group_id=group.id,
        biz_date=date.today(),
        lesson_id=stored_lesson.id,
        title=lesson.title,
        role_a_user_id=alice.id,
        role_a_label="Alice",
        role_a_status="pending",
        role_b_user_id=bob.id,
        role_b_label="Bob",
        role_b_status="pending",
        required_chunks_json=["reschedule", "blocked by"],
        capture_prompt="A 先说明延期原因，B 再追问。",
        rescue_mode=False,
        voice_required=False,
        benchmark_required=False,
        status="active",
        summary_json={"evidences": []},
    )

    await usecase.observe_passive_group_message(
        ConversationContext(
            raw_event_id="session-passive-a",
            group_id="204257012",
            group_name="英语学习群",
            user_id="u-alice",
            nickname="Alice",
            message_text="We are currently blocked by a dependency issue, so we need to reschedule the release.",
        )
    )
    event_a = await learning_repo.get_message_event_by_raw_event_id(raw_event_id="session-passive-a")
    session_after_a = await learning_repo.get_daily_session(group_id=group.id, biz_date=date.today())

    assert event_a is not None
    assert event_a.session_id == session_after_a.id
    assert session_after_a.role_a_status == "completed"
    assert session_after_a.status == "awaiting_role_b"

    await usecase.observe_passive_group_message(
        ConversationContext(
            raw_event_id="session-passive-b",
            group_id="204257012",
            group_name="英语学习群",
            user_id="u-bob",
            nickname="Bob",
            message_text="Could you clarify what the blocker is and what changed in the timeline?",
        )
    )
    event_b = await learning_repo.get_message_event_by_raw_event_id(raw_event_id="session-passive-b")
    session_after_b = await learning_repo.get_daily_session(group_id=group.id, biz_date=date.today())

    assert event_b is not None
    assert event_b.session_id == session_after_b.id
    assert session_after_b.role_b_status == "completed"
    assert session_after_b.status == "completed"

    await engine.dispose()
