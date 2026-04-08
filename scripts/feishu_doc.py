# -*- coding: utf-8 -*-
"""飞书文档写入工具。

在飞书云空间中创建文档并写入文本内容。

用法:
    # 从文件写入
    uv run python scripts/feishu_doc.py --title "文档标题" --file content.txt

    # 从命令行写入
    uv run python scripts/feishu_doc.py --title "文档标题" --text "内容"

    # 从 stdin 管道写入
    echo "内容" | uv run python scripts/feishu_doc.py --title "文档标题"

    # 指定父文件夹
    uv run python scripts/feishu_doc.py --title "文档标题" --file content.txt --folder "其他文件夹"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.infrastructure.docs.feishu_docs_client import FeishuDocsClient, FeishuDocsError

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILES = [ROOT / ".env", ROOT / "deploy" / ".env"]
DEFAULT_FOLDER = "englishImprovePlan"


def load_credentials() -> tuple[str, str]:
    for env_path in DEFAULT_ENV_FILES:
        if not env_path.exists():
            continue
        values = dotenv_values(env_path)
        app_id = values.get("FEISHU_APP_ID")
        app_secret = values.get("FEISHU_APP_SECRET")
        if app_id and app_secret:
            return str(app_id), str(app_secret)
    raise RuntimeError("未找到 FEISHU_APP_ID / FEISHU_APP_SECRET，请检查 .env 文件。")


def _text_block(content: str, bold: bool = False) -> dict:
    style = {"bold": bold} if bold else {}
    return {
        "block_type": 2,
        "text": {"elements": [{"text_run": {"content": content, "text_element_style": style}}]},
    }


def _divider_block() -> dict:
    return {"block_type": 22, "divider": {}}


def content_to_blocks(text: str) -> list[dict]:
    """将文本按行转换为飞书文档内容块。"""
    blocks: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            blocks.append(_divider_block())
        else:
            blocks.append(_text_block(line))
    return blocks


def read_content(args: argparse.Namespace) -> str:
    """从参数或 stdin 读取内容。"""
    if args.text:
        return args.text
    if args.file:
        path = Path(args.file)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        return path.read_text(encoding="utf-8")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise ValueError("请通过 --text、--file 或 stdin 管道提供内容。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="飞书文档写入工具")
    parser.add_argument("--title", required=True, help="文档标题")
    parser.add_argument("--text", help="直接指定文本内容")
    parser.add_argument("--file", help="从本地文件读取内容")
    parser.add_argument("--folder", default=DEFAULT_FOLDER, help=f"父文件夹名称（默认: {DEFAULT_FOLDER}）")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    content = read_content(args)

    app_id, app_secret = load_credentials()
    client = FeishuDocsClient(app_id=app_id, app_secret=app_secret)

    print(f"创建文件夹 '{args.folder}'...")
    folder_token = client.create_folder(name=args.folder)
    print(f"  folder_token: {folder_token}")

    print(f"创建文档 '{args.title}'...")
    doc_id = client.create_document(title=args.title, folder_token=folder_token)
    doc_url = f"https://bytedance.larkoffice.com/docx/{doc_id}"
    print(f"  document_id: {doc_id}")

    blocks = content_to_blocks(content)
    if blocks:
        print(f"写入 {len(blocks)} 个内容块...")
        client.append_blocks(document_id=doc_id, blocks=blocks)

    print(f"\n文档链接: {doc_url}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FeishuDocsError, FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
