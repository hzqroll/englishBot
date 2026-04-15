from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import typing
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from src.application.feishu_card_action_usecases import handle_feishu_card_action
from src.application.learning_usecases import EnrollmentContext
from src.application.message_intents import (
    extract_explicit_dialogue_analysis_text,
    is_recent_chat_analysis_request,
)
from src.application.message_usecases import MessageCommandContext, MessageUseCase
from src.domain.value_objects.learning import LanguageType
from src.domain.value_objects.messaging import MessageEnvelope
from src.infrastructure.auth.security import verify_password
from src.infrastructure.settings.container import ensure_container
from src.infrastructure.settings.models import PromptsSettings


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _current_admin(request: Request) -> str | None:
    return request.session.get("admin_username")


async def _container(request: Request):
    settings = request.app.state.settings
    return await ensure_container(settings)


def _provider_label(text: str, detected: LanguageType) -> str:
    if extract_explicit_dialogue_analysis_text(text) is not None or is_recent_chat_analysis_request(text):
        return "openai_compatible"
    if detected == LanguageType.ENGLISH:
        return "openai_compatible"
    return "openai_compatible"


def _count_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        key: after.get(key, 0) - before.get(key, 0)
        for key in after
    }


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request):
    try:
        await _container(request)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": exc.__class__.__name__},
        )
    return {"status": "ready"}


@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/admin/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    container = await _container(request)
    admin_user = await container.admin_repo.get_admin_user(username)
    if admin_user is None or not verify_password(password, admin_user.password_hash):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "用户名或密码错误"},
            status_code=401,
        )
    request.session["admin_username"] = username
    return RedirectResponse("/admin", status_code=303)


@router.get("/admin/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


@router.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    data = await container.admin_usecase.dashboard()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "metrics": data["metrics"],
            "jobs": data["jobs"],
            "admin_username": _current_admin(request),
        },
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def users_page(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    users = await container.admin_usecase.list_users()
    return templates.TemplateResponse(
        request,
        "users.html",
        {"users": users, "admin_username": _current_admin(request)},
    )


@router.get("/admin/groups", response_class=HTMLResponse)
async def groups_page(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    groups = await container.admin_usecase.list_groups()
    return templates.TemplateResponse(
        request,
        "groups.html",
        {
            "groups": groups,
            "admin_username": _current_admin(request),
            "error": None,
        },
    )


@router.post("/admin/groups", response_class=HTMLResponse)
async def groups_submit(
    request: Request,
    group_id: str | None = Form(None),
    chat_id: str = Form(...),
    name: str = Form(""),
    enabled: str | None = Form(None),
    is_admin: str | None = Form(None),
    render_mode: str = Form(""),
):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    parsed_group_id = int(group_id) if group_id and group_id.isdigit() else None
    try:
        await container.admin_usecase.save_group(
            group_id=parsed_group_id,
            chat_id=chat_id,
            name=name,
            enabled=bool(enabled),
            is_admin=bool(is_admin),
            render_mode=render_mode,
        )
        return RedirectResponse("/admin/groups", status_code=303)
    except ValueError as exc:
        groups = await container.admin_usecase.list_groups()
        return templates.TemplateResponse(
            request,
            "groups.html",
            {
                "groups": groups,
                "admin_username": _current_admin(request),
                "error": str(exc),
            },
            status_code=400,
        )


@router.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    settings = await container.admin_usecase.list_settings()
    effective_settings = await container.admin_usecase.effective_settings()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "settings": settings,
            "effective_settings": effective_settings,
            "admin_username": _current_admin(request),
        },
    )


