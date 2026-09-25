# Linkraft Ubuntu Installation

## Requirements

- Ubuntu 22.04 or 24.04 LTS, 4 vCPU, 8 GB RAM, and at least 40 GB free disk.
- Docker Engine 24+ and Docker Compose v2.24.4+ (the package override uses `!override` for port replacement). The deployment user must be able to run `docker`.
- Firewall or cloud security-group access to TCP `5175` (main platform) and `8443` (annotator portal). Docker Hub, GHCR, and the configured Python package mirror must be reachable for the first build.
- The deployment Docker daemon must be able to obtain the exact CPUv1 MinIO images below, or they must be preloaded with these exact names. The installer never substitutes `latest`; if Docker Hub returns `pull access denied`, configure your approved registry/mirror or import the supplied image tar files before installation.

## Install

```bash
tar -xzf linkraft-ubuntu-20260926-r9.tar.gz
cd linkraft-ubuntu-20260926-r9
chmod +x packaging/*.sh ml-platform/scripts/prepare-production-secrets.sh
PUBLIC_ORIGIN=http://SERVER_PUBLIC_IP:5175 ./packaging/install-ubuntu.sh
```

The installer uses `packaging/docker-compose.legacy-cpu.yml` through `packaging/compose-ubuntu.sh`. `PUBLIC_ORIGIN` must be the exact browser origin used to open the platform, without a trailing path; it is written to `FRONTEND_ORIGIN` and passed into the backend container. For additional exact origins, pass comma-separated `PUBLIC_ORIGIN_ALIASES`, for example `PUBLIC_ORIGIN_ALIASES=http://SERVER_PUBLIC_IP:5173,http://127.0.0.1:5173`. If `.env` already exists, its secrets remain unchanged; an explicit `PUBLIC_ORIGIN` updates only the CORS origin setting. The script sets the main platform binding to `0.0.0.0:5175`, exposes the annotator portal at `0.0.0.0:8443`, creates `secrets/notification_master_key` when absent, repairs bind-mounted `data/` and `uploads/` ownership for UID/GID 1000, and starts the complete Compose stack. The CPUv1 MinIO server health check uses its HTTP readiness endpoint through `curl`; the separate `minio-init` CPUv1 mc container waits for `service_healthy`, configures the alias, and creates the bucket. The annotator frontend is built from its checked-in Node/Vite source during the image build; a pre-existing `dist/` directory is not required. The generated `.env` and `secrets/` directory contain credentials and must be backed up securely but never committed.

Access the main platform at `http://SERVER_PUBLIC_IP:5175/` and the annotator portal at `http://SERVER_PUBLIC_IP:8443/`. If UFW is enabled, run `sudo ufw allow 5175/tcp` and `sudo ufw allow 8443/tcp`. Backend port 8000, frontend port 5173, annotator API port 8444, and MinIO ports 9000/9001 remain local-only by default. `ANNOTATOR_BIND_ADDRESS` defaults to `0.0.0.0`; set it to `127.0.0.1` in `.env` when the portal should remain local-only.

If the package was installed before `FRONTEND_ORIGIN` support, repair the existing deployment with the exact public origin and recreate the backend container:

```bash
PUBLIC_ORIGIN=http://SERVER_PUBLIC_IP:5175 ./packaging/install-ubuntu.sh
./packaging/compose-ubuntu.sh up -d --force-recreate backend
./packaging/compose-ubuntu.sh up -d --force-recreate annotator annotator-frontend
./packaging/compose-ubuntu.sh restart annotator-frontend
./packaging/prepare-production-storage.sh
./packaging/compose-ubuntu.sh restart backend
```

For a direct local frontend at `5173`, the browser origin must be exactly `http://localhost:5173` or an explicitly configured alias such as `http://127.0.0.1:5173`; `http://SERVER_PUBLIC_IP:5173` is a different origin and must be added to `PUBLIC_ORIGIN_ALIASES`.

If TCP `5173` is preferred as a second public entry, bind the frontend explicitly and allow that port. Keep `5175` as the primary entry unless there is a concrete reason to expose the frontend directly:

```bash
FRONTEND_BIND_ADDRESS=0.0.0.0 \
PUBLIC_ORIGIN=http://SERVER_PUBLIC_IP:5175 \
PUBLIC_ORIGIN_ALIASES=http://SERVER_PUBLIC_IP:5173 \
./packaging/install-ubuntu.sh
sudo ufw allow 5173/tcp
```

To make `5173` the primary browser origin instead, set `PUBLIC_ORIGIN=http://SERVER_PUBLIC_IP:5173` and keep `FRONTEND_BIND_ADDRESS=0.0.0.0`; the installer automatically adds the matching `5175` host alias when no explicit alias list is supplied.

## Return Acceptance Readiness

回传批次创建后，worker 会先异步冻结并校验不可变快照。批次显示为 `pending` 不代表已经可以验收；在操作状态为 `queued` 或 `running` 时，后端会按安全契约返回 `409 RETURN_BATCH_NOT_READY`。r8 起的主平台和审核员门户会显示“回传校验中”，并在校验完成前禁用差异、验收、退回和批注操作。

