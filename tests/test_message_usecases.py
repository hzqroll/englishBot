from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.application.message_intents import EXPLICIT_DIALOGUE_ANALYSIS_PREFIX, RECENT_CHAT_ANALYSIS_KEYWORD
from src.application.message_usecases import MessageCommandContext, MessageUseCase
from src.domain.services.error_points import ErrorAggregator
from src.domain.services.review import ReviewScheduler
from src.domain.value_objects.conversation import DialogueAnalysisResult, SpeakerFeedback
from src.domain.value_objects.learning import CorrectionResult, LanguageType, TranslationResult
from src.infrastructure.cache.context_store import ContextStore
from src.infrastructure.cache.group_dialogue_store import GroupDialogueStore


class _IdentityRepoStub:
    async def ensure_group(self, group_id: str, group_name: str):
        return SimpleNamespace(id=101, group_id=group_id, group_name=group_name)

    async def ensure_user(self, user_id: str, nickname: str):
        return SimpleNamespace(id=202, user_id=user_id, nickname=nickname)


class _LearningRepoStub:
    def __init__(self) -> None:
        self.interaction_results: list[dict] = []

    async def create_message_event(self, **kwargs):
        self.message_event = kwargs
        return SimpleNamespace(id=303)

    async def create_interaction_result(self, **kwargs) -> None:
        self.interaction_results.append(kwargs)

    async def upsert_error_points(self, **kwargs):
        return []

    async def create_error_occurrences(self, **kwargs) -> None:
        return None

    async def ensure_review_items(self, **kwargs) -> None:
        return None


class _TranslateProviderStub:
    def __init__(self) -> None:
        self.translate_calls: list[dict] = []

    async def detect_language(self, text: str) -> LanguageType:
        if any("\u4e00" <= char <= "\u9fff" for char in text):
            return LanguageType.CHINESE
        if any(char.isalpha() for char in text):
            return LanguageType.ENGLISH
        return LanguageType.UNKNOWN

    async def translate(
        self,
        text: str,
        *,
        source_lang: LanguageType | None,
        target_lang: LanguageType,
    ) -> TranslationResult:
        self.translate_calls.append(
            {
                "text": text,
                "source_lang": source_lang,
                "target_lang": target_lang,
            }
        )
        rendered = f"EN::{text}" if target_lang == LanguageType.ENGLISH else f"ZH::{text}"
        return TranslationResult(
            source_text=text,
            translated_text=rendered,
            source_language=source_lang or LanguageType.UNKNOWN,
            target_language=target_lang,
            provider="tencent",
        )


class _EnglishCorrectionProviderStub:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def correct_english(self, text: str, context: str | None = None) -> CorrectionResult:
        self.calls.append({"text": text, "context": context})
        return CorrectionResult(
            original_text=text,
            corrected_text="I like English.",
            zh_translation="ZH::I like English.",
            natural_expression="I like English.",
            explanation="检测到 1 处可能问题：表达问题1处。",
            provider="language-tool+tencent",
            error_points=[],
        )


class _LLMProviderStub:
    def __init__(self) -> None:
        self.analyze_calls: list[dict] = []

    async def analyze_dialogue(self, text: str, *, source_kind: str) -> DialogueAnalysisResult:
        self.analyze_calls.append({"text": text, "source_kind": source_kind})
        return DialogueAnalysisResult(
            translated_dialogue="Alice: Hello.\nBob: I'm fine.",
            speaker_feedbacks=[
                SpeakerFeedback(
                    speaker="Alice",
                    overall_comment="表达基本清晰。",
                    issues=["第一句时态不够自然。"],
                )
            ],
            source_kind=source_kind,
        )


def _build_usecase(
    *,
    group_dialogue_store: GroupDialogueStore | None = None,
) -> tuple[MessageUseCase, _LearningRepoStub, _TranslateProviderStub, _EnglishCorrectionProviderStub, _LLMProviderStub]:
    learning_repo = _LearningRepoStub()
    translate_provider = _TranslateProviderStub()
    english_provider = _EnglishCorrectionProviderStub()
    llm_provider = _LLMProviderStub()
    usecase = MessageUseCase(
        identity_repo=_IdentityRepoStub(),
        learning_repo=learning_repo,
        translate_provider=translate_provider,
        english_correction_provider=english_provider,
        llm_provider=llm_provider,
        context_store=ContextStore(ttl_minutes=15),
        group_dialogue_store=group_dialogue_store or GroupDialogueStore(),
        error_aggregator=ErrorAggregator(),
        review_scheduler=ReviewScheduler(),
        recent_chat_min_sentences=10,
    )
    return usecase, learning_repo, translate_provider, english_provider, llm_provider


