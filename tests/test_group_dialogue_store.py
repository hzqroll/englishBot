from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.infrastructure.cache.group_dialogue_store import GroupDialogueStore


def test_group_dialogue_store_counts_sentences_and_renders_speakers() -> None:
    store = GroupDialogueStore()
    store.append_group_message(
        group_id="g1",
        user_id="u1",
        nickname="Alice",
        text="Hello world. How are you?",
    )
    store.append_group_message(
        group_id="g1",
        user_id="u2",
        nickname="Bob",
        text="I am fine。",
    )

    snapshot = store.get_group_dialogue("g1")

    assert snapshot.entry_count == 2
    assert snapshot.sentence_count == 3
    assert "Alice：Hello world. How are you?" in snapshot.rendered_text
    assert "Bob：I am fine。" in snapshot.rendered_text


def test_group_dialogue_store_resets_when_day_changes() -> None:
    store = GroupDialogueStore()
    yesterday = datetime.now(UTC) - timedelta(days=1)
    store.append_group_message(
        group_id="g1",
        user_id="u1",
        nickname="Alice",
        text="Hello world.",
        created_at=yesterday,
    )

    snapshot = store.get_group_dialogue("g1", now=datetime.now(UTC))

    assert snapshot.entry_count == 0
    assert snapshot.sentence_count == 0
    assert snapshot.rendered_text == ""
