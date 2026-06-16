FROM node:22-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ── Python dependencies ────────────────────────────────────────────────

FROM python:3.12-slim AS python-builder

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Runtime image ──────────────────────────────────────────────────────

FROM python:3.12-slim

WORKDIR /app

COPY --from=python-builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=python-builder /usr/local/bin /usr/local/bin

COPY backend/app/ ./app/
COPY --from=frontend-builder /frontend/dist ./frontend_dist/

RUN mkdir -p /app/data && \
    addgroup --system --gid 1001 dashboard && \
    adduser --system --uid 1001 --ingroup dashboard dashboard && \
    chown -R dashboard:dashboard /app

USER dashboard

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--log-level", "info"]
