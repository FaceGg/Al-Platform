# Week 11-12 Acceptance Closure Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Produce reproducible Week 11-12 release evidence for performance, disaster recovery, N-1 migration, browser acceptance, web security, and remote CI, then merge only a fully verified branch.

**Architecture:** Run stateful checks in an isolated Docker Compose project from one WSL shell lifecycle. Evidence is written below `temp_test/acceptance-20260810/` and summarized by a machine-checked manifest. Resource changes are scoped to the user's WSL configuration, backed up before use, and restored in a `finally` path. The branch is promoted only after local gates, remote Actions, and main-branch synchronization agree.

**Tech Stack:** PowerShell 7, WSL2, Docker Compose, PostgreSQL, MinIO, Redis/Celery, Chromium/Playwright, Python `unittest`, Vite, GitHub Actions.

## Task 1: Freeze State and Prepare Evidence Workspace

**Files:**
- Create: `temp_test/acceptance-20260810/manifest.json` (generated only after evidence exists)
- Create: `temp_test/acceptance-20260810/README.md`
- Modify: `DEVELOPMENT_PLAN.md` only after a gate is actually verified
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md` only after a problem is resolved

- [ ] **Step 1: Record repository and runtime baseline.**

Use PowerShell 7 with `$Root = 'E:\codex_workspace\agent_spot_welding\.worktrees\week9-12-mlops-core'` and record branch, commit, remotes, dirty paths, Docker/Compose versions, WSL distribution list, and existing evidence hashes. Do not stage or remove `ml-platform/frontend/src/pages/ModelLibraryPage.test.tsx`, `tmp/npm-cache/`, `tmp/pip-cache/`, or `tmp/security-20260810/`.

- [ ] **Step 2: Create an isolated evidence directory and project name.**

Use a timestamped directory under `$Root\temp_test\acceptance-20260810` and a unique Compose project name such as `spot-welding-acceptance-20260810`. Capture the generated project name, ports, database name, MinIO bucket, Redis namespace, and source commit in the evidence README. Never use a production project, bucket, database, or volume.

- [ ] **Step 3: Add the evidence README contract.**

Document that every result must contain the exact command, start/end time, exit code, source commit, tool version, and artifact path. A failed or unavailable external service is recorded as `blocked` with output; it is never represented as `passed`.

## Task 2: Run Three-Round Performance Baseline Under Fixed WSL Resources

**Files:**
- Generate: `temp_test/acceptance-20260810/performance/`
- Modify: `DEVELOPMENT_PLAN.md` and shared experience after verification

- [ ] **Step 1: Back up and inspect the user WSL configuration.**

Resolve `$env:USERPROFILE\\.wslconfig` to an absolute path. Copy it byte-for-byte to the evidence directory, record whether it existed, and record `wsl.exe --status` plus `wsl.exe -l -v`. Do not change unrelated settings.

- [ ] **Step 2: Apply the temporary 4 vCPU / 8 GiB envelope.**

Write only `[wsl2]`, `processors=4`, and `memory=8GB` (preserving a prior file for restoration), run `wsl.exe --shutdown`, then start the Docker distribution. Verify effective CPU and memory from inside WSL and from `docker info`. If WSL or Docker cannot honor the envelope, capture the exact output and mark this gate blocked.

- [ ] **Step 3: Execute three identical performance rounds.**

Start the isolated Compose stack and run the repository's existing performance/benchmark entry point discovered from `DEVELOPMENT_PLAN.md` and `rg`. Use identical seed data, request count, concurrency, timeout, and image commit for rounds 1-3. Capture raw JSON/CSV, service logs, host capacity, and exit status for each round. Do not fabricate a baseline when the benchmark cannot run.

- [ ] **Step 4: Restore WSL state unconditionally.**

In a PowerShell `try/finally`, restore the original `.wslconfig` bytes or remove the temporary file when none existed, run `wsl.exe --shutdown`, and verify the restored contents/hash. Tear down only the generated Compose project resources.

- [ ] **Step 5: Validate and summarize the baseline.**

Check all three rounds have the same workload contract and complete measurements. Record median/mean, p95 where available, error count, and resource observations without inventing thresholds. Mark the gate `passed` only when the project's documented threshold is met in all required rounds.

## Task 3: Prove PostgreSQL/MinIO Backup Restore and RTO/RPO

**Files:**
- Generate: `temp_test/acceptance-20260810/backup-restore/`

- [ ] **Step 1: Seed isolated services with traceable fixtures.**

Start PostgreSQL and MinIO under the unique project. Insert a small known database fixture and upload a known object whose SHA-256 is recorded. Keep credentials in process environment only; redact them from logs and manifests.

- [ ] **Step 2: Create backups using repository tooling.**

Locate the supported backup commands from `DEVELOPMENT_PLAN.md`, deployment docs, and scripts. Produce a PostgreSQL logical backup and a MinIO/object backup in the evidence directory, recording command, tool version, size, and SHA-256.

- [ ] **Step 3: Restore into clean targets and verify integrity.**

Destroy or isolate the seeded targets, restore the database and object backup into fresh service names/volumes, query the fixture, download the object, and compare exact values and hashes. Capture start/end timestamps to calculate RTO and record the backup timestamp versus restore point to calculate RPO.

- [ ] **Step 4: Record a failed restore as failure.**

Any missing tool, permission error, checksum mismatch, or service outage stops promotion and is recorded with raw output. Do not edit evidence to force a pass.

## Task 4: Execute the N-1 Database Upgrade

**Files:**
- Generate: `temp_test/acceptance-20260810/n-minus-one/`

- [ ] **Step 1: Identify the current and target migration revisions.**

Read Alembic configuration and migration history. Confirm `20260718_08` is the N-1 source and `20260720_10_security_notifications` is the target named by the acceptance specification. Record the exact source/target revisions and image commit.

- [ ] **Step 2: Restore a disposable N-1 database.**

Create a fresh isolated PostgreSQL database, apply the N-1 schema/data fixture, and verify the source revision. Do not use a shared or production database.

- [ ] **Step 3: Run the real upgrade and downgrade safety checks.**

Run the repository's Alembic upgrade command from `20260718_08` to `20260720_10_security_notifications`, validate notification tables/indexes/constraints and existing data, then run the documented migration consistency check. Capture SQL/tool output and exit status.

- [ ] **Step 4: Verify application compatibility at the target revision.**

Start the backend against the upgraded database and run the notification/API smoke tests and targeted backend suite. Mark pass only when startup, migration checks, and behavior checks all pass.

## Task 5: Complete External Chromium, Role, Notification, and Web Security Acceptance

**Files:**
- Generate: `temp_test/acceptance-20260810/browser/`
- Generate: `temp_test/acceptance-20260810/web-security/`

- [ ] **Step 1: Start the full isolated stack and prove readiness.**

Start backend, frontend, PostgreSQL, MinIO, Redis/Celery, and any required inference services with the unique Compose project. Wait on health endpoints and record the URLs actually used by Chromium.

- [ ] **Step 2: Run the external Chromium matrix.**

Use the repository's Playwright/Chromium entry points, not mocked browser calls. Exercise login, core workflow/template execution, dataset/model artifact flow, notification center, and the release-critical paths from Weeks 1-12. Capture screenshots, traces, console/network failures, and exit codes.

- [ ] **Step 3: Exercise all four roles and notification channels.**

Run owner/editor/operator/viewer authorization checks, including denied writes and audit visibility. Verify in-app notification, enterprise WeChat, email, and generic Webhook through the repository's test adapters or configured disposable endpoints. Secrets remain environment-only and all outbound payload evidence is redacted.

- [ ] **Step 4: Run web security checks.**

Execute existing CORS, security-header, authentication, authorization, CSRF/SSRF, injection, and rate-limit tests discovered in the repository. Add a focused regression test only when a tested contract is missing; do not broaden a scanner exception.

## Task 6: Validate Security Gates and Build the Evidence Manifest

**Files:**
- Generate: `temp_test/acceptance-20260810/security/`
- Create: `docs/security/acceptance-20260810-manifest.json`
- Create: `docs/security/acceptance-20260810-report.md`

- [ ] **Step 1: Build and scan all production images.**

Build backend, worker, inference, and TensorBoard images from the same commit and pinned base digest. Run Trivy image scans at HIGH/CRITICAL, filesystem scan, Bandit, official-registry npm audit, scoped Gitleaks, and raw pip-audit with no cryptography exception. Store reports outside tracked source unless the plan explicitly names a reviewed summary.

- [ ] **Step 2: Run the complete local regression matrix.**

Run backend `run_suite.py`, targeted security/CI tests, frontend tests, production build, migration tests, and the Chromium suite. Record exact commands and exit codes. Any failure blocks the manifest.

- [ ] **Step 3: Generate and validate the manifest.**

Create a JSON manifest containing schema version, source commit, tool versions, each gate's status, command, exit code, timestamp, artifact relative path, SHA-256, and redaction status. A validator must reject missing artifacts, nonzero exit codes marked passed, absolute paths, credentials, and unresolved high/critical findings. Report blocked gates explicitly.

- [ ] **Step 4: Update project records.**

Append observed behavior, root cause, solution, verification method, prevention, and remaining work to `DEVELOPMENT_PLAN.md`. Append the reusable lesson to the project section of `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`; never include passwords, tokens, keys, customer data, or raw webhook/email secrets.

## Task 7: Push, Verify Remote Actions, Merge, and Prove Synchronization

**Files:**
- Modify: Git history and remote refs only after all required gates pass

- [ ] **Step 1: Review and commit only scoped changes.**

Run `git diff --check`, inspect staged paths, preserve user-owned modifications, and create focused commits. Do not stage temporary caches or raw evidence unless explicitly required by the manifest contract.

- [ ] **Step 2: Push the feature branch and wait for required Actions.**

Push `codex/week9-12-mlops-core`, inspect the remote commit and required GitHub Actions checks, and wait until every required job is green. A workflow outage or failed check is recorded and blocks merge.

- [ ] **Step 3: Merge only after remote evidence is green.**

Fast-forward or merge into `main` using the repository's protected-branch procedure. Do not force-push or rewrite unrelated history. Verify local `main`, `origin/main`, and the merge commit agree, and verify the feature branch is not ahead of its remote.

- [ ] **Step 4: Final synchronization check.**

Run `git fetch --prune`, compare `git rev-parse main` with `git rev-parse origin/main`, confirm the required workflow run references the merged commit, and record the final status in the acceptance report and development plan.

## Stop Conditions

- Stop promotion on any failing test, scanner, migration, restore, browser, performance, or remote CI gate.
- Treat Docker, WSL, registry, network, credential, and GitHub outages as externally blocked with reproducible evidence.
- Never replace real evidence with a fabricated result, broaden an ignore rule, delete user files, or claim completion while a required gate is blocked.

