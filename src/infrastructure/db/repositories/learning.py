from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.value_objects.learning import ErrorPointPayload, LessonBundle
from src.infrastructure.db.models import (
    ContentItem,
    DailyLesson,
    DailyTask,
    ErrorPoint,
    InteractionResult,
    JobRun,
    MessageEvent,
    PointsLedger,
    QuizQuestion,
    QuizSession,
    QuizAnswer,
    ReviewItem,
    RuntimeSetting,
    TaskSubmission,
    UserLevel,
    WeeklyReport,
)


class LearningRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_message_event(
        self,
        *,
        raw_event_id: str,
        group_id: int | None,
        user_id: int,
        message_text: str,
        event_type: str,
    ) -> MessageEvent:
        async with self._session_factory() as session:
            message_event = MessageEvent(
                raw_event_id=raw_event_id,
                group_id=group_id,
                user_id=user_id,
                message_text=message_text,
                event_type=event_type,
            )
            session.add(message_event)
            await session.commit()
            await session.refresh(message_event)
            return message_event

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
                    status="published",
                )
                session.add(lesson)
                await session.flush()
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
            await session.commit()
            await session.refresh(lesson)
            return lesson

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

    async def acquire_job_lock(self, *, job_name: str, biz_key: str) -> bool:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(JobRun).where(JobRun.job_name == job_name, JobRun.biz_key == biz_key)
            )
            if row is not None and row.status in {"running", "success"}:
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
            total_users = await session.scalar(select(func.count()).select_from(MessageEvent))
            total_errors = await session.scalar(select(func.count()).select_from(ErrorPoint))
            total_reviews = await session.scalar(select(func.count()).select_from(ReviewItem))
            total_jobs = await session.scalar(select(func.count()).select_from(JobRun))
            return {
                "message_events": int(total_users or 0),
                "error_points": int(total_errors or 0),
                "review_items": int(total_reviews or 0),
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
