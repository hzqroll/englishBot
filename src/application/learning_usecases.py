from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from src.domain.services.leveling import LearningEvidence, LevelService
from src.domain.services.review import ReviewScheduler
from src.domain.value_objects.learning import LessonBundle
from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.providers.curriculum_static import StaticCurriculumProvider
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider


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
        content_provider: StaticCurriculumProvider,
        feedback_provider: OpenAICompatibleProvider,
        points_per_task: int,
        points_per_review: int,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._level_service = level_service
        self._review_scheduler = review_scheduler
        self._content_provider = content_provider
        self._feedback_provider = feedback_provider
        self._points_per_task = points_per_task
        self._points_per_review = points_per_review

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

    async def build_today_lesson(self, *, qq_group_id: str, biz_date: date | None = None) -> LessonBundle:
        group = await self._identity_repo.ensure_group(qq_group_id)
        biz_date = biz_date or date.today()
        level = "beginner"
        bundle = await self._content_provider.build_lesson(level=level, biz_date=biz_date)
        yesterday_review = await self._prepare_review_candidates_for_lesson(
            group_id=group.id,
            target_date=biz_date,
        )
        if yesterday_review:
            bundle.package_snapshot["yesterday_review"] = yesterday_review
            review_lines = [f"{item['content_text']} -> {item['correct_text']}" for item in yesterday_review]
            if bundle.tasks:
                bundle.tasks[-1].prompt += (
                    "\n请至少复用昨日回顾中的 1 个表达："
                    + "；".join(review_lines)
                )
            await self._learning_repo.mark_review_candidates_used(
                group_id=group.id,
                biz_date=biz_date,
                content_texts=[item["content_text"] for item in yesterday_review],
            )
        await self._learning_repo.upsert_content_and_lesson(group.id, bundle)
        return bundle

    async def get_today_task_message(self, *, qq_group_id: str) -> str:
        group = await self._identity_repo.ensure_group(qq_group_id)
        lesson_detail, tasks = await self._ensure_today_task_detail(group.id, qq_group_id)
        lesson, content = lesson_detail
        target_items = await self._learning_repo.get_target_items_for_lesson(lesson_id=lesson.id)
        core_lines = [
            f"- {item.text} | {item.meaning_zh} | {item.example}"
            for item in target_items
            if item.target_role == "core_chunk"
        ]
        support_lines = [
            f"- {item.text} | {item.meaning_zh} | {item.example}"
            for item in target_items
            if item.target_role == "support_word"
        ]
        task_lines = [f"{task.id}. [{task.task_type}] {task.prompt}" for task in tasks]
        parts = [f"今日学习主题：{lesson.title or content.title}"]
        if lesson.theme_key:
            parts.append(f"主题编号：{lesson.theme_key}")
        yesterday_review = (lesson.package_snapshot_json or {}).get("yesterday_review", [])
        if yesterday_review:
            parts.append(
                "\n昨日回顾：\n" + "\n".join(
                    f"- {item['content_text']} -> {item['correct_text']}"
                    for item in yesterday_review
                )
            )
        if core_lines:
            parts.append("\n核心词块：\n" + "\n".join(core_lines))
        if support_lines:
            parts.append("\n支持词汇：\n" + "\n".join(support_lines))
        parts.append("\n办公室情景对话：\n" + content.transcript)
        parts.append("\n任务清单：\n" + "\n".join(task_lines))
        return "\n".join(parts)

    async def get_today_task_envelope(
        self,
        *,
        qq_group_id: str,
        qq_user_id: str,
        nickname: str,
    ) -> MessageEnvelope:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        enrolled = await self._identity_repo.is_enrolled(user.id, group.id)
        if not enrolled:
            return MessageEnvelope(plain_text="你还没有报名学习，请先发送“报名学习”。")

        lesson_detail, tasks = await self._ensure_today_task_detail(group.id, qq_group_id)
        lesson, content = lesson_detail
        target_items = await self._learning_repo.get_target_items_for_lesson(lesson_id=lesson.id)
        plain_text = await self.get_today_task_message(qq_group_id=qq_group_id)
        document = self._build_task_document(
            title=lesson.title or content.title,
            transcript=content.transcript,
            tasks=tasks,
            target_items=target_items,
            yesterday_review=(lesson.package_snapshot_json or {}).get("yesterday_review", []),
        )
        return MessageEnvelope(
            plain_text=plain_text,
            card_document=document,
        )

    async def get_today_task_broadcast_envelope(self, *, qq_group_id: str) -> MessageEnvelope:
        group = await self._identity_repo.ensure_group(qq_group_id)
        lesson_detail, tasks = await self._ensure_today_task_detail(group.id, qq_group_id)
        lesson, content = lesson_detail
        target_items = await self._learning_repo.get_target_items_for_lesson(lesson_id=lesson.id)
        plain_text = await self.get_today_task_message(qq_group_id=qq_group_id)
        return MessageEnvelope(
            plain_text=plain_text,
            card_document=self._build_task_document(
                title=lesson.title or content.title,
                transcript=content.transcript,
                tasks=tasks,
                target_items=target_items,
                yesterday_review=(lesson.package_snapshot_json or {}).get("yesterday_review", []),
            ),
            card_type="daily_lesson",
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
        target_date = date.today()
        lesson_detail = await self._learning_repo.get_today_lesson_detail(
            group_id=group_id,
            biz_date=target_date,
        )
        if lesson_detail is None:
            bundle = await self.build_today_lesson(qq_group_id=qq_group_id, biz_date=target_date)
            lesson_detail = await self._learning_repo.get_today_lesson_detail(
                group_id=group_id,
                biz_date=bundle.biz_date,
            )
            if lesson_detail is None:
                raise ValueError("今日任务生成失败。")
        tasks = await self._learning_repo.get_tasks_for_lesson(lesson_id=lesson_detail[0].id)
        return lesson_detail, tasks

    async def _prepare_review_candidates_for_lesson(self, *, group_id: int, target_date: date) -> list[dict]:
        source_date = target_date - timedelta(days=1)
        previous_lesson = await self._learning_repo.get_today_lesson_detail(group_id=group_id, biz_date=source_date)
        previous_target_items = []
        if previous_lesson is not None:
            previous_target_items = await self._learning_repo.get_target_items_for_lesson(lesson_id=previous_lesson[0].id)

        users = await self._identity_repo.list_enrolled_users(group_id)
        for user in users:
            digest = await self._learning_repo.get_daily_error_digest(
                user_id=user.id,
                group_id=group_id,
                target_date=source_date,
                word_limit=3,
                grammar_limit=3,
            )
            ranked: dict[tuple[str, str], dict] = {}
            for item in digest["word_items"] + digest["grammar_items"]:
                key = (item["source_fragment"], item["correct_fragment"])
                ranked[key] = {
                    "source_type": "error_occurrence",
                    "source_ref_id": item["error_type"],
                    "content_text": item["source_fragment"],
                    "correct_text": item["correct_fragment"],
                    "priority_score": 5 + int(item.get("frequency", 1)),
                    "selected_for_next_day": True,
                }
            for target_item in previous_target_items:
                key = (target_item.text, target_item.text)
                ranked.setdefault(
                    key,
                    {
                        "source_type": target_item.target_role,
                        "source_ref_id": target_item.entry_key,
                        "content_text": target_item.text,
                        "correct_text": target_item.text,
                        "priority_score": 3 if target_item.target_role == "core_chunk" else 2,
                        "selected_for_next_day": True,
                    },
                )
            selected = sorted(
                ranked.values(),
                key=lambda item: (-item["priority_score"], item["content_text"]),
            )[:3]
            await self._learning_repo.replace_review_candidates(
                user_id=user.id,
                group_id=group_id,
                biz_date=target_date,
                candidates=selected,
            )
        return await self._learning_repo.list_group_review_candidates(
            group_id=group_id,
            biz_date=target_date,
            limit=3,
        )

    def _build_task_document(
        self,
        *,
        title: str,
        transcript: str,
        tasks: list,
        target_items: list,
        yesterday_review: list[dict],
    ) -> CardDocument:
        sections = []
        if yesterday_review:
            sections.append(
                CardSection(
                    title="昨日回顾",
                    lines=[
                        f"{item['content_text']} -> {item['correct_text']}"
                        for item in yesterday_review
                    ],
                )
            )
        core_lines = [
            f"{item.text}  {item.phonetic}\n{item.meaning_zh}\n场景：{item.usage_scene}\n例句：{item.example}"
            for item in target_items
            if item.target_role == "core_chunk"
        ]
        support_lines = [
            f"{item.text}  {item.phonetic}\n{item.meaning_zh}\n场景：{item.usage_scene}\n例句：{item.example}"
            for item in target_items
            if item.target_role == "support_word"
        ]
        if core_lines:
            sections.append(CardSection(title="核心词块", lines=core_lines))
        if support_lines:
            sections.append(CardSection(title="支持词汇", lines=support_lines))
        sections.append(CardSection(title="办公室情景对话", lines=[transcript]))
        for index, task in enumerate(tasks, start=1):
            sections.append(
                CardSection(
                    title=f"任务 {index} · {task.task_type}",
                    lines=[
                        task.prompt,
                        f"提交命令：提交任务 {task.id} 你的答案",
                    ],
                )
            )
        return CardDocument(
            title=title,
            subtitle=f"今日任务 · 共 {len(tasks)} 个任务",
            sections=sections,
            footer_lines=["完成后直接在群里发送对应提交命令。"],
        )
