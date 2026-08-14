# Week 9-12 High-Risk Remediation and Release Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every verified Week 9-12 security and acceptance blocker with reproducible evidence, then publish only a commit set whose local and remote checks pass.

**Architecture:** Preserve the existing fail-closed security contracts. Fix the evidence-manifest fixture so it supplies valid scanner receipts before testing weakened-command rejection; diagnose the fixed-resource rate-limit failure at every Compose/configuration/Redis boundary before changing production code. Build each production image from the same source commit and immutable Wolfi base, bind image IDs and OCI revision labels to scanner receipts, and make the release manifest reject any incomplete or mismatched evidence.

**Tech Stack:** PowerShell 7, WSL2, Docker Compose, Chainguard Wolfi, Python 3.11, FastAPI, Redis Lua, PostgreSQL, MinIO, Playwright/Chromium, Trivy 0.73.0, pip-audit, Bandit, Gitleaks, `unittest`, Vitest, GitHub Actions.

---

## Working-tree and commit policy

- Treat the user's explicit “all changes must be committed” instruction as applying to all intentional source, configuration, test, documentation, and safe acceptance-summary changes in this worktree, including `ml-platform/frontend/src/pages/ModelLibraryPage.test.tsx`.
- Do not run `git add -A`. `tmp/npm-cache/`, `tmp/pip-cache/`, and `tmp/security-20260810/` are generated dependency caches/raw scanner output (about 1.18 GiB combined), are not source artifacts, and can contain registry metadata or redaction-sensitive evidence. Keep them local; commit reviewed, redacted summaries instead.
- `temp_test/acceptance-20260810/` is ignored by repository policy. Before any evidence is committed, copy only a reviewed, relative-path, credential-free summary into `docs/security/`; do not force-add `.wslconfig` backups, raw service logs, request payloads, or generated credentials.
- Every commit must pass `git diff --cached --check`, list staged paths explicitly, and use no force push or history rewrite. The shared `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md` is outside this Git worktree: update it per `AGENTS.md`, but it cannot be included in a repository commit.

## File responsibility map

| File or area | Responsibility |
| --- | --- |
| `ml-platform/backend/tests/test_evidence_manifest.py` | Creates semantically valid scanner fixtures, then proves altered security commands are rejected by the manifest. |
| `ml-platform/backend/tools/security_scans.py` | Validates scanner commands, raw reports, all four production image receipts, OCI revision, and source-commit provenance before emitting a passed summary. |
| `ml-platform/backend/tools/evidence_manifest.py` | Rejects incomplete, unsafe, stale, or failed acceptance evidence with stable error codes. |
| `ml-platform/backend/tests/test_week12_security_gates.py` | Contract coverage for fail-closed scanner, report, source-commit, image, and React Router audit behavior. |
| `.github/workflows/ci.yml` and `tests/test_ci_workflow.py` | Build all four labeled production images and pass their references/source commit through security summarization in CI. |
| `ml-platform/backend/Dockerfile*` and `requirements.txt` | Use the single pinned Wolfi reference, non-root app user, compatible Python runtime and audited dependency set. |
| `ml-platform/backend/tests/test_image_security_contracts.py` | Enforces shared immutable base, non-root runtime and supported package pins. |
| `ml-platform/backend/tests/test_inference_production_stack.py` plus `temp_test/acceptance-20260810/` scripts | Reproduces fixed-resource rate limiting and captures boundary diagnostics without changing production behavior speculatively. |
| `docs/security/` | Holds reviewed pinned-base and final redacted acceptance manifest/report; never raw secrets or cache output. |
| `DEVELOPMENT_PLAN.md` and `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md` | Append observed behavior, verified root cause, solution, verification, prevention and remaining release gates. |

## Task 1: Freeze a reviewed remediation checkpoint

**Files:**
- Create: `docs/superpowers/plans/2026-08-13-week9-12-high-risk-remediation-closure.md`
- Modify: `DEVELOPMENT_PLAN.md`

- [ ] **Step 1: Record current branch, ancestry, dirty paths, and generated-artifact classification.**

Run from the linked worktree:

```powershell
$Root = 'E:\codex_workspace\agent_spot_welding\.worktrees\week9-12-mlops-core'
git -C $Root status --short --branch
git -C $Root rev-list --left-right --count origin/main...HEAD
Get-ChildItem "$Root\tmp\npm-cache", "$Root\tmp\pip-cache", "$Root\tmp\security-20260810" -Force -ErrorAction SilentlyContinue |
  Select-Object FullName, Length, LastWriteTime
```

