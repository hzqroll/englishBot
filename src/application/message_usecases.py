from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from src.application.message_intents import (
    EXPLICIT_DIALOGUE_ANALYSIS_PREFIX,
    extract_explicit_dialogue_analysis_text,
    is_recent_chat_analysis_request,
)
from src.domain.services.error_points import ErrorAggregator
from src.domain.services.error_taxonomy import categorize_error_type, label_error_type
from src.domain.services.review import ReviewScheduler
from src.domain.value_objects.conversation import DialogueAnalysisResult, SpeakerFeedback
from src.domain.value_objects.learning import CorrectionResult, ErrorPointPayload, LanguageType
from src.infrastructure.cache.context_store import ContextStore
from src.infrastructure.cache.group_dialogue_store import GroupDialogueSnapshot, GroupDialogueStore
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.providers.english_correction import EnglishCorrectionProvider
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider


@dataclass(slots=True)
class MessageCommandContext:
    raw_event_id: str
    group_id: str
    group_name: str
    user_id: str
    nickname: str
    message_text: str


class MessageUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        english_correction_provider: EnglishCorrectionProvider,
        llm_provider: OpenAICompatibleProvider,
        context_store: ContextStore,
        group_dialogue_store: GroupDialogueStore,
        error_aggregator: ErrorAggregator,
        review_scheduler: ReviewScheduler,
        daily_session_usecase=None,
        recent_chat_min_sentences: int = 10,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._english_correction_provider = english_correction_provider
        self._llm_provider = llm_provider
        self._context_store = context_store
        self._group_dialogue_store = group_dialogue_store
        self._error_aggregator = error_aggregator
        self._review_scheduler = review_scheduler
        self._daily_session_usecase = daily_session_usecase
        self._recent_chat_min_sentences = recent_chat_min_sentences

    @staticmethod
    def _detect_language(text: str) -> LanguageType:
        if re.search(r"[\u4e00-\u9fff]", text):
            return LanguageType.CHINESE
        if re.search(r"[A-Za-z]", text):
            return LanguageType.ENGLISH
        return LanguageType.UNKNOWN

    async def handle_at_message(
        self,
        ctx: MessageCommandContext,
        *,
        stream_callback: Callable[[str], None] | None = None,
    ) -> str:
        cleaned = ctx.message_text.strip()
        explicit_dialogue = extract_explicit_dialogue_analysis_text(cleaned)
        is_recent_dialogue_request = is_recent_chat_analysis_request(cleaned)
        dialogue_snapshot = (
            self._group_dialogue_store.get_group_dialogue(ctx.group_id)
            if is_recent_dialogue_request
            else GroupDialogueSnapshot()
        )
        language_sample = explicit_dialogue or dialogue_snapshot.rendered_text or cleaned

        group = await self._identity_repo.ensure_group(ctx.group_id, ctx.group_name)
        user = await self._identity_repo.ensure_user(ctx.user_id, ctx.nickname)
        detected = self._detect_language(language_sample)
        active_session = await self._learning_repo.get_active_daily_session(
            group_id=group.id,
            biz_date=date.today(),
        )
        event = await self._learning_repo.create_message_event(
            raw_event_id=ctx.raw_event_id,
            group_id=group.id,
            session_id=active_session.id if active_session is not None else None,
            user_id=user.id,
            message_text=cleaned,
            event_type="at_message",
            source_type="at_message",
            is_to_bot=True,
            is_command=False,
            language_guess=detected.value,
            analysis_status="summarized",
            biz_date_local=date.today(),
        )
        context = self._context_store.get(ctx.group_id, ctx.user_id)
        success = True

        if explicit_dialogue is not None:
            if stream_callback is not None:
                analysis = await self._llm_provider.analyze_dialogue_stream(
                    explicit_dialogue, source_kind="explicit_text", on_chunk=stream_callback,
                )
            else:
                analysis = await self._llm_provider.analyze_dialogue(explicit_dialogue, source_kind="explicit_text")
            reply = self._render_dialogue_analysis_reply(analysis)
            action_type = "dialogue_analysis_explicit"
            provider = "openai_compatible"
        elif cleaned.startswith(EXPLICIT_DIALOGUE_ANALYSIS_PREFIX):
            reply = f"请在“{EXPLICIT_DIALOGUE_ANALYSIS_PREFIX}：”后粘贴需要分析的对话内容。"
            action_type = "dialogue_analysis_usage"
            provider = "message-intent"
            success = False
        elif is_recent_dialogue_request:
            if dialogue_snapshot.sentence_count < self._recent_chat_min_sentences or not dialogue_snapshot.rendered_text:
                reply = f"最近聊天内容不足 {self._recent_chat_min_sentences} 句，暂时无法整体分析。"
                action_type = "dialogue_analysis_group_cache"
                provider = "group-dialogue-cache"
                success = False
            else:
                if stream_callback is not None:
                    analysis = await self._llm_provider.analyze_dialogue_stream(
                        dialogue_snapshot.rendered_text,
                        source_kind="group_cache",
                        on_chunk=stream_callback,
                    )
                else:
                    analysis = await self._llm_provider.analyze_dialogue(
                        dialogue_snapshot.rendered_text,
                        source_kind="group_cache",
                    )
                reply = self._render_dialogue_analysis_reply(analysis)
                action_type = "dialogue_analysis_group_cache"
                provider = "openai_compatible"
        elif detected == LanguageType.ENGLISH:
            if stream_callback is not None:
                correction = await self._llm_provider.correct_english_stream(
                    cleaned, context=context, on_chunk=stream_callback,
                )
            else:
                correction = await self._english_correction_provider.correct_english(cleaned, context=context)
            await self._persist_error_points(event.id, user.id, group.id, correction.error_points)
            reply = self._render_english_reply(correction)
            action_type = "english_correction"
            provider = correction.provider
        else:
            if stream_callback is not None:
                translated_text = await self._llm_provider.translate_stream(
                    cleaned, on_chunk=stream_callback,
                )
            else:
                translated_text = await self._llm_provider.translate_stream(cleaned)
            reply = self._render_chinese_reply(translated_text=translated_text)
            action_type = "chinese_translation"
            provider = "openai_compatible"

        await self._learning_repo.create_interaction_result(
            event_id=event.id,
            action_type=action_type,
            provider=provider,
            reply_text=reply,
            success=success,
        )
        if self._daily_session_usecase is not None and action_type in {"english_correction", "dialogue_analysis_explicit"}:
            await self._daily_session_usecase.record_message_event(
                group_id=group.id,
                user_id=user.id,
                message_event_id=event.id,
                message_text=cleaned,
                message_type="text",
                evidence_types={"english_attempt", "at_message"},
                biz_date=date.today(),
            )
        self._context_store.put(
            ctx.group_id,
            ctx.user_id,
            summary=f"最近一句：{cleaned}\n最近回复：{reply[:120]}",
        )
        return reply

    async def _persist_error_points(
        self,
        event_id: int,
        user_id: int,
        group_id: int,
        payloads: list[ErrorPointPayload],
    ) -> None:
        if not payloads:
            return
        merged = self._error_aggregator.merge(payloads)
        stored = await self._learning_repo.upsert_error_points(
            user_id=user_id,
            group_id=group_id,
            payloads=merged,
        )
        await self._learning_repo.create_error_occurrences(
            event_id=event_id,
            user_id=user_id,
            group_id=group_id,
            payloads=merged,
            error_point_ids=[item.id for item in stored],
        )
        progress = self._review_scheduler.schedule_new()
        await self._learning_repo.ensure_review_items(
            user_id=user_id,
            source_type="correction",
            source_ref_id=None,
            error_point_ids=[item.id for item in stored],
            interval_days=progress.interval_days,
            next_review_at=progress.next_review_at,
            status=progress.status,
        )

    def _render_english_reply(self, result: CorrectionResult) -> str:
        parts = [f"✏️ {result.corrected_text}"]
        if result.zh_translation:
            parts.append(f"\n📖 {result.zh_translation}")
        if result.explanation:
            parts.append(f"\n💡 {result.explanation}")
        if result.error_points:
            word_lines: list[str] = []
            grammar_lines: list[str] = []
            for item in result.error_points[:6]:
                label = label_error_type(item.error_type)
                line = f"  {label}：{item.source_fragment} → {item.correct_fragment}"
                if categorize_error_type(item.error_type) == "word":
                    word_lines.append(line)
                else:
                    grammar_lines.append(line)
            if word_lines:
                parts.append("\n📝 单词/表达纠错\n" + "\n".join(word_lines))
            if grammar_lines:
                parts.append("\n📚 语法纠错\n" + "\n".join(grammar_lines))
        return "\n".join(parts)

    def _render_chinese_reply(self, *, translated_text: str) -> str:
        return f"🌐 {translated_text}"

    def _render_dialogue_analysis_reply(self, result: DialogueAnalysisResult) -> str:
        dialogue_text = result.translated_dialogue.strip() or "未生成英文版对话。"
        parts = [f"🌐 {dialogue_text}"]
        feedback_text = self._render_speaker_feedbacks(result.speaker_feedbacks)
        if feedback_text:
            parts.append(f"\n✨ {feedback_text}")
        return "\n\n".join(parts)

    def _render_speaker_feedbacks(self, speaker_feedbacks: list[SpeakerFeedback]) -> str:
        if not speaker_feedbacks:
            return "未发现明显语言问题。"

        blocks: list[str] = []
        for feedback in speaker_feedbacks:
            blocks.append(f"{feedback.speaker}：")
            if feedback.overall_comment:
                blocks.append(f"  总评：{feedback.overall_comment}")
            for issue in feedback.issues:
                blocks.append(f"  - {issue}")
        return "\n".join(blocks)
