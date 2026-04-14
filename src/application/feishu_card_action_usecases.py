from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from src.infrastructure.docs.feishu_docs_client import FeishuDocsError


@dataclass(slots=True)
class FeishuCardActionResult:
    toast_type: str
    toast_content: str
    data: dict[str, Any] | None = None


async def handle_feishu_card_action(
    *,
    container,
    action: str,
    chat_id: str,
    actor_open_id: str,
    biz_date: date,
) -> FeishuCardActionResult:
    try:
        if action == "open_week_doc":
            if container.feishu_docs_service is None:
                return FeishuCardActionResult(
                    toast_type="info",
                    toast_content="飞书文档未启用",
                )
            doc_url = await container.feishu_docs_service.get_weekly_doc_url(target_date=biz_date)
            return FeishuCardActionResult(
                toast_type="success",
                toast_content="已准备本周文档",
                data={"doc_url": doc_url},
            )

        if container.daily_session_usecase is None:
            return FeishuCardActionResult(
                toast_type="warning",
                toast_content="当前环境未启用双人 session 能力",
            )

        if action == "claim_baton":
            message = await container.daily_session_usecase.claim_baton(
                chat_id=chat_id,
                actor_open_id=actor_open_id,
                biz_date=biz_date,
            )
            return FeishuCardActionResult(toast_type="success", toast_content=message)

        if action == "enter_rescue":
            message = await container.daily_session_usecase.enter_rescue_mode(
                chat_id=chat_id,
                actor_open_id=actor_open_id,
                biz_date=biz_date,
            )
            return FeishuCardActionResult(toast_type="success", toast_content=message)

        if action == "remind_later":
            message = await container.daily_session_usecase.remind_later(
                chat_id=chat_id,
                actor_open_id=actor_open_id,
                biz_date=biz_date,
            )
            return FeishuCardActionResult(toast_type="success", toast_content=message)

        return FeishuCardActionResult(
            toast_type="info",
            toast_content=f"未支持动作：{action}",
        )
    except FeishuDocsError as exc:
        error_text = str(exc)
        if "no folder permission" in error_text:
            return FeishuCardActionResult(
                toast_type="warning",
                toast_content="文档目录无权限，请给当前飞书应用开通该文件夹权限。",
            )
        return FeishuCardActionResult(
            toast_type="warning",
            toast_content="飞书文档暂不可用，请稍后重试。",
        )
    except Exception:
        return FeishuCardActionResult(
            toast_type="error",
            toast_content="处理失败，请稍后重试。",
        )
