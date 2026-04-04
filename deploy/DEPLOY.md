# Deployment Guide

本文档描述如何在一台可以访问公网的机器上部署英语学习 QQ 机器人。

## 1. 准备文件

在 `deploy/` 目录下复制配置模板：

```bash
cd deploy
cp .env.example .env
cp config.example.yaml config.yaml
```

需要重点修改的文件：

- `.env`
- `config.yaml`

## 2. 修改 `.env`

至少需要调整以下字段：

- `SECRET_KEY`
  - 用一个足够长的随机字符串，供后台 Session 使用。
- `ACCESS_TOKEN`
  - OneBot 访问令牌。NapCat 反向 WebSocket 配置里要使用同一个值。
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `TENCENT_TRANSLATE_SECRET_ID`
- `TENCENT_TRANSLATE_SECRET_KEY`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `CADDY_HTTP_PORT`
  - 默认 `80`。
- `NAPCAT_WEBUI_PORT`
  - 默认 `6099`。

可以用下面的命令生成一个随机 `SECRET_KEY`：

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
```

## 3. 修改 `config.yaml`

至少需要确认这些配置：

- `bot.enabled_group_ids`
  - 允许机器人工作的群号列表。
- `bot.admin_group_ids`
  - 允许发管理通知的群号。
- `scheduler.*`
  - 每日任务、提醒、周报、周测、夜间备份时间。
- `learning.weekly_quiz_question_count`
- `learning.weekly_quiz_review_ratio`

如果现在只做单群试点，推荐先只保留一个群号。

## 4. 启动服务

```bash
docker compose up -d --build
```

启动后可先检查：

```bash
docker compose ps
docker compose logs -f bot-app
```

这套 Compose 会持久化以下目录：

- `../data/napcat`
  - NapCat WebUI 配置
- `../data/napcat-qq`
  - QQ 登录态与账号数据，避免容器重启后反复扫码
- `../data/napcat-cache`
  - NapCat 二维码缓存与临时文件

## 5. 配置 NapCat

当前 Compose 会把 NapCat WebUI 暴露到：

```text
http://<你的服务器 IP>:<NAPCAT_WEBUI_PORT>
```

完成 QQ 登录后，在 NapCat 的 OneBot 网络配置中新增一个反向 WebSocket 连接：

- 连接地址：`ws://bot-app:8080/onebot/v11/ws`
- 访问令牌：与 `.env` 里的 `ACCESS_TOKEN` 保持一致
- 启用连接后保存

如果你使用的是当前仓库，也可以直接运行：

```bash
uv run python scripts/configure_napcat_ws.py --refresh-qr
```

这个脚本会：

- 在未登录时输出当前二维码 URL
- 在已登录时自动把 `websocketClients` 写成 `ws://bot-app:8080/onebot/v11/ws`
- 自动把 `.env` 中的 `ACCESS_TOKEN` 同步到 NapCat 的 OneBot 配置

这里必须使用容器内地址 `bot-app:8080`，因为 NapCat 和机器人在同一个 Compose 网络里。

如果你不是用这套 Compose，而是把 NapCat 单独部署在另一台机器上，则连接地址应改成机器人实际可访问的公网地址，例如：

```text
ws://<服务器公网 IP>:8080/onebot/v11/ws
```

## 6. 验证服务

机器人服务就绪后，可以访问：

- `http://<你的服务器 IP>:<CADDY_HTTP_PORT>/healthz`
- `http://<你的服务器 IP>:<CADDY_HTTP_PORT>/readyz`
- `http://<你的服务器 IP>:<CADDY_HTTP_PORT>/admin/login`

后台默认使用 `.env` 中的管理员账号密码登录。

## 7. 首次群内联调

建议按这个顺序验证：

1. 在目标群里 `@机器人` 发送一条中文，确认能返回英文翻译。
2. 再 `@机器人` 发送一条有明显错误的英文，确认能返回纠错结果。
3. 发送 `报名学习`，再发送 `今日任务`。
4. 提交一条任务，再发送 `本周总结` 和 `开始周测`。
5. 登录后台查看仪表盘和运行时配置页，确认消息、错误点、任务和周测数据已入库。

## 8. 常见问题

### NapCat 连不上机器人

优先检查这几项：

- NapCat 反向 WebSocket 地址是否填成了 `ws://bot-app:8080/onebot/v11/ws`
- NapCat 使用的 `ACCESS_TOKEN` 是否与 `.env` 一致
- `bot-app` 是否已经启动成功
- `docker compose logs -f bot-app napcat` 中是否有鉴权失败或连接失败日志

### 后台可以打开，但群里没回复

通常是这几类问题：

- 目标群号没有写入 `bot.enabled_group_ids`
- NapCat 还没成功登录 QQ
- OneBot 连接未启用
- `ACCESS_TOKEN` 不一致

### 大模型或腾讯翻译调用失败

先核对：

- `TENCENT_TRANSLATE_SECRET_ID`
- `TENCENT_TRANSLATE_SECRET_KEY`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`

如果密钥未配置，机器人会退化为 mock 或简化逻辑，适合本地演示，不适合正式学习群。

## 9. 当前上线建议

当前部署形态仍是 `公网 IP + HTTP`，适合试点联调，不适合长期公开暴露。

正式上线建议下一步做两件事：

1. 给 Caddy 配域名和 HTTPS
2. 把后台访问限制到固定 IP 或增加更强的登录保护
