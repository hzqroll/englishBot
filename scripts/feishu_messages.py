# -*- coding: utf-8 -*-
"""飞书群消息拉取工具。

按时间范围拉取飞书群消息，支持分页和多种输出格式。

用法:
    # 拉取最近 1 小时的消息
    uv run python scripts/feishu_messages.py --chat-id oc_xxx --last 1h

    # 拉取最近 30 分钟
    uv run python scripts/feishu_messages.py --chat-id oc_xxx --last 30m

    # 指定时间范围
    uv run python scripts/feishu_messages.py --chat-id oc_xxx --from "2026-04-08 09:00" --to "2026-04-08 18:00"

    # 输出 JSON
    uv run python scripts/feishu_messages.py --chat-id oc_xxx --last 1h --format json

    # 限制消息数量
    uv run python scripts/feishu_messages.py --chat-id oc_xxx --last 1h --limit 100
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import lark_oapi as lark
from lark_oapi.api.im.v1 import ListMessageRequest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILES = [ROOT / ".env", ROOT / "deploy" / ".env"]

# 中国标准时间
CST = timezone(timedelta(hours=8))


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


def parse_relative_time(s: str) -> datetime:
    """解析相对时间字符串，如 '1h'、'30m'、'2d'。"""
    m = re.match(r"^(\d+)([hmd])$", s.lower())
    if not m:
        raise ValueError(f"无法解析相对时间: {s}（支持格式: 1h, 30m, 2d）")
    amount = int(m.group(1))
    unit = m.group(2)
    now = datetime.now(tz=CST)
    deltas = {"h": timedelta(hours=amount), "m": timedelta(minutes=amount), "d": timedelta(days=amount)}
    return now - deltas[unit]


def parse_absolute_time(s: str) -> datetime:
    """解析绝对时间字符串，格式: 'YYYY-MM-DD HH:MM' 或 'YYYY-MM-DD'。"""
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=CST)
        except ValueError:
            continue
    raise ValueError(f"无法解析时间: {s}（支持格式: YYYY-MM-DD HH:MM, YYYY-MM-DD）")


def resolve_time_range(args: argparse.Namespace) -> tuple[datetime, datetime]:
    """根据参数解析时间范围。"""
    now = datetime.now(tz=CST)
    if args.last:
        return parse_relative_time(args.last), now
    if args.from_time:
        start = parse_absolute_time(args.from_time)
        end = parse_absolute_time(args.to_time) if args.to_time else now
        return start, end
    raise ValueError("请指定 --last 或 --from 参数")


def fetch_messages(
    client: lark.Client,
    chat_id: str,
    start: datetime,
    end: datetime,
    limit: int = 0,
) -> list[dict]:
    """拉取飞书群消息，支持完整分页。"""
    messages: list[dict] = []
    page_token = None
    start_ts = str(int(start.timestamp()))
    end_ts = str(int(end.timestamp()))

    while True:
        builder = (
            ListMessageRequest.builder()
            .container_id_type("chat")
            .container_id(chat_id)
            .start_time(start_ts)
            .end_time(end_ts)
            .page_size(50)
        )
        if page_token:
            builder = builder.page_token(page_token)

        response = client.im.v1.message.list(builder.build())

        if not response.success():
            print(f"API 错误: code={response.code} msg={response.msg}", file=sys.stderr)
            break

        if not response.data or not response.data.items:
            break

        for item in response.data.items:
            text = ""
            if item.body and item.body.content:
                try:
                    obj = json.loads(item.body.content)
                    text = obj.get("text", "")
                except (json.JSONDecodeError, TypeError):
                    text = str(item.body.content)

            sender_id = item.sender.id if item.sender else ""
            create_time = getattr(item, "create_time", "")

            # 解析飞书时间戳（毫秒）
            ts = ""
            if create_time:
                try:
                    ts = datetime.fromtimestamp(int(create_time) / 1000, tz=CST).strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, TypeError, OSError):
                    ts = str(create_time)

            messages.append({
                "message_id": item.message_id or "",
                "sender_id": sender_id,
                "timestamp": ts,
                "text": text,
                "msg_type": item.msg_type or "",
            })

            if limit and len(messages) >= limit:
                return messages

        if not response.data.has_more:
            break
        page_token = response.data.page_token

    return messages


def format_text(messages: list[dict]) -> str:
    """格式化为纯文本输出。"""
    lines: list[str] = []
    for msg in messages:
        ts = msg["timestamp"]
        sender = msg["sender_id"][:12] if msg["sender_id"] else "unknown"
        text = msg["text"]
        lines.append(f"[{ts}] {sender}: {text}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="飞书群消息拉取工具")
    parser.add_argument("--chat-id", required=True, help="飞书群 chat ID（oc_ 开头）")

    time_group = parser.add_mutually_exclusive_group(required=True)
    time_group.add_argument("--last", help="拉取最近 N 时间段的消息（如 1h, 30m, 2d）")
    time_group.add_argument("--from", dest="from_time", help="起始时间（YYYY-MM-DD HH:MM）")
    parser.add_argument("--to", dest="to_time", help="结束时间（配合 --from 使用，默认当前时间）")

    parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式（默认: text）")
    parser.add_argument("--limit", type=int, default=0, help="限制最大消息数量（0=不限制）")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    start, end = resolve_time_range(args)

    app_id, app_secret = load_credentials()
    client = (
        lark.Client.builder()
        .app_id(app_id)
        .app_secret(app_secret)
        .log_level(lark.LogLevel.WARNING)
        .build()
    )

    print(f"拉取 {start.strftime('%Y-%m-%d %H:%M')} ~ {end.strftime('%Y-%m-%d %H:%M')} 的消息...", file=sys.stderr)
    messages = fetch_messages(client, args.chat_id, start, end, limit=args.limit)
    print(f"共 {len(messages)} 条消息", file=sys.stderr)

    if args.format == "json":
        print(json.dumps(messages, ensure_ascii=False, indent=2))
    else:
        output = format_text(messages)
        if output:
            print(output)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        raise SystemExit(1)
