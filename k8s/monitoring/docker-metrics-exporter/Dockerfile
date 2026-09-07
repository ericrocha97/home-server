# LabMonitor Docker metrics exporter (platform fallback, mode built).
# HTTP-only collector: scrapes the read-only proxy over TCP. No local
# mounts, no privileged flags, no host ports; runs as a non-root user.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    METRICS_PORT=9797

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    && rm -rf /root/.cache
COPY app.py /app/app.py

# Unprivileged runtime user (nobody); nothing here needs root.
USER 65534:65534
EXPOSE 9797
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9797/healthz', timeout=2)"
CMD ["python3", "/app/app.py"]
