from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from src.domain.services.leveling import LearningEvidence, LevelService
from src.domain.services.error_taxonomy import label_error_type
from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider
from src.infrastructure.settings.models import PromptsSettings


class ReportUseCase:
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

    def _document_to_json(self, document: CardDocument) -> dict:
        return asdict(document)
