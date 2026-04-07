from __future__ import annotations

import logging

import lark_oapi as lark
from lark_oapi.api.docx.v1 import (
    CreateDocumentBlockChildrenRequest,
    CreateDocumentBlockChildrenRequestBody,
    CreateDocumentRequest,
    CreateDocumentRequestBody,
)
from lark_oapi.api.drive.v1 import CreateFolderFileRequest, CreateFolderFileRequestBody

logger = logging.getLogger(__name__)


class FeishuDocsError(Exception):
    """飞书文档 API 调用失败。"""


class FeishuDocsClient:
    """封装飞书文档/云空间 API。"""

    def __init__(self, *, app_id: str, app_secret: str) -> None:
        self._client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .log_level(lark.LogLevel.INFO)
            .build()
        )

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
        """向文档末尾追加内容块。"""
        request = (
            CreateDocumentBlockChildrenRequest.builder()
            .document_id(document_id)
            .block_id(document_id)
            .request_body(
                CreateDocumentBlockChildrenRequestBody.builder()
                .children(blocks)
                .index(-1)
                .build()
            )
            .build()
        )
        resp = self._client.docx.v1.document_block_children.create(request)
        if not resp.success():
            raise FeishuDocsError(f"append_blocks failed: code={resp.code} msg={resp.msg}")
