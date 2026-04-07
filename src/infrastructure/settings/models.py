from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppRuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "English Learning QQ Bot"
    env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8080
    secret_key: str = "replace-me"
    access_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./data/english_bot.sqlite3"
    config_path: str = "./config.yaml"
    admin_username: str = "admin"
    admin_password: str = "admin123"

    tencent_translate_secret_id: str = ""
    tencent_translate_secret_key: str = ""
    tencent_translate_region: str = "ap-beijing"
    tencent_translate_endpoint: str = "tmt.tencentcloudapi.com"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    feishu_app_id: str = ""
    feishu_app_secret: str = ""


class BotSettings(BaseModel):
    enabled_group_ids: list[str] = Field(default_factory=list)
    admin_group_ids: list[str] = Field(default_factory=list)
    context_ttl_minutes: int = 15


class SchedulerSettings(BaseModel):
    daily_push_cron: str = "0 8 * * *"
    daily_error_digest_cron: str = "0 18 * * *"
    daily_progress_cron: str = "0 20 * * *"
    weekly_report_cron: str = "0 9 * * 1"
    weekly_quiz_cron: str = "0 19 * * 0"
    nightly_backup_cron: str = "0 2 * * *"


class ContentSettings(BaseModel):
    default_source: str = "ted"
    ted_rss_urls: list[str] = Field(
        default_factory=lambda: [
            "https://feeds.feedburner.com/tedtalks_audio",
            "https://feeds.feedburner.com/TEDTalks_video",
        ]
    )
    fallback_lesson_word_count: int = 180


class LearningSettings(BaseModel):
    beginner_threshold: int = 20
    intermediate_quiz_threshold: int = 70
    weekly_quiz_question_count: int = 8
    weekly_quiz_review_ratio: float = 0.4
    daily_review_insert_count: int = 2
    score_per_task_completion: int = 10
    score_per_review_completion: int = 6
    score_per_quiz_completion: int = 20


class AdminUiSettings(BaseModel):
    title: str = "English Bot Admin"
    enable_http_login_warning: bool = True


class MessageSettings(BaseModel):
    render_mode: str = "image_card"
    enable_task_cards: bool = True
    card_fallback_to_text: bool = True
    group_dialogue_trigger_min_sentences: int = 10


class FeishuSettings(BaseModel):
    enabled_group_ids: list[str] = Field(default_factory=list)


class StaticConfig(BaseModel):
    bot: BotSettings = Field(default_factory=BotSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    content: ContentSettings = Field(default_factory=ContentSettings)
    learning: LearningSettings = Field(default_factory=LearningSettings)
    admin: AdminUiSettings = Field(default_factory=AdminUiSettings)
    message: MessageSettings = Field(default_factory=MessageSettings)
    feishu: FeishuSettings = Field(default_factory=FeishuSettings)


@dataclass(slots=True)
class EffectiveSettings:
    runtime: AppRuntimeSettings
    static: StaticConfig
    project_root: Path
    template_dir: Path
    static_dir: Path
    data_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.data_dir = self.project_root / "data"
