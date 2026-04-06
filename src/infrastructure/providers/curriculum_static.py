from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import md5
from pathlib import Path

import yaml

from src.domain.value_objects.learning import LessonBundle, LessonTargetItem, LessonTask


@dataclass(slots=True)
class _LexiconEntry:
    entry_key: str
    entry_type: str
    text: str
    phonetic: str
    meaning_zh: str
    usage_scene: str
    example: str
    difficulty: str
    tags: list[str]


@dataclass(slots=True)
class _ThemeScenario:
    theme_key: str
    title: str
    scene: str
    opening: str
    core_tags: list[str]
    support_tags: list[str]
    dialogue_template: list[str]
    task_templates: list[dict]


class StaticCurriculumProvider:
    def __init__(self, *, lexicon_path: Path, theme_path: Path) -> None:
        self._lexicon = self._load_lexicon(lexicon_path)
        self._themes = self._load_themes(theme_path)

    async def build_lesson(self, *, level: str, biz_date: date) -> LessonBundle:
        theme = self._themes[biz_date.toordinal() % len(self._themes)]
        core_items = self._select_items(theme.core_tags, entry_type="chunk", limit=5)
        support_items = self._select_items(theme.support_tags, entry_type="word", limit=5)
        target_items = [
            self._to_target_item(item, target_role="core_chunk") for item in core_items
        ] + [
            self._to_target_item(item, target_role="support_word") for item in support_items
        ]

        dialogue = "\n".join(theme.dialogue_template)
        overview = self._build_overview(theme, target_items)
        tasks = [
            LessonTask(
                task_type=item["type"],
                prompt=item["prompt"],
                answer_key=None,
                score_weight=34 if index == 2 else 33,
            )
            for index, item in enumerate(theme.task_templates, start=1)
        ]
        package_snapshot = {
            "theme_key": theme.theme_key,
            "title": theme.title,
            "scene": theme.scene,
            "opening": theme.opening,
            "dialogue_lines": theme.dialogue_template,
            "targets": [
                {
                    "entry_key": item.entry_key,
                    "entry_type": item.entry_type,
                    "text": item.text,
                    "phonetic": item.phonetic,
                    "meaning_zh": item.meaning_zh,
                    "usage_scene": item.usage_scene,
                    "example": item.example,
                    "target_role": item.target_role,
                }
                for item in target_items
            ],
            "tasks": [task.prompt for task in tasks],
        }
        return LessonBundle(
            source_name="local-curriculum",
            external_id=md5(f"{theme.theme_key}:{biz_date.isoformat()}".encode("utf-8")).hexdigest(),
            title=f"{theme.title} · {theme.scene}",
            url="https://example.local/curriculum",
            transcript=f"{overview}\n\n办公室情景对话：\n{dialogue}",
            difficulty=level,
            biz_date=biz_date,
            tasks=tasks,
            theme_key=theme.theme_key,
            package_snapshot=package_snapshot,
            target_items=target_items,
        )

    def _build_overview(self, theme: _ThemeScenario, target_items: list[LessonTargetItem]) -> str:
        core = [item.text for item in target_items if item.target_role == "core_chunk"]
        support = [item.text for item in target_items if item.target_role == "support_word"]
        return (
            f"今日主题：{theme.title}\n"
            f"学习目标：{theme.opening}\n"
            f"核心词块：{', '.join(core)}\n"
            f"支持词汇：{', '.join(support)}"
        )

    def _select_items(self, tags: list[str], *, entry_type: str, limit: int) -> list[_LexiconEntry]:
        matched = [
            item for item in self._lexicon
            if item.entry_type == entry_type and any(tag in item.tags for tag in tags)
        ]
        return matched[:limit]

    def _to_target_item(self, item: _LexiconEntry, *, target_role: str) -> LessonTargetItem:
        return LessonTargetItem(
            entry_key=item.entry_key,
            entry_type=item.entry_type,
            text=item.text,
            phonetic=item.phonetic,
            meaning_zh=item.meaning_zh,
            usage_scene=item.usage_scene,
            example=item.example,
            target_role=target_role,
        )

    def _load_lexicon(self, path: Path) -> list[_LexiconEntry]:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        return [
            _LexiconEntry(
                entry_key=item["entry_key"],
                entry_type=item["entry_type"],
                text=item["text"],
                phonetic=item.get("phonetic", ""),
                meaning_zh=item.get("meaning_zh", ""),
                usage_scene=item.get("usage_scene", ""),
                example=item.get("example", ""),
                difficulty=item.get("difficulty", "unified"),
                tags=list(item.get("tags", [])),
            )
            for item in data
        ]

    def _load_themes(self, path: Path) -> list[_ThemeScenario]:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        return [
            _ThemeScenario(
                theme_key=item["theme_key"],
                title=item["title"],
                scene=item["scene"],
                opening=item["opening"],
                core_tags=list(item.get("core_tags", [])),
                support_tags=list(item.get("support_tags", [])),
                dialogue_template=list(item.get("dialogue_template", [])),
                task_templates=list(item.get("task_templates", [])),
            )
            for item in data
        ]
