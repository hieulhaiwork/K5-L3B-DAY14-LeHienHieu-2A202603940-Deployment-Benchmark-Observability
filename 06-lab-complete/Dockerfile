# ============================================================
# Stage 1: Builder — cài dependencies vào /root/.local
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ============================================================
# Stage 2: Runtime — image nhỏ gọn (< 500 MB), non-root user
# ============================================================
FROM python:3.11-slim AS runtime

RUN groupadd -r appuser && useradd -r -g appuser -m appuser

WORKDIR /app

COPY --from=builder /root/.local /home/appuser/.local
COPY app/ ./app/
COPY utils/ ./utils/

RUN chown -R appuser:appuser /app /home/appuser/.local

USER appuser

ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\", \"8000\")}/health')" || exit 1

# exec giúp uvicorn là PID 1 để nhận trực tiếp SIGTERM khi docker stop
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