@router.get("/admin/job-runs", response_class=HTMLResponse)
async def job_runs_page(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    jobs = await container.admin_usecase.list_job_runs()
    return templates.TemplateResponse(
        request,
        "job_runs.html",
        {
            "jobs": jobs,
            "admin_username": _current_admin(request),
        },
    )


@router.get("/admin/delivery-logs", response_class=HTMLResponse)
async def delivery_logs_page(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    logs = await container.admin_usecase.list_delivery_logs()
    return templates.TemplateResponse(
        request,
        "delivery_logs.html",
        {
            "logs": logs,
            "admin_username": _current_admin(request),
        },
    )


@router.post("/admin/settings", response_class=HTMLResponse)
async def settings_submit(request: Request, key: str = Form(...), value: str = Form(...)):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    await container.admin_usecase.update_setting(key, value)
    from src.plugins.scheduler import register_jobs

    register_jobs()
    return RedirectResponse("/admin/settings", status_code=303)


@router.post("/admin/triggers/{job_name}")
async def trigger_job(
    request: Request,
    job_name: str,
    target_date: str | None = Form(None),
    force_rerun: str | None = Form(None),
):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    from src.plugins.scheduler import (
        daily_friends_job,
        daily_summary_job,
        daily_push_job,
        nightly_backup_job,
        weekly_quiz_job,
        weekly_report_job,
    )

    job_map = {
        "daily_push": daily_push_job,
        "daily_summary": daily_summary_job,
        "weekly_report": weekly_report_job,
        "weekly_quiz": weekly_quiz_job,
        "nightly_backup": nightly_backup_job,
        "daily_friends": daily_friends_job,
    }
    job = job_map.get(job_name)
    if job is None:
        return RedirectResponse("/admin", status_code=303)
    parsed_target_date: date | None = None
    if target_date:
        try:
            parsed_target_date = date.fromisoformat(target_date)
        except ValueError:
            parsed_target_date = None
    force_run = bool(force_rerun)
    if job_name in {"daily_summary", "weekly_report", "weekly_quiz"}:
        await job(target_date=parsed_target_date, force_run=force_run)
    elif job_name in {"daily_push", "daily_friends"}:
        await job(force_run=force_run)
    else:
        await job()
    return RedirectResponse("/admin", status_code=303)


@router.get("/admin/debug", response_class=HTMLResponse)
async def debug_page(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    enabled_groups = container.runtime_config.enabled_group_ids()
    default_group_id = enabled_groups[0] if enabled_groups else "123456789"
    return templates.TemplateResponse(
        request,
        "debug.html",
        {
            "admin_username": _current_admin(request),
            "default_group_id": default_group_id,
            "form_data": None,
            "result": None,
        },
    )


@router.get("/admin/llm", response_class=HTMLResponse)
async def llm_page(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "llm.html",
        {"admin_username": _current_admin(request)},
    )


@router.post("/admin/debug", response_class=HTMLResponse)
async def debug_submit(
    request: Request,
    message_text: str = Form(...),
    group_id: str = Form(...),
    user_id: str = Form(...),
    nickname: str = Form(...),
    persist_to_db: str | None = Form(None),
):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    should_persist = bool(persist_to_db)

    form_data = {
        "message_text": message_text,
        "group_id": group_id,
        "user_id": user_id,
        "nickname": nickname,
        "persist_to_db": should_persist,
    }

    try:
        detected = MessageUseCase._detect_language(message_text)
        if should_persist:
            group = await container.identity_repo.ensure_group(group_id, "Admin Debug Group")
            user = await container.identity_repo.ensure_user(user_id, nickname)
            before_counts = await container.learning_repo.get_user_group_debug_counts(
                user_id=user.id,
                group_id=group.id,
            )
            raw_event_id = f"admin-debug-{int(datetime.now(UTC).timestamp() * 1000)}"
            reply = await container.message_usecase.handle_at_message(
                MessageCommandContext(
                    raw_event_id=raw_event_id,
                    group_id=group_id,
                    group_name="Admin Debug Group",
                    user_id=user_id,
                    nickname=nickname,
                    message_text=message_text,
                )
            )
            created_event = await container.learning_repo.get_message_event_by_raw_event_id(
                raw_event_id=raw_event_id
            )
            after_counts = await container.learning_repo.get_user_group_debug_counts(
                user_id=user.id,
                group_id=group.id,
            )
            mode = "persist_to_db"
            provider = _provider_label(message_text, detected)
            receipt = {
                "event_id": created_event.id if created_event else None,
                "raw_event_id": raw_event_id,
                "delta": _count_delta(before_counts, after_counts),
            }
        else:
            if extract_explicit_dialogue_analysis_text(message_text) is not None or is_recent_chat_analysis_request(message_text):
                reply = "dry_run 暂不支持整体对话分析，请使用 persist_to_db 或在线消息触发。"
            elif detected == LanguageType.ENGLISH:
                correction = await container.english_correction_provider.correct_english(message_text, context=None)
                parts = [f"✏️ {correction.corrected_text}"]
                if correction.zh_translation:
                    parts.append(f"\n📖 {correction.zh_translation}")
                if correction.explanation:
                    parts.append(f"\n💡 {correction.explanation}")
                if correction.error_points:
                    lines = []
                    for item in correction.error_points[:5]:
                        label = item.error_type or "修改"
                        lines.append(f"  {label}：{item.source_fragment} → {item.correct_fragment}")
                    parts.append("\n🔍 错误点\n" + "\n".join(lines))
                reply = "\n".join(parts)
            else:
                translated_text = await container.correction_provider.translate(message_text)
                reply = f"🌐 {translated_text}"
            mode = "dry_run_no_db"
            provider = _provider_label(message_text, detected)
            receipt = None
        result = {
            "mode": mode,
            "detected_language": detected.value,
            "provider": provider,
            "reply": reply,
            "receipt": receipt,
        }
    except Exception as exc:  # pragma: no cover - defensive path for manual debug
        result = {
            "mode": "error",
            "detected_language": "unknown",
            "provider": "error",
            "reply": f"{exc.__class__.__name__}: {exc}",
            "receipt": None,
        }

    return templates.TemplateResponse(
        request,
        "debug.html",
        {
            "admin_username": _current_admin(request),
            "default_group_id": group_id,
            "form_data": form_data,
            "result": result,
        },
    )


# ======================================================================
# /api/test/* — 功能验证接口（无鉴权）
# ======================================================================

_TEST_DEFAULT_USER = "test_user"
_TEST_DEFAULT_NICK = "Tester"


def _serialize_envelope(envelope: MessageEnvelope | None) -> dict | None:
    if envelope is None:
        return None
    result: dict = {"plain_text": envelope.plain_text}
    if envelope.fallback_text:
        result["fallback_text"] = envelope.fallback_text
    if envelope.card_document is not None:
        doc = envelope.card_document
        result["card_document"] = {
            "title": doc.title,
            "subtitle": doc.subtitle,
            "theme": doc.theme,
            "metadata": doc.metadata,
            "sections": [
                {"title": s.title, "lines": s.lines} for s in doc.sections
            ],
            "footer_lines": doc.footer_lines,
        }
    return result


def _ok(data=None, *, reply: str | None = None) -> JSONResponse:
    body: dict = {"success": True}
    if data is not None:
        if isinstance(data, MessageEnvelope):
            body["data"] = _serialize_envelope(data)
        elif isinstance(data, str):
            body["data"] = {"text": data}
        else:
            body["data"] = data
    if reply is not None:
        body["reply"] = reply
    return JSONResponse(body)


def _err(message: str) -> JSONResponse:
    return JSONResponse({"success": False, "error": message}, status_code=400)


def _extract_card_action_payload(payload: dict[str, typing.Any]) -> tuple[str | None, dict[str, typing.Any], str | None]:
    event = payload.get("event")
    event_body = event if isinstance(event, dict) else payload
    action_node = event_body.get("action") if isinstance(event_body, dict) else None
    value: dict[str, typing.Any] = {}
    if isinstance(action_node, dict):
        raw_value = action_node.get("value")
        if isinstance(raw_value, dict):
            value = raw_value
        elif isinstance(raw_value, str):
            try:
                decoded = json.loads(raw_value)
                if isinstance(decoded, dict):
                    value = decoded
            except json.JSONDecodeError:
                value = {}
    action = value.get("action") if isinstance(value, dict) else None

    operator = event_body.get("operator") if isinstance(event_body, dict) else None
    open_id: str | None = None
    if isinstance(operator, dict):
        open_id = operator.get("open_id") or (operator.get("operator_id") or {}).get("open_id")
    if not open_id and isinstance(event_body, dict):
        user_node = event_body.get("user_id")
        if isinstance(user_node, dict):
            open_id = user_node.get("open_id")
    if not open_id:
        open_id = value.get("open_id") if isinstance(value, dict) else None
    return action, value, open_id


def _extract_feishu_token(payload: dict[str, typing.Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("token"), str):
        return payload.get("token")
    header = payload.get("header")
    if isinstance(header, dict) and isinstance(header.get("token"), str):
        return header.get("token")
    event = payload.get("event")
    if isinstance(event, dict):
        if isinstance(event.get("token"), str):
            return event.get("token")
        event_header = event.get("header")
        if isinstance(event_header, dict) and isinstance(event_header.get("token"), str):
            return event_header.get("token")
    return None


def _verify_feishu_callback_auth(
    *,
    runtime_settings,
    request: Request,
    raw_body: bytes,
    payload: dict[str, typing.Any],
) -> tuple[bool, str]:
    token = str(getattr(runtime_settings, "feishu_verification_token", "") or "")
    encrypt_key = str(getattr(runtime_settings, "feishu_encrypt_key", "") or "")
    max_skew = int(getattr(runtime_settings, "feishu_callback_max_skew_seconds", 3600) or 3600)

    if not token and not encrypt_key:
        return True, ""

    if token:
        payload_token = _extract_feishu_token(payload)
        if payload_token is not None and payload_token != token:
            return False, "token 验证失败"

    if encrypt_key:
        timestamp = request.headers.get("x-lark-request-timestamp", "")
        nonce = request.headers.get("x-lark-request-nonce", "")
        signature = request.headers.get("x-lark-signature", "")
        if not timestamp or not nonce or not signature:
            return False, "签名头缺失"
        try:
            ts = int(timestamp)
        except ValueError:
            return False, "timestamp 非法"
        if abs(int(time.time()) - ts) > max_skew:
            return False, "请求已过期"

        digest = hashlib.sha256((timestamp + nonce + encrypt_key).encode("utf-8") + raw_body).hexdigest()
        if not hmac.compare_digest(digest, signature):
            return False, "签名验证失败"

    return True, ""


@router.post("/api/feishu/card-callback")
async def feishu_card_callback(request: Request):
    container = await _container(request)
    try:
        raw_body = await request.body()
        payload = json.loads(raw_body.decode("utf-8") if raw_body else "{}")
    except Exception:
        return JSONResponse({"toast": {"type": "warning", "content": "无效请求体"}})

    if not isinstance(payload, dict):
        return JSONResponse({"toast": {"type": "warning", "content": "无效请求体"}})
    runtime_settings = getattr(getattr(container, "settings", None), "runtime", None)
    ok, reason = _verify_feishu_callback_auth(
        runtime_settings=runtime_settings,
        request=request,
        raw_body=raw_body,
        payload=payload,
    )
    if not ok:
        return JSONResponse({"toast": {"type": "error", "content": reason}}, status_code=401)
    if "challenge" in payload:
        return JSONResponse({"challenge": payload["challenge"]})

    action, value, open_id = _extract_card_action_payload(payload)
    if not action:
        return JSONResponse({"toast": {"type": "warning", "content": "未识别卡片动作"}})

    chat_id = value.get("chat_id")
    if not chat_id:
        return JSONResponse({"toast": {"type": "warning", "content": "缺少 chat_id，上下文已过期"}})

    biz_date_raw = value.get("biz_date")
    try:
        biz_date = date.fromisoformat(biz_date_raw) if isinstance(biz_date_raw, str) and biz_date_raw else date.today()
    except ValueError:
        biz_date = date.today()

    actor_open_id = open_id or "card-user"
    card_snapshot_raw = value.get("card_snapshot_id")
    card_snapshot_id: int | None = None
    if isinstance(card_snapshot_raw, int):
        card_snapshot_id = card_snapshot_raw
    elif isinstance(card_snapshot_raw, str) and card_snapshot_raw.isdigit():
        card_snapshot_id = int(card_snapshot_raw)
    target_open_id = value.get("target_open_id") if isinstance(value.get("target_open_id"), str) else None
    result = await handle_feishu_card_action(
        container=container,
        action=action,
        chat_id=chat_id,
        actor_open_id=actor_open_id,
        biz_date=biz_date,
        card_snapshot_id=card_snapshot_id,
        target_open_id=target_open_id,
    )
    body: dict[str, typing.Any] = {
        "toast": {
            "type": result.toast_type,
            "content": result.toast_content,
        }
    }
    if result.data is not None:
        body["data"] = result.data
    return JSONResponse(body)


async def _test_params(request: Request) -> tuple:
    """从 query/form 提取 group_id, user_id, nickname。"""
    container = await _container(request)
    params = request.query_params
    form = await request.form() if request.method == "POST" else {}
    runtime_config = getattr(container, "runtime_config", None)
    enabled_groups: list[str] = []
    if runtime_config is not None:
        if hasattr(runtime_config, "enabled_group_ids"):
            enabled_groups = list(runtime_config.enabled_group_ids() or [])
        elif hasattr(runtime_config, "feishu_enabled_group_ids"):
            enabled_groups = list(runtime_config.feishu_enabled_group_ids() or [])

    first_group = enabled_groups[0] if enabled_groups else "test_group"
    group_id = params.get("group_id") or form.get("group_id") or first_group
    user_id = params.get("user_id") or form.get("user_id") or _TEST_DEFAULT_USER
    nickname = params.get("nickname") or form.get("nickname") or _TEST_DEFAULT_NICK
    return container, str(group_id), str(user_id), str(nickname)


@router.post("/api/test/enroll")
async def test_enroll(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    try:
        reply = await container.learning_usecase.enroll(
            EnrollmentContext(
                chat_id=group_id, group_name="TestGroup",
                open_id=user_id, nickname=nickname,
            )
        )
        return _ok(reply=reply)
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/test/today-task")
async def test_today_task(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    try:
        await container.learning_usecase.build_today_lesson(chat_id=group_id)
        envelope = await container.learning_usecase.get_today_task_envelope(
            chat_id=group_id, open_id=user_id, nickname=nickname,
        )
        return _ok(envelope, reply=envelope.plain_text)
    except Exception as exc:
        return _err(str(exc))


@router.post("/api/test/submit-task")
async def test_submit_task(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    form = await request.form()
    task_id = form.get("task_id")
    content = form.get("content")
    if not task_id or not content:
        return _err("需要 task_id 和 content 参数")
    if not str(task_id).isdigit():
        return _err("task_id 必须是数字")
    try:
        reply = await container.learning_usecase.submit_task(
            chat_id=group_id, open_id=user_id, nickname=nickname,
            task_id=int(task_id), content=str(content),
        )
        return _ok(reply=reply)
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/test/review")
async def test_review(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    try:
        reply = await container.learning_usecase.review_now(
            chat_id=group_id, open_id=user_id, nickname=nickname,
            limit=container.runtime_config.daily_review_insert_count(),
        )
        return _ok(reply=reply)
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/test/level")
async def test_level(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    try:
        reply = await container.learning_usecase.refresh_user_level(
            chat_id=group_id, open_id=user_id, nickname=nickname,
        )
        return _ok(reply=reply)
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/test/quiz")
async def test_quiz(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    try:
        envelope = await container.quiz_usecase.start_weekly_quiz_envelope(
            chat_id=group_id, open_id=user_id, nickname=nickname,
        )
        return _ok(envelope, reply=envelope.plain_text)
    except Exception as exc:
        return _err(str(exc))


@router.post("/api/test/quiz/submit")
async def test_quiz_submit(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    form = await request.form()
    session_id = form.get("session_id")
    if not session_id or not str(session_id).isdigit():
        return _err("需要 session_id 参数（数字）")
    answers: dict[int, str] = {}
    for key, val in form.items():
        if key.startswith("a"):
            num = key[1:]
            if num.isdigit():
                answers[int(num)] = str(val).upper()
    if not answers:
        return _err("需要至少一个答案，格式: a1=A&a2=B")
    try:
        reply = await container.quiz_usecase.submit_weekly_quiz(
            chat_id=group_id, open_id=user_id, nickname=nickname,
            session_id=int(session_id), answers=answers,
        )
        return _ok(reply=reply)
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/test/weekly-report")
async def test_weekly_report(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    try:
        envelope = await container.report_usecase.build_weekly_report_envelope(
            chat_id=group_id, open_id=user_id, nickname=nickname,
        )
        return _ok(envelope, reply=envelope.plain_text)
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/test/error-digest")
async def test_error_digest(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    try:
        envelope = await container.report_usecase.build_daily_error_digest_envelope(
            chat_id=group_id, open_id=user_id, nickname=nickname,
        )
        if envelope is None:
            return _ok(reply="当日无错误记录")
        return _ok(envelope, reply=envelope.plain_text)
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/test/progress")
async def test_progress(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    try:
        envelope = await container.report_usecase.build_daily_progress_envelope(
            chat_id=group_id, open_id=user_id, nickname=nickname,
        )
        if envelope is None:
            return _ok(reply="当日无学习进度")
        return _ok(envelope, reply=envelope.plain_text)
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/test/daily-summary")
async def test_daily_summary(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    try:
        await container.learning_usecase.build_today_lesson(chat_id=group_id)
        envelope = await container.report_usecase.build_group_daily_summary_envelope(
            chat_id=group_id,
        )
        if envelope is None:
            return _ok(reply="当日无学习内容，未生成日报")
        return _ok(envelope, reply=envelope.plain_text)
    except Exception as exc:
        return _err(str(exc))


@router.get("/api/test/friends")
async def test_friends(request: Request):
    container = await _container(request)
    if container.friends_usecase is None:
        return _err("Friends 功能未启用")
    try:
        today = date.today()
        envelope = await container.friends_usecase.build_daily_friends_envelope(
            biz_date=today, start_date=today,
        )
        return _ok(envelope, reply=envelope.plain_text)
    except Exception as exc:
        return _err(str(exc))


@router.post("/api/test/message")
async def test_message(request: Request):
    container, group_id, user_id, nickname = await _test_params(request)
    form = await request.form()
    message_text = form.get("message_text")
    if not message_text:
        return _err("需要 message_text 参数")
    try:
        raw_event_id = f"test-{int(datetime.now(UTC).timestamp() * 1000)}"
        text = str(message_text)
        # 先写入对话缓存（即使 LLM 调用失败也保留）
        container.group_dialogue_store.append_group_message(
            group_id=group_id, user_id=user_id, nickname=nickname, text=text,
        )
        reply = await container.message_usecase.handle_at_message(
            MessageCommandContext(
                raw_event_id=raw_event_id,
                group_id=group_id,
                group_name="TestGroup",
                user_id=user_id,
                nickname=nickname,
                message_text=text,
            )
        )
        return _ok(reply=reply)
    except Exception as exc:
        return _err(f"{exc.__class__.__name__}: {exc}")


@router.get("/api/test/cache-status")
async def cache_status(request: Request):
    """调试接口：查看当前对话缓存状态。"""
    container = await _container(request)
    store = container.group_dialogue_store
    result = {}
    for group_id, bucket in store._store.items():
        result[group_id] = {
            "biz_date": str(bucket.biz_date),
            "entry_count": len(bucket.entries),
            "last_entries": [
                {"speaker": e.speaker, "text": e.text[:50]}
                for e in bucket.entries[-3:]
            ],
        }
    return _ok({"groups": result, "total_groups": len(result)})


@router.post("/api/test/trigger/{job_name}")
async def test_trigger(job_name: str, force_rerun: str | None = Form(None)):
    """调试接口：无鉴权触发定时任务。"""
    from src.plugins.scheduler import (
        daily_friends_job,
        daily_summary_job,
        daily_push_job,
        nightly_backup_job,
        sync_feishu_messages_job,
        weekly_quiz_job,
        weekly_report_job,
    )

    job_map = {
        "daily_push": daily_push_job,
        "daily_summary": daily_summary_job,
        "weekly_report": weekly_report_job,
        "weekly_quiz": weekly_quiz_job,
        "nightly_backup": nightly_backup_job,
        "daily_friends": daily_friends_job,
        "sync_feishu_messages": sync_feishu_messages_job,
    }
    job = job_map.get(job_name)
    if job is None:
        return _err(f"未知任务: {job_name}，可选: {', '.join(job_map)}")
    force_run = bool(force_rerun)
    try:
        if job_name in {"daily_summary", "weekly_report", "weekly_quiz", "sync_feishu_messages"}:
            await job(target_date=None, force_run=force_run)
        elif job_name in {"daily_push", "daily_friends"}:
            await job(force_run=force_run)
        else:
            await job()
        return _ok(reply=f"{job_name} triggered")
    except Exception as exc:
        return _err(f"{exc.__class__.__name__}: {exc}")


# ======================================================================
# /api/llm/* — LLM 提示词测试 & 优化接口（无鉴权）
# ======================================================================

_VALID_PROMPT_NAMES = set(PromptsSettings.model_fields)


@router.get("/api/llm/prompts")
async def llm_get_prompts(request: Request, name: str | None = None):
    container = await _container(request)
    prompts = container.correction_provider._prompts
    if name:
        if name not in _VALID_PROMPT_NAMES:
            return _err(f"未知提示词: {name}，可选: {', '.join(sorted(_VALID_PROMPT_NAMES))}")
        return _ok({name: getattr(prompts, name)})
    return _ok(prompts.model_dump())


@router.put("/api/llm/prompts/{name}")
async def llm_put_prompt(request: Request, name: str):
    container = await _container(request)
    if name not in _VALID_PROMPT_NAMES:
        return _err(f"未知提示词: {name}，可选: {', '.join(sorted(_VALID_PROMPT_NAMES))}")
    body = await request.json()
    value = body.get("value")
    if value is None:
        return _err("需要 value 字段")
    provider = container.correction_provider
    setattr(provider._prompts, name, str(value))
    # 同步到 friends_usecase
    if container.friends_usecase is not None:
        setattr(container.friends_usecase._prompts, name, str(value))
    return _ok({name: getattr(provider._prompts, name)})


@router.post("/api/llm/test")
async def llm_test(request: Request):
    container = await _container(request)
    body = await request.json()
    messages = body.get("messages")
    if not messages:
        return _err("需要 messages 字段")
    try:
        result = await container.correction_provider.raw_chat(
            messages=messages,
            temperature=float(body.get("temperature", 0.5)),
            max_tokens=int(body.get("max_tokens", 500)),
            response_format=body.get("response_format", "text"),
            timeout=float(body["timeout"]) if body.get("timeout") else None,
        )
        return _ok({"response": result})
    except Exception as exc:
        return _err(f"{exc.__class__.__name__}: {exc}")


_LLM_FUNCTION_NAMES = {
    "correct", "improve-translation", "feedback",
    "analyze-dialogue", "weekly-report", "daily-progress", "daily-summary", "friends-analysis",
}

_LLM_JSON_FUNCTIONS = {"correct", "analyze-dialogue", "friends-analysis"}


async def _stream_llm(
    provider,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    name: str,
    prompt_used: str,
    is_json: bool = False,
    timeout: float = 120.0,
) -> typing.AsyncGenerator[str, None]:
    """SSE async generator: streams LLM text chunks, sends parsed result on completion."""
    queue: asyncio.Queue[tuple[str, typing.Any]] = asyncio.Queue()

    def on_chunk(text: str) -> None:
        queue.put_nowait(("chunk", text))

    async def run() -> None:
        try:
            accumulated = await provider._chat_text_stream(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                on_chunk=on_chunk,
                timeout=timeout,
            )
            result: typing.Any = accumulated
            if is_json:
                try:
                    result = json.loads(provider._extract_json(accumulated))
                except (json.JSONDecodeError, ValueError):
                    result = {}
            queue.put_nowait(("done", result))
        except Exception as exc:
            queue.put_nowait(("error", f"{exc.__class__.__name__}: {exc}"))

    task = asyncio.create_task(run())
    try:
        while True:
            event_type, data = await queue.get()
            if event_type == "chunk":
                yield f"data: {json.dumps({'type': 'chunk', 'content': data}, ensure_ascii=False)}\n\n"
            elif event_type == "done":
                payload = {
                    "type": "done",
                    "function": name,
                    "prompt_used": prompt_used,
                    "result": data,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break
            elif event_type == "error":
                yield f"data: {json.dumps({'type': 'error', 'error': data}, ensure_ascii=False)}\n\n"
                break
    finally:
        if not task.done():
            task.cancel()


@router.post("/api/llm/functions/{name}")
async def llm_function(request: Request, name: str, stream: bool = Query(False)):
    if name not in _LLM_FUNCTION_NAMES:
        return _err(f"未知函数: {name}，可选: {', '.join(sorted(_LLM_FUNCTION_NAMES))}")
    container = await _container(request)
    body = await request.json()
    provider = container.correction_provider
    prompts = provider._prompts

    try:
        if name == "correct":
            text = body.get("text")
            if not text:
                return _err("需要 text 参数")
            context = body.get("context")
            system_prompt = body.get("system_prompt") or prompts.correction_system
            user_prompt = f"上下文：{context or '无'}\n待纠错英文：{text}"
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            if stream:
                return StreamingResponse(
                    _stream_llm(provider, messages, 0.2, 500, name, system_prompt, is_json=True),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            data = await provider._chat_json(messages=messages, temperature=0.2, max_tokens=500, timeout=120.0)
            return _ok({"function": name, "prompt_used": system_prompt, "result": data})

        if name == "improve-translation":
            source_text = body.get("source_text")
            base_translation = body.get("base_translation")
            if not source_text or not base_translation:
                return _err("需要 source_text 和 base_translation 参数")
            prompt_template = body.get("prompt_template") or prompts.improve_translation
            prompt = prompt_template.format(
                context=body.get("context") or "无",
                source_text=source_text,
                base_translation=base_translation,
            )
            if stream:
                return StreamingResponse(
                    _stream_llm(provider, [{"role": "user", "content": prompt}], 0.3, 220, name, prompt),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            result = await provider._chat_text(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=220,
                timeout=120.0,
            )
            return _ok({"function": name, "prompt_used": prompt, "result": result})

        if name == "feedback":
            content = body.get("content")
            if not content:
                return _err("需要 content 参数")
            prompt_template = body.get("prompt_template") or prompts.task_feedback
            prompt = prompt_template.format(content=content)
            if stream:
                return StreamingResponse(
                    _stream_llm(provider, [{"role": "user", "content": prompt}], 0.5, 180, name, prompt),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            result = await provider._chat_text(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=180,
                timeout=120.0,
            )
            return _ok({"function": name, "prompt_used": prompt, "result": result})

        if name == "analyze-dialogue":
            text = body.get("text")
            if not text:
                return _err("需要 text 参数")
            source_kind = body.get("source_kind") or "group_chat"
            system_prompt = body.get("system_prompt") or prompts.dialogue_analysis_system
            user_prompt = f"来源：{source_kind}\n请分析下面的对话内容：\n{text}"
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            if stream:
                return StreamingResponse(
                    _stream_llm(provider, messages, 0.2, 1200, name, system_prompt, is_json=True),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            data = await provider._chat_json(messages=messages, temperature=0.2, max_tokens=1200, timeout=120.0)
            return _ok({"function": name, "prompt_used": system_prompt, "result": data})

        if name == "weekly-report":
            learning_days = body.get("learning_days")
            task_completion_rate = body.get("task_completion_rate")
            correction_count = body.get("correction_count")
            level = body.get("level")
            if any(v is None for v in [learning_days, task_completion_rate, correction_count, level]):
                return _err("需要 learning_days, task_completion_rate, correction_count, level 参数")
            prompt_template = body.get("prompt_template") or prompts.weekly_report_summary
            prompt = prompt_template.format(
                learning_days=learning_days,
                task_completion_rate=task_completion_rate,
                correction_count=correction_count,
                level=level,
            )
            if stream:
                return StreamingResponse(
                    _stream_llm(provider, [{"role": "user", "content": prompt}], 0.5, 180, name, prompt),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            result = await provider._chat_text(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=180,
                timeout=120.0,
            )
            return _ok({"function": name, "prompt_used": prompt, "result": result})

        if name == "daily-progress":
            required_fields = [
                "task_status", "level_label", "english_attempt_count",
                "target_hit_count", "correction_count", "today_task_completed",
                "today_task_total", "mastery_label", "mastery_reason",
            ]
            missing = [f for f in required_fields if body.get(f) is None]
            if missing:
                return _err(f"缺少参数: {', '.join(missing)}")
            prompt_template = body.get("prompt_template") or prompts.daily_progress_summary
            prompt = prompt_template.format(
                task_status=body["task_status"],
                level_label=body["level_label"],
                english_attempt_count=body["english_attempt_count"],
                target_hit_count=body["target_hit_count"],
                correction_count=body["correction_count"],
                today_task_completed=body["today_task_completed"],
                today_task_total=body["today_task_total"],
                mastery_label=body["mastery_label"],
                mastery_reason=body["mastery_reason"],
            )
            if stream:
                return StreamingResponse(
                    _stream_llm(provider, [{"role": "user", "content": prompt}], 0.5, 180, name, prompt),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            result = await provider._chat_text(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=180,
                timeout=120.0,
            )
            return _ok({"function": name, "prompt_used": prompt, "result": result})

        if name == "daily-summary":
            required_fields = [
                "daily_goal",
                "required_phrases",
                "today_dialogues",
                "yesterday_dialogues",
                "new_words_today",
            ]
            missing = [f for f in required_fields if body.get(f) is None]
            if missing:
                return _err(f"缺少参数: {', '.join(missing)}")
            prompt_template = body.get("prompt_template") or prompts.daily_summary_xhs_prompt
            prompt = (
                prompt_template
                .replace("{daily_goal}", str(body["daily_goal"]))
                .replace("{required_phrases}", str(body["required_phrases"]))
                .replace("{today_dialogues}", str(body["today_dialogues"]))
                .replace("{yesterday_dialogues}", str(body["yesterday_dialogues"]))
                .replace("{new_words_today}", str(body["new_words_today"]))
            )
            if stream:
                return StreamingResponse(
                    _stream_llm(provider, [{"role": "user", "content": prompt}], 0.4, 2400, name, prompt, is_json=True),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            data = await provider._chat_json(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=2400,
                timeout=150.0,
            )
            return _ok({"function": name, "prompt_used": prompt, "result": data})

        if name == "friends-analysis":
            text = body.get("text")
            if not text:
                return _err("需要 text 参数")
            system_prompt = body.get("system_prompt") or prompts.friends_analysis_system
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ]
            if stream:
                return StreamingResponse(
                    _stream_llm(provider, messages, 0.3, 1500, name, system_prompt, is_json=True),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
                )
            data = await provider._chat_json(
                messages=messages,
                temperature=0.3,
                max_tokens=1500,
                timeout=120.0,
            )
            return _ok({"function": name, "prompt_used": system_prompt, "result": data})

    except Exception as exc:
        return _err(f"{exc.__class__.__name__}: {exc}")