Expected: branch and user/test changes remain visible; no cache/raw scanner directory is staged.

- [ ] **Step 2: Append a plan-frozen checkpoint to `DEVELOPMENT_PLAN.md`.**

Append only a dated record that names the two reproduced blockers: invalid semantic scanner fixture causing `KeyError` in `test_generate_rejects_weakened_security_scan_commands`, and fixed-resource rate-limit evidence returning `200` where `429` is required. State that neither blocker is closed by this checkpoint.

- [ ] **Step 3: Self-review the plan and checkpoint.**

Run a literal-pattern scan whose patterns are assembled at runtime so the scan command itself is not a false positive:

```powershell
$Plan = Join-Path $Root 'docs\superpowers\plans\2026-08-13-week9-12-high-risk-remediation-closure.md'
$Patterns = @('TO'+'DO', 'T'+'BD', 'implement later', 'fill in details', 'appropriate error handling')
foreach ($Pattern in $Patterns) {
  if (Select-String -LiteralPath $Plan -Pattern $Pattern -Quiet) { throw "Placeholder found: $Pattern" }
}
git -C $Root diff --check
```

Expected: no placeholder match and no whitespace error.

- [ ] **Step 4: Commit the planning checkpoint.**

```powershell
git -C $Root add -- `
  docs/superpowers/plans/2026-08-13-week9-12-high-risk-remediation-closure.md `
  DEVELOPMENT_PLAN.md
git -C $Root diff --cached --check
git -C $Root diff --cached --stat
git -C $Root commit -m "docs(week12): plan high-risk closure"
```

Expected: one documentation-only commit; no raw evidence or cache path appears in `git diff --cached --name-only`.

## Task 2: Repair evidence-manifest weakened-command regression fixture

**Files:**
- Modify: `ml-platform/backend/tests/test_evidence_manifest.py`
- Verify: `ml-platform/backend/tools/security_scans.py`, `ml-platform/backend/tools/evidence_manifest.py`

- [ ] **Step 1: Reproduce and characterize the current failure.**

```powershell
Set-Location "$Root\ml-platform\backend"
$env:PYTHONPATH = '.'
& 'C:\Users\17723\miniconda3\python.exe' -m unittest `
  tests.test_evidence_manifest.EvidenceManifestTests.test_generate_rejects_weakened_security_scan_commands -v
```

Expected RED: subtests fail with `KeyError: 'command'` or `KeyError: 'images'`, proving fixture summary was downgraded before mutation.

- [ ] **Step 2: Trace the fixture-to-summary data flow before editing.**

Inspect `_write_security_evidence`, `summarize_scans`, `_raw_scan_report_error`, `is_required_scan_command`, and `generate`. For each gate record the exact required receipt shape, raw report file, command flags, return code, image ID, image artifact name, OCI revision, and expected source commit. Do not weaken production validation to accommodate a test fixture.

- [ ] **Step 3: Make the fixture produce a valid baseline receipt.**

Use one helper which writes a raw report and a corresponding receipt. The emitted structure must satisfy the production contract before the test mutates it:

```python
receipt = {
    "status": "passed",
    "returncode": 0,
    "command": required_command,
}
# container_image additionally uses source_commit and four ordered images:
image_receipt = {
    "component": component,
    "reference": reference,
    "evidence_path": report_name,
    "image_id": image_id,
    "revision": self._COMMIT,
    "command": trivy_command,
    "returncode": 0,
    "status": "passed",
}
```

The matching raw Trivy reports must expose `ArtifactName == reference` and `Metadata.ImageID == image_id`; all non-container raw reports must use the real scanner result schema expected by `_raw_scan_report_error`.

- [ ] **Step 4: Verify baseline semantic evidence before weakened-command mutations.**

Add a focused assertion inside the test fixture path:

```python
summary = summarize_scans(root / "security", root / "security" / "summary.json", source_commit=self._COMMIT)
self.assertEqual(summary["status"], "passed")
self.assertEqual(summary["gates"]["container_image"]["status"], "passed")
```

Run the new focused baseline test. Expected GREEN: the fixture contains every command/image field that the mutation loop accesses.

- [ ] **Step 5: Mutate exactly one semantic command field per subtest and verify manifest rejection.**

For Bandit remove `-lll`; for Trivy weaken `--severity HIGH,CRITICAL` or remove `--exit-code 1`; for the first container image perform the same mutations. Re-run `summarize_scans`, then call `generate`; assert the stable manifest error is the scanner-receipt failure, not an accidental `KeyError`.

- [ ] **Step 6: Run focused security regression and commit.**

```powershell
& 'C:\Users\17723\miniconda3\python.exe' -m unittest `
  tests.test_evidence_manifest tests.test_week12_security_gates tests.test_ci_workflow -v
& 'C:\Users\17723\miniconda3\python.exe' -m compileall -q app tools tests
git -C $Root diff --check
git -C $Root add -- ml-platform/backend/tests/test_evidence_manifest.py
git -C $Root diff --cached --check
git -C $Root commit -m "test(security): repair manifest scanner fixture"
```

