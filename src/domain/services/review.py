from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(slots=True)
class ReviewProgress:
    interval_days: int
    correct_streak: int
    next_review_at: datetime
    status: str


class ReviewScheduler:
    """A compact spaced repetition policy for v1."""

    def schedule_new(self) -> ReviewProgress:
        next_review = datetime.now(UTC) + timedelta(days=1)
        return ReviewProgress(
            interval_days=1,
            correct_streak=0,
            next_review_at=next_review,
            status="pending",
        )

    def update_after_answer(
        self,
        *,
        was_correct: bool,
        interval_days: int,
        correct_streak: int,
    ) -> ReviewProgress:
        if was_correct:
            correct_streak += 1
            interval_days = min(max(interval_days, 1) * 2, 30)
            status = "mastered" if correct_streak >= 3 else "learning"
        else:
            correct_streak = 0
            interval_days = 1
            status = "pending"

        next_review = datetime.now(UTC) + timedelta(days=interval_days)
        return ReviewProgress(
            interval_days=interval_days,
            correct_streak=correct_streak,
            next_review_at=next_review,
            status=status,
        )

