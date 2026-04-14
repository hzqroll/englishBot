from __future__ import annotations

import json
import time
from collections.abc import Callable, AsyncGenerator
from textwrap import dedent

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed

from src.domain.value_objects.conversation import DialogueAnalysisResult, SpeakerFeedback
from src.domain.value_objects.learning import CorrectionResult, ErrorPointPayload
from src.infrastructure.settings.models import PromptsSettings


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        prompts: PromptsSettings | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._prompts = prompts or PromptsSettings()
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

        system_prompt = self._prompts.correction_system

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

        prompt = self._prompts.improve_translation.format(
            context=context or "无",
            source_text=source_text,
            base_translation=base_translation,
        )
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

        system_prompt = self._prompts.dialogue_analysis_system
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

    # ---- Streaming methods ----

    async def correct_english_stream(
        self,
        text: str,
        context: str | None = None,
        *,
        on_chunk: Callable[[str], None] | None = None,
    ) -> CorrectionResult:
        """Streaming version of correct_english with optional progress callback."""
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

        system_prompt = (
            "你是英语纠错助教，严格返回JSON：\n"
            '{"corrected_text":"...","zh_translation":"...","natural_expression":"...",'
            '"explanation":"一句话总结","error_points":['
            '{"error_type":"tense|article|preposition|word_choice|spelling|expression|grammar|agreement",'
            '"source_fragment":"...","correct_fragment":"...","explanation":"简短说明"}]}\n'
            "要求：explanation和error_points[].explanation各限20字内。"
        )
        user_prompt = f"纠错：{text}"

        data = await self._chat_json_stream(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=400,
            on_chunk=on_chunk,
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

    async def analyze_dialogue_stream(
        self,
        text: str,
        *,
        source_kind: str,
        on_chunk: Callable[[str], None] | None = None,
    ) -> DialogueAnalysisResult:
        """Streaming version of analyze_dialogue with optional progress callback."""
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
        data = await self._chat_json_stream(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=1200,
            on_chunk=on_chunk,
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

    async def translate_stream(
        self,
        text: str,
        *,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str:
        """Translate Chinese text to English using LLM with optional streaming callback."""
        if not self._api_key or not self._base_url or not self._model:
            return f"[mock-en] {text}"

        prompt = (
            "请将下面中文翻译为自然地道的英文。只返回英文翻译结果，不要解释。\n\n"
            f"中文：{text}"
        )
        return await self._chat_text_stream(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=300,
            on_chunk=on_chunk,
        )

    # ---- Internal streaming helpers ----

    async def _chat_json_stream(
        self,
        *,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        on_chunk: Callable[[str], None] | None = None,
    ) -> dict:
        """Stream LLM response, call on_chunk with accumulated text, parse final JSON."""
        accumulated = await self._chat_text_stream(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            on_chunk=on_chunk,
        )
        try:
            return json.loads(self._extract_json(accumulated))
        except (json.JSONDecodeError, ValueError):
            return {}

    async def _chat_text_stream(
        self,
        *,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        on_chunk: Callable[[str], None] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Stream LLM response via SSE. Passes every chunk to on_chunk for minimal latency."""
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        accumulated = ""

        client: httpx.AsyncClient
        if timeout is not None and timeout != self._timeout:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                headers=headers,
            )
            should_close = True
        else:
            client = self._client_or_create()
            should_close = False

        async with client.stream(
            "POST", self._chat_completions_url(), json=payload, headers=headers,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue
                if content:
                    accumulated += content
                    if on_chunk:
                        on_chunk(accumulated)

        # Final callback with complete text
        if on_chunk:
            on_chunk(accumulated)
        if should_close:
            await client.aclose()
        return accumulated

    # ---- Non-streaming methods ----

    async def raw_chat(
        self,
        *,
        messages: list[dict],
        temperature: float = 0.5,
        max_tokens: int = 500,
        response_format: str = "text",
        timeout: float | None = None,
    ) -> str | dict:
        """Open-ended chat for prompt testing. Returns raw text or parsed JSON."""
        if response_format == "json":
            return await self._chat_json(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        return await self._chat_text(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    async def _chat_json(
        self,
        *,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        timeout: float | None = None,
    ) -> dict:
        content = await self._chat_text(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        return json.loads(self._extract_json(content))

    async def _chat_text(
        self,
        *,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        timeout: float | None = None,
    ) -> str:
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if timeout is None or timeout == self._timeout:
            response = await self._client_or_create().post(
                self._chat_completions_url(),
                json=payload,
            )
        else:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            ) as client:
                response = await client.post(
                    self._chat_completions_url(),
                    json=payload,
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
