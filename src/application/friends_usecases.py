from __future__ import annotations

import logging
from datetime import date

from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
from src.infrastructure.providers.friends_transcript import FriendsTranscriptProvider
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider
from src.infrastructure.providers.translate_tencent import TencentTranslateProvider

logger = logging.getLogger(__name__)


class FriendsUseCase:
    """构建每日 Friends 对话推送消息。"""

    def __init__(
        self,
        *,
        friends_provider: FriendsTranscriptProvider,
        llm_provider: OpenAICompatibleProvider,
        translate_provider: TencentTranslateProvider,
    ) -> None:
        self._provider = friends_provider
        self._llm = llm_provider
        self._translate = translate_provider

    async def build_daily_friends_envelope(self, *, biz_date: date, start_date: date) -> MessageEnvelope:
        segment = self._provider.get_segment(biz_date, start_date)

        dialogue_lines = [f"{line.speaker}: {line.text}" for line in segment.lines]
        dialogue_text = "\n".join(dialogue_lines)

        analysis = await self._analyze_dialogue(dialogue_text)

        sections: list[CardSection] = []

        sections.append(CardSection(title="Dialogue", lines=dialogue_lines))

        if analysis.get("translation"):
            sections.append(CardSection(
                title="中文翻译",
                lines=analysis["translation"].split("\n"),
            ))

        if analysis.get("vocabulary"):
            sections.append(CardSection(
                title="重点词汇",
                lines=analysis["vocabulary"],
            ))

        if analysis.get("grammar"):
            sections.append(CardSection(
                title="语法解析",
                lines=analysis["grammar"],
            ))

        if analysis.get("culture"):
            sections.append(CardSection(
                title="文化背景",
                lines=analysis["culture"],
            ))

        card_title = f"Friends S{segment.season:02d}E{segment.episode:02d} - {segment.title}"
        card_doc = CardDocument(title=card_title, sections=sections)

        plain_lines = [card_title, ""]
        for section in sections:
            if section.title:
                plain_lines.append(f"--- {section.title} ---")
            plain_lines.extend(section.lines)
            plain_lines.append("")

        return MessageEnvelope(
            plain_text="\n".join(plain_lines),
            card_document=card_doc,
            card_type="friends_dialogue",
        )

    @property
    def provider(self) -> FriendsTranscriptProvider:
        return self._provider

    async def _analyze_dialogue(self, dialogue_text: str) -> dict:
        if not self._llm._api_key or not self._llm._base_url or not self._llm._model:
            return {}

        system_prompt = (
            "你是英语学习助教，擅长分析美剧对话。请严格返回 JSON，结构如下：\n"
            "{\n"
            '  "translation": "对话的中文翻译，每行一句，用换行符分隔",\n'
            '  "vocabulary": ["词汇/短语 (音标) — 释义: 例句", ...],\n'
            '  "grammar": ["语法点1: 解析", "语法点2: 解析"],\n'
            '  "culture": ["文化背景说明"]\n'
            "}\n\n"
            "要求：\n"
            "1. translation: 逐句翻译，保留说话人前缀，如 'Monica: 莫妮卡说的中文翻译'\n"
            "2. vocabulary: 挑选 3-5 个重点词汇/短语，包含音标和例句\n"
            "3. grammar: 1-2 个语法点，用简单中文解析\n"
            "4. culture: 如有文化背景需要说明则给出，没有则返回空数组 []\n"
            "5. 只返回 JSON，不要有其他文字"
        )

        try:
            data = await self._llm._chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": dialogue_text},
                ],
                temperature=0.3,
                max_tokens=1500,
                timeout=60.0,
            )
            return {
                "translation": data.get("translation", ""),
                "vocabulary": data.get("vocabulary", []),
                "grammar": data.get("grammar", []),
                "culture": data.get("culture", []),
            }
        except Exception:
            logger.exception("friends dialogue analysis failed")
            return {}
