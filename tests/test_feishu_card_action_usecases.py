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
