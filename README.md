<div align="center">

<img src="frontend/public/app-logo.svg" width="96" height="96" alt="Fleetge" />

# Fleetge Docker Fleet 运维控制台

<a href="README.en.md"><img src="https://img.shields.io/badge/LANGUAGE-ENGLISH-2f3b4a?style=for-the-badge" alt="English" /></a>
<img src="https://img.shields.io/badge/PLATFORM-DOCKER%20%7C%20LINUX-0f766e?style=for-the-badge" alt="Platform" />
<img src="https://img.shields.io/badge/ARCHITECTURE-DASHBOARD%20%7C%20AGENT-0284c7?style=for-the-badge" alt="Architecture" />
<img src="https://img.shields.io/badge/STACK-COMPOSE-475569?style=for-the-badge" alt="Docker Compose" />
<img src="https://img.shields.io/badge/LICENSE-MIT-65a30d?style=for-the-badge" alt="MIT License" />

</div>


> [!IMPORTANT]
> **Vibe Coding 说明 / Disclaimer**
>
> 本仓库是作者在 AI 辅助下以 **vibe coding** 方式完成的个人作品：主要通过自然语言描述需求、由 AI 生成和修改代码，作者负责产品想法、体验验证和方向取舍。作者不是专业开发者，也不具备系统的代码审计能力；代码按现状提供，请在使用、部署或二次开发前自行审查、测试并承担相应风险。
---
> **Fleetge** 是一款面向多主机 Docker 环境的轻量级、实时化、可自托管运维控制台。
>
> 它通过在受管节点部署 `fleetge-agent`，把分散在不同服务器上的主机指标、容器状态、Compose Stack 生命周期、镜像更新检测和操作审计集中到一个现代化 Web 界面中。

