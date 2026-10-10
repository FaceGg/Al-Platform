#!/usr/bin/env bash
# Week 13-17 acceptance evidence collector.
#
# Usage (WSL or Linux, from any directory):
#   ml-platform/backend/tools/acceptance/run_week13_17_acceptance.sh week13
#
# Environment:
#   PYTHON  python interpreter with the backend dependencies (default: python3)
#
# Runs the focused gates for the requested week profile and writes an evidence
# manifest bound to the current commit SHA. Every step records its exit code;
# a failed step marks the manifest failed without aborting the remaining
# steps, so partial evidence stays reviewable. failed/skipped never count as
# passed (repository verification rules).
set -u

WEEK="${1:-week13}"
PYTHON="${PYTHON:-python3}"
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_DIR="$(cd "$BACKEND_DIR/../.." && pwd)"
FRONTEND_DIR="$REPO_DIR/ml-platform/frontend"
SHA="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

case "$WEEK" in
  week13)
    EVIDENCE_DIR="$BACKEND_DIR/temp_test/week13-local"
    BACKEND_MODULES="tests/test_kubernetes_client.py tests/test_kubernetes_cluster_api.py tests/test_cloud_resource_migrations.py"
    WEEK_NUMBER="13"
    FRONTEND_TESTS="src/pages/KubernetesPage.test.tsx src/weekAcceptance.test.ts"
    ;;
  week14)
    EVIDENCE_DIR="$BACKEND_DIR/temp_test/week14-local"
    BACKEND_MODULES="tests/test_kubernetes_executor.py tests/test_kubernetes_job_api.py tests/test_kubernetes_recovery.py tests/test_kubernetes_logs.py"
    WEEK_NUMBER="14"
    FRONTEND_TESTS="src/pages/JobRunsPage.test.tsx src/weekAcceptance.test.ts"
    ;;
  week15)
    EVIDENCE_DIR="$BACKEND_DIR/temp_test/week15-local"
    BACKEND_MODULES="tests/test_notebook_api.py tests/test_image_catalog_api.py tests/test_image_build_security.py tests/test_gpu_scheduling.py"
    WEEK_NUMBER="15"
    FRONTEND_TESTS="src/pages/NotebookPage.test.tsx src/pages/ImageCatalogPage.test.tsx src/weekAcceptance.test.ts"
    ;;
  week16)
    EVIDENCE_DIR="$BACKEND_DIR/temp_test/week16-local"
    BACKEND_MODULES="tests/test_multi_cluster_scheduler.py tests/test_resource_governance.py tests/test_storage_mounts.py tests/test_cluster_observability.py"
    WEEK_NUMBER="16"
    FRONTEND_TESTS="src/pages/ClusterGovernancePage.test.tsx src/weekAcceptance.test.ts"
    ;;
  *)
    echo "unknown profile: $WEEK (supported: week13..week16; week17+ extend this case)" >&2
    exit 2
    ;;
esac

mkdir -p "$EVIDENCE_DIR"
LOG="$EVIDENCE_DIR/acceptance-$STAMP.log"
RESULTS="$EVIDENCE_DIR/acceptance-$STAMP.json"
export LOG
OVERALL="passed"

run_step() {
  local name="$1"; shift
  echo "=== $name ===" | tee -a "$LOG"
  ( "$@" ) >> "$LOG" 2>&1
  local code=$?
  echo "step: $name exit: $code" | tee -a "$LOG"
  if [ "$code" -ne 0 ]; then
    OVERALL="failed"
  fi
  return 0
}

: > "$LOG"
echo "week13-17 acceptance | profile=$WEEK | sha=$SHA | started=$STAMP" | tee -a "$LOG"

cd "$BACKEND_DIR"
run_step "backend_focused_tests" "$PYTHON" -m pytest $BACKEND_MODULES -q
run_step "backend_week_suite" "$PYTHON" run_suite.py --week "$WEEK_NUMBER"
run_step "backend_compileall" "$PYTHON" -m compileall -q app

ALEMBIC_DB="sqlite:///./temp_test/${WEEK}-local/alembic-check.db"
rm -f "./temp_test/${WEEK}-local/alembic-check.db"
DATABASE_URL="$ALEMBIC_DB" run_step "alembic_upgrade_head" "$PYTHON" -m alembic upgrade head
DATABASE_URL="$ALEMBIC_DB" run_step "alembic_check" "$PYTHON" -m alembic check

cd "$FRONTEND_DIR"
run_step "frontend_vitest" npx vitest run $FRONTEND_TESTS
run_step "frontend_tsc" npx tsc --noEmit
run_step "frontend_build" npm run build

cd "$REPO_DIR"
run_step "git_diff_check" git diff --check

STATUS="$OVERALL" LOG_BASENAME="$(basename "$LOG")" SHA="$SHA" WEEK="$WEEK" RESULTS="$RESULTS" "$PYTHON" - <<'PYEOF'
import datetime
import json
import os

manifest = {
    "week": os.environ["WEEK"],
    "sha": os.environ["SHA"],
    "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "status": os.environ["STATUS"],
    "log": os.environ["LOG_BASENAME"],
}
with open(os.environ["RESULTS"], "w", encoding="utf-8") as handle:
    json.dump(manifest, handle, indent=2)
print("manifest:", os.environ["RESULTS"], "status:", os.environ["STATUS"])
PYEOF

echo "OVERALL: $OVERALL (log: $LOG)"
[ "$OVERALL" = "passed" ] && exit 0 || exit 1
