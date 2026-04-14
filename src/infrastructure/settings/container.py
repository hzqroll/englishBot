from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.application.admin_usecases import AdminUseCase
from src.application.conversation_usecases import ConversationUseCase
from src.application.daily_session_usecases import DailySessionUseCase
from src.application.friends_usecases import FriendsUseCase
from src.application.learning_usecases import LearningUseCase
from src.application.message_usecases import MessageUseCase
from src.application.quiz_usecases import QuizUseCase
from src.application.report_usecases import ReportUseCase
from src.domain.services.conversation_analysis import ConversationAnalysisService
from src.domain.services.error_points import ErrorAggregator
from src.domain.services.leveling import LevelService
from src.domain.services.review import ReviewScheduler
from src.infrastructure.cache.context_store import ContextStore
from src.infrastructure.cache.group_dialogue_store import GroupDialogueStore
from src.infrastructure.channels.base import ChannelAdapter
from src.infrastructure.docs.feishu_docs_client import FeishuDocsClient
from src.infrastructure.docs.feishu_docs_service import FeishuDocsService
from src.infrastructure.docs.repository import FeishuDocsRepository
from src.infrastructure.channels.feishu import FeishuChannel
from src.infrastructure.db.repositories.admin import AdminRepository
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.db.session import create_engine, create_session_factory, init_db
from src.infrastructure.providers.curriculum_static import StaticCurriculumProvider
from src.infrastructure.providers.english_language_tool import LanguageToolEnglishProvider
from src.infrastructure.providers.friends_transcript import FriendsTranscriptProvider
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider
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
    english_correction_provider: LanguageToolEnglishProvider
    correction_provider: OpenAICompatibleProvider
    content_provider: StaticCurriculumProvider
    runtime_config: RuntimeConfigService
    context_store: ContextStore
    group_dialogue_store: GroupDialogueStore
    conversation_usecase: ConversationUseCase
    message_usecase: MessageUseCase
    learning_usecase: LearningUseCase
    daily_session_usecase: DailySessionUseCase
    quiz_usecase: QuizUseCase
    report_usecase: ReportUseCase
    admin_usecase: AdminUseCase
    channels: dict[str, ChannelAdapter]
    feishu_docs_service: FeishuDocsService | None = None
    friends_usecase: FriendsUseCase | None = None


_container: ServiceContainer | None = None
logger = logging.getLogger(__name__)


async def _warm_english_provider(provider: LanguageToolEnglishProvider) -> None:
    try:
        await provider.warmup()
    except Exception:  # pragma: no cover - defensive logging for background warmup
        logger.exception("english correction provider warmup failed")


