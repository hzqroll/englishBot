# AGENTS.md
本文件为 AI Agent 在此代码库中工作时提供指导

## 常用命令

```bash
# 安装依赖
uv sync --python 3.12 --extra dev

# 启动应用（需要先准备 .env 和 config.yaml）
cp deploy/.env.example .env
cp deploy/config.example.yaml config.yaml
uv run python -m src.main

# 运行全部测试
uv run pytest

# 运行单个测试文件
uv run pytest tests/test_learning_repository.py

# 运行单个测试函数
uv run pytest tests/test_learning_repository.py::test_function_name

# 部署到远程服务器
rsync -avz --exclude='.venv' --exclude='__pycache__' --exclude='.git' src/ ubuntu@110.40.137.26:/home/ubuntu/englishBot/src/
ssh ubuntu@110.40.137.26 "cd /home/ubuntu/englishBot && find src -name '__pycache__' -exec rm -rf {} +; sudo systemctl restart englishbot"
```

## 架构概览

基于 Clean Architecture 的 NoneBot2 英语学习机器人，支持 QQ 和飞书双渠道，分为四层：

- **`src/plugins/`** — NoneBot2 插件，消息与调度入口（`at_message.py`、`commands.py`、`scheduler.py`）
- **`src/application/`** — 用例层，编排业务流程（MessageUseCase、LearningUseCase、QuizUseCase、ReportUseCase、ConversationUseCase）
- **`src/domain/`** — 领域层，纯业务规则：实体（entities/）、领域服务（services/）、值对象（value_objects/）
- **`src/infrastructure/`** — 基础设施层：数据库（db/）、外部服务（providers/）、配置（settings/）、鉴权（auth/）、缓存（cache/）、消息渲染（messaging/）、渠道适配（channels/）
- **`src/admin/`** — FastAPI + Jinja2 管理后台

### 多渠道架构

系统通过 `ChannelAdapter` 抽象（`src/infrastructure/channels/base.py`）支持多平台：

- **OneBotChannel**（`channels/onebot.py`）— QQ 渠道，通过 NoneBot2 OneBot v11 适配器收发消息
- **FeishuChannel**（`channels/feishu.py`）— 飞书渠道，通过 lark-oapi SDK 发送消息和拉取历史
- **FeishuBot**（`channels/feishu_bot.py`）— 飞书 WebSocket 入口，独立守护线程接收事件

渠道注册在 `ServiceContainer.channels: dict[str, ChannelAdapter]` 中。调度器通过 `group_id.startswith("oc_")` 判断飞书群，其余走 QQ 渠道。

飞书渠道的特殊处理：
- 回调在飞书 WS 线程中执行，通过 `asyncio.run_coroutine_threadsafe` 提交到 NoneBot2 主事件循环
- 卡片渲染使用飞书互动卡片 JSON（`msg_type: "interactive"`），不需要 Pillow
- 消息历史通过 `ListMessageRequest` API 拉取
- SDK 数据模型使用 `message_type`（非 `msg_type`）

### 依赖注入

手动 DI 容器 `ServiceContainer`（`src/infrastructure/settings/container.py`），在 `src/main.py` 启动时通过 `ensure_container()` 构建。全局单例通过 `get_container()` / `set_container()` 访问。

添加新依赖的步骤：在 `ServiceContainer` 添加字段 → 在 `build_container()` 中构造 → 注入到需要的 use case。

### Provider 模式

外部服务均抽象为 Provider：
- `TencentTranslateProvider` — 腾讯云翻译
- `OpenAICompatibleProvider` — OpenAI 兼容 LLM（纠错、反馈、测验、周报）
- `TedContentProvider` / `StaticCurriculumProvider` — TED RSS 内容抓取，不可用时回退到内置短文

未配置 API Key 时 Provider 走降级逻辑返回 mock 结果。

### 配置系统

两层配置：
1. **运行时配置**（`.env`）：密钥、端口、数据库 URL — `AppRuntimeSettings`（pydantic-settings）
2. **静态配置**（`config.yaml`）：调度 cron、学习参数、机器人行为 — `StaticConfig`（pydantic BaseModel）

还有数据库层的动态配置覆盖 `RuntimeConfigService`，管理后台可修改。

