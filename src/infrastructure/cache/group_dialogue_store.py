from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime


_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?\.]+|\n+")


@dataclass(slots=True)
class GroupDialogueEntry:
    speaker: str
    text: str
    created_at: datetime


@dataclass(slots=True)
class GroupDialogueBucket:
    biz_date: date
    entries: list[GroupDialogueEntry] = field(default_factory=list)


@dataclass(slots=True)
class GroupDialogueSnapshot:
    rendered_text: str = ""
    sentence_count: int = 0
    entry_count: int = 0


class GroupDialogueStore:
    def __init__(self, *, max_entries_per_group: int = 120) -> None:
        self._max_entries_per_group = max_entries_per_group
        self._store: dict[str, GroupDialogueBucket] = {}

    def append_group_message(
        self,
        *,
        group_id: str,
        user_id: str,
        nickname: str,
        text: str,
        created_at: datetime | None = None,
    ) -> None:
        cleaned = text.strip()
        if not cleaned:
            return

        now = created_at or datetime.now(UTC)
        biz_date = now.astimezone().date()
        bucket = self._store.get(group_id)
        if bucket is None or bucket.biz_date != biz_date:
            bucket = GroupDialogueBucket(biz_date=biz_date)
            self._store[group_id] = bucket

        speaker = (nickname or "").strip() or user_id or "用户"
        bucket.entries.append(GroupDialogueEntry(speaker=speaker, text=cleaned, created_at=now))
        if len(bucket.entries) > self._max_entries_per_group:
            bucket.entries = bucket.entries[-self._max_entries_per_group :]

    def get_group_dialogue(self, group_id: str, *, now: datetime | None = None) -> GroupDialogueSnapshot:
        current = now or datetime.now(UTC)
        bucket = self._store.get(group_id)
        if bucket is None:
            return GroupDialogueSnapshot()

        if bucket.biz_date != current.astimezone().date():
            self._store.pop(group_id, None)
            return GroupDialogueSnapshot()

        rendered_lines = [f"{item.speaker}：{item.text}" for item in bucket.entries]
        sentence_count = sum(self._count_sentences(item.text) for item in bucket.entries)
        return GroupDialogueSnapshot(
            rendered_text="\n".join(rendered_lines),
            sentence_count=sentence_count,
            entry_count=len(bucket.entries),
        )

    def _count_sentences(self, text: str) -> int:
        chunks = [item.strip() for item in _SENTENCE_SPLIT_RE.split(text) if item.strip()]
        return len(chunks) or 1
