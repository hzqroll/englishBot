from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(slots=True)
class ConversationContext:
    summary: str
    expires_at: datetime


class ContextStore:
    def __init__(self, ttl_minutes: int = 15) -> None:
        self._ttl_minutes = ttl_minutes
        self._store: dict[str, ConversationContext] = {}

    def _build_key(self, group_id: str, user_id: str) -> str:
        return f"{group_id}:{user_id}"

    def get(self, group_id: str, user_id: str) -> str | None:
        key = self._build_key(group_id, user_id)
        context = self._store.get(key)
        now = datetime.now(UTC)
        if context is None or context.expires_at <= now:
            self._store.pop(key, None)
            return None
        return context.summary

    def put(self, group_id: str, user_id: str, summary: str) -> None:
        key = self._build_key(group_id, user_id)
        self._store[key] = ConversationContext(
            summary=summary,
            expires_at=datetime.now(UTC) + timedelta(minutes=self._ttl_minutes),
        )

