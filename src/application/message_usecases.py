from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.domain.services.error_points import ErrorAggregator
from src.domain.services.error_taxonomy import categorize_error_type, label_error_type
from src.domain.services.review import ReviewScheduler
from src.domain.value_objects.learning import CorrectionResult, ErrorPointPayload, LanguageType
from src.infrastructure.cache.context_store import ContextStore
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider
from src.infrastructure.providers.translate_tencent import TencentTranslateProvider


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
        translate_provider: TencentTranslateProvider,
        correction_provider: OpenAICompatibleProvider,
        context_store: ContextStore,
        error_aggregator: ErrorAggregator,
        review_scheduler: ReviewScheduler,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._translate_provider = translate_provider
        self._correction_provider = correction_provider
        self._context_store = context_store
        self._error_aggregator = error_aggregator
        self._review_scheduler = review_scheduler

    async def handle_at_message(self, ctx: MessageCommandContext) -> str:
        group = await self._identity_repo.ensure_group(ctx.group_id, ctx.group_name)
        user = await self._identity_repo.ensure_user(ctx.user_id, ctx.nickname)
        detected = await self._translate_provider.detect_language(ctx.message_text)
        event = await self._learning_repo.create_message_event(
            raw_event_id=ctx.raw_event_id,
            group_id=group.id,
            user_id=user.id,
            message_text=ctx.message_text,
            event_type="at_message",
            source_type="at_message",
            is_to_bot=True,
            is_command=False,
            language_guess=detected.value,
            analysis_status="summarized",
            biz_date_local=date.today(),
        )
        context = self._context_store.get(ctx.group_id, ctx.user_id)

        if detected == LanguageType.ENGLISH:
            correction = await self._correction_provider.correct_english(ctx.message_text, context=context)
            await self._persist_error_points(event.id, user.id, group.id, correction.error_points)
            reply = self._render_english_reply(correction)
            action_type = "english_correction"
        else:
            base_translation = await self._translate_provider.translate(
                ctx.message_text,
                source_lang=detected,
                target_lang=LanguageType.ENGLISH,
            )
            natural = await self._correction_provider.improve_translation(
                source_text=ctx.message_text,
                base_translation=base_translation.translated_text,
                context=context,
            )
            reply = self._render_chinese_reply(
                translated_text=base_translation.translated_text,
                natural_text=natural,
            )
            action_type = "chinese_translation"

        await self._learning_repo.create_interaction_result(
            event_id=event.id,
            action_type=action_type,
            provider=(
                "tencent+openai_compatible"
                if detected != LanguageType.ENGLISH
                else "openai_compatible"
            ),
            reply_text=reply,
        )
        self._context_store.put(
            ctx.group_id,
            ctx.user_id,
            summary=f"最近一句：{ctx.message_text}\n最近回复：{reply[:120]}",
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

    def _render_chinese_reply(self, *, translated_text: str, natural_text: str) -> str:
        parts = [f"🌐 {translated_text}"]
        if natural_text:
            parts.append(f"\n✨ {natural_text}")
        return "\n".join(parts)
