from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
import json
from typing import Any

from src.domain.services.leveling import LearningEvidence, LevelService
from src.domain.services.error_taxonomy import label_error_type
from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider
from src.infrastructure.settings.models import PromptsSettings


class ReportUseCase:
    _DAILY_SUMMARY_TOP_KEYS = {"今日目标", "今日学习总结", "练习短文", "小红书发布文案", "图片生成提示词"}
    _DAILY_SUMMARY_XHS_KEYS = {"标题", "封面短句", "正文文案", "标签"}
    _DAILY_SUMMARY_IMAGE_KEYS = {"今日目标图", "今日学习总结图", "练习短文图"}

    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        summary_provider: OpenAICompatibleProvider,
        level_service: LevelService,
        prompts: PromptsSettings | None = None,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._summary_provider = summary_provider
        self._level_service = level_service
        self._prompts = prompts or PromptsSettings()

    async def build_weekly_report(
        self,
        *,
        chat_id: str,
        open_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> str:
        return (
            await self.build_weekly_report_envelope(
                chat_id=chat_id,
                open_id=open_id,
                nickname=nickname,
                target_date=target_date,
            )
        ).plain_text

    async def build_weekly_report_envelope(
        self,
        *,
        chat_id: str,
        open_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> MessageEnvelope:
        group = await self._identity_repo.ensure_group(chat_id)
        user = await self._identity_repo.ensure_user(open_id, nickname)

        target_date = target_date or datetime.now().astimezone().date()
        week_key = target_date.strftime("%G-W%V")
        week_anchor = target_date - timedelta(days=target_date.weekday())
        stats = await self._learning_repo.get_weekly_report_stats(
            user_id=user.id,
            group_id=group.id,
            end_date=target_date,
        )
        evidence = LearningEvidence(
            translation_count=stats["translation_count"],
            correction_count=stats["correction_count"],
            task_completion_count=stats["task_completion_count"],
            quiz_average_score=stats["quiz_average_score"],
        )
        level, evidence_json = self._level_service.evaluate(evidence)
        await self._learning_repo.upsert_user_level(
            user_id=user.id,
            group_id=group.id,
            current_level=level,
            evidence_json=evidence_json,
        )
        top_fragments = await self._learning_repo.list_top_error_fragments(
            user_id=user.id,
            group_id=group.id,
            limit=3,
        )
        weak_details = [
            f"{item.source_fragment} -> {item.correct_fragment}"
            for item in top_fragments
        ]
        summary_text = await self._summary_provider.generate_feedback(
            self._prompts.weekly_report_summary.format(
                learning_days=stats["learning_days"],
                task_completion_rate=f"{stats['task_completion_rate']:.0%}",
                correction_count=stats["correction_count"],
                level=level,
            )
        )
        report_json = {
            "week_key": week_key,
            "learning_days": stats["learning_days"],
            "task_completion_rate": stats["task_completion_rate"],
            "translation_count": stats["translation_count"],
            "correction_count": stats["correction_count"],
            "task_completion_count": stats["task_completion_count"],
            "quiz_average_score": stats["quiz_average_score"],
            "latest_quiz_score": stats["latest_quiz_score"],
            "weak_points": stats["weak_points"],
            "weak_details": weak_details,
            "points_earned": stats["points_earned"],
            "current_streak": stats["current_streak"],
            "level": level,
        }
        await self._learning_repo.save_weekly_report(
            biz_week=week_key,
            user_id=user.id,
            report_json=report_json,
            summary_text=summary_text,
        )
        weak_points = "、".join(label_error_type(item) for item in stats["weak_points"]) or "暂无明显高频薄弱项"
        weak_examples = "；".join(weak_details) or "本周没有沉淀新的典型错误片段。"
        level_label = "初级" if level == "beginner" else "中级"
        growth_lines = self._build_weekly_growth_lines(stats=stats, level_label=level_label)
        focus_lines = self._build_weekly_focus_lines(stats=stats)
        plain_text = (
            f"本周复盘 {week_key}\n"
            f"- 本周推进：学习 {stats['learning_days']} 天，完成率 {stats['task_completion_rate']:.0%}\n"
            f"- 这周暴露出来的边界：{weak_points}\n"
            f"- 典型错误：{weak_examples}\n"
            f"- 这周已经长出来的能力：{'；'.join(growth_lines)}\n"
            f"- 下周主攻：{'；'.join(focus_lines)}\n"
            f"- 总结：{summary_text}"
        )
        sections = [
            CardSection(
                title="本周推进",
                lines=[
                    f"学习天数：{stats['learning_days']} 天",
                    f"完成率：{stats['task_completion_rate']:.0%}",
                    f"翻译/纠错：{stats['translation_count']}/{stats['correction_count']}",
                    f"当前等级：{level_label}",
                    f"连续学习：{stats['current_streak']} 天",
                ],
            ),
            CardSection(
                title="这周暴露出来的边界",
                lines=(
                    [label_error_type(item) for item in stats["weak_points"]] + (weak_details[:1] or [])
                )[:3]
                or ["暂无明显高频薄弱项"],
            ),
            CardSection(
                title="这周已经长出来的能力",
                lines=growth_lines,
            ),
            CardSection(
                title="下周主攻",
                lines=focus_lines + [summary_text],
            ),
        ]
        document = CardDocument(
            title="本周复盘",
            subtitle=f"学习 {stats['learning_days']} 天，完成率 {stats['task_completion_rate']:.0%}",
            sections=sections,
            footer_lines=["下周继续沿着同一条主线推进。"],
            metadata={
                "chat_id": chat_id,
                "biz_date": week_anchor.isoformat(),
            },
        )
        card_snapshot = await self._learning_repo.upsert_daily_card_snapshot(
            biz_date=week_anchor,
            user_id=user.id,
            group_id=group.id,
            card_type="weekly_report",
            plain_text=plain_text,
            card_document_json=self._document_to_json(document),
        )
        return MessageEnvelope(
            plain_text=plain_text,
            card_document=document,
            card_type="weekly_report",
            card_snapshot_id=card_snapshot.id,
        )

    async def build_daily_error_digest_envelope(
        self,
        *,
        chat_id: str,
        open_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> MessageEnvelope | None:
        group = await self._identity_repo.ensure_group(chat_id)
        user = await self._identity_repo.ensure_user(open_id, nickname)

        target_date = target_date or datetime.now().astimezone().date()
        digest = await self._learning_repo.get_daily_error_digest(
            user_id=user.id,
            group_id=group.id,
            target_date=target_date,
        )
        total = digest["word_total"] + digest["grammar_total"]
        if total <= 0:
            return None

        repair_items = self._pick_repair_items(digest=digest)
        review_lines = [item["correct_fragment"] for item in repair_items[:2] if item["correct_fragment"]] or ["把今晚修正过的表达明天再说一轮。"]
        plain_lines = [
            f"{target_date.isoformat()} 今晚修正",
            f"- 今天最该修的：{'; '.join(item['source_line'] for item in repair_items)}",
            f"- 正确说法：{'; '.join(item['correct_line'] for item in repair_items)}",
            f"- 明天回捞：{'; '.join(review_lines)}",
        ]
        sections = [
            CardSection(
                title="今天最该修的",
                lines=[item["source_line"] for item in repair_items],
            )
        ]
        sections.append(
            CardSection(
                title="正确说法",
                lines=[item["correct_line"] for item in repair_items],
            )
        )
        sections.append(CardSection(title="明天回捞", lines=review_lines + ["今晚修完后，立刻重说或重写一轮。"]))
        document = CardDocument(
            title="今晚修正",
            subtitle=f"先修最重要的 {len(repair_items)} 个问题",
            sections=sections,
            footer_lines=["今晚修正这一轮，明天继续带着它们开口。"],
            theme="amber",
            metadata={
                "chat_id": chat_id,
                "biz_date": target_date.isoformat(),
            },
        )
        snapshot = await self._learning_repo.upsert_daily_card_snapshot(
            biz_date=target_date,
            user_id=user.id,
            group_id=group.id,
            card_type="error_digest",
            plain_text="\n".join(plain_lines),
            card_document_json=self._document_to_json(document),
        )
        return MessageEnvelope(
            plain_text="\n".join(plain_lines),
            card_document=document,
            card_type="error_digest",
            card_snapshot_id=snapshot.id,
        )

    async def build_daily_progress_envelope(
        self,
        *,
        chat_id: str,
        open_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> MessageEnvelope | None:
        group = await self._identity_repo.ensure_group(chat_id)
        user = await self._identity_repo.ensure_user(open_id, nickname)

        target_date = target_date or datetime.now().astimezone().date()
        stats = await self._learning_repo.get_daily_progress_stats(
            user_id=user.id,
            group_id=group.id,
            target_date=target_date,
        )
        evidence_stats = await self._learning_repo.get_daily_conversation_evidence_stats(
            user_id=user.id,
            group_id=group.id,
            target_date=target_date,
        )
        daily_session = await self._learning_repo.get_daily_session(group_id=group.id, biz_date=target_date)
        recall_results = await self._learning_repo.evaluate_review_candidates_for_day(
            user_id=user.id,
            group_id=group.id,
            biz_date=target_date,
        )
        if (
            not stats["has_activity"]
            and evidence_stats["total_messages"] <= 0
            and evidence_stats["evidence_score"] <= 0
            and not (
                daily_session is not None
                and user.id in {daily_session.role_a_user_id, daily_session.role_b_user_id}
            )
        ):
            return None

        level_label = "初级" if stats["level"] == "beginner" else "中级"
        task_status = (
            "已完成今日任务"
            if stats["today_task_total"] > 0 and stats["today_task_completed"] >= stats["today_task_total"]
            else "今日任务未完成"
        )
        lesson_detail = await self._learning_repo.get_today_lesson_detail(group_id=group.id, biz_date=target_date)
        lesson_id = lesson_detail[0].id if lesson_detail is not None else None
        mastery_level, mastery_reason = self._determine_mastery_level(
            stats=stats,
            evidence_stats=evidence_stats,
            recall_results=recall_results,
        )
        model_summary = await self._build_daily_summary(
            task_status=task_status,
            level_label=level_label,
            stats=stats,
            evidence_stats=evidence_stats,
            mastery_level=mastery_level,
            mastery_reason=mastery_reason,
        )
        duo_status, duo_next_step = self._build_duo_progress(daily_session=daily_session)
        summary_json = {
            "task_status": task_status,
            "stats": stats,
            "evidence_stats": evidence_stats,
            "recall_results": recall_results,
            "mastery_level": mastery_level,
            "mastery_reason": mastery_reason,
            "model_summary": model_summary,
            "duo_status": duo_status,
            "duo_next_step": duo_next_step,
        }
        snapshot = await self._learning_repo.upsert_daily_learning_snapshot(
            biz_date=target_date,
            user_id=user.id,
            group_id=group.id,
            lesson_id=lesson_id,
            summary_json=summary_json,
            mastery_level=mastery_level,
            mastery_reason=mastery_reason,
            model_summary=model_summary,
            activity_score=self._activity_score(stats),
            evidence_score=int(evidence_stats["evidence_score"]),
        )

        evidence_line = (
            f"今天最像真实输出的一句：{'、'.join(evidence_stats['examples'][:2])}"
            if evidence_stats["examples"]
            else "今天主要在推进任务和修正表达。"
        )
        recall_line = (
            f"昨日回捞：{recall_results[0]['content_text']}（{'已复现' if recall_results[0]['recalled_successfully'] else '仍需强化'}）"
            if recall_results
            else "今天没有需要特别回捞的旧内容。"
        )
        next_step_lines = [
            duo_next_step,
            "今晚只修最重要的 1-3 个问题，明天继续带着这些表达开口。",
        ]
        plain_text = "\n".join(
            [
                f"{target_date.isoformat()} 今晚进展",
                f"- 今天到了哪：{duo_status}",
                f"- 当前任务：{task_status}",
                f"- 学习证据：{evidence_line}",
                f"- 回捞状态：{recall_line}",
                f"- 下一步：{'；'.join(next_step_lines)}",
            ]
        )

        sections = [
            CardSection(
                title="今天到了哪",
                lines=[
                    duo_status,
                    f"当前任务：{task_status}",
                    duo_next_step,
                ],
            ),
            CardSection(
                title="学习证据",
                lines=[
                    evidence_line,
                    recall_line,
                    f"掌握判断：{self._mastery_label(mastery_level)}",
                ],
            ),
            CardSection(
                title="下一步",
                lines=next_step_lines,
            ),
        ]
        document = CardDocument(
            title="今晚进展",
            subtitle=duo_status,
            sections=sections,
            footer_lines=["直接在群里继续用英文说/写即可，系统会自动归档。"],
            theme="blue",
            metadata={
                "chat_id": chat_id,
                "biz_date": target_date.isoformat(),
            },
        )
        card_snapshot = await self._learning_repo.upsert_daily_card_snapshot(
            biz_date=target_date,
            user_id=user.id,
            group_id=group.id,
            card_type="progress",
            plain_text=plain_text,
            card_document_json=self._document_to_json(document),
        )
        return MessageEnvelope(
            plain_text=plain_text,
            card_document=document,
            card_type="progress",
            card_snapshot_id=card_snapshot.id,
        )

    async def build_daily_summary_envelope(
        self,
        *,
        chat_id: str,
        open_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> MessageEnvelope | None:
        group = await self._identity_repo.ensure_group(chat_id)
        user = await self._identity_repo.ensure_user(open_id, nickname)

        target_date = target_date or datetime.now().astimezone().date()
        stats = await self._learning_repo.get_daily_progress_stats(
            user_id=user.id,
            group_id=group.id,
            target_date=target_date,
        )
        evidence_stats = await self._learning_repo.get_daily_conversation_evidence_stats(
            user_id=user.id,
            group_id=group.id,
            target_date=target_date,
        )
        recall_results = await self._learning_repo.evaluate_review_candidates_for_day(
            user_id=user.id,
            group_id=group.id,
            biz_date=target_date,
        )
        practice_texts = await self._learning_repo.list_daily_practice_texts(
            biz_date=target_date,
            user_id=user.id,
            group_id=group.id,
            limit=20,
        )
        new_words = await self._learning_repo.list_daily_user_words(
            biz_date=target_date,
            user_id=user.id,
            group_id=group.id,
            limit=30,
        )
        lesson_detail = await self._learning_repo.get_today_lesson_detail(group_id=group.id, biz_date=target_date)
        lesson_id = lesson_detail[0].id if lesson_detail is not None else None
        target_items = (
            await self._learning_repo.get_target_items_for_lesson(lesson_id=lesson_id)
            if lesson_id is not None
            else []
        )
        required_phrases = self._collect_required_phrases(target_items=target_items, limit=8)
        if (
            not practice_texts
            and not recall_results
            and not new_words
            and not stats["has_activity"]
            and evidence_stats["total_messages"] <= 0
        ):
            return None

        lesson_title = ""
        if lesson_detail is not None:
            lesson, content = lesson_detail
            lesson_title = lesson.title or content.title
        daily_goal = self._build_system_daily_goal(lesson_title=lesson_title, required_phrases=required_phrases)
        prompt = self._render_daily_summary_prompt(
            daily_goal=daily_goal,
            required_phrases=required_phrases,
            today_dialogues=practice_texts,
            yesterday_dialogues=recall_results,
            new_words_today=new_words,
        )
        payload = await self._build_daily_summary_payload(
            prompt=prompt,
            daily_goal=daily_goal,
            required_phrases=required_phrases,
            today_dialogues=practice_texts,
            yesterday_dialogues=recall_results,
            new_words_today=new_words,
        )
        if payload is None:
            return None

        mastery_level, mastery_reason = self._determine_mastery_level(
            stats=stats,
            evidence_stats=evidence_stats,
            recall_results=recall_results,
        )
        summary_json = {
            "daily_goal": daily_goal,
            "required_phrases": required_phrases,
            "today_dialogues": practice_texts,
            "yesterday_dialogues": recall_results,
            "new_words_today": new_words,
            "xhs_payload": payload,
            "mastery_level": mastery_level,
            "mastery_reason": mastery_reason,
        }
        await self._learning_repo.upsert_daily_learning_snapshot(
            biz_date=target_date,
            user_id=user.id,
            group_id=group.id,
            lesson_id=lesson_id,
            summary_json=summary_json,
            mastery_level=mastery_level,
            mastery_reason=mastery_reason,
            model_summary=payload["今日学习总结"],
            activity_score=self._activity_score(stats),
            evidence_score=int(evidence_stats["evidence_score"]),
        )

        xhs = payload["小红书发布文案"]
        image_prompts = payload["图片生成提示词"]
        plain_text = "\n".join(
            [
                f"{target_date.isoformat()} Daily Summary",
                f"- Today's Goal: {payload['今日目标']}",
                f"- Study Summary: {payload['今日学习总结']}",
                f"- Practice Passage: {payload['练习短文']}",
                f"- 小红书标题：{xhs['标题']}",
                f"- 封面短句：{xhs['封面短句']}",
                f"- 标签：{' '.join(xhs['标签'])}",
                "- 图片提示词已直接展示在卡片中。",
            ]
        )
        sections = [
            CardSection(title="Today Goal", lines=[payload["今日目标"]]),
            CardSection(title="Today Study Summary", lines=[payload["今日学习总结"]]),
            CardSection(title="Practice Passage", lines=[payload["练习短文"]]),
            CardSection(
                title="小红书发布文案",
                lines=[
                    f"标题：{xhs['标题']}",
                    f"封面短句：{xhs['封面短句']}",
                    f"正文：{xhs['正文文案']}",
                    f"标签：{' '.join(xhs['标签'])}",
                ],
            ),
            CardSection(
                title="Image Prompt · TODAY'S GOAL",
                lines=[
                    image_prompts["今日目标图"],
                ],
            ),
            CardSection(
                title="Image Prompt · TODAY'S STUDY SUMMARY",
                lines=[
                    image_prompts["今日学习总结图"],
                ],
            ),
            CardSection(
                title="Image Prompt · PRACTICE PASSAGE",
                lines=[
                    image_prompts["练习短文图"],
                ],
            ),
        ]
        document = CardDocument(
            title="每日总结",
            subtitle="英语学习日报 + 小红书发布素材",
            sections=sections,
            footer_lines=["图片提示词已完整展示在卡片中，可直接复制。"],
            theme="green",
            metadata={
                "chat_id": chat_id,
                "biz_date": target_date.isoformat(),
                "target_open_id": open_id,
            },
        )
        card_snapshot = await self._learning_repo.upsert_daily_card_snapshot(
            biz_date=target_date,
            user_id=user.id,
            group_id=group.id,
            card_type="daily_summary",
            plain_text=plain_text,
            card_document_json=self._document_to_json(document),
        )
        return MessageEnvelope(
            plain_text=plain_text,
            card_document=document,
            card_type="daily_summary",
            card_snapshot_id=card_snapshot.id,
        )

    def _activity_score(self, stats: dict) -> int:
        return sum(
            int(stats.get(key, 0) or 0)
            for key in [
                "translation_count",
                "correction_count",
                "task_completion_count",
                "review_session_count",
                "quiz_activity_count",
            ]
        )

    def _build_weekly_growth_lines(self, *, stats: dict, level_label: str) -> list[str]:
        lines: list[str] = []
        if stats["learning_days"] > 0:
            lines.append(f"已经保持了 {stats['learning_days']} 天的学习节奏。")
        if stats["correction_count"] > 0:
            lines.append(f"这周愿意暴露问题并主动修正 {stats['correction_count']} 次。")
        if stats["task_completion_rate"] > 0:
            lines.append(f"主线任务完成率达到 {stats['task_completion_rate']:.0%}。")
        if stats["current_streak"] > 0:
            lines.append(f"当前连续学习 {stats['current_streak']} 天，状态还在延续。")
        lines.append(f"当前等级维持在 {level_label}，说明节奏已经建立起来。")
        return lines[:3]

    def _build_weekly_focus_lines(self, *, stats: dict) -> list[str]:
        weak_points = [label_error_type(item) for item in stats["weak_points"]]
        if weak_points:
            return [
                f"下周优先把「{weak_points[0]}」放进真实表达里修正。",
                "继续保持每天一轮双人闭环，不额外加量。",
            ]
        return [
            "下周继续沿着当前主题推进，优先稳住连续性。",
            "保持每天一轮双人闭环，把复用表达带进真实对话。",
        ]

    def _pick_repair_items(self, *, digest: dict) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for item in digest["word_items"]:
            explanation = f"（{item['explanation']}）" if item["explanation"] else ""
            items.append(
                {
                    "source_line": f"表达：{item['source_fragment']}",
                    "correct_line": f"{item['correct_fragment']}{explanation}",
                    "correct_fragment": item["correct_fragment"],
                }
            )
        for item in digest["grammar_items"]:
            explanation = f"（{item['explanation']}）" if item["explanation"] else ""
            items.append(
                {
                    "source_line": f"{label_error_type(item['error_type'])}：{item['source_fragment']}",
                    "correct_line": f"{item['correct_fragment']}{explanation}",
                    "correct_fragment": item["correct_fragment"],
                }
            )
        if not items:
            return [
                {
                    "source_line": "今天的错误点还没有整理出可展示的片段。",
                    "correct_line": "今晚先围绕今天的主题重说一轮。",
                    "correct_fragment": "围绕今天的主题重说一轮",
                }
            ]
        return items[:3]

    def _build_duo_progress(self, *, daily_session) -> tuple[str, str]:
        if daily_session is None:
            return "今天还没有双人 session。", "晨间执行卡发出后，直接开始 A→B 接棒。"
        if daily_session.status == "completed":
            return "今日双人闭环已完成。", "晚上看修正卡，明天继续交换角色。"
        if daily_session.rescue_mode:
            return "今天处于恢复模式。", "只完成最小闭环，不追之前欠下的内容。"
        if daily_session.role_a_status != "completed":
            return (
                f"等待 {daily_session.role_a_label or 'A'} 发起第一棒。",
                f"{daily_session.role_a_label or 'A'} 先用英文发 2-3 句。",
            )
        if daily_session.role_b_user_id is not None and daily_session.role_b_status != "completed":
            return (
                f"{daily_session.role_a_label or 'A'} 已发起，等待 {daily_session.role_b_label or 'B'} 接棒。",
                f"{daily_session.role_b_label or 'B'} 追问、澄清或补充 2 句。",
            )
        return "今日双人进度进行中。", "继续围绕今天主题完成一轮英文互动。"

    def _determine_mastery_level(
        self,
        *,
        stats: dict,
        evidence_stats: dict,
        recall_results: list[dict],
    ) -> tuple[str, str]:
        recall_success = sum(1 for item in recall_results if item["recalled_successfully"])
        recall_ready = True
        if recall_results:
            recall_ready = recall_success >= max(1, len(recall_results) // 2)
        if (
            stats["today_task_completed"] >= max(1, stats["today_task_total"])
            and evidence_stats["target_hit_count"] >= 2
            and recall_ready
        ):
            return "basically_mastered", "今天已经能在练习中复用目标表达，且任务完成度较好。"
        if evidence_stats["english_attempt_count"] > 0 or stats["correction_count"] > 0 or stats["today_task_completed"] > 0:
            return "started_using", "今天已经开始尝试使用英语表达，但还需要更多稳定复现。"
        return "needs_strengthening", "今天有参与，但可用于判断掌握度的有效学习证据仍然偏少。"

    def _mastery_label(self, mastery_level: str) -> str:
        return {
            "started_using": "已开始使用",
            "basically_mastered": "基本掌握",
            "needs_strengthening": "仍需强化",
        }.get(mastery_level, mastery_level)

    async def _build_daily_summary(
        self,
        *,
        task_status: str,
        level_label: str,
        stats: dict,
        evidence_stats: dict,
        mastery_level: str,
        mastery_reason: str,
    ) -> str:
        prompt = self._prompts.daily_progress_summary.format(
            task_status=task_status,
            level_label=level_label,
            english_attempt_count=evidence_stats["english_attempt_count"],
            target_hit_count=evidence_stats["target_hit_count"],
            correction_count=stats["correction_count"],
            today_task_completed=stats["today_task_completed"],
            today_task_total=stats["today_task_total"],
            mastery_label=self._mastery_label(mastery_level),
            mastery_reason=mastery_reason,
        )
        try:
            return await self._summary_provider.generate_feedback(prompt)
        except Exception:
            return f"今天状态为{task_status}，掌握度判断为{self._mastery_label(mastery_level)}。"

    def _collect_required_phrases(self, *, target_items: list[Any], limit: int = 8) -> list[str]:
        phrases: list[str] = []
        for item in target_items:
            text = (getattr(item, "text", "") or "").strip()
            if not text or text in phrases:
                continue
            phrases.append(text)
            if len(phrases) >= limit:
                break
        return phrases

    def _build_system_daily_goal(self, *, lesson_title: str, required_phrases: list[str]) -> str:
        title = lesson_title.strip() or "today's communication task"
        if required_phrases:
            selected = ", ".join(required_phrases[:3])
            return (
                f"Practice the theme \"{title}\" in a real work-chat scenario, and naturally reuse "
                f"{selected} in your own responses."
            )
        return f"Practice the theme \"{title}\" in a real work-chat scenario and complete one full English exchange."

    def _render_daily_summary_prompt(
        self,
        *,
        daily_goal: str,
        required_phrases: list[str],
        today_dialogues: list[str],
        yesterday_dialogues: list[dict[str, Any]],
        new_words_today: list[str],
    ) -> str:
        template = self._prompts.daily_summary_xhs_prompt
        rendered = template
        replacements = {
            "daily_goal": daily_goal,
            "required_phrases": self._format_lines_for_prompt(required_phrases, empty_text="(none)"),
            "today_dialogues": self._format_lines_for_prompt(today_dialogues, empty_text="(none)", max_lines=16),
            "yesterday_dialogues": self._format_recall_lines(yesterday_dialogues),
            "new_words_today": self._format_lines_for_prompt(new_words_today, empty_text="(none)", max_lines=20),
        }
        for key, value in replacements.items():
            rendered = rendered.replace(f"{{{key}}}", value)
        return rendered

    async def _build_daily_summary_payload(
        self,
        *,
        prompt: str,
        daily_goal: str,
        required_phrases: list[str],
        today_dialogues: list[str],
        yesterday_dialogues: list[dict[str, Any]],
        new_words_today: list[str],
    ) -> dict[str, Any] | None:
        first_raw: str = ""
        for attempt in range(2):
            try:
                if attempt == 0:
                    raw = await self._summary_provider.generate_feedback(prompt)
                    first_raw = raw
                else:
                    repair_prompt = (
                        "请将下面内容修复为严格 JSON，且只保留要求字段，不添加解释。\n\n"
                        f"{first_raw}"
                    )
                    raw = await self._summary_provider.generate_feedback(repair_prompt)
            except Exception:
                continue
            parsed = self._parse_daily_summary_payload(raw)
            if parsed is not None:
                return parsed
        return self._build_daily_summary_fallback(
            daily_goal=daily_goal,
            required_phrases=required_phrases,
            today_dialogues=today_dialogues,
            yesterday_dialogues=yesterday_dialogues,
            new_words_today=new_words_today,
        )

    def _parse_daily_summary_payload(self, raw: str) -> dict[str, Any] | None:
        text = raw.strip()
        if text.startswith("```"):
            lines = [line for line in text.splitlines() if not line.strip().startswith("```")]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if set(payload.keys()) != self._DAILY_SUMMARY_TOP_KEYS:
            return None
        for key in ["今日目标", "今日学习总结", "练习短文"]:
            if not isinstance(payload.get(key), str):
                return None
            payload[key] = payload[key].strip()

        xhs = payload.get("小红书发布文案")
        if not isinstance(xhs, dict) or set(xhs.keys()) != self._DAILY_SUMMARY_XHS_KEYS:
            return None
        if not isinstance(xhs.get("标签"), list) or not all(isinstance(item, str) for item in xhs["标签"]):
            return None
        payload["小红书发布文案"] = {
            "标题": str(xhs.get("标题", "")).strip(),
            "封面短句": str(xhs.get("封面短句", "")).strip(),
            "正文文案": str(xhs.get("正文文案", "")).strip(),
            "标签": [item.strip() for item in xhs["标签"] if item and item.strip()],
        }

        prompts = payload.get("图片生成提示词")
        if not isinstance(prompts, dict) or set(prompts.keys()) != self._DAILY_SUMMARY_IMAGE_KEYS:
            return None
        payload["图片生成提示词"] = {
            "今日目标图": str(prompts.get("今日目标图", "")).strip(),
            "今日学习总结图": str(prompts.get("今日学习总结图", "")).strip(),
            "练习短文图": str(prompts.get("练习短文图", "")).strip(),
        }
        return payload

    def _build_daily_summary_fallback(
        self,
        *,
        daily_goal: str,
        required_phrases: list[str],
        today_dialogues: list[str],
        yesterday_dialogues: list[dict[str, Any]],
        new_words_today: list[str],
    ) -> dict[str, Any]:
        today_points = "; ".join(today_dialogues[:3]) or "I completed focused English practice tasks."
        recall_line = "; ".join(
            [
                f"{item['content_text']} ({'recalled' if item['recalled_successfully'] else 'needs more practice'})"
                for item in yesterday_dialogues[:2]
                if item.get("content_text")
            ]
        ) or "No explicit recall notes were captured today."
        phrases_line = ", ".join(required_phrases[:3]) or "core expressions from today's lesson"
        words_line = ", ".join(new_words_today[:5]) or "no extra words logged"
        study_summary = (
            "Today I stayed on the main lesson goal and practiced with concrete outputs. "
            f"My key practice lines were: {today_points}. "
            f"I also reviewed yesterday's items: {recall_line}. "
            f"I tried to reuse {phrases_line}, and I logged {words_line}. "
            "Some sentences still need smoother transitions, so I will keep refining the same topic tomorrow."
        )
        practice_passage = (
            "During today's practice, I focused on communicating clearly in a realistic work scenario. "
            f"My target was to follow this goal: {daily_goal} "
            f"I actively reused these expressions: {phrases_line}. "
            "I wrote and spoke in short rounds, then adjusted wording to sound more natural and precise. "
            f"I also kept an eye on yesterday's recall points: {recall_line}. "
            f"New words from today included: {words_line}. "
            "The next step is to keep the same context tomorrow and push for better fluency with fewer pauses."
        )
        xhs_body = (
            "今天按主线完成了一轮英语练习。我把重点放在真实场景输出上，先写再改，再复述。"
            f"今天重点复用了：{phrases_line}。"
            f"回捞结果：{recall_line}。"
            "整体比昨天更连贯，但衔接词和句子自然度还要继续打磨。"
        )
        image_prompts = {
            "今日目标图": self._build_image_prompt(title="TODAY'S GOAL", body=daily_goal),
            "今日学习总结图": self._build_image_prompt(title="TODAY'S STUDY SUMMARY", body=study_summary),
            "练习短文图": self._build_image_prompt(title="PRACTICE PASSAGE", body=practice_passage),
        }
        return {
            "今日目标": daily_goal,
            "今日学习总结": study_summary,
            "练习短文": practice_passage,
            "小红书发布文案": {
                "标题": "英语打卡第N天：今天稳住主线",
                "封面短句": "今日复盘已完成",
                "正文文案": xhs_body,
                "标签": ["#英语学习", "#英语打卡", "#今日复盘"],
            },
            "图片生成提示词": image_prompts,
        }

    def _build_image_prompt(self, *, title: str, body: str) -> str:
        content = " ".join(body.split())
        return (
            "premium minimalist chalkboard editorial poster for English learning, "
            "deep green chalkboard with subtle gradient and fine chalk dust texture, "
            "ultra clean and restrained composition, elegant and calm high-end design, "
            "inspired by Apple keynote slides, editorial typography style, strong negative space, "
            "portrait 4:5 ratio, strong typography hierarchy, grid-based layout, subtle asymmetry with balance, "
            "clean chalk lettering but highly controlled, high legibility, no distortion, no clutter, "
            "no excessive doodles, no childish illustration style, no classroom poster style, no flashy decoration, "
            "no modern infographic style, focus on typography spacing negative space readability, "
            "ultra high resolution, premium poster quality, Xiaohongshu cover ready, "
            f'use subtitle \"{title}\", embed main text: \"{content}\", text must be the visual focus and clearly readable'
        )

    def _format_recall_lines(self, items: list[dict[str, Any]]) -> str:
        lines = [
            f"{item['content_text']} ({'recalled' if item['recalled_successfully'] else 'needs more practice'})"
            for item in items[:10]
            if item.get("content_text")
        ]
        return self._format_lines_for_prompt(lines, empty_text="(none)", max_lines=10)

    def _format_lines_for_prompt(self, values: list[str], *, empty_text: str, max_lines: int = 10) -> str:
        if not values:
            return empty_text
        rows = []
        for item in values[:max_lines]:
            clean = " ".join(str(item).split())
            if not clean:
                continue
            rows.append(f"- {clean[:220]}")
        return "\n".join(rows) if rows else empty_text

    def _document_to_json(self, document: CardDocument) -> dict:
        return asdict(document)
