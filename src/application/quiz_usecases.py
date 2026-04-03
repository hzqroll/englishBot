from __future__ import annotations

from datetime import UTC, datetime

from src.domain.value_objects.learning import QuizQuestionBundle
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
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._runtime_config = runtime_config

    async def start_weekly_quiz(self, *, qq_group_id: str, qq_user_id: str, nickname: str) -> str:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        if not await self._identity_repo.is_enrolled(user.id, group.id):
            return "请先发送“报名学习”后再开始周测。"

        biz_week = datetime.now(UTC).strftime("%G-W%V")
        session = await self._learning_repo.create_quiz_session(
            biz_week=biz_week,
            group_id=group.id,
            user_id=user.id,
        )
        questions = self._build_mock_questions()[: self._runtime_config.weekly_quiz_question_count()]
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
        lines = [
            f"{index}. {question.stem}\n   " + " ".join(
                f"{chr(65 + option_index)}.{option}"
                for option_index, option in enumerate(question.options)
            )
            for index, question in enumerate(questions, start=1)
        ]
        return (
            f"周测已生成，session_id={session.id}\n"
            f"请使用 `答题 {session.id} 1:A 2:B ...` 提交整卷。\n\n"
            + "\n\n".join(lines)
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

        questions = await self._learning_repo.get_quiz_questions(session_id=session_id)
        if not questions:
            return "未找到对应周测试卷，请先发送“开始周测”。"

        scored_answers: list[dict] = []
        total_score = 0
        wrong_items: list[str] = []
        for index, question in enumerate(questions, start=1):
            user_answer = answers.get(index, "").upper()
            is_correct = user_answer == question.answer_key.upper()
            score = 10 if is_correct else 0
            total_score += score
            if not is_correct:
                wrong_items.append(f"{index}. 正确答案 {question.answer_key}，你的答案 {user_answer or '未作答'}")
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
        await self._learning_repo.award_points(user_id=user.id, points=20, reason="weekly_quiz")
        summary = "\n".join(wrong_items[:5]) if wrong_items else "全部答对，做得很好。"
        return f"周测提交成功，总分 {total_score}。\n错题摘要：\n{summary}"

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
