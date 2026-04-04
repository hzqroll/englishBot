from __future__ import annotations

import json
from textwrap import dedent

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

from src.domain.value_objects.learning import CorrectionResult, ErrorPointPayload


class OpenAICompatibleProvider:
    def __init__(self, *, api_key: str, base_url: str, model: str, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    @retry(wait=wait_fixed(1), stop=stop_after_attempt(2), reraise=True)
    async def correct_english(self, text: str, context: str | None = None) -> CorrectionResult:
        if not self._api_key or not self._base_url or not self._model:
            return CorrectionResult(
                original_text=text,
                corrected_text=text,
                zh_translation=f"[mock-zh] {text}",
                natural_expression=text,
                explanation="未配置 OpenAI 兼容模型接口，当前返回本地 mock 结果。",
                provider="openai-compatible-mock",
                error_points=[],
            )

        system_prompt = dedent(
            """
            你是英语学习助教。请严格返回 JSON，结构如下：
            {
              "corrected_text": "...",
              "zh_translation": "...",
              "natural_expression": "...",
              "explanation": "...",
              "error_points": [
                {
                  "error_type": "tense|article|preposition|word_choice|spelling|expression|grammar|agreement|natural_expression",
                  "source_fragment": "...",
                  "correct_fragment": "...",
                  "explanation": "..."
                }
              ]
            }
            """
        ).strip()

        user_prompt = f"上下文：{context or '无'}\n待纠错英文：{text}"
        data = await self._chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return CorrectionResult(
            original_text=text,
            corrected_text=data.get("corrected_text", text),
            zh_translation=data.get("zh_translation", ""),
            natural_expression=data.get("natural_expression", data.get("corrected_text", text)),
            explanation=data.get("explanation", ""),
            provider="openai-compatible",
            error_points=[
                ErrorPointPayload(
                    error_type=item["error_type"],
                    source_fragment=item["source_fragment"],
                    correct_fragment=item["correct_fragment"],
                    explanation=item["explanation"],
                )
                for item in data.get("error_points", [])
            ],
        )

    async def improve_translation(
        self,
        *,
        source_text: str,
        base_translation: str,
        context: str | None = None,
    ) -> str:
        if not self._api_key or not self._base_url or not self._model:
            return base_translation

        prompt = dedent(
            f"""
            请将下面中文翻译优化为更自然的英文。
            保持简洁，只返回优化后的英文。
            上下文：{context or '无'}
            中文：{source_text}
            基础翻译：{base_translation}
            """
        ).strip()
        return await self._chat_text(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )

    async def generate_feedback(self, prompt: str) -> str:
        if not self._api_key or not self._base_url or not self._model:
            return "完成得不错，继续保持。"
        return await self._chat_text(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )

    async def _chat_json(self, *, messages: list[dict], temperature: float) -> dict:
        content = await self._chat_text(messages=messages, temperature=temperature)
        return json.loads(self._extract_json(content))

    async def _chat_text(self, *, messages: list[dict], temperature: float) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._chat_completions_url(),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()

    def _chat_completions_url(self) -> str:
        if self._base_url.endswith("/chat/completions"):
            return self._base_url
        return f"{self._base_url}/chat/completions"

    def _extract_json(self, content: str) -> str:
        content = content.strip()
        if content.startswith("```"):
            lines = [line for line in content.splitlines() if not line.startswith("```")]
            content = "\n".join(lines)
        return content
