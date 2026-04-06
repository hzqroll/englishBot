from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(slots=True)
class UserProfile:
    id: int
    qq_user_id: str
    nickname: str
    joined_at: datetime
    last_active_at: datetime


@dataclass(slots=True)
class Enrollment:
    user_id: int
    group_id: int
    status: str
    enrolled_at: datetime


@dataclass(slots=True)
class ErrorPointEntity:
    id: int
    user_id: int
    group_id: int
    error_type: str
    source_fragment: str
    correct_fragment: str
    explanation: str
    frequency: int
    last_seen_at: datetime


@dataclass(slots=True)
class ReviewItemEntity:
    id: int
    user_id: int
    error_point_id: int | None
    source_type: str
    source_ref_id: str | None
    interval_days: int
    next_review_at: datetime
    correct_streak: int
    status: str


@dataclass(slots=True)
class ReviewCandidateEntity:
    id: int
    biz_date: date
    user_id: int
    group_id: int
    source_type: str
    source_ref_id: str | None
    content_text: str
    correct_text: str
    priority_score: int
    selected_for_next_day: bool
    used_in_next_day_task: bool
    recalled_successfully: bool | None


@dataclass(slots=True)
class DailyTaskEntity:
    id: int
    lesson_id: int
    task_type: str
    prompt: str
    answer_key: str | None
    score_weight: int


@dataclass(slots=True)
class QuizSessionEntity:
    id: int
    biz_week: str
    group_id: int
    user_id: int
    total_score: int
    status: str


@dataclass(slots=True)
class WeeklyReportEntity:
    id: int
    biz_week: str
    user_id: int
    summary_text: str
    report_json: dict
    created_at: date
