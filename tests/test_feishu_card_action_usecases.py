from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.application.feishu_card_action_usecases import handle_feishu_card_action
from src.infrastructure.docs.feishu_docs_client import FeishuDocsError


@pytest.mark.asyncio
async def test_open_week_doc_returns_success_when_docs_service_ready() -> None:
    async def _get_weekly_doc_url(*, target_date):
        assert target_date == date(2026, 4, 13)
        return "https://bytedance.larkoffice.com/docx/abc123"

    container = SimpleNamespace(
        feishu_docs_service=SimpleNamespace(get_weekly_doc_url=_get_weekly_doc_url),
        daily_session_usecase=None,
    )

    result = await handle_feishu_card_action(
        container=container,
        action="open_week_doc",
        chat_id="oc_test",
        actor_open_id="u-test",
        biz_date=date(2026, 4, 13),
    )

    assert result.toast_type == "success"
    assert result.data == {"doc_url": "https://bytedance.larkoffice.com/docx/abc123"}


@pytest.mark.asyncio
async def test_open_week_doc_returns_permission_hint_when_folder_forbidden() -> None:
    async def _get_weekly_doc_url(*, target_date):
        raise FeishuDocsError("create_document failed: code=1770040 msg=no folder permission")

    container = SimpleNamespace(
        feishu_docs_service=SimpleNamespace(get_weekly_doc_url=_get_weekly_doc_url),
        daily_session_usecase=None,
    )

    result = await handle_feishu_card_action(
        container=container,
        action="open_week_doc",
        chat_id="oc_test",
        actor_open_id="u-test",
        biz_date=date(2026, 4, 13),
    )

    assert result.toast_type == "warning"
    assert "文档目录无权限" in result.toast_content


@pytest.mark.asyncio
async def test_open_week_doc_returns_docs_unavailable_on_generic_docs_error() -> None:
    async def _get_weekly_doc_url(*, target_date):
        raise FeishuDocsError("create_document failed: code=123 msg=unknown")

    container = SimpleNamespace(
        feishu_docs_service=SimpleNamespace(get_weekly_doc_url=_get_weekly_doc_url),
        daily_session_usecase=None,
    )

    result = await handle_feishu_card_action(
        container=container,
        action="open_week_doc",
        chat_id="oc_test",
        actor_open_id="u-test",
        biz_date=date(2026, 4, 13),
    )

    assert result.toast_type == "warning"
    assert "飞书文档暂不可用" in result.toast_content


@pytest.mark.asyncio
async def test_copy_image_prompt_action_sends_prompt_text() -> None:
    sent: list[tuple[str, str, str | None]] = []

    class _ChannelStub:
        async def send_text(self, chat_id: str, text: str, *, mention_user: str | None = None):
            sent.append((chat_id, text, mention_user))

    async def _ensure_group(chat_id: str):
        return SimpleNamespace(id=10, chat_id=chat_id)

    async def _ensure_user(open_id: str, nickname: str = ""):
        return SimpleNamespace(id=20, open_id=open_id, nickname=nickname)

    async def _get_daily_learning_snapshot(*, user_id: int, group_id: int, biz_date):
        return SimpleNamespace(
            summary_json={
                "xhs_payload": {
                    "图片生成提示词": {
                        "今日目标图": "goal prompt",
                        "今日学习总结图": "summary prompt",
                        "练习短文图": "passage prompt",
                    }
                }
            }
        )

    container = SimpleNamespace(
        feishu_docs_service=None,
        daily_session_usecase=None,
        identity_repo=SimpleNamespace(ensure_group=_ensure_group, ensure_user=_ensure_user),
        learning_repo=SimpleNamespace(get_daily_learning_snapshot=_get_daily_learning_snapshot),
        channels={"feishu": _ChannelStub()},
    )

    result = await handle_feishu_card_action(
        container=container,
        action="copy_goal_image_prompt",
        chat_id="oc_test",
        actor_open_id="u-test",
        biz_date=date(2026, 4, 13),
    )

    assert result.toast_type == "success"
    assert "已发送完整提示词" in result.toast_content
    assert sent == [("oc_test", "goal prompt", "u-test")]


@pytest.mark.asyncio
async def test_copy_image_prompt_uses_card_snapshot_owner_when_actor_differs() -> None:
    sent: list[tuple[str, str, str | None]] = []
    snapshot_user_ids: list[int] = []

    class _ChannelStub:
        async def send_text(self, chat_id: str, text: str, *, mention_user: str | None = None):
            sent.append((chat_id, text, mention_user))

    async def _ensure_group(chat_id: str):
        return SimpleNamespace(id=10, chat_id=chat_id)

    async def _ensure_user(open_id: str, nickname: str = ""):
        return SimpleNamespace(id=99, open_id=open_id, nickname=nickname)

    async def _get_daily_card_snapshot_by_id(snapshot_id: int):
        assert snapshot_id == 321
        return SimpleNamespace(id=snapshot_id, group_id=10, user_id=20)

    async def _get_daily_learning_snapshot(*, user_id: int, group_id: int, biz_date):
        snapshot_user_ids.append(user_id)
        return SimpleNamespace(
            summary_json={
                "xhs_payload": {
                    "图片生成提示词": {
                        "今日目标图": "goal prompt from owner",
                    }
                }
            }
        )

    container = SimpleNamespace(
        feishu_docs_service=None,
        daily_session_usecase=None,
        identity_repo=SimpleNamespace(ensure_group=_ensure_group, ensure_user=_ensure_user),
        learning_repo=SimpleNamespace(
            get_daily_card_snapshot_by_id=_get_daily_card_snapshot_by_id,
            get_daily_learning_snapshot=_get_daily_learning_snapshot,
        ),
        channels={"feishu": _ChannelStub()},
    )

    result = await handle_feishu_card_action(
        container=container,
        action="copy_goal_image_prompt",
        chat_id="oc_test",
        actor_open_id="u-clicker",
        biz_date=date(2026, 4, 13),
        card_snapshot_id=321,
    )

    assert result.toast_type == "success"
    assert snapshot_user_ids == [20]
    assert sent == [("oc_test", "goal prompt from owner", "u-clicker")]
