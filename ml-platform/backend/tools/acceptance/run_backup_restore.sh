#!/bin/sh
set -eu

: "${DATABASE_URL:?DATABASE_URL is required}"
: "${MINIO_ACCESS_KEY:?MINIO_ACCESS_KEY is required}"
: "${MINIO_SECRET_KEY:?MINIO_SECRET_KEY is required}"

receipt=/evidence/backup
acceptance_tag="${ACCEPTANCE_RUN_TAG:-$(date -u +%Y%m%d%H%M%S)}"
restore_database="${DATABASE_URL%/*}/ml_platform_restore_${acceptance_tag}"
source_minio="source/ml-platform"
restore_minio="restore/ml-platform-restore-${acceptance_tag}"

if [ -e "$receipt" ]; then
  echo "backup receipt directory already exists: $receipt" >&2
  exit 1
fi
mkdir -p "$receipt"

export BACKUP_SOURCE_DATABASE_URL="$DATABASE_URL"
export BACKUP_ACCEPTANCE_ISOLATED=1
export BACKUP_ACCEPTANCE_MINIO_DESTINATION="$receipt/minio"
export RESTORE_SOURCE_DATABASE_URL="$DATABASE_URL"
export RESTORE_ACCEPTANCE_DATABASE_URL="$restore_database"
export RESTORE_ACCEPTANCE_ISOLATED=1
export RESTORE_SOURCE_MINIO="$source_minio"
export RESTORE_ACCEPTANCE_MINIO_DESTINATION="$restore_minio"
export BACKUP_RESTORE_EVIDENCE_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export MC_CONFIG_DIR=/tmp/minio-client
export PYTHONPATH=/app

command -v pg_dump >/dev/null
command -v pg_restore >/dev/null
command -v mc >/dev/null

# pg_restore requires the target database to exist; create it through a
# validated SQL identifier instead of interpolating an untrusted name.
python - "$restore_database" <<'PY'
import os
import sys

import psycopg
from sqlalchemy.engine import make_url
from psycopg import sql

target_url = make_url(sys.argv[1])
target = target_url.database or ""
source = make_url(os.environ["DATABASE_URL"])
if not target.startswith("ml_platform_restore_"):
    raise SystemExit("invalid restore database name")
admin = source.set(drivername="postgresql", database="postgres")
with psycopg.connect(admin.render_as_string(hide_password=False)) as connection:
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,))
        if cursor.fetchone() is None:
            cursor.execute(sql.SQL("CREATE DATABASE {}" ).format(sql.Identifier(target)))
PY

mc alias set source http://minio:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
mc alias set restore http://minio:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
if ! mc ls "$restore_minio" >/dev/null 2>&1; then
  mc mb "$restore_minio" >/dev/null
elif [ -n "$(mc ls --recursive "$restore_minio")" ]; then
  echo "restore bucket is not empty: $restore_minio" >&2
  exit 1
fi

python tools/acceptance/seed_backup_fixture.py
printf '%s\n' '{"fixture":"backup","payload":"retained"}' > /tmp/backup-fixture.json
mc cp /tmp/backup-fixture.json "$source_minio/acceptance/backup-fixture.json" >/dev/null

python tools/backup_restore.py backup-postgres \
  --database-url-env BACKUP_SOURCE_DATABASE_URL \
  --output "$receipt/postgres.dump"
python tools/backup_restore.py backup-minio \
  --source "$source_minio" \
  --destination "$receipt/minio" \
  --receipt-dir "$receipt"
python tools/backup_restore.py manifest --root "$receipt"
python tools/backup_restore.py restore-postgres --dump "$receipt/postgres.dump"
python tools/backup_restore.py restore-minio \
  --source "$receipt/minio" \
  --destination "$restore_minio" \
  --receipt-dir "$receipt"
python tools/backup_restore.py verify \
  --source-database-env RESTORE_SOURCE_DATABASE_URL \
  --restored-database-env RESTORE_ACCEPTANCE_DATABASE_URL \
  --source-minio-env RESTORE_SOURCE_MINIO \
  --manifest "$receipt/manifest.json" \
  --restored-bucket "$restore_minio" \
  --output "$receipt/restore-result.json"
