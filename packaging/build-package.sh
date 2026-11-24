#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-20260926-r12}"
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
    .trae|.trae/*|.trae-*/*|*/.trae|*/.trae/*|*/.trae-*/[!x]*/[!x]*|\
    .zcode|.zcode/*|*/.zcode|*/.zcode/*|\
    ml-platform/backend/data/*|\
    */temp_login.*|*/temp_token.*|temp_login.*|temp_token.*|\
    ml_platform.db|*.db|*.db-shm|*.db-wal|*.tar.gz|*.log|*.err|\
    node_modules/*|*/node_modules/*|__pycache__/*|*/__pycache__/*|\
    *竞品对比*|\
    spot_weld_quality_experiment_1875.csv|spot_weld_quality_experiment_60.csv) return 0 ;;
  esac
  return 1
}

prune_excluded_stage_paths() {
  local stage_root="$STAGE_DIR/$PACKAGE_NAME"

  find "$stage_root" -type d \( \
    -name .git -o -name .worktrees -o -name node_modules -o -name __pycache__ \
    -o -name secrets -o -name output -o -name temp_test -o -name tmp \
    -o -name wheelhouse -o -name .trae -o -name '.trae-*' \
    -o -name .zcode -o -path '*/ml-platform/backend/data' \
  \) -prune -exec rm -rf -- {} +

  find "$stage_root" -type f \( \
    -name .env -o -name '.env.*' -o -name '*.db' -o -name '*.db-shm' \
    -o -name '*.db-wal' -o -name '*.tar.gz' -o -name '*.log' -o -name '*.err' \
    -o -name '*竞品对比*' -o -name 'temp_login.*' -o -name 'temp_token.*' \
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

# Windows 工作区覆盖（autocrlf）可能把 CRLF 行尾带入归档，Linux 侧的
# shell 脚本会因此无法执行（/usr/bin/env: bash\r）。打包前统一归一为 LF。
find "$STAGE_DIR/$PACKAGE_NAME" -type f \( \
  -name '*.sh' -o -name '*.py' -o -name '*.yml' -o -name '*.yaml' \
  -o -name 'Dockerfile*' -o -name '*.conf' -o -name '*.service' \
\) -exec sed -i 's/\r$//' {} +

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
MinIO health: CPUv1 server uses curl HTTP readiness probe; mc init waits for service_healthy before creating the bucket
Package indexes: PIP_INDEX_URL defaults to mirrors.aliyun.com; NPM_REGISTRY defaults to registry.npmmirror.com
Windows package: linkraft-windows-<VERSION>.zip（同一源码树；入口 packaging/install-windows.ps1 + README-WINDOWS.md）
Storage ownership repair (chown 1000:1000) applies to Ubuntu bind mounts only; Windows Docker Desktop needs no chown
Excluded: .env, secrets, databases, caches, dependencies, test evidence, Git metadata
EOF

tar -C "$STAGE_DIR" -czf "$TMP_ARCHIVE" "$PACKAGE_NAME"
mv -f -- "$TMP_ARCHIVE" "$ARCHIVE"
(
  cd "$OUTPUT_DIR"
  sha256sum "$(basename "$ARCHIVE")" > "$(basename "$CHECKSUM")"
)
printf '%s\n' "$ARCHIVE"

# Windows 包：同一棵 stage 树，顶层目录改 windows 命名后压成 zip。仅构建机
# 同时具备 powershell.exe 与 cygpath（Git Bash）时产出——下游 Ubuntu 重建与
# WSL 构建自动降级为只产 tar.gz，不受影响。
ZIP_ARCHIVE="$OUTPUT_DIR/linkraft-windows-${VERSION}.zip"
ZIP_CHECKSUM="${ZIP_ARCHIVE}.sha256"
ZIP_DIR_NAME="linkraft-windows-${VERSION}"
if command -v powershell.exe >/dev/null 2>&1 && command -v cygpath >/dev/null 2>&1; then
  mv -- "$STAGE_DIR/$PACKAGE_NAME" "$STAGE_DIR/$ZIP_DIR_NAME"
  STAGE_WIN="$(cygpath -w "$STAGE_DIR/$ZIP_DIR_NAME")"
  ZIP_WIN="$(cygpath -w "$ZIP_ARCHIVE")"
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command \
    "Compress-Archive -Path '$STAGE_WIN' -DestinationPath '$ZIP_WIN' -Force" >/dev/null
  (
    cd "$OUTPUT_DIR"
    sha256sum "$(basename "$ZIP_ARCHIVE")" > "$(basename "$ZIP_CHECKSUM")"
  )
  printf '%s\n' "$ZIP_ARCHIVE"
else
  echo "[INFO] powershell.exe/cygpath 不可用，跳过 Windows zip（仅产出 tar.gz）。"
fi
