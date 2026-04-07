from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from src.domain.services.leveling import LearningEvidence, LevelService
from src.domain.services.error_taxonomy import label_error_type
from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository
from src.infrastructure.providers.llm_openai import OpenAICompatibleProvider


class ReportUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        summary_provider: OpenAICompatibleProvider,
        level_service: LevelService,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._summary_provider = summary_provider
        self._level_service = level_service

    async def build_weekly_report(
        self,
        *,
        qq_group_id: str,
        qq_user_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> str:
        return (
            await self.build_weekly_report_envelope(
                qq_group_id=qq_group_id,
                qq_user_id=qq_user_id,
                nickname=nickname,
                target_date=target_date,
            )
        ).plain_text

    async def build_weekly_report_envelope(
        self,
        *,
        qq_group_id: str,
        qq_user_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> MessageEnvelope:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        if not await self._identity_repo.is_enrolled(user.id, group.id):
            return MessageEnvelope(plain_text="你还没有报名学习。")

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
            (
                "请生成一句简洁的英语学习周报鼓励语，语气积极，不超过 50 字。"
                f" 学习天数：{stats['learning_days']}，完成率：{stats['task_completion_rate']:.0%}，"
                f" 纠错次数：{stats['correction_count']}，当前等级：{level}。"
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
        plain_text = (
            f"周报 {week_key}\n"
            f"- 学习天数：{stats['learning_days']} 天\n"
            f"- 本周完成率：{stats['task_completion_rate']:.0%}\n"
            f"- 翻译/纠错次数：{stats['translation_count']}/{stats['correction_count']}\n"
            f"- 周测平均分：{stats['quiz_average_score']:.1f}，最近一次：{stats['latest_quiz_score']}\n"
            f"- 当前等级：{level_label}（{level}）\n"
            f"- 连续学习：{stats['current_streak']} 天，累计积分：{stats['points_earned']}\n"
            f"- 薄弱点：{weak_points}\n"
            f"- 典型错误：{weak_examples}\n"
            f"- 总结：{summary_text}"
        )
        sections = [
            CardSection(
                title="本周概览",
                lines=[
                    f"学习天数：{stats['learning_days']} 天",
                    f"完成率：{stats['task_completion_rate']:.0%}",
                    f"翻译/纠错次数：{stats['translation_count']}/{stats['correction_count']}",
                    f"周测平均分：{stats['quiz_average_score']:.1f}",
                    f"最近一次周测：{stats['latest_quiz_score']}",
                    f"当前等级：{level_label}（{level}）",
                    f"连续学习：{stats['current_streak']} 天",
                    f"累计积分：{stats['points_earned']}",
                ],
            ),
            CardSection(
                title="薄弱点",
                lines=[label_error_type(item) for item in stats["weak_points"]] or ["暂无明显高频薄弱项"],
            ),
            CardSection(
                title="典型错误",
                lines=weak_details or ["本周没有沉淀新的典型错误片段。"],
            ),
            CardSection(
                title="本周总结",
                lines=[summary_text],
            ),
        ]
        document = CardDocument(
            title=f"{week_key} 学习周报",
            subtitle=f"学习 {stats['learning_days']} 天，完成率 {stats['task_completion_rate']:.0%}",
            sections=sections,
            footer_lines=["继续保持，明天可以发送 今日任务 或 复习一下。"],
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
        qq_group_id: str,
        qq_user_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> MessageEnvelope | None:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        if not await self._identity_repo.is_enrolled(user.id, group.id):
            return None

        target_date = target_date or datetime.now().astimezone().date()
        digest = await self._learning_repo.get_daily_error_digest(
            user_id=user.id,
            group_id=group.id,
            target_date=target_date,
        )
        total = digest["word_total"] + digest["grammar_total"]
        if total <= 0:
            return None

        plain_lines = [
            f"{target_date.isoformat()} 今日纠错整理",
            f"- 错词/表达：{digest['word_total']} 个",
            f"- 语法问题：{digest['grammar_total']} 个",
        ]
        sections = [
            CardSection(
                title="今日概览",
                lines=[
                    f"今天共识别 {total} 个可复习错误",
                    "建议先看错词，再看语法。",
                ],
            )
        ]

        if digest["word_items"]:
            word_lines = []
            for item in digest["word_items"]:
                line = f"{item['source_fragment']} -> {item['correct_fragment']}"
                if item["explanation"]:
                    line += f"（{item['explanation']}）"
                word_lines.append(line)
                plain_lines.append(f"- 错词：{line}")
            sections.append(CardSection(title="错词/表达", lines=word_lines))

        if digest["grammar_items"]:
            grammar_lines = []
            for item in digest["grammar_items"]:
                label = label_error_type(item["error_type"])
                line = f"{label}：{item['source_fragment']} -> {item['correct_fragment']}"
                if item["explanation"]:
                    line += f"（{item['explanation']}）"
                grammar_lines.append(line)
                plain_lines.append(f"- 语法：{line}")
            sections.append(CardSection(title="语法问题", lines=grammar_lines))

        sections.append(
            CardSection(
                title="今晚建议",
                lines=["发送 复习一下 开始针对今天的问题练习。"],
            )
        )
        document = CardDocument(
            title="今日纠错整理",
            subtitle=f"错词 {digest['word_total']} 个 · 语法问题 {digest['grammar_total']} 个",
            sections=sections,
            footer_lines=["固定命令：复习一下"],
            theme="amber",
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
        qq_group_id: str,
        qq_user_id: str,
        nickname: str,
        target_date: date | None = None,
    ) -> MessageEnvelope | None:
        group = await self._identity_repo.ensure_group(qq_group_id)
        user = await self._identity_repo.ensure_user(qq_user_id, nickname)
        if not await self._identity_repo.is_enrolled(user.id, group.id):
            return None

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
        if (
            not stats["has_activity"]
            and evidence_stats["total_messages"] <= 0
            and evidence_stats["evidence_score"] <= 0
        ):
            return None

        level_label = "初级" if stats["level"] == "beginner" else "中级"
        task_status = (
            "已完成今日任务"
            if stats["today_task_total"] > 0 and stats["today_task_completed"] >= stats["today_task_total"]
            else "今日任务未完成"
        )
        quiz_status = "已进行" if stats["quiz_activity_count"] > 0 else "未开始"
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
        summary_json = {
            "task_status": task_status,
            "stats": stats,
            "evidence_stats": evidence_stats,
            "recall_results": recall_results,
            "mastery_level": mastery_level,
            "mastery_reason": mastery_reason,
            "model_summary": model_summary,
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

        plain_text = "\n".join(
            [
                f"{target_date.isoformat()} 今日学习进度",
                f"- 状态：{task_status}",
                f"- 今日发言：{evidence_stats['total_messages']}",
                f"- 英语尝试/目标词命中：{evidence_stats['english_attempt_count']}/{evidence_stats['target_hit_count']}",
                f"- 翻译/纠错：{stats['translation_count']}/{stats['correction_count']}",
                f"- 新增错词/语法：{stats['word_error_count']}/{stats['grammar_error_count']}",
                f"- 今日任务：{stats['today_task_completed']}/{stats['today_task_total']}",
                f"- 复习次数：{stats['review_session_count']}",
                f"- 今日积分：{stats['points_earned']}",
                f"- 连续学习：{stats['current_streak']} 天",
                f"- 当前等级：{level_label}",
                f"- 掌握判断：{self._mastery_label(mastery_level)}",
                f"- 判断依据：{mastery_reason}",
                f"- 总结：{model_summary}",
                *(
                    [f"- 昨日回捞：{item['content_text']}（{'已复现' if item['recalled_successfully'] else '仍需强化'}）" for item in recall_results]
                    if recall_results
                    else []
                ),
            ]
        )

        sections = [
            CardSection(
                title="今日参与概览",
                lines=[
                    f"今日发言：{evidence_stats['total_messages']}",
                    f"英语尝试：{evidence_stats['english_attempt_count']}",
                    f"目标词命中：{evidence_stats['target_hit_count']}",
                    f"学习提问：{evidence_stats['question_asked_count']}",
                ],
            ),
            CardSection(
                title="今日数据",
                lines=[
                    f"翻译次数：{stats['translation_count']}",
                    f"纠错次数：{stats['correction_count']}",
                    f"新增错词：{stats['word_error_count']}",
                    f"新增语法错误：{stats['grammar_error_count']}",
                ],
            ),
            CardSection(
                title="任务进度",
                lines=[
                    f"今日任务：{stats['today_task_completed']}/{stats['today_task_total']}",
                    f"复习次数：{stats['review_session_count']}",
                    f"周测状态：{quiz_status}",
                ],
            ),
            CardSection(
                title="学习证据",
                lines=[
                    f"典型表达：{'、'.join(evidence_stats['examples']) if evidence_stats['examples'] else '今天主要以完成任务和纠错为主。'}",
                    f"学习证据评分：{evidence_stats['evidence_score']}",
                ],
            ),
            CardSection(
                title="掌握判断",
                lines=[
                    f"掌握度：{self._mastery_label(mastery_level)}",
                    mastery_reason,
                    model_summary,
                    f"当前等级：{level_label}",
                    f"今日新增积分：{stats['points_earned']} · 连续学习：{stats['current_streak']} 天",
                ],
            ),
            CardSection(
                title="昨日回捞表现",
                lines=[
                    f"{item['content_text']}：{'已复现' if item['recalled_successfully'] else '仍需强化'}"
                    for item in recall_results
                ] or ["今天没有需要回捞的历史内容。"],
            ),
            CardSection(
                title="下一步",
                lines=[
                    "如果还没完成任务，发送 今日任务",
                    "如果想巩固今天错误，发送 复习一下",
                ],
            ),
        ]
        document = CardDocument(
            title="今日学习进度",
            subtitle=task_status,
            sections=sections,
            footer_lines=["固定命令：今日任务 / 复习一下 / 开始周测"],
            theme="blue",
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
        prompt = (
            "请用不超过 60 字生成一段英语学习日总结，语气积极、具体。"
            f" 状态：{task_status}；等级：{level_label}；"
            f" 英语尝试：{evidence_stats['english_attempt_count']}；目标词命中：{evidence_stats['target_hit_count']}；"
            f" 纠错次数：{stats['correction_count']}；任务完成：{stats['today_task_completed']}/{stats['today_task_total']}；"
            f" 掌握度：{self._mastery_label(mastery_level)}；依据：{mastery_reason}"
        )
        try:
            return await self._summary_provider.generate_feedback(prompt)
        except Exception:
            return f"今天状态为{task_status}，掌握度判断为{self._mastery_label(mastery_level)}。"

    def _document_to_json(self, document: CardDocument) -> dict:
        return asdict(document)
