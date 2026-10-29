FROM node:22-bookworm-slim AS node-deps
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM node:22-bookworm-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Preserve the deployed Python runtime during application-only updates.
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    NODE_ENV=production \
    FRONTEND_SERVE_STATIC=true \
    CONFIG_FILE=/app/config/default.yaml \
    TZ=Asia/Shanghai
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node-deps /usr/local/bin/node /usr/local/bin/node
COPY --from=node-deps /build/node_modules ./node_modules
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
RUN mkdir -p /app/data /app/backend/app/storage/media /app/backend/app/storage/exports
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"
CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8000"]
