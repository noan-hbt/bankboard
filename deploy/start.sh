#!/bin/sh
# Starts the three processes of the all-in-one image. If any of them exits, the container
# exits too, so Railway restarts it (no half-alive deployment).
set -eu

API_DIR="${API_DIR:-/app/api}"
WEB_DIR="${WEB_DIR:-/app/web}"
PY="${PYTHON:-python}"
PUBLIC_PORT="${PORT:-3000}"
API_PORT="${API_PORT:-8000}"

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL is missing: add a PostgreSQL database and set DATABASE_URL=\${{Postgres.DATABASE_URL}}" >&2
  exit 1
fi
if [ -z "${APP_ENCRYPTION_KEY:-}" ]; then
  echo "APP_ENCRYPTION_KEY is missing: set it to a random string of 32+ characters" >&2
  exit 1
fi

cd "$API_DIR"
"$PY" -m alembic upgrade head

"$PY" -m uvicorn bankboard.main:app --host 127.0.0.1 --port "$API_PORT" --proxy-headers --forwarded-allow-ips=127.0.0.1 &
API_PID=$!
"$PY" -m bankboard.jobs scheduler &
WORKER_PID=$!

cd "$WEB_DIR"
PORT="$PUBLIC_PORT" HOSTNAME=0.0.0.0 BACKEND_URL="http://127.0.0.1:$API_PORT" node server.js &
WEB_PID=$!

trap 'kill $API_PID $WORKER_PID $WEB_PID 2>/dev/null' TERM INT
# exit as soon as one process stops
while kill -0 $API_PID 2>/dev/null && kill -0 $WORKER_PID 2>/dev/null && kill -0 $WEB_PID 2>/dev/null; do
  sleep 5
done
echo "a process exited; stopping container" >&2
kill $API_PID $WORKER_PID $WEB_PID 2>/dev/null || true
exit 1
