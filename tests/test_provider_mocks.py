from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.domain.value_objects.learning import CorrectionResult, LanguageType
from src.infrastructure.providers.curriculum_static import StaticCurriculumProvider
from src.infrastructure.providers.english_language_tool import LanguageToolEnglishProvider
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider
from src.infrastructure.providers.translate_tencent import TencentTranslateProvider


@pytest.mark.asyncio
async def test_tencent_translate_provider_falls_back_to_mock_without_credentials():
    provider = TencentTranslateProvider(
        secret_id="",
        secret_key="",
        region="ap-beijing",
        endpoint="tmt.tencentcloudapi.com",
    )
    detected = await provider.detect_language("你好，world")
    result = await provider.translate(
        "你好",
        source_lang=LanguageType.CHINESE,
        target_lang=LanguageType.ENGLISH,
    )

    assert detected == LanguageType.CHINESE
    assert result.provider == "tencent-mock"
    assert result.translated_text.startswith("[mock:en]")


@pytest.mark.asyncio
async def test_openai_compatible_provider_returns_mock_without_configuration():
    provider = OpenAICompatibleProvider(api_key="", base_url="", model="")

    result = await provider.correct_english("I very like English.")
    feedback = await provider.generate_feedback("给一条鼓励反馈")
    analysis = await provider.analyze_dialogue("Alice：你好", source_kind="explicit_text")

    assert result.provider == "openai-compatible-mock"
    assert "mock" in result.explanation
    assert feedback
    assert "[mock-en]" in analysis.translated_dialogue


class _FallbackCorrectionProvider:
    async def correct_english(self, text: str, context: str | None = None) -> CorrectionResult:
        return CorrectionResult(
            original_text=text,
            corrected_text="fallback corrected",
            zh_translation="fallback zh",
            natural_expression="fallback corrected",
            explanation="fallback explanation",
            provider="fallback-provider",
            error_points=[],
        )


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
async def test_language_tool_provider_falls_back_when_tool_unavailable():
    translate_provider = TencentTranslateProvider(
        secret_id="",
        secret_key="",
        region="ap-beijing",
        endpoint="tmt.tencentcloudapi.com",
    )
    provider = LanguageToolEnglishProvider(
        translate_provider=translate_provider,
        fallback_provider=_FallbackCorrectionProvider(),
        tool_factory=lambda: (_ for _ in ()).throw(RuntimeError("tool unavailable")),
    )

    result = await provider.correct_english("I very like English.")

    assert result.provider == "fallback-provider"


@pytest.mark.asyncio
async def test_language_tool_provider_maps_matches_into_correction_result():
    translate_provider = TencentTranslateProvider(
        secret_id="",
        secret_key="",
        region="ap-beijing",
        endpoint="tmt.tencentcloudapi.com",
    )
    provider = LanguageToolEnglishProvider(
        translate_provider=translate_provider,
        tool_factory=lambda: _FakeLanguageTool(),
    )

    result = await provider.correct_english("I very like English.")

    assert result.provider == "language-tool+tencent"
    assert result.corrected_text == "I like English."
    assert result.zh_translation.startswith("[mock:zh]")
    assert result.error_points[0].error_type == "natural_expression"
    assert result.error_points[0].correct_fragment == "like"


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
