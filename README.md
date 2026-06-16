# Fleetge

多主机 Docker fleet 管理控制台。聚合 Dockge、docker-socket-proxy、host-metrics exporter 三路数据源，提供统一只读监控 + Stack 基础操作。

## 架构

```
用户浏览器 ─HTTPS→ Fleetge Frontend (Vue 3)
                    ─REST→ Fleetge Backend (FastAPI)
                              ├─→ Dockge Socket.IO ─ stack 管理
                              ├─→ docker-socket-proxy ─ Docker 只读状态
                              └─→ host-metrics exporter ─ 主机指标
```

## 部署

### 1. 准备

```bash
# 生成必要密钥
python -c "import secrets; print(secrets.token_hex(32))"          # JWT_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # CREDENTIALS_KEY

# 生成管理员密码 hash
pip install pwdlib[argon2]
python -c "from pwdlib import PasswordHash; print(PasswordHash.recommended().hash('your-admin-password'))"
```

### 2. 配置

```bash
cp .env.example .env           # 编辑 JWT_SECRET, CREDENTIALS_KEY, ADMIN_PASSWORD_HASH
cp hosts.yaml.example data/hosts.yaml   # 编辑各主机连接信息
```

如果是从现有本地数据切换到 Docker 部署，直接保留并挂载当前 `data/` 目录即可：

```text
data/
  hosts.yaml
  dashboard-local.db
  dashboard-local.db-wal
  dashboard-local.db-shm
  stack_icons/
```

镜像内不包含这些数据。`docker-compose.yml` 会把宿主机 `./data` 挂载到容器的 `/app/data`，后端默认读取：

```env
DATABASE_URL=sqlite:////app/data/dashboard-local.db
HOST_CONFIG_PATH=/app/data/hosts.yaml
```

注意：`ADMIN_PASSWORD_HASH` 是 Argon2 字符串，里面包含 `$`。在 `.env` 里请保留单引号，否则 Docker Compose 会把 `$argon2id`、`$v`、`$m` 等当成环境变量插值：

```env
ADMIN_PASSWORD_HASH='$argon2id$v=19$m=65536,t=3,p=4$...'
```

`CREDENTIALS_KEY` 用于解密数据库里已保存的远端凭据。复用旧数据库时，优先沿用原来的 `CREDENTIALS_KEY`。

**hosts.yaml** 结构：

```yaml
hosts:
  - host_id: oc-chicago
    display_name: OC Chicago
    dockge:
      url: https://dockge.1989009.xyz
      username: admin
      password: "dockge_password"
    docker_proxy:
      url: https://docker.1989009.xyz
      username: "monitor"
      password: "proxy_password"
    metrics:
      url: https://metrics.1989009.xyz
      username: "monitor"
      password: "metrics_password"
    sort_order: 1
    enabled: true
```

### 3. 部署

```bash
docker compose up -d
```

Fleetge 将在 `http://<host>:80` 可用。

### 4. 前置依赖

每台受管主机需要：

| 组件 | 说明 | 部署位置 |
|---|---|---|
| **Dockge** | Compose stack 管理 | 每台主机一个 |
| **docker-socket-proxy** | Docker 只读 HTTP API | 需增加 `INFO=1 VERSION=1 SYSTEM=1 IMAGES=1 EVENTS=0` |
| **host-metrics exporter** | 主机实时指标 (CPU/内存/磁盘) | 每台主机一个 |

Exporter 部署示例：

```bash
cd host-metrics-exporter
docker compose -f compose.example.yaml up -d
```

## 功能

- **主机总览**：在线状态、CPU/内存/磁盘利用率、Docker 版本
- **Stack 管理**：列表查看、启动/停止/重启/更新
- **容器状态**：列表、资源占用 (CPU/内存/网络/IO)
- **镜像更新检测**：自动对比 registry digest 判断可更新镜像
- **操作审计**：所有写操作记录时间戳和操作人
- **日志查看**：Stack 日志尾部查看（200–5000 行）

## 安全说明

- 后端凭据使用独立 `CREDENTIALS_KEY` (Fernet) 加密存储，不与 JWT 密钥共用
- 前端不保存任何远端凭据，仅持有 JWT token
- docker-socket-proxy 保持 `POST=0`，拒绝写入
- 登录 5 次失败后 IP 限速 15 分钟
- 写操作需前端二次确认 + 后端动作名白名单

## 路由

| 路径 | 说明 |
|---|---|
| `/login` | 登录 |
| `/` | 主机总览 |
| `/hosts/:hostId` | 主机详情 |
| `/updates` | 镜像更新 |
| `/audit` | 审计日志 |
| `/api/docs` | API 文档 (Swagger) |

## 开发

```bash
# 后端
cd backend
pip install -r requirements.txt
JWT_SECRET=dev CREDENTIALS_KEY=... ADMIN_PASSWORD_HASH=... uvicorn app.main:app --reload

# 前端
cd frontend
npm install
npm run dev
```

前端开发服务器自动代理 `/api` 到 `127.0.0.1:8000`。

## GitHub Actions 镜像构建

推送到 `main` 后，GitHub Actions 会构建并推送多架构镜像到 GHCR：

```text
ghcr.io/<owner>/host-dashboard-backend-public:latest
ghcr.io/<owner>/host-dashboard-frontend-public:latest
ghcr.io/<owner>/host-dashboard-metrics-public:latest
```

每次构建还会额外推送以 commit SHA 命名的标签，方便固定版本部署。

### 正式发布流程

本地执行一条命令完成版本 bump、前端构建、后端测试、commit、tag、push：

```powershell
.\scripts\release.ps1 -Version 0.1.1
```

脚本会更新：

```text
VERSION
backend/app/version.py
frontend/package.json
frontend/package-lock.json
```

然后提交：

```text
chore: release v0.1.1
```

并推送 `v0.1.1` tag。GitHub 收到 tag 后会运行 Release workflow：

1. 构建并推送 backend/frontend/metrics 三个多架构镜像。
2. 给镜像打 `latest`、`0.1.1`、`v0.1.1`、`<commit-sha>` 标签。
3. 自动创建 GitHub Release，并生成 release notes。

如果只想本地 bump 和打 tag，不推送：

```powershell
.\scripts\release.ps1 -Version 0.1.1 -NoPush
```

### 使用 GHCR 镜像部署

正式发布后可以用预构建镜像部署：

```bash
cp compose.ghcr.example.yml docker-compose.yml
```

在 `.env` 里增加：

```env
GHCR_OWNER=your-github-owner
FLEETGE_VERSION=0.1.1
```

然后启动：

```bash
docker compose pull
docker compose up -d
```
