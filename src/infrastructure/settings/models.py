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

    app_name: str = "English Learning Feishu Bot"
    env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8003
    secret_key: str = "replace-me"
    database_url: str = "sqlite+aiosqlite:///./data/english_bot.sqlite3"
    config_path: str = "./config.yaml"
    admin_username: str = "admin"
    admin_password: str = "admin123"

    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_verification_token: str = ""
    feishu_encrypt_key: str = ""
    feishu_callback_max_skew_seconds: int = 3600


class SchedulerSettings(BaseModel):
    daily_push_cron: str = "0 8 * * *"
    midday_baton_cron: str = "30 12 * * *"
    evening_baton_cron: str = "30 18 * * *"
    daily_error_digest_cron: str = "0 18 * * *"
    daily_progress_cron: str = "0 20 * * *"
    daily_summary_cron: str = "0 20 * * *"
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
    voice_required_weekdays: list[int] = Field(default_factory=lambda: [1, 4])
    monthly_benchmark_weekday: int = 6
    rescue_lookback_days: int = 2


class AdminUiSettings(BaseModel):
    title: str = "English Bot Admin"
    enable_http_login_warning: bool = True


class FeishuDocsSettings(BaseModel):
    enabled: bool = False
    folder_name: str = "englishImprovePlan"
    notify_chat_ids: list[str] = Field(default_factory=list)


class FeishuSettings(BaseModel):
    enabled: bool = True
    enabled_group_ids: list[str] = Field(default_factory=list)
    context_ttl_minutes: int = 15
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
    daily_summary_xhs_prompt: str = """
你是一名英语学习陪练总结助手，同时也是小红书学习内容策划助手（小红书内容主要是为了记录学习状态）。请根据用户当天的学习输入，生成一份“英语学习日报 + 小红书可发布文案 + 图片生成提示词”。

【输入内容】
- 今日目标：{daily_goal}
- 今日练习词语：{required_phrases}
- 今日练习文本：{today_dialogues}
- 回捞结果：{yesterday_dialogues}
- 今日新学单词：{new_words_today}

【输出要求】
- 严格输出 JSON
- 只允许输出下方定义的固定字段
- 不要添加额外字段
- 不要输出解释
- 不要使用 markdown
- 没有足够依据的内容不要编造

【输出字段】
{
  "今日目标": "",
  "今日学习总结": "",
  "练习短文": "",
  "小红书发布文案": {
    "标题": "",
    "封面短句": "",
    "正文文案": "",
    "标签": []
  },
  "图片生成提示词": {
    "今日目标图": "",
    "今日学习总结图": "",
    "练习短文图": ""
  }
}

【语言要求】
- “今日目标”“今日学习总结”“练习短文”必须全英文
- “小红书发布文案”必须全中文
- “图片生成提示词”必须用英文撰写，便于直接用于图像生成模型
- 不要中英混杂，除非标签中需要保留常见英文话题词

【字段要求】

1. 今日目标
- 今日目标必须自然包含 1~3 个“今日练习词语”中的核心表达，并体现明确应用场景
- 这句话必须同时体现：
  - 当天学习主线
  - 今天需要主动复用的关键词语或表达
  - 一个明确的实际应用场景
- 优先把“今日练习词语”自然融入句子本身，而不是额外单独罗列
- 如果“今日练习词语”有多个，只选择最核心、最适合融入目标句的 1~3 个
- 语言要自然，像真实学习目标，不要写成关键词堆砌
- 不要空泛，不要夸张
- 长度控制在 1 句话

2. 今日学习总结
- 输出 1 段英文总结
- 必须优先引用今天真实练习里出现过的内容，不要空泛发挥
- 必须结合“今日练习文本”和“回捞结果”
- 需要体现：
  - 今天主要练了什么
  - 哪些表达被反复使用或复习
  - 相比昨天有哪些延续或进步
  - 还有哪些地方不够自然
- 语气真实、具体、简洁，像学习教练
- 不要逐条罗列
- 不要写成老师批改意见
- 如果信息不足，基于已有内容保守总结，不要虚构细节
- 长度控制在  300字以内 词

3. 练习短文
- 输出 1 段英文短文，用来进行今日的练习
- 内容贴合“今日目标”
- 尽量包含“今日练习词语”中的表达
- 可以自然吸收“今日新学单词”，但不要单独解释单词
- 文风自然，像真实英文表达，不像教材例文
- 长度控制在  500字以内 词

4. 小红书发布文案
- 必须为中文
- 标题：简洁，有成长感、打卡感，不夸张
- 封面短句：适合放在图片封面上，8~16 个字
- 正文文案：以第一人称写，像真实学习打卡分享，简洁自然，不鸡汤，要体现今天具体练了什么
- 标签：输出 3~5 个，适合英语学习打卡场景

5. 图片生成提示词
需要分别生成 3 条英文图片提示词，对应：
- 今日目标图
- 今日学习总结图
- 练习短文图

这 3 条提示词必须遵循同一视觉体系，风格如下：
- premium minimalist chalkboard editorial poster for English learning
- deep green chalkboard with subtle gradient and fine chalk dust texture
- ultra clean and restrained composition
- elegant, calm, high-end design
- inspired by Apple keynote slides
- editorial typography style
- strong negative space
- portrait 4:5 ratio
- strong typography hierarchy
- grid-based layout
- subtle asymmetry with balance
- clean chalk lettering but highly controlled
- high legibility, no distortion
- no clutter
- no excessive doodles
- no childish illustration style
- focus on typography and layout
- ultra high resolution
- premium poster quality
- Xiaohongshu cover ready

其中：
- “今日目标图”要使用小标题 "TODAY'S GOAL"
- “今日学习总结图”要使用小标题 "TODAY'S STUDY SUMMARY"
- “练习短文图”要使用小标题 "PRACTICE PASSAGE"

图片提示词内容要求：
- 必须把对应字段的正文内容嵌入提示词
- 明确要求文字是画面主体
- 明确要求文字清晰可读
- 明确要求不要出现杂乱插画、可爱风、课堂海报风、花哨装饰、现代信息图风格
- 可以加入少量辅助短句或关键词作为次要元素，但必须非常克制
- 重点强调 typography, spacing, negative space, readability

【整体风格要求】
- 真实，不夸张
- 鼓励但不过度吹捧
- 要体现“今天确实学了什么”
- 整体适合直接做成小红书图文内容
- 所有输出内容要彼此一致，不能互相矛盾

【输出示例】
{
  "今日目标": "...",
  "今日学习总结": "...",
  "练习短文": "...",
  "小红书发布文案": {
    "标题": "...",
    "封面短句": "...",
    "正文文案": "...",
    "标签": ["#英语学习", "#英语打卡", "#今日复盘"]
  },
  "图片生成提示词": {
    "今日目标图": "...",
    "今日学习总结图": "...",
    "练习短文图": "..."
  }
}
""".strip()
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
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)
    content: ContentSettings = Field(default_factory=ContentSettings)
    learning: LearningSettings = Field(default_factory=LearningSettings)
    admin: AdminUiSettings = Field(default_factory=AdminUiSettings)
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
