from __future__ import annotations
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.application.message_intents import (
    extract_explicit_dialogue_analysis_text,
    is_recent_chat_analysis_request,
)
from src.application.message_usecases import MessageCommandContext
from src.domain.value_objects.learning import LanguageType
from src.infrastructure.auth.security import verify_password
from src.infrastructure.settings.container import ensure_container


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
        return "language-tool+tencent"
    return "tencent"


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
    qq_group_id: str = Form(...),
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
            qq_group_id=qq_group_id,
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
        daily_error_digest_job,
        daily_progress_job,
        daily_push_job,
        nightly_backup_job,
        weekly_quiz_job,
        weekly_report_job,
    )

    job_map = {
        "daily_push": daily_push_job,
        "daily_error_digest": daily_error_digest_job,
        "daily_progress": daily_progress_job,
        "weekly_report": weekly_report_job,
        "weekly_quiz": weekly_quiz_job,
        "nightly_backup": nightly_backup_job,
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
    if job_name in {"daily_error_digest", "daily_progress", "weekly_report", "weekly_quiz"}:
        await job(target_date=parsed_target_date, force_run=force_run)
    elif job_name == "daily_push":
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
        detected = await container.translate_provider.detect_language(message_text)
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
                translated = await container.translate_provider.translate(
                    message_text,
                    source_lang=detected,
                    target_lang=LanguageType.ENGLISH,
                )
                reply = f"🌐 {translated.translated_text}"
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
