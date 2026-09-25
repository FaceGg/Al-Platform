# Linkraft Ubuntu Installation

## Requirements

- Ubuntu 22.04 or 24.04 LTS, 4 vCPU, 8 GB RAM, and at least 40 GB free disk.
- Docker Engine 24+ and Docker Compose v2.24.4+ (the package override uses `!override` for port replacement). The deployment user must be able to run `docker`.
- Firewall or cloud security-group access to TCP `5175` (main platform) and `8443` (annotator portal). Docker Hub, GHCR, and the configured Python package mirror must be reachable for the first build.
- The deployment Docker daemon must be able to obtain the exact CPUv1 MinIO images below, or they must be preloaded with these exact names. The installer never substitutes `latest`; if Docker Hub returns `pull access denied`, configure your approved registry/mirror or import the supplied image tar files before installation.

## Install

```bash
tar -xzf linkraft-ubuntu-20260925-r5.tar.gz
cd linkraft-ubuntu-20260925-r5
chmod +x packaging/*.sh ml-platform/scripts/prepare-production-secrets.sh
PUBLIC_ORIGIN=http://SERVER_PUBLIC_IP:5175 ./packaging/install-ubuntu.sh
```

The installer uses `packaging/docker-compose.legacy-cpu.yml` through `packaging/compose-ubuntu.sh`. `PUBLIC_ORIGIN` must be the exact browser origin used to open the platform, without a trailing path; it is written to `FRONTEND_ORIGIN` and passed into the backend container. For additional exact origins, pass comma-separated `PUBLIC_ORIGIN_ALIASES`, for example `PUBLIC_ORIGIN_ALIASES=http://SERVER_PUBLIC_IP:5173,http://127.0.0.1:5173`. If `.env` already exists, its secrets remain unchanged; an explicit `PUBLIC_ORIGIN` updates only the CORS origin setting. The script sets the main platform binding to `0.0.0.0:5175`, exposes the annotator portal at `0.0.0.0:8443`, creates `secrets/notification_master_key` when absent, repairs bind-mounted `data/` and `uploads/` ownership for UID/GID 1000, and starts the complete Compose stack. The CPUv1 MinIO server image does not include `mc`, so the legacy Compose profile disables the inherited server-side `mc ready local` check and lets the `minio-init` mc container retry readiness and bucket creation before dependent services start. The annotator frontend is built from its checked-in Node/Vite source during the image build; a pre-existing `dist/` directory is not required. The generated `.env` and `secrets/` directory contain credentials and must be backed up securely but never committed.

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

If an r4 deployment reports `minio is unhealthy` and its health log says `mc: executable file not found`, deploy r5 or copy the r5 `packaging/docker-compose.legacy-cpu.yml` first. The CPUv1 server image intentionally does not contain `mc`; r5 runs readiness and bucket creation from the separate `minio-init` mc container:

```bash
./packaging/compose-ubuntu.sh up -d --force-recreate minio minio-init
./packaging/compose-ubuntu.sh up -d --remove-orphans
```

To rebuild the archive from this source tree, run `./packaging/build-package.sh 20260925-r5`.
