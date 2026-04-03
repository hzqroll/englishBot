# English Learning QQ Bot

一个基于 `NoneBot2 + NapCat + SQLite + FastAPI` 的英语学习 QQ 机器人项目。

## 当前实现范围

- `@机器人` 自动中英识别、翻译、纠错
- 错误点沉淀与复习项生成
- 报名学习、每日任务、复习、周测、周报的应用层骨架
- 管理后台、动态配置、定时任务与部署脚手架

## 快速开始

1. 复制 [deploy/.env.example](/Users/roll/Documents/Playground/englishBot-staging/deploy/.env.example) 为 `.env`
2. 复制 [deploy/config.example.yaml](/Users/roll/Documents/Playground/englishBot-staging/deploy/config.example.yaml) 为 `config.yaml`
3. 安装依赖并启动：

```bash
uv sync
uv run python -m src.main
```

4. 如果使用 Docker Compose：

```bash
cd deploy
docker compose up -d --build
```

## 目录结构

- [src/main.py](/Users/roll/Documents/Playground/englishBot-staging/src/main.py)：应用入口
- [src/plugins](/Users/roll/Documents/Playground/englishBot-staging/src/plugins)：NoneBot 消息与任务入口
- [src/application](/Users/roll/Documents/Playground/englishBot-staging/src/application)：应用服务
- [src/domain](/Users/roll/Documents/Playground/englishBot-staging/src/domain)：领域对象与规则
- [src/infrastructure](/Users/roll/Documents/Playground/englishBot-staging/src/infrastructure)：数据库、Provider、配置与鉴权
- [src/admin](/Users/roll/Documents/Playground/englishBot-staging/src/admin)：管理后台
- [deploy](/Users/roll/Documents/Playground/englishBot-staging/deploy)：部署文件

