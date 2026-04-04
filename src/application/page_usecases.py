from __future__ import annotations

from dataclasses import dataclass

from src.application.learning_usecases import LearningUseCase
from src.application.quiz_usecases import QuizUseCase
from src.application.report_usecases import ReportUseCase
from src.domain.value_objects.messaging import CardLinkPayload
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository


@dataclass(slots=True)
class TaskPageData:
    title: str
    transcript: str
    tasks: list
    submissions: dict
    qq_group_id: str
    qq_user_id: str


class TaskPageUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        learning_usecase: LearningUseCase,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._learning_usecase = learning_usecase

    async def load(self, token_payload: CardLinkPayload) -> TaskPageData:
        user = await self._identity_repo.get_user_by_qq_user_id(token_payload.qq_user_id)
        group = await self._identity_repo.get_group_by_qq_group_id(token_payload.qq_group_id)
        if user is None or group is None:
            raise ValueError("学习页链接无效，请回到群里重新获取。")

        lesson_detail = await self._learning_repo.get_lesson_detail(lesson_id=int(token_payload.resource_id))
        if lesson_detail is None:
            raise ValueError("未找到对应任务，请回到群里重新获取。")
        lesson, content = lesson_detail
        if lesson.group_id != group.id:
            raise ValueError("任务不属于当前学习群。")

        tasks = await self._learning_repo.get_tasks_for_lesson(lesson_id=lesson.id)
        submissions = await self._learning_repo.get_task_submissions_for_user(
            user_id=user.id,
            task_ids=[task.id for task in tasks],
        )
        return TaskPageData(
            title=content.title,
            transcript=content.transcript,
            tasks=tasks,
            submissions=submissions,
            qq_group_id=token_payload.qq_group_id,
            qq_user_id=token_payload.qq_user_id,
        )

    async def submit(self, token_payload: CardLinkPayload, *, task_id: int, content: str) -> str:
        return await self._learning_usecase.submit_task(
            qq_group_id=token_payload.qq_group_id,
            qq_user_id=token_payload.qq_user_id,
            nickname="",
            task_id=task_id,
            content=content,
        )


class QuizPageUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        quiz_usecase: QuizUseCase,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._quiz_usecase = quiz_usecase

    async def load(self, token_payload: CardLinkPayload) -> dict:
        user = await self._identity_repo.get_user_by_qq_user_id(token_payload.qq_user_id)
        group = await self._identity_repo.get_group_by_qq_group_id(token_payload.qq_group_id)
        if user is None or group is None:
            raise ValueError("学习页链接无效，请回到群里重新获取。")

        session = await self._learning_repo.get_quiz_session(session_id=int(token_payload.resource_id))
        if session is None:
            raise ValueError("未找到对应周测试卷。")
        if session.user_id != user.id or session.group_id != group.id:
            raise ValueError("这份试卷不属于当前用户或学习群。")

        questions = await self._learning_repo.get_quiz_questions(session_id=session.id)
        answers = await self._learning_repo.get_quiz_answers(session_id=session.id)
        return {
            "session": session,
            "questions": questions,
            "answers": answers,
            "qq_group_id": token_payload.qq_group_id,
            "qq_user_id": token_payload.qq_user_id,
        }

    async def submit(self, token_payload: CardLinkPayload, *, answers: dict[int, str]) -> str:
        return await self._quiz_usecase.submit_weekly_quiz(
            qq_group_id=token_payload.qq_group_id,
            qq_user_id=token_payload.qq_user_id,
            nickname="",
            session_id=int(token_payload.resource_id),
            answers=answers,
        )


class ReportPageUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        report_usecase: ReportUseCase,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._report_usecase = report_usecase

    async def load(self, token_payload: CardLinkPayload) -> dict:
        user = await self._identity_repo.get_user_by_qq_user_id(token_payload.qq_user_id)
        group = await self._identity_repo.get_group_by_qq_group_id(token_payload.qq_group_id)
        if user is None or group is None:
            raise ValueError("学习页链接无效，请回到群里重新获取。")

        report = await self._learning_repo.get_weekly_report(
            biz_week=token_payload.resource_id,
            user_id=user.id,
        )
        if report is None:
            await self._report_usecase.build_weekly_report(
                qq_group_id=token_payload.qq_group_id,
                qq_user_id=token_payload.qq_user_id,
                nickname="",
            )
            report = await self._learning_repo.get_weekly_report(
                biz_week=token_payload.resource_id,
                user_id=user.id,
            )
        if report is None:
            raise ValueError("未找到对应周报。")

        return {
            "report": report,
            "qq_group_id": token_payload.qq_group_id,
            "qq_user_id": token_payload.qq_user_id,
        }
