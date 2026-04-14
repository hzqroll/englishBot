from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

import lark_oapi as lark
from lark_oapi.api.cardkit.v1 import (
    Card,
    CreateCardRequest,
    CreateCardRequestBody,
    UpdateCardRequest,
    UpdateCardRequestBody,
)
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
                card_json = self._render_envelope_card(envelope)
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

    def _render_envelope_card(self, envelope: MessageEnvelope) -> dict:
        doc = envelope.card_document
        assert doc is not None
        if envelope.card_snapshot_id is not None:
            doc.metadata = dict(doc.metadata or {})
            doc.metadata["card_snapshot_id"] = str(envelope.card_snapshot_id)
        if envelope.card_type == "daily_lesson":
            return self._render_task_card(doc)
        if envelope.card_type == "daily_session":
            return self._render_daily_session_card(doc)
        if envelope.card_type == "session_reminder":
            return self._render_session_reminder_card(doc)
        if envelope.card_type == "progress":
            return self._render_progress_card(doc)
        if envelope.card_type == "error_digest":
            return self._render_error_digest_card(doc)
        if envelope.card_type == "daily_summary":
            return self._render_daily_summary_card(doc)
        if envelope.card_type == "weekly_report":
            return self._render_weekly_report_card(doc)
        return self._render_card_document(doc)

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

    # ---- CardKit streaming card methods ----

    async def create_streaming_card(self, chat_id: str, *, title: str = "English Bot") -> str | None:
        """Create a CardKit card entity and send it as a message. Returns card_id or None."""
        try:
            return self._create_streaming_card_impl(chat_id, title)
        except Exception:
            logger.exception("create_streaming_card failed")
            return None

    def create_streaming_card_sync(self, chat_id: str, *, title: str = "English Bot") -> str | None:
        """Synchronous version of create_streaming_card for use in sync callbacks."""
        try:
            return self._create_streaming_card_impl(chat_id, title)
        except Exception:
            logger.exception("create_streaming_card_sync failed")
            return None

    def _create_streaming_card_impl(self, chat_id: str, title: str) -> str | None:
        card_data = json.dumps({
            "schema": "2.0",
            "config": {
                "update_multi": True,
                "streaming_mode": True,
                "summary": {"content": ""},
                "streaming_config": {
                    "print_frequency_ms": {"default": 50},
                    "print_step": {"default": 1},
                    "print_strategy": "fast",
                },
            },
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "body": {
                "elements": [{"tag": "markdown", "content": "🤔 正在思考...", "element_id": "streaming_text"}],
            },
        })
        card_request = (
            CreateCardRequest.builder()
            .request_body(
                CreateCardRequestBody.builder()
                .type("card_json")
                .data(card_data)
                .build()
            )
            .build()
        )
        card_response = self._client.cardkit.v1.card.create(card_request)
        if not card_response.success():
            logger.error("CardKit create failed: code=%s msg=%s", card_response.code, card_response.msg)
            return None

        card_id = card_response.data.card_id

        msg_request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(json.dumps({"type": "card", "data": {"card_id": card_id}}))
                .build()
            )
            .build()
        )
        msg_response = self._client.im.v1.message.create(msg_request)
        if not msg_response.success():
            logger.error("CardKit send message failed: code=%s msg=%s", msg_response.code, msg_response.msg)
            return None

        return card_id

    async def update_streaming_card(self, card_id: str, content: str, sequence: int) -> bool:
        """Update streaming card with partial content. Best-effort, logs errors."""
        return self._update_streaming_card_impl(card_id, content, sequence)

    def update_streaming_card_sync(self, card_id: str, content: str, sequence: int) -> bool:
        """Synchronous version for use in sync callbacks."""
        return self._update_streaming_card_impl(card_id, content, sequence)

    def _update_streaming_card_impl(self, card_id: str, content: str, sequence: int) -> bool:
        try:
            card_data = json.dumps({
                "schema": "2.0",
                "config": {"update_multi": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "English Bot"},
                    "template": "blue",
                },
                "body": {
                    "elements": [{"tag": "markdown", "content": content, "element_id": "streaming_text"}],
                },
            })
            request = (
                UpdateCardRequest.builder()
                .card_id(card_id)
                .request_body(
                    UpdateCardRequestBody.builder()
                    .card(Card.builder().type("card_json").data(card_data).build())
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = self._client.cardkit.v1.card.update(request)
            if not response.success():
                logger.warning("CardKit update failed: seq=%s code=%s msg=%s", sequence, response.code, response.msg)
                return False
            return True
        except Exception:
            logger.exception("update_streaming_card failed seq=%s", sequence)
            return False

    async def finalize_streaming_card(self, card_id: str, reply: str, sequence: int) -> bool:
        """Replace streaming card with final formatted result."""
        # Split the reply into markdown-friendly sections
        elements: list[dict] = []
        for line in reply.split("\n"):
            line = line.strip()
            if line:
                elements.append({"tag": "markdown", "content": line})

        try:
            card_data = json.dumps({
                "schema": "2.0",
                "config": {"update_multi": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "English Bot"},
                    "template": "blue",
                },
                "body": {
                    "elements": elements or [{"tag": "markdown", "content": reply, "element_id": "streaming_text"}],
                },
            })
            request = (
                UpdateCardRequest.builder()
                .card_id(card_id)
                .request_body(
                    UpdateCardRequestBody.builder()
                    .card(Card.builder().type("card_json").data(card_data).build())
                    .sequence(sequence)
                    .build()
                )
                .build()
            )
            response = self._client.cardkit.v1.card.update(request)
            if not response.success():
                logger.error("CardKit finalize failed: code=%s msg=%s", response.code, response.msg)
                return False
            return True
        except Exception:
            logger.exception("finalize_streaming_card failed")
            return False

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
            "subtitle": {"tag": "plain_text", "content": "B2 Sprint"},
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

    @staticmethod
    def _build_header(doc: CardDocument) -> dict:
        return {
            "template": {"blue": "blue", "green": "green", "amber": "orange"}.get(doc.theme, "blue"),
            "title": {"tag": "plain_text", "content": doc.title},
            "subtitle": {"tag": "plain_text", "content": "B2 Sprint"},
            "padding": "12px 12px 12px 12px",
        }

    @staticmethod
    def _markdown(text: str) -> dict:
        return {"tag": "markdown", "content": text}

    @staticmethod
    def _action_value(doc: CardDocument, action: str) -> dict[str, str]:
        value = dict(doc.metadata or {})
        value["action"] = action
        return value

    def _button(self, *, label: str, action: str, doc: CardDocument, button_type: str = "default") -> dict:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": button_type,
            "value": self._action_value(doc, action),
        }

    def _actions_bar(self, actions: list[dict]) -> dict:
        columns = [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [action],
                "vertical_align": "top",
            }
            for action in actions
        ]
        return {
            "tag": "column_set",
            "horizontal_spacing": "8px",
            "horizontal_align": "left",
            "columns": columns,
        }

    def _section_panel(
        self,
        *,
        title: str,
        lines: list[str],
        expanded: bool = True,
    ) -> dict:
        return self._collapsible_panel(
            title=f"**{title}**",
            elements=[self._markdown(line) for line in lines],
            expanded=expanded,
        )

    @staticmethod
    def _find_section(doc: CardDocument, title: str) -> CardSection | None:
        for section in doc.sections:
            if section.title == title:
                return section
        return None

    def _render_daily_session_card(self, doc: CardDocument) -> dict:
        goal = self._find_section(doc, "今日目标")
        roles = self._find_section(doc, "今日角色")
        reuse = self._find_section(doc, "必须复用")
        actions = self._find_section(doc, "今天动作")
        completion = self._find_section(doc, "完成标准")

        elements: list[dict] = []
        if doc.subtitle:
            elements.append(self._markdown(f"<font color='grey'>{doc.subtitle}</font>"))
        if goal or actions:
            hero_lines = []
            if goal:
                hero_lines.extend(goal.lines)
            if actions:
                hero_lines.append("")
                hero_lines.extend(actions.lines)
            elements.append(self._section_panel(title="今天先做这一轮", lines=hero_lines, expanded=True))
        if roles:
            elements.append(self._section_panel(title="角色分工", lines=roles.lines, expanded=True))
        if reuse:
            elements.append(self._section_panel(title="必须复用", lines=reuse.lines, expanded=True))
        if completion:
            elements.append(self._section_panel(title="完成标准", lines=completion.lines, expanded=False))
        elements.append(
            self._actions_bar(
                [
                    self._button(label="我先发起", action="claim_baton", doc=doc, button_type="primary"),
                    self._button(label="切到保底版", action="enter_rescue", doc=doc),
                    self._button(label="查看本周文档", action="open_week_doc", doc=doc),
                ]
            )
        )
        if doc.footer_lines:
            elements.append({"tag": "hr"})
            for line in doc.footer_lines:
                elements.append(self._markdown(f"<font color='grey'>{line}</font>"))
        return {
            "schema": "2.0",
            "header": self._build_header(doc),
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": elements,
            },
        }

    def _render_session_reminder_card(self, doc: CardDocument) -> dict:
        current = doc.sections[0] if doc.sections else CardSection(title="现在该做什么", lines=[])
        elements: list[dict] = []
        if doc.subtitle:
            elements.append(self._markdown(f"<font color='grey'>{doc.subtitle}</font>"))
        elements.append(self._section_panel(title=current.title or "现在该做什么", lines=current.lines, expanded=True))
        elements.append(
            self._actions_bar(
                [
                    self._button(label="今晚再提醒我", action="remind_later", doc=doc),
                    self._button(label="查看本周文档", action="open_week_doc", doc=doc),
                ]
            )
        )
        if doc.footer_lines:
            for line in doc.footer_lines:
                elements.append(self._markdown(f"<font color='grey'>{line}</font>"))
        return {
            "schema": "2.0",
            "header": self._build_header(doc),
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": elements,
            },
        }

    def _render_progress_card(self, doc: CardDocument) -> dict:
        elements: list[dict] = []
        if doc.subtitle:
            elements.append(self._markdown(f"**{doc.subtitle}**"))
        for index, section in enumerate(doc.sections):
            elements.append(self._section_panel(title=section.title or f"区块 {index + 1}", lines=section.lines, expanded=True))
        elements.append(self._actions_bar([self._button(label="查看本周文档", action="open_week_doc", doc=doc)]))
        if doc.footer_lines:
            elements.append({"tag": "hr"})
            for line in doc.footer_lines:
                elements.append(self._markdown(f"<font color='grey'>{line}</font>"))
        return {
            "schema": "2.0",
            "header": self._build_header(doc),
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": elements,
            },
        }

    def _render_error_digest_card(self, doc: CardDocument) -> dict:
        elements: list[dict] = []
        if doc.subtitle:
            elements.append(self._markdown(f"<font color='grey'>{doc.subtitle}</font>"))
        for section in doc.sections:
            elements.append(self._section_panel(title=section.title or "", lines=section.lines, expanded=True))
        elements.append(self._actions_bar([self._button(label="查看本周文档", action="open_week_doc", doc=doc)]))
        if doc.footer_lines:
            elements.append({"tag": "hr"})
            for line in doc.footer_lines:
                elements.append(self._markdown(f"<font color='grey'>{line}</font>"))
        return {
            "schema": "2.0",
            "header": self._build_header(doc),
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": elements,
            },
        }

    def _render_weekly_report_card(self, doc: CardDocument) -> dict:
        elements: list[dict] = []
        if doc.subtitle:
            elements.append(self._markdown(f"<font color='grey'>{doc.subtitle}</font>"))
        for section in doc.sections:
            elements.append(self._section_panel(title=section.title or "", lines=section.lines, expanded=False))
        elements.append(self._actions_bar([self._button(label="查看本周文档", action="open_week_doc", doc=doc)]))
        if doc.footer_lines:
            elements.append({"tag": "hr"})
            for line in doc.footer_lines:
                elements.append(self._markdown(f"<font color='grey'>{line}</font>"))
        return {
            "schema": "2.0",
            "header": self._build_header(doc),
            "body": {
                "direction": "vertical",
                "padding": "12px 12px 12px 12px",
                "elements": elements,
            },
        }

    def _render_daily_summary_card(self, doc: CardDocument) -> dict:
        elements: list[dict] = []
        if doc.subtitle:
            elements.append(self._markdown(f"<font color='grey'>{doc.subtitle}</font>"))
        for index, section in enumerate(doc.sections):
            expanded = index <= 1
            elements.append(self._section_panel(title=section.title or f"区块 {index + 1}", lines=section.lines, expanded=expanded))
        if doc.footer_lines:
            elements.append({"tag": "hr"})
            for line in doc.footer_lines:
                elements.append(self._markdown(f"<font color='grey'>{line}</font>"))
        return {
            "schema": "2.0",
            "header": self._build_header(doc),
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
            "subtitle": {"tag": "plain_text", "content": "B2 Sprint"},
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
