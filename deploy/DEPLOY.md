# Deployment Guide (Cockpit + systemd + Atomic Release)

本文档是当前推荐的线上部署方案，目标是：

1. 服务稳定运行（systemd 托管，自动拉起）
2. 可视化运维（Cockpit 控制台）
3. 可回滚发布（原子切换 `current` 软链）

## 1. 目录模型

远程服务器统一使用这套目录：

```text
/home/ubuntu/apps/englishbot/
  releases/<release_id>/
  shared/.env
  shared/config.yaml
  shared/data/
  current -> releases/<release_id>
  .previous_release
```

- `releases/`：每次发布一个独立版本目录
- `shared/`：持久化配置和数据，不随版本覆盖
- `current`：线上运行版本软链，切换时原子替换

## 2. 服务器一次性初始化

### 2.1 安装 Cockpit

```bash
sudo apt update
sudo apt install -y cockpit
sudo systemctl enable --now cockpit.socket
```

控制台地址：

- `https://<服务器IP>:9090`

### 2.2 安装 uv（若未安装）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env || true
```

### 2.3 初始化目录

```bash
mkdir -p /home/ubuntu/apps/englishbot/releases
mkdir -p /home/ubuntu/apps/englishbot/shared/data
```

### 2.4 准备共享配置

如果你已有旧目录 `~/englishBot`，可直接迁移：

```bash
cp ~/englishBot/.env /home/ubuntu/apps/englishbot/shared/.env
cp ~/englishBot/config.yaml /home/ubuntu/apps/englishbot/shared/config.yaml
```

## 3. 安装 systemd 服务

使用仓库中的服务文件：

- `deploy/systemd/englishbot.service`

部署到服务器：

```bash
sudo cp /home/ubuntu/englishBot/deploy/systemd/englishbot.service /etc/systemd/system/englishbot.service
sudo systemctl daemon-reload
sudo systemctl enable englishbot
```

> 默认服务用户是 `ubuntu`，路径是 `/home/ubuntu/apps/englishbot/current`。如果你的服务器用户或路径不同，请先修改 service 文件再复制。

## 4. 首次发布（Bootstrap）

先把代码放入一个首发 release，再启动服务：

```bash
RELEASE_ID=bootstrap-$(date +%Y%m%d%H%M%S)
mkdir -p /home/ubuntu/apps/englishbot/releases/$RELEASE_ID
rsync -az --delete --exclude='.git' --exclude='.venv' --exclude='data' ~/englishBot/ /home/ubuntu/apps/englishbot/releases/$RELEASE_ID/

ln -sfn /home/ubuntu/apps/englishbot/shared/.env /home/ubuntu/apps/englishbot/releases/$RELEASE_ID/.env
ln -sfn /home/ubuntu/apps/englishbot/shared/config.yaml /home/ubuntu/apps/englishbot/releases/$RELEASE_ID/config.yaml
ln -sfn /home/ubuntu/apps/englishbot/shared/data /home/ubuntu/apps/englishbot/releases/$RELEASE_ID/data

cd /home/ubuntu/apps/englishbot/releases/$RELEASE_ID
uv sync --python 3.12

ln -sfn /home/ubuntu/apps/englishbot/releases/$RELEASE_ID /home/ubuntu/apps/englishbot/current
sudo systemctl restart englishbot
curl -fsS http://127.0.0.1:8003/healthz
```

## 5. 日常发布（推荐命令）

本仓库已提供原子发布脚本：

- `deploy/scripts/deploy_remote.sh`

本地执行：

```bash
DEPLOY_HOST=110.40.137.26 \
DEPLOY_USER=ubuntu \
DEPLOY_BASE_DIR=/home/ubuntu/apps/englishbot \
./deploy/scripts/deploy_remote.sh
```

可选参数：

- `DEPLOY_RELEASE_ID=custom-id`
- `KEEP_RELEASES=10`
- `REMOTE_HEALTH_URL=http://127.0.0.1:8003/healthz`
- `SERVICE_NAME=englishbot`
- `DEPLOY_PORT=22`

脚本行为：

1. 上传代码到新 release 目录
2. 链接 `shared/.env`、`shared/config.yaml`、`shared/data`
3. 安装依赖（`uv sync --python 3.12`）
4. 原子切换 `current`
5. 重启服务 + 健康检查
6. 失败自动回滚

## 6. 回滚

使用回滚脚本：

- `deploy/scripts/rollback_remote.sh`

### 6.1 回滚到上一版本

```bash
DEPLOY_HOST=110.40.137.26 \
DEPLOY_USER=ubuntu \
DEPLOY_BASE_DIR=/home/ubuntu/apps/englishbot \
./deploy/scripts/rollback_remote.sh
```

### 6.2 指定 release 回滚

```bash
DEPLOY_HOST=110.40.137.26 \
DEPLOY_USER=ubuntu \
DEPLOY_BASE_DIR=/home/ubuntu/apps/englishbot \
ROLLBACK_RELEASE=20260414093000-abc123 \
./deploy/scripts/rollback_remote.sh
```

## 7. GitHub Actions 自动发布

新增 workflow：

- `.github/workflows/deploy-production.yml`

触发：

- `push main`
- 手动 `workflow_dispatch`

旧 workflow：

- `.github/workflows/deploy.yml` 已改为仅手动触发（Legacy）
- `.github/workflows/rollback-production.yml` 用于手动回滚生产

### 7.1 必要 Secrets

- `SERVER_HOST`
- `SERVER_USER`
- `SERVER_SSH_KEY`
- `DEPLOY_BASE_DIR`（可选，不填则走脚本默认）

### 7.2 生产门禁建议

在 GitHub 仓库设置 `Environment: production`，启用 Required reviewers，再执行正式自动发布。

### 7.3 GitHub 一键回滚

在 Actions 里运行 `Rollback Production`：

1. `rollback_release` 留空：回滚到上一版本
2. `rollback_release` 填值：回滚到指定 release id

## 8. 运维常用命令

```bash
# 服务状态
sudo systemctl status englishbot --no-pager

# 实时日志
sudo journalctl -u englishbot -f

# 重启
sudo systemctl restart englishbot

# 健康检查
curl -fsS http://127.0.0.1:8003/healthz
```

## 9. Cockpit 常用入口

登录 `https://<服务器IP>:9090` 后：

1. `Services`：启动/停止/重启 `englishbot`
2. `Logs`：查看 `englishbot` 实时日志
3. `Storage`：检查磁盘，避免 release 累积占满空间

## 10. 故障排查

### 10.1 健康检查失败

先看日志：

```bash
sudo journalctl -u englishbot -n 200 --no-pager
```

然后检查：

1. `shared/.env` 是否存在且配置正确
2. `shared/config.yaml` 是否存在
3. `uv sync` 是否成功
4. 端口 `8003` 是否被其他进程占用

### 10.2 启动成功但飞书无响应

检查：

1. `FEISHU_APP_ID / FEISHU_APP_SECRET`
2. `feishu.enabled_group_ids`
3. 飞书应用事件订阅（长连接模式）
