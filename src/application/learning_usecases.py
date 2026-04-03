from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.domain.services.leveling import LearningEvidence, LevelService
from src.domain.services.review import ReviewScheduler
from src.domain.value_objects.learning import LessonBundle
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.providers.content_ted import TedContentProvider
from src.infrastructure.providers.llm_doubao import DoubaoProvider
from src.infrastructure.settings.runtime import RuntimeConfigService


@dataclass(slots=True)
class EnrollmentContext:
    qq_group_id: str
    group_name: str
    qq_user_id: str
    nickname: str


class LearningUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        level_service: LevelService,
        review_scheduler: ReviewScheduler,
        content_provider: TedContentProvider,
        feedback_provider: DoubaoProvider,
        points_per_task: int,
        points_per_review: int,
        runtime_config: RuntimeConfigService,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._level_service = level_service
        self._review_scheduler = review_scheduler
        self._content_provider = content_provider
        self._feedback_provider = feedback_provider
        self._points_per_task = points_per_task
        self._points_per_review = points_per_review
        self._runtime_config = runtime_config

    async def enroll(self, ctx: EnrollmentContext) -> str:
        group = await self._identity_repo.ensure_group(ctx.qq_group_id, ctx.group_name)
        user = await self._identity_repo.ensure_user(ctx.qq_user_id, ctx.nickname)
        await self._identity_repo.enroll_user(user.id, group.id)
        await self._learning_repo.upsert_user_level(
            user_id=user.id,
            group_id=group.id,
            current_level="beginner",
            evidence_json={"source": "enrollment_default"},
        )
        return "报名成功，已加入英语训练营。你现在可以使用“今日任务”“复习一下”“开始周测”等命令。"

    async def build_today_lesson(self, *, qq_group_id: str) -> LessonBundle:
        group = await self._identity_repo.ensure_group(qq_group_id)
        level = "beginner"
        bundle = await self._content_provider.build_lesson(level=level, biz_date=date.today())
        await self._learning_repo.upsert_content_and_lesson(group.id, bundle)
        return bundle

    async def get_today_task_message(self, *, qq_group_id: str) -> str:
        group = await self._identity_repo.ensure_group(qq_group_id)
        tasks = await self._learning_repo.get_today_tasks(group_id=group.id, biz_date=date.today())
        if not tasks:
            bundle = await self.build_today_lesson(qq_group_id=qq_group_id)
            tasks = await self._learning_repo.get_today_tasks(group_id=group.id, biz_date=bundle.biz_date)
            title = bundle.title
            transcript = bundle.transcript
        else:
            title = "今日任务"
            transcript = "今日任务已生成，可按任务编号提交。"

        task_lines = [
            f"{task.id}. [{task.task_type}] {task.prompt}"
            for task in tasks
        ]
        return (
            f"今日学习主题：{title}\n\n"
            f"材料节选：\n{transcript[:280]}...\n\n"
            f"任务清单：\n" + "\n".join(task_lines)
        )

    async def submit_task(
        self,
        *,
        qq_group_id: str,
        qq_user_id: str,
        nickname: str,
        task_id: int,
        content: str,
    ) -> str:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        enrolled = await self._identity_repo.is_enrolled(user.id, group.id)
        if not enrolled:
            return "你还没有报名学习，请先发送“报名学习”。"

        score = min(max(len(content.strip()) // 6, 1), 10) * 10
        feedback = await self._feedback_provider.generate_feedback(
            f"请用 2 句话评价以下英语学习任务提交，给出鼓励和一个改进建议：\n{content}"
        )
        await self._learning_repo.submit_task(
            task_id=task_id,
            user_id=user.id,
            submission_text=content,
            score=score,
            feedback=feedback,
        )
        await self._learning_repo.award_points(
            user_id=user.id,
            points=self._points_per_task,
            reason="daily_task",
        )
        return f"任务提交成功，得分 {score}。\n反馈：{feedback}"

    async def review_now(self, *, qq_group_id: str, qq_user_id: str, nickname: str, limit: int) -> str:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        enrolled = await self._identity_repo.is_enrolled(user.id, group.id)
        if not enrolled:
            return "你还没有报名学习，请先发送“报名学习”。"

        items = await self._learning_repo.get_due_review_items(user_id=user.id, limit=limit)
        if not items:
            return "当前没有到期的复习项，可以先完成今日任务。"

        lines = [
            f"- 复习项 #{item.id}，来源：{item.source_type}，当前间隔：{item.interval_days} 天"
            for item in items
        ]
        await self._learning_repo.award_points(
            user_id=user.id,
            points=self._points_per_review,
            reason="review_session",
        )
        return "以下是当前到期复习项：\n" + "\n".join(lines)

    async def refresh_user_level(self, *, qq_group_id: str, qq_user_id: str, nickname: str) -> str:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        evidence = LearningEvidence(
            translation_count=6,
            correction_count=6,
            task_completion_count=2,
            quiz_average_score=72,
        )
        level, payload = self._level_service.evaluate(evidence)
        await self._learning_repo.upsert_user_level(
            user_id=user.id,
            group_id=group.id,
            current_level=level,
            evidence_json=payload,
        )
        return f"当前等级：{level}。判定依据：{payload}"
