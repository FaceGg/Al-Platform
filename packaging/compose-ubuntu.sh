#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

exec docker compose \
  -f "$ROOT/docker-compose.yml" \
  -f "$ROOT/packaging/docker-compose.legacy-cpu.yml" \
  "$@"
