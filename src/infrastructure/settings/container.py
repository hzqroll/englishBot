from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.application.admin_usecases import AdminUseCase
from src.application.learning_usecases import LearningUseCase
from src.application.message_usecases import MessageUseCase
from src.application.quiz_usecases import QuizUseCase
from src.application.report_usecases import ReportUseCase
from src.domain.services.error_points import ErrorAggregator
from src.domain.services.leveling import LevelService
from src.domain.services.review import ReviewScheduler
from src.infrastructure.cache.context_store import ContextStore
from src.infrastructure.db.repositories.admin import AdminRepository
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.db.session import create_engine, create_session_factory, init_db
from src.infrastructure.providers.content_ted import TedContentProvider
from src.infrastructure.providers.llm_doubao import DoubaoProvider
from src.infrastructure.providers.translate_google import GoogleTranslateProvider
from src.infrastructure.settings.models import EffectiveSettings
from src.infrastructure.settings.runtime import RuntimeConfigService


@dataclass(slots=True)
class ServiceContainer:
    settings: EffectiveSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    identity_repo: IdentityRepository
    learning_repo: LearningRepository
    admin_repo: AdminRepository
    translate_provider: GoogleTranslateProvider
    correction_provider: DoubaoProvider
    content_provider: TedContentProvider
    runtime_config: RuntimeConfigService
    context_store: ContextStore
    message_usecase: MessageUseCase
    learning_usecase: LearningUseCase
    quiz_usecase: QuizUseCase
    report_usecase: ReportUseCase
    admin_usecase: AdminUseCase


_container: ServiceContainer | None = None


async def build_container(settings: EffectiveSettings) -> ServiceContainer:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.runtime.database_url)
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)
    admin_repo = AdminRepository(session_factory)
    translate_provider = GoogleTranslateProvider(
        api_key=settings.runtime.google_translate_api_key,
        base_url=settings.runtime.google_translate_base_url,
    )
    correction_provider = DoubaoProvider(
        api_key=settings.runtime.ark_api_key,
        base_url=settings.runtime.ark_base_url,
        model=settings.runtime.ark_model,
    )
    content_provider = TedContentProvider(
        rss_urls=settings.static.content.ted_rss_urls,
        fallback_word_count=settings.static.content.fallback_lesson_word_count,
    )
    runtime_config = RuntimeConfigService(settings=settings, learning_repo=learning_repo)
    await runtime_config.refresh()
    context_store = ContextStore(ttl_minutes=settings.static.bot.context_ttl_minutes)
    level_service = LevelService()
    error_aggregator = ErrorAggregator()
    review_scheduler = ReviewScheduler()

    message_usecase = MessageUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        translate_provider=translate_provider,
        correction_provider=correction_provider,
        context_store=context_store,
        error_aggregator=error_aggregator,
        review_scheduler=review_scheduler,
    )
    learning_usecase = LearningUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        level_service=level_service,
        review_scheduler=review_scheduler,
        content_provider=content_provider,
        feedback_provider=correction_provider,
        points_per_task=settings.static.learning.score_per_task_completion,
        points_per_review=settings.static.learning.score_per_review_completion,
        runtime_config=runtime_config,
    )
    quiz_usecase = QuizUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        runtime_config=runtime_config,
    )
    report_usecase = ReportUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        summary_provider=correction_provider,
    )
    admin_usecase = AdminUseCase(
        admin_repo=admin_repo,
        learning_repo=learning_repo,
        runtime_config=runtime_config,
        settings=settings,
    )
    await admin_usecase.bootstrap_admin()
    container = ServiceContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        admin_repo=admin_repo,
        translate_provider=translate_provider,
        correction_provider=correction_provider,
        content_provider=content_provider,
        runtime_config=runtime_config,
        context_store=context_store,
        message_usecase=message_usecase,
        learning_usecase=learning_usecase,
        quiz_usecase=quiz_usecase,
        report_usecase=report_usecase,
        admin_usecase=admin_usecase,
    )
    set_container(container)
    return container


async def ensure_container(settings: EffectiveSettings) -> ServiceContainer:
    if _container is not None:
        return _container
    return await build_container(settings)


def set_container(container: ServiceContainer) -> None:
    global _container
    _container = container


def get_container() -> ServiceContainer:
    if _container is None:
        raise RuntimeError("Service container has not been initialized.")
    return _container
