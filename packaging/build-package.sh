#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-20260925-r5}"
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
    .env|.env.*|*/.env|*/.env.*|secrets/*|*/secrets/*|output/*|*/output/*|temp_test/*|*/temp_test/*|tmp/*|*/tmp/*|.worktrees/*|*/.worktrees/*|.git/*|*/.git/*|\
    ml_platform.db|*.db|*.db-shm|*.db-wal|*.tar.gz|*.log|*.err|\
    node_modules/*|*/node_modules/*|__pycache__/*|*/__pycache__/*|\
    spot_weld_quality_experiment_1875.csv|spot_weld_quality_experiment_60.csv) return 0 ;;
  esac
  return 1
}

prune_excluded_stage_paths() {
  local stage_root="$STAGE_DIR/$PACKAGE_NAME"

  find "$stage_root" -type d \( \
    -name .git -o -name .worktrees -o -name node_modules -o -name __pycache__ \
    -o -name secrets -o -name output -o -name temp_test -o -name tmp \
  \) -prune -exec rm -rf -- {} +

  find "$stage_root" -type f \( \
    -name .env -o -name '.env.*' -o -name '*.db' -o -name '*.db-shm' \
    -o -name '*.db-wal' -o -name '*.tar.gz' -o -name '*.log' -o -name '*.err' \
  \) ! -name .env.example -delete
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

prune_excluded_stage_paths

chmod +x "$STAGE_DIR/$PACKAGE_NAME/packaging/"*.sh \
  "$STAGE_DIR/$PACKAGE_NAME/ml-platform/scripts/prepare-production-secrets.sh"

cat > "$STAGE_DIR/$PACKAGE_NAME/RELEASE-MANIFEST.txt" <<EOF
Package: ${PACKAGE_NAME}
Source HEAD: $(git -C "$ROOT" rev-parse HEAD)
Working tree overlay: included for tracked changes and non-ignored untracked source files
Built UTC: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Public endpoint: http://<server-ip>:5175/
Annotator portal: http://<server-ip>:8443/ (ANNOTATOR_BIND_ADDRESS defaults to 0.0.0.0)
Deployment profile: packaging/docker-compose.legacy-cpu.yml
CORS: FRONTEND_ORIGIN is set from PUBLIC_ORIGIN; FRONTEND_ORIGIN_ALIASES accepts exact comma-separated browser origins
HTTP UUID compatibility: frontend request and annotation IDs use an RFC 4122 fallback when crypto.randomUUID is unavailable on private-IP HTTP
MinIO: minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1
MinIO client: minio/mc:RELEASE.2025-07-21T05-28-08Z-cpuv1
Python services: python:3.11-slim-bookworm (package-specific legacy CPU Dockerfiles)
Frontend build: node:20-bookworm-slim with npm retries (package-specific legacy CPU Dockerfile)
Annotator frontend build: node:20-bookworm-slim source build; no host dist/ required
Writable storage: installer repairs bind-mounted backend data/uploads ownership to UID/GID 1000 before startup
MinIO health: CPUv1 server health is coordinated by the mc init container because the server image does not include mc
Package indexes: PIP_INDEX_URL defaults to mirrors.aliyun.com; NPM_REGISTRY defaults to registry.npmmirror.com
Excluded: .env, secrets, databases, caches, dependencies, test evidence, Git metadata
EOF

tar -C "$STAGE_DIR" -czf "$TMP_ARCHIVE" "$PACKAGE_NAME"
mv -f -- "$TMP_ARCHIVE" "$ARCHIVE"
(
  cd "$OUTPUT_DIR"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$CHECKSUM")"
)
printf '%s\n' "$ARCHIVE"
