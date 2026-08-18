# GitHub Actions Quota Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce routine GitHub Actions use while retaining PR quality coverage, preserving scheduled/full production verification, and automatically removing only expired Actions data.

**Architecture:** Keep one CI workflow, but classify each run as light or full from its event and manual input. Add a separate least-privilege cleanup workflow that uses the GitHub REST API through `gh`, applies explicit age/name/status filters before deletion, and never acts on non-completed workflow runs.

**Tech Stack:** GitHub Actions YAML, GitHub CLI REST API, Bash, Python `unittest`, PyYAML.

---

## File structure

| File | Responsibility |
| --- | --- |
| `.github/workflows/ci.yml` | Defines light/full CI triggers, same-ref cancellation, heavy-job gating and evidence retention. |
| `.github/workflows/actions-cleanup.yml` | Schedules/manual-runs scoped cleanup of known CI artifacts, stale caches and completed runs. |
| `ml-platform/backend/tests/test_ci_workflow.py` | Parses both workflows and locks trigger, permission, retention and deletion-safety contracts. |
| `DEVELOPMENT_PLAN.md` | Records the completed CI quota task, exact local verification and remote billing limitation. |
| `C:\\Users\\17723\\.codex\\DEVELOPMENT_EXPERIENCE.md` | Appends reusable Actions quota/cleanup prevention guidance after verification. |

## Task 1: Add failing workflow contract tests

**Files:**

- Modify: `ml-platform/backend/tests/test_ci_workflow.py`
- Test: `ml-platform/backend/tests/test_ci_workflow.py`

- [ ] **Step 1: Add cleanup-path and trigger-contract helpers.**

Add this beside the existing `CI_WORKFLOW` constant; use `BaseLoader` only when inspecting root triggers so `on` stays a string:

```python
CLEANUP_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "actions-cleanup.yml"

def load_workflow_contract(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
```

- [ ] **Step 2: Add failing CI routing, concurrency and retention tests.**

Add tests that assert:

```python
contract = load_workflow_contract(CI_WORKFLOW)
triggers = contract["on"]
assert triggers["schedule"][0]["cron"] == "0 2 * * 0"
mode = triggers["workflow_dispatch"]["inputs"]["mode"]
assert mode["default"] == "light"
assert mode["options"] == ["light", "full"]
assert contract["concurrency"]["cancel-in-progress"] == "true"
assert "github.event.pull_request.number" in contract["concurrency"]["group"]
assert "github.ref" in contract["concurrency"]["group"]
```

For each of `production-integration`, `experiment-integration` and `week11-12-verification`, assert its `if` expression includes main `push`, `schedule`, manual `workflow_dispatch`, and `inputs.mode == 'full'`. Assert `retention-days: 7` for Playwright, production and experiment failure evidence uploads and `retention-days: 14` for verification evidence.

- [ ] **Step 3: Add failing cleanup safety-contract tests.**

Create `TestActionsCleanupWorkflow`. Assert the cleanup workflow:

```python
assert contract["on"]["schedule"][0]["cron"] == "30 2 * * 0"
assert "workflow_dispatch" in contract["on"]
assert job["permissions"] == {"actions": "write"}
```

Assert its shell script includes the exact markers:

```text
FAILURE_EVIDENCE_RETENTION_DAYS=7
VERIFICATION_EVIDENCE_RETENTION_DAYS=14
CACHE_RETENTION_DAYS=7
RUN_RETENTION_DAYS=30
status == "completed"
actions/artifacts
actions/caches
actions/runs
--paginate
--method DELETE
playwright-failure-evidence
week11-12-verification-evidence
```

- [ ] **Step 4: Run the focused test to prove the new contracts are initially RED.**

