from __future__ import annotations

import asyncio
import importlib
from collections import Counter
from collections.abc import Callable
from typing import Any

from src.domain.services.error_taxonomy import label_error_type
from src.domain.value_objects.learning import CorrectionResult, ErrorPointPayload
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider


class LanguageToolEnglishProvider:
    def __init__(
        self,
        *,
        llm_provider: OpenAICompatibleProvider,
        language: str = "en-US",
        tool_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._llm_provider = llm_provider
        self._language = language
        self._tool_factory = tool_factory or self._default_tool_factory
        self._tool: Any | None = None
        self._tool_init_error: Exception | None = None

    async def warmup(self) -> None:
        await asyncio.to_thread(self._tool_or_none)

    async def correct_english(self, text: str, context: str | None = None) -> CorrectionResult:
        del context
        tool = await asyncio.to_thread(self._tool_or_none)
        if tool is None:
            return await self._llm_provider.correct_english(text)

        matches = await asyncio.to_thread(tool.check, text)
        corrected_text = await asyncio.to_thread(tool.correct, text)
        zh_translation = await self._translate_to_chinese(corrected_text)
        error_points = self._build_error_points(text=text, matches=matches)
        explanation = self._build_summary(error_points)

        if not error_points:
            explanation = "未发现明显的语法或拼写问题。"

        return CorrectionResult(
            original_text=text,
            corrected_text=corrected_text,
            zh_translation=zh_translation,
            natural_expression=corrected_text,
            explanation=explanation,
            provider="language-tool+llm",
            error_points=error_points,
        )

    async def _translate_to_chinese(self, text: str) -> str:
        prompt = f"请将以下英文翻译为中文，只返回翻译结果：\n{text}"
        return await self._llm_provider._chat_text(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=200,
        )

    def _tool_or_none(self) -> Any | None:
        if self._tool is not None:
            return self._tool
        if self._tool_init_error is not None:
            return None
        try:
            self._tool = self._tool_factory()
            return self._tool
        except Exception as exc:  # pragma: no cover - defensive
            self._tool_init_error = exc
            return None

    def _default_tool_factory(self) -> Any:
        module = importlib.import_module("language_tool_python")
        return module.LanguageTool(self._language)

    def _build_error_points(self, *, text: str, matches: list[Any]) -> list[ErrorPointPayload]:
        payloads: list[ErrorPointPayload] = []
        for match in matches[:8]:
            source_fragment = text[match.offset : match.offset + match.errorLength].strip() or text.strip()
            replacement = ""
            if getattr(match, "replacements", None):
                replacement = str(match.replacements[0]).strip()
            payloads.append(
                ErrorPointPayload(
                    error_type=self._map_error_type(match),
                    source_fragment=source_fragment,
                    correct_fragment=replacement or source_fragment,
                    explanation=getattr(match, "message", "") or getattr(match, "ruleId", ""),
                )
            )
        return payloads

    def _build_summary(self, payloads: list[ErrorPointPayload]) -> str:
        if not payloads:
            return ""
        counts = Counter(label_error_type(item.error_type) for item in payloads)
        summary = "、".join(f"{label}{count}处" for label, count in counts.items())
        return f"检测到 {len(payloads)} 处可能问题：{summary}。"

    def _map_error_type(self, match: Any) -> str:
        issue_type = str(getattr(match, "ruleIssueType", "") or "").strip().lower()
        rule_id = str(getattr(match, "ruleId", "") or "").strip().lower()
        category = str(getattr(getattr(match, "category", None), "id", "") or "").strip().lower()

        if issue_type in {"misspelling", "typographical"} or "spell" in rule_id or "typo" in category:
            return "spelling"
        if "tense" in rule_id:
            return "tense"
        if "article" in rule_id:
            return "article"
        if "plural" in rule_id:
            return "plural"
        if "prep" in rule_id:
            return "preposition"
        if issue_type == "style":
            return "natural_expression"
        if issue_type == "grammar":
            return "grammar"
        return "expression"
