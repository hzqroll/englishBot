from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.services.error_taxonomy import categorize_error_type
from src.domain.value_objects.conversation import ConversationEvidencePayload
from src.domain.value_objects.learning import ErrorPointPayload, LessonBundle
from src.infrastructure.db.models import (
    ConversationEvidence,
    ContentItem,
    DailyCardSnapshot,
    DailyLesson,
    DailyLearningSnapshot,
    DailySession,
    DailyTask,
    DailyTargetItem,
    Enrollment,
    ErrorOccurrence,
    ErrorPoint,
    InteractionResult,
    JobRun,
    MessageEvent,
    MessageDeliveryLog,
    PointsLedger,
    QuizQuestion,
    QuizSession,
    QuizAnswer,
    ReviewCandidate,
    ReviewItem,
    RuntimeSetting,
    Streak,
    TaskSubmission,
    UserLevel,
    WeeklyReport,
)


class LearningRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def _local_day_bounds(self, target_date: date) -> tuple[datetime, datetime]:
        local_tz = datetime.now().astimezone().tzinfo or UTC
        start_local = datetime.combine(target_date, time.min, tzinfo=local_tz)
        end_local = start_local + timedelta(days=1)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    @staticmethod
    def _error_signature(payload: ErrorPointPayload) -> tuple[str, str, str]:
        return (
            payload.error_type.strip().lower(),
            payload.source_fragment.strip(),
            payload.correct_fragment.strip(),
        )

    async def create_message_event(
        self,
        *,
        raw_event_id: str,
        group_id: int | None,
        session_id: int | None,
        user_id: int,
        message_text: str,
        event_type: str,
        source_type: str = "unknown",
        is_to_bot: bool = False,
        is_command: bool = False,
        language_guess: str = "unknown",
        analysis_status: str = "pending",
        biz_date_local: date | None = None,
    ) -> MessageEvent:
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(MessageEvent).where(MessageEvent.raw_event_id == raw_event_id)
            )
            if existing is not None:
                return existing
            message_event = MessageEvent(
                raw_event_id=raw_event_id,
                group_id=group_id,
                session_id=session_id,
                user_id=user_id,
                message_text=message_text,
                event_type=event_type,
                source_type=source_type,
                is_to_bot=is_to_bot,
                is_command=is_command,
                language_guess=language_guess,
                analysis_status=analysis_status,
                biz_date_local=biz_date_local or datetime.now().astimezone().date(),
            )
            session.add(message_event)
            await session.commit()
            await session.refresh(message_event)
            return message_event

    async def get_daily_session(
        self,
        *,
        group_id: int,
        biz_date: date,
    ) -> DailySession | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(DailySession).where(
                    DailySession.group_id == group_id,
                    DailySession.biz_date == biz_date,
                )
            )

    async def get_active_daily_session(
        self,
        *,
        group_id: int,
        biz_date: date,
    ) -> DailySession | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(DailySession)
                .where(
                    DailySession.group_id == group_id,
                    DailySession.biz_date == biz_date,
                    DailySession.status.in_(("active", "awaiting_role_b", "rescue", "benchmark_pending")),
                )
                .order_by(DailySession.id.desc())
            )

    async def list_recent_daily_sessions(
        self,
        *,
        group_id: int,
        before_date: date,
        limit: int,
    ) -> list[DailySession]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(DailySession)
                .where(
                    DailySession.group_id == group_id,
                    DailySession.biz_date < before_date,
                )
                .order_by(DailySession.biz_date.desc(), DailySession.id.desc())
                .limit(limit)
            )
            return list(rows)

    async def upsert_daily_session(
        self,
        *,
        group_id: int,
        biz_date: date,
        lesson_id: int | None,
        title: str,
        role_a_user_id: int | None,
        role_a_label: str,
        role_a_status: str,
        role_b_user_id: int | None,
        role_b_label: str,
        role_b_status: str,
        required_chunks_json: list[str],
        capture_prompt: str,
        rescue_mode: bool,
        voice_required: bool,
        benchmark_required: bool,
        status: str,
        summary_json: dict[str, Any] | None = None,
    ) -> DailySession:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(DailySession).where(
                    DailySession.group_id == group_id,
                    DailySession.biz_date == biz_date,
                )
            )
            if row is None:
                row = DailySession(group_id=group_id, biz_date=biz_date)
                session.add(row)
            row.lesson_id = lesson_id
            row.title = title
            row.role_a_user_id = role_a_user_id
            row.role_a_label = role_a_label
            row.role_a_status = role_a_status
            row.role_b_user_id = role_b_user_id
            row.role_b_label = role_b_label
            row.role_b_status = role_b_status
            row.required_chunks_json = required_chunks_json
            row.capture_prompt = capture_prompt
            row.rescue_mode = rescue_mode
            row.voice_required = voice_required
            row.benchmark_required = benchmark_required
            row.status = status
            row.summary_json = summary_json or {}
            await session.commit()
            await session.refresh(row)
            return row

    async def update_daily_session(
        self,
        *,
        session_id: int,
        **kwargs: Any,
    ) -> DailySession | None:
        async with self._session_factory() as session:
            row = await session.get(DailySession, session_id)
            if row is None:
                return None
            for key, value in kwargs.items():
                setattr(row, key, value)
            await session.commit()
            await session.refresh(row)
            return row

    async def create_interaction_result(
        self,
        *,
        event_id: int,
        action_type: str,
        provider: str,
        reply_text: str,
        success: bool = True,
    ) -> InteractionResult:
        async with self._session_factory() as session:
            interaction = InteractionResult(
                event_id=event_id,
                action_type=action_type,
                provider=provider,
                reply_text=reply_text,
                success=success,
            )
            session.add(interaction)
            await session.commit()
            await session.refresh(interaction)
            return interaction

    async def get_message_event_by_raw_event_id(self, *, raw_event_id: str) -> MessageEvent | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(MessageEvent).where(MessageEvent.raw_event_id == raw_event_id)
            )

    async def get_user_group_debug_counts(self, *, user_id: int, group_id: int) -> dict[str, int]:
        async with self._session_factory() as session:
            message_events = await session.scalar(
                select(func.count())
                .select_from(MessageEvent)
                .where(
                    MessageEvent.user_id == user_id,
                    MessageEvent.group_id == group_id,
                )
            )
            interaction_results = await session.scalar(
                select(func.count())
                .select_from(InteractionResult)
                .join(MessageEvent, MessageEvent.id == InteractionResult.event_id)
                .where(
                    MessageEvent.user_id == user_id,
                    MessageEvent.group_id == group_id,
                )
            )
            error_points = await session.scalar(
                select(func.count())
                .select_from(ErrorPoint)
                .where(
                    ErrorPoint.user_id == user_id,
                    ErrorPoint.group_id == group_id,
                )
            )
            review_items = await session.scalar(
                select(func.count())
                .select_from(ReviewItem)
                .join(ErrorPoint, ErrorPoint.id == ReviewItem.error_point_id, isouter=True)
                .where(
                    ReviewItem.user_id == user_id,
                    (ErrorPoint.group_id == group_id) | (ReviewItem.error_point_id.is_(None)),
                )
            )
            conversation_evidences = await session.scalar(
                select(func.count())
                .select_from(ConversationEvidence)
                .where(
                    ConversationEvidence.user_id == user_id,
                    ConversationEvidence.group_id == group_id,
                )
            )
            return {
                "message_events": int(message_events or 0),
                "interaction_results": int(interaction_results or 0),
                "error_points": int(error_points or 0),
                "review_items": int(review_items or 0),
                "conversation_evidences": int(conversation_evidences or 0),
            }

    async def create_conversation_evidences(
        self,
        *,
        message_event_id: int,
        user_id: int,
        group_id: int,
        biz_date: date,
        payloads: list[ConversationEvidencePayload],
    ) -> None:
        if not payloads:
            return
        async with self._session_factory() as session:
            for payload in payloads:
                session.add(
                    ConversationEvidence(
                        message_event_id=message_event_id,
                        user_id=user_id,
                        group_id=group_id,
                        biz_date=biz_date,
                        evidence_type=payload.evidence_type,
                        evidence_score=payload.evidence_score,
                        payload_json=payload.payload_json,
                    )
                )
            await session.commit()

    async def list_conversation_evidences_for_message(self, *, message_event_id: int) -> list[ConversationEvidence]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ConversationEvidence)
                .where(ConversationEvidence.message_event_id == message_event_id)
                .order_by(ConversationEvidence.id.asc())
            )
            return list(rows)

    async def get_user_day_conversation_materials(
        self,
        *,
        user_id: int,
        group_id: int,
        target_date: date,
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(MessageEvent, ConversationEvidence)
                .join(
                    ConversationEvidence,
                    ConversationEvidence.message_event_id == MessageEvent.id,
                    isouter=True,
                )
                .where(
                    MessageEvent.user_id == user_id,
                    MessageEvent.group_id == group_id,
                    MessageEvent.biz_date_local == target_date,
                )
                .order_by(MessageEvent.created_at.asc(), ConversationEvidence.id.asc())
            )
            grouped: dict[int, dict[str, Any]] = {}
            for message_event, evidence in rows:
                item = grouped.setdefault(
                    message_event.id,
                    {
                        "event_id": message_event.id,
                        "raw_event_id": message_event.raw_event_id,
                        "message_text": message_event.message_text,
                        "source_type": message_event.source_type,
                        "event_type": message_event.event_type,
                        "language_guess": message_event.language_guess,
                        "analysis_status": message_event.analysis_status,
                        "created_at": message_event.created_at,
                        "evidences": [],
                    },
                )
                if evidence is not None:
                    item["evidences"].append(
                        {
                            "evidence_type": evidence.evidence_type,
                            "evidence_score": evidence.evidence_score,
                            "payload_json": evidence.payload_json,
                        }
                    )
            return list(grouped.values())

    async def upsert_error_points(
        self,
        *,
        user_id: int,
        group_id: int,
        payloads: list[ErrorPointPayload],
    ) -> list[ErrorPoint]:
        now = datetime.now(UTC)
        stored: list[ErrorPoint] = []
        async with self._session_factory() as session:
            for payload in payloads:
                existing = await session.scalar(
                    select(ErrorPoint).where(
                        ErrorPoint.user_id == user_id,
                        ErrorPoint.group_id == group_id,
                        ErrorPoint.error_type == payload.error_type,
                        ErrorPoint.source_fragment == payload.source_fragment,
                        ErrorPoint.correct_fragment == payload.correct_fragment,
                    )
                )
                if existing is None:
                    existing = ErrorPoint(
                        user_id=user_id,
                        group_id=group_id,
                        error_type=payload.error_type,
                        source_fragment=payload.source_fragment,
                        correct_fragment=payload.correct_fragment,
                        explanation=payload.explanation,
                        frequency=1,
                        last_seen_at=now,
                    )
                    session.add(existing)
                    await session.flush()
                else:
                    existing.frequency += 1
                    existing.last_seen_at = now
                    existing.explanation = payload.explanation
                stored.append(existing)
            await session.commit()
            for item in stored:
                await session.refresh(item)
            return stored

    async def create_error_occurrences(
        self,
        *,
        event_id: int,
        user_id: int,
        group_id: int,
        payloads: list[ErrorPointPayload],
        error_point_ids: list[int | None] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        if not payloads:
            return
        error_point_ids = error_point_ids or [None] * len(payloads)
        created_at = created_at or datetime.now(UTC)
        async with self._session_factory() as session:
            for payload, error_point_id in zip(payloads, error_point_ids, strict=False):
                existing = await session.scalar(
                    select(ErrorOccurrence).where(
                        ErrorOccurrence.event_id == event_id,
                        ErrorOccurrence.error_type == payload.error_type,
                        ErrorOccurrence.source_fragment == payload.source_fragment,
                        ErrorOccurrence.correct_fragment == payload.correct_fragment,
                    )
                )
                if existing is not None:
                    continue
                session.add(
                    ErrorOccurrence(
                        event_id=event_id,
                        user_id=user_id,
                        group_id=group_id,
                        error_point_id=error_point_id,
                        error_category=categorize_error_type(payload.error_type),
                        error_type=payload.error_type,
                        source_fragment=payload.source_fragment,
                        correct_fragment=payload.correct_fragment,
                        explanation=payload.explanation,
                        created_at=created_at,
                    )
                )
            await session.commit()

    async def ensure_review_items(
        self,
        *,
        user_id: int,
        source_type: str,
        source_ref_id: str | None,
        error_point_ids: list[int],
        interval_days: int,
        next_review_at: datetime,
        status: str,
    ) -> None:
        async with self._session_factory() as session:
            for error_point_id in error_point_ids:
                review = await session.scalar(
                    select(ReviewItem).where(
                        ReviewItem.user_id == user_id,
                        ReviewItem.error_point_id == error_point_id,
                    )
                )
                if review is None:
                    review = ReviewItem(
                        user_id=user_id,
                        source_type=source_type,
                        source_ref_id=source_ref_id,
                        error_point_id=error_point_id,
                        interval_days=interval_days,
                        next_review_at=next_review_at,
                        correct_streak=0,
                        status=status,
                    )
                    session.add(review)
                else:
                    review.interval_days = interval_days
                    review.next_review_at = next_review_at
                    review.status = status
            await session.commit()

    async def upsert_content_and_lesson(self, group_id: int, bundle: LessonBundle) -> DailyLesson:
        async with self._session_factory() as session:
            content = await session.scalar(
                select(ContentItem).where(
                    ContentItem.source_name == bundle.source_name,
                    ContentItem.external_id == bundle.external_id,
                )
            )
            if content is None:
                content = ContentItem(
                    source_name=bundle.source_name,
                    external_id=bundle.external_id,
                    title=bundle.title,
                    url=bundle.url,
                    transcript=bundle.transcript,
                    difficulty=bundle.difficulty,
                )
                session.add(content)
                await session.flush()

            lesson = await session.scalar(
                select(DailyLesson).where(
                    DailyLesson.biz_date == bundle.biz_date,
                    DailyLesson.group_id == group_id,
                )
            )
            if lesson is None:
                lesson = DailyLesson(
                    biz_date=bundle.biz_date,
                    group_id=group_id,
                    content_item_id=content.id,
                    theme_key=bundle.theme_key,
                    title=bundle.title,
                    package_snapshot_json=bundle.package_snapshot or {},
                    status="published",
                )
                session.add(lesson)
                await session.flush()
                for index, target in enumerate(bundle.target_items, start=1):
                    session.add(
                        DailyTargetItem(
                            lesson_id=lesson.id,
                            entry_key=target.entry_key,
                            entry_type=target.entry_type,
                            text=target.text,
                            phonetic=target.phonetic,
                            meaning_zh=target.meaning_zh,
                            usage_scene=target.usage_scene,
                            example=target.example,
                            target_role=target.target_role,
                            sort_order=index,
                        )
                    )
                for task in bundle.tasks:
                    session.add(
                        DailyTask(
                            lesson_id=lesson.id,
                            task_type=task.task_type,
                            prompt=task.prompt,
                            answer_key=task.answer_key,
                            score_weight=task.score_weight,
                        )
                    )
            else:
                lesson.theme_key = bundle.theme_key or lesson.theme_key
                lesson.title = bundle.title or lesson.title
                lesson.package_snapshot_json = bundle.package_snapshot or lesson.package_snapshot_json or {}
            await session.commit()
            await session.refresh(lesson)
            return lesson

    async def update_lesson_push_status(
        self,
        *,
        group_id: int,
        biz_date: date,
        channel: str,
        push_status: str,
        summary_text: str = "",
    ) -> None:
        async with self._session_factory() as session:
            lesson = await session.scalar(
                select(DailyLesson).where(
                    DailyLesson.group_id == group_id,
                    DailyLesson.biz_date == biz_date,
                )
            )
            if lesson is None:
                return
            lesson.channel = channel
            lesson.push_status = push_status
            lesson.pushed_at = datetime.now(UTC)
            lesson.summary_text = summary_text
            await session.commit()

    async def get_today_tasks(self, *, group_id: int, biz_date: date) -> list[DailyTask]:
        async with self._session_factory() as session:
            lesson = await session.scalar(
                select(DailyLesson).where(
                    DailyLesson.group_id == group_id,
                    DailyLesson.biz_date == biz_date,
                )
            )
            if lesson is None:
                return []
            tasks = await session.scalars(select(DailyTask).where(DailyTask.lesson_id == lesson.id))
            return list(tasks)

    async def get_today_lesson_detail(self, *, group_id: int, biz_date: date) -> tuple[DailyLesson, ContentItem] | None:
        async with self._session_factory() as session:
            row = await session.execute(
                select(DailyLesson, ContentItem)
                .join(ContentItem, ContentItem.id == DailyLesson.content_item_id)
                .where(
                    DailyLesson.group_id == group_id,
                    DailyLesson.biz_date == biz_date,
                )
            )
            result = row.first()
            if result is None:
                return None
            return result[0], result[1]

    async def get_lesson_detail(self, *, lesson_id: int) -> tuple[DailyLesson, ContentItem] | None:
        async with self._session_factory() as session:
            row = await session.execute(
                select(DailyLesson, ContentItem)
                .join(ContentItem, ContentItem.id == DailyLesson.content_item_id)
                .where(DailyLesson.id == lesson_id)
            )
            result = row.first()
            if result is None:
                return None
            return result[0], result[1]

    async def get_tasks_for_lesson(self, *, lesson_id: int) -> list[DailyTask]:
        async with self._session_factory() as session:
            tasks = await session.scalars(
                select(DailyTask)
                .where(DailyTask.lesson_id == lesson_id)
                .order_by(DailyTask.id.asc())
            )
            return list(tasks)

    async def get_target_items_for_lesson(self, *, lesson_id: int) -> list[DailyTargetItem]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(DailyTargetItem)
                .where(DailyTargetItem.lesson_id == lesson_id)
                .order_by(DailyTargetItem.sort_order.asc(), DailyTargetItem.id.asc())
            )
            return list(rows)

    async def get_target_terms_for_group_date(self, *, group_id: int, biz_date: date) -> set[str]:
        async with self._session_factory() as session:
            lesson = await session.scalar(
                select(DailyLesson).where(
                    DailyLesson.group_id == group_id,
                    DailyLesson.biz_date == biz_date,
                )
            )
            if lesson is None:
                return set()
            rows = await session.scalars(
                select(DailyTargetItem.text).where(DailyTargetItem.lesson_id == lesson.id)
            )
            result: set[str] = set()
            for item in rows:
                normalized = (item or "").strip().lower()
                if not normalized:
                    continue
                result.add(normalized)
                result.update(part for part in normalized.split() if len(part) >= 4)
            return result

    async def replace_review_candidates(
        self,
        *,
        user_id: int,
        group_id: int,
        biz_date: date,
        candidates: list[dict[str, Any]],
    ) -> None:
        async with self._session_factory() as session:
            await session.execute(
                ReviewCandidate.__table__.delete().where(
                    ReviewCandidate.user_id == user_id,
                    ReviewCandidate.group_id == group_id,
                    ReviewCandidate.biz_date == biz_date,
                )
            )
            for item in candidates:
                session.add(
                    ReviewCandidate(
                        biz_date=biz_date,
                        user_id=user_id,
                        group_id=group_id,
                        source_type=item["source_type"],
                        source_ref_id=item.get("source_ref_id"),
                        content_text=item["content_text"],
                        correct_text=item.get("correct_text", ""),
                        priority_score=int(item.get("priority_score", 0)),
                        selected_for_next_day=bool(item.get("selected_for_next_day", True)),
                        used_in_next_day_task=bool(item.get("used_in_next_day_task", False)),
                        recalled_successfully=item.get("recalled_successfully"),
                    )
                )
            await session.commit()

    async def list_review_candidates(
        self,
        *,
        user_id: int,
        group_id: int,
        biz_date: date,
    ) -> list[ReviewCandidate]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ReviewCandidate)
                .where(
                    ReviewCandidate.user_id == user_id,
                    ReviewCandidate.group_id == group_id,
                    ReviewCandidate.biz_date == biz_date,
                )
                .order_by(desc(ReviewCandidate.priority_score), ReviewCandidate.id.asc())
            )
            return list(rows)

    async def list_group_review_candidates(
        self,
        *,
        group_id: int,
        biz_date: date,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    ReviewCandidate.content_text,
                    ReviewCandidate.correct_text,
                    func.max(ReviewCandidate.priority_score).label("priority_score"),
                    func.count().label("hit_count"),
                )
                .where(
                    ReviewCandidate.group_id == group_id,
                    ReviewCandidate.biz_date == biz_date,
                    ReviewCandidate.selected_for_next_day.is_(True),
                )
                .group_by(ReviewCandidate.content_text, ReviewCandidate.correct_text)
                .order_by(desc("priority_score"), desc("hit_count"))
                .limit(limit)
            )
            return [
                {
                    "content_text": row[0],
                    "correct_text": row[1],
                    "priority_score": int(row[2] or 0),
                    "hit_count": int(row[3] or 0),
                }
                for row in rows.all()
            ]

    async def mark_review_candidates_used(
        self,
        *,
        group_id: int,
        biz_date: date,
        content_texts: list[str],
    ) -> None:
        if not content_texts:
            return
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ReviewCandidate).where(
                    ReviewCandidate.group_id == group_id,
                    ReviewCandidate.biz_date == biz_date,
                    ReviewCandidate.content_text.in_(content_texts),
                )
            )
            for row in rows:
                row.used_in_next_day_task = True
            await session.commit()

    async def evaluate_review_candidates_for_day(
        self,
        *,
        user_id: int,
        group_id: int,
        biz_date: date,
    ) -> list[dict[str, Any]]:
        async with self._session_factory() as session:
            candidates = await session.scalars(
                select(ReviewCandidate)
                .where(
                    ReviewCandidate.user_id == user_id,
                    ReviewCandidate.group_id == group_id,
                    ReviewCandidate.biz_date == biz_date,
                    ReviewCandidate.selected_for_next_day.is_(True),
                )
                .order_by(desc(ReviewCandidate.priority_score), ReviewCandidate.id.asc())
            )
            start, end = self._local_day_bounds(biz_date)
            texts = await session.scalars(
                select(MessageEvent.message_text)
                .where(
                    MessageEvent.user_id == user_id,
                    MessageEvent.group_id == group_id,
                    MessageEvent.created_at >= start,
                    MessageEvent.created_at < end,
                )
            )
            task_texts = await session.scalars(
                select(TaskSubmission.submission_text)
                .join(DailyTask, DailyTask.id == TaskSubmission.task_id)
                .join(DailyLesson, DailyLesson.id == DailyTask.lesson_id)
                .where(
                    TaskSubmission.user_id == user_id,
                    DailyLesson.group_id == group_id,
                    DailyLesson.biz_date == biz_date,
                )
            )
            corpus = "\n".join(list(texts) + list(task_texts)).lower()
            results: list[dict[str, Any]] = []
            for candidate in candidates:
                tokens = {
                    part.strip().lower()
                    for part in [candidate.content_text, candidate.correct_text]
                    if part and part.strip()
                }
                matched = any(token.lower() in corpus for token in tokens)
                candidate.recalled_successfully = matched
                results.append(
                    {
                        "content_text": candidate.content_text,
                        "correct_text": candidate.correct_text,
                        "priority_score": candidate.priority_score,
                        "recalled_successfully": matched,
                    }
                )
            await session.commit()
            return results

    async def get_daily_learning_snapshot(
        self,
        *,
        user_id: int,
        group_id: int,
        biz_date: date,
    ) -> DailyLearningSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(DailyLearningSnapshot).where(
                    DailyLearningSnapshot.user_id == user_id,
                    DailyLearningSnapshot.group_id == group_id,
                    DailyLearningSnapshot.biz_date == biz_date,
                )
            )

    async def upsert_daily_learning_snapshot(
        self,
        *,
        biz_date: date,
        user_id: int,
        group_id: int,
        lesson_id: int | None,
        summary_json: dict[str, Any],
        mastery_level: str,
        mastery_reason: str,
        model_summary: str,
        activity_score: int,
        evidence_score: int,
    ) -> DailyLearningSnapshot:
        async with self._session_factory() as session:
            snapshot = await session.scalar(
                select(DailyLearningSnapshot).where(
                    DailyLearningSnapshot.biz_date == biz_date,
                    DailyLearningSnapshot.user_id == user_id,
                    DailyLearningSnapshot.group_id == group_id,
                )
            )
            if snapshot is None:
                snapshot = DailyLearningSnapshot(
                    biz_date=biz_date,
                    user_id=user_id,
                    group_id=group_id,
                )
                session.add(snapshot)
            snapshot.lesson_id = lesson_id
            snapshot.summary_json = summary_json
            snapshot.mastery_level = mastery_level
            snapshot.mastery_reason = mastery_reason
            snapshot.model_summary = model_summary
            snapshot.activity_score = activity_score
            snapshot.evidence_score = evidence_score
            snapshot.generated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(snapshot)
            return snapshot

    async def get_daily_card_snapshot(
        self,
        *,
        biz_date: date,
        group_id: int,
        card_type: str,
        user_id: int | None = None,
    ) -> DailyCardSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(DailyCardSnapshot).where(
                    DailyCardSnapshot.biz_date == biz_date,
                    DailyCardSnapshot.group_id == group_id,
                    DailyCardSnapshot.card_type == card_type,
                    DailyCardSnapshot.user_id == user_id,
                )
            )

    async def upsert_daily_card_snapshot(
        self,
        *,
        biz_date: date,
        group_id: int,
        card_type: str,
        plain_text: str,
        card_document_json: dict[str, Any],
        user_id: int | None = None,
        image_paths_json: list[str] | None = None,
    ) -> DailyCardSnapshot:
        async with self._session_factory() as session:
            snapshot = await session.scalar(
                select(DailyCardSnapshot).where(
                    DailyCardSnapshot.biz_date == biz_date,
                    DailyCardSnapshot.group_id == group_id,
                    DailyCardSnapshot.card_type == card_type,
                    DailyCardSnapshot.user_id == user_id,
                )
            )
            if snapshot is None:
                snapshot = DailyCardSnapshot(
                    biz_date=biz_date,
                    group_id=group_id,
                    card_type=card_type,
                    user_id=user_id,
                )
                session.add(snapshot)
            snapshot.plain_text = plain_text
            snapshot.card_document_json = card_document_json
            snapshot.image_paths_json = image_paths_json or []
            snapshot.created_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(snapshot)
            return snapshot

    async def update_daily_card_snapshot_images(
        self,
        *,
        snapshot_id: int,
        image_paths_json: list[str],
    ) -> None:
        async with self._session_factory() as session:
            snapshot = await session.get(DailyCardSnapshot, snapshot_id)
            if snapshot is None:
                return
            snapshot.image_paths_json = image_paths_json
            await session.commit()

    async def create_message_delivery_log(
        self,
        *,
        group_id: int,
        job_name: str,
        delivery_mode: str,
        success: bool,
        user_id: int | None = None,
        card_snapshot_id: int | None = None,
        provider_response: str = "",
    ) -> MessageDeliveryLog:
        async with self._session_factory() as session:
            log = MessageDeliveryLog(
                group_id=group_id,
                user_id=user_id,
                job_name=job_name,
                card_snapshot_id=card_snapshot_id,
                delivery_mode=delivery_mode,
                success=success,
                provider_response=provider_response,
            )
            session.add(log)
            await session.commit()
            await session.refresh(log)
            return log

    async def submit_task(
        self,
        *,
        task_id: int,
        user_id: int,
        submission_text: str,
        score: int,
        feedback: str,
    ) -> TaskSubmission:
        async with self._session_factory() as session:
            submission = await session.scalar(
                select(TaskSubmission).where(
                    TaskSubmission.task_id == task_id,
                    TaskSubmission.user_id == user_id,
                )
            )
            if submission is None:
                submission = TaskSubmission(
                    task_id=task_id,
                    user_id=user_id,
                    submission_text=submission_text,
                    score=score,
                    feedback=feedback,
                    submitted_at=datetime.now(UTC),
                )
                session.add(submission)
            else:
                submission.submission_text = submission_text
                submission.score = score
                submission.feedback = feedback
                submission.submitted_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(submission)
            return submission

    async def get_task_submissions_for_user(self, *, user_id: int, task_ids: list[int]) -> dict[int, TaskSubmission]:
        if not task_ids:
            return {}
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(TaskSubmission).where(
                    TaskSubmission.user_id == user_id,
                    TaskSubmission.task_id.in_(task_ids),
                )
            )
            return {row.task_id: row for row in rows}

    async def get_due_review_items(self, *, user_id: int, limit: int) -> list[ReviewItem]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ReviewItem)
                .where(
                    ReviewItem.user_id == user_id,
                    ReviewItem.next_review_at <= datetime.now(UTC),
                )
                .order_by(desc(ReviewItem.next_review_at))
                .limit(limit)
            )
            return list(rows)

    async def update_review_item(self, review_item_id: int, **kwargs: Any) -> None:
        async with self._session_factory() as session:
            review_item = await session.get(ReviewItem, review_item_id)
            if review_item is None:
                return
            for key, value in kwargs.items():
                setattr(review_item, key, value)
            await session.commit()

    async def award_points(self, *, user_id: int, points: int, reason: str) -> None:
        async with self._session_factory() as session:
            session.add(PointsLedger(user_id=user_id, points=points, reason=reason))
            streak = await session.scalar(select(Streak).where(Streak.user_id == user_id))
            today = datetime.now(UTC).date()
            if streak is None:
                streak = Streak(user_id=user_id, current_days=1, max_days=1, last_activity_date=datetime.now(UTC))
                session.add(streak)
            else:
                last_date = streak.last_activity_date.date() if streak.last_activity_date else None
                if last_date == today:
                    pass
                elif last_date == today - timedelta(days=1):
                    streak.current_days += 1
                    streak.max_days = max(streak.max_days, streak.current_days)
                    streak.last_activity_date = datetime.now(UTC)
                else:
                    streak.current_days = 1
                    streak.max_days = max(streak.max_days, 1)
                    streak.last_activity_date = datetime.now(UTC)
            await session.commit()

    async def upsert_user_level(self, *, user_id: int, group_id: int, current_level: str, evidence_json: dict) -> None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserLevel).where(
                    UserLevel.user_id == user_id,
                    UserLevel.group_id == group_id,
                )
            )
            if row is None:
                row = UserLevel(
                    user_id=user_id,
                    group_id=group_id,
                    current_level=current_level,
                    evidence_json=evidence_json,
                )
                session.add(row)
            else:
                row.current_level = current_level
                row.evidence_json = evidence_json
                row.evaluated_at = datetime.now(UTC)
            await session.commit()

    async def get_user_level(self, *, user_id: int, group_id: int) -> str:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(UserLevel).where(
                    UserLevel.user_id == user_id,
                    UserLevel.group_id == group_id,
                )
            )
            return row.current_level if row is not None else "beginner"

    async def create_quiz_session(self, *, biz_week: str, group_id: int, user_id: int) -> QuizSession:
        async with self._session_factory() as session:
            quiz_session = await session.scalar(
                select(QuizSession).where(
                    QuizSession.biz_week == biz_week,
                    QuizSession.group_id == group_id,
                    QuizSession.user_id == user_id,
                )
            )
            if quiz_session is None:
                quiz_session = QuizSession(
                    biz_week=biz_week,
                    group_id=group_id,
                    user_id=user_id,
                    status="ready",
                )
                session.add(quiz_session)
                await session.commit()
                await session.refresh(quiz_session)
            return quiz_session

    async def add_quiz_questions(self, *, session_id: int, questions: list[dict]) -> None:
        async with self._session_factory() as session:
            existing = await session.scalars(select(QuizQuestion).where(QuizQuestion.session_id == session_id))
            if list(existing):
                return
            for question in questions:
                session.add(QuizQuestion(session_id=session_id, **question))
            await session.commit()

    async def get_quiz_questions(self, *, session_id: int) -> list[QuizQuestion]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(QuizQuestion).where(QuizQuestion.session_id == session_id).order_by(QuizQuestion.id.asc())
            )
            return list(rows)

    async def get_quiz_answers(self, *, session_id: int) -> dict[int, QuizAnswer]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(QuizAnswer).where(QuizAnswer.session_id == session_id)
            )
            return {row.question_id: row for row in rows}

    async def get_quiz_session(self, *, session_id: int) -> QuizSession | None:
        async with self._session_factory() as session:
            return await session.get(QuizSession, session_id)

    async def get_recent_tasks_for_quiz(
        self,
        *,
        group_id: int,
        days: int = 7,
        limit: int = 10,
    ) -> list[DailyTask]:
        async with self._session_factory() as session:
            start_date = (datetime.now(UTC) - timedelta(days=days)).date()
            rows = await session.scalars(
                select(DailyTask)
                .join(DailyLesson, DailyLesson.id == DailyTask.lesson_id)
                .where(
                    DailyLesson.group_id == group_id,
                    DailyLesson.biz_date >= start_date,
                )
                .order_by(desc(DailyLesson.biz_date), DailyTask.id.asc())
                .limit(limit)
            )
            return list(rows)

    async def save_quiz_answers(
        self,
        *,
        session_id: int,
        answers: list[dict],
        total_score: int,
    ) -> None:
        async with self._session_factory() as session:
            for item in answers:
                row = await session.scalar(
                    select(QuizAnswer).where(
                        QuizAnswer.session_id == session_id,
                        QuizAnswer.question_id == item["question_id"],
                    )
                )
                if row is None:
                    row = QuizAnswer(
                        session_id=session_id,
                        question_id=item["question_id"],
                        user_answer=item["user_answer"],
                        is_correct=item["is_correct"],
                        score=item["score"],
                    )
                    session.add(row)
                else:
                    row.user_answer = item["user_answer"]
                    row.is_correct = item["is_correct"]
                    row.score = item["score"]

            quiz_session = await session.get(QuizSession, session_id)
            if quiz_session is not None:
                quiz_session.total_score = total_score
                quiz_session.status = "submitted"
            await session.commit()

    async def save_weekly_report(self, *, biz_week: str, user_id: int, report_json: dict, summary_text: str) -> None:
        async with self._session_factory() as session:
            report = await session.scalar(
                select(WeeklyReport).where(
                    WeeklyReport.biz_week == biz_week,
                    WeeklyReport.user_id == user_id,
                )
            )
            if report is None:
                session.add(
                    WeeklyReport(
                        biz_week=biz_week,
                        user_id=user_id,
                        report_json=report_json,
                        summary_text=summary_text,
                    )
                )
            else:
                report.report_json = report_json
                report.summary_text = summary_text
            await session.commit()

    async def get_weekly_report(self, *, biz_week: str, user_id: int) -> WeeklyReport | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(WeeklyReport).where(
                    WeeklyReport.biz_week == biz_week,
                    WeeklyReport.user_id == user_id,
                )
            )

    async def acquire_job_lock(self, *, job_name: str, biz_key: str, force: bool = False) -> bool:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(JobRun).where(JobRun.job_name == job_name, JobRun.biz_key == biz_key)
            )
            if row is not None and row.status in {"running", "success"} and not force:
                return False
            if row is None:
                row = JobRun(job_name=job_name, biz_key=biz_key, status="running")
                session.add(row)
            else:
                row.status = "running"
                row.started_at = datetime.now(UTC)
                row.finished_at = None
            await session.commit()
            return True

    async def finish_job_lock(self, *, job_name: str, biz_key: str, status: str) -> None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(JobRun).where(JobRun.job_name == job_name, JobRun.biz_key == biz_key)
            )
            if row is None:
                return
            row.status = status
            row.finished_at = datetime.now(UTC)
            await session.commit()

    async def get_dashboard_metrics(self) -> dict[str, int]:
        async with self._session_factory() as session:
            total_messages = await session.scalar(select(func.count()).select_from(MessageEvent))
            total_errors = await session.scalar(select(func.count()).select_from(ErrorPoint))
            total_reviews = await session.scalar(select(func.count()).select_from(ReviewItem))
            total_jobs = await session.scalar(select(func.count()).select_from(JobRun))
            total_enrollments = await session.scalar(select(func.count()).select_from(Enrollment))
            active_users = await session.scalar(
                select(func.count(func.distinct(MessageEvent.user_id))).select_from(MessageEvent)
            )
            total_submissions = await session.scalar(select(func.count()).select_from(TaskSubmission))
            total_quiz_sessions = await session.scalar(select(func.count()).select_from(QuizSession))
            return {
                "message_events": int(total_messages or 0),
                "active_users": int(active_users or 0),
                "enrolled_profiles": int(total_enrollments or 0),
                "error_points": int(total_errors or 0),
                "review_items": int(total_reviews or 0),
                "task_submissions": int(total_submissions or 0),
                "quiz_sessions": int(total_quiz_sessions or 0),
                "job_runs": int(total_jobs or 0),
            }

    async def list_runtime_settings(self) -> list[RuntimeSetting]:
        async with self._session_factory() as session:
            rows = await session.scalars(select(RuntimeSetting).order_by(RuntimeSetting.key))
            return list(rows)

    async def upsert_runtime_setting(self, *, key: str, value: str) -> None:
        async with self._session_factory() as session:
            row = await session.scalar(select(RuntimeSetting).where(RuntimeSetting.key == key))
            if row is None:
                row = RuntimeSetting(key=key, value=value, updated_at=datetime.now(UTC))
                session.add(row)
            else:
                row.value = value
                row.updated_at = datetime.now(UTC)
            await session.commit()

    async def get_learning_evidence(
        self,
        *,
        user_id: int,
        group_id: int,
        days: int = 7,
        end_date: date | None = None,
    ) -> dict:
        async with self._session_factory() as session:
            reference_date = end_date or datetime.now().astimezone().date()
            start_date = reference_date - timedelta(days=max(days - 1, 0))
            start, _ = self._local_day_bounds(start_date)
            _, end = self._local_day_bounds(reference_date)

            translation_count = await session.scalar(
                select(func.count())
                .select_from(InteractionResult)
                .join(MessageEvent, MessageEvent.id == InteractionResult.event_id)
                .where(
                    MessageEvent.user_id == user_id,
                    MessageEvent.group_id == group_id,
                    InteractionResult.action_type == "chinese_translation",
                    InteractionResult.created_at >= start,
                    InteractionResult.created_at < end,
                )
            )
            correction_count = await session.scalar(
                select(func.count())
                .select_from(InteractionResult)
                .join(MessageEvent, MessageEvent.id == InteractionResult.event_id)
                .where(
                    MessageEvent.user_id == user_id,
                    MessageEvent.group_id == group_id,
                    InteractionResult.action_type == "english_correction",
                    InteractionResult.created_at >= start,
                    InteractionResult.created_at < end,
                )
            )
            task_completion_count = await session.scalar(
                select(func.count())
                .select_from(TaskSubmission)
                .join(DailyTask, DailyTask.id == TaskSubmission.task_id)
                .join(DailyLesson, DailyLesson.id == DailyTask.lesson_id)
                .where(
                    TaskSubmission.user_id == user_id,
                    DailyLesson.group_id == group_id,
                    TaskSubmission.submitted_at >= start,
                    TaskSubmission.submitted_at < end,
                )
            )
            quiz_average_score = await session.scalar(
                select(func.avg(QuizSession.total_score)).where(
                    QuizSession.user_id == user_id,
                    QuizSession.group_id == group_id,
                    QuizSession.status == "submitted",
                    QuizSession.updated_at >= start,
                    QuizSession.updated_at < end,
                )
            )
            return {
                "translation_count": int(translation_count or 0),
                "correction_count": int(correction_count or 0),
                "task_completion_count": int(task_completion_count or 0),
                "quiz_average_score": float(quiz_average_score or 0.0),
            }

    async def get_weekly_report_stats(
        self,
        *,
        user_id: int,
        group_id: int,
        days: int = 7,
        end_date: date | None = None,
    ) -> dict:
        async with self._session_factory() as session:
            reference_date = end_date or datetime.now().astimezone().date()
            start_date = reference_date - timedelta(days=max(days - 1, 0))
            start, _ = self._local_day_bounds(start_date)
            _, end = self._local_day_bounds(reference_date)
            snapshot_rows = list(
                (
                    await session.scalars(
                        select(DailyLearningSnapshot)
                        .where(
                            DailyLearningSnapshot.user_id == user_id,
                            DailyLearningSnapshot.group_id == group_id,
                            DailyLearningSnapshot.biz_date >= start_date,
                            DailyLearningSnapshot.biz_date <= reference_date,
                        )
                        .order_by(DailyLearningSnapshot.biz_date.asc(), DailyLearningSnapshot.generated_at.asc())
                    )
                ).all()
            )

            if snapshot_rows:
                translation_count = 0
                correction_count = 0
                task_completion_count = 0
                available_tasks = 0
                points_earned = 0
                latest_snapshot_level = None
                for snapshot in snapshot_rows:
                    summary = snapshot.summary_json or {}
                    stats = summary.get("stats", {}) or {}
                    translation_count += int(stats.get("translation_count", 0) or 0)
                    correction_count += int(stats.get("correction_count", 0) or 0)
                    task_completion_count += int(stats.get("today_task_completed", 0) or 0)
                    available_tasks += int(stats.get("today_task_total", 0) or 0)
                    points_earned += int(stats.get("points_earned", 0) or 0)
                    latest_snapshot_level = stats.get("level", latest_snapshot_level)
                evidence = {
                    "translation_count": translation_count,
                    "correction_count": correction_count,
                    "task_completion_count": task_completion_count,
                    "quiz_average_score": 0.0,
                }
                learning_days = len({snapshot.biz_date for snapshot in snapshot_rows})
                task_completion_rate = (
                    round(task_completion_count / available_tasks, 2) if available_tasks else 0.0
                )
            else:
                evidence = await self.get_learning_evidence(
                    user_id=user_id,
                    group_id=group_id,
                    days=days,
                    end_date=reference_date,
                )
                available_tasks = await session.scalar(
                    select(func.count())
                    .select_from(DailyTask)
                    .join(DailyLesson, DailyLesson.id == DailyTask.lesson_id)
                    .where(
                        DailyLesson.group_id == group_id,
                        DailyLesson.biz_date >= start_date,
                        DailyLesson.biz_date <= reference_date,
                    )
                )
                task_completion_rate = (
                    round(evidence["task_completion_count"] / available_tasks, 2) if available_tasks else 0.0
                )
                event_dates = await session.scalars(
                    select(func.date(MessageEvent.created_at))
                    .where(
                        MessageEvent.user_id == user_id,
                        MessageEvent.group_id == group_id,
                        MessageEvent.created_at >= start,
                        MessageEvent.created_at < end,
                    )
                )
                task_dates = await session.scalars(
                    select(func.date(TaskSubmission.submitted_at))
                    .select_from(TaskSubmission)
                    .join(DailyTask, DailyTask.id == TaskSubmission.task_id)
                    .join(DailyLesson, DailyLesson.id == DailyTask.lesson_id)
                    .where(
                        TaskSubmission.user_id == user_id,
                        DailyLesson.group_id == group_id,
                        TaskSubmission.submitted_at >= start,
                        TaskSubmission.submitted_at < end,
                    )
                )
                learning_days = len(set(event_dates.all()) | set(task_dates.all()))
                points_earned = None
                latest_snapshot_level = None

            weak_rows = await session.execute(
                select(ErrorPoint.error_type, func.sum(ErrorPoint.frequency).label("freq"))
                .where(
                    ErrorPoint.user_id == user_id,
                    ErrorPoint.group_id == group_id,
                    ErrorPoint.last_seen_at >= start,
                    ErrorPoint.last_seen_at < end,
                )
                .group_by(ErrorPoint.error_type)
                .order_by(desc("freq"))
                .limit(3)
            )
            weak_points = [row[0] for row in weak_rows.all()]

            if not weak_points:
                weak_rows = await session.execute(
                    select(ErrorPoint.error_type, func.sum(ErrorPoint.frequency).label("freq"))
                    .where(
                        ErrorPoint.user_id == user_id,
                        ErrorPoint.group_id == group_id,
                    )
                    .group_by(ErrorPoint.error_type)
                    .order_by(desc("freq"))
                    .limit(3)
                )
                weak_points = [row[0] for row in weak_rows.all()]

            quiz_scores = await session.scalars(
                select(QuizSession.total_score).where(
                    QuizSession.user_id == user_id,
                    QuizSession.group_id == group_id,
                    QuizSession.status == "submitted",
                    QuizSession.updated_at >= start,
                    QuizSession.updated_at < end,
                )
            )
            total_points = await session.scalar(
                select(func.sum(PointsLedger.points)).where(
                    PointsLedger.user_id == user_id,
                    PointsLedger.created_at >= start,
                    PointsLedger.created_at < end,
                )
            )
            streak = await session.scalar(select(Streak).where(Streak.user_id == user_id))
            level_row = await session.scalar(
                select(UserLevel).where(
                    UserLevel.user_id == user_id,
                    UserLevel.group_id == group_id,
                )
            )
            quiz_score_list = list(quiz_scores.all())
            latest_quiz_score = quiz_score_list[-1] if quiz_score_list else 0
            quiz_average_score = (
                round(sum(quiz_score_list) / len(quiz_score_list), 1)
                if quiz_score_list
                else float(evidence.get("quiz_average_score", 0.0) or 0.0)
            )

            return {
                "learning_days": learning_days,
                "task_completion_rate": task_completion_rate,
                "translation_count": evidence["translation_count"],
                "correction_count": evidence["correction_count"],
                "task_completion_count": evidence["task_completion_count"],
                "quiz_average_score": quiz_average_score,
                "latest_quiz_score": latest_quiz_score,
                "weak_points": weak_points,
                "points_earned": int(points_earned if points_earned is not None else (total_points or 0)),
                "current_streak": int(streak.current_days if streak else 0),
                "level": latest_snapshot_level or (level_row.current_level if level_row else "beginner"),
            }

    async def get_daily_error_digest(
        self,
        *,
        user_id: int,
        group_id: int,
        target_date: date,
        word_limit: int = 5,
        grammar_limit: int = 5,
    ) -> dict[str, Any]:
        async with self._session_factory() as session:
            start, end = self._local_day_bounds(target_date)

            word_total = await session.scalar(
                select(func.count())
                .select_from(ErrorOccurrence)
                .where(
                    ErrorOccurrence.user_id == user_id,
                    ErrorOccurrence.group_id == group_id,
                    ErrorOccurrence.error_category == "word",
                    ErrorOccurrence.created_at >= start,
                    ErrorOccurrence.created_at < end,
                )
            )
            grammar_total = await session.scalar(
                select(func.count())
                .select_from(ErrorOccurrence)
                .where(
                    ErrorOccurrence.user_id == user_id,
                    ErrorOccurrence.group_id == group_id,
                    ErrorOccurrence.error_category == "grammar",
                    ErrorOccurrence.created_at >= start,
                    ErrorOccurrence.created_at < end,
                )
            )

            async def _load_items(category: str, limit: int) -> list[dict[str, Any]]:
                rows = await session.execute(
                    select(
                        ErrorOccurrence.error_type,
                        ErrorOccurrence.source_fragment,
                        ErrorOccurrence.correct_fragment,
                        ErrorOccurrence.explanation,
                        func.count().label("frequency"),
                        func.max(ErrorOccurrence.created_at).label("latest_at"),
                    )
                    .where(
                        ErrorOccurrence.user_id == user_id,
                        ErrorOccurrence.group_id == group_id,
                        ErrorOccurrence.error_category == category,
                        ErrorOccurrence.created_at >= start,
                        ErrorOccurrence.created_at < end,
                    )
                    .group_by(
                        ErrorOccurrence.error_type,
                        ErrorOccurrence.source_fragment,
                        ErrorOccurrence.correct_fragment,
                        ErrorOccurrence.explanation,
                    )
                    .order_by(desc("frequency"), desc("latest_at"))
                    .limit(limit)
                )
                return [
                    {
                        "error_type": row[0],
                        "source_fragment": row[1],
                        "correct_fragment": row[2],
                        "explanation": row[3],
                        "frequency": int(row[4] or 0),
                    }
                    for row in rows.all()
                ]

            return {
                "word_total": int(word_total or 0),
                "grammar_total": int(grammar_total or 0),
                "word_items": await _load_items("word", word_limit),
                "grammar_items": await _load_items("grammar", grammar_limit),
            }

    async def get_daily_conversation_evidence_stats(
        self,
        *,
        user_id: int,
        group_id: int,
        target_date: date,
    ) -> dict[str, Any]:
        async with self._session_factory() as session:
            total_messages = await session.scalar(
                select(func.count())
                .select_from(MessageEvent)
                .where(
                    MessageEvent.user_id == user_id,
                    MessageEvent.group_id == group_id,
                    MessageEvent.biz_date_local == target_date,
                )
            )
            rows = await session.execute(
                select(
                    ConversationEvidence.evidence_type,
                    func.count().label("evidence_count"),
                    func.sum(ConversationEvidence.evidence_score).label("score_sum"),
                )
                .where(
                    ConversationEvidence.user_id == user_id,
                    ConversationEvidence.group_id == group_id,
                    ConversationEvidence.biz_date == target_date,
                )
                .group_by(ConversationEvidence.evidence_type)
            )
            counts: dict[str, dict[str, int]] = {}
            for evidence_type, evidence_count, score_sum in rows.all():
                counts[str(evidence_type)] = {
                    "count": int(evidence_count or 0),
                    "score": int(score_sum or 0),
                }

            evidence_examples = await session.scalars(
                select(ConversationEvidence.payload_json)
                .where(
                    ConversationEvidence.user_id == user_id,
                    ConversationEvidence.group_id == group_id,
                    ConversationEvidence.biz_date == target_date,
                    ConversationEvidence.evidence_type.in_(["target_hit", "english_attempt", "question_asked"]),
                )
                .order_by(desc(ConversationEvidence.evidence_score), ConversationEvidence.id.asc())
                .limit(6)
            )
            examples: list[str] = []
            for payload in evidence_examples:
                if not isinstance(payload, dict):
                    continue
                token = (payload.get("token") or payload.get("text") or "").strip()
                if token and token not in examples:
                    examples.append(token)

            return {
                "total_messages": int(total_messages or 0),
                "english_attempt_count": counts.get("english_attempt", {}).get("count", 0),
                "target_hit_count": counts.get("target_hit", {}).get("count", 0),
                "question_asked_count": counts.get("question_asked", {}).get("count", 0),
                "chat_noise_count": counts.get("chat_noise", {}).get("count", 0),
                "evidence_score": sum(item["score"] for item in counts.values()),
                "examples": examples[:3],
            }

    async def get_daily_progress_stats(
        self,
        *,
        user_id: int,
        group_id: int,
        target_date: date,
    ) -> dict[str, Any]:
        async with self._session_factory() as session:
            start, end = self._local_day_bounds(target_date)

            translation_count = await session.scalar(
                select(func.count())
                .select_from(InteractionResult)
                .join(MessageEvent, MessageEvent.id == InteractionResult.event_id)
                .where(
                    MessageEvent.user_id == user_id,
                    MessageEvent.group_id == group_id,
                    InteractionResult.action_type == "chinese_translation",
                    InteractionResult.created_at >= start,
                    InteractionResult.created_at < end,
                )
            )
            correction_count = await session.scalar(
                select(func.count())
                .select_from(InteractionResult)
                .join(MessageEvent, MessageEvent.id == InteractionResult.event_id)
                .where(
                    MessageEvent.user_id == user_id,
                    MessageEvent.group_id == group_id,
                    InteractionResult.action_type == "english_correction",
                    InteractionResult.created_at >= start,
                    InteractionResult.created_at < end,
                )
            )
            word_error_count = await session.scalar(
                select(func.count())
                .select_from(ErrorOccurrence)
                .where(
                    ErrorOccurrence.user_id == user_id,
                    ErrorOccurrence.group_id == group_id,
                    ErrorOccurrence.error_category == "word",
                    ErrorOccurrence.created_at >= start,
                    ErrorOccurrence.created_at < end,
                )
            )
            grammar_error_count = await session.scalar(
                select(func.count())
                .select_from(ErrorOccurrence)
                .where(
                    ErrorOccurrence.user_id == user_id,
                    ErrorOccurrence.group_id == group_id,
                    ErrorOccurrence.error_category == "grammar",
                    ErrorOccurrence.created_at >= start,
                    ErrorOccurrence.created_at < end,
                )
            )
            task_completion_count = await session.scalar(
                select(func.count())
                .select_from(TaskSubmission)
                .join(DailyTask, DailyTask.id == TaskSubmission.task_id)
                .join(DailyLesson, DailyLesson.id == DailyTask.lesson_id)
                .where(
                    TaskSubmission.user_id == user_id,
                    DailyLesson.group_id == group_id,
                    TaskSubmission.submitted_at >= start,
                    TaskSubmission.submitted_at < end,
                )
            )
            review_session_count = await session.scalar(
                select(func.count())
                .select_from(PointsLedger)
                .where(
                    PointsLedger.user_id == user_id,
                    PointsLedger.reason == "review_session",
                    PointsLedger.created_at >= start,
                    PointsLedger.created_at < end,
                )
            )
            points_earned = await session.scalar(
                select(func.sum(PointsLedger.points))
                .where(
                    PointsLedger.user_id == user_id,
                    PointsLedger.created_at >= start,
                    PointsLedger.created_at < end,
                )
            )
            today_task_total = await session.scalar(
                select(func.count())
                .select_from(DailyTask)
                .join(DailyLesson, DailyLesson.id == DailyTask.lesson_id)
                .where(
                    DailyLesson.group_id == group_id,
                    DailyLesson.biz_date == target_date,
                )
            )
            today_task_completed = await session.scalar(
                select(func.count())
                .select_from(TaskSubmission)
                .join(DailyTask, DailyTask.id == TaskSubmission.task_id)
                .join(DailyLesson, DailyLesson.id == DailyTask.lesson_id)
                .where(
                    TaskSubmission.user_id == user_id,
                    DailyLesson.group_id == group_id,
                    DailyLesson.biz_date == target_date,
                )
            )
            quiz_activity_count = await session.scalar(
                select(func.count())
                .select_from(QuizSession)
                .where(
                    QuizSession.user_id == user_id,
                    QuizSession.group_id == group_id,
                    QuizSession.updated_at >= start,
                    QuizSession.updated_at < end,
                )
            )
            level_row = await session.scalar(
                select(UserLevel).where(
                    UserLevel.user_id == user_id,
                    UserLevel.group_id == group_id,
                )
            )
            streak = await session.scalar(select(Streak).where(Streak.user_id == user_id))
            activity_count = sum(
                int(value or 0)
                for value in [
                    translation_count,
                    correction_count,
                    word_error_count,
                    grammar_error_count,
                    task_completion_count,
                    review_session_count,
                    quiz_activity_count,
                ]
            )

            return {
                "translation_count": int(translation_count or 0),
                "correction_count": int(correction_count or 0),
                "word_error_count": int(word_error_count or 0),
                "grammar_error_count": int(grammar_error_count or 0),
                "task_completion_count": int(task_completion_count or 0),
                "today_task_total": int(today_task_total or 0),
                "today_task_completed": int(today_task_completed or 0),
                "review_session_count": int(review_session_count or 0),
                "quiz_activity_count": int(quiz_activity_count or 0),
                "points_earned": int(points_earned or 0),
                "current_streak": int(streak.current_days if streak else 0),
                "level": level_row.current_level if level_row else "beginner",
                "has_activity": activity_count > 0,
            }

    async def list_top_error_fragments(self, *, user_id: int, group_id: int, limit: int = 5) -> list[ErrorPoint]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(ErrorPoint)
                .where(
                    ErrorPoint.user_id == user_id,
                    ErrorPoint.group_id == group_id,
                )
                .order_by(desc(ErrorPoint.frequency), desc(ErrorPoint.last_seen_at))
                .limit(limit)
            )
            return list(rows)
