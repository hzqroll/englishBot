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
                if envelope.card_type == "daily_lesson":
                    card_json = self._render_task_card(envelope.card_document)
                else:
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
        results: list[MessageContext] = []
        page_token: str | None = None

        while True:
            builder = (
                ListMessageRequest.builder()
                .container_id_type("chat")
                .container_id(chat_id)
                .start_time(start_time)
                .page_size(limit)
            )
            if page_token:
                builder = builder.page_token(page_token)
            response = self._client.im.v1.message.list(builder.build())
            if not response.success():
                logger.error("feishu get_chat_messages failed: code=%s msg=%s", response.code, response.msg)
                break

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

            if not response.data.has_more:
                break
            page_token = response.data.page_token

        return results

    def _render_card_document(self, doc: CardDocument) -> dict:
        """将 CardDocument 渲染为飞书互动卡片 JSON 2.0。"""
        elements: list[dict] = []

        # 副标题
        if doc.subtitle:
            elements.append({"tag": "markdown", "content": f"**{doc.subtitle}**"})

        for section in doc.sections:
            elements.append({"tag": "hr"})
            if section.title:
                elements.append({"tag": "markdown", "content": f"**{section.title}**"})
            for line in section.lines:
                safe_line = line[:3000] if len(line) > 3000 else line
                elements.append({"tag": "markdown", "content": safe_line})

        # 页脚
        if doc.footer_lines:
            elements.append({"tag": "hr"})
            for line in doc.footer_lines:
                elements.append({"tag": "markdown", "content": f"<font color='grey'>{line}</font>"})

        header = {
            "template": {"blue": "blue", "green": "green", "amber": "orange"}.get(doc.theme, "blue"),
            "title": {"tag": "plain_text", "content": doc.title},
            "subtitle": {"tag": "plain_text", "content": "English Learning Bot"},
        }

        return {
            "schema": "2.0",
            "header": {**header, "padding": "12px 12px 12px 12px"},
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": elements,
            },
        }

    # ---- 每日任务专用渲染 ----

    @staticmethod
    def _compact_vocab_line(line: str) -> str:
        """将词汇 4 行格式压缩为 2 行紧凑 markdown。"""
        parts = line.split("\n")
        if len(parts) < 4:
            return line
        word_phonetic = parts[0].strip()
        meaning = parts[1].strip()
        scene = parts[2].replace("场景：", "").strip()
        example = parts[3].replace("例句：", "").strip()
        return (
            f"🔤 **{word_phonetic}** — {meaning}\n"
            f"> 🎯 场景：{scene} | 📝 例句：{example}"
        )

    @staticmethod
    def _collapsible_panel(
        *,
        title: str,
        elements: list[dict],
        expanded: bool = False,
    ) -> dict:
        """构建 JSON 2.0 折叠面板。"""
        return {
            "tag": "collapsible_panel",
            "expanded": expanded,
            "header": {
                "title": {"tag": "markdown", "content": title},
                "vertical_align": "center",
                "icon": {
                    "tag": "standard_icon",
                    "token": "down-small-ccm_outlined",
                    "size": "16px 16px",
                },
                "icon_position": "right",
                "icon_expanded_angle": -180,
            },
            "border": {"color": "grey", "corner_radius": "5px"},
            "vertical_spacing": "8px",
            "padding": "8px",
            "elements": elements,
        }

    def _render_task_card(self, doc: CardDocument) -> dict:
        """将每日任务 CardDocument 渲染为紧凑的飞书互动卡片 JSON 2.0。"""
        elements: list[dict] = []

        # 副标题
        if doc.subtitle:
            elements.append({"tag": "markdown", "content": f"**{doc.subtitle}**"})

        # 收集任务 section，最后合并
        task_sections: list[tuple[str, list[str]]] = []

        for section in doc.sections:
            title = section.title or ""

            # 昨日回顾 — 折叠
            if title == "昨日回顾":
                panel_elements = [
                    {"tag": "markdown", "content": line}
                    for line in section.lines
                ]
                if panel_elements:
                    elements.append(self._collapsible_panel(
                        title="**🔙 昨日回顾**",
                        elements=panel_elements,
                        expanded=False,
                    ))

            # 核心词块 — 展开，紧凑格式
            elif title == "核心词块":
                panel_elements = [
                    {"tag": "markdown", "content": self._compact_vocab_line(line)}
                    for line in section.lines
                ]
                if panel_elements:
                    elements.append(self._collapsible_panel(
                        title="**📚 核心词块**",
                        elements=panel_elements,
                        expanded=True,
                    ))

            # 支持词汇 — 折叠
            elif title == "支持词汇":
                panel_elements = [
                    {"tag": "markdown", "content": self._compact_vocab_line(line)}
                    for line in section.lines
                ]
                if panel_elements:
                    elements.append(self._collapsible_panel(
                        title="**📖 支持词汇**",
                        elements=panel_elements,
                        expanded=False,
                    ))

            # 情景对话 — 折叠
            elif "对话" in title:
                panel_elements = []
                for line in section.lines:
                    # 截断长对话，前 3 句 + 提示
                    sentences = line.replace("。", "。\n").replace("！", "！\n").replace("？", "？\n").split("\n")
                    sentences = [s.strip() for s in sentences if s.strip()]
                    if len(sentences) > 3:
                        preview = "\n".join(sentences[:3])
                        panel_elements.append({"tag": "markdown", "content": f"{preview}\n\n……\n📄 完整内容请查看飞书文档"})
                    else:
                        panel_elements.append({"tag": "markdown", "content": line})
                if panel_elements:
                    elements.append(self._collapsible_panel(
                        title=f"**💬 {title}**",
                        elements=panel_elements,
                        expanded=False,
                    ))

            # 任务 section — 收集后合并
            elif title.startswith("任务"):
                task_type = title.split("·", 1)[-1].strip() if "·" in title else title
                task_sections.append((task_type, section.lines))

            # 其他 section — 兜底展开
            else:
                elements.append({"tag": "markdown", "content": f"**{title}**"})
                for line in section.lines:
                    elements.append({"tag": "markdown", "content": line})

        # 合并所有任务为一个折叠面板
        if task_sections:
            merged_elements: list[dict] = []
            for i, (task_type, lines) in enumerate(task_sections, start=1):
                num_emoji = f"{i}\ufe0f\u20e3" if i <= 9 else f"{i}"
                prompt = lines[0] if lines else ""
                cmd = lines[1] if len(lines) > 1 else ""
                merged_elements.append({"tag": "markdown", "content": f"**{num_emoji} {task_type}** — {prompt}"})
                if cmd:
                    merged_elements.append({"tag": "markdown", "content": f"`{cmd}`"})
            elements.append(self._collapsible_panel(
                title="**✅ 今日任务**",
                elements=merged_elements,
                expanded=True,
            ))

        # 页脚
        if doc.footer_lines:
            elements.append({"tag": "hr"})
            for line in doc.footer_lines:
                elements.append({"tag": "markdown", "content": f"<font color='grey'>{line}</font>"})

        header = {
            "template": {"blue": "blue", "green": "green", "amber": "orange"}.get(doc.theme, "blue"),
            "title": {"tag": "plain_text", "content": doc.title},
            "subtitle": {"tag": "plain_text", "content": "English Learning Bot"},
        }

        return {
            "schema": "2.0",
            "header": {**header, "padding": "12px 12px 12px 12px"},
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": elements,
            },
        }
