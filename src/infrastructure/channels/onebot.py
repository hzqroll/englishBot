from __future__ import annotations

from datetime import datetime

from nonebot import get_bots
from nonebot.adapters.onebot.v11 import Bot as OneBotBot
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from src.domain.value_objects.messaging import MessageEnvelope
from src.infrastructure.channels.base import ChannelAdapter, DeliveryResult, MessageContext
from src.infrastructure.messaging.renderers import ImageCardRenderer, PlainTextRenderer
from src.infrastructure.settings.runtime import RuntimeConfigService


class OneBotChannel(ChannelAdapter):
    def __init__(
        self,
        *,
        runtime_config: RuntimeConfigService,
        plain_text_renderer: PlainTextRenderer,
        image_card_renderer: ImageCardRenderer,
    ) -> None:
        self._runtime_config = runtime_config
        self._plain_text_renderer = plain_text_renderer
        self._image_card_renderer = image_card_renderer

    @property
    def channel_name(self) -> str:
        return "onebot"

    def _get_bots(self) -> list[OneBotBot]:
        return [b for b in get_bots().values() if isinstance(b, OneBotBot)]

    async def send_text(self, chat_id: str, text: str, *, mention_user: str | None = None) -> DeliveryResult:
        message = ""
        if mention_user:
            message += f"[CQ:at,qq={mention_user}]\n"
        message += text
        await self._raw_send(chat_id, message)
        return DeliveryResult(delivery_mode="text", success=True)

    async def send_envelope(
        self,
        chat_id: str,
        envelope: MessageEnvelope,
        *,
        mention_user: str | None = None,
    ) -> DeliveryResult:
        render_mode = self._runtime_config.render_mode_for_group(chat_id)
        if render_mode != "text" and self._runtime_config.enable_task_cards() and envelope.card_document is not None:
            try:
                pages = self._image_card_renderer.render_document(envelope.card_document)
                if len(pages) == 1:
                    msg = Message()
                    if mention_user:
                        msg += MessageSegment.at(int(mention_user))
                        msg += MessageSegment.text("\n")
                    msg += MessageSegment.image(self._image_card_renderer.image_data_uri(pages[0]))
                    await self._raw_send_message(chat_id, msg)
                    return DeliveryResult(delivery_mode="image_single", success=True, image_paths=[str(pages[0])])
                else:
                    if mention_user:
                        await self._raw_send(chat_id, f"[CQ:at,qq={mention_user}]\n你的内容较长，以下为分页卡片。")
                    try:
                        await self._send_forward_images(chat_id, envelope.card_document.title, pages)
                        return DeliveryResult(
                            delivery_mode="image_multi_page",
                            success=True,
                            image_paths=[str(p) for p in pages],
                        )
                    except Exception:
                        for page in pages:
                            msg = Message() + MessageSegment.image(self._image_card_renderer.image_data_uri(page))
                            await self._raw_send_message(chat_id, msg)
                        return DeliveryResult(
                            delivery_mode="image_single",
                            success=True,
                            image_paths=[str(p) for p in pages],
                        )
            except Exception:
                if not self._runtime_config.card_fallback_to_text():
                    raise

        text = self._plain_text_renderer.render(envelope, mention_qq=mention_user)
        await self._raw_send(chat_id, text)
        return DeliveryResult(delivery_mode="text", success=True)

    async def get_chat_messages(self, chat_id: str, since: datetime, limit: int = 50) -> list[MessageContext]:
        return []

    async def _raw_send(self, group_id: str, message: str) -> None:
        bots = self._get_bots()
        last_error: Exception | None = None
        for bot in bots:
            try:
                await bot.send_group_msg(group_id=int(group_id), message=message)
                return
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error

    async def _raw_send_message(self, group_id: str, message: Message) -> None:
        bots = self._get_bots()
        last_error: Exception | None = None
        for bot in bots:
            try:
                await bot.send_group_msg(group_id=int(group_id), message=message)
                return
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error

    async def _send_forward_images(self, group_id: str, title: str, image_paths: list) -> None:
        bots = self._get_bots()
        last_error: Exception | None = None
        for bot in bots:
            try:
                nodes = []
                bot_uin = str(getattr(bot, "self_id", "0"))
                for index, image_path in enumerate(image_paths, start=1):
                    content = [
                        {"type": "text", "data": {"text": f"{title}（第 {index} 页）\n"}},
                        {"type": "image", "data": {"file": self._image_card_renderer.image_data_uri(image_path)}},
                    ]
                    nodes.append({"type": "node", "data": {"name": "英语学习机器人", "uin": bot_uin, "content": content}})
                await bot.call_api("send_group_forward_msg", group_id=int(group_id), messages=nodes)
                return
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
