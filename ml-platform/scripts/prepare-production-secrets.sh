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

# Fernet 主密钥缺键补齐（2026-11-25，补齐路线 D8）：LLM 档案密钥与外部数据源
# 口令密钥纳入 production 必填校验。.env 里缺失或为空 → 生成；已有非空值 →
# 原样保留（换 key 会让已加密的 LLM 档案密钥无法解密）。全新安装与存量升级
# 都经过本脚本，升级前先执行一次即可补齐。
env_value() {
  awk -v key="$1" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      print substr($0, index($0, "=") + 1)
      exit
    }
  ' "$ENV_FILE"
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

fernet_key() {
  # 同步剥掉 \r：个别 shell 的 openssl 走文本模式管道会输出 CRLF
  openssl rand -base64 32 | tr '+/' '-_' | tr -d '\r\n'
}

ensure_master_key() {
  local name="$1" current
  current="$(env_value "$name")"
  current="${current%$'\r'}"
  if [[ -n "${current//\"/}" ]]; then
    echo "[INFO] Existing $name preserved."
    return
  fi
  set_env_value "$name" "$(fernet_key)"
  echo "[INFO] Generated $name."
  if [[ "$name" == "LLM_MASTER_KEY" ]]; then
    printf '%s\n' \
      "[NOTE] .env 中没有 LLM_MASTER_KEY，已生成新密钥。若此前是通过其他方式（如 shell 环境变量）" \
      "[NOTE] 提供该密钥，请把 .env 中这一行改回原密钥，否则已保存的大模型档案密钥将无法解密。"
  fi
}

ensure_master_key LLM_MASTER_KEY
ensure_master_key DATASOURCE_MASTER_KEY
