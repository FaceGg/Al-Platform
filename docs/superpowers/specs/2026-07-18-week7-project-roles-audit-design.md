# Week 7 Project Roles and Audit Design

**Status:** Approved for written-spec review

**Goal:** Add project-scoped collaboration roles and durable audit events while preserving the existing project owner contract and hidden-resource authorization behavior.

## Scope

This is the second Week 7 subsystem. It covers membership for already registered users, a fixed four-role matrix, centralized project authorization, write-operation audit events, member-management APIs, audit-query APIs, and migration of project-scoped backend access checks.

It does not include a membership frontend, email invitations, pending invitations, ownership transfer, multiple owners, SSO, enterprise notifications, or audit export/archival. These remain later-week work.

## Architecture

`Project.owner_id` remains the sole ownership source of truth. Non-owner access is stored in `ProjectMember`. A centralized `ProjectAccessService` resolves the actor's project role and checks named permissions. Project-owned API routes call this service instead of directly requiring `Project.owner_id == current_user.id`.

Auditable writes use an `AuditService` with explicit action/resource identifiers. Successful business changes and their `success` event commit in the same transaction. Permission denials against an existing project write a `denied` event before returning a stable 403. Unexpected failures after project resolution roll back the business transaction, then write a `failed` event in a new short transaction.

```text
authenticated request
    -> resolve project/resource
    -> ProjectAccessService.require(permission)
    -> mutate business state
    -> AuditService.record(success | denied | failed)
    -> commit
```

## Persistence Model

### `project_members`

- `id`: UUID primary key
- `project_id`: project foreign key with cascade delete
- `user_id`: user foreign key with cascade delete
- `role`: `editor`, `operator`, or `viewer`
- `created_by`: owner user foreign key
- `created_at`, `updated_at`

Constraints and indexes:

- Unique `(project_id, user_id)`.
- Check constraint limiting `role` to the three non-owner roles.
- Index `(user_id, project_id)` for accessible-project lists.
- The project owner is never inserted into this table.

### `audit_events`

- `id`: UUID primary key
- `project_id`: nullable project foreign key using `SET NULL`, preserving audit history after project deletion
- `actor_id`: nullable user foreign key using `SET NULL`, preserving history after user deletion
- `actor_username`: immutable username snapshot
- `action`: stable dotted action such as `project.member.add` or `schedule.backfill`
- `resource_type`: stable category such as `project`, `workflow`, `dataset`, `experiment`, `training_job`, `workflow_run`, or `schedule`
- `resource_id`: nullable UUID/string identity
- `result`: `success`, `denied`, or `failed`
- `request_id`: UUID correlation ID
- `source_ip`: nullable normalized client IP
- `changes`: JSON object containing a redacted change summary
- `error_code`: nullable stable code
- `created_at`: immutable server timestamp

Indexes cover `(project_id, created_at)`, `(project_id, action, created_at)`, `(project_id, actor_id, created_at)`, and `request_id`. Audit events have no update or delete API.

## Role and Permission Matrix

| Permission | owner | editor | operator | viewer |
|---|---:|---:|---:|---:|
| `project.read` | yes | yes | yes | yes |
| `project.update` / `project.delete` | yes | no | no | no |
| `member.manage` | yes | no | no | no |
| `resource.create` / `resource.update` / `resource.delete` | yes | yes | no | no |
| `execution.operate` | yes | yes | yes | no |
| `schedule.manage` | yes | yes | no | no |
| `schedule.operate` | yes | yes | yes | no |
| `audit.read` | yes | no | no | no |

`resource.*` covers workflows, datasets, experiments, training configuration, model artifacts bound to a project, and other project-owned definitions. `execution.operate` covers starting/cancelling workflow runs and starting/stopping/resuming training. `schedule.manage` covers schedule creation and configuration; `schedule.operate` covers pause, resume, backfill, and protected manual ticks.

The owner cannot be demoted, removed, or represented as a normal member. Ownership transfer is not exposed in this subsystem.

## Authorization Semantics

- A user with no membership receives the existing hidden-resource 404 behavior.
- A project member who can see the project but lacks the requested permission receives HTTP 403 with `PROJECT_PERMISSION_DENIED`.
- Missing users, duplicate membership, and owner-as-member requests use stable codes: `PROJECT_MEMBER_USER_NOT_FOUND`, `PROJECT_MEMBER_EXISTS`, and `PROJECT_OWNER_MEMBERSHIP_IMMUTABLE`.
- Owner and member role resolution is always server-side. JWTs continue to contain only the user identity; project roles are not cached in tokens.
- Global `User.role == "admin"` remains limited to current platform-admin endpoints and does not silently grant project membership.

