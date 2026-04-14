from __future__ import annotations

import hashlib
import json
import time
from types import SimpleNamespace

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
        self.feishu_docs_service = None
        self.daily_session_usecase = None
        self.settings = SimpleNamespace(
            runtime=SimpleNamespace(
                feishu_verification_token="",
                feishu_encrypt_key="",
                feishu_callback_max_skew_seconds=3600,
            )
        )


def _build_test_client(monkeypatch) -> TestClient:
    return _build_test_client_with_container(monkeypatch, _ContainerStub())


def _build_test_client_with_container(monkeypatch, container) -> TestClient:
    async def _fake_container(_request):
        return container

    monkeypatch.setattr(admin_routes, "_current_admin", lambda request: "tester")
    monkeypatch.setattr(admin_routes, "_container", _fake_container)

    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret")
    app.include_router(admin_routes.router)
    return TestClient(app)


class _DocsServiceStub:
    async def get_weekly_doc_url(self, *, target_date):
        return f"https://bytedance.larkoffice.com/docx/week-{target_date.isoformat()}"


class _DailySessionUseCaseStub:
    async def claim_baton(self, *, chat_id: str, actor_open_id: str, biz_date):
        return f"claim:{chat_id}:{actor_open_id}:{biz_date.isoformat()}"

    async def enter_rescue_mode(self, *, chat_id: str, actor_open_id: str, biz_date):
        return f"rescue:{chat_id}:{actor_open_id}:{biz_date.isoformat()}"

    async def remind_later(self, *, chat_id: str, actor_open_id: str, biz_date):
        return f"later:{chat_id}:{actor_open_id}:{biz_date.isoformat()}"


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


def test_feishu_card_callback_challenge(monkeypatch) -> None:
    client = _build_test_client(monkeypatch)

    response = client.post("/api/feishu/card-callback", json={"challenge": "abc123"})

    assert response.status_code == 200
    assert response.json() == {"challenge": "abc123"}


def test_feishu_card_callback_open_week_doc(monkeypatch) -> None:
    container = _ContainerStub()
    container.feishu_docs_service = _DocsServiceStub()
    container.daily_session_usecase = _DailySessionUseCaseStub()
    client = _build_test_client_with_container(monkeypatch, container)

    payload = {
        "event": {
            "operator": {"open_id": "u1"},
            "action": {
                "value": {
                    "action": "open_week_doc",
                    "chat_id": "oc_test",
                    "biz_date": "2026-04-13",
                }
            },
        }
    }
    response = client.post("/api/feishu/card-callback", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["toast"]["type"] == "success"
    assert data["data"]["doc_url"].startswith("https://bytedance.larkoffice.com/docx/week-2026-04-13")


def test_feishu_card_callback_session_actions(monkeypatch) -> None:
    container = _ContainerStub()
    container.feishu_docs_service = _DocsServiceStub()
    container.daily_session_usecase = _DailySessionUseCaseStub()
    client = _build_test_client_with_container(monkeypatch, container)

    for action, prefix in (
        ("claim_baton", "claim:"),
        ("enter_rescue", "rescue:"),
        ("remind_later", "later:"),
    ):
        payload = {
            "event": {
                "operator": {"open_id": "u-actor"},
                "action": {
                    "value": {
                        "action": action,
                        "chat_id": "oc_test",
                        "biz_date": "2026-04-13",
                    }
                },
            }
        }
        response = client.post("/api/feishu/card-callback", json=payload)
        assert response.status_code == 200
        assert response.json()["toast"]["content"].startswith(prefix)


def test_feishu_card_callback_rejects_invalid_signature(monkeypatch) -> None:
    container = _ContainerStub()
    container.feishu_docs_service = _DocsServiceStub()
    container.daily_session_usecase = _DailySessionUseCaseStub()
    container.settings.runtime.feishu_encrypt_key = "enc-key"
    client = _build_test_client_with_container(monkeypatch, container)

    payload = {
        "event": {
            "operator": {"open_id": "u-actor"},
            "action": {"value": {"action": "open_week_doc", "chat_id": "oc_test", "biz_date": "2026-04-13"}},
        }
    }

    response = client.post("/api/feishu/card-callback", json=payload)
    assert response.status_code == 401
    assert response.json()["toast"]["type"] == "error"


def test_feishu_card_callback_accepts_valid_signature(monkeypatch) -> None:
    container = _ContainerStub()
    container.feishu_docs_service = _DocsServiceStub()
    container.daily_session_usecase = _DailySessionUseCaseStub()
    container.settings.runtime.feishu_encrypt_key = "enc-key"
    client = _build_test_client_with_container(monkeypatch, container)

    payload = {
        "event": {
            "operator": {"open_id": "u-actor"},
            "action": {"value": {"action": "open_week_doc", "chat_id": "oc_test", "biz_date": "2026-04-13"}},
        }
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    timestamp = str(int(time.time()))
    nonce = "nonce-123"
    signature = hashlib.sha256((timestamp + nonce + "enc-key").encode("utf-8") + body).hexdigest()

    response = client.post(
        "/api/feishu/card-callback",
        data=body,
        headers={
            "content-type": "application/json",
            "x-lark-request-timestamp": timestamp,
            "x-lark-request-nonce": nonce,
            "x-lark-signature": signature,
        },
    )
    assert response.status_code == 200
    assert response.json()["toast"]["type"] == "success"
