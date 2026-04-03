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

    google_translate_api_key: str = ""
    google_translate_base_url: str = "https://translation.googleapis.com/language/translate/v2"

    ark_api_key: str = ""
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    ark_model: str = "doubao-1-5-pro-32k-250115"


class BotSettings(BaseModel):
    enabled_group_ids: list[str] = Field(default_factory=list)
    admin_group_ids: list[str] = Field(default_factory=list)
    context_ttl_minutes: int = 15
    daily_reminder_enabled: bool = True


class SchedulerSettings(BaseModel):
    daily_push_cron: str = "0 8 * * *"
    daily_reminder_cron: str = "0 20 * * *"
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


class StaticConfig(BaseModel):
    bot: BotSettings = Field(default_factory=BotSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    content: ContentSettings = Field(default_factory=ContentSettings)
    learning: LearningSettings = Field(default_factory=LearningSettings)
    admin: AdminUiSettings = Field(default_factory=AdminUiSettings)


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

