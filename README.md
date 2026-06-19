<div align="center">

# <img src="frontend/public/app-logo.svg" width="40" height="40" alt="Fleetge" style="vertical-align: middle; margin-right: 4px;" /> Fleetge - Docker Fleet Console

**A lightweight, real-time multi-host Docker fleet and Compose Stack management console.**

**轻量级、实时的多主机 Docker 容器集群与 Compose Stack 统一运维大盘控制台。**

[简体中文](#-简体中文) | [English](#-english)

</div>

---

## 🇨🇳 简体中文

Fleetge 是一个专为多主机环境设计的轻量级 Docker 集群与 Compose 容器编排控制台。

它通过在被控节点部署极简的 `fleetge-agent`，将多个独立主机的容器运行状态、主机硬件指标（CPU、内存、磁盘、网络）及 Compose 编排生命周期整合在单一的现代化 Web 界面中。支持秒级实时性能曲线、日志流式输出，并且支持对所有敏感凭证进行高级加密，提供详细的操作审计日志。

### ✨ 核心特性

- **🔍 统一主机大盘监控**：实时在线探测与资源监控，展示 CPU、内存、磁盘 IO、网络流速及容器运行数等关键指标，支持秒级实时历史曲线。
- **📦 Compose Stack 生命周期管理**：统一节点环境 Stack 列表，支持一键启动、停止、重启、更新与删除。提供容器的 SSE 实时终端输出，操作无缝流转。
- **➕ 可视化 Compose 编排编辑器**：提供直观易用的全新 Compose Stack 编写界面，支持语法高亮，轻松在线编排和部署容器。
- **🛡️ 凭证加固与操作审计**：所有连接凭证均采用 Fernet 高强度加密落库；管理员采用 Argon2 密码散列验证；所有关键写操作（清理、Stack 变更、系统配置）均记录在审计日志中，确保轨迹可追溯。
- **💡 极简接入**：在被控节点部署极简的 `fleetge-agent`，即可同时获得监控与 Compose 编排能力。

---

### 🖼️ UI 细节展示

#### 1. 全局主机监控大盘 (Overview Dashboard)
全局大盘提供了所有受管主机的实时在线状态与基础资源负载概览。可以一目了然地监控各主机的 CPU 使用率、内存占用、磁盘空间以及正在运行和已停止的容器数量，并支持一键检测所有主机的系统升级。

<div align="center">
  <img src="assets/dashboard.png" width="90%" alt="Fleetge Dashboard Overview" style="border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15);"/>
</div>

#### 2. 主机控制台与实时监控 (Host Details & Live Monitor)
进入单台主机详情页后，系统将通过 Server-Sent Events (SSE) 协议为您推送**秒级更新**的 CPU 负载、内存占用、网络带宽流速以及磁盘 I/O 吞吐曲线。同时，您可以在此管理所有的 Docker Compose Stacks、查看实时容器终端日志、以及编辑 Compose 编排文件。

<div align="center">
  <img src="assets/host_detail.png" width="90%" alt="Host Detail & Metrics" style="border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15);"/>
</div>

#### 3. 操作审计流水 (Audit Logs)
为了保障生产环境的操作安全性，Fleetge 内置了完善的审计机制。系统会自动记录用户登录、凭证修改、容器 Stack 的启动/停止/更新等关键指令的执行时间、操作用户和详细日志，随时应对安全回溯要求。

<div align="center">
  <img src="assets/audit.png" width="90%" alt="Fleetge Audit Logs" style="border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15);"/>
</div>

#### 4. 安全与参数配置 (System Settings)
在系统设置页，您可以灵活调整应用的主机连接参数。所有输入的主机登录凭证（如 Token 或密码）均在后端数据库中经过强对称加密，页面上仅以脱敏形式展示。支持配置第三方自定义快速导航链接。

<div align="center">
  <img src="assets/settings.png" width="90%" alt="Fleetge Settings" style="border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15);"/>
</div>

---

### 🚀 快速开始与部署

#### 1. 密钥准备
为了保障控制台的数据安全，在部署前您需要生成三组必要的密钥/哈希：

```bash
# A. 生成 JWT 签名密钥 (用于前端会话凭证)
python -c "import secrets; print(secrets.token_hex(32))"

# B. 生成 Fernet 强加密密钥 (用于加密落库的主机密码/Token)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# C. 设置管理员登录密码 (明文)
# 直接将密码填入 docker-compose.yml 即可。
```

#### 2. 编写配置文件
在项目根目录下创建并编辑 `docker-compose.yml`。

将上一步生成的密钥填入对应的环境变量中：

```yaml
version: '3.8'

services:
  fleetge:
    image: ghcr.io/virgooooox/fleetge:latest
    container_name: fleetge
    restart: unless-stopped
    ports:
      - "80:8000"
    environment:
      # 填入生成的密钥与哈希
      JWT_SECRET: "替换为步骤A生成的32位十六进制字符串"
      CREDENTIALS_KEY: "替换为步骤B生成的Fernet密钥"
      ADMIN_PASSWORD: "替换为您的强密码"
      
      # 配置文件与数据库路径
      DATABASE_URL: sqlite:////app/data/dashboard-local.db
      HOST_CONFIG_PATH: /app/data/hosts.yaml
      
      # 轮询时间配置 (秒)
      METRICS_STREAM_INTERVAL: 1  # SSE 指标前端推送间隔
      DOCKER_POLL_INTERVAL: 10     # 容器与 Stack 列表刷新间隔
      BACKGROUND_STRUCTURE_REFRESH_INTERVAL: 3600  # 无连接时后台轮询刷新间隔
      UPDATE_CHECK_INTERVAL: 43200 # 主机系统升级检测缓存时间
      
      LOG_LEVEL: info
    volumes:
      - ./data:/app/data
```

#### 3. 配置管理主机列表
初始化数据目录并创建主机配置文件：

```bash
mkdir -p data
cp hosts.yaml.example data/hosts.yaml
```

编辑 `data/hosts.yaml`，填入您的主机连接信息：

```yaml
hosts:
  - host_id: my-node-1
    display_name: "生产节点-01 (Agent模式)"
    sort_order: 1
    enabled: true
    agent:
      url: http://<your-agent-ip>:8080
      token: "your_agent_secret_token"
```

#### 4. 启动控制台
```bash
docker compose up -d
```
启动后在浏览器中访问 `http://<your-server-ip>`，使用您在生成 Argon2 哈希时设定的密码即可登录。

---

### 🔌 受管主机部署 (Fleetge Agent)

对于希望一键接入并同时支持指标监控与 Compose Stack 编排的远程主机，推荐部署轻量级的 `fleetge-agent`：

在被控节点创建 `docker-compose.yml` 并启动：

```yaml
version: '3.8'

services:
  agent:
    image: ghcr.io/virgooooox/fleetge-agent:latest
    container_name: fleetge-agent
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - AGENT_TOKEN=your_agent_secret_token  # 对应主控端 hosts.yaml 中的 token
      - STACKS_BASE_DIR=/opt/stacks          # Docker Compose 文件在宿主机的存放目录
      - DISK_PATHS=/                         # 监控的宿主机挂载点，多个用逗号分隔
      - COLLECT_INTERVAL=5                   # 指标采集频率 (秒)
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/stacks:/opt/stacks
```
运行启动指令：
```bash
docker compose up -d
```

---
---

## 🇺🇸 English

Fleetge is a lightweight, real-time Docker fleet and Compose Stack management console designed for multi-host server environments.

By aggregating data from `fleetge-agent`, Fleetge provides a unified, production-ready interface to inspect container statuses, monitor hardware performance (CPU, Memory, Disk, Network) with 1-second interval charts, deploy Compose stacks, and review secure audit logs.

### ✨ Core Features

- **🔍 Unified Fleet Dashboard**: Multi-host status overview showing CPU, memory, disk, network throughput, and container count.
- **📦 Stack Lifecycle Control**: Start, stop, restart, update, and remove Compose Stacks remotely, complete with a live terminal output powered by Server-Sent Events (SSE).
- **➕ Built-in Compose Editor**: Write, edit, and orchestrate Compose files directly inside a syntax-highlighted editor.
- **🛡️ Secure Access & Auditing**: Enterprise-grade Fernet encryption for remote tokens and passwords; secure Argon2 hashing for administrator logins; comprehensive audit logging for all critical state actions.
- **💡 Flexible Agent Options**:
  - **Agent Mode**: Run a tiny helper agent (`fleetge-agent`) on remote hosts to fetch host-level metrics and execute Compose commands.

---

### 🖼️ UI Showcase

#### 1. Overview Dashboard
Get a high-level picture of your entire host fleet. Real-time metrics widgets display CPU, RAM, disk space, and total containers running/stopped across all connected servers. A central update utility checks if any remote host requires system package updates.

<div align="center">
  <img src="assets/dashboard.png" width="90%" alt="Fleetge Dashboard Overview" style="border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15);"/>
</div>

#### 2. Host Operations & Metrics Stream
Inside each host's workspace, view **1-second real-time charts** streaming CPU usage, memory foot-print, disk IO, and network speeds. Launch, restart, or update stacks on this host, edit compose configurations, or look at container terminals in real-time.

<div align="center">
  <img src="assets/host_detail.png" width="90%" alt="Host Detail & Metrics" style="border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15);"/>
</div>

#### 3. Audit Logs Trail
Track all administrative and cluster events. Whenever a user logs in, triggers a stack action, or alters credentials, it is permanently logged with the timestamp, target host, operator account, and log payload.

<div align="center">
  <img src="assets/audit.png" width="90%" alt="Fleetge Audit Logs" style="border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15);"/>
</div>

#### 4. Settings & Credentials Manager
Easily register new hosts, assign weights, sort order, and add customized shortcut links in the main navigation. Fleetge securely encrypts credentials in your local SQLite/PostgreSQL database, ensuring that raw passwords and tokens are never exposed.

<div align="center">
  <img src="assets/settings.png" width="90%" alt="Fleetge Settings" style="border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.15);"/>
</div>

---

### 🚀 Quick Start & Deployment

#### 1. Generate Security Credentials
To configure the environment securely, generate the required security keys:

```bash
# A. Generate a JWT Secret (for web session verification)
python -c "import secrets; print(secrets.token_hex(32))"

# B. Generate a Fernet Key (for database credentials encryption)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# C. Set the plain-text administrator login password.
# Simply fill the password in docker-compose.yml.
```

#### 2. Create the Compose Config
Create a `docker-compose.yml` file in your project directory:

```yaml
version: '3.8'

services:
  fleetge:
    image: ghcr.io/virgooooox/fleetge:latest
    container_name: fleetge
    restart: unless-stopped
    ports:
      - "80:8000"
    environment:
      # Inject your generated secrets
      JWT_SECRET: "replace_with_jwt_secret_from_step_A"
      CREDENTIALS_KEY: "replace_with_fernet_key_from_step_B"
      ADMIN_PASSWORD: "replace_with_your_strong_password"
      
      # Database and configurations
      DATABASE_URL: sqlite:////app/data/dashboard-local.db
      HOST_CONFIG_PATH: /app/data/hosts.yaml
      
      # Metrics and structure polling intervals (in seconds)
      METRICS_STREAM_INTERVAL: 1  # Frequency of SSE metrics pushes to clients
      DOCKER_POLL_INTERVAL: 10     # Refresh interval for containers/stacks with active web UI
      BACKGROUND_STRUCTURE_REFRESH_INTERVAL: 3600  # Offline refresh interval
      UPDATE_CHECK_INTERVAL: 43200 # System update check cache TTL
      
      LOG_LEVEL: info
    volumes:
      - ./data:/app/data
```

#### 3. Configure Hosts List
Initialize the configuration volume:

```bash
mkdir data
cp hosts.yaml.example data/hosts.yaml
```

Edit `data/hosts.yaml` to specify the managed nodes:

```yaml
hosts:
  - host_id: my-node-1
    display_name: "Production Node 01 (Agent)"
    sort_order: 1
    enabled: true
    agent:
      url: http://<your-agent-ip>:8080
      token: "your_agent_secret_token"
```

#### 4. Run the Console
Start the service:
```bash
docker compose up -d
```
Access the console at `http://localhost:80` (or your server's IP address) and log in using the password chosen during the Argon2 generation step.

---

### 🔌 Agent Setup (Fleetge Agent)

To connect remote hosts securely and monitor system metrics along with Docker Compose stacks, deploy the lightweight agent on each target node:

```yaml
version: '3.8'

services:
  agent:
    image: ghcr.io/virgooooox/fleetge-agent:latest
    container_name: fleetge-agent
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - AGENT_TOKEN=your_agent_secret_token  # Must match the token configured in hosts.yaml
      - STACKS_BASE_DIR=/opt/stacks          # The host path where Compose stacks are located
      - DISK_PATHS=/                         # Mount points to monitor (comma separated)
      - COLLECT_INTERVAL=5                   # Metric polling interval in seconds
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /opt/stacks:/opt/stacks
```
Start the agent:
```bash
docker compose up -d
```

---

## 🛠️ Environment Configuration Reference / 环境变量参考

The dashboard console supports the following environment variables:

| Variable / 环境变量 | Type / 类型 | Default / 默认值 | Description / 描述 |
| :--- | :--- | :--- | :--- |
| `JWT_SECRET` | String | *Required / 必填* | Hex signature key for JSON Web Tokens. / 用于 JWT 鉴权的 64 位十六进制签名密钥。 |
| `CREDENTIALS_KEY` | String | *Required / 必填* | Fernet symmetric key to encrypt remote passwords/tokens in the DB. / 数据库敏感凭证的 Fernet 对称加密密钥。 |
| `ADMIN_PASSWORD`      | String | *Required / 必填* | Plain-text administrator login password. / 管理员登录密码的明文。 |
| `DATABASE_URL` | String | `sqlite:////app/data/dashboard-local.db` | Connection URI for SQLAlchemy. / 数据库连接 URI，支持 SQLite/PostgreSQL 等。 |
| `HOST_CONFIG_PATH` | String | `/app/data/hosts.yaml` | Host YAML file path. / 主机静态配置文件路径。 |
| `METRICS_STREAM_INTERVAL` | Integer | `1` | Stream update interval for metrics in seconds. / SSE 实时性能指标推送间隔（秒）。 |
| `DOCKER_POLL_INTERVAL`| Integer | `10` | Poll interval for Docker containers/stacks. / 前端在线时，Docker 容器结构轮询刷新间隔（秒）。 |
| `BACKGROUND_STRUCTURE_REFRESH_INTERVAL`| Integer | `3600` | Offline background poll interval. / 前端离线时，后台轮询刷新数据结构间隔（秒）。 |
| `UPDATE_CHECK_INTERVAL`| Integer | `43200` | Host update check cache time. / 主机系统升级包缓存时长（秒，默认12小时）。 |
| `CORS_ORIGINS` | String | *Empty / 留空* | Allowed CORS origins, comma separated. / 跨域允许来源列表，逗号分隔，留空为同源。 |
| `LOG_LEVEL` | String | `info` | Logging level (`debug`, `info`, `warning`, `error`). / 控制台日志级别。 |

---
Released under the [MIT License](LICENSE).
