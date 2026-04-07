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


@dataclass(slots=True)
class SpeakerFeedback:
    speaker: str
    issues: list[str] = field(default_factory=list)
    overall_comment: str = ""


@dataclass(slots=True)
class DialogueAnalysisResult:
    translated_dialogue: str
    speaker_feedbacks: list[SpeakerFeedback] = field(default_factory=list)
    source_kind: str = "explicit_text"
