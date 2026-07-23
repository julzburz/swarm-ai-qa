FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "python -m uvicorn api.automation_factory:create_automation_app --factory --host 0.0.0.0 --port ${PORT:-8000}"]
