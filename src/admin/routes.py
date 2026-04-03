from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from src.infrastructure.auth.security import verify_password
from src.infrastructure.settings.container import get_container


router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))


def _current_admin(request: Request) -> str | None:
    return request.session.get("admin_username")


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ready"}


@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@router.post("/admin/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    container = get_container()
    admin_user = await container.admin_repo.get_admin_user(username)
    if admin_user is None or not verify_password(password, admin_user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "用户名或密码错误"},
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
    container = get_container()
    data = await container.admin_usecase.dashboard()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "metrics": data["metrics"],
            "jobs": data["jobs"],
            "admin_username": _current_admin(request),
        },
    )


@router.get("/admin/users", response_class=HTMLResponse)
async def users_page(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = get_container()
    users = await container.admin_usecase.list_users()
    return templates.TemplateResponse(
        "users.html",
        {"request": request, "users": users, "admin_username": _current_admin(request)},
    )


@router.get("/admin/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = get_container()
    settings = await container.admin_usecase.list_settings()
    effective_settings = await container.admin_usecase.effective_settings()
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "settings": settings,
            "effective_settings": effective_settings,
            "admin_username": _current_admin(request),
        },
    )


@router.post("/admin/settings", response_class=HTMLResponse)
async def settings_submit(request: Request, key: str = Form(...), value: str = Form(...)):
    if not _current_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    container = get_container()
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
