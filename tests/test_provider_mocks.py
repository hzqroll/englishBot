from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.domain.value_objects.learning import CorrectionResult
from src.infrastructure.providers.curriculum_static import StaticCurriculumProvider
from src.infrastructure.providers.english_language_tool import LanguageToolEnglishProvider
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider


@pytest.mark.asyncio
async def test_openai_compatible_provider_returns_mock_without_configuration():
    provider = OpenAICompatibleProvider(api_key="", base_url="", model="")

    result = await provider.correct_english("I very like English.")
    feedback = await provider.generate_feedback("给一条鼓励反馈")
    analysis = await provider.analyze_dialogue("Alice：你好", source_kind="explicit_text")
    non_stream_translation = await provider.translate("你好世界")
    translation = await provider.translate_stream("你好世界")

    assert result.provider == "openai-compatible-mock"
    assert "mock" in result.explanation
    assert feedback
    assert "[mock-en]" in analysis.translated_dialogue
    assert "[mock-en]" in non_stream_translation
    assert "[mock-en]" in translation


class _FallbackLLMProvider:
    def __init__(self) -> None:
        self.correct_calls: list[dict] = []
        self.chat_calls = 0

    async def correct_english(
        self,
        text: str,
        context: str | None = None,
        *,
        include_translation: bool = True,
    ) -> CorrectionResult:
        self.correct_calls.append(
            {"text": text, "context": context, "include_translation": include_translation}
        )
        return CorrectionResult(
            original_text=text,
            corrected_text="fallback corrected",
            zh_translation="fallback zh" if include_translation else "",
            natural_expression="fallback corrected",
            explanation="fallback explanation",
            provider="fallback-provider",
            error_points=[],
        )

    async def _chat_text(self, *, messages, temperature, max_tokens, timeout=None) -> str:
        self.chat_calls += 1
        return "fallback zh translation"


class _FakeLanguageTool:
    def check(self, text: str):
        return [
            SimpleNamespace(
                offset=2,
                errorLength=4,
                replacements=["like"],
                message="Use a more natural expression.",
                ruleIssueType="style",
                ruleId="VERY_LIKE",
                category=SimpleNamespace(id="STYLE"),
            )
        ]

    def correct(self, text: str) -> str:
        return "I like English."


@pytest.mark.asyncio
async def test_language_tool_provider_falls_back_to_llm_when_tool_unavailable():
    llm_provider = _FallbackLLMProvider()
    provider = LanguageToolEnglishProvider(
        llm_provider=llm_provider,
        tool_factory=lambda: (_ for _ in ()).throw(RuntimeError("tool unavailable")),
    )

    result = await provider.correct_english("I very like English.")

    assert result.provider == "fallback-provider"


@pytest.mark.asyncio
async def test_language_tool_provider_maps_matches_into_correction_result():
    llm_provider = _FallbackLLMProvider()
    provider = LanguageToolEnglishProvider(
        llm_provider=llm_provider,
        tool_factory=lambda: _FakeLanguageTool(),
    )

    result = await provider.correct_english("I very like English.")

    assert result.provider == "language-tool+llm"
    assert result.corrected_text == "I like English."
    assert "fallback zh" in result.zh_translation
    assert result.error_points[0].error_type == "natural_expression"
    assert result.error_points[0].correct_fragment == "like"


@pytest.mark.asyncio
async def test_language_tool_provider_skips_translation_when_disabled():
    llm_provider = _FallbackLLMProvider()
    provider = LanguageToolEnglishProvider(
        llm_provider=llm_provider,
        tool_factory=lambda: _FakeLanguageTool(),
    )

    result = await provider.correct_english("I very like English.", include_translation=False)

    assert result.provider == "language-tool+llm"
    assert result.zh_translation == ""
    assert llm_provider.chat_calls == 0


@pytest.mark.asyncio
async def test_static_curriculum_provider_builds_daily_package():
    project_root = Path(__file__).resolve().parents[1]
    provider = StaticCurriculumProvider(
        lexicon_path=project_root / "resources" / "lexicon" / "bec_advanced.yaml",
        theme_path=project_root / "resources" / "themes" / "office_scenarios.yaml",
    )

    lesson = await provider.build_lesson(level="beginner", biz_date=date(2026, 4, 6))

    assert lesson.theme_key
    assert len(lesson.target_items) == 10
    assert sum(1 for item in lesson.target_items if item.target_role == "core_chunk") == 5
    assert sum(1 for item in lesson.target_items if item.target_role == "support_word") == 5
    assert len(lesson.tasks) == 3
    assert "办公室情景对话" in lesson.transcript
    assert lesson.package_snapshot["theme_key"] == lesson.theme_key
