from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CardSection:
    title: str | None = None
    lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CardDocument:
    title: str
    subtitle: str | None = None
    sections: list[CardSection] = field(default_factory=list)
    footer_lines: list[str] = field(default_factory=list)
    theme: str = "blue"


@dataclass(slots=True)
class MessageEnvelope:
    plain_text: str
    fallback_text: str | None = None
    card_document: CardDocument | None = None
    card_type: str | None = None
    card_snapshot_id: int | None = None

    def delivery_text(self) -> str:
        return self.fallback_text or self.plain_text
