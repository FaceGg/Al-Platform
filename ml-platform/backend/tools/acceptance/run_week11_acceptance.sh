#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../../../.." && pwd)"
EVIDENCE="${ML_PLATFORM_EVIDENCE_DIR:?ML_PLATFORM_EVIDENCE_DIR is required}"
PROJECT="${COMPOSE_PROJECT_NAME:?COMPOSE_PROJECT_NAME is required}"
COMPOSE=(docker compose --project-name "$PROJECT")
SOURCE_COMMIT="${ACCEPTANCE_SOURCE_COMMIT:-$(git -C "$ROOT" rev-parse HEAD)}"
RUNTIME_DIR="$(mktemp -d)"
MC_PATH="$RUNTIME_DIR/mc"
MC_CONTAINER=""
CREATED_NOTIFICATION_KEY=0
RUNNER_NOTIFICATION_KEY="$RUNTIME_DIR/notification-master-runner.key"
RUNNER_NOTIFICATION_KEY_CONTAINER=/tmp/week11-notification-master.key

cleanup() {
  local status=$?
  if [ -n "$MC_CONTAINER" ]; then
    docker rm -f "$MC_CONTAINER" >/dev/null 2>&1 || true
  fi
  rm -rf "$RUNTIME_DIR"
  if [ "$CREATED_NOTIFICATION_KEY" -eq 1 ]; then
    sudo rm -f -- "$NOTIFICATION_CRYPTO_SECRET_FILE"
  fi
  exit "$status"
}
trap cleanup EXIT

if [ -z "${NOTIFICATION_CRYPTO_SECRET_FILE:-}" ]; then
  export NOTIFICATION_CRYPTO_SECRET_FILE="$RUNTIME_DIR/notification-master.key"
  CREATED_NOTIFICATION_KEY=1
fi
if [ ! -s "$NOTIFICATION_CRYPTO_SECRET_FILE" ]; then
  python - "$NOTIFICATION_CRYPTO_SECRET_FILE" <<'PY'
import sys
from pathlib import Path

from cryptography.fernet import Fernet

target = Path(sys.argv[1])
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(Fernet.generate_key() + b"\n")
target.chmod(0o600)
PY
fi

# The production images run as UID 1000 and must be able to read the mounted key.
sudo chown 1000:1000 "$NOTIFICATION_CRYPTO_SECRET_FILE"
sudo chmod 0400 "$NOTIFICATION_CRYPTO_SECRET_FILE"
# The evidence executors run as the host runner UID so bind-mounted receipts are
# writable by Actions. Give those short-lived containers a separate, read-only
# copy of the same key without weakening the production secret mount.
sudo install \
  -o "$(id -u)" \
  -g "$(id -g)" \
  -m 0400 \
  "$NOTIFICATION_CRYPTO_SECRET_FILE" \
  "$RUNNER_NOTIFICATION_KEY"

mkdir -p "$EVIDENCE" "$EVIDENCE/security"
export ACCEPTANCE_SOURCE_COMMIT="$SOURCE_COMMIT"

if ! "${COMPOSE[@]}" up -d --wait --no-build \
  postgres redis minio minio-init mlflow tensorboard-gateway inference-runtime \
  migrate backend worker scheduler; then
  "${COMPOSE[@]}" logs --no-color migrate || true
  exit 1
fi

"${COMPOSE[@]}" exec -T backend \
  python -m tools.acceptance_environment environment \
  --output /tmp/week11-environment.json
"${COMPOSE[@]}" cp backend:/tmp/week11-environment.json "$EVIDENCE/environment.json"

bash "$ROOT/ml-platform/backend/tools/acceptance/run_performance.sh"

MC_CONTAINER="$(docker create minio/mc:latest)"
docker cp "$MC_CONTAINER:/usr/bin/mc" "$MC_PATH"
chmod 0555 "$MC_PATH"
docker rm -f "$MC_CONTAINER" >/dev/null
MC_CONTAINER=""

"${COMPOSE[@]}" run --rm -T \
  --user "$(id -u):$(id -g)" \
  --env "NOTIFICATION_MASTER_KEY_FILE=$RUNNER_NOTIFICATION_KEY_CONTAINER" \
  -v "$EVIDENCE:/evidence" \
  -v "$RUNNER_NOTIFICATION_KEY:$RUNNER_NOTIFICATION_KEY_CONTAINER:ro" \
  -v "$MC_PATH:/usr/local/bin/mc:ro" \
  backend sh tools/acceptance/run_backup_restore.sh

"${COMPOSE[@]}" run --rm -T \
  --user "$(id -u):$(id -g)" \
  --env "NOTIFICATION_MASTER_KEY_FILE=$RUNNER_NOTIFICATION_KEY_CONTAINER" \
  -v "$EVIDENCE:/evidence" \
  -v "$RUNNER_NOTIFICATION_KEY:$RUNNER_NOTIFICATION_KEY_CONTAINER:ro" \
  backend sh tools/acceptance/run_upgrade_fixture.sh
