# Week 9-12 Acceptance Closure Plan

## 1. Purpose

Close the remaining Week 9-12 acceptance work without confusing implementation, local tests, remote CI, real runtime evidence, and skipped states.

Current execution is based on source commit `430db194e5ecf0932c5ba2e6357c97ab0f2fe955` (`HEAD == origin/main`) and remote full run `32681461233` (`in_progress`). Previous Run `32679688421` passed Quality and production integration but failed isolated Chromium with `MODEL_REGISTRY_FAILED`; its Week 11-12 verification was skipped.

## 2. Current Baseline

| Area | Status | Evidence boundary |
|---|---|---|
| Week 9 implementation | Complete, acceptance open | Current `main` and local/production checks; final SHA-bound remote evidence pending |
| Week 10 implementation | Complete, acceptance open | Current `main`, local contracts, and production checks; final SHA-bound remote evidence pending |
| Week 11 tool contracts | Complete | Container tests `104/104` |
| Week 11 fixed-resource performance | Open | Previous runtime attempt failed when services exited together |
| Week 11 PostgreSQL/MinIO restore | Open | No valid real restore result yet |
| Week 11 N-1 data upgrade | Open | Fixture supports dual heads and seeding, but real seeded run is pending |
| Week 12 security/CI/browser gates | In progress | Run `32681461233` for SHA `430db19`; previous Run `32679688421` failed Chromium and skipped verification |
| Week 12 external role/notification matrix | Open | Requires independent evidence review and artifact binding |
| Final evidence manifest/report | Blocked | Requires successful current-SHA remote gates plus refreshed Week 11 runtime artifacts |

## 3. Work Packages

### WP0: Freeze and evidence workspace

**Dependencies:** none.

**Tasks:**

1. Confirm repository `main` is clean and points to the frozen SHA.
2. Create an isolated evidence root outside the source tree for temporary credentials, dumps, and runtime logs.
3. Record Docker/WSL versions and enforce the 4 vCPU / 8 GiB resource envelope.
4. Render Compose configuration and verify that platform PostgreSQL and MLflow use separate databases.

**Required outputs:**

- `environment.json`
- resource-envelope receipt
- redacted Compose configuration receipt
- source SHA and runtime image binding receipt

**Exit criteria:** no credential appears in an output; all runtime targets are explicitly isolated; source SHA is stable.

### WP1: Week 9 production inference acceptance

**Dependencies:** WP0; current full CI remains green.

**Tasks:**

1. Rebuild or verify backend, worker, inference, and TensorBoard production images from the frozen SHA.
2. Verify image IDs, OCI revision, non-root execution, and source provenance.
3. Run production inference lifecycle checks: API-key authentication, rate limiting, model revision exposure, rollout/rollback and readiness.
4. Preserve the successful remote production integration evidence and bind it to the same SHA.

**Required outputs:**

- `security/runtime-images.json`
- production integration result
- redacted inference lifecycle result

**Exit criteria:** all required checks pass on the same frozen SHA; no stale image or stale receipt is reused.

### WP2: Week 10 role, audit, and notification acceptance

**Dependencies:** WP0 and WP1.

**Tasks:**

1. Execute the owner/editor/operator/viewer/outsider authorization matrix for representative project resources.
2. Exercise in-app, enterprise WeCom, SMTP email, and generic Webhook channels.
3. Verify success, retry, dead-letter, redaction, audit-record, 403, and 404 paths.
4. Capture request/response or event evidence with secrets and customer values redacted.

**Required outputs:**

- role matrix receipt
- four-channel notification receipt
- retry/dead-letter receipt
- audit and denial-path receipt

**Exit criteria:** every matrix cell has a pass or an explicitly recorded, approved exception; skipped cells are not counted as passed.

### WP3: Week 11 fixed-resource performance

**Dependencies:** WP0 and a stable isolated stack from WP1.

**Tasks:**

1. Keep the stack alive for the entire load window and capture `docker compose ps -a` plus service logs on any exit.
2. Run `core-read`, `warm-inference`, and `enqueue` for iterations 1, 2, and 3 at the frozen concurrency/load.
3. Run `cold-model-load` iteration 1.
4. Run `welding-e2e` iteration 1 with ten requests and terminal `completed` evidence.
5. Summarize without deleting failed raw samples.

**Required outputs:**

- all raw performance JSON files
- `performance/summary.json`
- resource envelope receipt
- runtime image/revision receipt

