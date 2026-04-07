from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    ListMessageRequest,
)

from src.domain.value_objects.messaging import CardDocument, MessageEnvelope
from src.infrastructure.channels.base import ChannelAdapter, DeliveryResult, MessageContext

logger = logging.getLogger(__name__)


class FeishuChannel(ChannelAdapter):
    def __init__(self, *, app_id: str, app_secret: str) -> None:
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

    @property
    def channel_name(self) -> str:
        return "feishu"

    @property
    def client(self) -> lark.Client:
        return self._client

    async def send_text(self, chat_id: str, text: str, *, mention_user: str | None = None) -> DeliveryResult:
        if mention_user:
            text = f"<at user_id=\"{mention_user}\">{mention_user}</at>\n{text}"
        content = {"text": text}
        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps(content))
                .build()
            )
            .build()
        )
        response = self._client.im.v1.message.create(request)
        if not response.success():
            logger.error("feishu send_text failed: code=%s msg=%s", response.code, response.msg)
            return DeliveryResult(delivery_mode="text", success=False)
        return DeliveryResult(delivery_mode="text", success=True)

    async def send_envelope(
        self,
        chat_id: str,
        envelope: MessageEnvelope,
        *,
        mention_user: str | None = None,
    ) -> DeliveryResult:
        if envelope.card_document is not None:
            try:
                if mention_user:
                    await self.send_text(chat_id, "请查看今天的学习卡片。", mention_user=mention_user)
                card_json = self._render_card_document(envelope.card_document)
                request = (
                    CreateMessageRequest.builder()
                    .receive_id_type("chat_id")
                    .request_body(
                        CreateMessageRequestBody.builder()
                        .receive_id(chat_id)
                        .msg_type("interactive")
                        .content(json.dumps(card_json))
                        .build()
                    )
                    .build()
                )
                response = self._client.im.v1.message.create(request)
                if response.success():
                    return DeliveryResult(delivery_mode="card", success=True)
                logger.warning("feishu card send failed, falling back to text: %s", response.msg)
            except Exception:
                logger.exception("feishu card render failed, falling back to text")

        text = envelope.delivery_text()
        return await self.send_text(chat_id, text, mention_user=mention_user)

    async def get_chat_messages(self, chat_id: str, since: datetime, limit: int = 50) -> list[MessageContext]:
        start_time = str(int(since.timestamp()))
        request = (
            ListMessageRequest.builder()
            .container_id_type("chat")
            .container_id(chat_id)
            .start_time(start_time)
            .page_size(limit)
            .build()
        )
        response = self._client.im.v1.message.list(request)
        if not response.success():
            logger.error("feishu get_chat_messages failed: code=%s msg=%s", response.code, response.msg)
            return []

        results: list[MessageContext] = []
        items = response.data.items if response.data and response.data.items else []
        for item in items:
            text = ""
            if item.body and item.body.content:
                try:
                    obj = json.loads(item.body.content)
                    text = obj.get("text", "")
                except (json.JSONDecodeError, TypeError):
                    text = str(item.body.content)
            sender_id = item.sender.id if item.sender else ""
            nickname = item.sender.name if item.sender and hasattr(item.sender, "name") else ""
            results.append(
                MessageContext(
                    raw_event_id=item.message_id or "",
                    chat_id=chat_id,
                    chat_name="",
                    user_id=sender_id or "",
                    nickname=nickname or "",
                    message_text=text,
                    is_mention_bot=False,
                    platform="feishu",
                )
            )
        return results

    def _render_card_document(self, doc: CardDocument) -> dict:
        """将 CardDocument 渲染为飞书互动卡片 JSON。"""
        elements: list[dict] = []

        # 副标题
        if doc.subtitle:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{doc.subtitle}**"},
            })

        for section in doc.sections:
            elements.append({"tag": "hr"})
            if section.title:
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{section.title}**"},
                })
            for line in section.lines:
                # 截断过长行（飞书卡片单元素限制 30000 字符）
                safe_line = line[:3000] if len(line) > 3000 else line
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": safe_line},
                })

        # 页脚
        if doc.footer_lines:
            elements.append({"tag": "hr"})
            note_elements = [
                {"tag": "plain_text", "content": line}
                for line in doc.footer_lines
            ]
            elements.append({"tag": "note", "elements": note_elements})

        header = {
            "template": {"blue": "blue", "green": "green", "amber": "orange"}.get(doc.theme, "blue"),
            "title": {"tag": "plain_text", "content": doc.title},
            "subtitle": {"tag": "plain_text", "content": "English Learning Bot"},
        }

        return {
            "config": {"wide_screen_mode": True},
            "header": header,
            "elements": elements,
        }
