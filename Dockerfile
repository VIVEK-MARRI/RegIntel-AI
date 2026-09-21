# RegIntel AI backend image — LOCAL development and self-hosted use.
#
# NOT USED FOR RENDER HOSTING. The canonical Render deployment is the
# Blueprint in render.yaml (native-Python backend + static frontend + free
# Neon Postgres). Do NOT point a Render Web Service at this Dockerfile:
# previous deploys that did so OOM'd on the free tier and bypassed every
# env var render.yaml wires (JWT secret, CORS, admin seeding, demo mode).
# Use `docker compose up` locally, where Postgres + full ML are available.
#
# The heavy torch/transformers ML stack is OPT-IN via build arg:
#   docker build --build-arg INSTALL_ML_STACK=1 .
# (docker-compose.yml already passes it.) Default slim image uses TF-IDF.
# ─── Stage 0: frontend builder (Node → static SPA) ────────────────────────
# Builds the React SPA so this single image serves the COMPLETE application
# (API + UI on one origin: no CORS, no extra service). The SPA is built with
# default env (relative /api calls, basename /app), which is exactly what
# same-origin serving needs — no build args required.
FROM node:20-alpine AS frontend-builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund --prefer-offline
COPY frontend/tsconfig.json frontend/tsconfig.node.json frontend/vite.config.ts frontend/tailwind.config.ts frontend/postcss.config.js frontend/index.html ./
COPY frontend/src ./src
COPY frontend/public ./public
ENV NODE_ENV=production
RUN npm run build

# ─── Stage 1: python builder ─────────────────────────────────────────────
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt requirements-ml.txt requirements-llm.txt ./
ARG INSTALL_ML_STACK=0
RUN pip install --upgrade pip wheel \
    && pip install -r requirements.txt -r requirements-llm.txt \
    && if [ "$INSTALL_ML_STACK" = "1" ]; then \
           pip install -r requirements-ml.txt; \
       fi

FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="regintel-ai-backend-dev" \
      org.opencontainers.image.description="RegIntel AI development backend"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    PYTHONPATH="/app"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

# Demo corpus excerpts for SEED_DEMO_CORPUS one-shot seeding (25 KB).
COPY seed_data ./seed_data

# Built SPA (served by FastAPI itself at /app — see STATIC_DIR in app/main.py).
COPY --from=frontend-builder /build/dist ./static

# Copy the static landing page (served at / by FastAPI — see LANDING_DIR).
COPY landing/ ./landing

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health/ready || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
