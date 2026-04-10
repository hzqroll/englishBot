# Deployment Guide

本文档描述如何在一台可以访问公网的机器上部署英语学习飞书机器人。

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
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- `CADDY_HTTP_PORT`
  - 默认 `80`。

可以用下面的命令生成一个随机 `SECRET_KEY`：

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
```

## 3. 修改 `config.yaml`

至少需要确认这些配置：

- `feishu.enabled_group_ids`
  - 允许机器人工作的飞书群 chat_id 列表（`oc_` 开头）。
- `scheduler.*`
  - 每日任务、提醒、周报、周测、夜间备份时间。
- `learning.weekly_quiz_question_count`
- `learning.weekly_quiz_review_ratio`

如果现在只做单群试点，推荐先只保留一个群 ID。

## 4. 启动服务

```bash
docker compose up -d --build
```

启动后可先检查：

```bash
docker compose ps
docker compose logs -f bot-app
```

## 5. 验证服务

机器人服务就绪后，可以访问：

- `http://<你的服务器 IP>:<CADDY_HTTP_PORT>/healthz`
- `http://<你的服务器 IP>:<CADDY_HTTP_PORT>/readyz`
- `http://<你的服务器 IP>:<CADDY_HTTP_PORT>/admin/login`

后台默认使用 `.env` 中的管理员账号密码登录。

## 6. 首次群内联调

建议按这个顺序验证：

1. 在目标飞书群里 `@机器人` 发送一条中文，确认能返回英文翻译。
2. 再 `@机器人` 发送一条有明显错误的英文，确认能返回纠错结果。
3. 发送 `报名学习`，再发送 `今日任务`。
4. 提交一条任务，再发送 `本周总结` 和 `开始周测`。
5. 登录后台查看仪表盘和运行时配置页，确认消息、错误点、任务和周测数据已入库。

## 7. 常见问题

### 后台可以打开，但群里没回复

通常是这几类问题：

- 目标群 ID 没有写入 `feishu.enabled_group_ids`
- `FEISHU_APP_ID` 或 `FEISHU_APP_SECRET` 配置错误
- 飞书应用未正确配置事件订阅

### 大模型调用失败

先核对：

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`

如果密钥未配置，机器人会退化为 mock 或简化逻辑，适合本地演示，不适合正式学习群。

## 8. 当前上线建议

当前部署形态仍是 `公网 IP + HTTP`，适合试点联调，不适合长期公开暴露。

正式上线建议下一步做两件事：

1. 给 Caddy 配域名和 HTTPS
2. 把后台访问限制到固定 IP 或增加更强的登录保护
