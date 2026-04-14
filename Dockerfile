FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir poetry==$POETRY_VERSION

# 1. Vendored shared lib (for the editable install reference)
COPY libs/python-common /app/libs/python-common

# 2. Dependency manifests first — better Docker layer caching
COPY pyproject.toml ./
COPY poetry.lock ./

# 3. Install only main deps (no dev)
RUN poetry install --no-root --only main

# 4. App code
COPY app /app/app

ENV PYTHONPATH=/app:/app/libs/python-common/src

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=20 CMD curl -fsS http://localhost:8000/livez || exit 1
CMD ["python", "-m", "app.main"]
