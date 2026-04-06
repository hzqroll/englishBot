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
```

## 架构概览

基于 Clean Architecture 的 NoneBot2 QQ 英语学习机器人，分为四层：

- **`src/plugins/`** — NoneBot2 插件，消息与调度入口（`at_message.py`、`commands.py`、`scheduler.py`）
- **`src/application/`** — 用例层，编排业务流程（MessageUseCase、LearningUseCase、QuizUseCase、ReportUseCase）
- **`src/domain/`** — 领域层，纯业务规则：实体（entities/）、领域服务（services/）、值对象（value_objects/）
- **`src/infrastructure/`** — 基础设施层：数据库（db/）、外部服务（providers/）、配置（settings/）、鉴权（auth/）、缓存（cache/）、消息渲染（messaging/）
- **`src/admin/`** — FastAPI + Jinja2 管理后台

### 依赖注入

手动 DI 容器 `ServiceContainer`（`src/infrastructure/settings/container.py`），在 `src/main.py` 启动时通过 `ensure_container()` 构建。全局单例通过 `get_container()` / `set_container()` 访问。

添加新依赖的步骤：在 `ServiceContainer` 添加字段 → 在 `build_container()` 中构造 → 注入到需要的 use case。

### Provider 模式

外部服务均抽象为 Provider：
- `TencentTranslateProvider` — 腾讯云翻译
- `OpenAICompatibleProvider` — OpenAI 兼容 LLM（纠错、反馈、测验、周报）
- `TedContentProvider` — TED RSS 内容抓取，不可用时回退到内置短文

未配置 API Key 时 Provider 走降级逻辑返回 mock 结果。

### 配置系统

两层配置：
1. **运行时配置**（`.env`）：密钥、端口、数据库 URL — `AppRuntimeSettings`（pydantic-settings）
2. **静态配置**（`config.yaml`）：调度 cron、学习参数、机器人行为 — `StaticConfig`（pydantic BaseModel）

还有数据库层的动态配置覆盖 `RuntimeConfigService`，管理后台可修改。

### 数据库

SQLite + SQLAlchemy 2.0 async（aiosqlite）。ORM 模型在 `src/infrastructure/db/models.py`，数据访问通过 Repository 模式（`IdentityRepository`、`LearningRepository`、`AdminRepository`）。启动时自动建表。

### 消息流程

QQ 群 @机器人 → NoneBot2（OneBot v11）→ `plugins/at_message.py` 或 `plugins/commands.py` → 对应 UseCase → 领域服务 + Provider → 持久化 → 回复

### 消息渲染与卡片

UseCase 统一返回 `MessageEnvelope`（`src/domain/value_objects/messaging.py`），携带纯文本和可选的 `CardDocument` 结构化卡片数据。`MessageDeliveryService`（`src/infrastructure/messaging/renderers.py`）根据 `render_mode` 配置选择渲染策略：

- **`PlainTextRenderer`**：纯文本 + CQ 码
- **`ImageCardRenderer`**：用 Pillow 生成 PNG 图片卡片（1080×1520px），支持多页分页、主题配色、自动文字换行

渲染链路：`render_mode == "image_card"` 时生成图片 → 单页直接发送 / 多页用合并转发 → 失败时回退纯文本（需 `card_fallback_to_text` 开启）。渲染的图片缓存在 `data/rendered_cards/`，自动清理超过 200 个的旧文件。

`CardDocument` 是结构化的卡片文档模型（标题、副标题、`CardSection` 列表、页脚、主题），由 UseCase 构建，再交给 `ImageCardRenderer` 渲染为图片。

### 定时任务

六个 cron 定时任务（`src/plugins/scheduler.py`），通过 `nonebot-apscheduler` 注册：
1. **daily_push** — 晨间推送课程（默认 8:00）
2. **daily_error_digest** — 晚间错误摘要（默认 18:00）
3. **daily_progress** — 每日学习进度（默认 20:00）
4. **weekly_report** — 周报（周一 9:00）
5. **weekly_quiz** — 周测（周日 19:00）
6. **nightly_backup** — 数据库备份（每日 2:00）

所有任务通过 `acquire_job_lock()` 防止并发执行。管理后台 `/admin/triggers/{job_name}` 支持手动触发。修改运行时配置后需调用 `register_jobs()` 刷新调度器。

### 错误分类体系

`src/domain/services/error_taxonomy.py` 提供两层错误分类：
- `label_error_type()` — 返回中文标签（"时态"、"拼写"等）
- `categorize_error_type()` — 归为 `"word"`（单词/表达类）或 `"grammar"`（语法类）

纠错结果通过 `create_error_occurrences()` 记录到 `error_occurrences` 表，关联消息事件和 error_point，支持按类别统计。

### 关键领域逻辑

- **纠错聚合**（`ErrorAggregator`）：按签名去重 error_points
- **间隔复习**（`ReviewScheduler`）：1→2→4→8... 天倍增间隔
- **分级系统**（`LevelService`）：基于活跃度 + 测验分数的 beginner/intermediate 两级
- **上下文缓存**（`ContextStore`）：LRU 缓存，15 分钟 TTL

### 管理后台

`src/admin/routes.py` 中 FastAPI 路由，Session 认证。关键页面：
- `/admin/debug` — 无需 QQ 即可测试翻译/纠错流程（dry_run 和 persist_to_db 两种模式）
- `/admin/cards` — 生成任务/周测/周报的卡片预览
- `/admin/settings` — 运行时配置覆盖，修改后自动刷新调度器
- `/admin/triggers/{job_name}` — 手动触发定时任务

## 开发约定

- Python 3.12，异步优先（async/await）
- 测试框架：pytest + pytest-asyncio（`asyncio_mode = "auto"`）
- 包管理：uv
- `alembic/` 目录已初始化但当前使用启动时 auto-create，非强制迁移
- Provider 缺少配置时走降级而非报错
- 测试用轻量 stub 类注入依赖，数据库测试用 `tmp_path` 临时 SQLite，不依赖 mock 框架
- Pillow 用于图片卡片渲染，字体依赖系统字体路径
