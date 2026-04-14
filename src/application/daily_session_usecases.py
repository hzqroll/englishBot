from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime

from src.domain.value_objects.messaging import CardDocument, CardSection, MessageEnvelope
from src.infrastructure.db.repositories.identity import IdentityRepository
from src.infrastructure.db.repositories.learning import LearningRepository


@dataclass(slots=True)
class DailySessionReminder:
    envelope: MessageEnvelope
    mention_open_id: str | None = None
    mention_user_id: int | None = None


class DailySessionUseCase:
    def __init__(
        self,
        *,
        identity_repo: IdentityRepository,
        learning_repo: LearningRepository,
        voice_required_weekdays: tuple[int, ...] = (1, 4),
        monthly_benchmark_weekday: int = 6,
        rescue_lookback_days: int = 2,
    ) -> None:
        self._identity_repo = identity_repo
        self._learning_repo = learning_repo
        self._voice_required_weekdays = tuple(sorted(set(voice_required_weekdays)))
        self._monthly_benchmark_weekday = monthly_benchmark_weekday
        self._rescue_lookback_days = max(rescue_lookback_days, 1)

    async def ensure_daily_session(self, *, chat_id: str, biz_date: date | None = None):
        group = await self._identity_repo.ensure_group(chat_id)
        target_date = biz_date or date.today()
        lesson_detail = await self._learning_repo.get_today_lesson_detail(
            group_id=group.id,
            biz_date=target_date,
        )
        if lesson_detail is None:
            raise ValueError("今日任务尚未生成。")

        lesson, content = lesson_detail
        target_items = await self._learning_repo.get_target_items_for_lesson(lesson_id=lesson.id)
        tasks = await self._learning_repo.get_tasks_for_lesson(lesson_id=lesson.id)
        existing = await self._learning_repo.get_daily_session(group_id=group.id, biz_date=target_date)
        recent_sessions = await self._learning_repo.list_recent_daily_sessions(
            group_id=group.id,
            before_date=target_date,
            limit=max(self._rescue_lookback_days, 2),
        )
        role_a, role_b = await self._pick_roles(group_id=group.id, previous_session=recent_sessions[0] if recent_sessions else None)
        rescue_mode = self._should_enter_rescue_mode(recent_sessions)
        voice_required = target_date.weekday() in self._voice_required_weekdays
        benchmark_required = target_date.weekday() == self._monthly_benchmark_weekday
        required_chunks = self._build_required_chunks(
            target_items=target_items,
            yesterday_review=(lesson.package_snapshot_json or {}).get("yesterday_review", []),
        )
        capture_prompt = tasks[0].prompt if tasks else f"围绕「{lesson.title or content.title}」完成一轮英文互动。"

        role_a_status = (
            existing.role_a_status
            if existing is not None and existing.role_a_user_id == (role_a.id if role_a else None)
            else "pending"
        )
        role_b_status = (
            existing.role_b_status
            if existing is not None and existing.role_b_user_id == (role_b.id if role_b else None)
            else "pending"
        )
        summary_json = dict(existing.summary_json or {}) if existing is not None else {"evidences": []}
        status = self._derive_status(
            role_a_status=role_a_status,
            role_b_status=role_b_status,
            has_role_b=role_b is not None,
            rescue_mode=rescue_mode,
            benchmark_required=benchmark_required,
            existing_status=existing.status if existing is not None else None,
        )

        session = await self._learning_repo.upsert_daily_session(
            group_id=group.id,
            biz_date=target_date,
            lesson_id=lesson.id,
            title=lesson.title or content.title,
            role_a_user_id=role_a.id if role_a else None,
            role_a_label=role_a.nickname if role_a else "A",
            role_a_status=role_a_status,
            role_b_user_id=role_b.id if role_b else None,
            role_b_label=role_b.nickname if role_b else "B",
            role_b_status=role_b_status,
            required_chunks_json=required_chunks,
            capture_prompt=capture_prompt,
            rescue_mode=rescue_mode,
            voice_required=voice_required,
            benchmark_required=benchmark_required,
            status=status,
            summary_json=summary_json,
        )
        return session, (lesson, content), target_items, tasks

    async def build_execution_envelope(
        self,
        *,
        chat_id: str,
        biz_date: date | None = None,
    ) -> MessageEnvelope:
        session, lesson_detail, _, _ = await self.ensure_daily_session(chat_id=chat_id, biz_date=biz_date)
        lesson, content = lesson_detail

        theme_tags = []
        if session.rescue_mode:
            theme_tags.append("恢复模式")
        if session.voice_required:
            theme_tags.append("语音日")
        if session.benchmark_required:
            theme_tags.append("benchmark")
        subtitle = " · ".join(theme_tags) if theme_tags else "今日双人执行卡"

        goal = (
            "先恢复连续性，完成一轮最小英文互动。"
            if session.rescue_mode
            else f"能围绕「{lesson.title or content.title}」完成一轮工作场景英文互动。"
        )
        action_lines = self._build_action_lines(session=session)
        completion_lines = self._build_completion_lines(session=session)
        footer_lines = [
            "看到卡片后直接开始，不需要先发命令。",
            "系统会根据白天的英文消息自动归档，并在晚上生成修正反馈。",
        ]

        document = CardDocument(
            title=f"Day {session.biz_date.strftime('%m/%d')} | {session.title or content.title}",
            subtitle=subtitle,
            sections=[
                CardSection(title="今日目标", lines=[goal]),
                CardSection(
                    title="今日角色",
                    lines=[
                        f"A 发起：{session.role_a_label or '待定'}",
                        f"B 接棒：{session.role_b_label or '待定'}",
                        "明天自动交换角色。",
                    ],
                ),
                CardSection(
                    title="必须复用",
                    lines=session.required_chunks_json or ["今天至少复用 1 个旧表达。"],
                ),
                CardSection(title="今天动作", lines=action_lines),
                CardSection(title="完成标准", lines=completion_lines),
            ],
            footer_lines=footer_lines,
            theme="amber" if session.rescue_mode else ("green" if session.voice_required else "blue"),
            metadata={
                "chat_id": chat_id,
                "biz_date": session.biz_date.isoformat(),
            },
        )
        plain_text = "\n".join(
            [
                f"Day {session.biz_date.strftime('%m/%d')} | {session.title or content.title}",
                f"今日目标：{goal}",
                f"A 发起：{session.role_a_label or '待定'}",
                f"B 接棒：{session.role_b_label or '待定'}",
                "必须复用：",
                *[f"- {line}" for line in (session.required_chunks_json or ["至少复用 1 个旧表达"])],
                "今天动作：",
                *[f"- {line}" for line in action_lines],
                "完成标准：",
                *[f"- {line}" for line in completion_lines],
            ]
        )
        snapshot = await self._learning_repo.upsert_daily_card_snapshot(
            biz_date=session.biz_date,
            group_id=(await self._identity_repo.ensure_group(chat_id)).id,
            card_type="daily_session",
            plain_text=plain_text,
            card_document_json=asdict(document),
        )
        return MessageEnvelope(
            plain_text=plain_text,
            card_document=document,
            card_type="daily_session",
            card_snapshot_id=snapshot.id,
        )

    async def build_baton_reminder(
        self,
        *,
        chat_id: str,
        biz_date: date | None = None,
        phase: str = "midday",
    ) -> DailySessionReminder | None:
        try:
            session, _, _, _ = await self.ensure_daily_session(chat_id=chat_id, biz_date=biz_date)
        except ValueError:
            return None
        if session.status == "completed":
            return None

        target_user_id: int | None
        target_label: str
        reason: str
        if session.role_a_status != "completed":
            target_user_id = session.role_a_user_id
            target_label = session.role_a_label or "A"
            reason = "还没看到今天的第一棒英文发起。"
        elif session.role_b_user_id is not None and session.role_b_status != "completed":
            target_user_id = session.role_b_user_id
            target_label = session.role_b_label or "B"
            reason = "A 已经发起，轮到你接棒追问或补充。"
        else:
            return None

        target_user = await self._identity_repo.get_user_by_id(target_user_id) if target_user_id else None
        if target_user is None:
            return None

        title = "中午接棒提醒" if phase == "midday" else "晚间接棒提醒"
        document = CardDocument(
            title=title,
            subtitle=session.title or "双人学习提醒",
            sections=[
                CardSection(
                    title="现在该做什么",
                    lines=[
                        f"{target_label}：{reason}",
                        f"今天必须复用：{', '.join(session.required_chunks_json[:2]) or '1 个旧表达'}",
                    ],
                )
            ],
            footer_lines=["直接在群里发英文即可，系统会自动记完成。"],
            theme="amber",
            metadata={
                "chat_id": chat_id,
                "biz_date": session.biz_date.isoformat(),
            },
        )
        plain_text = f"{title}\n{target_label}：{reason}\n直接在群里发英文即可。"
        return DailySessionReminder(
            envelope=MessageEnvelope(plain_text=plain_text, card_document=document, card_type="session_reminder"),
            mention_open_id=target_user.open_id,
            mention_user_id=target_user.id,
        )

    async def claim_baton(
        self,
        *,
        chat_id: str,
        actor_open_id: str,
        biz_date: date | None = None,
    ) -> str:
        group = await self._identity_repo.ensure_group(chat_id)
        actor = await self._identity_repo.get_user_by_open_id(actor_open_id)
        if actor is None:
            return "未识别到你的账号，请直接在群里发英文开始。"
        target_date = biz_date or date.today()
        session = await self._learning_repo.get_daily_session(group_id=group.id, biz_date=target_date)
        if session is None:
            return "今天还没有任务卡，稍后再试。"

        summary_json = dict(session.summary_json or {})
        summary_json["last_claim"] = {
            "open_id": actor_open_id,
            "user_id": actor.id,
            "at": datetime.now(UTC).isoformat(),
        }
        await self._learning_repo.update_daily_session(
            session_id=session.id,
            summary_json=summary_json,
        )

        if session.role_a_user_id == actor.id and session.role_a_status != "completed":
            return "已接棒。你是今天第一棒，直接发 2-3 句英文即可。"
        if session.role_b_user_id == actor.id and session.role_a_status == "completed" and session.role_b_status != "completed":
            return "已接棒。轮到你追问或补充 2 句英文。"
        return "已记录你的接棒。直接在群里发英文即可，系统会自动归档。"

    async def enter_rescue_mode(
        self,
        *,
        chat_id: str,
        actor_open_id: str,
        biz_date: date | None = None,
    ) -> str:
        group = await self._identity_repo.ensure_group(chat_id)
        target_date = biz_date or date.today()
        session = await self._learning_repo.get_daily_session(group_id=group.id, biz_date=target_date)
        if session is None:
            return "今天还没有任务卡，稍后再试。"
        if session.status == "completed":
            return "今天已经完成，不需要切换保底版。"

        summary_json = dict(session.summary_json or {})
        summary_json["manual_rescue"] = {
            "open_id": actor_open_id,
            "at": datetime.now(UTC).isoformat(),
        }
        await self._learning_repo.update_daily_session(
            session_id=session.id,
            rescue_mode=True,
            status="rescue",
            summary_json=summary_json,
        )
        return "已切到保底版。今天按最小闭环完成一轮即可。"

    async def remind_later(
        self,
        *,
        chat_id: str,
        actor_open_id: str,
        biz_date: date | None = None,
    ) -> str:
        group = await self._identity_repo.ensure_group(chat_id)
        target_date = biz_date or date.today()
        session = await self._learning_repo.get_daily_session(group_id=group.id, biz_date=target_date)
        if session is None:
            return "今天还没有任务卡，稍后再试。"

        summary_json = dict(session.summary_json or {})
        records = list(summary_json.get("remind_later_requests", []))
        records.append({"open_id": actor_open_id, "at": datetime.now(UTC).isoformat()})
        summary_json["remind_later_requests"] = records[-10:]
        await self._learning_repo.update_daily_session(
            session_id=session.id,
            summary_json=summary_json,
        )
        return "好的，晚点我会再提醒一次。"

    async def record_message_event(
        self,
        *,
        group_id: int,
        user_id: int,
        message_event_id: int,
        message_text: str,
        message_type: str,
        evidence_types: set[str],
        biz_date: date | None = None,
    ) -> None:
        target_date = biz_date or date.today()
        session = await self._learning_repo.get_active_daily_session(group_id=group_id, biz_date=target_date)
        if session is None:
            return

        is_voice = message_type != "text"
        is_relevant = self._is_relevant_message(
            session=session,
            message_text=message_text,
            message_type=message_type,
            evidence_types=evidence_types,
        )
        if not is_relevant:
            return

        role_a_status = session.role_a_status
        role_b_status = session.role_b_status
        touched_role: str | None = None

        if session.role_a_user_id == user_id and session.role_a_status != "completed":
            role_a_status = "completed"
            touched_role = "role_a"
        elif (
            session.role_b_user_id == user_id
            and session.role_a_status == "completed"
            and session.role_b_status != "completed"
        ):
            role_b_status = "completed"
            touched_role = "role_b"
        else:
            return

        evidence_entry = {
            "event_id": message_event_id,
            "user_id": user_id,
            "role": touched_role,
            "message_type": message_type,
            "is_voice": is_voice,
            "evidence_types": sorted(evidence_types),
        }
        summary_json = dict(session.summary_json or {})
        evidences = list(summary_json.get("evidences", []))
        if any(item.get("event_id") == message_event_id for item in evidences):
            return
        evidences.append(evidence_entry)
        summary_json["evidences"] = evidences[-10:]
        status = self._derive_status(
            role_a_status=role_a_status,
            role_b_status=role_b_status,
            has_role_b=session.role_b_user_id is not None,
            rescue_mode=session.rescue_mode,
            benchmark_required=session.benchmark_required,
            existing_status=session.status,
        )

        await self._learning_repo.update_daily_session(
            session_id=session.id,
            role_a_status=role_a_status,
            role_b_status=role_b_status,
            status=status,
            summary_json=summary_json,
        )

    async def _pick_roles(self, *, group_id: int, previous_session) -> tuple[object | None, object | None]:
        active_users = await self._identity_repo.list_group_active_users(group_id)
        enrolled_users = await self._identity_repo.list_enrolled_users(group_id)
        ordered: list[object] = []
        seen: set[int] = set()
        for user in [*active_users, *enrolled_users]:
            if user.id in seen:
                continue
            seen.add(user.id)
            ordered.append(user)

        if not ordered:
            return None, None
        if len(ordered) == 1:
            return ordered[0], None
        if previous_session is not None:
            previous_ids = [previous_session.role_b_user_id, previous_session.role_a_user_id]
            rotated = [next((user for user in ordered if user.id == user_id), None) for user_id in previous_ids]
            if rotated[0] is not None and rotated[1] is not None:
                return rotated[0], rotated[1]
        return ordered[0], ordered[1]

    def _build_required_chunks(self, *, target_items, yesterday_review: list[dict]) -> list[str]:
        items: list[str] = []
        for item in target_items:
            if item.target_role == "core_chunk" and item.text:
                items.append(item.text)
        for item in yesterday_review:
            text = (item.get("correct_text") or item.get("content_text") or "").strip()
            if text:
                items.append(text)
        for item in target_items:
            if item.target_role != "core_chunk" and item.text:
                items.append(item.text)
        deduped: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = item.strip()
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(normalized)
            if len(deduped) >= 3:
                break
        return deduped

    def _should_enter_rescue_mode(self, recent_sessions: list) -> bool:
        if not recent_sessions:
            return False
        latest = recent_sessions[0]
        if latest.role_a_status != "completed" and latest.role_b_status != "completed":
            return True

        incomplete_counts: dict[int, int] = {}
        for session in recent_sessions[: self._rescue_lookback_days]:
            for user_id, status in (
                (session.role_a_user_id, session.role_a_status),
                (session.role_b_user_id, session.role_b_status),
            ):
                if user_id is None or status == "completed":
                    continue
                incomplete_counts[user_id] = incomplete_counts.get(user_id, 0) + 1
        return any(count >= self._rescue_lookback_days for count in incomplete_counts.values())

    def _derive_status(
        self,
        *,
        role_a_status: str,
        role_b_status: str,
        has_role_b: bool,
        rescue_mode: bool,
        benchmark_required: bool,
        existing_status: str | None,
    ) -> str:
        if role_a_status == "completed" and (not has_role_b or role_b_status == "completed"):
            return "completed"
        if role_a_status == "completed" and has_role_b:
            return "awaiting_role_b"
        if rescue_mode:
            return "rescue"
        if benchmark_required and existing_status == "benchmark_pending":
            return "benchmark_pending"
        return "active"

    def _build_action_lines(self, *, session) -> list[str]:
        if session.rescue_mode:
            return [
                f"{session.role_a_label or 'A'} 先发 2 句英文，复盘今天主题。",
                f"{session.role_b_label or 'B'} 追问 1 个问题或补 1 句。",
                "纠错后立刻重说一轮，不追之前欠下的内容。",
            ]
        action_lines = [
            f"{session.role_a_label or 'A'} 先发 3 句英文，围绕今天主题展开。",
            f"{session.role_b_label or 'B'} 跟进 2 句追问、澄清或补充。",
            "双方至少复用 1 个旧表达，再根据纠错结果重说一次。",
        ]
        if session.voice_required:
            action_lines.append("今天至少有一棒要用语音完成。")
        return action_lines

    def _build_completion_lines(self, *, session) -> list[str]:
        lines = [
            "至少完成一轮 A→B 的英文接棒。",
            "至少复用 1 个旧表达。",
            "尽量不切回中文。",
        ]
        if session.voice_required:
            lines.append("语音日：至少 1 条语音消息会被记为有效证据。")
        return lines

    def _is_relevant_message(
        self,
        *,
        session,
        message_text: str,
        message_type: str,
        evidence_types: set[str],
    ) -> bool:
        if message_type != "text":
            return session.voice_required
        if "chat_noise" in evidence_types and len(evidence_types) == 1:
            return False
        if "english_attempt" not in evidence_types:
            return False
        lowered = message_text.lower()
        if any(chunk.lower() in lowered for chunk in (session.required_chunks_json or [])):
            return True
        if "target_hit" in evidence_types or "question_asked" in evidence_types:
            return True
        return len(lowered.split()) >= 4
