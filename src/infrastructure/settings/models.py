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
    port: int = 8003
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
    enabled: bool = False
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
    sync_feishu_messages_cron: str = "50 17 * * *"


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


class FeishuDocsSettings(BaseModel):
    enabled: bool = False
    folder_name: str = "englishImprovePlan"
    notify_chat_ids: list[str] = Field(default_factory=list)


class FeishuSettings(BaseModel):
    enabled: bool = True
    enabled_group_ids: list[str] = Field(default_factory=list)
    docs: FeishuDocsSettings = Field(default_factory=FeishuDocsSettings)


class FriendsSettings(BaseModel):
    enabled: bool = False
    start_date: str = ""
    daily_push_cron: str = "0 9 * * *"


class PromptsSettings(BaseModel):
    correction_system: str = (
        "你是英语学习助教。请严格返回 JSON，结构如下：\n"
        '{"corrected_text": "...", "zh_translation": "...", "natural_expression": "...", "explanation": "...", '
        '"error_points": [{"error_type": "tense|article|preposition|word_choice|spelling|expression|grammar|agreement|natural_expression", '
        '"source_fragment": "...", "correct_fragment": "...", "explanation": "..."}]}'
    )
    improve_translation: str = (
        "请将下面中文翻译优化为更自然的英文。\n"
        "保持简洁，只返回优化后的英文。\n"
        "上下文：{context}\n"
        "中文：{source_text}\n"
        "基础翻译：{base_translation}"
    )
    task_feedback: str = "请用 2 句话评价以下英语学习任务提交，给出鼓励和一个改进建议：\n{content}"
    dialogue_analysis_system: str = (
        "你是英语学习助教。请严格返回 JSON，结构如下：\n"
        '{"translated_dialogue": "...", "speaker_feedbacks": [{"speaker": "...", "overall_comment": "...", "issues": ["..."]}]}'
        "\n\n要求：\n1. 保留原始对话顺序和说话人标识。\n2. 如果原文已经是英文，只做轻微润色，不要改写语义。\n"
        "3. 只指出语言表达、语法、用词、自然度问题。\n4. 如果某个说话人没有明显问题，可以省略。"
    )
    weekly_report_summary: str = (
        "请生成一句简洁的英语学习周报鼓励语，语气积极，不超过 50 字。"
        " 学习天数：{learning_days}，完成率：{task_completion_rate}，"
        " 纠错次数：{correction_count}，当前等级：{level}。"
    )
    daily_progress_summary: str = (
        "请用不超过 60 字生成一段英语学习日总结，语气积极、具体。"
        " 状态：{task_status}；等级：{level_label}；"
        " 英语尝试：{english_attempt_count}；目标词命中：{target_hit_count}；"
        " 纠错次数：{correction_count}；任务完成：{today_task_completed}/{today_task_total}；"
        " 掌握度：{mastery_label}；依据：{mastery_reason}"
    )
    friends_analysis_system: str = (
        '你是英语学习助教，擅长分析美剧对话。请严格返回 JSON，结构如下：\n'
        '{\n'
        '  "translation": "对话的中文翻译，每行一句，用换行符分隔",\n'
        '  "vocabulary": ["词汇/短语 (音标) — 释义: 例句", ...],\n'
        '  "grammar": ["语法点1: 解析", "语法点2: 解析"],\n'
        '  "culture": ["文化背景说明"]\n'
        '}\n\n'
        '要求：\n'
        "1. translation: 逐句翻译，保留说话人前缀，如 'Monica: 莫妮卡说的中文翻译'\n"
        "2. vocabulary: 挑选 3-5 个重点词汇/短语，包含音标和例句\n"
        "3. grammar: 1-2 个语法点，用简单中文解析\n"
        "4. culture: 如有文化背景需要说明则给出，没有则返回空数组 []\n"
        "5. 只返回 JSON，不要有其他文字"
    )


class StaticConfig(BaseModel):
    bot: BotSettings = Field(default_factory=BotSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    content: ContentSettings = Field(default_factory=ContentSettings)
    learning: LearningSettings = Field(default_factory=LearningSettings)
    admin: AdminUiSettings = Field(default_factory=AdminUiSettings)
    message: MessageSettings = Field(default_factory=MessageSettings)
    feishu: FeishuSettings = Field(default_factory=FeishuSettings)
    friends: FriendsSettings = Field(default_factory=FriendsSettings)
    prompts: PromptsSettings = Field(default_factory=PromptsSettings)


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
