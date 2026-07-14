#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
ATTEMPTS="${1:-1}"

for ((attempt=1; attempt<=ATTEMPTS; attempt++)); do
  if curl --fail --silent "http://127.0.0.1:$BACKEND_PORT/api/health" | grep -Eq '"status":"(ok|healthy)"' \
    && curl --fail --silent "http://127.0.0.1:$FRONTEND_PORT/" >/dev/null; then
    echo "Health check passed."
    exit 0
  fi
  sleep 1
done
echo "Health check failed after $ATTEMPTS attempts." >&2
exit 1
