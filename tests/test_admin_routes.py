from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from src.admin import routes as admin_routes


class _AdminUseCaseStub:
    async def list_job_runs(self, *, limit: int = 100) -> list[dict]:
        return [
            {
                "id": 1,
                "job_name": "weekly_report",
                "biz_key": "2026-W15",
                "status": "success",
                "started_at": "2026-04-07 10:00:00",
                "finished_at": "2026-04-07 10:00:04",
                "duration_seconds": 4.0,
                "created_at": "2026-04-07 10:00:00",
            }
        ]

    async def list_delivery_logs(self, *, limit: int = 100) -> list[dict]:
        return [
            {
                "id": 8,
                "job_name": "weekly_quiz",
                "delivery_mode": "image_single",
                "success": True,
                "provider_response": "sent",
                "created_at": "2026-04-07 10:01:00",
                "group_id": "204257012",
                "group_name": "No Rain No Rainbow",
                "user_id": "472583006",
                "nickname": "Rainbow",
                "card_type": "weekly_quiz",
                "image_count": 1,
                "card_snapshot_id": 12,
            }
        ]


class _ContainerStub:
    def __init__(self) -> None:
        self.admin_usecase = _AdminUseCaseStub()


def _build_test_client(monkeypatch) -> TestClient:
    async def _fake_container(_request):
        return _ContainerStub()

    monkeypatch.setattr(admin_routes, "_current_admin", lambda request: "tester")
    monkeypatch.setattr(admin_routes, "_container", _fake_container)

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(admin_routes.router)
    return TestClient(app)


def test_admin_job_runs_page_renders(monkeypatch) -> None:
    client = _build_test_client(monkeypatch)

    response = client.get("/admin/job-runs")

    assert response.status_code == 200
    assert "任务执行记录" in response.text
    assert "weekly_report" in response.text


def test_admin_delivery_logs_page_renders(monkeypatch) -> None:
    client = _build_test_client(monkeypatch)

    response = client.get("/admin/delivery-logs")

    assert response.status_code == 200
    assert "发送日志" in response.text
    assert "weekly_quiz" in response.text
