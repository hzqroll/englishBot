from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from src.application.daily_session_usecases import DailySessionUseCase
from src.domain.value_objects.learning import LessonBundle, LessonTargetItem, LessonTask
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.db.session import create_engine, create_session_factory, init_db
from src.infrastructure.settings.models import PromptsSettings


class _LLMProviderStub:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[str] = []

    async def generate_feedback(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self._responses:
            return ""
        return self._responses.pop(0)


async def _build_daily_session_context(
    tmp_path: Path,
    *,
    llm_responses: list[str],
) -> tuple[DailySessionUseCase, IdentityRepository, LearningRepository, int, AsyncEngine]:
    db_path = tmp_path / "dialogue-guardian.db"
    engine = create_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)
    llm_provider = _LLMProviderStub(llm_responses)
    usecase = DailySessionUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        llm_provider=llm_provider,  # type: ignore[arg-type]
        prompts=PromptsSettings(),
    )

    group = await identity_repo.ensure_group("oc_test_dialogue_guardian", "英语群")
    user = await identity_repo.ensure_user("u-dialogue-user", "Tester")
    target_date = date(2026, 4, 20)
    lesson = LessonBundle(
        source_name="ted-fallback",
        external_id="dialogue-guardian-lesson",
        title="Client Update Handoff",
        url="https://example.com/dialogue-guardian",
        transcript="The team prepares a quick client update before an internal handoff.",
        difficulty="beginner",
        biz_date=target_date,
        package_snapshot={"scene": "handoff at a daily standup"},
        target_items=[
            LessonTargetItem(
                entry_key="follow_up",
                entry_type="chunk",
                text="follow up",
                phonetic="",
                meaning_zh="跟进",
                usage_scene="daily standup",
                example="I will follow up with the client by noon.",
                target_role="core_chunk",
            )
        ],
        tasks=[LessonTask(task_type="scenario_reply", prompt="Discuss next steps", answer_key=None, score_weight=10)],
    )
    stored_lesson = await learning_repo.upsert_content_and_lesson(group.id, lesson)
    await learning_repo.upsert_daily_session(
        group_id=group.id,
        biz_date=target_date,
        lesson_id=stored_lesson.id,
        title=lesson.title,
        role_a_user_id=user.id,
        role_a_label="Tester",
        role_a_status="pending",
        role_b_user_id=None,
        role_b_label="",
        role_b_status="pending",
        required_chunks_json=["follow up"],
        capture_prompt="Discuss next steps",
        rescue_mode=False,
        voice_required=False,
        benchmark_required=False,
        status="active",
        summary_json={},
    )
    return usecase, identity_repo, learning_repo, group.id, engine


def test_dialogue_guardian_prompt_rendering_replaces_vars() -> None:
    usecase = DailySessionUseCase(
        identity_repo=object(),  # type: ignore[arg-type]
        learning_repo=object(),  # type: ignore[arg-type]
        prompts=PromptsSettings(),
    )
    prompt = usecase._render_story_opener_prompt(  # noqa: SLF001
        lesson_title="Release Handoff",
        lesson_scene="daily standup",
        required_chunks=["follow up", "on track"],
        time_window="09:00-21:00",
    )
    assert "{lesson_title}" not in prompt
    assert "Release Handoff" in prompt
    assert "daily standup" in prompt
    assert "follow up, on track" in prompt
    assert "09:00-21:00" in prompt


@pytest.mark.asyncio
async def test_dialogue_guardian_sends_story_once_and_persists_state(tmp_path: Path) -> None:
    usecase, _, learning_repo, group_id, engine = await _build_daily_session_context(
        tmp_path,
        llm_responses=[
            (
                "The team is preparing a quick client handoff before noon. "
                "One teammate gives a short status update and asks for support. "
                "Another teammate checks deadlines and suggests next actions.\n\n"
                "How would you follow up with the client in this situation?"
            )
        ],
    )

    first = await usecase.build_conversation_guardian_envelope(
        chat_id="oc_test_dialogue_guardian",
        now=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
    )
    second = await usecase.build_conversation_guardian_envelope(
        chat_id="oc_test_dialogue_guardian",
        now=datetime(2026, 4, 20, 10, 10, tzinfo=UTC),
    )

    assert first is not None
    assert "\n\n" in first.plain_text
    assert first.plain_text.strip().endswith("?")
    assert second is None

    session = await learning_repo.get_daily_session(group_id=group_id, biz_date=date(2026, 4, 20))
    assert session is not None
    guardian_state = (session.summary_json or {}).get("conversation_guardian", {})
    assert guardian_state.get("opener_sent_for_date") == "2026-04-20"

    await engine.dispose()


