from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.domain.services.conversation_analysis import ConversationAnalysisService
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.cache.group_dialogue_store import GroupDialogueStore


@dataclass(slots=True)
class ConversationContext:
    raw_event_id: str
    group_id: str
    group_name: str
    user_id: str
    nickname: str
    message_text: str


class ConversationUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        analysis_service: ConversationAnalysisService,
        group_dialogue_store: GroupDialogueStore | None = None,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._analysis_service = analysis_service
        self._group_dialogue_store = group_dialogue_store or GroupDialogueStore()

    async def observe_passive_group_message(self, ctx: ConversationContext) -> None:
        cleaned = ctx.message_text.strip()
        if not cleaned:
            return

        existing = await self._learning_repo.get_message_event_by_raw_event_id(raw_event_id=ctx.raw_event_id)
        if existing is not None:
            return

        group = await self._identity_repo.ensure_group(ctx.group_id, ctx.group_name)
        user = await self._identity_repo.ensure_user(ctx.user_id, ctx.nickname)
        today = date.today()
        target_terms = await self._load_today_target_terms(group.id, today)
        observation = self._analysis_service.observe_message(text=cleaned, target_terms=target_terms)

        event = await self._learning_repo.create_message_event(
            raw_event_id=ctx.raw_event_id,
            group_id=group.id,
            user_id=user.id,
            message_text=cleaned,
            event_type="group_message",
            source_type="passive_group_message",
            is_to_bot=False,
            is_command=False,
            language_guess=observation.language_guess,
            analysis_status="tagged",
            biz_date_local=today,
        )
        await self._learning_repo.create_conversation_evidences(
            message_event_id=event.id,
            user_id=user.id,
            group_id=group.id,
            biz_date=today,
            payloads=observation.evidence_payloads,
        )
        self._group_dialogue_store.append_group_message(
            group_id=ctx.group_id,
            user_id=ctx.user_id,
            nickname=ctx.nickname,
            text=cleaned,
        )

    async def record_command_message(self, ctx: ConversationContext) -> None:
        cleaned = ctx.message_text.strip()
        if not cleaned:
            return

        existing = await self._learning_repo.get_message_event_by_raw_event_id(raw_event_id=ctx.raw_event_id)
        if existing is not None:
            return

        group = await self._identity_repo.ensure_group(ctx.group_id, ctx.group_name)
        user = await self._identity_repo.ensure_user(ctx.user_id, ctx.nickname)
        language_guess = self._analysis_service.guess_language(cleaned)
        await self._learning_repo.create_message_event(
            raw_event_id=ctx.raw_event_id,
            group_id=group.id,
            user_id=user.id,
            message_text=cleaned,
            event_type="group_message",
            source_type="learning_command",
            is_to_bot=False,
            is_command=True,
            language_guess=language_guess,
            analysis_status="pending",
            biz_date_local=date.today(),
        )

    async def _load_today_target_terms(self, group_id: int, target_date: date) -> set[str]:
        terms = await self._learning_repo.get_target_terms_for_group_date(
            group_id=group_id,
            biz_date=target_date,
        )
        if terms:
            return terms
        lesson_detail = await self._learning_repo.get_today_lesson_detail(group_id=group_id, biz_date=target_date)
        if lesson_detail is None:
            return set()
        _, content = lesson_detail
        return self._analysis_service.extract_target_terms(content.title, content.transcript)
