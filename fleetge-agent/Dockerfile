FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default configuration environment variables
ENV PORT=8080
ENV STACKS_BASE_DIR=/opt/stacks
ENV AGENT_TOKEN=""

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
