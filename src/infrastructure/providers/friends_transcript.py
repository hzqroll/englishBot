from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(slots=True)
class DialogueLine:
    speaker: str
    text: str


@dataclass(slots=True)
class FriendsSegment:
    season: int
    episode: int
    title: str
    lines: list[DialogueLine]


class FriendsTranscriptProvider:
    """加载预抓取的 Friends 对话数据，按索引返回分段。"""

    def __init__(self, transcripts_path: Path) -> None:
        self._episodes: list[dict] = []
        self._segments: list[FriendsSegment] = []
        self._load(transcripts_path)

    def _load(self, path: Path) -> None:
        with open(path, encoding="utf-8") as f:
            self._episodes = json.load(f)

        for ep in self._episodes:
            all_lines: list[DialogueLine] = []
            for scene in ep.get("scenes", []):
                for line in scene.get("lines", []):
                    if line.get("speaker"):
                        all_lines.append(
                            DialogueLine(speaker=line["speaker"], text=line["text"])
                        )
            if not all_lines:
                continue

            # Most episodes: 1 segment with first 25 lines (key dialogue excerpt)
            # Long episodes (>40 lines): split into 2 segments
            if len(all_lines) <= 40:
                self._segments.append(
                    FriendsSegment(
                        season=ep["season"],
                        episode=ep["episode"],
                        title=ep["title"],
                        lines=all_lines[:25],
                    )
                )
            else:
                mid = len(all_lines) // 2
                self._segments.append(
                    FriendsSegment(
                        season=ep["season"],
                        episode=ep["episode"],
                        title=f"{ep['title']} (Part 1)",
                        lines=all_lines[:mid][:25],
                    )
                )
                self._segments.append(
                    FriendsSegment(
                        season=ep["season"],
                        episode=ep["episode"],
                        title=f"{ep['title']} (Part 2)",
                        lines=all_lines[mid:][:25],
                    )
                )

    def get_segment(self, biz_date: date, start_date: date) -> FriendsSegment:
        """根据日期偏移获取当日对话段。"""
        if not self._segments:
            raise ValueError("No transcript segments available")
        delta = (biz_date - start_date).days
        index = delta % len(self._segments)
        return self._segments[index]

    @property
    def total_segments(self) -> int:
        return len(self._segments)
