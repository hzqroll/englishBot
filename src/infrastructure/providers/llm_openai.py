from __future__ import annotations

import json
from textwrap import dedent

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

from src.domain.value_objects.conversation import DialogueAnalysisResult, SpeakerFeedback
from src.domain.value_objects.learning import CorrectionResult, ErrorPointPayload


class OpenAICompatibleProvider:
    def __init__(self, *, api_key: str, base_url: str, model: str, timeout: float = 30.0) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

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
            max_tokens=500,
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
            max_tokens=220,
        )

    async def generate_feedback(self, prompt: str) -> str:
        if not self._api_key or not self._base_url or not self._model:
            return "完成得不错，继续保持。"
        return await self._chat_text(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=180,
        )

    async def analyze_dialogue(self, text: str, *, source_kind: str) -> DialogueAnalysisResult:
        if not self._api_key or not self._base_url or not self._model:
            return DialogueAnalysisResult(
                translated_dialogue=f"[mock-en]\n{text}",
                speaker_feedbacks=[],
                source_kind=source_kind,
            )

        system_prompt = dedent(
            """
            你是英语学习助教。请严格返回 JSON，结构如下：
            {
              "translated_dialogue": "...",
              "speaker_feedbacks": [
                {
                  "speaker": "...",
                  "overall_comment": "...",
                  "issues": ["...", "..."]
                }
              ]
            }

            要求：
            1. 保留原始对话顺序和说话人标识。
            2. 如果原文已经是英文，只做轻微润色，不要改写语义。
            3. 只指出语言表达、语法、用词、自然度问题。
            4. 如果某个说话人没有明显问题，可以省略。
            """
        ).strip()
        user_prompt = dedent(
            f"""
            来源：{source_kind}
            请分析下面的对话内容：
            {text}
            """
        ).strip()
        data = await self._chat_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1200,
        )
        return DialogueAnalysisResult(
            translated_dialogue=str(data.get("translated_dialogue", "")).strip(),
            speaker_feedbacks=[
                SpeakerFeedback(
                    speaker=str(item.get("speaker", "")).strip() or "未命名说话人",
                    overall_comment=str(item.get("overall_comment", "")).strip(),
                    issues=[
                        str(issue).strip()
                        for issue in item.get("issues", [])
                        if str(issue).strip()
                    ],
                )
                for item in data.get("speaker_feedbacks", [])
                if isinstance(item, dict)
            ],
            source_kind=source_kind,
        )

    async def _chat_json(self, *, messages: list[dict], temperature: float, max_tokens: int) -> dict:
        content = await self._chat_text(messages=messages, temperature=temperature, max_tokens=max_tokens)
        return json.loads(self._extract_json(content))

    async def _chat_text(self, *, messages: list[dict], temperature: float, max_tokens: int) -> str:
        response = await self._client_or_create().post(
            self._chat_completions_url(),
            json={
                "model": self._model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    def _chat_completions_url(self) -> str:
        if self._base_url.endswith("/chat/completions"):
            return self._base_url
        return f"{self._base_url}/chat/completions"

    def _client_or_create(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def _extract_json(self, content: str) -> str:
        content = content.strip()
        if content.startswith("```"):
            lines = [line for line in content.splitlines() if not line.startswith("```")]
            content = "\n".join(lines)
        return content
