from __future__ import annotations

import asyncio
import json
import re

from tenacity import retry, stop_after_attempt, wait_fixed

from src.domain.value_objects.learning import LanguageType, TranslationResult


class TencentTranslateProvider:
    def __init__(
        self,
        *,
        secret_id: str,
        secret_key: str,
        region: str,
        endpoint: str,
        timeout: float = 12.0,
    ) -> None:
        self._secret_id = secret_id
        self._secret_key = secret_key
        self._region = region
        self._endpoint = endpoint
        self._timeout = timeout

    async def detect_language(self, text: str) -> LanguageType:
        return self._heuristic_detect(text)

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(3), reraise=True)
    async def translate(
        self,
        text: str,
        *,
        source_lang: LanguageType | None,
        target_lang: LanguageType,
    ) -> TranslationResult:
        detected = source_lang if source_lang and source_lang is not LanguageType.UNKNOWN else self._heuristic_detect(text)
        if not self._secret_id or not self._secret_key:
            translated = f"[mock:{target_lang.value}] {text}"
            return TranslationResult(
                source_text=text,
                translated_text=translated,
                source_language=detected,
                target_language=target_lang,
                provider="tencent-mock",
            )

        translated_text = await asyncio.to_thread(
            self._translate_sync,
            text,
            self._normalize_language(detected),
            self._normalize_language(target_lang),
        )
        return TranslationResult(
            source_text=text,
            translated_text=translated_text,
            source_language=detected,
            target_language=target_lang,
            provider="tencent",
        )

    def _translate_sync(self, text: str, source: str, target: str) -> str:
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.tmt.v20180321 import models, tmt_client

        cred = credential.Credential(self._secret_id, self._secret_key)
        http_profile = HttpProfile()
        http_profile.endpoint = self._endpoint
        http_profile.reqTimeout = int(self._timeout)
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile

        client = tmt_client.TmtClient(cred, self._region, client_profile)
        client._sdkVersion += "_english_learning_bot"

        request = models.TextTranslateRequest()
        request.from_json_string(
            json.dumps(
                {
                    "SourceText": text,
                    "Source": source,
                    "Target": target,
                    "ProjectId": 0,
                }
            )
        )
        response = client.TextTranslate(request)
        return response.TargetText

    def _normalize_language(self, language: LanguageType) -> str:
        if language == LanguageType.CHINESE:
            return "zh"
        if language == LanguageType.ENGLISH:
            return "en"
        return "auto"

    def _heuristic_detect(self, text: str) -> LanguageType:
        if re.search(r"[\u4e00-\u9fff]", text):
            return LanguageType.CHINESE
        if re.search(r"[A-Za-z]", text):
            return LanguageType.ENGLISH
        return LanguageType.UNKNOWN
