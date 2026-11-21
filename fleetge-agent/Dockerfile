FROM docker:27-cli AS docker-cli

FROM --platform=$BUILDPLATFORM alpine:3.21 AS compressor
RUN apk add --no-cache upx
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/docker-compose /tmp/docker-compose
RUN upx -1 /tmp/docker-compose

FROM python:3.12-alpine

COPY --from=compressor /tmp/docker-compose /usr/local/bin/docker-compose
RUN mkdir -p /usr/local/libexec/docker/cli-plugins && \
    ln -s /usr/local/bin/docker-compose /usr/local/libexec/docker/cli-plugins/docker-compose

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y pip setuptools wheel && \
    find /usr/local -depth \( -type d -a \( -name test -o -name tests -o -name __pycache__ \) -o -type f -a \( -name '*.pyc' -o -name '*.pyo' \) \) -exec rm -rf '{}' +

COPY . .
RUN sed -i 's/\r$//' /app/*.py && \
    chmod +x /app/docker_cli_shim.py && \
    ln -sf /app/docker_cli_shim.py /usr/local/bin/docker

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

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "/app/healthcheck.py"]

CMD ["sh", "-c", "exec python -m uvicorn main:app --host \"${AGENT_BIND_HOST:-0.0.0.0}\" --port \"${PORT:-8080}\""]