async def build_container(settings: EffectiveSettings) -> ServiceContainer:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_engine(settings.runtime.database_url)
    session_factory = create_session_factory(engine)
    await init_db(engine)

    identity_repo = IdentityRepository(session_factory)
    learning_repo = LearningRepository(session_factory)
    admin_repo = AdminRepository(session_factory)
    correction_provider = OpenAICompatibleProvider(
        api_key=settings.runtime.llm_api_key,
        base_url=settings.runtime.llm_base_url,
        model=settings.runtime.llm_model,
        prompts=settings.static.prompts,
    )
    english_correction_provider = LanguageToolEnglishProvider(
        llm_provider=correction_provider,
    )
    content_provider = StaticCurriculumProvider(
        lexicon_path=settings.project_root / "resources" / "lexicon" / "bec_advanced.yaml",
        theme_path=settings.project_root / "resources" / "themes" / "office_scenarios.yaml",
    )
    runtime_config = RuntimeConfigService(settings=settings, learning_repo=learning_repo, admin_repo=admin_repo)
    await runtime_config.refresh()
    context_store = ContextStore(ttl_minutes=settings.static.feishu.context_ttl_minutes)
    group_dialogue_store = GroupDialogueStore()
    conversation_analysis_service = ConversationAnalysisService()
    level_service = LevelService()
    error_aggregator = ErrorAggregator()
    review_scheduler = ReviewScheduler()

    daily_session_usecase = DailySessionUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        voice_required_weekdays=tuple(settings.static.learning.voice_required_weekdays),
        monthly_benchmark_weekday=settings.static.learning.monthly_benchmark_weekday,
        rescue_lookback_days=settings.static.learning.rescue_lookback_days,
    )
    message_usecase = MessageUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        english_correction_provider=english_correction_provider,
        llm_provider=correction_provider,
        context_store=context_store,
        group_dialogue_store=group_dialogue_store,
        error_aggregator=error_aggregator,
        review_scheduler=review_scheduler,
        daily_session_usecase=daily_session_usecase,
        recent_chat_min_sentences=10,
    )
    conversation_usecase = ConversationUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        analysis_service=conversation_analysis_service,
        group_dialogue_store=group_dialogue_store,
        daily_session_usecase=daily_session_usecase,
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
        prompts=settings.static.prompts,
    )
    quiz_usecase = QuizUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        runtime_config=runtime_config,
        review_scheduler=review_scheduler,
    )
    report_usecase = ReportUseCase(
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        summary_provider=correction_provider,
        level_service=level_service,
        prompts=settings.static.prompts,
    )
    admin_usecase = AdminUseCase(
        admin_repo=admin_repo,
        learning_repo=learning_repo,
        runtime_config=runtime_config,
        settings=settings,
    )
    await admin_usecase.bootstrap_admin()
    asyncio.create_task(_warm_english_provider(english_correction_provider))

    channels: dict[str, ChannelAdapter] = {}
    feishu_docs_service: FeishuDocsService | None = None

    if settings.runtime.feishu_app_id:
        feishu_channel = FeishuChannel(
            app_id=settings.runtime.feishu_app_id,
            app_secret=settings.runtime.feishu_app_secret,
        )
        channels["feishu"] = feishu_channel

        if settings.static.feishu.docs.enabled:
            docs_client = FeishuDocsClient(
                app_id=settings.runtime.feishu_app_id,
                app_secret=settings.runtime.feishu_app_secret,
            )
            docs_repo = FeishuDocsRepository(session_factory)
            feishu_docs_service = FeishuDocsService(
                docs_client=docs_client,
                docs_repo=docs_repo,
                feishu_channel=feishu_channel,
                folder_name=settings.static.feishu.docs.folder_name,
                notify_chat_ids=settings.static.feishu.docs.notify_chat_ids,
            )
    else:
        logger.warning("feishu_app_id not configured, no channels registered")

    container = ServiceContainer(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        identity_repo=identity_repo,
        learning_repo=learning_repo,
        admin_repo=admin_repo,
        english_correction_provider=english_correction_provider,
        correction_provider=correction_provider,
        content_provider=content_provider,
        runtime_config=runtime_config,
        context_store=context_store,
        group_dialogue_store=group_dialogue_store,
        conversation_usecase=conversation_usecase,
        message_usecase=message_usecase,
        learning_usecase=learning_usecase,
        daily_session_usecase=daily_session_usecase,
        quiz_usecase=quiz_usecase,
        report_usecase=report_usecase,
        admin_usecase=admin_usecase,
        channels=channels,
        feishu_docs_service=feishu_docs_service,
    )
    set_container(container)

    # 注册 Friends 每日对话推送服务
    if settings.static.friends.enabled:
        transcripts_path = settings.project_root / "resources" / "friends" / "transcripts.json"
        if transcripts_path.exists():
            friends_provider = FriendsTranscriptProvider(transcripts_path)
            container.friends_usecase = FriendsUseCase(
                friends_provider=friends_provider,
                llm_provider=correction_provider,
                prompts=settings.static.prompts,
            )
            logger.info(
                "friends feature enabled: %d segments loaded from %s",
                friends_provider.total_segments,
                transcripts_path,
            )
        else:
            logger.warning("friends feature enabled but transcripts not found: %s", transcripts_path)

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
