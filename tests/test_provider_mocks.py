from __future__ import annotations

import pytest

from src.domain.value_objects.learning import LanguageType
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

    assert result.provider == "openai-compatible-mock"
    assert "mock" in result.explanation
    assert feedback
