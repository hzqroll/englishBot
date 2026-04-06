from __future__ import annotations

from datetime import date

import pytest

from src.application.conversation_usecases import ConversationContext, ConversationUseCase
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