Expected: the original subtest reports expected manifest rejection for every weakened command.

## Task 3: Diagnose the fixed-resource rate-limit failure before a fix

**Files:**
- Modify only if diagnosis proves a product defect: `ml-platform/backend/app/services/inference_rate_limit.py` or `ml-platform/backend/app/api/inference_production.py`, plus the focused regression test that proves the defect
- Modify: `ml-platform/backend/tests/test_inference_production_stack.py` only for a durable regression test
- Generate local-only: `temp_test/acceptance-20260810/performance/`

- [ ] **Step 1: Reproduce in one isolated WSL Compose lifecycle.**

Use a unique Compose project, ports, database, bucket, and Redis namespace. Start, execute rate-limit test, collect diagnostics, and tear down in the same `bash -lc` invocation. Never touch an existing Compose project.

```bash
set -Eeuo pipefail
ROOT=/mnt/e/codex_workspace/agent_spot_welding/.worktrees/week9-12-mlops-core
PERF="$ROOT/temp_test/acceptance-20260810/performance"
PROJECT=spot-welding-rate-limit-20260813
OVERRIDE="$PERF/compose-rate-limit-diagnostic-20260813.yml"
cat > "$OVERRIDE" <<'YAML'
services:
  migrate:
    image: codex-week12-final-backend:latest
  backend:
    image: codex-week12-final-backend:latest
  worker:
    image: codex-week12-final-worker:latest
  scheduler:
    image: codex-week12-final-worker:latest
  inference-runtime:
    image: codex-week12-final-inference:latest
  tensorboard-gateway:
    image: codex-week12-final-tensorboard:latest
YAML
compose() { docker compose -f "$ROOT/docker-compose.yml" -f "$OVERRIDE" --project-name "$PROJECT" "$@"; }
trap 'compose down --volumes --remove-orphans' EXIT
compose up --detach --wait postgres redis minio minio-init mlflow tensorboard-gateway inference-runtime migrate backend worker scheduler
  compose exec -T -e RUN_INFERENCE_INTEGRATION=1 \
  -e INFERENCE_INTEGRATION_CONTEXT_PATH=/tmp/inference-lifecycle-context.json \
  -e INFERENCE_RATE_LIMIT_CAPACITY=5 \
  -e INFERENCE_RATE_LIMIT_REFILL_PER_SECOND=0.001 \
  backend python -m unittest tests.test_inference_production_stack.TestInferenceProductionStack.test_rollout_key_restart_and_rollback -v
```

Expected RED: record the current sixth-response status without changing code.

- [ ] **Step 2: Collect configuration and state at each boundary.**

Before request 1 and after every request record, in a redacted local diagnostic log:

```bash
compose exec -T backend sh -lc 'env | grep "^INFERENCE_RATE_LIMIT_"'
compose exec -T backend python -c 'from app.config import settings; print(settings.inference_rate_limit_capacity, settings.inference_rate_limit_refill_per_second)'
compose exec -T backend python - <<'PY'
import json
import os
from pathlib import Path
from redis import Redis

context = json.loads(Path("/tmp/inference-lifecycle-context.json").read_text())
key_id = context["api_key_id"]
deployment_id = context["deployment_id"]
key = f"inference:{deployment_id}:{key_id}"
client = Redis.from_url(os.environ["REDIS_EVENTS_URL"], decode_responses=True)
print(json.dumps({"key": key, "state": client.hgetall(key)}, sort_keys=True))
PY
docker inspect --format '{{.Image}} {{index .Config.Labels "org.opencontainers.image.revision"}}' "${PROJECT}-backend-1"
```

The existing test context contains only the deployment ID and plaintext key. Add a diagnostic-only context field containing the created record ID (UUID) and an array of response status codes; never persist plaintext. The rate-limit key is then exactly `inference:{deployment_id}:{api_key_id}`. Record actual image IDs, Compose override image entries, request sequence, Redis key, token count and timestamp. Do not log full API keys or secrets.

