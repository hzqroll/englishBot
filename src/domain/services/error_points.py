from __future__ import annotations

from collections.abc import Iterable

from src.domain.value_objects.learning import ErrorPointPayload


class ErrorAggregator:
    """Aggregate repeated error points into a deterministic signature."""

    @staticmethod
    def signature(payload: ErrorPointPayload) -> str:
        return "|".join(
            [
                payload.error_type.strip().lower(),
                payload.source_fragment.strip().lower(),
                payload.correct_fragment.strip().lower(),
            ]
        )

    def merge(self, payloads: Iterable[ErrorPointPayload]) -> list[ErrorPointPayload]:
        merged: dict[str, ErrorPointPayload] = {}
        for payload in payloads:
            signature = self.signature(payload)
            merged.setdefault(signature, payload)
        return list(merged.values())

