from __future__ import annotations

import logging
from datetime import date

from src.domain.value_objects.messaging import CardDocument, MessageEnvelope
from src.infrastructure.channels.feishu import FeishuChannel
from src.infrastructure.docs.feishu_docs_client import FeishuDocsClient
from src.infrastructure.docs.repository import FeishuDocsRepository

logger = logging.getLogger(__name__)


class FeishuDocsService:
    """管理飞书文档文件夹/周文档生命周期，并将 CardDocument 内容写入文档。"""

    def __init__(
        self,
        *,
        docs_client: FeishuDocsClient,
        docs_repo: FeishuDocsRepository,
        feishu_channel: FeishuChannel,
        folder_name: str,
        notify_chat_ids: list[str],
    ) -> None:
        self._client = docs_client
        self._repo = docs_repo
        self._channel = feishu_channel
        self._folder_name = folder_name
        self._notify_chat_ids = notify_chat_ids

    async def append_content(
        self,
        *,
        envelope: MessageEnvelope,
        card_type: str,
        target_date: date,
    ) -> None:
        """将消息内容追加到当周飞书文档。"""
        if envelope.card_document is None:
            return

        folder_token = await self._ensure_folder()
        document_id = await self._ensure_weekly_doc(folder_token, target_date)
        blocks = _card_document_to_blocks(envelope.card_document, card_type, target_date)

        if not blocks:
            return

        self._client.append_blocks(document_id=document_id, blocks=blocks)
        logger.info("feishu docs: appended %d blocks for %s/%s", len(blocks), card_type, target_date)

    # ------------------------------------------------------------------
    # folder / document lifecycle
    # ------------------------------------------------------------------

    async def _ensure_folder(self) -> str:
        token = await self._repo.get_value("feishu_docs.folder_token")
        if token:
            return token
        token = self._client.create_folder(name=self._folder_name)
        await self._repo.save_value("feishu_docs.folder_token", token)
        logger.info("feishu docs: created folder %s (token=%s)", self._folder_name, token)
        return token

    async def _ensure_weekly_doc(self, folder_token: str, target_date: date) -> str:
        week_key = _week_key(target_date)
        cache_key = f"feishu_docs.weekly_doc.{week_key}"
        doc_id = await self._repo.get_value(cache_key)
        if doc_id:
            return doc_id

        title = f"{week_key} 学习计划"
        doc_id = self._client.create_document(title=title, folder_token=folder_token)
        await self._repo.save_value(cache_key, doc_id)
        logger.info("feishu docs: created weekly doc %s (id=%s)", title, doc_id)

        # 通知群
        doc_url = f"https://bytedance.larkoffice.com/docx/{doc_id}"
        for chat_id in self._notify_chat_ids:
            try:
                await self._channel.send_text(chat_id, f"本周学习文档已创建：{doc_url}")
            except Exception:
                logger.exception("feishu docs: failed to notify chat %s", chat_id)

        return doc_id

    # ------------------------------------------------------------------
    # Friends per-episode document methods
    # ------------------------------------------------------------------

    async def append_friends_content(
        self,
        *,
        envelope: MessageEnvelope,
        season: int,
        episode: int,
        episode_title: str,
        target_date: date,
    ) -> str | None:
        """将 Friends 对话内容追加到按集文档中，返回文档 URL。"""
        if envelope.card_document is None:
            return None

        folder_token = await self._ensure_friends_folder()
        document_id = await self._ensure_episode_doc(folder_token, season, episode, episode_title)
        doc_url = f"https://bytedance.larkoffice.com/docx/{document_id}"

        blocks = _card_document_to_blocks(envelope.card_document, "friends_dialogue", target_date)
        if blocks:
            try:
                self._client.append_blocks(document_id=document_id, blocks=blocks)
                logger.info(
                    "feishu docs: appended %d blocks for friends S%02dE%02d",
                    len(blocks), season, episode,
                )
            except Exception:
                logger.exception("feishu docs: append_blocks failed for friends S%02dE%02d", season, episode)

        return doc_url

    async def _ensure_friends_folder(self) -> str:
        """确保 friends 根文件夹存在。"""
        token = await self._repo.get_value("feishu_docs.friends_folder_token")
        if token:
            return token
        token = self._client.create_folder(name="friends")
        await self._repo.save_value("feishu_docs.friends_folder_token", token)
        logger.info("feishu docs: created friends folder (token=%s)", token)
        return token

    async def _ensure_episode_doc(
        self, folder_token: str, season: int, episode: int, title: str,
    ) -> str:
        """确保单集文档存在。"""
        cache_key = f"feishu_docs.friends_doc.s{season:02d}e{episode:02d}"
        doc_id = await self._repo.get_value(cache_key)
        if doc_id:
            return doc_id

        doc_title = f"S{season:02d}E{episode:02d} - {title}"
        doc_id = self._client.create_document(title=doc_title, folder_token=folder_token)
        await self._repo.save_value(cache_key, doc_id)
        logger.info("feishu docs: created episode doc %s (id=%s)", doc_title, doc_id)

        return doc_id


# ------------------------------------------------------------------
# Block conversion helpers
# ------------------------------------------------------------------

_CARD_TYPE_LABELS: dict[str, str] = {
    "daily_lesson": "每日任务",
    "error_digest": "错误摘要",
    "progress": "学习进度",
    "weekly_report": "周报",
    "friends_dialogue": "Friends 对话",
}


def _week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _card_document_to_blocks(doc: CardDocument, card_type: str, target_date: date) -> list[dict]:
    """将 CardDocument 转换为飞书文档内容块列表。"""
    blocks: list[dict] = []

    label = _CARD_TYPE_LABELS.get(card_type, card_type)
    blocks.append(_text_block(f"== {target_date.isoformat()} {label} ==", bold=True))
    blocks.append(_divider_block())

    if doc.subtitle:
        blocks.append(_text_block(doc.subtitle, bold=True))

    for section in doc.sections:
        if section.title:
            blocks.append(_text_block(f"[ {section.title} ]", bold=True))
        for line in section.lines:
            blocks.append(_text_block(line))

    if doc.footer_lines:
        blocks.append(_divider_block())
        for line in doc.footer_lines:
            blocks.append(_text_block(line))

    blocks.append(_divider_block())
    return blocks


def _text_block(content: str, bold: bool = False) -> dict:
    style = {"bold": bold} if bold else {}
    return {
        "block_type": 2,
        "text": {
            "elements": [
                {"text_run": {"content": content, "text_element_style": style}}
            ]
        },
    }


def _divider_block() -> dict:
    return {"block_type": 22, "divider": {}}
