#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

"$ROOT/packaging/compose-ubuntu.sh" down --remove-orphans
echo "[INFO] Containers stopped and removed. Volumes, .env, and secrets are preserved."