回传后请在门户中点击“刷新”，确认回传操作状态为 `completed` 再验收。若持续停留在校验中，先检查 worker 和 scheduler：

```bash
./packaging/compose-ubuntu.sh ps backend worker scheduler
./packaging/compose-ubuntu.sh logs --tail=200 worker scheduler
```

r8 及更早版本存在一个 PostgreSQL 专属缺陷：`generic_annotation_tasks.status` 列宽为 `VARCHAR(24)`，而回传冻结会写入 `returned_pending_acceptance`（27 字符），导致每次回传校验都失败并表现为 `409 RETURN_BATCH_NOT_READY`（操作 `error_code` 显示为乱码如 `9h9h`，这是 SQLAlchemy 内部错误码泄漏）。SQLite 不检查 VARCHAR 宽度，所以本地开发与测试环境从未暴露该问题。r9 通过 alembic 迁移 `20260926_61` 将 `status` 与 `paused_from_status` 加宽到 `VARCHAR(32)`；升级时 `migrate` 容器会自动执行。升级前已 `failed` 的回传批次不会自动恢复，请让标注员重新执行一次回传。

从 r4-r8 升级时，保留现有 `.env`、`secrets/` 和数据库，只覆盖源码并重建相关服务：

```bash
tar -xzf /path/to/linkraft-ubuntu-20260926-r9.tar.gz \
  --strip-components=1 -C ~/linkraft-ubuntu-20260924-r4
cd ~/linkraft-ubuntu-20260924-r4
./packaging/compose-ubuntu.sh up -d --build --force-recreate backend worker scheduler frontend annotator annotator-frontend
./packaging/compose-ubuntu.sh ps
```

## CPU Compatibility

The package fixes MinIO to `minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1` and mc to `minio/mc:RELEASE.2025-07-21T05-28-08Z-cpuv1`. Backend, worker, inference runtime, TensorBoard gateway, migration, and MLflow use package-specific `python:3.11-slim-bookworm` Dockerfiles instead of Wolfi, so the prior `CPU does not support x86-64-v2` failure is avoided. The frontend and annotator frontend builds use package-specific Debian Node 20 Dockerfiles with npm retries; their default registry is npmmirror. Set `PIP_INDEX_URL` and/or `NPM_REGISTRY` before installation to use different mirrors. `--resume-retries` is intentionally absent because the target pip version rejects that option.

Before installation, verify the exact image names on the target server:

```bash
docker image inspect minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1 \
  minio/mc:RELEASE.2025-07-21T05-28-08Z-cpuv1
```

If the images are stored in an approved private registry, pull them there and tag them with the two names above, or load an offline image archive provided by your administrator. Do not retag them to `latest` or use a newer MinIO release on this legacy-CPU host.

## Operations

```bash
./packaging/compose-ubuntu.sh ps
./packaging/compose-ubuntu.sh logs -f backend worker
./packaging/compose-ubuntu.sh restart
./packaging/uninstall-ubuntu.sh
./packaging/compose-ubuntu.sh down -v  # permanently deletes volumes; use only when data removal is intended
```

After rebuilding the `annotator` gateway, restart `annotator-frontend` because nginx resolves the upstream container address when it starts:

```bash
./packaging/compose-ubuntu.sh restart annotator-frontend
```

To repair upload errors caused by an existing root-owned bind mount without reinstalling:

```bash
./packaging/prepare-production-storage.sh
./packaging/compose-ubuntu.sh restart backend
```

If an r4, r5, r6, or r7 deployment returns `MODEL_CONVERSION_FAILED` when registering an XGBoost AutoML result, update the existing deployment directory without replacing `.env`, `secrets/`, or database files, then rebuild the Python services:

```bash
tar -xzf /path/to/linkraft-ubuntu-20260926-r9.tar.gz \
  --strip-components=1 -C ~/linkraft-ubuntu-20260924-r4
cd ~/linkraft-ubuntu-20260924-r4
./packaging/compose-ubuntu.sh up -d --build --force-recreate backend worker scheduler
./packaging/compose-ubuntu.sh ps backend worker scheduler
```

The r8 and later worker imports ONNX/XGBoost binary extensions before applying its Linux address-space limit. Existing model artifacts do not need to be retrained; retry registration after the rebuilt `backend` container is healthy.

If an r4, r5, r6, or r7 deployment reports a MinIO health-check problem, deploy r8 or later, or copy the r9 `packaging/docker-compose.legacy-cpu.yml` first. The CPUv1 server image does not provide the `mc` health-check command; r8 uses the server's HTTP readiness endpoint and keeps bucket creation in the separate `minio-init` mc container:

```bash
./packaging/compose-ubuntu.sh up -d --force-recreate minio minio-init
./packaging/compose-ubuntu.sh up -d --remove-orphans
```

To rebuild the archive from this source tree, run `./packaging/build-package.sh 20260926-r9`.