@pytest.mark.asyncio
async def test_dialogue_guardian_skips_story_when_english_message_exists(tmp_path: Path) -> None:
    usecase, _, learning_repo, group_id, engine = await _build_daily_session_context(
        tmp_path,
        llm_responses=["should-not-be-used"],
    )
    user = await usecase._identity_repo.get_user_by_open_id("u-dialogue-user")  # noqa: SLF001
    assert user is not None
    await learning_repo.create_message_event(
        raw_event_id="evt-english-1",
        group_id=group_id,
        session_id=None,
        user_id=user.id,
        message_text="I will follow up after the standup.",
        event_type="group_message",
        source_type="passive_group_message",
        is_to_bot=False,
        is_command=False,
        language_guess="english",
        analysis_status="tagged",
        biz_date_local=date(2026, 4, 20),
        created_at=datetime(2026, 4, 20, 9, 20, tzinfo=UTC),
    )

    envelope = await usecase.build_conversation_guardian_envelope(
        chat_id="oc_test_dialogue_guardian",
        now=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
    )

    assert envelope is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_dialogue_guardian_idle_followup_once_per_latest_event(tmp_path: Path) -> None:
    usecase, _, learning_repo, group_id, engine = await _build_daily_session_context(
        tmp_path,
        llm_responses=[
            "What would be your next follow up in this handoff?",
            "Could you add one clear next step to keep this moving?",
        ],
    )
    user = await usecase._identity_repo.get_user_by_open_id("u-dialogue-user")  # noqa: SLF001
    assert user is not None
    session = await learning_repo.get_daily_session(group_id=group_id, biz_date=date(2026, 4, 20))
    assert session is not None
    await learning_repo.update_daily_session(
        session_id=session.id,
        summary_json={"conversation_guardian": {"opener_sent_for_date": "2026-04-20"}},
    )

    first_event = await learning_repo.create_message_event(
        raw_event_id="evt-any-1",
        group_id=group_id,
        session_id=None,
        user_id=user.id,
        message_text="今天先这样吧，稍后再看。",
        event_type="group_message",
        source_type="passive_group_message",
        is_to_bot=False,
        is_command=False,
        language_guess="chinese",
        analysis_status="tagged",
        biz_date_local=date(2026, 4, 20),
        created_at=datetime(2026, 4, 20, 9, 10, tzinfo=UTC),
    )
    first = await usecase.build_conversation_guardian_envelope(
        chat_id="oc_test_dialogue_guardian",
        now=datetime(2026, 4, 20, 10, 20, tzinfo=UTC),
    )
    second = await usecase.build_conversation_guardian_envelope(
        chat_id="oc_test_dialogue_guardian",
        now=datetime(2026, 4, 20, 10, 30, tzinfo=UTC),
    )

    assert first is not None
    assert first.plain_text.strip().endswith("?")
    assert second is None

    await learning_repo.create_message_event(
        raw_event_id="evt-any-2",
        group_id=group_id,
        session_id=None,
        user_id=user.id,
        message_text="我补一句更新。",
        event_type="group_message",
        source_type="passive_group_message",
        is_to_bot=False,
        is_command=False,
        language_guess="chinese",
        analysis_status="tagged",
        biz_date_local=date(2026, 4, 20),
        created_at=datetime(2026, 4, 20, 10, 35, tzinfo=UTC),
    )
    third = await usecase.build_conversation_guardian_envelope(
        chat_id="oc_test_dialogue_guardian",
        now=datetime(2026, 4, 20, 11, 40, tzinfo=UTC),
    )
    assert third is not None
    assert third.plain_text.strip().endswith("?")
    assert first_event.id != 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_dialogue_guardian_falls_back_to_english_when_llm_output_invalid(tmp_path: Path) -> None:
    usecase, _, learning_repo, group_id, engine = await _build_daily_session_context(
        tmp_path,
        llm_responses=[
            "你好，大家早上好。\n\n你们今天打算怎么练习",
            "我们先暂停一下，晚点再说。",
        ],
    )
    story_envelope = await usecase.build_conversation_guardian_envelope(
        chat_id="oc_test_dialogue_guardian",
        now=datetime(2026, 4, 20, 10, 0, tzinfo=UTC),
    )
    assert story_envelope is not None
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in story_envelope.plain_text)
    assert story_envelope.plain_text.strip().endswith("?")

    user = await usecase._identity_repo.get_user_by_open_id("u-dialogue-user")  # noqa: SLF001
    assert user is not None
    session = await learning_repo.get_daily_session(group_id=group_id, biz_date=date(2026, 4, 20))
    assert session is not None
    await learning_repo.create_message_event(
        raw_event_id="evt-any-3",
        group_id=group_id,
        session_id=None,
        user_id=user.id,
        message_text="晚点继续。",
        event_type="group_message",
        source_type="passive_group_message",
        is_to_bot=False,
        is_command=False,
        language_guess="chinese",
        analysis_status="tagged",
        biz_date_local=date(2026, 4, 20),
        created_at=datetime(2026, 4, 20, 10, 5, tzinfo=UTC),
    )
    followup = await usecase.build_conversation_guardian_envelope(
        chat_id="oc_test_dialogue_guardian",
        now=datetime(2026, 4, 20, 11, 20, tzinfo=UTC),
    )
    assert followup is not None
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in followup.plain_text)
    assert followup.plain_text.strip().endswith("?")
    await engine.dispose()
