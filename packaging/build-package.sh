#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-20260909}"
PACKAGE_NAME="linkraft-ubuntu-${VERSION}"
OUTPUT_DIR="$ROOT/output"
ARCHIVE="$OUTPUT_DIR/${PACKAGE_NAME}.tar.gz"
CHECKSUM="${ARCHIVE}.sha256"
STAGE_DIR="$(mktemp -d)"
TMP_ARCHIVE="${ARCHIVE}.tmp"

cleanup() {
  rm -rf -- "$STAGE_DIR"
  rm -f -- "$TMP_ARCHIVE"
}
trap cleanup EXIT

exclude_path() {
  case "$1" in
    .env|.env.*|secrets/*|output/*|temp_test/*|tmp/*|.worktrees/*|.git/*|\
    ml_platform.db|*.db|*.db-shm|*.db-wal|*.tar.gz|*.log|*.err|\
    node_modules/*|*/node_modules/*|__pycache__/*|*/__pycache__/*|\
    spot_weld_quality_experiment_1875.csv|spot_weld_quality_experiment_60.csv) return 0 ;;
  esac
  return 1
}

copy_overlay_file() {
  local path="$1" destination
  exclude_path "$path" && return 0
  [[ -f "$ROOT/$path" ]] || return 0
  destination="$STAGE_DIR/$PACKAGE_NAME/$path"
  mkdir -p "$(dirname "$destination")"
  cp -- "$ROOT/$path" "$destination"
}

mkdir -p "$OUTPUT_DIR" "$STAGE_DIR"
git -C "$ROOT" archive --format=tar --prefix="$PACKAGE_NAME/" HEAD | tar -C "$STAGE_DIR" -xf -

while IFS= read -r -d '' path; do
  copy_overlay_file "$path"
done < <(git -C "$ROOT" diff --name-only -z HEAD)

while IFS= read -r -d '' path; do
  copy_overlay_file "$path"
done < <(git -C "$ROOT" ls-files --others --exclude-standard -z)

while IFS= read -r -d '' path; do
  rm -f -- "$STAGE_DIR/$PACKAGE_NAME/$path"
done < <(git -C "$ROOT" diff --diff-filter=D --name-only -z HEAD)

chmod +x "$STAGE_DIR/$PACKAGE_NAME/packaging/"*.sh \
  "$STAGE_DIR/$PACKAGE_NAME/ml-platform/scripts/prepare-production-secrets.sh"

cat > "$STAGE_DIR/$PACKAGE_NAME/RELEASE-MANIFEST.txt" <<EOF
Package: ${PACKAGE_NAME}
Source HEAD: $(git -C "$ROOT" rev-parse HEAD)
Working tree overlay: included for tracked changes and non-ignored untracked source files
Built UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Public endpoint: http://<server-ip>:5175/
MinIO: minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1
MinIO client: minio/mc:RELEASE.2025-07-21T05-28-08Z-cpuv1
Python services: python:3.11-slim-bookworm
Excluded: .env, secrets, databases, caches, dependencies, test evidence, Git metadata
EOF

tar -C "$STAGE_DIR" -czf "$TMP_ARCHIVE" "$PACKAGE_NAME"
mv -f -- "$TMP_ARCHIVE" "$ARCHIVE"
(
  cd "$OUTPUT_DIR"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$CHECKSUM")"
)
printf '%s\n' "$ARCHIVE"
