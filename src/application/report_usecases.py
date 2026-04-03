from __future__ import annotations

from datetime import UTC, datetime

from src.domain.services.leveling import LearningEvidence, LevelService
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider


class ReportUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        summary_provider: OpenAICompatibleProvider,
        level_service: LevelService,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._summary_provider = summary_provider
        self._level_service = level_service

    async def build_weekly_report(self, *, qq_group_id: str, qq_user_id: str, nickname: str) -> str:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        if not await self._identity_repo.is_enrolled(user.id, group.id):
            return "你还没有报名学习。"

        week_key = datetime.now(UTC).strftime("%G-W%V")
        stats = await self._learning_repo.get_weekly_report_stats(
            user_id=user.id,
            group_id=group.id,
        )
        evidence = LearningEvidence(
            translation_count=stats["translation_count"],
            correction_count=stats["correction_count"],
            task_completion_count=stats["task_completion_count"],
            quiz_average_score=stats["quiz_average_score"],
        )
        level, evidence_json = self._level_service.evaluate(evidence)
        await self._learning_repo.upsert_user_level(
            user_id=user.id,
            group_id=group.id,
            current_level=level,
            evidence_json=evidence_json,
        )
        top_fragments = await self._learning_repo.list_top_error_fragments(
            user_id=user.id,
            group_id=group.id,
            limit=3,
        )
        weak_details = [
            f"{item.source_fragment} -> {item.correct_fragment}"
            for item in top_fragments
        ]
        summary_text = await self._summary_provider.generate_feedback(
            (
                "请生成一句简洁的英语学习周报鼓励语，语气积极，不超过 50 字。"
                f" 学习天数：{stats['learning_days']}，完成率：{stats['task_completion_rate']:.0%}，"
                f" 纠错次数：{stats['correction_count']}，当前等级：{level}。"
            )
        )
        report_json = {
            "week_key": week_key,
            "learning_days": stats["learning_days"],
            "task_completion_rate": stats["task_completion_rate"],
            "translation_count": stats["translation_count"],
            "correction_count": stats["correction_count"],
            "task_completion_count": stats["task_completion_count"],
            "quiz_average_score": stats["quiz_average_score"],
            "latest_quiz_score": stats["latest_quiz_score"],
            "weak_points": stats["weak_points"],
            "weak_details": weak_details,
            "points_earned": stats["points_earned"],
            "current_streak": stats["current_streak"],
            "level": level,
        }
        await self._learning_repo.save_weekly_report(
            biz_week=week_key,
            user_id=user.id,
            report_json=report_json,
            summary_text=summary_text,
        )
        weak_points = "、".join(self._label_error_type(item) for item in stats["weak_points"]) or "暂无明显高频薄弱项"
        weak_examples = "；".join(weak_details) or "本周没有沉淀新的典型错误片段。"
        level_label = "初级" if level == "beginner" else "中级"
        return (
            f"周报 {week_key}\n"
            f"- 学习天数：{stats['learning_days']} 天\n"
            f"- 本周完成率：{stats['task_completion_rate']:.0%}\n"
            f"- 翻译/纠错次数：{stats['translation_count']}/{stats['correction_count']}\n"
            f"- 周测平均分：{stats['quiz_average_score']:.1f}，最近一次：{stats['latest_quiz_score']}\n"
            f"- 当前等级：{level_label}（{level}）\n"
            f"- 连续学习：{stats['current_streak']} 天，累计积分：{stats['points_earned']}\n"
            f"- 薄弱点：{weak_points}\n"
            f"- 典型错误：{weak_examples}\n"
            f"- 总结：{summary_text}"
        )

    def _label_error_type(self, error_type: str) -> str:
        labels = {
            "tense": "时态",
            "preposition": "介词",
            "article": "冠词",
            "plural": "单复数",
            "spelling": "拼写",
            "word_choice": "词语搭配",
            "agreement": "主谓一致",
            "natural_expression": "表达自然度",
        }
        return labels.get(error_type, error_type)
