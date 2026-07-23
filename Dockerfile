FROM node:22-bookworm-slim AS axe_core

WORKDIR /axe
RUN npm init -y \
    && npm install --omit=dev --no-audit --no-fund axe-core@4.11.4

FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SWARM_AXE_SCRIPT_PATH=/opt/swarm/axe/axe.min.js

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=axe_core /axe/node_modules/axe-core/axe.min.js /opt/swarm/axe/axe.min.js

CMD ["sh", "-c", "python -m uvicorn api.automation_factory:create_automation_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
