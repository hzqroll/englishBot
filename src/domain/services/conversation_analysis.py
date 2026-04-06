from __future__ import annotations

import re

from src.domain.value_objects.conversation import ConversationEvidencePayload, ConversationObservationResult


class ConversationAnalysisService:
    _WORD_RE = re.compile(r"[A-Za-z][A-Za-z']+")
    _CJK_RE = re.compile(r"[\u4e00-\u9fff]")
    _STOPWORDS = {
        "about",
        "after",
        "again",
        "because",
        "before",
        "being",
        "could",
        "every",
        "first",
        "great",
        "hello",
        "please",
        "should",
        "their",
        "there",
        "these",
        "thing",
        "think",
        "today",
        "tomorrow",
        "would",
        "which",
        "while",
        "with",
        "your",
    }

    def guess_language(self, text: str) -> str:
        letters = len(self._WORD_RE.findall(text))
        cjk = len(self._CJK_RE.findall(text))
        if letters and cjk:
            return "mixed"
        if letters:
            return "english"
        if cjk:
            return "chinese"
        return "unknown"

    def extract_target_terms(self, *texts: str, limit: int = 12) -> set[str]:
        ordered_terms: list[str] = []
        seen: set[str] = set()
        for text in texts:
            for match in self._WORD_RE.findall(text.lower()):
                token = match.strip("'")
                if len(token) < 4 or token in self._STOPWORDS:
                    continue
                if token in seen:
                    continue
                seen.add(token)
                ordered_terms.append(token)
                if len(ordered_terms) >= limit:
                    return set(ordered_terms)
        return set(ordered_terms)

    def observe_message(self, *, text: str, target_terms: set[str] | None = None) -> ConversationObservationResult:
        language_guess = self.guess_language(text)
        payloads: list[ConversationEvidencePayload] = []
        normalized = text.lower()
        message_terms = {token.strip("'") for token in self._WORD_RE.findall(normalized)}

        if language_guess in {"english", "mixed"} and len(message_terms) >= 1:
            payloads.append(
                ConversationEvidencePayload(
                    evidence_type="english_attempt",
                    evidence_score=2,
                    payload_json={"matched_terms": sorted(message_terms)[:8]},
                )
            )

        if "?" in text or "？" in text:
            payloads.append(
                ConversationEvidencePayload(
                    evidence_type="question_asked",
                    evidence_score=1,
                    payload_json={"text": text[:120]},
                )
            )

        target_terms = target_terms or set()
        matched_targets = sorted(message_terms & target_terms)
        if matched_targets:
            payloads.append(
                ConversationEvidencePayload(
                    evidence_type="target_hit",
                    evidence_score=3,
                    payload_json={"matched_terms": matched_targets[:8]},
                )
            )

        if not payloads:
            payloads.append(
                ConversationEvidencePayload(
                    evidence_type="chat_noise",
                    evidence_score=0,
                    payload_json={"reason": "no_learning_signal"},
                )
            )

        return ConversationObservationResult(
            language_guess=language_guess,
            evidence_payloads=payloads,
        )
