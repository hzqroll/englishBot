from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from src.domain.services.leveling import LearningEvidence, LevelService
from src.domain.services.review import ReviewScheduler
from src.domain.value_objects.learning import LessonBundle
from src.domain.value_objects.messaging import MessageEnvelope
from src.infrastructure.auth.card_links import CardLinkSigner
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.messaging.renderers import NapCatCardRenderer
from src.infrastructure.providers.content_ted import TedContentProvider
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider
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
        feedback_provider: OpenAICompatibleProvider,
        points_per_task: int,
        points_per_review: int,
        runtime_config: RuntimeConfigService,
        card_link_signer: CardLinkSigner,
        napcat_card_renderer: NapCatCardRenderer,
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
        self._card_link_signer = card_link_signer
        self._napcat_card_renderer = napcat_card_renderer

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
        lesson_detail, tasks = await self._ensure_today_task_detail(group.id, qq_group_id)
        lesson, content = lesson_detail
        task_lines = [
            f"{task.id}. [{task.task_type}] {task.prompt}"
            for task in tasks
        ]
        return (
            f"今日学习主题：{content.title}\n\n"
            f"材料节选：\n{content.transcript[:280]}...\n\n"
            f"任务清单：\n" + "\n".join(task_lines)
        )

    async def get_today_task_envelope(
        self,
        *,
        qq_group_id: str,
        qq_user_id: str,
        nickname: str,
        base_url_override: str | None = None,
    ) -> MessageEnvelope:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        enrolled = await self._identity_repo.is_enrolled(user.id, group.id)
        if not enrolled:
            return MessageEnvelope(plain_text="你还没有报名学习，请先发送“报名学习”。")

        lesson_detail, tasks = await self._ensure_today_task_detail(group.id, qq_group_id)
        lesson, content = lesson_detail
        plain_text = await self.get_today_task_message(qq_group_id=qq_group_id)
        card_link_url = self._build_card_link(
            resource_type="task",
            resource_id=str(lesson.id),
            qq_user_id=qq_user_id,
            qq_group_id=qq_group_id,
            base_url_override=base_url_override,
        )
        if not card_link_url:
            return MessageEnvelope(plain_text=plain_text)

        summary = f"{len(tasks)} 个任务，点击打开学习页并提交答案。"
        card_payload = self._napcat_card_renderer.build_click_card(
            title=content.title,
            summary=summary,
            url=card_link_url,
            action_label="打开任务页",
        )
        return MessageEnvelope(
            plain_text=plain_text,
            fallback_text=f"{plain_text}\n\n任务页：{card_link_url}",
            card_payload=card_payload,
            card_link_url=card_link_url,
            card_title=content.title,
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
        enrolled = await self._identity_repo.is_enrolled(user.id, group.id)
        if not enrolled:
            return "你还没有报名学习，请先发送“报名学习”。"

        evidence_payload = await self._learning_repo.get_learning_evidence(
            user_id=user.id,
            group_id=group.id,
        )
        evidence = LearningEvidence(
            translation_count=evidence_payload["translation_count"],
            correction_count=evidence_payload["correction_count"],
            task_completion_count=evidence_payload["task_completion_count"],
            quiz_average_score=evidence_payload["quiz_average_score"],
        )
        level, payload = self._level_service.evaluate(evidence)
        await self._learning_repo.upsert_user_level(
            user_id=user.id,
            group_id=group.id,
            current_level=level,
            evidence_json=payload,
        )
        level_label = "初级" if level == "beginner" else "中级"
        return (
            f"当前等级：{level_label}（{level}）\n"
            f"- 翻译次数：{evidence.translation_count}\n"
            f"- 纠错次数：{evidence.correction_count}\n"
            f"- 任务完成数：{evidence.task_completion_count}\n"
            f"- 周测平均分：{evidence.quiz_average_score:.1f}\n"
            f"- 活跃度评分：{payload['activity_score']}"
        )

    async def _ensure_today_task_detail(self, group_id: int, qq_group_id: str):
        lesson_detail = await self._learning_repo.get_today_lesson_detail(
            group_id=group_id,
            biz_date=date.today(),
        )
        if lesson_detail is None:
            bundle = await self.build_today_lesson(qq_group_id=qq_group_id)
            lesson_detail = await self._learning_repo.get_today_lesson_detail(
                group_id=group_id,
                biz_date=bundle.biz_date,
            )
            if lesson_detail is None:
                raise ValueError("今日任务生成失败。")
        tasks = await self._learning_repo.get_tasks_for_lesson(lesson_id=lesson_detail[0].id)
        return lesson_detail, tasks

    def _build_card_link(
        self,
        *,
        resource_type: str,
        resource_id: str,
        qq_user_id: str,
        qq_group_id: str,
        base_url_override: str | None,
    ) -> str | None:
        base_url = (base_url_override or self._runtime_config.public_base_url()).rstrip("/")
        if not base_url:
            return None
        expires_at = datetime.now(UTC) + timedelta(minutes=self._runtime_config.link_expire_minutes())
        token = self._card_link_signer.sign(
            resource_type=resource_type,
            resource_id=resource_id,
            qq_user_id=qq_user_id,
            qq_group_id=qq_group_id,
            expires_at=expires_at,
        )
        return f"{base_url}/learn/{resource_type}/{token}"
