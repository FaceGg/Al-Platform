# Week 7 Project Roles and Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add owner/editor/operator/viewer project collaboration, centralized project authorization, and append-only audit events for all core project-scoped writes.

**Architecture:** Preserve `Project.owner_id` as the unique owner and persist only non-owner memberships. Route project permission decisions through one access service and audited mutations through one transaction context so successful business state and audit rows commit together while denied/failed outcomes use controlled short transactions. Request-ID middleware supplies correlation without putting project roles into JWTs.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL/SQLite, unittest, existing JWT authentication and TestClient fixtures.

---

## File Map

- Create `app/models/access.py`: `ProjectMember` and `AuditEvent` ORM models.
- Create `app/schemas/access.py`: strict membership and audit contracts.
- Create `app/services/project_access.py`: role matrix and project/resource authorization.
- Create `app/services/audit.py`: redaction, event creation, and audited transaction context.
- Create `app/middleware/request_id.py`: UUID request correlation.
- Create `app/api/project_access.py`: membership and audit-query routes.
- Create Alembic `20260718_07_project_roles_audit.py`.
- Create `tests/test_project_access.py` and `tests/test_api_project_access.py`.
- Modify project-owned routers, model registration, migration tests, manifest, CI, and status docs.

### Task 1: Request correlation and audit redaction

**Files:**
- Create: `ml-platform/backend/app/middleware/request_id.py`
- Create: `ml-platform/backend/app/services/audit.py`
- Create: `ml-platform/backend/tests/test_project_access.py`
- Modify: `ml-platform/backend/app/main.py`

- [x] **Step 1: Write failing tests**

Test missing, valid, and invalid `X-Request-ID` values. Add recursive redaction coverage:

```python
self.assertEqual(
    redact_changes(
        {"role": "editor", "password": "x", "nested": {"token": "x", "count": 2}},
        allowed={"role", "nested"},
    ),
    {"role": "editor", "nested": {"token": "[REDACTED]", "count": 2}},
)
```

- [x] **Step 2: Confirm RED**

```powershell
python -m unittest tests.test_project_access.TestRequestCorrelation tests.test_project_access.TestAuditRedaction -v
```

Expected: middleware/service imports do not exist.

- [x] **Step 3: Implement the stable interfaces**

`RequestIdMiddleware.dispatch` parses the request header with `uuid.UUID`; on missing/invalid input it uses `uuid.uuid4()`, stores the UUID as `request.state.request_id`, invokes `call_next`, and writes the same UUID to the response header. `redact_changes(value, allowed)` copies only top-level allowlisted keys and recursively replaces sensitive-key values with `[REDACTED]`. `audit_request_context(request)` returns the state UUID and `request.client.host` when available.

Sensitive key fragments are `password`, `token`, `secret`, `credential`, `authorization`, `cookie`, `content`, `data`, and `path`. Source IP uses `request.client.host`; do not trust forwarding headers without a trusted-proxy configuration.

- [x] **Step 4: Verify GREEN and commit**

```powershell
python -m unittest tests.test_project_access.TestRequestCorrelation tests.test_project_access.TestAuditRedaction -v
git add ml-platform/backend/app/middleware ml-platform/backend/app/services/audit.py ml-platform/backend/app/main.py ml-platform/backend/tests/test_project_access.py
git commit -m "feat: add audit request correlation and redaction"
```

### Task 2: Persist project members and audit events

**Files:**
- Create: `ml-platform/backend/app/models/access.py`
- Create: `ml-platform/backend/alembic/versions/20260718_07_project_roles_audit.py`
- Modify: `ml-platform/backend/app/models/__init__.py`
- Modify: `ml-platform/backend/alembic/env.py`
- Modify: `ml-platform/backend/tests/test_project_access.py`
- Modify: `ml-platform/backend/tests/test_database_production.py`

- [x] **Step 1: Write model/migration tests**

Assert tables, unique `(project_id, user_id)`, role/result checks, user-project and audit query indexes, audit `SET NULL` foreign keys, head `20260718_07`, 35 business tables, and downgrade to `20260718_06`.

- [x] **Step 2: Confirm RED**

```powershell
python -m unittest tests.test_project_access.TestAccessModels tests.test_database_production.TestAlembicBaseline -v
```

- [x] **Step 3: Implement models and migration**

