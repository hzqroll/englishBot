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
    card_snapshot_id: int | None = None,
    target_open_id: str | None = None,
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

        copy_action_to_field = {
            "copy_goal_image_prompt": "今日目标图",
            "copy_summary_image_prompt": "今日学习总结图",
            "copy_passage_image_prompt": "练习短文图",
        }
        if action in copy_action_to_field:
            group = await container.identity_repo.ensure_group(chat_id)
            target_user_id: int | None = None
            if card_snapshot_id is not None and hasattr(container.learning_repo, "get_daily_card_snapshot_by_id"):
                card_snapshot = await container.learning_repo.get_daily_card_snapshot_by_id(card_snapshot_id)
                if card_snapshot is not None and card_snapshot.group_id == group.id and card_snapshot.user_id is not None:
                    target_user_id = card_snapshot.user_id
            if target_user_id is None and target_open_id:
                get_user_by_open_id = getattr(container.identity_repo, "get_user_by_open_id", None)
                if callable(get_user_by_open_id):
                    target_user = await get_user_by_open_id(target_open_id)
                else:
                    target_user = await container.identity_repo.ensure_user(target_open_id)
                if target_user is not None:
                    target_user_id = target_user.id
            if target_user_id is None:
                user = await container.identity_repo.ensure_user(actor_open_id)
                target_user_id = user.id
            snapshot = await container.learning_repo.get_daily_learning_snapshot(
                user_id=target_user_id,
                group_id=group.id,
                biz_date=biz_date,
            )
            if snapshot is None:
                return FeishuCardActionResult(
                    toast_type="warning",
                    toast_content="还没有可复制的提示词，请先等待每日总结生成。",
                )
            payload = dict(snapshot.summary_json or {}).get("xhs_payload", {})
            image_prompts = payload.get("图片生成提示词", {}) if isinstance(payload, dict) else {}
            prompt_field = copy_action_to_field[action]
            prompt_text = image_prompts.get(prompt_field, "") if isinstance(image_prompts, dict) else ""
            if not isinstance(prompt_text, str) or not prompt_text.strip():
                return FeishuCardActionResult(
                    toast_type="warning",
                    toast_content="提示词暂未生成，请稍后重试。",
                )
            channel = container.channels.get("feishu")
            if channel is None:
                return FeishuCardActionResult(
                    toast_type="warning",
                    toast_content="飞书通道不可用，无法发送提示词。",
                )
            await channel.send_text(chat_id=chat_id, text=prompt_text.strip(), mention_user=actor_open_id)
            return FeishuCardActionResult(
                toast_type="success",
                toast_content="已发送完整提示词，直接复制即可。",
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
