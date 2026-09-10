#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env}"
DEFAULT_SECRET_PATH="./secrets/notification_master_key"

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

command -v openssl >/dev/null 2>&1 || die "openssl is required to generate the notification key."

umask 077
if [[ ! -f "$ENV_FILE" ]]; then
  touch "$ENV_FILE"
fi

secret_path="$(awk -F= '
  /^[[:space:]]*NOTIFICATION_CRYPTO_SECRET_FILE[[:space:]]*=/ {
    value = substr($0, index($0, "=") + 1)
    gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
    gsub(/^"|"$/, "", value)
    gsub(/^\x27|\x27$/, "", value)
    print value
    exit
  }
' "$ENV_FILE")"

if [[ -z "$secret_path" ]]; then
  secret_path="$DEFAULT_SECRET_PATH"
  printf '\nNOTIFICATION_CRYPTO_SECRET_FILE=%s\n' "$secret_path" >> "$ENV_FILE"
fi

if [[ "$secret_path" = /* ]]; then
  key_file="$secret_path"
else
  key_file="$ROOT/${secret_path#./}"
fi

key_dir="$(dirname "$key_file")"
if [[ ! -d "$key_dir" ]]; then
  mkdir -m 700 -p "$key_dir"
fi
chmod 700 "$key_dir"

if [[ ! -s "$key_file" ]]; then
  openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n' > "$key_file"
  printf '\n'
  chmod 600 "$key_file"
  echo "[INFO] Generated notification key: $key_file"
else
  chmod 600 "$key_file"
  echo "[INFO] Existing notification key preserved: $key_file"
fi
