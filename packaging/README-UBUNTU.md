# Linkraft Ubuntu Installation

## Requirements

- Ubuntu 22.04 or 24.04 LTS, 4 vCPU, 8 GB RAM, and at least 40 GB free disk.
- Docker Engine 24+ and Docker Compose v2. The deployment user must be able to run `docker`.
- Firewall or cloud security-group access to TCP `5175`. Docker Hub, GHCR, and the configured Python package mirror must be reachable for the first build.

## Install

```bash
tar -xzf linkraft-ubuntu-20260909.tar.gz
cd linkraft-ubuntu-20260909
chmod +x packaging/*.sh ml-platform/scripts/prepare-production-secrets.sh
./packaging/install-ubuntu.sh
```

The installer creates `.env` only when it does not exist, preserves an existing `.env`, sets `NGINX_PORT=5175`, creates `secrets/notification_master_key` when absent, and starts the complete Compose stack. The generated `.env` and `secrets/` directory contain credentials and must be backed up securely but never committed.

Access the platform at `http://SERVER_PUBLIC_IP:5175/`. If UFW is enabled, run `sudo ufw allow 5175/tcp`. Backend port 8000, frontend port 5173, and MinIO ports 9000/9001 remain local-only by default.

## CPU Compatibility

The package fixes MinIO to `RELEASE.2025-07-23T15-54-02Z-cpuv1` and `mc` to `RELEASE.2025-07-21T05-28-08Z-cpuv1`. Backend, worker, inference runtime, TensorBoard gateway, and MLflow use `python:3.11-slim-bookworm` instead of Wolfi, so the prior `CPU does not support x86-64-v2` failure is avoided.

## Operations

```bash
docker compose ps
docker compose logs -f backend worker
docker compose restart
./packaging/uninstall-ubuntu.sh
docker compose down -v  # permanently deletes volumes; use only when data removal is intended
```

To rebuild the archive from this source tree, run `./packaging/build-package.sh 20260909`.
