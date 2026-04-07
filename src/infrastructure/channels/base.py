from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from src.domain.value_objects.messaging import MessageEnvelope


@dataclass(slots=True)
class MessageContext:
    """统一的跨平台消息上下文"""

    raw_event_id: str
    chat_id: str
    chat_name: str
    user_id: str
    nickname: str
    message_text: str
    is_mention_bot: bool
    platform: str = ""


@dataclass(slots=True)
class DeliveryResult:
    delivery_mode: str
    success: bool = True
    image_paths: list[str] = field(default_factory=list)


class ChannelAdapter(ABC):
    @property
    @abstractmethod
    def channel_name(self) -> str: ...

    @abstractmethod
    async def send_text(self, chat_id: str, text: str, *, mention_user: str | None = None) -> DeliveryResult: ...

    @abstractmethod
    async def send_envelope(
        self,
        chat_id: str,
        envelope: MessageEnvelope,
        *,
        mention_user: str | None = None,
    ) -> DeliveryResult: ...

    @abstractmethod
    async def get_chat_messages(self, chat_id: str, since: datetime, limit: int = 50) -> list[MessageContext]: ...
