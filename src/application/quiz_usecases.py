from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from src.domain.services.review import ReviewScheduler
from src.domain.value_objects.learning import QuizQuestionBundle
from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.settings.runtime import RuntimeConfigService


class QuizUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        runtime_config: RuntimeConfigService,
        review_scheduler: ReviewScheduler,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._runtime_config = runtime_config
        self._review_scheduler = review_scheduler

    async def start_weekly_quiz(
        self,
        *,
        qq_group_id: str,
        qq_user_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> str:
        return (
            await self.start_weekly_quiz_envelope(
                qq_group_id=qq_group_id,
                qq_user_id=qq_user_id,
                nickname=nickname,
                target_date=target_date,
            )
        ).plain_text

    async def start_weekly_quiz_envelope(
        self,
        *,
        qq_group_id: str,
        qq_user_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> MessageEnvelope:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        if not await self._identity_repo.is_enrolled(user.id, group.id):
            return MessageEnvelope(plain_text="请先发送“报名学习”后再开始周测。")

        target_date = target_date or datetime.now().astimezone().date()
        biz_week = target_date.strftime("%G-W%V")
        week_anchor = target_date - timedelta(days=target_date.weekday())
        session = await self._learning_repo.create_quiz_session(
            biz_week=biz_week,
            group_id=group.id,
            user_id=user.id,
        )
        question_count = self._runtime_config.weekly_quiz_question_count()
        questions = await self._build_weekly_questions(
            group_id=group.id,
            user_id=user.id,
            question_count=question_count,
        )
        await self._learning_repo.add_quiz_questions(
            session_id=session.id,
            questions=[
                {
                    "source_type": question.source_type,
                    "stem": question.stem,
                    "options": question.options,
                    "answer_key": question.answer_key,
                    "explanation": question.explanation,
                }
                for question in questions
            ],
        )
        stored_questions = await self._learning_repo.get_quiz_questions(session_id=session.id)
        lines = [
            f"{index}. {question.stem}\n   " + " ".join(
                f"{chr(65 + option_index)}.{option}"
                for option_index, option in enumerate(question.options)
            )
            for index, question in enumerate(stored_questions, start=1)
        ]
        plain_text = (
            f"周测已生成，session_id={session.id}\n"
            f"请使用 `答题 {session.id} 1:A 2:B ...` 提交整卷。\n\n"
            + "\n\n".join(lines)
        )
        sections = [
            CardSection(
                title="提交说明",
                lines=[f"试卷 ID：{session.id}", f"提交命令：答题 {session.id} 1:A 2:B ..."],
            )
        ]
        for index, question in enumerate(stored_questions, start=1):
            sections.append(
                CardSection(
                    title=f"{index}. {question.stem}",
                    lines=[f"{chr(65 + option_index)}. {option}" for option_index, option in enumerate(question.options)],
                )
            )
        document = CardDocument(
            title="本周英语小测",
            subtitle=f"共 {len(stored_questions)} 题",
            sections=sections,
            footer_lines=[f"答题后发送：答题 {session.id} 1:A 2:B ..."],
        )
        card_snapshot = await self._learning_repo.upsert_daily_card_snapshot(
            biz_date=week_anchor,
            user_id=user.id,
            group_id=group.id,
            card_type="weekly_quiz",
            plain_text=plain_text,
            card_document_json=asdict(document),
        )
        return MessageEnvelope(
            plain_text=plain_text,
            card_document=document,
            card_type="weekly_quiz",
            card_snapshot_id=card_snapshot.id,
        )

    async def submit_weekly_quiz(
        self,
        *,
        qq_group_id: str,
        qq_user_id: str,
        nickname: str,
        session_id: int,
        answers: dict[int, str],
    ) -> str:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        if not await self._identity_repo.is_enrolled(user.id, group.id):
            return "你还没有报名学习。"

        session = await self._learning_repo.get_quiz_session(session_id=session_id)
        if session is None:
            return "未找到对应周测试卷，请先发送“开始周测”。"
        if session.user_id != user.id or session.group_id != group.id:
            return "这份试卷不属于你当前所在的学习群，无法提交。"

        questions = await self._learning_repo.get_quiz_questions(session_id=session_id)
        if not questions:
            return "未找到对应周测试卷，请先发送“开始周测”。"

        scored_answers: list[dict] = []
        total_score = 0
        wrong_items: list[str] = []
        wrong_review_error_point_ids: list[int] = []
        for index, question in enumerate(questions, start=1):
            user_answer = answers.get(index, "").upper()
            is_correct = user_answer == question.answer_key.upper()
            score = 10 if is_correct else 0
            total_score += score
            if not is_correct:
                wrong_items.append(f"{index}. 正确答案 {question.answer_key}，你的答案 {user_answer or '未作答'}")
                if question.source_type.startswith("review:error_point:"):
                    error_point_id = question.source_type.removeprefix("review:error_point:")
                    if error_point_id.isdigit():
                        wrong_review_error_point_ids.append(int(error_point_id))
            scored_answers.append(
                {
                    "question_id": question.id,
                    "user_answer": user_answer or "-",
                    "is_correct": is_correct,
                    "score": score,
                }
            )

        await self._learning_repo.save_quiz_answers(
            session_id=session_id,
            answers=scored_answers,
            total_score=total_score,
        )
        if wrong_review_error_point_ids:
            progress = self._review_scheduler.schedule_new()
            await self._learning_repo.ensure_review_items(
                user_id=user.id,
                source_type="weekly_quiz",
                source_ref_id=str(session_id),
                error_point_ids=wrong_review_error_point_ids,
                interval_days=progress.interval_days,
                next_review_at=progress.next_review_at,
                status=progress.status,
            )
        await self._learning_repo.award_points(user_id=user.id, points=20, reason="weekly_quiz")
        summary = "\n".join(wrong_items[:5]) if wrong_items else "全部答对，做得很好。"
        return f"周测提交成功，总分 {total_score}。\n错题摘要：\n{summary}"

    async def _build_weekly_questions(
        self,
        *,
        group_id: int,
        user_id: int,
        question_count: int,
    ) -> list[QuizQuestionBundle]:
        review_quota = round(question_count * self._runtime_config.weekly_quiz_review_ratio())
        review_quota = min(max(review_quota, 1), question_count) if question_count > 1 else question_count
        lesson_quota = max(question_count - review_quota, 0)

        top_errors = await self._learning_repo.list_top_error_fragments(
            user_id=user_id,
            group_id=group_id,
            limit=review_quota,
        )
        recent_tasks = await self._learning_repo.get_recent_tasks_for_quiz(
            group_id=group_id,
            limit=max(lesson_quota, question_count),
        )

        questions: list[QuizQuestionBundle] = []
        questions.extend(self._build_review_questions(top_errors))
        questions.extend(self._build_lesson_questions(recent_tasks[:lesson_quota]))

        if len(questions) < question_count:
            for fallback in self._build_mock_questions():
                questions.append(fallback)
                if len(questions) >= question_count:
                    break
        return questions[:question_count]

    def _build_review_questions(self, error_points: list) -> list[QuizQuestionBundle]:
        questions: list[QuizQuestionBundle] = []
        for item in error_points:
            options = [
                item.source_fragment,
                item.correct_fragment,
                "No change needed",
            ]
            questions.append(
                QuizQuestionBundle(
                    source_type=f"review:error_point:{item.id}",
                    stem=(
                        f"你的高频错误类型是 {item.error_type}。"
                        f" 哪个片段更适合替换 `{item.source_fragment}`？"
                    ),
                    options=options,
                    answer_key="B",
                    explanation=item.explanation,
                )
            )
        return questions

    def _build_lesson_questions(self, tasks: list) -> list[QuizQuestionBundle]:
        label_to_option = {
            "vocabulary": "词汇提取",
            "reading": "阅读理解",
            "output": "英文输出",
        }
        options = ["词汇提取", "阅读理解", "英文输出", "语法观察"]
        questions: list[QuizQuestionBundle] = []
        for task in tasks:
            correct_option = label_to_option.get(task.task_type, "语法观察")
            answer_key = chr(65 + options.index(correct_option))
            questions.append(
                QuizQuestionBundle(
                    source_type=f"lesson:{task.task_type}",
                    stem=f"题目“{task.prompt[:70]}...”主要训练哪项能力？",
                    options=options,
                    answer_key=answer_key,
                    explanation=f"该题来自最近任务，核心目标是：{correct_option}。",
                )
            )
        return questions

    def _build_mock_questions(self) -> list[QuizQuestionBundle]:
        return [
            QuizQuestionBundle(
                source_type="lesson",
                stem="Choose the best meaning of the phrase 'small steps'.",
                options=["Huge goals", "Gradual progress", "Random changes", "Quick success"],
                answer_key="B",
                explanation="small steps 表示循序渐进。",
            ),
            QuizQuestionBundle(
                source_type="review",
                stem="Which sentence is more natural?",
                options=[
                    "I very like study English.",
                    "I like studying English very much.",
                    "I liking English study much.",
                    "I am like English very much.",
                ],
                answer_key="B",
                explanation="like studying English very much 更自然。",
            ),
        ]
