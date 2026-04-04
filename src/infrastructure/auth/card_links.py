from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from itsdangerous import BadData, URLSafeSerializer

from src.domain.value_objects.messaging import CardLinkPayload


class CardLinkSigner:
    def __init__(self, secret_key: str) -> None:
        self._serializer = URLSafeSerializer(secret_key=secret_key, salt="english-bot-card-links")

    def sign(
        self,
        *,
        resource_type: str,
        resource_id: str,
        qq_user_id: str,
        qq_group_id: str,
        expires_at: datetime,
    ) -> str:
        payload = CardLinkPayload(
            resource_type=resource_type,
            resource_id=resource_id,
            qq_user_id=qq_user_id,
            qq_group_id=qq_group_id,
            expires_at=expires_at.astimezone(UTC),
        )
        data = asdict(payload)
        data["expires_at"] = payload.expires_at.isoformat()
        return self._serializer.dumps(data)

    def verify(self, token: str) -> CardLinkPayload:
        try:
            data = self._serializer.loads(token)
        except BadData as exc:
            raise ValueError("链接签名无效。") from exc

        expires_at = datetime.fromisoformat(data["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        expires_at = expires_at.astimezone(UTC)
        if expires_at < datetime.now(UTC):
            raise ValueError("链接已过期，请回到群里重新获取。")

        return CardLinkPayload(
            resource_type=str(data["resource_type"]),
            resource_id=str(data["resource_id"]),
            qq_user_id=str(data["qq_user_id"]),
            qq_group_id=str(data["qq_group_id"]),
            expires_at=expires_at,
        )
