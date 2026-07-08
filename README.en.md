<div align="center">

<img src="frontend/public/app-logo.svg" width="96" height="96" alt="Fleetge" />

# Fleetge Docker Fleet Console

<a href="README.md"><img src="https://img.shields.io/badge/LANGUAGE-%E7%AE%80%E4%BD%93%E4%B8%AD%E6%96%87-2f3b4a?style=for-the-badge" alt="Simplified Chinese" /></a>
<img src="https://img.shields.io/badge/PLATFORM-DOCKER%20%7C%20LINUX-0f766e?style=for-the-badge" alt="Platform" />
<img src="https://img.shields.io/badge/ARCHITECTURE-DASHBOARD%20%7C%20AGENT-0284c7?style=for-the-badge" alt="Architecture" />
<img src="https://img.shields.io/badge/STACK-COMPOSE-475569?style=for-the-badge" alt="Docker Compose" />
<img src="https://img.shields.io/badge/LICENSE-MIT-65a30d?style=for-the-badge" alt="MIT License" />

</div>

---

> **Fleetge** is a lightweight, real-time, self-hosted operations console for multi-host Docker environments.
>
> By deploying `fleetge-agent` on managed nodes, it brings host metrics, container status, Compose Stack lifecycle actions, image update checks, and audit logs from different servers into one modern web interface.

Fleetge's product shape and parts of its interaction model are inspired by and acknowledge [Dockge](https://github.com/louislam/dockge). This project is not a Dockge fork; it is an independent implementation for multi-host Docker operations.

## Preview

<div align="center">
  <img src="assets/dashboard.png" width="92%" alt="Fleetge Dashboard" />
</div>

| App Launchpad | Host Console |
| :---: | :---: |
| <img src="assets/apps.png" alt="App Launchpad" /> | <img src="assets/host_detail.png" alt="Host Detail" /> |

| Image Updates | Settings |
| :---: | :---: |
| <img src="assets/updates.png" alt="Image Updates" /> | <img src="assets/settings.png" alt="Settings" /> |

## Capabilities

| Capability | Description |
| :--- | :--- |
| Multi-host dashboard | View online status, CPU, memory, disk, network throughput, and container counts across all managed hosts. |
| Real-time metrics | Stream host metrics over SSE with second-level refresh intervals. |
| App Launchpad | Aggregate service entry points by host or custom group, filter by runtime/update status, and open external app URLs quickly. |
| Compose Stack management | Start, stop, restart, update, and delete stacks remotely with live terminal output. |
| Built-in Compose editor | Create, edit, and deploy Compose files directly from the web UI. |
| Image update detection | Compare local images with remote registry digests and classify up-to-date, updatable, needs-auth, rate-limited, and failed checks. |
| Host OS update checks | Detect package updates from agent hosts, including apt/yum-based systems. |
| Host customization | Manage `global.env`, stack icon matching rules, app profiles, custom groups, uploaded icons, and external URLs. |
| Security and auditing | Encrypt sensitive credentials with Fernet, verify admin passwords with Argon2, and record critical write actions in audit logs. |

## Architecture

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

## Quick Start

### 1. Prepare the data directory

```bash
mkdir -p data
cp hosts.yaml.example data/hosts.yaml
```

Edit `data/hosts.yaml`:

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

### 2. Generate secrets

```bash
# JWT signing secret
python -c "import secrets; print(secrets.token_hex(32))"

# Fernet key for credential encryption
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Create `.env`

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

### 4. Start the dashboard

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

Open `http://<server-ip>` in your browser. The default admin username is `admin`, and the password is the `ADMIN_PASSWORD` value from `.env`.

## Agent Deployment

Deploy `fleetge-agent` on each managed Docker host:

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

If `AGENT_SECRET_PATH` is set, include it in the dashboard-side `agent.url`, for example `http://192.168.1.10:8080/replace-with-random-path`.

## Configuration

### Dashboard

