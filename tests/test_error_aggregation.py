from src.domain.services.error_points import ErrorAggregator
from src.domain.value_objects.learning import ErrorPointPayload


def test_error_aggregation_deduplicates_same_signature():
    aggregator = ErrorAggregator()
    payload = ErrorPointPayload(
        error_type="tense",
        source_fragment="go",
        correct_fragment="went",
        explanation="past tense",
    )
    merged = aggregator.merge([payload, payload])
    assert len(merged) == 1

