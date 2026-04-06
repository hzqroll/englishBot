from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ConversationEvidencePayload:
    evidence_type: str
    evidence_score: int
    payload_json: dict = field(default_factory=dict)


@dataclass(slots=True)
class ConversationObservationResult:
    language_guess: str
    evidence_payloads: list[ConversationEvidencePayload] = field(default_factory=list)