**Exit criteria:** summary `status=passed` and `candidate_status=passed`; all frozen scenarios and iterations are present; request accounting and commit consistency gates pass.

### WP4: Week 11 PostgreSQL/MinIO backup and restore

**Dependencies:** WP0 and a healthy isolated stack.

**Tasks:**

1. Seed deterministic representative database rows and MinIO objects in the isolated source stack.
2. Create PostgreSQL and MinIO backups with environment-based credentials.
3. Restore into a distinct database and bucket.
4. Compare table counts, values, foreign keys, object SHA-256, RTO and RPO.
5. Finalize signed backup receipts and manifest.

**Required outputs:**

- backup operation receipts
- restore operation receipts
- backup manifest
- `backup/restore-result.json`

**Exit criteria:** restore result `status=passed`; counts, values, foreign keys, object hashes, RTO, and RPO all pass; source and restore targets are proven distinct.

### WP5: Week 11 real N-1 migration

**Dependencies:** WP0 and an isolated PostgreSQL target distinct from the production database.

**Tasks:**

1. Move the target to the supported N-1 dual heads `20260720_10_security_notifications` and `20260730_09`.
2. Run `upgrade_fixture.py seed` and verify non-zero `users`, `projects`, `workflows`, and `model_library` counts.
3. Capture the pre-upgrade snapshot.
4. Upgrade twice to `20260819_12`; run `alembic current` and `alembic check`.
5. Verify row retention, foreign-key health, readiness, worker, API, and notification smoke.

**Required outputs:**

- seed receipt
- pre-upgrade snapshot
- `upgrade/result.json`
- post-upgrade readiness and smoke receipts

**Exit criteria:** result `status=passed`; both upgrade attempts, Alembic check, data retention, FK health, readiness, worker, API, and notification smoke pass. Empty-schema results remain failures.

### WP6: Week 12 final evidence manifest and release report

**Dependencies:** WP1-WP5.

**Tasks:**

1. Download and verify the remote full-run artifact for the frozen SHA.
2. Assemble `environment.json`, performance, backup/restore, upgrade, security, browser, and runtime-image evidence.
3. Run the fail-closed evidence manifest tool.
4. Generate the final acceptance report with separate local, runtime, remote, failed, and skipped sections.
5. Update `DEVELOPMENT_PLAN.md` and `PLATFORM_STATUS.md` only after all required outputs pass.

**Required outputs:**

- `security/summary.json`
- `playwright/result.json`
- final evidence manifest
- final acceptance report
- updated project status documents

**Exit criteria:** all required manifest gates pass; every artifact binds to one SHA; no required evidence is skipped or stale; working tree contains no unreviewed Week 12 changes.

## 4. Execution Order

1. WP0 freeze and environment validation.
2. WP1 Week 9 production inference evidence.
3. WP2 Week 10 role/notification matrix.
4. WP3 fixed-resource performance.
5. WP4 backup/restore.
6. WP5 seeded N-1 migration.
7. WP6 final manifest, report, and status closure.

If WP3 fails because services exit, stop and diagnose the lifecycle before rerunning load. Preserve the failed evidence and do not proceed to a green manifest. WP4 and WP5 may run in separate isolated stacks, but must use the same frozen source SHA.

## 5. Final Closure Rule

Week 9-12 may be marked complete only when WP0-WP6 exit criteria all pass. Remote CI success alone is insufficient. Any `failed`, `cancelled`, or `skipped` required gate keeps the overall status `in progress`.

## 6. Reproducible Runbook

All commands below run from `ml-platform/backend` inside the acceptance container or an equivalent environment with the repository root mounted at `/workspace`. Replace only values marked `<...>`; never place credentials in command arguments or evidence files.

### 6.1 Environment and image evidence

```bash
python tools/acceptance_environment.py environment --output <evidence>/environment.json
python tools/acceptance_environment.py runtime-images \
  --project-name <compose-project> \
  --source-commit 252abf77c547bdb637755b00d1ff1aec8f13e14d \
  --output <evidence>/security/runtime-images.json
```

Before proceeding, verify the recorded resource envelope is exactly 4 vCPU / 8 GiB and that the runtime image evidence binds all four required production components to the frozen SHA.

### 6.2 Performance evidence

Run the CLI once per scenario and iteration, writing each raw result under `<evidence>/performance/`. The URLs, auth environment names, body files, and completion URL template must come from the frozen Compose/API contract; do not invent fallback endpoints.

