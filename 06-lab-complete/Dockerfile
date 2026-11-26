# ---- Stage 1: builder — cài dependencies vào virtualenv ----
FROM python:3.11-slim AS builder
WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: runtime — chỉ copy venv + source ----
FROM python:3.11-slim
RUN groupadd -r app && useradd -r -g app app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app/ ./app/
COPY utils/ ./utils/
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request as u; u.urlopen('http://localhost:%s/health' % os.getenv('PORT','8000'), timeout=3)" || exit 1
# exec → uvicorn là PID 1, nhận SIGTERM trực tiếp khi `docker stop`
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2"]