@pytest.mark.asyncio
async def test_plain_chinese_message_uses_tencent_translation_only() -> None:
    usecase, learning_repo, _, english_provider, llm_provider = _build_usecase()

    reply = await usecase.handle_at_message(
        MessageCommandContext(
            raw_event_id="evt-1",
            group_id="g1",
            group_name="group",
            user_id="u1",
            nickname="tester",
            message_text="你好，今天过得怎么样？",
        )
    )

    assert reply == "🌐 EN::你好，今天过得怎么样？"
    assert english_provider.calls == []
    assert llm_provider.analyze_calls == []
    assert learning_repo.interaction_results[-1]["provider"] == "tencent"


@pytest.mark.asyncio
async def test_plain_english_message_uses_language_tool_correction() -> None:
    usecase, learning_repo, _, english_provider, llm_provider = _build_usecase()

    reply = await usecase.handle_at_message(
        MessageCommandContext(
            raw_event_id="evt-2",
            group_id="g1",
            group_name="group",
            user_id="u1",
            nickname="tester",
            message_text="I very like English.",
        )
    )

    assert "✏️ I like English." in reply
    assert "📖 ZH::I like English." in reply
    assert len(english_provider.calls) == 1
    assert llm_provider.analyze_calls == []
    assert learning_repo.interaction_results[-1]["provider"] == "language-tool+tencent"


@pytest.mark.asyncio
async def test_explicit_dialogue_analysis_uses_llm() -> None:
    usecase, learning_repo, _, english_provider, llm_provider = _build_usecase()

    reply = await usecase.handle_at_message(
        MessageCommandContext(
            raw_event_id="evt-3",
            group_id="g1",
            group_name="group",
            user_id="u1",
            nickname="tester",
            message_text=f"{EXPLICIT_DIALOGUE_ANALYSIS_PREFIX}：Alice：你好\nBob：我很好",
        )
    )

    assert reply.startswith("🌐 ")
    assert "Alice: Hello." in reply
    assert "\n\n✨ Alice：" in reply
    assert english_provider.calls == []
    assert llm_provider.analyze_calls == [
        {"text": "Alice：你好\nBob：我很好", "source_kind": "explicit_text"}
    ]
    assert learning_repo.interaction_results[-1]["action_type"] == "dialogue_analysis_explicit"


@pytest.mark.asyncio
async def test_recent_chat_analysis_requires_minimum_sentences() -> None:
    group_dialogue_store = GroupDialogueStore()
    group_dialogue_store.append_group_message(
        group_id="g1",
        user_id="u2",
        nickname="Alice",
        text="今天天气不错",
    )
    usecase, learning_repo, _, _, llm_provider = _build_usecase(group_dialogue_store=group_dialogue_store)

    reply = await usecase.handle_at_message(
        MessageCommandContext(
            raw_event_id="evt-4",
            group_id="g1",
            group_name="group",
            user_id="u1",
            nickname="tester",
            message_text=RECENT_CHAT_ANALYSIS_KEYWORD,
        )
    )

    assert "最近聊天内容不足 10 句" in reply
    assert llm_provider.analyze_calls == []
    assert learning_repo.interaction_results[-1]["success"] is False


@pytest.mark.asyncio
async def test_recent_chat_analysis_uses_group_cache_when_threshold_met() -> None:
    group_dialogue_store = GroupDialogueStore()
    for idx in range(10):
        group_dialogue_store.append_group_message(
            group_id="g1",
            user_id=f"u{idx}",
            nickname=f"user{idx}",
            text=f"第 {idx + 1} 句。",
        )
    usecase, learning_repo, _, _, llm_provider = _build_usecase(group_dialogue_store=group_dialogue_store)

    reply = await usecase.handle_at_message(
        MessageCommandContext(
            raw_event_id="evt-5",
            group_id="g1",
            group_name="group",
            user_id="u1",
            nickname="tester",
            message_text=RECENT_CHAT_ANALYSIS_KEYWORD,
        )
    )

    assert reply.startswith("🌐 ")
    assert len(llm_provider.analyze_calls) == 1
    assert llm_provider.analyze_calls[0]["source_kind"] == "group_cache"
    assert "user0：第 1 句。" in llm_provider.analyze_calls[0]["text"]
    assert learning_repo.interaction_results[-1]["provider"] == "openai_compatible"