Run:

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest ml-platform.backend.tests.test_ci_workflow -v
```

Expected: failures due to missing trigger/concurrency/retention fields and missing cleanup workflow.

- [ ] **Step 5: Commit only the test change.**

```powershell
git add -- ml-platform/backend/tests/test_ci_workflow.py
git commit -m "test(ci): define quota workflow contracts"
```

## Task 2: Implement light/full CI routing

**Files:**

- Modify: `.github/workflows/ci.yml`
- Test: `ml-platform/backend/tests/test_ci_workflow.py`

- [ ] **Step 1: Add schedule/manual triggers and workflow-level concurrency.**

Use this exact YAML after the current push/PR triggers:

```yaml
  schedule:
    - cron: "0 2 * * 0"
  workflow_dispatch:
    inputs:
      mode:
        description: "CI coverage level"
        required: true
        default: light
        type: choice
        options:
          - light
          - full

concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
```

- [ ] **Step 2: Gate the three heavy jobs only.**

Insert the same `if` before `runs-on` for `production-integration`, `experiment-integration` and `week11-12-verification`:

```yaml
if: >-
  (github.event_name == 'push' && github.ref == 'refs/heads/main') ||
  github.event_name == 'schedule' ||
  (github.event_name == 'workflow_dispatch' && inputs.mode == 'full')
```

Do not gate `quality` or `browser-acceptance`; they must run for every PR, `develop`, scheduled and manual event. Preserve Week 11-12 `needs` unchanged, so skipped heavy jobs cannot be reported as a full verification pass.

- [ ] **Step 3: Set the evidence retention policy without changing paths or conditions.**

Under existing artifact `with:` mappings add:

```yaml
retention-days: 7
```

for `Upload Playwright failure evidence`, `Upload production failure evidence`, and `Upload experiment failure evidence`; add:

```yaml
retention-days: 14
```

for `Upload verification evidence`.

- [ ] **Step 4: Run all existing CI contract tests.**

Run:

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest ml-platform.backend.tests.test_ci_workflow.TestProductionIntegrationWorkflow -v
```

Expected: routing, concurrency and retention tests pass with no regression to existing redaction, Docker or frozen-stack contracts.

- [ ] **Step 5: Commit only workflow and test changes.**

```powershell
git add -- .github/workflows/ci.yml ml-platform/backend/tests/test_ci_workflow.py
git commit -m "ci: split light and full validation"
```

## Task 3: Implement least-privilege Actions cleanup

**Files:**

- Create: `.github/workflows/actions-cleanup.yml`
- Modify: `ml-platform/backend/tests/test_ci_workflow.py`
- Test: `ml-platform/backend/tests/test_ci_workflow.py`

- [ ] **Step 1: Create the restricted cleanup workflow header.**

```yaml
name: Actions data cleanup

on:
  schedule:
    - cron: "30 2 * * 0"
  workflow_dispatch:

jobs:
  cleanup:
    name: Remove expired Actions data
    runs-on: ubuntu-22.04
    permissions:
      actions: write
```

Do not check out source and do not request `contents`, PR, issue or administration permissions.

- [ ] **Step 2: Implement the cleanup step with exact thresholds and resource allow-list.**

Use `shell: bash`, `set -euo pipefail`, and these declarations:

```bash
FAILURE_EVIDENCE_RETENTION_DAYS=7
VERIFICATION_EVIDENCE_RETENTION_DAYS=14
CACHE_RETENTION_DAYS=7
RUN_RETENTION_DAYS=30
REPOSITORY="${GITHUB_REPOSITORY}"

failure_cutoff="$(date -u -d "${FAILURE_EVIDENCE_RETENTION_DAYS} days ago" +%s)"
verification_cutoff="$(date -u -d "${VERIFICATION_EVIDENCE_RETENTION_DAYS} days ago" +%s)"
cache_cutoff="$(date -u -d "${CACHE_RETENTION_DAYS} days ago" +%s)"
run_cutoff="$(date -u -d "${RUN_RETENTION_DAYS} days ago" +%s)"

delete_resource() {
  local endpoint="$1"
  gh api --method DELETE "repos/${REPOSITORY}/${endpoint}"
}
```