```bash
python tools/week11_performance.py run --scenario <scenario> --iteration <n> \
  --url <url> --output <evidence>/performance/<scenario>-<n>.json \
  --api-key-env <api-key-env> [scenario-specific options]
python tools/week11_performance.py summarize \
  --input-dir <evidence>/performance \
  --output <evidence>/performance/summary.json
```

Stop on the first service exit, authentication mismatch, missing completion evidence, or failed candidate gate. Capture `docker compose ps -a`, service logs, resource limits, and the failed raw JSON before any restart.

### 6.3 Backup and restore evidence

```bash
python tools/backup_restore.py backup-postgres \
  --database-url-env <SOURCE_DATABASE_ENV> \
  --output <evidence>/backup/postgres.dump
python tools/backup_restore.py backup-minio \
  --source <isolated-source-bucket> \
  --destination <isolated-backup-dir> \
  --receipt-dir <evidence>/backup
python tools/backup_restore.py manifest --root <evidence>/backup
python tools/backup_restore.py restore-postgres \
  --dump <evidence>/backup/postgres.dump
python tools/backup_restore.py restore-minio \
  --source <isolated-backup-dir> \
  --destination <isolated-restore-bucket> \
  --receipt-dir <evidence>/backup
python tools/backup_restore.py verify \
  --source-database-env <SOURCE_DATABASE_ENV> \
  --restored-database-env <RESTORED_DATABASE_ENV> \
  --manifest <evidence>/backup/backup-manifest.json \
  --restored-bucket <isolated-restore-bucket> \
  --output <evidence>/backup/restore-result.json
```

The source and restore targets must be distinct and explicitly confirmed by the tool. A command exit code without matching counts, values, hashes, RTO, and RPO is not a pass.

### 6.4 N-1 evidence

```bash
python tools/upgrade_fixture.py create \
  --revision 20260720_10_security_notifications \
  --output <evidence>/upgrade/create.json
python tools/upgrade_fixture.py seed \
  --output <evidence>/upgrade/seed.json
python tools/upgrade_fixture.py snapshot \
  --output <evidence>/upgrade/before.json
python tools/upgrade_fixture.py upgrade --target 20260819_12 \
  --output <evidence>/upgrade/result.json
```

The command environment must set `UPGRADE_ACCEPTANCE_DATABASE_URL` and `UPGRADE_ACCEPTANCE_ISOLATED=1`. Inspect the seed and snapshot before upgrade; if any representative table is zero, stop and classify the run as `UPGRADE_SNAPSHOT_INVALID`.

### 6.5 Final manifest

```bash
export REMOTE_CI_RUN_URL=<full-run-url>
export ACCEPTANCE_IMAGE_DIGEST=<frozen-image-digest>
python tools/evidence_manifest.py \
  --evidence-dir <evidence> \
  --output <evidence>/final-evidence-manifest.json
```

The final command is allowed to succeed only after the performance, backup, upgrade, security, runtime-image, and Playwright result files all exist and report `status=passed`. Do not manually edit a failed result to satisfy the manifest.

## 7. Stop/Resume Rules

- A runtime failure produces a failed evidence bundle first; restarting containers without preserving the failed bundle invalidates the diagnostic trail.
- A skipped GitHub step remains skipped and is never counted as passed.
- A new source commit invalidates runtime image provenance and all SHA-bound receipts; repeat WP0 and all affected gates.
- Only after WP6 passes may the status documents be changed from `进行中` to `已完成` and a release merge be considered.

## 8. Current Progress Record (2026-08-24)

- WeCom acceptance DNS/SSRF allowlist issue: fixed and verified through notification creation/send.
- Browser fixture artifact storage mismatch: fixed in `430db19` by using MinIO backend and local CI endpoint; contract coverage added.
- Run `32681461233` is `in_progress`. Until Chromium acceptance and Week 11-12 verification both succeed, Week 9-12 remains `in progress`.
- After the remote gate, rerun and bind fixed-resource performance, PostgreSQL/MinIO restore, N-1 migration, image provenance, and final manifest to `430db19`. Failed, cancelled, or skipped artifacts remain non-passing.
- Run `32681461233` completed with `failure`: standard Chromium regression inherited external MinIO settings while using the local SQLite fixture, so MinIO upload failed with connection refused before isolated Week 12. The worktree fix forces `ARTIFACT_STORAGE_BACKEND=local` for standard Playwright services/fixtures and adds a CI contract assertion; external acceptance remains MinIO-backed. A new SHA/full run is required.
