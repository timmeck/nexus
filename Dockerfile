# ── Stage 1: Dependencies ────────────────────────────────────────────
FROM python:3.12-slim AS deps

WORKDIR /app

# System deps for async DB and WebSocket support
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Stage 2: Application ────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="Tim Mecklenburg <tim@timmeck.dev>"
LABEL description="Nexus — AI-to-AI Protocol Layer"

WORKDIR /app

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy source
COPY nexus/ nexus/
COPY agents/ agents/
COPY run.py .
COPY requirements.txt .

# Persistent data volume
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Non-root user for security
RUN groupadd -r nexus && useradd -r -g nexus -d /app nexus && \
    chown -R nexus:nexus /app
USER nexus

EXPOSE 9500

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9500/health')" || exit 1

CMD ["uvicorn", "nexus.main:app", "--host", "0.0.0.0", "--port", "9500"]
