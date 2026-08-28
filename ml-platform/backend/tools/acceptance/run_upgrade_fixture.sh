#!/bin/sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"

receipt=/evidence/upgrade
acceptance_tag="${ACCEPTANCE_RUN_TAG:-$(date -u +%Y%m%d%H%M%S)}"
upgrade_database="${DATABASE_URL%/*}/ml_platform_upgrade_${acceptance_tag}"

if [ -e "$receipt" ]; then
  echo "upgrade receipt directory already exists: $receipt" >&2
  exit 1
fi
mkdir -p "$receipt"

export UPGRADE_ACCEPTANCE_DATABASE_URL="$upgrade_database"
export UPGRADE_ACCEPTANCE_ISOLATED=1

# Alembic must connect to a real, empty target database before creating the
# supported N-1 fixture. Use a validated identifier for CREATE DATABASE.
python - "$upgrade_database" <<'PY'
import os
import sys

import psycopg
from psycopg import sql
from sqlalchemy.engine import make_url

target_url = make_url(sys.argv[1])
target = target_url.database or ""
source = make_url(os.environ["DATABASE_URL"])
if not target.startswith("ml_platform_upgrade_"):
    raise SystemExit("invalid upgrade database name")
admin = source.set(drivername="postgresql", database="postgres")
with psycopg.connect(admin.render_as_string(hide_password=False)) as connection:
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,))
        if cursor.fetchone() is None:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
PY

python tools/upgrade_fixture.py create \
  --revision 20260720_10_security_notifications \
  --output "$receipt/create.json"
python tools/upgrade_fixture.py seed --output "$receipt/seed.json"
python tools/upgrade_fixture.py snapshot --output "$receipt/before.json"
python tools/upgrade_fixture.py upgrade \
  --target 20260826_13 \
  --output "$receipt/result.json"

export DATABASE_URL="$upgrade_database"
python - "$receipt/smoke.json" <<'PY'
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.tasks.celery_app import celery_app

with TestClient(app) as client:
    health = client.get("/api/health", timeout=15)
    readiness = client.get("/api/ready", timeout=15)
worker_ping = celery_app.control.ping(timeout=10)
result = {
    "status": "passed"
    if health.status_code == 200
    and health.json().get("status") == "ok"
    and readiness.status_code == 200
    and readiness.json().get("database", {}).get("ready") is True
    and bool(worker_ping)
    else "failed",
    "api_health_status": health.status_code,
    "api_ready_status": readiness.status_code,
    "database_ready": readiness.json().get("database", {}).get("ready"),
    "worker_replies": len(worker_ping),
}
Path(sys.argv[1]).write_text(
    json.dumps(result, ensure_ascii=True, sort_keys=True) + "\n",
    encoding="utf-8",
)
raise SystemExit(0 if result["status"] == "passed" else 1)
PY
