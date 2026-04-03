from __future__ import annotations

from collections.abc import Sequence
import re

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

from src.domain.value_objects.learning import LanguageType, TranslationResult


class GoogleTranslateProvider:
    def __init__(self, *, api_key: str, base_url: str, timeout: float = 12.0) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def detect_language(self, text: str) -> LanguageType:
        if not self._api_key:
            return self._heuristic_detect(text)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/detect",
                params={"key": self._api_key},
                data={"q": text},
            )
            response.raise_for_status()
            language = response.json()["data"]["detections"][0][0]["language"]
            if language.startswith("zh"):
                return LanguageType.CHINESE
            if language.startswith("en"):
                return LanguageType.ENGLISH
            return LanguageType.UNKNOWN

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(3), reraise=True)
    async def translate(
        self,
        text: str,
        *,
        source_lang: LanguageType | None,
        target_lang: LanguageType,
    ) -> TranslationResult:
        if not self._api_key:
            translated = f"[mock:{target_lang.value}] {text}"
            return TranslationResult(
                source_text=text,
                translated_text=translated,
                source_language=source_lang or self._heuristic_detect(text),
                target_language=target_lang,
                provider="google-mock",
            )

        payload = {
            "q": text,
            "target": target_lang.value,
            "format": "text",
        }
        if source_lang and source_lang is not LanguageType.UNKNOWN:
            payload["source"] = source_lang.value

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base_url}/translate",
                params={"key": self._api_key},
                data=payload,
            )
            response.raise_for_status()
            data = response.json()["data"]["translations"][0]
            detected = source_lang or self._heuristic_detect(text)
            return TranslationResult(
                source_text=text,
                translated_text=data["translatedText"],
                source_language=detected,
                target_language=target_lang,
                provider="google",
            )

    def _heuristic_detect(self, text: str) -> LanguageType:
        if re.search(r"[\u4e00-\u9fff]", text):
            return LanguageType.CHINESE
        if re.search(r"[A-Za-z]", text):
            return LanguageType.ENGLISH
        return LanguageType.UNKNOWN

