from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.application.learning_usecases import EnrollmentContext
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


def _provider_label(detected: LanguageType) -> str:
    if detected == LanguageType.ENGLISH:
        return "openai_compatible"
    return "tencent+openai_compatible"


def _preview_base_url(request: Request, container) -> str:
    return container.runtime_config.public_base_url() or str(request.base_url).rstrip("/")


def _count_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {
        key: after.get(key, 0) - before.get(key, 0)
        for key in after
    }


async def _load_card_payload(container, token: str, expected_type: str):
    payload = container.card_link_signer.verify(token)
    if payload.resource_type != expected_type:
        raise ValueError("链接类型不匹配，请回到群里重新获取。")
    return payload


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
async def trigger_job(request: Request, job_name: str):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    from src.plugins.scheduler import (
        daily_push_job,
        daily_reminder_job,
        nightly_backup_job,
        weekly_quiz_job,
        weekly_report_job,
    )

    job_map = {
        "daily_push": daily_push_job,
        "daily_reminder": daily_reminder_job,
        "weekly_report": weekly_report_job,
        "weekly_quiz": weekly_quiz_job,
        "nightly_backup": nightly_backup_job,
    }
    job = job_map.get(job_name)
    if job is None:
        return RedirectResponse("/admin", status_code=303)
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
            provider = _provider_label(detected)
            receipt = {
                "event_id": created_event.id if created_event else None,
                "raw_event_id": raw_event_id,
                "delta": _count_delta(before_counts, after_counts),
            }
        else:
            if detected == LanguageType.ENGLISH:
                correction = await container.correction_provider.correct_english(message_text, context=None)
                reply = (
                    f"纠错后：\n{correction.corrected_text}\n\n"
                    f"中文翻译：\n{correction.zh_translation}\n\n"
                    f"说明：{correction.explanation}"
                )
            else:
                translated = await container.translate_provider.translate(
                    message_text,
                    source_lang=detected,
                    target_lang=LanguageType.ENGLISH,
                )
                natural = await container.correction_provider.improve_translation(
                    source_text=message_text,
                    base_translation=translated.translated_text,
                    context=None,
                )
                reply = f"英文翻译：\n{translated.translated_text}\n\n更自然表达：\n{natural}"
            mode = "dry_run_no_db"
            provider = _provider_label(detected)
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


