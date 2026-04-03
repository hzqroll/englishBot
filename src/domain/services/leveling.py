from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class LearningEvidence:
    translation_count: int
    correction_count: int
    task_completion_count: int
    quiz_average_score: float


class LevelService:
    """Simple two-level placement logic for the first release."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"

    def evaluate(self, evidence: LearningEvidence) -> tuple[str, dict]:
        activity_score = (
            evidence.translation_count
            + evidence.correction_count * 2
            + evidence.task_completion_count * 3
        )
        mastery_score = evidence.quiz_average_score

        if activity_score >= 20 and mastery_score >= 70:
            level = self.INTERMEDIATE
        else:
            level = self.BEGINNER

        return level, {
            "activity_score": activity_score,
            "mastery_score": mastery_score,
            "translation_count": evidence.translation_count,
            "correction_count": evidence.correction_count,
            "task_completion_count": evidence.task_completion_count,
        }