| Variable | Default | Description |
| :--- | :--- | :--- |
| `JWT_SECRET` | Required | JWT signing secret. A 64-character hex random string is recommended. |
| `CREDENTIALS_KEY` | Required | Fernet symmetric key for encrypting remote credentials in the database. |
| `ADMIN_USERNAME` | `admin` | Administrator username. |
| `ADMIN_PASSWORD` | Required | Administrator login password. |
| `DATABASE_URL` | `sqlite:////app/data/dashboard-local.db` | SQLAlchemy database URI. SQLite and PostgreSQL are supported. |
| `HOST_CONFIG_PATH` | `/app/data/hosts.yaml` | Path to the host configuration file. |
| `METRICS_STREAM_INTERVAL` | `1` | SSE metrics stream interval in seconds. Valid range: `0.5` to `10.0`. |
| `DOCKER_POLL_INTERVAL` | `10` | Docker container and stack structure refresh interval while clients are connected, in seconds. |
| `BACKGROUND_STRUCTURE_REFRESH_INTERVAL` | `3600` | Background structure refresh interval while no clients are connected, in seconds. Valid range: `60` to `86400`. |
| `UPDATE_CHECK_INTERVAL` | `43200` | System and image update check cache interval in seconds. Valid range: `3600` to `172800`. |
| `JWT_EXPIRE_HOURS` | `24` | Login session lifetime in hours. Valid range: `1` to `720`. |
| `CORS_ORIGINS` | Empty | Allowed CORS origins, comma separated. Empty means same-origin only. |
| `LOG_LEVEL` | `info` | Log level: `debug`, `info`, `warning`, or `error`. |

### Agent

| Variable | Default | Description |
| :--- | :--- | :--- |
| `AGENT_TOKEN` | Required | Agent access token. At least 32 characters are required by default. |
| `AGENT_SECRET_PATH` | Empty | Optional URL prefix. When set, all agent routes require this path. |
| `AGENT_TOKEN_MIN_LENGTH` | `32` | Minimum token length. |
| `AGENT_REQUIRE_TOKEN` | `true` | Whether the agent must require a token. |
| `AGENT_PUBLIC_HEALTH` | `false` | Whether health endpoints are publicly accessible. |
| `AGENT_ENABLE_WRITE` | `true` | Whether stack write operations are allowed. |
| `AGENT_ENABLE_DELETE` | `true` | Whether stack deletion is allowed. |
| `AGENT_ENABLE_GLOBAL_ENV` | `true` | Whether writing `global.env` is allowed. |
| `AGENT_ENABLE_PRUNE` | `false` | Whether Docker prune is allowed. |
| `AGENT_ENABLE_SELF_UPDATE` | `true` | Whether agent self-update related operations are allowed. |
| `STACKS_BASE_DIR` | `/opt/stacks` | Compose stack directory on the managed host. |
| `DISK_PATHS` | `/` | Disk mount points to monitor, comma separated. |
| `COLLECT_INTERVAL` | `5` | Agent metrics collection interval in seconds. |
| `AGENT_LOG_LEVEL` | `INFO` | Agent log level. |

## Build From Source

```bash
mkdir -p data
cp hosts.yaml.example data/hosts.yaml
docker compose up -d --build
```

## Security Notes

- Use strong values for `ADMIN_PASSWORD` and `AGENT_TOKEN`.
- Do not commit production `.env`, `data/hosts.yaml`, or database files.
- Expose agents only to trusted networks, or place them behind a reverse proxy/firewall.
- Be careful when enabling high-risk capabilities such as `AGENT_ENABLE_PRUNE` and `AGENT_ENABLE_DELETE`.
- Back up the `data` directory regularly. It contains host configuration, database state, and runtime data.

## Acknowledgements

- [Dockge](https://github.com/louislam/dockge): Fleetge's product shape and parts of its interaction model are inspired by Dockge.
- Docker, Compose, FastAPI, Vue, and the wider open-source ecosystem.

## License

MIT License
