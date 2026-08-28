#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/../../../.." && pwd)"
PROJECT="${COMPOSE_PROJECT_NAME:?COMPOSE_PROJECT_NAME is required}"
EVIDENCE="${ML_PLATFORM_EVIDENCE_DIR:?ML_PLATFORM_EVIDENCE_DIR is required}"
PERFORMANCE="$EVIDENCE/performance"
BACKEND="${PROJECT}-backend-1"
WORKER="${PROJECT}-worker-1"
REDIS="${PROJECT}-redis-1"
POSTGRES="${PROJECT}-postgres-1"
CONTEXT=/tmp/week11-perf-context.json
CONTAINER_PERFORMANCE=/tmp/week11-performance
COMPOSE=(docker compose --project-name "$PROJECT")
COMMIT="${ACCEPTANCE_SOURCE_COMMIT:-$(git -C "$ROOT" rev-parse HEAD)}"

cleanup() {
  set +e
  docker start "$WORKER" >/dev/null 2>&1 || true
  rm -f "$CONTEXT"
}

on_exit() {
  status=$?
  docker cp "$BACKEND:$CONTAINER_PERFORMANCE/." "$PERFORMANCE" >/dev/null 2>&1 || true
  if [ "$status" -ne 0 ] && [ -d "$PERFORMANCE" ]; then
    "${COMPOSE[@]}" ps -a > "$PERFORMANCE/compose-ps-failure.txt" 2>&1 || true
    "${COMPOSE[@]}" logs --no-color --tail 200 > "$PERFORMANCE/compose-logs-failure.txt" 2>&1 || true
    docker logs --tail 200 "$BACKEND" > "$PERFORMANCE/backend-failure.log" 2>&1 || true
  fi
  cleanup
  exit "$status"
}
trap on_exit EXIT

if [ -e "$PERFORMANCE" ]; then
  echo "performance evidence already exists: $PERFORMANCE" >&2
  exit 1
fi
mkdir -p "$PERFORMANCE"

export INFERENCE_RATE_LIMIT_CAPACITY=20000
export INFERENCE_RATE_LIMIT_REFILL_PER_SECOND=10000
export INFERENCE_ROLLOUT_OBSERVATION_SECONDS=60
"${COMPOSE[@]}" up -d --force-recreate inference-runtime backend worker scheduler

for _ in $(seq 1 90); do
  if "${COMPOSE[@]}" exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
"${COMPOSE[@]}" exec -T backend python -c "import json,urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3))['status'] == 'ok'"

docker cp "$ROOT/ml-platform/backend/tools/acceptance/prepare_performance_fixture.py" "$BACKEND:/tmp/prepare_performance_fixture.py"
docker exec -w /app -e PYTHONPATH=/app "$BACKEND" python /tmp/prepare_performance_fixture.py >/dev/null
docker cp "$BACKEND:/tmp/week11-perf-context.json" "$CONTEXT"
chmod 600 "$CONTEXT"

API_KEY="$(python3 -c "import json; print(json.load(open('$CONTEXT'))['api_key'])")"
BEARER="$(python3 -c "import json; print(json.load(open('$CONTEXT'))['bearer'])")"
DEPLOYMENT="$(python3 -c "import json; print(json.load(open('$CONTEXT'))['deployment_id'])")"
WORKFLOW="$(python3 -c "import json; print(json.load(open('$CONTEXT'))['workflow_id'])")"

docker exec "$BACKEND" mkdir -p "$CONTAINER_PERFORMANCE"

for iteration in 1 2 3; do
  docker exec -e ACCEPTANCE_SOURCE_COMMIT="$COMMIT" -e PERF_BEARER="$BEARER" "$BACKEND" \
    python -m tools.week11_performance run \
      --url http://127.0.0.1:8000/api/projects \
      --scenario core-read --iteration "$iteration" \
      --concurrency 20 --requests-per-worker 100 \
      --bearer-env PERF_BEARER \
      --output "$CONTAINER_PERFORMANCE/core-read-${iteration}.json"
done

for iteration in 1 2 3; do
  docker exec -e ACCEPTANCE_SOURCE_COMMIT="$COMMIT" -e PERF_API_KEY="$API_KEY" "$BACKEND" \
    python -m tools.week11_performance run \
      --url "http://127.0.0.1:8000/api/v1/inference/${DEPLOYMENT}/predict" \
      --scenario warm-inference --iteration "$iteration" \
      --concurrency 20 --requests-per-worker 100 --method POST \
      --body-file /tmp/week11-inference-body.json --api-key-env PERF_API_KEY \
      --output "$CONTAINER_PERFORMANCE/warm-inference-${iteration}.json"
done

docker stop "$WORKER" >/dev/null
for iteration in 1 2 3; do
  docker exec -e ACCEPTANCE_SOURCE_COMMIT="$COMMIT" -e PERF_BEARER="$BEARER" "$BACKEND" \
    python -m tools.week11_performance run \
      --url "http://127.0.0.1:8000/api/workflows/${WORKFLOW}/run" \
      --scenario enqueue --iteration "$iteration" \
      --concurrency 20 --requests-per-worker 100 --method POST \
      --bearer-env PERF_BEARER \
      --output "$CONTAINER_PERFORMANCE/enqueue-${iteration}.json"
done
docker exec "$REDIS" redis-cli DEL celery >/dev/null
docker exec "$POSTGRES" psql -U ml_platform -d ml_platform -c \
  "update workflow_runs set status='cancelled', finished_at=now() where status='pending';" >/dev/null
docker start "$WORKER" >/dev/null
sleep 5

docker exec -e PERF_BEARER="$BEARER" -e PERF_DEPLOYMENT="$DEPLOYMENT" "$BACKEND" \
  python -c "import os,urllib.request; request=urllib.request.Request('http://127.0.0.1:8000/api/inference-deployments/'+os.environ['PERF_DEPLOYMENT']+'/stop', method='POST', headers={'Authorization':'Bearer '+os.environ['PERF_BEARER']}); urllib.request.urlopen(request, timeout=30).read()"
docker exec -e ACCEPTANCE_SOURCE_COMMIT="$COMMIT" -e PERF_BEARER="$BEARER" "$BACKEND" \
  python -m tools.week11_performance run \
    --url "http://127.0.0.1:8000/api/inference-deployments/${DEPLOYMENT}/start" \
    --scenario cold-model-load --iteration 1 \
    --concurrency 1 --requests-per-worker 1 --method POST \
    --bearer-env PERF_BEARER \
    --output "$CONTAINER_PERFORMANCE/cold-model-load-1.json"

docker exec -e ACCEPTANCE_SOURCE_COMMIT="$COMMIT" -e PERF_BEARER="$BEARER" "$BACKEND" \
  python -m tools.week11_performance run \
    --url "http://127.0.0.1:8000/api/workflows/${WORKFLOW}/run" \
    --scenario welding-e2e --iteration 1 \
    --concurrency 1 --requests-per-worker 10 --method POST \
    --bearer-env PERF_BEARER \
    --completion-url-template "http://127.0.0.1:8000/api/runs/{run_id}" \
    --completion-timeout 90 \
    --output "$CONTAINER_PERFORMANCE/welding-e2e-1.json"

docker exec -e ACCEPTANCE_SOURCE_COMMIT="$COMMIT" "$BACKEND" \
  python -m tools.week11_performance summarize \
    --input-dir "$CONTAINER_PERFORMANCE" --output "$CONTAINER_PERFORMANCE/summary.json"
