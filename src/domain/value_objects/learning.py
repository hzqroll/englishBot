from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class LanguageType(str, Enum):
    ENGLISH = "en"
    CHINESE = "zh"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class TranslationResult:
    source_text: str
    translated_text: str
    source_language: LanguageType
    target_language: LanguageType
    provider: str


@dataclass(slots=True)
class ErrorPointPayload:
    error_type: str
    source_fragment: str
    correct_fragment: str
    explanation: str


@dataclass(slots=True)
class CorrectionResult:
    original_text: str
    corrected_text: str
    zh_translation: str
    natural_expression: str
    explanation: str
    provider: str
    error_points: list[ErrorPointPayload] = field(default_factory=list)


@dataclass(slots=True)
class LessonTask:
    task_type: str
    prompt: str
    answer_key: str | None
    score_weight: int


@dataclass(slots=True)
class LessonTargetItem:
    entry_key: str
    entry_type: str
    text: str
    phonetic: str
    meaning_zh: str
    usage_scene: str
    example: str
    target_role: str


@dataclass(slots=True)
class LessonBundle:
    source_name: str
    external_id: str
    title: str
    url: str
    transcript: str
    difficulty: str
    biz_date: date
    tasks: list[LessonTask]
    theme_key: str = ""
    package_snapshot: dict = field(default_factory=dict)
    target_items: list[LessonTargetItem] = field(default_factory=list)


@dataclass(slots=True)
class QuizQuestionBundle:
    source_type: str
    stem: str
    options: list[str]
    answer_key: str
    explanation: str


@dataclass(slots=True)
class WeeklyReportBundle:
    week_key: str
    summary_text: str
    report_json: dict


@dataclass(slots=True)
class RuntimeSetting:
    key: str
    value: str
    updated_at: datetime
