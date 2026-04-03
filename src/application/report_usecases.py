from __future__ import annotations

from datetime import UTC, datetime

from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.providers.llm_doubao import DoubaoProvider


class ReportUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        summary_provider: DoubaoProvider,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._summary_provider = summary_provider

    async def build_weekly_report(self, *, qq_group_id: str, qq_user_id: str, nickname: str) -> str:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        if not await self._identity_repo.is_enrolled(user.id, group.id):
            return "你还没有报名学习。"

        week_key = datetime.now(UTC).strftime("%G-W%V")
        summary_text = await self._summary_provider.generate_feedback(
            "请生成一句简洁的英语学习周报鼓励语。"
        )
        report_json = {
            "week_key": week_key,
            "task_completion_rate": 0.75,
            "correction_count": 8,
            "weak_points": ["preposition", "word_choice"],
            "level": "beginner",
        }
        await self._learning_repo.save_weekly_report(
            biz_week=week_key,
            user_id=user.id,
            report_json=report_json,
            summary_text=summary_text,
        )
        return (
            f"周报 {week_key}\n"
            f"- 本周完成率：75%\n"
            f"- 翻译/纠错次数：8\n"
            f"- 薄弱点：介词、词语搭配\n"
            f"- 总结：{summary_text}"
        )

