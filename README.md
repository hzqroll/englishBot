# English Learning QQ Bot

一个基于 `NoneBot2 + NapCat + SQLite + FastAPI` 的英语学习群机器人，当前支持 QQ 和飞书双渠道。

## 方案文档

- 当前功能说明书：[docs/EnglishBotProductOverview.md](docs/EnglishBotProductOverview.md)
- 产品评估与优化建议：[docs/EnglishBotProductEvaluation.md](docs/EnglishBotProductEvaluation.md)
- 产品设计：[docs/product-design.md](docs/product-design.md)
- 第一版技术方案：[docs/technical-solution-v1.md](docs/technical-solution-v1.md)
- 第一版开发计划与 Todo：[docs/development-plan-v1.md](docs/development-plan-v1.md)

## 当前能力

- 群内 `@机器人` 自动识别中英文，执行翻译、英文纠错和表达优化
- 把纠错结果沉淀为 `error_points` 和 `review_items`
- 支持固定命令：`报名学习`、`今日任务`、`提交任务`、`复习一下`、`我的等级`、`开始周测`、`答题`、`本周总结`、`帮助`
- 支持任务类消息卡片：`今日任务`、`周测`、`周报` 直接在群消息里展示完整内容
- 飞书侧支持每日 `Friends` 对话学习推送，并可按集归档到飞书文档
- 提供 `FastAPI + Jinja2` 管理后台
- 支持定时推送、周报、周测、SQLite 备份和动态配置覆盖

## 交互规则

- 学习系统命令请直接发送，不需要 `@机器人`
- `@机器人` 只用于翻译、纠错、表达润色、语法解释
- 如果发送 `@机器人 报名学习` 这类消息，机器人会提示改用固定命令
- `@机器人` 翻译/纠错默认继续使用文本回复，学习系统消息优先走图片卡片

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
- 一期不再依赖 H5 学习页和跳转卡，任务/周测/周报统一以群内图片卡片展示