@router.get("/admin/cards", response_class=HTMLResponse)
async def card_preview_page(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    enabled_groups = container.runtime_config.enabled_group_ids()
    default_group_id = enabled_groups[0] if enabled_groups else "123456789"
    return templates.TemplateResponse(
        request,
        "cards.html",
        {
            "admin_username": _current_admin(request),
            "default_group_id": default_group_id,
            "form_data": None,
            "result": None,
        },
    )


@router.post("/admin/cards", response_class=HTMLResponse)
async def card_preview_submit(
    request: Request,
    resource_type: str = Form(...),
    group_id: str = Form(...),
    user_id: str = Form(...),
    nickname: str = Form(...),
):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = await _container(request)
    form_data = {
        "resource_type": resource_type,
        "group_id": group_id,
        "user_id": user_id,
        "nickname": nickname,
    }
    preview_base_url = _preview_base_url(request, container)
    try:
        await container.learning_usecase.enroll(
            EnrollmentContext(
                qq_group_id=group_id,
                group_name="Card Preview Group",
                qq_user_id=user_id,
                nickname=nickname,
            )
        )
        if resource_type == "task":
            envelope = await container.learning_usecase.get_today_task_envelope(
                qq_group_id=group_id,
                qq_user_id=user_id,
                nickname=nickname,
                base_url_override=preview_base_url,
            )
        elif resource_type == "quiz":
            envelope = await container.quiz_usecase.start_weekly_quiz_envelope(
                qq_group_id=group_id,
                qq_user_id=user_id,
                nickname=nickname,
                base_url_override=preview_base_url,
            )
        elif resource_type == "report":
            envelope = await container.report_usecase.build_weekly_report_envelope(
                qq_group_id=group_id,
                qq_user_id=user_id,
                nickname=nickname,
                base_url_override=preview_base_url,
            )
        else:
            raise ValueError("不支持的卡片类型。")
        result = {
            "resource_type": resource_type,
            "plain_text": envelope.plain_text,
            "fallback_text": envelope.delivery_text(),
            "card_link_url": envelope.card_link_url,
            "card_payload_json": json.dumps(envelope.card_payload, ensure_ascii=False, indent=2)
            if envelope.card_payload
            else "",
        }
    except Exception as exc:  # pragma: no cover - manual preview path
        result = {
            "resource_type": resource_type,
            "plain_text": f"{exc.__class__.__name__}: {exc}",
            "fallback_text": "",
            "card_link_url": "",
            "card_payload_json": "",
        }
    return templates.TemplateResponse(
        request,
        "cards.html",
        {
            "admin_username": _current_admin(request),
            "default_group_id": group_id,
            "form_data": form_data,
            "result": result,
        },
    )


@router.get("/learn/task/{token}", response_class=HTMLResponse)
async def learn_task_page(request: Request, token: str):
    container = await _container(request)
    try:
        payload = await _load_card_payload(container, token, "task")
        page = await container.task_page_usecase.load(payload)
        return templates.TemplateResponse(
            request,
            "learn_task.html",
            {"page": page, "token": token, "submit_result": None, "error": None},
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "learn_error.html",
            {"title": "任务页不可用", "error": str(exc)},
            status_code=400,
        )


@router.post("/learn/task/{token}", response_class=HTMLResponse)
async def learn_task_submit(request: Request, token: str, task_id: int = Form(...), submission_text: str = Form(...)):
    container = await _container(request)
    try:
        payload = await _load_card_payload(container, token, "task")
        submit_result = await container.task_page_usecase.submit(
            payload,
            task_id=task_id,
            content=submission_text,
        )
        page = await container.task_page_usecase.load(payload)
        return templates.TemplateResponse(
            request,
            "learn_task.html",
            {"page": page, "token": token, "submit_result": submit_result, "error": None},
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "learn_error.html",
            {"title": "任务提交失败", "error": str(exc)},
            status_code=400,
        )


@router.get("/learn/quiz/{token}", response_class=HTMLResponse)
async def learn_quiz_page(request: Request, token: str):
    container = await _container(request)
    try:
        payload = await _load_card_payload(container, token, "quiz")
        page = await container.quiz_page_usecase.load(payload)
        return templates.TemplateResponse(
            request,
            "learn_quiz.html",
            {"page": page, "token": token, "submit_result": None, "error": None},
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "learn_error.html",
            {"title": "周测页不可用", "error": str(exc)},
            status_code=400,
        )


@router.post("/learn/quiz/{token}", response_class=HTMLResponse)
async def learn_quiz_submit(request: Request, token: str):
    container = await _container(request)
    try:
        payload = await _load_card_payload(container, token, "quiz")
        form = await request.form()
        answers: dict[int, str] = {}
        for key, value in form.items():
            if not key.startswith("q_"):
                continue
            index_text = key.removeprefix("q_")
            if index_text.isdigit():
                answers[int(index_text)] = str(value).strip().upper()
        submit_result = await container.quiz_page_usecase.submit(payload, answers=answers)
        page = await container.quiz_page_usecase.load(payload)
        return templates.TemplateResponse(
            request,
            "learn_quiz.html",
            {"page": page, "token": token, "submit_result": submit_result, "error": None},
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "learn_error.html",
            {"title": "周测提交失败", "error": str(exc)},
            status_code=400,
        )


@router.get("/learn/report/{token}", response_class=HTMLResponse)
async def learn_report_page(request: Request, token: str):
    container = await _container(request)
    try:
        payload = await _load_card_payload(container, token, "report")
        page = await container.report_page_usecase.load(payload)
        return templates.TemplateResponse(
            request,
            "learn_report.html",
            {"page": page, "error": None},
        )
    except Exception as exc:
        return templates.TemplateResponse(
            request,
            "learn_error.html",
            {"title": "周报页不可用", "error": str(exc)},
            status_code=400,
        )
