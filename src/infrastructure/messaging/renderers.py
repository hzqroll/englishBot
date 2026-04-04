from __future__ import annotations

import json

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from src.domain.value_objects.messaging import MessageEnvelope
from src.infrastructure.settings.runtime import RuntimeConfigService


class PlainTextRenderer:
    def render(self, envelope: MessageEnvelope, *, mention_qq: str | None = None) -> str:
        text = envelope.delivery_text()
        if mention_qq:
            return f"[CQ:at,qq={mention_qq}]\n{text}"
        return text


class NapCatCardRenderer:
    def build_click_card(
        self,
        *,
        title: str,
        summary: str,
        url: str,
        action_label: str,
        tag: str = "English Bot",
    ) -> dict:
        return {
            "app": "com.tencent.structmsg",
            "config": {
                "autosize": 1,
                "forward": 1,
            },
            "desc": tag,
            "meta": {
                "news": {
                    "tag": tag,
                    "title": title[:60],
                    "desc": f"{summary[:120]}\n点击操作：{action_label}",
                    "jumpUrl": url,
                }
            },
            "prompt": f"[{tag}] {title[:40]}",
            "ver": "0.0.0.1",
            "view": "news",
        }

    def render(self, envelope: MessageEnvelope, *, mention_qq: str | None = None) -> Message:
        if envelope.card_payload is None:
            raise ValueError("MessageEnvelope does not contain a card payload.")
        message = Message()
        if mention_qq:
            message += MessageSegment.at(int(mention_qq))
            message += MessageSegment.text("\n")
        message += MessageSegment.json(json.dumps(envelope.card_payload, ensure_ascii=False))
        return message


class MessageDeliveryService:
    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService,
        plain_text_renderer: PlainTextRenderer,
        napcat_card_renderer: NapCatCardRenderer,
    ) -> None:
        self._runtime_config = runtime_config
        self._plain_text_renderer = plain_text_renderer
        self._napcat_card_renderer = napcat_card_renderer

    def can_send_card(self, envelope: MessageEnvelope) -> bool:
        return (
            self._runtime_config.render_mode() == "hybrid"
            and self._runtime_config.enable_task_cards()
            and bool(self._runtime_config.public_base_url())
            and envelope.card_payload is not None
        )

    async def send_group_envelope(
        self,
        *,
        bots: list,
        group_id: str,
        envelope: MessageEnvelope,
        mention_qq: str | None = None,
    ) -> None:
        if self.can_send_card(envelope):
            try:
                message = self._napcat_card_renderer.render(envelope, mention_qq=mention_qq)
                await self._send_message(bots=bots, group_id=group_id, message=message)
                return
            except Exception:
                if not self._runtime_config.card_fallback_to_text():
                    raise
        text_message = self._plain_text_renderer.render(envelope, mention_qq=mention_qq)
        await self._send_message(bots=bots, group_id=group_id, message=text_message)

    async def reply_group_envelope(
        self,
        *,
        bot,
        group_id: str,
        envelope: MessageEnvelope,
        mention_qq: str | None = None,
    ) -> None:
        await self.send_group_envelope(
            bots=[bot],
            group_id=group_id,
            envelope=envelope,
            mention_qq=mention_qq,
        )

    async def _send_message(self, *, bots: list, group_id: str, message) -> None:
        last_error: Exception | None = None
        for bot in bots:
            try:
                await bot.send_group_msg(group_id=int(group_id), message=message)
                return
            except Exception as exc:  # pragma: no cover - only used in live integrations
                last_error = exc
        if last_error is not None:
            raise last_error
