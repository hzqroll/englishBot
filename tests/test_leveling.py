from src.domain.services.leveling import LearningEvidence, LevelService


def test_level_service_promotes_active_and_high_score_user():
    service = LevelService()
    level, evidence = service.evaluate(
        LearningEvidence(
            translation_count=8,
            correction_count=6,
            task_completion_count=4,
            quiz_average_score=80,
        )
    )
    assert level == "intermediate"
    assert evidence["activity_score"] >= 20