- [ ] **Step 3: Form and minimally test one hypothesis.**

Only after diagnostic evidence identifies a boundary mismatch, write the smallest failing regression test. Examples of valid hypotheses are: Compose runs the wrong image, environment overrides do not reach the runtime, request keys differ, or the Lua update permits an extra token. Change one variable only and prove the test fails for the exact observed reason.

- [ ] **Step 4: Apply the minimal root-cause fix and verify GREEN.**

Keep Redis failure behavior fail-closed with `RATE_LIMIT_BACKEND_UNAVAILABLE`. Re-run the focused production-stack rate-limit test and confirm capacity requests return `200`, the next request returns `429`, and retry-after remains valid.

- [ ] **Step 5: Run relevant regressions and commit.**

```powershell
Set-Location "$Root\ml-platform\backend"
& 'C:\Users\17723\miniconda3\python.exe' -m unittest `
  tests.test_inference_production_stack tests.test_inference_production_api tests.test_week9_inference -v
git -C $Root diff --check
git -C $Root add -- `
  ml-platform/backend/app/services/inference_rate_limit.py `
  ml-platform/backend/app/api/inference_production.py `
  ml-platform/backend/tests/test_inference_rate_limit.py `
  ml-platform/backend/tests/test_inference_production_stack.py
git -C $Root diff --cached --check
git -C $Root commit -m "fix(inference): enforce Redis rate-limit capacity"
```

Expected: no commit occurs if the cause is external image/config drift; in that case commit only a durable test/script correction with documented evidence.

## Task 4: Validate production image runtime compatibility

**Files:**
- Modify: `ml-platform/backend/Dockerfile`
- Modify: `ml-platform/backend/Dockerfile.worker`
- Modify: `ml-platform/backend/Dockerfile.inference`
- Modify: `ml-platform/backend/Dockerfile.tensorboard`
- Modify: `ml-platform/backend/requirements.txt`
- Modify: `ml-platform/backend/tests/test_image_security_contracts.py`

- [ ] **Step 1: Add/confirm contract coverage before changing image behavior.**

The test must require all four first `FROM` lines to equal the approved digest, require `USER 1000:1000`, require a non-root `app` account/home directory when package installation writes user state, and require the approved direct pins:

```python
for dockerfile in DOCKERFILES:
    text = dockerfile.read_text(encoding="utf-8")
    self.assertIn("USER 1000:1000", text)
    self.assertIn("ENV HOME=/home/app", text)
