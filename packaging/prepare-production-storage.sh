#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Bind mounts replace the image directories, so repair their ownership before
# the non-root backend starts writing uploads or runtime data.
exec "$ROOT/packaging/compose-ubuntu.sh" run --rm --no-deps \
  --user 0:0 \
  --entrypoint /bin/sh \
  backend \
  -c 'set -eu; mkdir -p /app/app/uploads /app/data; chown -R 1000:1000 /app/app/uploads /app/data'
