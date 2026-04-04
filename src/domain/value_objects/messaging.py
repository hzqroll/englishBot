from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class MessageEnvelope:
    plain_text: str
    fallback_text: str | None = None
    card_payload: dict[str, Any] | None = None
    card_link_url: str | None = None
    card_title: str | None = None

    def delivery_text(self) -> str:
        return self.fallback_text or self.plain_text


@dataclass(slots=True)
class CardLinkPayload:
    resource_type: str
    resource_id: str
    qq_user_id: str
    qq_group_id: str
    expires_at: datetime
