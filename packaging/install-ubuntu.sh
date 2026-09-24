#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"
PUBLIC_PORT="${PUBLIC_PORT:-5175}"
PUBLIC_ORIGIN="${PUBLIC_ORIGIN:-}"
PUBLIC_ORIGIN_ALIASES="${PUBLIC_ORIGIN_ALIASES:-}"
FRONTEND_BIND_ADDRESS="${FRONTEND_BIND_ADDRESS:-}"
ANNOTATOR_BIND_ADDRESS="${ANNOTATOR_BIND_ADDRESS:-}"
COMPOSE_WRAPPER="$ROOT/packaging/compose-ubuntu.sh"

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

info() {
  echo "[INFO] $*"
}

default_frontend_origin_aliases() {
  local aliases="http://localhost:5173,http://127.0.0.1:5173,http://localhost:5175,http://127.0.0.1:5175"
  case "$PUBLIC_ORIGIN" in
    *:5175) aliases="${aliases},${PUBLIC_ORIGIN%:*}:5173" ;;
    *:5173) aliases="${aliases},${PUBLIC_ORIGIN%:*}:5175" ;;
  esac
  printf '%s\n' "$aliases"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

create_production_env() {
  local postgres_password minio_password secret_key tensorboard_secret inference_secret frontend_origin frontend_aliases frontend_bind_address annotator_bind_address

  frontend_origin="${PUBLIC_ORIGIN:-http://localhost:${PUBLIC_PORT}}"
  frontend_aliases="${PUBLIC_ORIGIN_ALIASES:-$(default_frontend_origin_aliases)}"
  frontend_bind_address="${FRONTEND_BIND_ADDRESS:-127.0.0.1}"
  annotator_bind_address="${ANNOTATOR_BIND_ADDRESS:-0.0.0.0}"

  postgres_password="$(openssl rand -hex 32)"
  minio_password="$(openssl rand -hex 32)"
  secret_key="$(openssl rand -hex 32)"
  tensorboard_secret="$(openssl rand -hex 32)"
  inference_secret="$(openssl rand -hex 32)"

  umask 077
  cat > "$ENV_FILE" <<EOF
# Generated for this deployment. Keep this file and secrets/ outside version control.
POSTGRES_DB=ml_platform
POSTGRES_USER=ml_platform
POSTGRES_PASSWORD=${postgres_password}
DATABASE_URL=postgresql+psycopg://ml_platform:${postgres_password}@postgres:5432/ml_platform

SECRET_KEY=${secret_key}
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
REDIS_EVENTS_URL=redis://redis:6379/2

MINIO_ROOT_USER=mlplatform
MINIO_ROOT_PASSWORD=${minio_password}
MINIO_ACCESS_KEY=mlplatform
MINIO_SECRET_KEY=${minio_password}
MINIO_ENDPOINT=minio:9000
MINIO_BUCKET=ml-platform
MINIO_SECURE=false
MLFLOW_S3_ENDPOINT_URL=http://minio:9000
MLFLOW_TRACKING_URI=http://mlflow:5000
MLFLOW_BACKEND_STORE_URI=postgresql+psycopg://ml_platform:${postgres_password}@postgres:5432/mlflow
MLFLOW_ARTIFACT_ROOT=s3://ml-platform/mlflow

TENSORBOARD_GATEWAY_URL=http://tensorboard-gateway:6006
TENSORBOARD_SESSION_SECRET=${tensorboard_secret}
TENSORBOARD_SESSION_TTL_SECONDS=300
TENSORBOARD_IDLE_TIMEOUT_SECONDS=600
INFERENCE_RUNTIME_URL=http://inference-runtime:7000
INFERENCE_INTERNAL_SECRET=${inference_secret}
NOTIFICATION_CRYPTO_SECRET_FILE=./secrets/notification_master_key

NGINX_BIND_ADDRESS=0.0.0.0
NGINX_PORT=${PUBLIC_PORT}
BACKEND_BIND_ADDRESS=127.0.0.1
BACKEND_PORT=8000
FRONTEND_BIND_ADDRESS=${frontend_bind_address}
FRONTEND_PORT=5173
ANNOTATOR_BIND_ADDRESS=${annotator_bind_address}
ANNOTATOR_PORT=8443
MINIO_BIND_ADDRESS=127.0.0.1
MINIO_API_PORT=9000
MINIO_CONSOLE_PORT=9001
FRONTEND_ORIGIN=${frontend_origin}
FRONTEND_ORIGIN_ALIASES=${frontend_aliases}
EOF
  chmod 600 "$ENV_FILE"
  info "Generated .env with new deployment secrets."
}