Fleetge 的产品形态与部分交互体验参考并致谢 [Dockge](https://github.com/louislam/dockge)。本项目不是 Dockge 的 fork，而是面向多主机 Docker 运维场景的独立实现。

## 预览

<div align="center">
  <img src="assets/dashboard.png" width="92%" alt="Fleetge Dashboard" />
</div>

| 应用启动台 | 主机控制台 |
| :---: | :---: |
| <img src="assets/apps.png" alt="App Launchpad" /> | <img src="assets/host_detail.png" alt="Host Detail" /> |

| 镜像更新 | 系统设置 |
| :---: | :---: |
| <img src="assets/updates.png" alt="Image Updates" /> | <img src="assets/settings.png" alt="Settings" /> |

## 核心能力

| 能力 | 说明 |
| :--- | :--- |
| 多主机总览 | 集中查看所有受管节点的在线状态、CPU、内存、磁盘、网络吞吐与容器数量。 |
| 实时指标曲线 | 通过 SSE 推送秒级性能数据，适合轻量运维看板和日常巡检。 |
| 应用启动台 | 按主机或自定义分组聚合服务入口，支持运行状态、更新状态筛选和快速跳转。 |
| Compose Stack 管理 | 远程启动、停止、重启、更新、删除 Stack，并查看实时终端输出。 |
| 在线 Compose 编辑器 | 直接在 Web 界面中创建、编辑和部署 Compose 文件。 |
| 镜像更新检测 | 对比本地镜像与远端 Registry digest，区分最新、可更新、需认证、被限流和检查失败等状态。 |
| 主机系统更新检测 | 通过 Agent 检测 apt/yum 等系统包更新，并在主机卡片和总览中展示。 |
| 节点定制 | 支持 `global.env`、Stack 图标匹配规则、应用资料、自定义分组、本地图标上传和外部访问地址。 |
| 安全与审计 | Fernet 加密保存敏感凭证，Argon2 校验管理员密码，关键写操作写入审计日志。 |

## 架构

```text
Browser
  |
  v
Fleetge Dashboard
  |-- SQLite / PostgreSQL
  |-- hosts.yaml
  |
  +-- fleetge-agent on Host A -- Docker Engine / Compose stacks
  +-- fleetge-agent on Host B -- Docker Engine / Compose stacks
  +-- fleetge-agent on Host C -- Docker Engine / Compose stacks
```

## 快速开始

### 1. 准备数据目录

```bash
mkdir -p data
cp hosts.yaml.example data/hosts.yaml
```

编辑 `data/hosts.yaml`：

```yaml
hosts:
  - host_id: node-1
    display_name: Production Node 01
    sort_order: 1
    enabled: true
    agent:
      url: http://<agent-host>:8080/<optional-secret-path>
      token: "replace-with-a-long-random-token"
```

### 2. 生成密钥

```bash
# JWT 签名密钥
python -c "import secrets; print(secrets.token_hex(32))"

# Fernet 凭证加密密钥
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. 编写 `.env`

```env
JWT_SECRET=replace_with_jwt_secret
CREDENTIALS_KEY=replace_with_fernet_key
ADMIN_PASSWORD=replace_with_strong_admin_password

DATABASE_URL=sqlite:////app/data/dashboard-local.db
HOST_CONFIG_PATH=/app/data/hosts.yaml

METRICS_STREAM_INTERVAL=1
DOCKER_POLL_INTERVAL=10
BACKGROUND_STRUCTURE_REFRESH_INTERVAL=3600
UPDATE_CHECK_INTERVAL=43200
LOG_LEVEL=info
```

### 4. 启动 Dashboard

```yaml
services:
  fleetge:
    image: ghcr.io/virgooooox/fleetge:latest
    container_name: fleetge
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
    ports:
      - "80:8000"
```

```bash
docker compose up -d
```

访问 `http://<server-ip>`，默认管理员用户名为 `admin`，密码为 `.env` 中的 `ADMIN_PASSWORD`。

## 部署 Agent

在每台受管 Docker 主机上部署 `fleetge-agent`：

```yaml
services:
  agent:
    image: ghcr.io/virgooooox/fleetge-agent:latest
    container_name: fleetge-agent
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      AGENT_TOKEN: replace-with-a-long-random-token
      AGENT_SECRET_PATH: /replace-with-random-path
      AGENT_REQUIRE_TOKEN: "true"
      AGENT_PUBLIC_HEALTH: "false"
      AGENT_ENABLE_WRITE: "true"
      AGENT_ENABLE_DELETE: "true"
      AGENT_ENABLE_GLOBAL_ENV: "true"
      AGENT_ENABLE_PRUNE: "false"
      AGENT_ENABLE_SELF_UPDATE: "true"
      STACKS_BASE_DIR: /opt/stacks
      DISK_PATHS: /
      COLLECT_INTERVAL: "5"
      AGENT_LOG_LEVEL: INFO
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/stacks:/opt/stacks
```

```bash
docker compose up -d
```

如果设置了 `AGENT_SECRET_PATH`，主控端 `hosts.yaml` 中的 `agent.url` 需要包含该路径，例如 `http://192.168.1.10:8080/replace-with-random-path`。

## 配置参考

### Dashboard

| 变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `JWT_SECRET` | 必填 | JWT 会话签名密钥，建议使用 64 位十六进制随机字符串。 |
| `CREDENTIALS_KEY` | 必填 | Fernet 对称加密密钥，用于加密数据库中的远程凭证。 |
| `ADMIN_USERNAME` | `admin` | 管理员用户名。 |
| `ADMIN_PASSWORD` | 必填 | 管理员登录密码。 |
| `DATABASE_URL` | `sqlite:////app/data/dashboard-local.db` | SQLAlchemy 数据库连接 URI，支持 SQLite/PostgreSQL 等。 |
| `HOST_CONFIG_PATH` | `/app/data/hosts.yaml` | 主机配置文件路径。 |
| `METRICS_STREAM_INTERVAL` | `1` | SSE 指标推送间隔，单位秒，范围 `0.5` 到 `10.0`。 |
| `DOCKER_POLL_INTERVAL` | `10` | 前端在线时 Docker 容器与 Stack 结构刷新间隔，单位秒。 |
| `BACKGROUND_STRUCTURE_REFRESH_INTERVAL` | `3600` | 前端离线时后台结构刷新间隔，单位秒，范围 `60` 到 `86400`。 |
| `UPDATE_CHECK_INTERVAL` | `43200` | 系统和镜像更新检测缓存时间，单位秒，范围 `3600` 到 `172800`。 |
| `JWT_EXPIRE_HOURS` | `24` | 登录会话有效期，单位小时，范围 `1` 到 `720`。 |
| `CORS_ORIGINS` | 空 | 允许的跨域来源，多个值用逗号分隔，留空表示同源。 |
| `LOG_LEVEL` | `info` | 日志级别：`debug`、`info`、`warning`、`error`。 |

### Agent

| 变量 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `AGENT_TOKEN` | 必填 | Agent 访问 Token，默认要求至少 32 个字符。 |
| `AGENT_SECRET_PATH` | 空 | 可选 URL 前缀，设置后所有 Agent 路由都需要带该路径。 |
| `AGENT_TOKEN_MIN_LENGTH` | `32` | Token 最小长度。 |
| `AGENT_REQUIRE_TOKEN` | `true` | 是否强制要求 Token。 |
| `AGENT_PUBLIC_HEALTH` | `false` | 是否允许公开访问健康检查。 |
| `AGENT_ENABLE_WRITE` | `true` | 是否允许 Stack 写操作。 |
| `AGENT_ENABLE_DELETE` | `true` | 是否允许删除 Stack。 |
| `AGENT_ENABLE_GLOBAL_ENV` | `true` | 是否允许写入 `global.env`。 |
| `AGENT_ENABLE_PRUNE` | `false` | 是否允许执行 Docker prune。 |
| `AGENT_ENABLE_SELF_UPDATE` | `true` | 是否允许 Agent 自更新相关操作。 |
| `STACKS_BASE_DIR` | `/opt/stacks` | Compose Stack 在受管主机上的目录。 |
| `DISK_PATHS` | `/` | 需要监控的磁盘挂载点，多个值用逗号分隔。 |
| `COLLECT_INTERVAL` | `5` | Agent 指标采集间隔，单位秒。 |
| `AGENT_LOG_LEVEL` | `INFO` | Agent 日志级别。 |

## 从源码构建

```bash
mkdir -p data
cp hosts.yaml.example data/hosts.yaml
docker compose up -d --build
```

## 安全建议

- 使用足够长的 `ADMIN_PASSWORD` 和 `AGENT_TOKEN`。
- 不要把生产环境 `.env`、`data/hosts.yaml`、数据库文件提交到版本控制。
- 只把 Agent 暴露给可信网络，或在反向代理/防火墙后使用。
- 谨慎开启 `AGENT_ENABLE_PRUNE`、`AGENT_ENABLE_DELETE` 等高风险能力。
- 定期备份 `data` 目录，它包含主机配置、数据库和运行状态。

## 致谢

- [Dockge](https://github.com/louislam/dockge)：Fleetge 的产品形态与部分交互体验受到 Dockge 启发。
- Docker、Compose、FastAPI、Vue 以及相关开源生态。

## 许可证

[MIT License](LICENSE)
