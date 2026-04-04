from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WEBUI_CONFIG = ROOT / "data" / "napcat" / "webui.json"
DEFAULT_ENV_FILES = [ROOT / ".env", ROOT / "deploy" / ".env"]


class NapCatSetupError(RuntimeError):
    pass


def load_access_token() -> str:
    for env_path in DEFAULT_ENV_FILES:
        if not env_path.exists():
            continue
        values = dotenv_values(env_path)
        access_token = values.get("ACCESS_TOKEN")
        if access_token:
            return str(access_token)
    raise NapCatSetupError("没有找到 ACCESS_TOKEN，请先配置 .env 或 deploy/.env。")


def load_webui_token(webui_config_path: Path) -> str:
    if not webui_config_path.exists():
        raise NapCatSetupError(f"找不到 NapCat WebUI 配置文件: {webui_config_path}")
    data = json.loads(webui_config_path.read_text(encoding="utf-8"))
    token = data.get("token")
    if not token:
        raise NapCatSetupError("NapCat WebUI token 为空，请先启动 docker compose。")
    return str(token)


def login_webui(base_url: str, webui_token: str) -> str:
    token_hash = hashlib.sha256(f"{webui_token}.napcat".encode("utf-8")).hexdigest()
    response = requests.post(
        f"{base_url}/api/auth/login",
        json={"hash": token_hash},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise NapCatSetupError(f"NapCat WebUI 登录失败: {payload}")
    credential = payload.get("data", {}).get("Credential")
    if not credential:
        raise NapCatSetupError("NapCat WebUI 未返回 Credential。")
    return str(credential)


def api_post(base_url: str, credential: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.post(
        f"{base_url}/api/{path}",
        headers={"Authorization": f"Bearer {credential}"},
        json=body or {},
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0:
        raise NapCatSetupError(payload.get("message", f"{path} 调用失败"))
    return payload


def ensure_ws_client(
    config: dict[str, Any],
    *,
    name: str,
    url: str,
    access_token: str,
    enable: bool,
    debug: bool,
    report_self_message: bool,
    message_post_format: str,
    heart_interval: int,
    reconnect_interval: int,
) -> dict[str, Any]:
    network = config.setdefault("network", {})
    websocket_clients = network.setdefault("websocketClients", [])

    ws_client = {
        "enable": enable,
        "name": name,
        "url": url,
        "reportSelfMessage": report_self_message,
        "messagePostFormat": message_post_format,
        "token": access_token,
        "debug": debug,
        "heartInterval": heart_interval,
        "reconnectInterval": reconnect_interval,
    }

    for index, item in enumerate(websocket_clients):
        if item.get("name") == name:
            websocket_clients[index] = ws_client
            break
    else:
        websocket_clients.append(ws_client)

    return config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="配置 NapCat 的 OneBot 反向 WebSocket 客户端。")
    parser.add_argument("--base-url", default="http://127.0.0.1:6099", help="NapCat WebUI 地址")
    parser.add_argument("--webui-config", default=str(DEFAULT_WEBUI_CONFIG), help="NapCat webui.json 路径")
    parser.add_argument("--name", default="english-bot-local", help="NapCat 网络配置名称")
    parser.add_argument("--url", default="ws://bot-app:8080/onebot/v11/ws", help="OneBot 反向 WebSocket 地址")
    parser.add_argument("--message-post-format", default="array", choices=["array", "string"], help="OneBot 消息格式")
    parser.add_argument("--heart-interval", type=int, default=30000, help="心跳间隔，毫秒")
    parser.add_argument("--reconnect-interval", type=int, default=30000, help="重连间隔，毫秒")
    parser.add_argument("--report-self-message", action="store_true", help="启用上报自身消息")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument("--disable", action="store_true", help="创建但不启用此网络配置")
    parser.add_argument("--refresh-qr", action="store_true", help="若 QQ 未登录，先刷新二维码再输出二维码地址")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    webui_token = load_webui_token(Path(args.webui_config))
    access_token = load_access_token()
    credential = login_webui(args.base_url.rstrip("/"), webui_token)

    if args.refresh_qr:
        try:
            api_post(args.base_url, credential, "QQLogin/RefreshQRcode")
        except NapCatSetupError as exc:
            if "QQ Is Logined" not in str(exc):
                raise

    login_status = api_post(args.base_url, credential, "QQLogin/CheckLoginStatus")["data"]
    if not login_status.get("isLogin"):
        qrcode = api_post(args.base_url, credential, "QQLogin/GetQQLoginQrcode")["data"]["qrcode"]
        print("NapCat 尚未登录 QQ。")
        if login_status.get("loginError"):
            print(f"当前登录状态: {login_status['loginError']}")
        print(f"请先扫码登录: {qrcode}")
        print("登录成功后重新运行本脚本，即可自动写入反向 WebSocket 配置。")
        return 1

    config_payload = api_post(args.base_url, credential, "OB11Config/GetConfig")["data"]
    updated_config = ensure_ws_client(
        config_payload,
        name=args.name,
        url=args.url,
        access_token=access_token,
        enable=not args.disable,
        debug=args.debug,
        report_self_message=args.report_self_message,
        message_post_format=args.message_post_format,
        heart_interval=args.heart_interval,
        reconnect_interval=args.reconnect_interval,
    )
    api_post(
        args.base_url,
        credential,
        "OB11Config/SetConfig",
        {"config": json.dumps(updated_config, ensure_ascii=False)},
    )
    print("NapCat 反向 WebSocket 配置已写入。")
    print(f"name: {args.name}")
    print(f"url:  {args.url}")
    print(f"token 已同步为 .env 中的 ACCESS_TOKEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
