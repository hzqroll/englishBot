from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    qq_user_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(128), default="")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class Group(Base, TimestampMixin):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    qq_group_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    platform: Mapped[str] = mapped_column(String(32), default="onebot")


class Enrollment(Base, TimestampMixin):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "group_id", name="uq_enrollments_user_group"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class MessageEvent(Base):
    __tablename__ = "message_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_event_id: Mapped[str] = mapped_column(String(64), index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    message_text: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(String(64), default="group_message")
    source_type: Mapped[str] = mapped_column(String(32), default="unknown", index=True)
    is_to_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_command: Mapped[bool] = mapped_column(Boolean, default=False)
    language_guess: Mapped[str] = mapped_column(String(16), default="unknown")
    analysis_status: Mapped[str] = mapped_column(String(16), default="pending")
    biz_date_local: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class InteractionResult(Base):
    __tablename__ = "interaction_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("message_events.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(64))
    reply_text: Mapped[str] = mapped_column(Text)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ErrorPoint(Base, TimestampMixin):
    __tablename__ = "error_points"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "group_id",
            "error_type",
            "source_fragment",
            "correct_fragment",
            name="uq_error_points_signature",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    error_type: Mapped[str] = mapped_column(String(64), index=True)
    source_fragment: Mapped[str] = mapped_column(String(255))
    correct_fragment: Mapped[str] = mapped_column(String(255))
    explanation: Mapped[str] = mapped_column(Text)
    frequency: Mapped[int] = mapped_column(Integer, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ErrorOccurrence(Base):
    __tablename__ = "error_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "error_type",
            "source_fragment",
            "correct_fragment",
            name="uq_error_occurrences_event_signature",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("message_events.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    error_point_id: Mapped[int | None] = mapped_column(ForeignKey("error_points.id"), nullable=True, index=True)
    error_category: Mapped[str] = mapped_column(String(16), index=True)
    error_type: Mapped[str] = mapped_column(String(64), index=True)
    source_fragment: Mapped[str] = mapped_column(String(255))
    correct_fragment: Mapped[str] = mapped_column(String(255))
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ConversationEvidence(Base):
    __tablename__ = "conversation_evidences"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    message_event_id: Mapped[int] = mapped_column(ForeignKey("message_events.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    biz_date: Mapped[date] = mapped_column(Date, index=True)
    evidence_type: Mapped[str] = mapped_column(String(32), index=True)
    evidence_score: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ReviewItem(Base, TimestampMixin):
    __tablename__ = "review_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    source_ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_point_id: Mapped[int | None] = mapped_column(ForeignKey("error_points.id"), nullable=True, index=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=1)
    next_review_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    correct_streak: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")


class ReviewCandidate(Base, TimestampMixin):
    __tablename__ = "review_candidates"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    biz_date: Mapped[date] = mapped_column(Date, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_text: Mapped[str] = mapped_column(String(255))
    correct_text: Mapped[str] = mapped_column(String(255), default="")
    priority_score: Mapped[int] = mapped_column(Integer, default=0)
    selected_for_next_day: Mapped[bool] = mapped_column(Boolean, default=False)
    used_in_next_day_task: Mapped[bool] = mapped_column(Boolean, default=False)
    recalled_successfully: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class ContentItem(Base, TimestampMixin):
    __tablename__ = "content_items"
    __table_args__ = (UniqueConstraint("source_name", "external_id", name="uq_content_source_external"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(500))
    transcript: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(32), default="beginner")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class DailyLesson(Base, TimestampMixin):
    __tablename__ = "daily_lessons"
    __table_args__ = (UniqueConstraint("biz_date", "group_id", name="uq_daily_lessons_biz_date_group"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    biz_date: Mapped[datetime] = mapped_column(Date)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    content_item_id: Mapped[int] = mapped_column(ForeignKey("content_items.id"))
    theme_key: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    package_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="published")


class DailyTargetItem(Base, TimestampMixin):
    __tablename__ = "daily_target_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("daily_lessons.id"), index=True)
    entry_key: Mapped[str] = mapped_column(String(128), index=True)
    entry_type: Mapped[str] = mapped_column(String(32), default="word")
    text: Mapped[str] = mapped_column(String(255))
    phonetic: Mapped[str] = mapped_column(String(255), default="")
    meaning_zh: Mapped[str] = mapped_column(String(255), default="")
    usage_scene: Mapped[str] = mapped_column(Text, default="")
    example: Mapped[str] = mapped_column(Text, default="")
    target_role: Mapped[str] = mapped_column(String(32), default="support_word")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class DailyTask(Base, TimestampMixin):
    __tablename__ = "daily_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    lesson_id: Mapped[int] = mapped_column(ForeignKey("daily_lessons.id"), index=True)
    task_type: Mapped[str] = mapped_column(String(64))
    prompt: Mapped[str] = mapped_column(Text)
    answer_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_weight: Mapped[int] = mapped_column(Integer, default=10)


class TaskSubmission(Base, TimestampMixin):
    __tablename__ = "task_submissions"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_submissions_task_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("daily_tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    submission_text: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class DailyLearningSnapshot(Base, TimestampMixin):
    __tablename__ = "daily_learning_snapshots"
    __table_args__ = (UniqueConstraint("biz_date", "user_id", "group_id", name="uq_daily_learning_snapshots_day_user_group"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    biz_date: Mapped[date] = mapped_column(Date, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    lesson_id: Mapped[int | None] = mapped_column(ForeignKey("daily_lessons.id"), nullable=True, index=True)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    mastery_level: Mapped[str] = mapped_column(String(32), default="needs_strengthening")
    mastery_reason: Mapped[str] = mapped_column(Text, default="")
    model_summary: Mapped[str] = mapped_column(Text, default="")
    activity_score: Mapped[int] = mapped_column(Integer, default=0)
    evidence_score: Mapped[int] = mapped_column(Integer, default=0)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class DailyCardSnapshot(Base, TimestampMixin):
    __tablename__ = "daily_card_snapshots"
    __table_args__ = (UniqueConstraint("biz_date", "user_id", "group_id", "card_type", name="uq_daily_card_snapshots_day_user_group_type"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    biz_date: Mapped[date] = mapped_column(Date, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    card_type: Mapped[str] = mapped_column(String(32), index=True)
    card_document_json: Mapped[dict] = mapped_column(JSON, default=dict)
    plain_text: Mapped[str] = mapped_column(Text, default="")
    image_paths_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class MessageDeliveryLog(Base, TimestampMixin):
    __tablename__ = "message_delivery_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    job_name: Mapped[str] = mapped_column(String(64), index=True)
    card_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("daily_card_snapshots.id"), nullable=True, index=True)
    delivery_mode: Mapped[str] = mapped_column(String(32), default="text")
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    provider_response: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class QuizSession(Base, TimestampMixin):
    __tablename__ = "quiz_sessions"
    __table_args__ = (UniqueConstraint("biz_week", "group_id", "user_id", name="uq_quiz_sessions_week_group_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    biz_week: Mapped[str] = mapped_column(String(16), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    total_score: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="ready")


class QuizQuestion(Base, TimestampMixin):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("quiz_sessions.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(64))
    stem: Mapped[str] = mapped_column(Text)
    options: Mapped[list[str]] = mapped_column(JSON)
    answer_key: Mapped[str] = mapped_column(String(8))
    explanation: Mapped[str] = mapped_column(Text)


class QuizAnswer(Base, TimestampMixin):
    __tablename__ = "quiz_answers"
    __table_args__ = (UniqueConstraint("session_id", "question_id", name="uq_quiz_answers_session_question"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("quiz_sessions.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("quiz_questions.id"), index=True)
    user_answer: Mapped[str] = mapped_column(String(8))
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[int] = mapped_column(Integer, default=0)


class WeeklyReport(Base, TimestampMixin):
    __tablename__ = "weekly_reports"
    __table_args__ = (UniqueConstraint("biz_week", "user_id", name="uq_weekly_reports_week_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    biz_week: Mapped[str] = mapped_column(String(16), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    report_json: Mapped[dict] = mapped_column(JSON)
    summary_text: Mapped[str] = mapped_column(Text)


class UserLevel(Base, TimestampMixin):
    __tablename__ = "user_levels"
    __table_args__ = (UniqueConstraint("user_id", "group_id", name="uq_user_levels_user_group"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    current_level: Mapped[str] = mapped_column(String(32), default="beginner")
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    evidence_json: Mapped[dict] = mapped_column(JSON, default=dict)


class PointsLedger(Base, TimestampMixin):
    __tablename__ = "points_ledger"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    points: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(128))


class Streak(Base, TimestampMixin):
    __tablename__ = "streaks"
    __table_args__ = (UniqueConstraint("user_id", name="uq_streaks_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    current_days: Mapped[int] = mapped_column(Integer, default=0)
    max_days: Mapped[int] = mapped_column(Integer, default=0)
    last_activity_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class GroupConfig(Base, TimestampMixin):
    __tablename__ = "group_configs"
    __table_args__ = (UniqueConstraint("group_id", "key", name="uq_group_configs_group_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    key: Mapped[str] = mapped_column(String(128))
    value: Mapped[str] = mapped_column(Text)


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="active")


class JobRun(Base, TimestampMixin):
    __tablename__ = "job_runs"
    __table_args__ = (UniqueConstraint("job_name", "biz_key", name="uq_job_runs_job_key"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_name: Mapped[str] = mapped_column(String(64), index=True)
    biz_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
