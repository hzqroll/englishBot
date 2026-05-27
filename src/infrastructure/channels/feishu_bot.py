from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from datetime import date

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    CallBackToast,
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from src.application.conversation_usecases import ConversationContext
from src.application.feishu_card_action_usecases import FeishuCardActionResult, handle_feishu_card_action
from src.application.message_intents import is_analysis_control_text
from src.application.message_usecases import MessageCommandContext
from src.infrastructure.channels.feishu import FeishuChannel
from src.infrastructure.settings.container import get_container
from src.plugins.command_catalog import is_fixed_command_text
from src.plugins.command_handlers import handle_fixed_command_text

logger = logging.getLogger(__name__)


class FeishuBot:
    """飞书机器人入口：接收 WebSocket 事件，路由到业务逻辑。"""

    def __init__(self, *, app_id: str, app_secret: str, enabled_chat_ids: list[str] | None = None) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._enabled_chat_ids = set(enabled_chat_ids) if enabled_chat_ids else None
        self._main_loop: asyncio.AbstractEventLoop | None = None
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

    def start(self) -> None:
        """在后台守护线程中启动飞书 WebSocket 客户端。"""
        self._main_loop = asyncio.get_running_loop()
        event_handler = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._on_message)
            .register_p2_card_action_trigger(self._on_card_action_trigger)
            .build()
        )
        ws_client = lark.ws.Client(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=event_handler,
            log_level=lark.LogLevel.DEBUG,
        )
        thread = threading.Thread(target=ws_client.start, daemon=True, name="feishu-ws")
        thread.start()
        logger.info("feishu bot started")

    def _on_message(self, data: P2ImMessageReceiveV1) -> None:
        try:
            msg = data.event.message
            logger.info("feishu _on_message: chat_type=%s message_type=%s chat_id=%s", msg.chat_type, msg.message_type, msg.chat_id)
            if msg.chat_type != "group":
                return
            chat_id = msg.chat_id or ""
            if self._enabled_chat_ids and chat_id not in self._enabled_chat_ids:
                logger.info("feishu ignore message from disabled chat_id=%s", chat_id)
                return
            content_obj = json.loads(msg.content) if msg.content else {}
            text = content_obj.get("text", "") if msg.message_type == "text" else ""

            # 去掉 @机器人 的占位符
            is_mention_bot = False
            if msg.mentions:
                for mention in msg.mentions:
                    text = text.replace(mention.key, "").strip()
                    is_mention_bot = True

            text = text.strip()
            if msg.message_type == "text" and not text:
                return

            sender = data.event.sender
            user_id = sender.sender_id.open_id if sender and sender.sender_id and sender.sender_id.open_id else ""
            nickname = ""

            logger.info("feishu dispatching: chat_id=%s user=%s text=%r mention=%s", chat_id, user_id, text[:50], is_mention_bot)
            self._dispatch_sync(
                msg.message_id or "",
                chat_id,
                user_id,
                nickname,
                text,
                is_mention_bot,
                msg.message_type,
            )
        except Exception:
            logger.exception("feishu message handler failed")

    def _on_card_action_trigger(self, data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        try:
            event = data.event
            action_value = {}
            if event is not None and event.action is not None and isinstance(event.action.value, dict):
                action_value = dict(event.action.value)
            action = action_value.get("action")
            if not isinstance(action, str) or not action:
                return self._build_card_action_response("warning", "未识别卡片动作")

            chat_id = str(action_value.get("chat_id") or "")
            if not chat_id and event is not None and event.context is not None and event.context.open_chat_id:
                chat_id = event.context.open_chat_id
            if not chat_id:
                return self._build_card_action_response("warning", "缺少 chat_id，上下文已过期")

            biz_date_raw = action_value.get("biz_date")
            try:
                biz_date = (
                    date.fromisoformat(biz_date_raw)
                    if isinstance(biz_date_raw, str) and biz_date_raw
                    else date.today()
                )
            except ValueError:
                biz_date = date.today()

            actor_open_id = "card-user"
            if event is not None and event.operator is not None and event.operator.open_id:
                actor_open_id = event.operator.open_id
            card_snapshot_raw = action_value.get("card_snapshot_id")
            card_snapshot_id: int | None = None
            if isinstance(card_snapshot_raw, int):
                card_snapshot_id = card_snapshot_raw
            elif isinstance(card_snapshot_raw, str) and card_snapshot_raw.isdigit():
                card_snapshot_id = int(card_snapshot_raw)
            target_open_id = action_value.get("target_open_id") if isinstance(action_value.get("target_open_id"), str) else None

            logger.info(
                "feishu card action trigger: action=%s chat_id=%s actor=%s",
                action,
                chat_id,
                actor_open_id,
            )
            return self._dispatch_card_action_sync(
                action=action,
                chat_id=chat_id,
                actor_open_id=actor_open_id,
                biz_date=biz_date,
                card_snapshot_id=card_snapshot_id,
                target_open_id=target_open_id,
            )
        except Exception:
            logger.exception("feishu card action handler failed")
            return self._build_card_action_response("error", "处理失败，请稍后重试")

    def _dispatch_card_action_sync(
        self,
        *,
        action: str,
        chat_id: str,
        actor_open_id: str,
        biz_date: date,
        card_snapshot_id: int | None = None,
        target_open_id: str | None = None,
    ) -> P2CardActionTriggerResponse:
        if self._main_loop is None or not self._main_loop.is_running():
            logger.error("feishu main loop unavailable, drop card action chat_id=%s", chat_id)
            return self._build_card_action_response("error", "服务尚未就绪，请稍后重试")
        try:
            future: Future = asyncio.run_coroutine_threadsafe(
                self._dispatch_card_action(
                    action=action,
                    chat_id=chat_id,
                    actor_open_id=actor_open_id,
                    biz_date=biz_date,
                    card_snapshot_id=card_snapshot_id,
                    target_open_id=target_open_id,
                ),
                self._main_loop,
            )
            result: FeishuCardActionResult = future.result(timeout=8)
            return self._build_card_action_response(result.toast_type, result.toast_content)
        except FutureTimeoutError:
            logger.exception("feishu card action dispatch timeout")
            return self._build_card_action_response("error", "处理超时，请稍后重试")
        except Exception:
            logger.exception("feishu card action dispatch failed")
            return self._build_card_action_response("error", "处理失败，请稍后重试")

    async def _dispatch_card_action(
        self,
        *,
        action: str,
        chat_id: str,
        actor_open_id: str,
        biz_date: date,
        card_snapshot_id: int | None = None,
        target_open_id: str | None = None,
    ) -> FeishuCardActionResult:
        container = get_container()
        if not container.runtime_config.is_feishu_enabled():
            return FeishuCardActionResult(toast_type="warning", toast_content="飞书通道未启用")
        if self._enabled_chat_ids and chat_id not in self._enabled_chat_ids:
            return FeishuCardActionResult(toast_type="warning", toast_content="当前群未启用机器人")
        if not container.runtime_config.is_enabled_chat(chat_id):
            return FeishuCardActionResult(toast_type="warning", toast_content="当前群未启用机器人")
        return await handle_feishu_card_action(
            container=container,
            action=action,
            chat_id=chat_id,
            actor_open_id=actor_open_id,
            biz_date=biz_date,
            card_snapshot_id=card_snapshot_id,
            target_open_id=target_open_id,
        )

    @staticmethod
    def _build_card_action_response(toast_type: str, toast_content: str) -> P2CardActionTriggerResponse:
        response = P2CardActionTriggerResponse()
        response.toast = CallBackToast(
            {
                "type": toast_type,
                "content": toast_content,
            }
        )
        return response

    def _dispatch_sync(
        self,
        raw_event_id: str,
        chat_id: str,
        user_id: str,
        nickname: str,
        text: str,
        is_mention: bool,
        message_type: str,
    ) -> None:
        """将协程提交到 NoneBot2 主事件循环中执行。"""
        if self._main_loop is None or not self._main_loop.is_running():
            logger.error("feishu main loop unavailable, drop message chat_id=%s", chat_id)
            return
        try:
            future: Future = asyncio.run_coroutine_threadsafe(
                self._dispatch(raw_event_id, chat_id, user_id, nickname, text, is_mention, message_type),
                self._main_loop,
            )
            future.add_done_callback(self._log_dispatch_failure)
        except Exception:
            logger.exception("feishu async dispatch failed")

    def _log_dispatch_failure(self, future: Future) -> None:
        try:
            future.result()
        except Exception:
            logger.exception("feishu dispatch task failed")

    async def _dispatch(
        self,
        raw_event_id: str,
        chat_id: str,
        user_id: str,
        nickname: str,
        text: str,
        is_mention: bool,
        message_type: str,
    ) -> None:
        container = get_container()
        if not container.runtime_config.is_feishu_enabled():
            return
        channel = container.channels.get("feishu")
        if channel is None or not isinstance(channel, FeishuChannel):
            logger.error("feishu channel not registered")
            return
        if self._enabled_chat_ids and chat_id not in self._enabled_chat_ids:
            logger.info("feishu ignore dispatch from disabled chat_id=%s", chat_id)
            return
        if not container.runtime_config.is_enabled_chat(chat_id):
            return

        if message_type == "text" and is_fixed_command_text(text):
            envelope = await handle_fixed_command_text(
                group_id=chat_id,
                group_name="",
                user_id=user_id,
                nickname=nickname,
                text=text,
                raw_event_id=raw_event_id,
                container=container,
            )
            await channel.send_envelope(chat_id, envelope)
        elif message_type == "text" and (is_analysis_control_text(text) or is_mention):
            # 分析指令 / @机器人 → 翻译/纠错/润色（仅发送最终结果）
            translation_enabled = container.runtime_config.is_message_translation_enabled()
            reply = await container.message_usecase.handle_at_message(
                MessageCommandContext(
                    raw_event_id=raw_event_id,
                    group_id=chat_id,
                    group_name="",
                    user_id=user_id,
                    nickname=nickname,
                    message_text=text,
                ),
                translation_enabled=translation_enabled,
            )
            if reply is None:
                return
            await channel.send_text(chat_id, reply)
            # 用户消息写入对话缓存（机器人回复不进入缓存）
            container.group_dialogue_store.append_group_message(
                group_id=chat_id, user_id=user_id, nickname=nickname, text=text,
            )
        else:
            # 被动消息观察
            await container.conversation_usecase.observe_passive_group_message(
                ConversationContext(
                    raw_event_id=raw_event_id,
                    group_id=chat_id,
                    group_name="",
                    user_id=user_id,
                    nickname=nickname,
                    message_text=text,
                    message_type=message_type,
                )
            )
