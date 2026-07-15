#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$ROOT/.." && pwd)"
FRONTEND_DIR="${ML_PLATFORM_FRONTEND_DIR:-$ROOT/frontend}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
RUNTIME_DIR="${ML_PLATFORM_RUNTIME_DIR:-$PROJECT_ROOT/temp_test/runtime}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

command -v "$PYTHON_BIN" >/dev/null || { echo "Python 3.10+ is required." >&2; exit 1; }
command -v node >/dev/null || { echo "Node.js 18+ is required." >&2; exit 1; }
command -v npm >/dev/null || { echo "npm is required." >&2; exit 1; }
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'
node -e 'const major=Number(process.versions.node.split(".")[0]); if(major<18) process.exit(1)'
[[ -f "$ROOT/backend/requirements.txt" ]] || { echo "Backend requirements.txt is missing." >&2; exit 1; }
[[ -d "$FRONTEND_DIR/node_modules" ]] || { echo "Frontend dependencies are missing in $FRONTEND_DIR. Run npm ci there." >&2; exit 1; }

port_free() {
  "$PYTHON_BIN" - "$1" <<'PY'
import socket, sys
sock = socket.socket()
try:
    sock.bind(("127.0.0.1", int(sys.argv[1])))
finally:
    sock.close()
PY
}
port_free "$BACKEND_PORT" || { echo "Port $BACKEND_PORT is already in use." >&2; exit 1; }
port_free "$FRONTEND_PORT" || { echo "Port $FRONTEND_PORT is already in use." >&2; exit 1; }

mkdir -p "$RUNTIME_DIR"
touch "$RUNTIME_DIR/.write-test" && rm "$RUNTIME_DIR/.write-test"
cd "$ROOT/backend"
nohup setsid "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" >"$RUNTIME_DIR/backend.log" 2>"$RUNTIME_DIR/backend.err.log" &
echo $! >"$RUNTIME_DIR/backend.pid"
cd "$FRONTEND_DIR"
nohup setsid npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" >"$RUNTIME_DIR/frontend.log" 2>"$RUNTIME_DIR/frontend.err.log" &
echo $! >"$RUNTIME_DIR/frontend.pid"

cleanup_on_error() { "$ROOT/scripts/stop.sh" || true; }
trap cleanup_on_error ERR
BACKEND_PORT="$BACKEND_PORT" FRONTEND_PORT="$FRONTEND_PORT" "$ROOT/scripts/health-check.sh" 30
trap - ERR
echo "Backend:  http://127.0.0.1:$BACKEND_PORT"
echo "Frontend: http://127.0.0.1:$FRONTEND_PORT"
