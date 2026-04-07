from __future__ import annotations

from typing import Protocol

from src.domain.value_objects.learning import CorrectionResult


class EnglishCorrectionProvider(Protocol):
    async def correct_english(self, text: str, context: str | None = None) -> CorrectionResult:
        ...
