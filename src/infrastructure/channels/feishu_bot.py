from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import Future

import lark_oapi as lark
from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from src.application.conversation_usecases import ConversationContext
from src.application.message_intents import is_analysis_control_text
from src.application.message_usecases import MessageCommandContext
from src.infrastructure.channels.feishu import FeishuChannel
from src.infrastructure.settings.container import get_container
from src.plugins.command_catalog import is_fixed_command_text
from src.plugins.commands import handle_fixed_command_text

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
            if msg.message_type != "text":
                return

            content_obj = json.loads(msg.content) if msg.content else {}
            text = content_obj.get("text", "")

            # 去掉 @机器人 的占位符
            is_mention_bot = False
            if msg.mentions:
                for mention in msg.mentions:
                    text = text.replace(mention.key, "").strip()
                    is_mention_bot = True

            text = text.strip()
            if not text:
                return

            sender = data.event.sender
            user_id = sender.sender_id.open_id if sender and sender.sender_id and sender.sender_id.open_id else ""
            nickname = ""

            logger.info("feishu dispatching: chat_id=%s user=%s text=%r mention=%s", chat_id, user_id, text[:50], is_mention_bot)
            self._dispatch_sync(msg.message_id or "", chat_id, user_id, nickname, text, is_mention_bot)
        except Exception:
            logger.exception("feishu message handler failed")

    def _dispatch_sync(
        self,
        raw_event_id: str,
        chat_id: str,
        user_id: str,
        nickname: str,
        text: str,
        is_mention: bool,
    ) -> None:
        """将协程提交到 NoneBot2 主事件循环中执行。"""
        if self._main_loop is None or not self._main_loop.is_running():
            logger.error("feishu main loop unavailable, drop message chat_id=%s", chat_id)
            return
        try:
            future: Future = asyncio.run_coroutine_threadsafe(
                self._dispatch(raw_event_id, chat_id, user_id, nickname, text, is_mention),
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

        if is_fixed_command_text(text):
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
        elif is_analysis_control_text(text) or is_mention:
            # 分析指令 / @机器人 → 翻译/纠错/润色 (流式卡片输出)
            card_id: str | None = None
            sequence = 0
            last_update_time = 0.0

            def _on_chunk(accumulated: str) -> None:
                nonlocal card_id, sequence, last_update_time
                now = time.monotonic()
                if now - last_update_time < 0.2:  # throttle ~5 updates/sec
                    return
                if card_id is None:
                    # Lazy card creation — only when first chunk arrives
                    try:
                        card_id_sync = channel.create_streaming_card_sync(chat_id)
                        if card_id_sync:
                            card_id = card_id_sync
                    except Exception:
                        logger.exception("feishu streaming card create failed")
                        return
                if card_id is None:
                    return
                sequence += 1
                last_update_time = now
                try:
                    channel.update_streaming_card_sync(card_id, accumulated, sequence)
                except Exception:
                    logger.exception("feishu streaming card update failed seq=%s", sequence)

            reply = await container.message_usecase.handle_at_message(
                MessageCommandContext(
                    raw_event_id=raw_event_id,
                    group_id=chat_id,
                    group_name="",
                    user_id=user_id,
                    nickname=nickname,
                    message_text=text,
                ),
                stream_callback=_on_chunk,
            )

            if card_id is not None:
                sequence += 1
                try:
                    await channel.finalize_streaming_card(card_id, reply, sequence)
                except Exception:
                    logger.exception("feishu streaming card finalize failed")
                    await channel.send_text(chat_id, reply)
            else:
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
                )
            )
