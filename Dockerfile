# ============================================================================
# PageIndex — Docker image for FastAPI backend + Next.js frontend
# ============================================================================
# Multi-stage build:
#   1. Build frontend (Next.js)
#   2. Install Python deps
#   3. Runtime: serve both FastAPI and Next.js
# ============================================================================

# Stage 1: Build Next.js frontend
FROM node:20-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .

ENV NEXT_PUBLIC_API_URL=""
RUN npm run build

# Stage 2: Build Python dependencies
FROM python:3.11-slim AS backend-builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 3: Runtime
FROM python:3.11-slim

# Install Node.js for Next.js server
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python packages
COPY --from=backend-builder /install /usr/local

# Copy backend code
COPY backend/ backend/
COPY pageindex/ pageindex/
COPY storage/ storage/

# Copy built frontend
COPY --from=frontend-builder /frontend/.next frontend/.next
COPY --from=frontend-builder /frontend/package.json frontend/package.json
COPY --from=frontend-builder /frontend/next.config.ts frontend/next.config.ts
COPY --from=frontend-builder /frontend/node_modules frontend/node_modules

# Environment
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV NEXT_PUBLIC_API_URL=""

# Start script: run both backend and frontend
RUN cat <<'SCRIPT' > /app/start.sh
#!/bin/bash
set -e

# Start FastAPI backend (log stderr to stdout so Cloud Run captures it)
echo "Starting FastAPI backend..."
cd /app && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 2>&1 &
BACKEND_PID=$!

# Give backend a moment to start (or fail)
sleep 3

# Check if backend is still running
if ! kill -0 $BACKEND_PID 2>/dev/null; then
    echo "ERROR: FastAPI backend failed to start!"
    wait $BACKEND_PID
    exit 1
fi

echo "Backend started (PID $BACKEND_PID)"

# Start Next.js frontend
echo "Starting Next.js frontend..."
cd /app/frontend && npx next start --port 8080 --hostname 0.0.0.0 2>&1 &
FRONTEND_PID=$!

# Wait for any process to exit
wait -n
exit $?
SCRIPT
RUN chmod +x /app/start.sh

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8080/ || exit 1

EXPOSE 8080
CMD ["/app/start.sh"]
