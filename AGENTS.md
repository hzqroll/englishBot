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
- **`src/infrastructure/`** — 基础设施层：数据库（db/）、外部服务（providers/）、配置（settings/）、鉴权（auth/）、缓存（cache/）
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

### 关键领域逻辑

- **纠错聚合**（`ErrorAggregator`）：按签名去重 error_points
- **间隔复习**（`ReviewScheduler`）：1→2→4→8... 天倍增间隔
- **分级系统**（`LevelService`）：基于活跃度 + 测验分数的 beginner/intermediate 两级
- **上下文缓存**（`ContextStore`）：LRU 缓存，15 分钟 TTL

## 开发约定

- Python 3.12，异步优先（async/await）
- 测试框架：pytest + pytest-asyncio（`asyncio_mode = "auto"`）
- 包管理：uv
- 无 Alembic 迁移脚本的硬性要求，当前使用启动时 auto-create
- Provider 缺少配置时走降级而非报错
