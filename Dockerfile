# All-in-one image for Railway (single service): web (Next.js PWA) + api (FastAPI) + worker (scheduler).
# Railway detects this file at the repo root automatically; no Root Directory to configure.

# ---- web build ---------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY apps/web ./
RUN npm run build

# ---- runtime -----------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
# Node runtime only (the Next standalone server needs nothing else)
COPY --from=web /usr/local/bin/node /usr/local/bin/node

WORKDIR /app/api
COPY apps/api/pyproject.toml ./
COPY apps/api/src ./src
RUN pip install --upgrade pip && pip install .
COPY apps/api/alembic.ini ./
COPY apps/api/migrations ./migrations

WORKDIR /app/web
COPY --from=web /web/.next/standalone ./
COPY --from=web /web/.next/static ./.next/static
COPY --from=web /web/public ./public

COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh && useradd --create-home --uid 10001 app && chown -R app /app
USER app
WORKDIR /app
CMD ["/app/start.sh"]
