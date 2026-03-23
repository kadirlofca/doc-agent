# ============================================================================
# PageIndex — Docker image for Google Cloud Run
# ============================================================================
# Multi-stage build: install deps in builder, copy to slim runtime
# Final image: ~400MB (Python + PyMuPDF + tiktoken + Streamlit)
# ============================================================================

# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies for PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Stage 2: Runtime
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY app.py .
COPY pageindex/ pageindex/
COPY storage/ storage/

# Streamlit config: disable telemetry, set server options
RUN mkdir -p /root/.streamlit
RUN cat <<'EOF' > /root/.streamlit/config.toml
[server]
headless = true
port = 8080
enableCORS = false
enableXsrfProtection = false
maxUploadSize = 50

[browser]
gatherUsageStats = false

[theme]
base = "light"
EOF

# Cloud Run uses PORT env var (default 8080)
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

# Health check for Cloud Run
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8080/_stcore/health || exit 1

# Run Streamlit
EXPOSE 8080
CMD ["python3", "-m", "streamlit", "run", "app.py", \
     "--server.port=8080", \
     "--server.address=0.0.0.0"]