## API Contract

### Membership

- `GET /api/projects/{project_id}/members`: owner-only member list including the owner as a synthetic `owner` entry.
- `POST /api/projects/{project_id}/members`: owner adds an existing user by `{username, role}`.
- `PATCH /api/projects/{project_id}/members/{user_id}`: owner changes a non-owner role.
- `DELETE /api/projects/{project_id}/members/{user_id}`: owner removes a non-owner member.

Accepted member roles are exactly `editor`, `operator`, and `viewer`. Payloads forbid extra fields. Usernames use the existing registered-user namespace; this subsystem sends no invitation or notification.

### Projects and Audit

- `GET /api/projects`: returns owned and joined projects without duplicates and includes the current actor's `project_role`.
- `GET /api/projects/{project_id}/audit-events`: owner-only, newest-first, with bounded pagination and optional `action`, `resource_type`, `actor_id`, `result`, `from_time`, and `to_time` filters.

Audit responses expose redacted changes, stable codes, correlation IDs, and timestamps. They never expose password hashes, JWTs, Secret values, object-storage credentials, full uploaded content, raw training data, or arbitrary request bodies.

## Audit Coverage

Every project-scoped write in these core modules records a stable action:

- Projects and members: create, update, delete, batch delete, add member, change role, remove member.
- Workflows and versions: create, save/update, delete, publish, restore, template instantiate.
- Datasets and artifacts: upload, batch upload, delete, export-triggering mutations.
- Experiments and training: create experiment, submit/resume/stop training, AutoML submission, TensorBoard session creation when it mutates session state.
- Workflow execution: start and cancel.
- Schedules: create, update, pause, resume, backfill, and protected tick.

Routes that do not resolve to a project, global admin operations, authentication, and read-only requests are outside this audit stream.

## Request Correlation and Redaction

Middleware accepts a valid `X-Request-ID` UUID or generates a new UUID, stores it on request state, and echoes it in the response header. The audit service reads the same ID.

The audit service uses an allowlist per action. `changes` contains only known safe fields, IDs, role names, state transitions, counts, and schedule policy values. Unknown values are omitted. Keys matching password, token, secret, credential, key, authorization, cookie, content, data, or path patterns are redacted recursively before persistence.

## Transaction and Failure Handling

- Success events are added to the same SQLAlchemy session before the business commit.
- Denied events are written only after an existing project and authenticated actor are known; outsider 404 probes do not create a project-visible event.
- Failed events are written after rollback through a short session created by the audit service. Error messages are normalized to stable codes and never persist raw connection strings or exception representations.
- Audit persistence failure aborts a successful business write. The platform must not report a mutation as successful without its required audit record.
- Audit rows are append-only at the API/service layer.

## Migration and Compatibility

Alembic adds both tables, constraints, indexes, and a complete downgrade after `20260718_06`. SQLite and PostgreSQL use the same role values and uniqueness rules. Local `Base.metadata.create_all` creates the new tables; no historical owner backfill is required because owner authorization remains derived from `Project.owner_id`.

Existing project-owner behavior must remain valid. Migration of API checks proceeds through shared project/resource resolvers so existing hidden-resource behavior does not change accidentally.

## Testing and Acceptance

1. Model and migration tests cover constraints, indexes, clean double upgrade/current/check, and downgrade.
2. Permission-service table tests cover all roles and permissions, owner precedence, missing membership, and no global-admin bypass.
3. Membership API tests cover add/list/change/remove, existing-user lookup, duplicate membership, owner immutability, and cross-project hiding.
4. Project-list tests cover owned/joined union, no duplicates, and `project_role`.
5. Audit tests cover success/denied/failed, same-transaction rollback, short-session failure recording, request correlation, recursive redaction, filters, pagination, and append-only behavior.
6. Core project APIs are tested once per role for read, definition mutation, execution operation, schedule management, and schedule operation.
7. Existing owner-focused tests remain green while new Week 7 modules receive exactly one manifest owner.
8. Full backend, clean migration, Compose production integration, and remote CI must pass before Week 7 is marked complete.

## Remaining Week 7 Gate

This subsystem and the already implemented Pipeline scheduler together form the Week 7 deliverable. Week 7 remains `in progress` until project roles/audit implementation, local production verification, and remote GitHub Actions acceptance all succeed.
