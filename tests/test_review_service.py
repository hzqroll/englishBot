from src.domain.services.review import ReviewScheduler


def test_review_scheduler_resets_interval_after_wrong_answer():
    scheduler = ReviewScheduler()
    progress = scheduler.update_after_answer(
        was_correct=False,
        interval_days=4,
        correct_streak=2,
    )
    assert progress.interval_days == 1
    assert progress.correct_streak == 0
    assert progress.status == "pending"