self.assertIn("cryptography==50.0.*", requirements)
self.assertIn("setuptools==80.10.2", requirements)
```

Run this contract before implementation if coverage is missing; expected RED must identify the absent security behavior rather than a syntax error.

- [ ] **Step 2: Build every image without cache from the current source commit.**

```powershell
wsl.exe -e bash -lc 'set -euo pipefail
cd /mnt/e/codex_workspace/agent_spot_welding/.worktrees/week9-12-mlops-core/ml-platform/backend
for spec in backend:Dockerfile worker:Dockerfile.worker inference:Dockerfile.inference tensorboard:Dockerfile.tensorboard; do
  name=${spec%%:*}; dockerfile=${spec#*:}
  docker build --pull --no-cache \
    --label org.opencontainers.image.revision="'"$(git rev-parse HEAD)"'" \
    -t "codex-week12-final-${name}:latest" -f "$dockerfile" .
done'
```

Expected: four build IDs captured from exactly the current commit; registry/network failure is recorded as blocked, never passed.

- [ ] **Step 3: Execute image runtime smoke checks as non-root.**

```bash
for image in codex-week12-final-backend:latest codex-week12-final-worker:latest codex-week12-final-inference:latest codex-week12-final-tensorboard:latest; do
  docker run --rm --entrypoint sh "$image" -lc 'id -u; test "$(id -u)" = 1000; test "$HOME" = /home/app; python3.11 --version'
done
```

Expected: all images prove UID 1000 and a writable application home; service-specific health checks are executed in the later Compose gate.

- [ ] **Step 4: Run contracts and commit image/runtime changes.**

```powershell
Set-Location "$Root\ml-platform\backend"
& 'C:\Users\17723\miniconda3\python.exe' -m unittest tests.test_image_security_contracts -v
git -C $Root diff --check
git -C $Root add -- ml-platform/backend/Dockerfile* ml-platform/backend/requirements.txt ml-platform/backend/tests/test_image_security_contracts.py
git -C $Root diff --cached --check
git -C $Root commit -m "build(security): harden Wolfi production images"
```

## Task 5: Scan the complete production image set and generate valid receipts

**Files:**
- Modify: `ml-platform/backend/tools/security_scans.py`
- Modify: `ml-platform/backend/tests/test_week12_security_gates.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `ml-platform/backend/tests/test_ci_workflow.py`
- Generate reviewed only: `docs/security/acceptance-20260813-manifest.json`, `docs/security/acceptance-20260813-report.md`

- [ ] **Step 1: Add fail-closed tests for all four image receipts.**

Add a test that removes one receipt, changes one `ArtifactName`, changes one `Metadata.ImageID`, or changes one OCI revision. It must assert `SECURITY_EVIDENCE_INVALID` and never silently downgrade a required image to optional. Verify RED against the previous behavior if the test describes a new gap.

- [ ] **Step 2: Scan images with the same database and threshold.**

```powershell
wsl.exe -e bash -lc 'set -euo pipefail
out=/mnt/e/codex_workspace/agent_spot_welding/.worktrees/week9-12-mlops-core/temp_test/security-20260813
mkdir -p "$out"
for image in backend worker inference tensorboard; do
  docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache \
    aquasec/trivy:0.73.0 image --skip-db-update --exit-code 1 \
    --severity HIGH,CRITICAL --format json \
    --output "$out/trivy-image-${image}.json" "codex-week12-final-${image}:latest"
done'
```

Expected: each command exits zero and each JSON has zero HIGH/CRITICAL. A nonzero scan blocks promotion.

- [ ] **Step 3: Run complete security tool chain from current source.**

Run `tools.security_scans all` with the pinned image receipt list and source commit, plus raw `pip-audit`, Trivy filesystem, Bandit, official npm registry audit, and scoped no-git Gitleaks. Preserve raw output under ignored `temp_test`; produce a redacted, relative-path manifest only after all gates pass.

- [ ] **Step 4: Run scanner/CI contract suite and commit.**

```powershell
Set-Location "$Root\ml-platform\backend"
& 'C:\Users\17723\miniconda3\python.exe' -m unittest `
  tests.test_image_security_contracts tests.test_week12_security_gates tests.test_ci_workflow tests.test_evidence_manifest -v
git -C $Root diff --check
git -C $Root add -- .github/workflows/ci.yml ml-platform/backend/tools/security_scans.py `
  ml-platform/backend/tests/test_week12_security_gates.py ml-platform/backend/tests/test_ci_workflow.py `
  docs/security/acceptance-20260813-manifest.json docs/security/acceptance-20260813-report.md
git -C $Root diff --cached --check
git -C $Root commit -m "fix(security): bind all production image evidence"
```

## Task 6: Close stateful Week 11 acceptance gates

**Files:**
- Generate local-only: `temp_test/acceptance-20260810/performance/`, `backup-restore/`, `n-minus-one/`, `browser/`, `web-security/`
- Create reviewed: `docs/security/acceptance-20260813-manifest.json`, `docs/security/acceptance-20260813-report.md`

- [ ] **Step 1: Run three fixed-resource performance rounds.**

Use the existing `run-performance-resource-envelope.ps1` wrapper with `try/finally`; verify 4 CPUs and 8 GiB inside WSL and Docker before each round. Require all three rounds to use one source commit, one exact image ID, one workload/seed, and the corrected rate-limit behavior. Restore the byte-identical original `.wslconfig` even on failure.

- [ ] **Step 2: Run real PostgreSQL/MinIO backup and restore.**

Use isolated database/bucket/volumes. Record fixture values and object SHA-256 before backup, restore into fresh services, then prove table counts/values and exact object hash. Record RTO/RPO from actual timestamps; redact credentials.

- [ ] **Step 3: Run real N-1 migration.**

Start from revision `20260718_08`, prove current revision, upgrade to `20260720_10_security_notifications`, run Alembic consistency check and notification/API smoke tests against the upgraded database. No shared/production database may be used.

- [ ] **Step 4: Run external Chromium and notification matrix.**

From a full isolated stack, run the repository Chromium matrix across owner/editor/operator/viewer. Verify allowed/denied changes, audit visibility, in-app notification, enterprise WeChat, email, and generic Webhook against disposable controlled receivers. Save redacted screenshots/traces/exit codes only.

- [ ] **Step 5: Generate final evidence manifest.**

Use `tools.evidence_manifest.generate` after every required artifact is present and validates. It must record relative artifact paths, hashes, source commit, tool versions, commands, timestamps, exit codes, redaction state, and explicit statuses. Any gate failure leaves manifest/report absent or marked blocked; no synthetic `passed` result.

## Task 7: Full regression, project records, and complete task-owned commits

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`
- Modify: `ml-platform/frontend/src/pages/ModelLibraryPage.test.tsx`
- Modify as required by Tasks 2-6

- [ ] **Step 1: Run full local regression in non-conflicting order.**

```powershell
Set-Location "$Root\ml-platform\backend"
$env:PYTHONPATH = '.'
& 'C:\Users\17723\miniconda3\python.exe' run_suite.py
& 'C:\Users\17723\miniconda3\python.exe' -m compileall -q app tools tests
Set-Location "$Root\ml-platform\frontend"
npm test -- --run
npm run build
npx playwright test --project=chromium
```

Expected: all commands exit zero. Record any known bundle-size warning separately from failures; never label a skipped external-stack suite as passed.

- [ ] **Step 2: Append precise project and reusable-experience records.**

Append to `DEVELOPMENT_PLAN.md` and external `DEVELOPMENT_EXPERIENCE.md`: observed symptom, verified root cause, minimal solution, commands/results, prevention, remaining gate status, source commit, and no secrets. Only mark Weeks 9-12 complete after all local, stateful, scanner, manifest, and remote CI gates are green.

- [ ] **Step 3: Commit every task-owned changed file.**

```powershell
git -C $Root status --short
git -C $Root add -- DEVELOPMENT_PLAN.md ml-platform/frontend/src/pages/ModelLibraryPage.test.tsx
git -C $Root diff --cached --check
git -C $Root diff --cached --name-status
git -C $Root commit -m "test(frontend): reduce model log fixture volume"
```

For all remaining reviewed source/config/test/doc changes, stage explicit paths, repeat the check, and commit them with the task that introduced them. Verify `git status --short` contains only deliberately local caches/raw evidence; if any task-owned file remains, stage and commit it before pushing.

## Task 8: Push, wait for GitHub Actions, merge only after green, and synchronize

**Files:**
- Remote Git refs and GitHub Actions only after Task 7 passes

- [ ] **Step 1: Fetch, re-evaluate ancestry, and push the complete branch.**

```powershell
git -C $Root fetch origin --prune
git -C $Root status --short --branch
git -C $Root push origin codex/week9-12-mlops-core
git -C $Root ls-remote --heads origin codex/week9-12-mlops-core
```

Expected: local and remote feature heads match; do not push while any required local gate is failed.

- [ ] **Step 2: Wait for the workflow attached to the pushed commit.**

Use GitHub CLI/API to identify the run where `head_sha` equals pushed `HEAD`, then wait for every required job. Capture run URL/ID and conclusions in the reviewed acceptance report. `queued`, `in_progress`, `cancelled`, `skipped`, and `neutral` are not a green release gate.

- [ ] **Step 3: Merge through the repository’s protected-branch procedure only after all required checks pass.**

Before merge, fetch `origin/main`, compare merge base, rebase/merge only if the project’s protected-branch procedure permits it, and rerun required checks if the merge changes source. Never force-push.

- [ ] **Step 4: Prove final local/remote synchronization.**

```powershell
git -C $Root fetch origin --prune
git -C $Root rev-parse HEAD
git -C $Root rev-parse origin/codex/week9-12-mlops-core
git -C 'E:\codex_workspace\agent_spot_welding' rev-parse main
git -C 'E:\codex_workspace\agent_spot_welding' rev-parse origin/main
git -C 'E:\codex_workspace\agent_spot_welding' diff --check origin/main..main
git -C $Root status --short --branch
```

Expected: merged `main` and `origin/main` resolve to the same commit; feature local/remote heads match; only deliberately untracked caches/raw evidence remain.

## Plan self-review

- Each currently confirmed blocker maps to a task: manifest fixture (Task 2), rate-limit diagnostic/fix (Task 3), images/dependencies (Tasks 4-5), stateful acceptance (Task 6), all task-owned commits (Task 7), remote publication/merge (Task 8).
- The plan does not weaken scanner rules, add an exception, accept mutable image evidence, use old scans for a new commit, or represent an external outage as passing.
- Each code behavior change requires an observed failing test first, then minimal implementation and focused/full verification.
- Generated caches and raw evidence have a defined safe-review path rather than an implicit `git add -A` path.
