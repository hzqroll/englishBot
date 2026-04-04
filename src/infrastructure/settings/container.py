from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.application.admin_usecases import AdminUseCase
from src.application.learning_usecases import LearningUseCase
from src.application.message_usecases import MessageUseCase
from src.application.page_usecases import QuizPageUseCase, ReportPageUseCase, TaskPageUseCase
from src.application.quiz_usecases import QuizUseCase
from src.application.report_usecases import ReportUseCase
from src.infrastructure.auth.card_links import CardLinkSigner
from src.domain.services.error_points import ErrorAggregator
from src.domain.services.leveling import LevelService
from src.domain.services.review import ReviewScheduler
from src.infrastructure.cache.context_store import ContextStore
from src.infrastructure.db.repositories.admin import AdminRepository
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.db.session import create_engine, create_session_factory, init_db
from src.infrastructure.messaging.renderers import MessageDeliveryService, NapCatCardRenderer, PlainTextRenderer
from src.infrastructure.providers.content_ted import TedContentProvider
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider
from src.infrastructure.providers.translate_tencent import TencentTranslateProvider
from src.infrastructure.settings.loader import load_settings
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
    translate_provider: TencentTranslateProvider
    correction_provider: OpenAICompatibleProvider
    content_provider: TedContentProvider
    runtime_config: RuntimeConfigService
    context_store: ContextStore
    card_link_signer: CardLinkSigner
    plain_text_renderer: PlainTextRenderer
    napcat_card_renderer: NapCatCardRenderer
    message_delivery_service: MessageDeliveryService
    message_usecase: MessageUseCase
    learning_usecase: LearningUseCase
    quiz_usecase: QuizUseCase
    report_usecase: ReportUseCase
    task_page_usecase: TaskPageUseCase
    quiz_page_usecase: QuizPageUseCase
    report_page_usecase: ReportPageUseCase
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
    translate_provider = TencentTranslateProvider(
        secret_id=settings.runtime.tencent_translate_secret_id,
        secret_key=settings.runtime.tencent_translate_secret_key,
        region=settings.runtime.tencent_translate_region,
        endpoint=settings.runtime.tencent_translate_endpoint,
    )
    correction_provider = OpenAICompatibleProvider(
        api_key=settings.runtime.llm_api_key,
        base_url=settings.runtime.llm_base_url,
        model=settings.runtime.llm_model,
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
    card_link_signer = CardLinkSigner(settings.runtime.secret_key)
    plain_text_renderer = PlainTextRenderer()
    napcat_card_renderer = NapCatCardRenderer()
    message_delivery_service = MessageDeliveryService(
        runtime_config=runtime_config,
        plain_text_renderer=plain_text_renderer,
        napcat_card_renderer=napcat_card_renderer,
    )

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
        card_link_signer=card_link_signer,
        napcat_card_renderer=napcat_card_renderer,
    )
    quiz_usecase = QuizUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        runtime_config=runtime_config,
        review_scheduler=review_scheduler,
        card_link_signer=card_link_signer,
        napcat_card_renderer=napcat_card_renderer,
    )
    report_usecase = ReportUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        summary_provider=correction_provider,
        level_service=level_service,
        runtime_config=runtime_config,
        card_link_signer=card_link_signer,
        napcat_card_renderer=napcat_card_renderer,
    )
    task_page_usecase = TaskPageUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        learning_usecase=learning_usecase,
    )
    quiz_page_usecase = QuizPageUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        quiz_usecase=quiz_usecase,
    )
    report_page_usecase = ReportPageUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        report_usecase=report_usecase,
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
        card_link_signer=card_link_signer,
        plain_text_renderer=plain_text_renderer,
        napcat_card_renderer=napcat_card_renderer,
        message_delivery_service=message_delivery_service,
        message_usecase=message_usecase,
        learning_usecase=learning_usecase,
        quiz_usecase=quiz_usecase,
        report_usecase=report_usecase,
        task_page_usecase=task_page_usecase,
        quiz_page_usecase=quiz_page_usecase,
        report_page_usecase=report_page_usecase,
        admin_usecase=admin_usecase,
    )
    set_container(container)
    return container


async def ensure_container(settings: EffectiveSettings) -> ServiceContainer:
    if _container is not None:
        return _container
    return await build_container(settings)


async def get_or_init_container(settings: EffectiveSettings | None = None) -> ServiceContainer:
    if _container is not None:
        return _container
    effective_settings = settings or load_settings()
    return await build_container(effective_settings)


def set_container(container: ServiceContainer) -> None:
    global _container
    _container = container


def get_container() -> ServiceContainer:
    if _container is None:
        raise RuntimeError("Service container has not been initialized.")
    return _container
