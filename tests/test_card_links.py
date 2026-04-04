from datetime import UTC, datetime, timedelta

import pytest

from src.infrastructure.auth.card_links import CardLinkSigner


def test_card_link_signer_roundtrip() -> None:
    signer = CardLinkSigner("secret-key")
    token = signer.sign(
        resource_type="task",
        resource_id="12",
        qq_user_id="10001",
        qq_group_id="20002",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )

    payload = signer.verify(token)

    assert payload.resource_type == "task"
    assert payload.resource_id == "12"
    assert payload.qq_user_id == "10001"
    assert payload.qq_group_id == "20002"


def test_card_link_signer_rejects_expired_token() -> None:
    signer = CardLinkSigner("secret-key")
    token = signer.sign(
        resource_type="quiz",
        resource_id="5",
        qq_user_id="10001",
        qq_group_id="20002",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    with pytest.raises(ValueError, match="已过期"):
        signer.verify(token)