Artifacts are eligible only if their name is one of:

```text
playwright-failure-evidence
production-integration-failure-evidence
experiment-integration-failure-evidence
week11-12-verification-evidence
```

Use `gh api --paginate` plus `jq` to compare `created_at | fromdateiso8601`; only the Week 11-12 name uses `verification_cutoff`, the other three use `failure_cutoff`. Delete artifacts with `actions/artifacts/<id>`.

List caches through `actions/caches?per_page=100`; delete only a cache whose `last_accessed_at | fromdateiso8601` is older than `cache_cutoff`, through `actions/caches/<id>`.

List runs through `actions/runs?status=completed&per_page=100`; independently enforce `status == "completed"` in `jq` before comparing `created_at` to `run_cutoff`, then delete only those entries through `actions/runs/<id>`. Never add `|| true` to deletion calls: a deletion error must fail the cleanup job rather than report a misleading complete cleanup.

- [ ] **Step 3: Run cleanup contract tests and repair marker/behavior mismatches.**

Run:

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest ml-platform.backend.tests.test_ci_workflow.TestActionsCleanupWorkflow -v
```

Expected: all cleanup safety-contract tests pass, including actions-only permission and non-completed run protection.

- [ ] **Step 4: Run the full CI workflow contract module.**

Run:

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest ml-platform.backend.tests.test_ci_workflow -v
```

Expected: all tests pass and existing security/evidence contracts remain unchanged.

- [ ] **Step 5: Commit only cleanup workflow and test changes.**

```powershell
git add -- .github/workflows/actions-cleanup.yml ml-platform/backend/tests/test_ci_workflow.py
git commit -m "ci: clean expired Actions data"
```

## Task 4: Verify, document and publish scoped changes

**Files:**

- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`
- Verify: `.github/workflows/ci.yml`
- Verify: `.github/workflows/actions-cleanup.yml`

- [ ] **Step 1: Validate YAML and final implementation scope.**

Run:

```powershell
C:\Users\17723\miniconda3\python.exe -c "from pathlib import Path; import yaml; [yaml.safe_load(Path(path).read_text(encoding='utf-8')) for path in ('.github/workflows/ci.yml', '.github/workflows/actions-cleanup.yml')]; print('YAML OK')"
git diff --check
git status --short
```

Expected: `YAML OK`, no whitespace errors, and no unrelated file modifications.

- [ ] **Step 2: Append a dated delivery record to `DEVELOPMENT_PLAN.md`.**

Record the light/full event policy, weekly cron values, 7/14/7/30-day thresholds, concurrency cancellation behavior, exact local test output and remote billing/quota boundary. Explicitly distinguish runner-start failure from code failure or a passing remote CI run.

- [ ] **Step 3: Append a reusable `EXP-AW-*` entry to the shared experience file.**

Include observed problem, root cause, implementation, local verification, prevention rule and any unresolved remote execution boundary. Do not include credentials or account-sensitive data.

- [ ] **Step 4: Re-run final verification.**

Run:

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest ml-platform.backend.tests.test_ci_workflow -v
git diff --check
git status --short
```

Expected: tests pass and the only unstaged repository change is the required `DEVELOPMENT_PLAN.md` record. The shared experience entry is outside this repository and is not part of Git status.

- [ ] **Step 5: Commit documentation separately and verify remote branch state before/after scoped push.**

```powershell
git add -- DEVELOPMENT_PLAN.md
git commit -m "docs(ci): record Actions quota controls"
git remote -v
git ls-remote --heads origin "$(git branch --show-current)"
git push origin HEAD
git ls-remote --heads origin "$(git branch --show-current)"
```

Expected: the remote branch SHA equals local HEAD. If GitHub billing/quota still prevents a runner from starting, record the blocked remote validation and do not retry repeatedly.
