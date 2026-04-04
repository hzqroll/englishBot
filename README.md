# English Learning QQ Bot

一个基于 `NoneBot2 + NapCat + SQLite + FastAPI` 的英语学习 QQ 机器人。

## 当前能力

- 群内 `@机器人` 自动识别中英文，执行翻译、英文纠错和表达优化
- 把纠错结果沉淀为 `error_points` 和 `review_items`
- 支持固定命令：`报名学习`、`今日任务`、`提交任务`、`复习一下`、`我的等级`、`开始周测`、`答题`、`本周总结`、`帮助`
- 支持任务类卡片预览：`今日任务`、`周测`、`周报` 可生成 NapCat `json` 卡片和免登录签名学习页
- 提供 `FastAPI + Jinja2` 管理后台
- 支持定时推送、周报、周测、SQLite 备份和动态配置覆盖

## 交互规则

- 学习系统命令请直接发送，不需要 `@机器人`
- `@机器人` 只用于翻译、纠错、表达润色、语法解释
- 如果发送 `@机器人 报名学习` 这类消息，机器人会提示改用固定命令
- 当 `message.public_base_url` 为空时，群内仍会自动回退为纯文本，不会发不可访问的卡片链接

## 项目结构

- `src/main.py`：应用入口
- `src/plugins/`：NoneBot 消息入口与调度入口
- `src/application/`：应用服务和业务编排
- `src/domain/`：领域规则
- `src/infrastructure/`：数据库、Provider、配置与鉴权
- `src/admin/`：管理后台页面和路由
- `deploy/`：Docker、Caddy、示例配置和部署文档

## 外部接口

- 翻译：腾讯云机器翻译 `TextTranslate`
- 大模型：OpenAI 兼容 `chat/completions` 接口
- 数据库：本地 SQLite 文件

## 本地开发

1. 在项目根目录复制运行时文件：

```bash
cp deploy/.env.example .env
cp deploy/config.example.yaml config.yaml
```

2. 按需修改 `.env` 和 `config.yaml`。
3. 安装依赖并启动：

```bash
uv python install 3.12
uv sync --python 3.12 --extra dev
uv run python -m src.main
```

4. 打开后台：

- `http://127.0.0.1:8080/admin/login`
- `http://127.0.0.1:8080/healthz`
- `http://127.0.0.1:8080/admin/debug`（联调调试页，可直接测试翻译/纠错）
- `http://127.0.0.1:8080/admin/cards`（卡片预览页，可生成任务/周测/周报的本地签名链接）

5. 本地使用 Docker + NapCat 联调时，可以用脚本自动配置反向 WebSocket：

```bash
uv run python scripts/configure_napcat_ws.py --refresh-qr
```

- 如果 NapCat 还没登录 QQ，脚本会直接输出当前二维码 URL
- 登录成功后再次运行，会自动写入 `websocketClients`
- 默认会配置到 `ws://bot-app:8080/onebot/v11/ws`

## Docker 部署

部署步骤见 [deploy/DEPLOY.md](deploy/DEPLOY.md)。

最短路径：

```bash
cd deploy
cp .env.example .env
cp config.example.yaml config.yaml
docker compose up -d --build
```

启动后：

- 管理后台：`http://<你的服务器 IP>:<CADDY_HTTP_PORT>/admin/login`
- 健康检查：`http://<你的服务器 IP>:<CADDY_HTTP_PORT>/healthz`
- NapCat WebUI：`http://<你的服务器 IP>:<NAPCAT_WEBUI_PORT>`
- NapCat 登录态会持久化到 `data/napcat-qq/`
- NapCat 二维码缓存会持久化到 `data/napcat-cache/`

## 当前边界

- 第一版只面向单群试点
- 周测目前是客观题
- TED 内容源不可用时会回退到内置短文
- 未配置腾讯翻译或大模型密钥时，相关能力会走降级逻辑
- 当前 NapCat 卡片路线默认优先做“整卡点击跳转”，不承诺官方机器人那种稳定按钮回调
