FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app

# Railway injects $PORT. Migrations run before the API starts (idempotent).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn bankboard.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
