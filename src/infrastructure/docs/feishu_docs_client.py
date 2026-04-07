from __future__ import annotations

import json
import logging
import time

import httpx
import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    CreateDocumentRequest,
    CreateDocumentRequestBody,
)
from lark_oapi.api.drive.v1 import CreateFolderFileRequest, CreateFolderFileRequestBody

logger = logging.getLogger(__name__)

_BASE_URL = "https://open.feishu.cn/open-apis"


class FeishuDocsError(Exception):
    """飞书文档 API 调用失败。"""


class FeishuDocsClient:
    """封装飞书文档/云空间 API。

    文件夹和文档的创建使用 lark-oapi SDK（builder 模式稳定），
    内容块追加使用原始 HTTP 请求（SDK 对 block children 序列化有 bug）。
    """

    def __init__(self, *, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )
        self._token: str = ""
        self._token_expires: float = 0.0
        self._http: httpx.Client | None = None

    def _ensure_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires:
            return self._token
        resp = self._get_http().post(
            f"{_BASE_URL}/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuDocsError(f"get token failed: {data}")
        self._token = data["tenant_access_token"]
        self._token_expires = time.monotonic() + data.get("expire", 7200) - 60
        return self._token

    def _get_http(self) -> httpx.Client:
        if self._http is None or self._http.is_closed:
            self._http = httpx.Client(timeout=30.0)
        return self._http

    def create_folder(self, *, name: str, folder_token: str = "") -> str:
        """在云空间创建文件夹，返回 folder_token。"""
        request = (
            CreateFolderFileRequest.builder()
            .request_body(
                CreateFolderFileRequestBody.builder()
                .name(name)
                .folder_token(folder_token)
                .build()
            )
            .build()
        )
        resp = self._client.drive.v1.file.create_folder(request)
        if not resp.success():
            raise FeishuDocsError(f"create_folder failed: code={resp.code} msg={resp.msg}")
        return resp.data.token

    def create_document(self, *, title: str, folder_token: str) -> str:
        """创建文档并放入指定文件夹，返回 document_id。"""
        request = (
            CreateDocumentRequest.builder()
            .request_body(
                CreateDocumentRequestBody.builder()
                .title(title)
                .folder_token(folder_token)
                .build()
            )
            .build()
        )
        resp = self._client.docx.v1.document.create(request)
        if not resp.success():
            raise FeishuDocsError(f"create_document failed: code={resp.code} msg={resp.msg}")
        return resp.data.document.document_id

    def append_blocks(self, *, document_id: str, blocks: list[dict]) -> None:
        """向文档末尾追加内容块（使用原始 HTTP 避免 SDK 序列化问题）。"""
        token = self._ensure_token()
        url = f"{_BASE_URL}/docx/v1/documents/{document_id}/blocks/{document_id}/children"
        body = {"children": blocks, "index": -1}
        resp = self._get_http().post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise FeishuDocsError(f"append_blocks failed: code={data.get('code')} msg={data.get('msg')}")