Define `PROJECT_MEMBER_ROLES = ("editor", "operator", "viewer")` and `AUDIT_RESULTS = ("success", "denied", "failed")`. `ProjectMember` uses UUID `id/project_id/user_id/created_by`, `String(16)` role, server timestamps, named unique/check constraints, and the user-project index. `AuditEvent` uses UUID `id/request_id`, nullable UUID `project_id/actor_id`, `String` snapshots/action/resource/result/source/error`, JSON changes, server timestamp, and the four specified query indexes.

The owner has no member row. Membership references cascade; audit references use `SET NULL`. Downgrade drops indexes before tables.

- [x] **Step 4: Verify and commit**

```powershell
python -m unittest tests.test_project_access.TestAccessModels tests.test_database_production -v
$db = Join-Path $env:TEMP ("week7-access-" + [guid]::NewGuid().ToString("N") + ".db")
$env:DATABASE_URL = "sqlite:///" + ($db -replace '\\','/')
alembic upgrade head
alembic upgrade head
alembic current
alembic check
git add ml-platform/backend/app/models ml-platform/backend/alembic ml-platform/backend/tests
git commit -m "feat: persist project members and audit events"
```

### Task 3: Centralize project role permissions

**Files:**
- Create: `ml-platform/backend/app/services/project_access.py`
- Modify: `ml-platform/backend/tests/test_project_access.py`

- [ ] **Step 1: Write the full matrix tests**

Table-drive `owner/editor/operator/viewer` against `project.read`, project update/delete, member manage, resource create/update/delete, execution operate, schedule manage/operate, and audit read. Assert owner precedence, missing membership as hidden, and no global-admin bypass.

- [ ] **Step 2: Confirm RED**

```powershell
python -m unittest tests.test_project_access.TestProjectPermissionMatrix -v
```

- [ ] **Step 3: Implement the service**

Define `ProjectRole(str, Enum)` with `OWNER/EDITOR/OPERATOR/VIEWER`, and frozen `ProjectAccess(project: Project, role: ProjectRole)`. `ProjectAccessService.resolve(db, project_id, user_id)` checks owner first and then membership. `ProjectAccessService.require(db, project_id, user_id, permission)` returns access when the role matrix contains the permission, otherwise raises hidden `PROJECT_NOT_FOUND` or visible `PROJECT_PERMISSION_DENIED`. `accessible_project_query(db, user_id)` uses an outer membership join with an owner-or-member predicate and `distinct(Project.id)`.

Use `ProjectAccessError(code, hidden)` for stable 404/403 translation. The accessible query returns owner/member union without duplicates.

- [ ] **Step 4: Verify and commit**

```powershell
python -m unittest tests.test_project_access.TestProjectPermissionMatrix -v
git add ml-platform/backend/app/services/project_access.py ml-platform/backend/tests/test_project_access.py
git commit -m "feat: centralize project role permissions"
```

### Task 4: Implement audited transaction semantics

**Files:**
- Modify: `ml-platform/backend/app/services/audit.py`
- Modify: `ml-platform/backend/tests/test_project_access.py`

- [ ] **Step 1: Write transaction RED tests**

Cover success row/event in one commit, rollback removing both, visible permission denial event, outsider hidden denial without event, failed event through an injected short session, and audit persistence failure aborting business success.

- [ ] **Step 2: Confirm RED**

```powershell
python -m unittest tests.test_project_access.TestAuditedProjectAction -v
```

- [ ] **Step 3: Implement one context-managed boundary**

Define frozen `AuditIntent(project_id, action, resource_type, resource_id, changes)` and `AuditService.project_action(db, request, actor, access, permission, intent, allowed_changes)` as a `@contextmanager`. It calls the access check before yielding, adds a redacted success event and commits after the body, rolls back and records a visible denial, and on other exceptions rolls back, records a normalized failed event through the injected session factory, then re-raises.

Entry checks permission. Success adds the audit row before the only commit. Denied visible access commits a denied event. Unexpected exceptions roll back, write a normalized failed event in `session_factory`, and re-raise.

- [ ] **Step 4: Verify and commit**

```powershell
python -m unittest tests.test_project_access.TestAuditedProjectAction -v
git add ml-platform/backend/app/services/audit.py ml-platform/backend/tests/test_project_access.py
git commit -m "feat: enforce audited project transactions"
```

### Task 5: Membership, joined projects, and audit-query APIs

**Files:**
- Create: `ml-platform/backend/app/schemas/access.py`
- Create: `ml-platform/backend/app/api/project_access.py`
- Create: `ml-platform/backend/tests/test_api_project_access.py`
- Modify: `ml-platform/backend/app/api/projects.py`
- Modify: `ml-platform/backend/app/schemas/project.py`
- Modify: `ml-platform/backend/app/main.py`

- [ ] **Step 1: Write membership/API RED tests**

Cover synthetic owner list entry, add by username, duplicate/unknown user, role change/removal, strict payloads, owner immutability, outsider hidden 404, visible non-owner 403, owned/joined project union, no duplicates, and `project_role`.

- [ ] **Step 2: Write audit-query RED tests**

Assert owner-only newest-first bounded pagination and action/resource/actor/result/time filters. Assert no audit POST/PATCH/DELETE route exists.

- [ ] **Step 3: Confirm RED**

```powershell
python -m unittest tests.test_api_project_access -v
```

- [ ] **Step 4: Implement strict schemas and routes**

Use `ConfigDict(extra="forbid")`, UUID fields, `Literal["editor", "operator", "viewer"]`, offset `ge=0`, and limit `1..200`. Membership actions are `project.member.add`, `project.member.role_change`, and `project.member.remove`.

- [ ] **Step 5: Verify and commit**

```powershell
python -m unittest tests.test_api_project_access tests.test_api_projects -v
git add ml-platform/backend/app/api/project_access.py ml-platform/backend/app/api/projects.py ml-platform/backend/app/schemas ml-platform/backend/app/main.py ml-platform/backend/tests
git commit -m "feat: expose project membership and audit APIs"
```

### Task 6: Migrate projects, workflows, versions, templates, and runs

**Files:**
- Modify: `ml-platform/backend/app/api/projects.py`
- Modify: `ml-platform/backend/app/api/workflows.py`
- Modify: `ml-platform/backend/app/api/workflows_direct.py`
- Modify: `ml-platform/backend/app/api/workflow_versions.py`
- Modify: `ml-platform/backend/app/api/templates.py`
- Modify: `ml-platform/backend/app/api/runs.py`
- Modify: `ml-platform/backend/tests/test_api_projects.py`
- Modify: `ml-platform/backend/tests/test_api_workflows.py`
- Modify: `ml-platform/backend/tests/test_workflow_versions.py`
- Modify: `ml-platform/backend/tests/test_api_runs.py`
- Modify: `ml-platform/backend/tests/test_api_project_access.py`

- [ ] **Step 1: Add role/audit RED tests**

Assert viewer reads; editor edits definitions but not project metadata; operator starts/cancels runs only; viewer cannot execute; owner alone updates/deletes projects and manages batch delete. Assert success and denied events.

- [ ] **Step 2: Confirm RED**

```powershell
python -m unittest tests.test_api_projects tests.test_api_workflows tests.test_workflow_versions tests.test_api_runs tests.test_api_project_access -v
```

- [ ] **Step 3: Apply access and audit boundaries**

Use project read/update/delete, resource create/update/delete, and execution operate. Resolve indirect workflow/run resources to project before authorization. Action names are `project.create/update/delete/batch_delete`, `workflow.create/update/delete/publish/restore/template_instantiate`, and `workflow_run.start/cancel`.

- [ ] **Step 4: Verify and commit**

```powershell
python -m unittest tests.test_api_projects tests.test_api_workflows tests.test_workflow_versions tests.test_api_runs tests.test_api_project_access -v
git add ml-platform/backend/app/api ml-platform/backend/tests
git commit -m "feat: enforce project roles on workflows and runs"
```

### Task 7: Migrate datasets, experiments, training, and schedules

**Files:**
- Modify: `ml-platform/backend/app/api/datasets.py`
- Modify: `ml-platform/backend/app/api/experiments.py`
- Modify: `ml-platform/backend/app/api/training.py`
- Modify: `ml-platform/backend/app/api/schedules.py`
- Modify: `ml-platform/backend/tests/test_api_datasets.py`
- Modify: `ml-platform/backend/tests/test_api_experiments.py`
- Modify: `ml-platform/backend/tests/test_training.py`
- Modify: `ml-platform/backend/tests/test_api_schedules.py`
- Modify: `ml-platform/backend/tests/test_api_project_access.py`

- [ ] **Step 1: Add role/audit RED tests**

Cover editor definition writes, operator execution/stop/resume and schedule pause/resume/backfill, viewer reads, and outsider 404 for each resource family. Assert redacted audit actions.

- [ ] **Step 2: Confirm RED**

```powershell
python -m unittest tests.test_api_datasets tests.test_api_experiments tests.test_training tests.test_api_schedules tests.test_api_project_access -v
```

- [ ] **Step 3: Apply permissions and audited actions**

Use resource permissions for data/experiment/training definitions, execution operate for submit/resume/stop, schedule manage for create/update, and schedule operate for pause/resume/backfill/tick. Action prefixes are `dataset`, `experiment`, `training_job`, and `schedule`.

- [ ] **Step 4: Verify and commit**

```powershell
python -m unittest tests.test_api_datasets tests.test_api_experiments tests.test_training tests.test_api_schedules tests.test_api_project_access -v
git add ml-platform/backend/app/api ml-platform/backend/tests
git commit -m "feat: enforce project roles on data training and schedules"
```

### Task 8: Audit completeness for project-bound model and orchestration writes

**Files:**
- Modify: `ml-platform/backend/app/api/models.py`
- Modify: `ml-platform/backend/app/api/model_library.py`
- Modify: `ml-platform/backend/app/api/orchestration.py`
- Modify: `ml-platform/backend/app/api/platform_api.py`
- Modify: `ml-platform/backend/tests/test_api_project_access.py`
- Modify: `ml-platform/backend/tests/test_module_imports.py`

- [ ] **Step 1: Inventory writes**

```powershell
rg -n "@(router|app)\.(post|put|patch|delete)" ml-platform/backend/app/api
rg -n "Project\.owner_id|project_id" ml-platform/backend/app/api
```

Classify every write as project-scoped, global admin, authentication, or non-project. Add reviewed project route/action pairs to the completeness test; no unclassified project write remains.

- [ ] **Step 2: Add a failing completeness test**

Assert every classified project write appears in its module's `PROJECT_WRITE_ACTIONS` mapping and uses the centralized access/audit boundary.

- [ ] **Step 3: Migrate the classified project writes**

Apply helpers to project-bound model-library/model/orchestration routes. Do not change global admin, authentication, compute-owner, knowledge-base-owner, or annotation-owner semantics unless the resource is actually project-bound.

- [ ] **Step 4: Verify and commit**

```powershell
python -m unittest tests.test_api_project_access tests.test_module_imports -v
git add ml-platform/backend/app/api ml-platform/backend/tests
git commit -m "feat: complete project write audit coverage"
```

### Task 9: Week 7 registration and final acceptance

**Files:**
- Modify: `ml-platform/backend/tests/week_manifest.py`
- Modify: `.github/workflows/ci.yml` when adding the production access integration entry
- Modify: `DEVELOPMENT_PLAN.md`, `PLATFORM_STATUS.md`, and shared experience

- [ ] **Step 1: Register tests under Week 7**

Add `test_project_access` and `test_api_project_access` exactly once. Observe manifest RED before registration and GREEN afterward.

- [ ] **Step 2: Run focused and Week 7 suites**

```powershell
python -m unittest tests.test_project_access tests.test_api_project_access tests.test_pipeline_scheduler tests.test_api_schedules tests.test_suite_manifest -v
python run_suite.py --week 7
```

- [ ] **Step 3: Run migration and full regressions**

```powershell
$db = Join-Path $env:TEMP ("week7-final-" + [guid]::NewGuid().ToString("N") + ".db")
$env:DATABASE_URL = "sqlite:///" + ($db -replace '\\','/')
alembic upgrade head
alembic upgrade head
alembic current
alembic check
python run_suite.py
git diff --check
```

- [ ] **Step 4: Run isolated WSL production integration**

Migrate clean PostgreSQL to `20260718_07`, run owner/editor/operator/viewer and audit transaction checks through the production image, inspect evidence, and remove only the isolated Compose project. Do not modify the user's default stack.

- [ ] **Step 5: Update docs and shared experience**

Record exact test counts, migration head, Docker evidence, audit coverage, risks, and the remote run URL. Week 7 becomes complete only when scheduler, roles/audit, local production integration, and remote CI are green.

- [ ] **Step 6: Commit, push, and monitor CI**

```powershell
git add .github/workflows/ci.yml ml-platform/backend/tests DEVELOPMENT_PLAN.md PLATFORM_STATUS.md
git commit -m "feat: complete week 7 roles and audit"
git push -u origin codex/week-6-experiment-training
```

Monitor GitHub Actions to completion and append any corrective evidence rather than rewriting history.

## Verification Checklist

- [ ] Four roles match the frozen matrix; owner is immutable and derived from `Project.owner_id`.
- [ ] Owned/joined projects appear once with `project_role`.
- [ ] All classified project writes use centralized permission and audit boundaries.
- [ ] Business success cannot commit without its success audit event.
- [ ] Denied/failed events are redacted and do not leak outsider project existence.
- [ ] Audit query is owner-only, filtered, paginated, and append-only.
- [ ] Alembic `20260718_07` double upgrade/current/check and downgrade pass.
- [ ] Week 1-6, scheduler, PostgreSQL integration, and remote CI are green.
