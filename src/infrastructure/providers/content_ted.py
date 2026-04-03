from __future__ import annotations

from datetime import date
from hashlib import md5
from textwrap import shorten

import feedparser

from src.domain.value_objects.learning import LessonBundle, LessonTask


class TedContentProvider:
    def __init__(self, rss_urls: list[str], fallback_word_count: int = 180) -> None:
        self._rss_urls = rss_urls
        self._fallback_word_count = fallback_word_count

    async def fetch_candidates(self) -> list[dict]:
        candidates: list[dict] = []
        for url in self._rss_urls:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:5]:
                summary = (getattr(entry, "summary", "") or "").replace("<p>", "").replace("</p>", " ")
                candidates.append(
                    {
                        "source_name": "ted",
                        "external_id": md5((entry.link + entry.title).encode("utf-8")).hexdigest(),
                        "title": entry.title,
                        "url": entry.link,
                        "transcript": shorten(summary.strip(), width=1200, placeholder="..."),
                    }
                )
        return candidates

    async def build_lesson(self, *, level: str, biz_date: date) -> LessonBundle:
        candidates = await self.fetch_candidates()
        content = candidates[0] if candidates else self._fallback_content(level)
        transcript = content["transcript"] or self._fallback_content(level)["transcript"]
        tasks = [
            LessonTask(
                task_type="vocabulary",
                prompt=f"阅读短文《{content['title']}》，列出 3 个你认为重要的词或短语，并写出中文意思。",
                answer_key=None,
                score_weight=30,
            ),
            LessonTask(
                task_type="reading",
                prompt=f"用中文总结《{content['title']}》的核心观点，不超过 80 字。",
                answer_key=None,
                score_weight=30,
            ),
            LessonTask(
                task_type="output",
                prompt="请基于短文内容写 2 句英文表达，或把其中一个观点改写成更适合日常口语的表达。",
                answer_key=None,
                score_weight=40,
            ),
        ]
        return LessonBundle(
            source_name=content["source_name"],
            external_id=content["external_id"],
            title=content["title"],
            url=content["url"],
            transcript=transcript,
            difficulty=level,
            biz_date=biz_date,
            tasks=tasks,
        )

    def _fallback_content(self, level: str) -> dict:
        transcript = (
            "Learning English in small steps is often more effective than studying a huge amount at once. "
            "A daily habit can help learners remember vocabulary, notice grammar, and gain confidence."
        )
        return {
            "source_name": "ted-fallback",
            "external_id": "fallback-daily-learning",
            "title": f"Daily Learning Habit ({level})",
            "url": "https://www.ted.com/podcasts/ted-talks-daily",
            "transcript": transcript[: self._fallback_word_count * 8],
        }