set_env_value() {
  local key="$1" value="$2" temp_file
  temp_file="${ENV_FILE}.tmp"
  awk -v key="$key" -v value="$value" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      print key "=" value
      found = 1
      next
    }
    { print }
    END { if (!found) print key "=" value }
  ' "$ENV_FILE" > "$temp_file"
  mv "$temp_file" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

[[ -f /etc/os-release ]] || die "Cannot identify the operating system."
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || die "This installer supports Ubuntu only (detected: ${PRETTY_NAME:-unknown})."

require_command docker
require_command openssl
require_command curl
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 (docker compose) is required."
docker info >/dev/null 2>&1 || die "Docker daemon is unavailable to the current user."
[[ -x "$COMPOSE_WRAPPER" ]] || die "Missing executable Compose wrapper: $COMPOSE_WRAPPER"

if [[ -n "$PUBLIC_ORIGIN" && ! "$PUBLIC_ORIGIN" =~ ^https?://[^/]+$ ]]; then
  die "PUBLIC_ORIGIN must be an origin such as http://SERVER_PUBLIC_IP:5175 (without a path)."
fi

cd "$ROOT"
if [[ ! -f "$ENV_FILE" ]]; then
  create_production_env
else
  info "Existing .env detected; preserving its secrets and service configuration."
fi

if [[ -n "$PUBLIC_ORIGIN" ]]; then
  set_env_value FRONTEND_ORIGIN "$PUBLIC_ORIGIN"
elif ! grep -Eq '^[[:space:]]*FRONTEND_ORIGIN[[:space:]]*=' "$ENV_FILE"; then
  set_env_value FRONTEND_ORIGIN "http://localhost:${PUBLIC_PORT}"
fi
if [[ -n "$PUBLIC_ORIGIN_ALIASES" ]]; then
  set_env_value FRONTEND_ORIGIN_ALIASES "$PUBLIC_ORIGIN_ALIASES"
elif [[ -n "$PUBLIC_ORIGIN" ]] && ! grep -Eq '^[[:space:]]*FRONTEND_ORIGIN_ALIASES[[:space:]]*=.+[[:space:]]*$' "$ENV_FILE"; then
  set_env_value FRONTEND_ORIGIN_ALIASES "$(default_frontend_origin_aliases)"
elif ! grep -Eq '^[[:space:]]*FRONTEND_ORIGIN_ALIASES[[:space:]]*=' "$ENV_FILE"; then
  set_env_value FRONTEND_ORIGIN_ALIASES "$(default_frontend_origin_aliases)"
fi
if [[ -n "$FRONTEND_BIND_ADDRESS" ]]; then
  set_env_value FRONTEND_BIND_ADDRESS "$FRONTEND_BIND_ADDRESS"
elif ! grep -Eq '^[[:space:]]*FRONTEND_BIND_ADDRESS[[:space:]]*=' "$ENV_FILE"; then
  set_env_value FRONTEND_BIND_ADDRESS "127.0.0.1"
fi
if [[ -n "$ANNOTATOR_BIND_ADDRESS" ]]; then
  set_env_value ANNOTATOR_BIND_ADDRESS "$ANNOTATOR_BIND_ADDRESS"
elif ! grep -Eq '^[[:space:]]*ANNOTATOR_BIND_ADDRESS[[:space:]]*=' "$ENV_FILE"; then
  set_env_value ANNOTATOR_BIND_ADDRESS "0.0.0.0"
fi
set_env_value NGINX_PORT "$PUBLIC_PORT"
set_env_value NGINX_BIND_ADDRESS "0.0.0.0"
info "Backend CORS frontend origin: $(awk -F= '/^[[:space:]]*FRONTEND_ORIGIN[[:space:]]*=/{print substr($0, index($0, "=") + 1); exit}' "$ENV_FILE")"
"$ROOT/ml-platform/scripts/prepare-production-secrets.sh"

info "Validating the Compose configuration."
"$COMPOSE_WRAPPER" config >/dev/null

info "Building and starting services. The first build can take several minutes."
"$COMPOSE_WRAPPER" up -d --build --remove-orphans

info "Waiting for the public health endpoint on port $PUBLIC_PORT."
for _ in $(seq 1 120); do
  if curl --fail --silent "http://127.0.0.1:${PUBLIC_PORT}/health" >/dev/null \
    && curl --fail --silent "http://127.0.0.1:${PUBLIC_PORT}/api/health" >/dev/null; then
    info "Installation completed. Open http://<server-ip>:${PUBLIC_PORT}/"
    exit 0
  fi
  sleep 3
done

"$COMPOSE_WRAPPER" ps
"$COMPOSE_WRAPPER" logs --tail=100
die "Services did not become healthy within six minutes."