### 数据库

SQLite + SQLAlchemy 2.0 async（aiosqlite）。ORM 模型在 `src/infrastructure/db/models.py`，数据访问通过 Repository 模式（`IdentityRepository`、`LearningRepository`、`AdminRepository`）。启动时自动建表和 schema 升级（`_upgrade_sqlite_schema`）。

### 消息流程

**QQ 渠道**：QQ 群消息 → NapCat → OneBot v11 → NoneBot2 → `plugins/at_message.py` 或 `plugins/commands.py` → UseCase → 回复

**飞书渠道**：飞书群消息 → WebSocket → `FeishuBot._on_message()` → `_dispatch()` → UseCase → `FeishuChannel.send_text()` / `send_envelope()`

**调度推送**：`scheduler.py` 定时任务 → `_send_group_envelope()` → 根据 `group_id` 前缀选择渠道发送

### 消息渲染与卡片

UseCase 统一返回 `MessageEnvelope`（`src/domain/value_objects/messaging.py`），携带纯文本和可选的 `CardDocument` 结构化卡片数据。

- **QQ 渠道**：`MessageDeliveryService`（`src/infrastructure/messaging/renderers.py`）根据 `render_mode` 选择 `PlainTextRenderer`（CQ 码）或 `ImageCardRenderer`（Pillow 生成 PNG）
- **飞书渠道**：`FeishuChannel._render_card_document()` 将 `CardDocument` 渲染为飞书互动卡片 JSON

`CardDocument` 是结构化的卡片文档模型（标题、副标题、`CardSection` 列表、页脚、主题），由 UseCase 构建，各渠道自行渲染。

### 定时任务

六个 cron 定时任务（`src/plugins/scheduler.py`），通过 `nonebot-apscheduler` 注册：
1. **daily_push** — 晨间推送课程（默认 8:00）
2. **daily_error_digest** — 晚间错误摘要（默认 18:00）
3. **daily_progress** — 每日学习进度（默认 20:00）
4. **weekly_report** — 周报（周一 9:00）
5. **weekly_quiz** — 周测（周日 19:00）
6. **nightly_backup** — 数据库备份（每日 2:00）

所有任务通过 `acquire_job_lock()` 防止并发执行，管理后台 `/admin/triggers/{job_name}` 支持手动触发。所有任务同时推送 QQ 群和飞书群。

### 错误分类体系

`src/domain/services/error_taxonomy.py` 提供两层错误分类：
- `label_error_type()` — 返回中文标签（"时态"、"拼写"等）
- `categorize_error_type()` — 归为 `"word"`（单词/表达类）或 `"grammar"`（语法类）

### 关键领域逻辑

- **纠错聚合**（`ErrorAggregator`）：按签名去重 error_points
- **间隔复习**（`ReviewScheduler`）：1→2→4→8... 天倍增间隔
- **分级系统**（`LevelService`）：基于活跃度 + 测验分数的 beginner/intermediate 两级
- **上下文缓存**（`ContextStore`）：LRU 缓存，15 分钟 TTL
- **命令路由**（`command_catalog.py`）：固定命令文本匹配，支持 `is_fixed_command_text()` 判断

### 管理后台

`src/admin/routes.py` 中 FastAPI 路由，Session 认证。关键页面：
- `/admin/debug` — 无需 QQ 即可测试翻译/纠错流程
- `/admin/cards` — 生成任务/周测/周报的卡片预览
- `/admin/settings` — 运行时配置覆盖，修改后自动刷新调度器
- `/admin/triggers/{job_name}` — 手动触发定时任务
- `/admin/groups` — 群组管理
- `/admin/logs` — 作业运行和消息投递日志查询

## 开发约定

- Python 3.12，异步优先（async/await）
- 测试框架：pytest + pytest-asyncio（`asyncio_mode = "auto"`）
- 包管理：uv
- `alembic/` 目录已初始化但当前使用启动时 auto-create，非强制迁移
- Provider 缺少配置时走降级而非报错
- 测试用轻量 stub 类注入依赖，数据库测试用 `tmp_path` 临时 SQLite，不依赖 mock 框架
- Pillow 用于 QQ 渠道图片卡片渲染，飞书渠道不需要图片渲染
