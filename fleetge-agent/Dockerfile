FROM python:3.11-slim

# Copy docker and docker-compose-plugin from the official docker image
COPY --from=docker:latest /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:latest /usr/local/libexec/docker/cli-plugins/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default configuration environment variables
ENV PORT=8080
ENV AGENT_BIND_HOST=0.0.0.0
ENV STACKS_BASE_DIR=/opt/stacks
ENV AGENT_STATE_DIR=/opt/stacks/.fleetge
ENV METRICS_ACTIVE_INTERVAL=2
ENV METRICS_IDLE_TIMEOUT=15
ENV TRAFFIC_IDLE_INTERVAL=60
ENV TRAFFIC_INTERFACES=auto
ENV AGENT_TOKEN=""
ENV AGENT_REQUIRE_TOKEN=true

EXPOSE 8080

CMD ["sh", "-c", "exec python -m uvicorn main:app --host \"${AGENT_BIND_HOST:-0.0.0.0}\" --port \"${PORT:-8080}\""]
