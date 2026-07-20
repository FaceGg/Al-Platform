# Week 10 Security, Platform Audit, and Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining cross-user authorization gaps, add an independent platform security audit stream, and deliver transactional in-app, WeCom, email, and generic Webhook notifications without coupling notification delivery to the Week 9 inference rollout state machine.

**Architecture:** Reuse `ProjectAccessService` for project roles and hidden-resource semantics, and add a separate `ResourceAccessService` for user-private and indirect resource ownership. Week 9 owns the frozen `DomainEvent` and `DomainEventRecorder` protocol; Week 10 implements an `OutboxDomainEventRecorder` that only adds and flushes an outbox row in the caller's transaction. A Celery notification worker claims outbox rows atomically, creates idempotent per-channel deliveries, and invokes adapters with encrypted endpoint configuration and SSRF-safe network rules.

**Tech Stack:** FastAPI, Pydantic v2 strict schemas, SQLAlchemy 2, Alembic, PostgreSQL/SQLite, Celery/Redis, `cryptography` Fernet, `requests`, stdlib `smtplib`, React 18, TypeScript, Ant Design, Vitest, unittest, Playwright, Docker Compose.

---

## Scope and Dependency Gates

- Every checkbox is one 2-5 minute action. When a task touches several routes or adapters, execute and verify the shown route/adapter slice before moving to the next checkbox; do not batch unrelated files into one unverified edit.
- Week 7 project roles and `AuditEvent` remain the project-domain source of truth. Do not grant project access from `User.role == "admin"`; an admin without membership remains an outsider for project-bound resources.
- The Week 10 Alembic revision is exactly `20260720_10_security_notifications` with `down_revision = "20260720_09_production_inference"`. Do not create a second head or edit the Week 9 revision.
- Consume the frozen Week 9 `DomainEvent` at `app/events/domain.py` with fields `event_id`, `idempotency_key`, `event_type`, `severity`, `occurred_at`, `project_id`, `actor_id`, `resource_type`, `resource_id`, and `payload`.
- Consume the exact protocol method `DomainEventRecorder.record(self, db: Session, event: DomainEvent) -> None`.
- `OutboxDomainEventRecorder.record` must not call `commit`; business state and the outbox row commit together. Notification code must not import or mutate `InferenceDeployment`, `DeploymentRollout`, or Week 9 runtime state.
- Final production verification waits for the Week 9 migration and event producer to exist. Local unit tests use an in-memory `DomainEvent` and a fake recorder implementing the frozen protocol.

## File Map

### Backend

- Create `ml-platform/backend/app/models/platform_audit.py`: append-only `PlatformAuditEvent`.
- Create `ml-platform/backend/app/models/notifications.py`: endpoint, subscription, outbox, delivery, and in-app notification models.
- Create `ml-platform/backend/app/schemas/platform_audit.py` and `app/schemas/notifications.py`: strict API contracts.
- Create `ml-platform/backend/app/services/resource_access.py`: owner and indirect-resource resolvers.
- Create `ml-platform/backend/app/services/platform_audit.py`: stable audit actions, redaction, and transaction helpers.
- Create `ml-platform/backend/app/services/notification_crypto.py`: Fernet configuration encryption.
- Create `ml-platform/backend/app/services/notification_outbox.py`: concrete Week 9 recorder, safe payload filtering, and claim helpers.
- Create `ml-platform/backend/app/services/notification_channels.py`: in-app, WeCom, email, and Webhook adapters.
- Create `ml-platform/backend/app/services/webhook_security.py`: DNS/IP/redirect/size/timeout/signing policy.
- Create `ml-platform/backend/app/tasks/notification_tasks.py`: Celery fan-out, retry, and dead-letter handling.
- Create `ml-platform/backend/app/api/platform_security.py` and `app/api/notifications.py`.
- Create `ml-platform/backend/alembic/versions/20260720_10_security_notifications.py` with a complete downgrade.
- Modify `ml-platform/backend/app/api/auth.py`, `users.py`, `compute.py`, `annotations.py`, `platform_api.py`, `project_access.py`, and `project_security.py`.
- Modify `ml-platform/backend/app/services/project_access.py`, `app/config.py`, `app/main.py`, `app/tasks/celery_app.py`, `requirements.txt`, and `.env.example`.
- Create `ml-platform/backend/tests/test_security_hardening.py`, `test_platform_audit.py`, `test_notification_models.py`, `test_notification_outbox.py`, `test_notification_channels.py`, `test_api_notifications.py`, and `test_notification_production_stack.py`.
- Modify `ml-platform/backend/tests/test_api_platform.py`, `test_api_compute.py`, `test_api_users.py`, and `week_manifest.py`.

### Frontend

- Create `ml-platform/frontend/src/api/securityNotifications.ts` and `securityNotifications.test.ts`.
- Create `ml-platform/frontend/src/components/NotificationCenter.tsx` and `NotificationCenter.test.tsx`.
- Create `ml-platform/frontend/src/pages/ProjectGovernanceTabs.tsx` and `ProjectGovernanceTabs.test.tsx`.
- Modify `ml-platform/frontend/src/pages/ProjectDetailPage.tsx`, `src/components/AppLayout.tsx`, and `src/i18n/index.tsx`.
- Create `ml-platform/frontend/e2e/security-notifications.spec.ts`.

### Serial Integration

- The primary integrator modifies `docker-compose.yml`, `.github/workflows/ci.yml`, shared settings/startup registration, Alembic order, week manifests, frontend routes/translations, and status documents after feature tests pass.
- Update `DEVELOPMENT_PLAN.md`, `PLATFORM_STATUS.md`, and `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md` only after implementation verification has exact evidence.

### Task 1: Freeze Security Regression Contracts

**Files:**
- Create: `ml-platform/backend/tests/test_security_hardening.py`
- Modify: `ml-platform/backend/tests/test_api_users.py`
- Modify: `ml-platform/backend/tests/test_api_compute.py`
- Modify: `ml-platform/backend/tests/test_api_platform.py`

- [ ] **Step 1: Write failing self-registration tests**

```python
def test_registration_rejects_platform_role_field(self):
    response = self.client.post(
        "/api/auth/register",
        json={"username": "role-probe", "password": "safe-password", "role": "admin"},
    )
    self.assertEqual(response.status_code, 422)

def test_registration_without_role_creates_engineer(self):
    response = self.client.post(
        "/api/auth/register",
        json={"username": "ordinary-user", "password": "safe-password"},
    )
    self.assertEqual(response.status_code, 200)
    user = self.db.query(User).filter(User.username == "ordinary-user").one()
    self.assertEqual(user.role, "engineer")
```

- [ ] **Step 2: Write failing cross-user owner tests**

```python
def test_compute_update_hides_other_owner(self):
    response = self.client.put(
        f"/api/compute/nodes/{self.other_node.id}",
        json={"name": "probe"},
    )
    self.assertEqual(response.status_code, 404)

def test_annotation_sample_and_auto_label_hide_other_owner(self):
    sample = self.client.get(f"/api/annotations/tasks/{self.other_task.id}/samples")
    auto = self.client.post(f"/api/annotations/tasks/{self.other_task.id}/auto-label")
    self.assertEqual(sample.status_code, 404)
    self.assertEqual(auto.status_code, 404)

def test_platform_api_list_requires_auth_and_hides_private_rows(self):
    self.assertEqual(self.client.get("/api/platform/apis").status_code, 401)
    response = self.client.get("/api/platform/apis", headers=self.other_headers)
    ids = {item["id"] for item in response.json()["items"]}
    self.assertNotIn(str(self.private_api.id), ids)
```

- [ ] **Step 3: Run focused tests and prove RED**

Run from `E:\codex_workspace\agent_spot_welding\ml-platform\backend`:

```powershell
python -m unittest tests.test_security_hardening tests.test_api_users tests.test_api_compute tests.test_api_platform -v
```

Expected: registration accepts the `role` field, and at least one foreign-resource mutation returns success instead of hidden `404`.

- [ ] **Step 4: Freeze the resource matrix in executable data**

```python
RESOURCE_CASES = (
    ("compute_node", "read", "owner", 200),
    ("compute_node", "read", "outsider", 404),
    ("annotation_task", "update", "owner", 200),
    ("annotation_task", "update", "outsider", 404),
    ("platform_api", "update", "owner", 200),
    ("platform_api", "update", "outsider", 404),
)
```

- [ ] **Step 5: Keep Week 1 fixtures compatible**

Replace role-bearing public-registration fixtures with the strict two-field payload. Create the bootstrap admin through application lifespan or direct database fixtures, and preserve unrelated assertions in the existing tests.

```python
client.post(
    "/api/auth/register",
    json={"username": "platform-test-user", "password": "admin12345"},
)
admin = User(username="platform-admin", password_hash="hash", role="admin")
db.add(admin)
db.commit()
```

### Task 2: Harden Authentication and Platform User Administration

**Files:**
- Modify: `ml-platform/backend/app/api/auth.py`
- Modify: `ml-platform/backend/app/api/users.py`
- Create: `ml-platform/backend/app/schemas/platform_audit.py`
- Create: `ml-platform/backend/app/services/platform_audit.py`
- Test: `ml-platform/backend/tests/test_security_hardening.py`
- Test: `ml-platform/backend/tests/test_platform_audit.py`

- [ ] **Step 1: Define strict request and platform-role contracts**

```python
class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=256)


PLATFORM_ROLES = frozenset({"admin", "engineer", "operator", "viewer"})
```

- [ ] **Step 2: Write platform audit RED tests**

```python
def test_admin_role_change_writes_platform_event(self):
    response = self.client.put(
        f"/api/admin/users/{self.target.id}/role",
        params={"role": "operator"},
        headers=self.admin_headers,
    )
    self.assertEqual(response.status_code, 200)
    event = self.db.query(PlatformAuditEvent).filter(
        PlatformAuditEvent.action == "platform.user.role_change"
    ).one()
    self.assertEqual(event.result, "success")
    self.assertEqual(event.changes, {"previous_role": "engineer", "role": "operator"})

def test_failed_login_writes_redacted_platform_event(self):
    response = self.client.post(
        "/api/auth/login",
        data={"username": "audit-user", "password": "wrong-password"},
    )
    self.assertEqual(response.status_code, 401)
    event = self.db.query(PlatformAuditEvent).filter(
        PlatformAuditEvent.action == "auth.login.failed"
    ).order_by(PlatformAuditEvent.created_at.desc()).first()
    self.assertEqual(event.result, "failed")
    self.assertNotIn("wrong-password", str(event.changes))
```

- [ ] **Step 3: Run RED**

```powershell
python -m unittest tests.test_security_hardening tests.test_platform_audit -v
```

Expected: strict request schemas and platform audit service are missing.

- [ ] **Step 4: Implement platform audit intent and safe row creation**

```python
@dataclass(frozen=True)
class PlatformAuditIntent:
    action: str
    resource_type: str
    resource_id: str | None = None
    changes: dict[str, object] = field(default_factory=dict)


def record_platform_event(db, *, actor, request, intent, result, error_code=None):
    request_id, source_ip = audit_request_context(request)
    db.add(PlatformAuditEvent(
        actor_id=getattr(actor, "id", None),
        actor_username=getattr(actor, "username", "anonymous"),
        action=intent.action,
        resource_type=intent.resource_type,
        resource_id=intent.resource_id,
        result=result,
        request_id=request_id,
        source_ip=source_ip,
        changes=redact_changes(intent.changes, allowed=set(intent.changes)),
        error_code=error_code,
    ))
```

Admin mutations add the success event before their single commit. Failed mutations rollback and write only a stable code through a fresh short session. Login failures store only the attempted username and request context.

- [ ] **Step 5: Enforce strict self-registration**

```python
@router.post("/register")
def register(data: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, {"code": "USERNAME_EXISTS"})
    user = User(username=data.username, password_hash=pwd_context.hash(data.password), role="engineer")
    db.add(user)
    db.flush()
    record_platform_event(
        db,
        actor=user,
        request=request,
        intent=PlatformAuditIntent("auth.register", "user", str(user.id), {"username": user.username}),
        result="success",
    )
    db.commit()
    return {"message": "User created", "user_id": str(user.id)}
```

Validate admin role changes against `PLATFORM_ROLES`, reject self-demotion and self-deletion, and audit `platform.user.role_change` and `platform.user.delete`.

- [ ] **Step 6: Verify authentication and admin audit GREEN**

```powershell
python -m unittest tests.test_security_hardening tests.test_platform_audit tests.test_api_users -v
```

Expected: role-bearing registration returns `422`; all normal registrations are engineer; success/failed auth and admin actions each create one redacted platform event.

### Task 3: Add Centralized Resource Ownership Resolvers

**Files:**
- Create: `ml-platform/backend/app/services/resource_access.py`
- Modify: `ml-platform/backend/app/api/compute.py`
- Modify: `ml-platform/backend/app/api/annotations.py`
- Modify: `ml-platform/backend/app/api/platform_api.py`
- Modify: `ml-platform/backend/app/api/project_access.py`
- Modify: `ml-platform/backend/app/api/project_security.py`
- Test: `ml-platform/backend/tests/test_security_hardening.py`

- [ ] **Step 1: Write direct and indirect resolver RED tests**

```python
def test_resolver_returns_owner_and_hides_foreign_resource(self):
    row = ResourceAccessService().require_owned(self.db, ComputeNode, self.node.id, self.owner.id)
    self.assertEqual(row.owner_id, self.owner.id)
    with self.assertRaises(ResourceAccessError) as denied:
        ResourceAccessService().require_owned(self.db, ComputeNode, self.node.id, self.outsider.id)
    self.assertEqual(denied.exception.code, "RESOURCE_NOT_FOUND")

def test_annotation_sample_resolves_task_owner(self):
    with self.assertRaises(ResourceAccessError):
        ResourceAccessService().require_annotation_sample(self.db, self.sample.id, self.outsider.id)

def test_member_denial_happens_before_target_lookup(self):
    self.current_user = self.viewer
    response = self.client.post(
        f"/api/projects/{self.project.id}/members",
        json={"username": "known-target", "role": "viewer"},
    )
    self.assertEqual(response.status_code, 403)
    self.assertEqual(response.json()["detail"]["code"], "PROJECT_PERMISSION_DENIED")
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_security_hardening.TestResourceAccess -v
```

Expected: `app.services.resource_access` is not importable.

- [ ] **Step 3: Implement fail-closed resolvers**

```python
class ResourceAccessError(Exception):
    def __init__(self, code: str = "RESOURCE_NOT_FOUND"):
        super().__init__(code)
        self.code = code


class ResourceAccessService:
    def require_owned(self, db, model, resource_id, user_id):
        row = db.query(model).filter(model.id == resource_id).first()
        if row is None or row.owner_id != user_id:
            raise ResourceAccessError()
        return row

    def require_annotation_sample(self, db, sample_id, user_id):
        sample = db.query(AnnotationResult).filter(AnnotationResult.id == sample_id).first()
        if sample is None:
            raise ResourceAccessError()
        task = db.query(AnnotationTask).filter(AnnotationTask.id == sample.task_id).first()
        if task is None or task.owner_id != user_id:
            raise ResourceAccessError()
        return sample, task
```

Add `require_owned_project_resource` for models with `project_id`: recover the project, resolve membership through `ProjectAccessService`, then return the resource. Unknown model classes and permission names fail closed.

- [ ] **Step 4: Apply checks before target or provider access**

Use `require_owned` for ComputeNode/EdgeDevice details, update, and delete. Resolve AnnotationTask before sample listing/auto-label and resolve sample-to-task before update. Require authentication for PlatformAPI list/stats, return only `owner_id == current_user.id OR is_public == true`, and require owner for update/delete. Keep `labeling.py` as a stateless computation API; it receives no resource ID and is outside this ownership resolver.

```python
node = ResourceAccessService().require_owned(
    db, ComputeNode, uuid.UUID(node_id), current_user.id,
)

task = ResourceAccessService().require_owned(
    db, AnnotationTask, uuid.UUID(task_id), current_user.id,
)

query = db.query(PlatformAPI).filter(
    or_(PlatformAPI.owner_id == current_user.id, PlatformAPI.is_public.is_(True))
)
```

For project member add/change/remove, enter the existing audited `member.manage` boundary before querying the target `User` or `ProjectMember`. A viewer always receives `403` and an outsider always receives hidden `404`, regardless of whether the probed username/user ID exists. Preserve the Week 7 denied audit event for visible members.

```python
access = ProjectAccessService().resolve(db, project_id, current_user.id)
with _audit_service(db).project_action(
    db,
    request=request,
    actor=current_user,
    access=access,
    permission="member.manage",
    intent=intent,
    allowed_changes={"role"},
):
    target = db.query(User).filter(User.username == data.username).first()
    if target is None:
        raise HTTPException(404, {"code": "PROJECT_MEMBER_USER_NOT_FOUND"})
    db.add(ProjectMember(project_id=project_id, user_id=target.id, role=data.role))
```

- [ ] **Step 5: Verify IDOR and non-disclosure GREEN**

```powershell
python -m unittest tests.test_security_hardening tests.test_api_compute tests.test_api_platform -v
```

Expected: owner operations preserve success codes; foreign IDs return `404` before payload/provider access; private APIs disappear from another user's list while public APIs remain visible to authenticated users.

### Task 4: Persist Platform Security Audit Events and Query API

**Files:**
- Create: `ml-platform/backend/app/models/platform_audit.py`
- Create: `ml-platform/backend/app/schemas/platform_audit.py`
- Create: `ml-platform/backend/app/api/platform_security.py`
- Modify: `ml-platform/backend/app/main.py`
- Test: `ml-platform/backend/tests/test_platform_audit.py`

- [ ] **Step 1: Write model and query RED tests**

```python
def test_platform_audit_preserves_actor_snapshot_after_delete(self):
    event = PlatformAuditEvent(
        actor_id=self.user.id,
        actor_username=self.user.username,
        action="platform.user.role_change",
        resource_type="user",
        resource_id=str(self.user.id),
        result="success",
        request_id=uuid.uuid4(),
        changes={"role": "operator"},
    )
    self.db.add(event)
    self.db.commit()
    self.db.delete(self.user)
    self.db.commit()
    stored = self.db.get(PlatformAuditEvent, event.id)
    self.assertIsNone(stored.actor_id)
    self.assertEqual(stored.actor_username, "audit-user")

def test_security_audit_is_admin_only_and_filtered(self):
    denied = self.client.get("/api/admin/security-audit", headers=self.engineer_headers)
    self.assertEqual(denied.status_code, 403)
    allowed = self.client.get(
        "/api/admin/security-audit",
        params={"action": "auth.login.failed", "result": "failed", "limit": 10},
        headers=self.admin_headers,
    )
    self.assertEqual(allowed.status_code, 200)
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_platform_audit -v
```

Expected: the model and `/api/admin/security-audit` route do not exist.

- [ ] **Step 3: Implement the append-only model**

```python
class PlatformAuditEvent(Base):
    __tablename__ = "platform_audit_events"
    __table_args__ = (
        CheckConstraint("result IN ('success', 'denied', 'failed')", name="ck_platform_audit_result"),
        Index("ix_platform_audit_created", "created_at"),
        Index("ix_platform_audit_action_created", "action", "created_at"),
        Index("ix_platform_audit_actor_created", "actor_id", "created_at"),
        Index("ix_platform_audit_request_id", "request_id"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_username = Column(String(64), nullable=False)
    action = Column(String(128), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=True)
    result = Column(String(16), nullable=False)
    request_id = Column(UUID(as_uuid=True), nullable=False)
    source_ip = Column(String(64), nullable=True)
    changes = Column(JSON, nullable=False, default=dict)
    error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
```

- [ ] **Step 4: Implement strict paginated query API**

Expose newest-first rows with `offset >= 0`, `1 <= limit <= 200`, and optional `action`, `resource_type`, `actor_id`, `result`, `from_time`, and `to_time`. Require `get_current_admin`; do not expose update/delete endpoints or raw request bodies.

```python
@router.get("/api/admin/security-audit", response_model=PlatformAuditEventList)
def list_platform_audit(
    action: str | None = None,
    result: Literal["success", "denied", "failed"] | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    query = db.query(PlatformAuditEvent)
    if action is not None:
        query = query.filter(PlatformAuditEvent.action == action)
    if result is not None:
        query = query.filter(PlatformAuditEvent.result == result)
    total = query.count()
    items = query.order_by(
        PlatformAuditEvent.created_at.desc(), PlatformAuditEvent.id.desc()
    ).offset(offset).limit(limit).all()
    return {"items": items, "total": total, "offset": offset, "limit": limit}
```

- [ ] **Step 5: Register and verify the platform audit stream**

```powershell
python -m unittest tests.test_platform_audit tests.test_api_users -v
```

Expected: admin filters pass, non-admins get `403`, actor deletion retains history, and the existing project `AuditEvent` model/router are unchanged.

### Task 5: Add Notification Settings, Models, and Linear Migration

**Files:**
- Modify: `ml-platform/backend/app/config.py`
- Modify: `ml-platform/backend/requirements.txt`
- Modify: `ml-platform/backend/.env.example`
- Create: `ml-platform/backend/app/models/notifications.py`
- Create: `ml-platform/backend/alembic/versions/20260720_10_security_notifications.py`
- Modify: `ml-platform/backend/app/main.py`
- Create: `ml-platform/backend/tests/test_notification_models.py`

- [ ] **Step 1: Write configuration and model RED tests**

```python
def test_production_requires_notification_master_key(self):
    values = complete_production_settings()
    values.pop("notification_master_key", None)
    with self.assertRaises(ValueError):
        Settings(**values)

def test_notification_endpoint_kind_and_outbox_keys_are_constrained(self):
    self.db.add(NotificationEndpoint(
        project_id=self.project.id,
        kind="sms",
        name="invalid",
        destination_hint="none",
        encrypted_config="ciphertext",
    ))
    with self.assertRaises(IntegrityError):
        self.db.commit()
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_notification_models -v
```

Expected: notification settings, models, and revision are absent.

- [ ] **Step 3: Add production-safe settings and dependency**

Add `notification_master_key`/`notification_master_key_file` as an excluded `SecretStr` pair, SMTP host/port/user/password/from/TLS fields, `notification_max_payload_bytes=65536`, `notification_delivery_max_attempts=5`, `notification_webhook_timeout_seconds=10`, and `notification_webhook_allowlist` as a non-secret list. Resolve the secret-file pair like existing MinIO/inference secrets; production requires a valid Fernet key. Pin `cryptography` in `requirements.txt`.

```python
notification_master_key: SecretStr | None = Field(default=None, exclude=True)
notification_master_key_file: str | None = Field(default=None, repr=False, exclude=True)
smtp_host: str | None = None
smtp_port: int = Field(default=587, ge=1, le=65535)
smtp_username: SecretStr | None = Field(default=None, exclude=True)
smtp_password: SecretStr | None = Field(default=None, exclude=True)
smtp_from: str | None = None
smtp_use_tls: bool = True
notification_max_payload_bytes: int = Field(default=65536, ge=1024, le=1048576)
notification_delivery_max_attempts: int = Field(default=5, ge=1, le=20)
notification_webhook_timeout_seconds: int = Field(default=10, ge=1, le=30)
notification_webhook_allowlist: list[str] = Field(default_factory=list)
```

```text
NOTIFICATION_MASTER_KEY_FILE=/run/secrets/notification-master-key
SMTP_HOST=smtp.example.invalid
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_FROM=ml-platform@example.invalid
NOTIFICATION_WEBHOOK_ALLOWLIST=
```

Do not put a real key, mailbox, WeCom token, or callback URL in `.env.example`.

- [ ] **Step 4: Implement endpoint and subscription tables**

```python
class NotificationEndpoint(Base):
    __tablename__ = "notification_endpoints"
    __table_args__ = (
        CheckConstraint("kind IN ('in_app', 'wecom', 'email', 'webhook')", name="ck_notification_endpoint_kind"),
        UniqueConstraint("project_id", "name", name="uq_notification_endpoint_project_name"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(16), nullable=False)
    name = Column(String(128), nullable=False)
    destination_hint = Column(String(256), nullable=False, default="")
    encrypted_config = Column(Text, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
```

`NotificationSubscription` stores project/endpoint IDs, event types, minimum severity, recipient roles, explicit recipient IDs, enabled state, creator, and timestamps. Validate the endpoint belongs to the same project.

```python
class NotificationSubscription(Base):
    __tablename__ = "notification_subscriptions"
    __table_args__ = (
        CheckConstraint("minimum_severity IN ('info', 'warning', 'critical')", name="ck_notification_subscription_severity"),
        Index("ix_notification_subscription_project_enabled", "project_id", "enabled"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    endpoint_id = Column(UUID(as_uuid=True), ForeignKey("notification_endpoints.id", ondelete="CASCADE"), nullable=False)
    event_types = Column(JSON, nullable=False, default=list)
    minimum_severity = Column(String(16), nullable=False, default="info")
    recipient_roles = Column(JSON, nullable=False, default=list)
    recipient_user_ids = Column(JSON, nullable=False, default=list)
    enabled = Column(Boolean, nullable=False, default=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
```

- [ ] **Step 5: Implement outbox, delivery, and in-app tables**

`NotificationOutbox` has unique `event_id` and `idempotency_key`, the safe envelope, status, attempts, `next_attempt_at`, `claimed_at`, stable `last_error_code`, and timestamps. `NotificationDelivery` has outbox/subscription/endpoint IDs, unique deterministic delivery key, status, attempts, next attempt, bounded provider metadata, stable error code, and timestamps. `InAppNotification` has recipient/project/event identity, event type/severity, safe title/body/payload, read/archive timestamps, and created time. Use `SET NULL` for actor/creator history and `CASCADE` only for project-owned configuration.

```python
class NotificationOutbox(Base):
    __tablename__ = "notification_outbox"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(UUID(as_uuid=True), nullable=False, unique=True)
    idempotency_key = Column(String(256), nullable=False, unique=True)
    event_type = Column(String(128), nullable=False)
    severity = Column(String(16), nullable=False)
    occurred_at = Column(DateTime, nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(128), nullable=True)
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(16), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    last_error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    outbox_id = Column(UUID(as_uuid=True), ForeignKey("notification_outbox.id", ondelete="CASCADE"), nullable=False)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("notification_subscriptions.id", ondelete="SET NULL"), nullable=True)
    endpoint_id = Column(UUID(as_uuid=True), ForeignKey("notification_endpoints.id", ondelete="SET NULL"), nullable=True)
    idempotency_key = Column(String(64), nullable=False, unique=True)
    status = Column(String(16), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    provider_status = Column(Integer, nullable=True)
    provider_metadata = Column(JSON, nullable=False, default=dict)
    last_error_code = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class InAppNotification(Base):
    __tablename__ = "in_app_notifications"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipient_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    event_id = Column(UUID(as_uuid=True), nullable=False)
    event_type = Column(String(128), nullable=False)
    severity = Column(String(16), nullable=False)
    title = Column(String(256), nullable=False)
    body = Column(Text, nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    read_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
```

- [ ] **Step 6: Write the exact linear Alembic revision**

```python
revision = "20260720_10_security_notifications"
down_revision = "20260720_09_production_inference"
branch_labels = None
depends_on = None
```

Create `platform_audit_events` plus all five notification tables, constraints, and indexes with explicit `op.create_table` and `op.create_index`. Drop in reverse dependency order. Do not call metadata helpers from migration code.

- [ ] **Step 7: Verify migration ordering and downgrade**

```powershell
alembic upgrade head
alembic current
alembic check
alembic downgrade 20260720_09_production_inference
alembic upgrade head
python -m unittest tests.test_notification_models -v
```

Expected: current is `20260720_10_security_notifications`, check reports no pending operations, downgrade removes only Week 10 objects, and re-upgrade succeeds.

### Task 6: Implement Encryption, SSRF Guards, and Channel Adapters

**Files:**
- Create: `ml-platform/backend/app/services/notification_crypto.py`
- Create: `ml-platform/backend/app/services/webhook_security.py`
- Create: `ml-platform/backend/app/services/notification_channels.py`
- Create: `ml-platform/backend/tests/test_notification_channels.py`

- [ ] **Step 1: Write crypto and network RED tests**

```python
def test_endpoint_config_round_trip_never_exposes_plaintext(self):
    config = {"url": "https://hooks.example.invalid/x", "secret": "test-only"}
    ciphertext = encrypt_config(config, self.master_key)
    self.assertNotIn("test-only", ciphertext)
    self.assertEqual(decrypt_config(ciphertext, self.master_key)["secret"], "test-only")

def test_webhook_rejects_loopback_private_metadata_and_schemes(self):
    blocked = ("http://127.0.0.1/x", "http://10.0.0.2/x", "http://169.254.169.254/latest", "file:///tmp/x")
    for url in blocked:
        with self.subTest(url=url):
            with self.assertRaises(WebhookSecurityError):
                validate_webhook_url(url, resolve=static_resolution)
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_notification_channels -v
```

Expected: crypto and Webhook security modules are not importable.

- [ ] **Step 3: Implement Fernet at the smallest boundary**

```python
def encrypt_config(config: dict[str, object], master_key: SecretStr) -> str:
    raw = json.dumps(config, separators=(",", ":"), sort_keys=True).encode("utf-8")
    token = Fernet(master_key.get_secret_value().encode("ascii")).encrypt(raw)
    return token.decode("ascii")


def decrypt_config(token: str, master_key: SecretStr) -> dict[str, object]:
    raw = Fernet(master_key.get_secret_value().encode("ascii")).decrypt(token.encode("ascii"))
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise NotificationCredentialError("NOTIFICATION_CREDENTIAL_INVALID")
    return value
```

Never log encrypted/decrypted config, SMTP password, WeCom key, signing secret, custom request headers, or provider body.

- [ ] **Step 4: Implement URL and bounded-request policy**

Accept HTTPS, parse DNS answers with `socket.getaddrinfo`, and reject loopback, private, link-local, multicast, unspecified, metadata, userinfo, fragments, and disallowed ports. External requests use `allow_redirects=False`, one request, connect/read timeout, and 64 KiB canonical JSON. WeCom accepts only official hosts and documented robot/application paths. Re-resolve immediately before connect to limit DNS rebinding exposure.

- [ ] **Step 5: Implement adapter protocol and result contract**

```python
@dataclass(frozen=True)
class DeliveryResult:
    status: Literal["sent", "retry", "failed"]
    error_code: str | None = None
    provider_status: int | None = None


class NotificationAdapter(Protocol):
    def send(self, *, endpoint: NotificationEndpoint, event: DomainEvent, delivery_key: str) -> DeliveryResult:
        return DeliveryResult(status="failed", error_code="NOTIFICATION_ADAPTER_ABSTRACT")
```

Implement in-app as a database insert, WeCom as bounded JSON, email through TLS SMTP with recipient cap, and Webhook with optional HMAC-SHA256 over canonical JSON. Every adapter receives only safe event fields.

- [ ] **Step 6: Verify channel contracts GREEN**

```powershell
python -m unittest tests.test_notification_channels -v
```

Expected: encryption, redaction, WeCom host restrictions, Webhook DNS/IP/redirect checks, timeout/body limits, email limits, deterministic signing, and retry/permanent mappings pass.

### Task 7: Implement the Week 9 Event Recorder and Transactional Outbox

**Files:**
- Create: `ml-platform/backend/app/services/notification_outbox.py`
- Modify: Week 9 `ml-platform/backend/app/services/inference_deployment.py` only at recorder injection/call sites.
- Create: `ml-platform/backend/tests/test_notification_outbox.py`
- Test: `ml-platform/backend/tests/test_inference_deployment.py`

- [ ] **Step 1: Write recorder atomicity RED test**

```python
def test_recorder_adds_safe_outbox_without_commit(self):
    event = DomainEvent(
        event_id=uuid.uuid4(),
        idempotency_key="rollout-1-completed",
        event_type="rollout.completed",
        severity="info",
        occurred_at=datetime.now(timezone.utc),
        project_id=self.project.id,
        actor_id=self.owner.id,
        resource_type="deployment",
        resource_id=str(self.deployment.id),
        payload={"revision_id": str(self.revision.id), "storage_uri": "must-drop"},
    )
    OutboxDomainEventRecorder().record(self.db, event)
    self.assertEqual(self.db.query(NotificationOutbox).one().payload, {"revision_id": str(self.revision.id)})
    self.db.rollback()
    self.assertEqual(self.db.query(NotificationOutbox).count(), 0)
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_notification_outbox -v
```

Expected: recorder and outbox services are missing.

- [ ] **Step 3: Implement safe payload filtering and recorder**

```python
SAFE_EVENT_KEYS = frozenset({
    "revision_id", "model_version_id", "deployment_id", "error_code", "threshold", "state",
})


class OutboxDomainEventRecorder:
    def record(self, db: Session, event: DomainEvent) -> None:
        row = NotificationOutbox(
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            event_type=event.event_type,
            severity=event.severity,
            occurred_at=event.occurred_at.replace(tzinfo=None),
            project_id=event.project_id,
            actor_id=event.actor_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            payload=redact_changes(event.payload, allowed=set(SAFE_EVENT_KEYS)),
            status="pending",
        )
        db.add(row)
        db.flush()
```

Treat only an existing `(event_id, idempotency_key)` unique collision as already recorded. Re-raise unrelated integrity errors. Do not commit or dispatch Celery.

- [ ] **Step 4: Connect Week 9 producers by dependency injection**

The Week 9 service accepts a `DomainEventRecorder` and calls `record(db, event)` for rollout started/failed/completed, rollback completed, runtime load failed, rate-limit threshold, and error-rate threshold events in the same domain transaction. Week 10 does not alter rollout transitions or runtime calls.

- [ ] **Step 5: Verify transaction and duplicate behavior**

```powershell
python -m unittest tests.test_notification_outbox tests.test_inference_deployment -v
```

Expected: successful domain transition has one outbox row, rollback has none, duplicate idempotency is suppressed, and Week 9 state assertions remain green.

### Task 8: Build Claiming, Delivery, Retry, and Dead-Letter Tasks

**Files:**
- Create: `ml-platform/backend/app/tasks/notification_tasks.py`
- Modify: `ml-platform/backend/app/tasks/celery_app.py`
- Modify: `ml-platform/backend/app/main.py`
- Test: `ml-platform/backend/tests/test_notification_outbox.py`
- Test: `ml-platform/backend/tests/test_notification_production_stack.py`

- [ ] **Step 1: Write claim, idempotency, and dead-letter RED tests**

```python
def test_claim_is_single_winner_and_delivery_is_idempotent(self):
    self.assertTrue(claim_outbox(self.db, self.outbox.id))
    self.assertFalse(claim_outbox(self.db, self.outbox.id))
    self.assertEqual(deliver_notifications(self.outbox.id), "sent")
    self.assertEqual(deliver_notifications(self.outbox.id), "sent")
    self.assertEqual(self.db.query(NotificationDelivery).count(), 1)

def test_transient_error_exhaustion_creates_one_operator_alert(self):
    self.adapter.result = DeliveryResult("retry", "WEBHOOK_TIMEOUT")
    for attempt in range(settings.notification_delivery_max_attempts):
        run_due_delivery(self.delivery.id, now=self.base_time + timedelta(minutes=attempt + 1))
    self.assertEqual(self.db.get(NotificationDelivery, self.delivery.id).status, "dead_letter")
    count = self.db.query(InAppNotification).filter(
        InAppNotification.event_type == "notification.dead_letter"
    ).count()
    self.assertEqual(count, 1)
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_notification_outbox -v
```

Expected: claim and delivery task functions are missing.

- [ ] **Step 3: Implement atomic claim and subscription fan-out**

Use `SELECT FOR UPDATE SKIP LOCKED` on PostgreSQL and conditional update on SQLite. Claim due `pending` rows, persist `processing`, and commit before external I/O. Resolve active subscriptions by event type/severity/project. Recipient roles resolve owner-first; explicit recipients must be project members. Delivery idempotency key is SHA-256 of `event_id:subscription_id:endpoint_id`.

- [ ] **Step 4: Implement bounded retry schedule**

```python
def next_retry_at(attempt: int, now: datetime, jitter: float) -> datetime:
    base = min(300, 2 ** max(0, attempt - 1))
    return now + timedelta(seconds=base + min(jitter, base / 4))
```

Retry timeouts, HTTP `429`, and provider `5xx`. Do not retry invalid credentials, blocked destinations, malformed payloads, or recipient-limit errors. Persist stable codes and bounded status only. Exhaustion creates one deduplicated in-app operator alert.

- [ ] **Step 5: Register and verify the stable Celery task**

```python
@celery_app.task(name="ml_platform.deliver_notifications")
def deliver_notifications_task(outbox_id: str):
    return execute_notification_delivery(outbox_id)
```

```powershell
python -m unittest tests.test_notification_outbox tests.test_notification_production_stack -v
```

Expected: one claim winner, one successful delivery across repeated task calls, persisted increasing retry times, immediate permanent failure, one dead-letter alert, and registered stable task name.

### Task 9: Expose Notification APIs

**Files:**
- Create: `ml-platform/backend/app/schemas/notifications.py`
- Create: `ml-platform/backend/app/api/notifications.py`
- Modify: `ml-platform/backend/app/services/project_access.py`
- Modify: `ml-platform/backend/app/main.py`
- Test: `ml-platform/backend/tests/test_api_notifications.py`

- [ ] **Step 1: Write strict API RED tests**

```python
def test_endpoint_schema_rejects_unknown_fields_and_hides_credentials(self):
    rejected = self.client.post(
        f"/api/projects/{self.project.id}/notification-endpoints",
        json={"kind": "webhook", "name": "ops", "config": {}, "extra": True},
        headers=self.owner_headers,
    )
    self.assertEqual(rejected.status_code, 422)
    created = self.client.post(
        f"/api/projects/{self.project.id}/notification-endpoints",
        json={
            "kind": "webhook",
            "name": "ops",
            "config": {"url": "https://hooks.example.invalid/x", "secret": "test-only"},
        },
        headers=self.owner_headers,
    )
    self.assertEqual(created.status_code, 201)
    self.assertNotIn("test-only", created.text)
    self.assertNotIn("config", created.json())

def test_in_app_notification_is_recipient_private(self):
    response = self.client.patch(
        f"/api/notifications/{self.other_notification.id}/read",
        headers=self.owner_headers,
    )
    self.assertEqual(response.status_code, 404)
```

- [ ] **Step 2: Run RED**

```powershell
python -m unittest tests.test_api_notifications -v
```

Expected: notification router and schemas are not registered.

- [ ] **Step 3: Implement strict endpoint and subscription schemas**

```python
class NotificationEndpointCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["in_app", "wecom", "email", "webhook"]
    name: str = Field(min_length=1, max_length=128)
    config: dict[str, object]


class NotificationSubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint_id: UUID
    event_types: list[str] = Field(min_length=1, max_length=32)
    minimum_severity: Literal["info", "warning", "critical"] = "info"
    recipient_roles: list[Literal["owner", "editor", "operator", "viewer"]] = Field(default_factory=list)
    recipient_user_ids: list[UUID] = Field(default_factory=list)
```

Channel-specific validation occurs before encryption: official WeCom destination, at most 50 valid email recipients, safe Webhook URL/signing/header policy, and at least one in-app recipient selector.

- [ ] **Step 4: Extend the existing project permission matrix**

Add `notification.read` to all four project roles and `notification.manage` to owner/editor only. Keep `audit.read` owner-only and keep global admin outside the project role matrix.

```python
ROLE_PERMISSIONS[ProjectRole.EDITOR] = ROLE_PERMISSIONS[ProjectRole.EDITOR] | frozenset({
    "notification.read", "notification.manage",
})
ROLE_PERMISSIONS[ProjectRole.OPERATOR] = ROLE_PERMISSIONS[ProjectRole.OPERATOR] | frozenset({"notification.read"})
ROLE_PERMISSIONS[ProjectRole.VIEWER] = ROLE_PERMISSIONS[ProjectRole.VIEWER] | frozenset({"notification.read"})
```

Update `PERMISSIONS` and the owner set consistently, then extend the existing table-driven role test.

- [ ] **Step 5: Implement project configuration routes**

```text
GET    /api/projects/{project_id}/notification-endpoints
POST   /api/projects/{project_id}/notification-endpoints
PATCH  /api/projects/{project_id}/notification-endpoints/{endpoint_id}
DELETE /api/projects/{project_id}/notification-endpoints/{endpoint_id}
POST   /api/projects/{project_id}/notification-endpoints/{endpoint_id}/test
GET    /api/projects/{project_id}/notification-subscriptions
POST   /api/projects/{project_id}/notification-subscriptions
PATCH  /api/projects/{project_id}/notification-subscriptions/{subscription_id}
DELETE /api/projects/{project_id}/notification-subscriptions/{subscription_id}
```

Resolve project permission before endpoint/subscription IDs. Encrypt configuration before persistence, expose only destination hint, and audit each write in the same transaction with existing `AuditService`.

- [ ] **Step 6: Implement recipient and administrator routes**

```text
GET    /api/notifications
GET    /api/notifications/unread-count
PATCH  /api/notifications/{notification_id}/read
PATCH  /api/notifications/{notification_id}/archive
GET    /api/admin/notification-deliveries
POST   /api/admin/notification-deliveries/{delivery_id}/retry
```

Filter in-app rows by `recipient_user_id == current_user.id`. The admin delivery response contains status, attempt count, stable error code, destination hint, and timestamps only. Audit administrator retry as `platform.notification.delivery_retry`.

- [ ] **Step 7: Implement safe endpoint testing**

Create a synthetic safe `DomainEvent`, pass it through the same adapter and URL checks, use a deterministic user/endpoint idempotency key, and return only `{status, error_code}`. Do not bypass the encrypted-config or SSRF boundary and do not persist raw provider bodies.

- [ ] **Step 8: Verify API GREEN**

```powershell
python -m unittest tests.test_api_notifications tests.test_platform_audit tests.test_security_hardening tests.test_project_access -v
```

Expected: strict schemas, secret non-disclosure, 404/403 role matrix, recipient isolation, admin retry audit, project write audits, and the existing Week 7 matrix pass.

### Task 10: Build the Frontend Governance and Notification Experience

**Files:**
- Create: `ml-platform/frontend/src/api/securityNotifications.ts`
- Create: `ml-platform/frontend/src/api/securityNotifications.test.ts`
- Create: `ml-platform/frontend/src/components/NotificationCenter.tsx`
- Create: `ml-platform/frontend/src/components/NotificationCenter.test.tsx`
- Create: `ml-platform/frontend/src/pages/ProjectGovernanceTabs.tsx`
- Create: `ml-platform/frontend/src/pages/ProjectGovernanceTabs.test.tsx`
- Modify: `ml-platform/frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `ml-platform/frontend/src/components/AppLayout.tsx`
- Modify: `ml-platform/frontend/src/i18n/index.tsx`

- [ ] **Step 1: Write typed-client RED tests**

```typescript
it("uses exact endpoint URL and returns only safe endpoint metadata", async () => {
  const endpoint = await notificationsApi.createEndpoint("project-1", {
    kind: "webhook",
    name: "ops",
    config: { url: "https://hooks.example.invalid/x" },
  });
  expect(client.post).toHaveBeenCalledWith(
    "/projects/project-1/notification-endpoints",
    expect.objectContaining({ kind: "webhook" }),
  );
  expect(endpoint).not.toHaveProperty("config");
});
```

- [ ] **Step 2: Write component RED tests**

```typescript
it("shows unread count and marks one notification read", async () => {
  render(<NotificationCenter />);
  expect(await screen.findByLabelText("Notifications (2 unread)")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Mark as read" }));
  expect(notificationsApi.markRead).toHaveBeenCalledWith("notice-1");
});

it("shows notification write controls only to owner and editor", async () => {
  render(<ProjectGovernanceTabs projectId="project-1" projectRole="viewer" />);
  await user.click(screen.getByRole("tab", { name: "Notifications" }));
  expect(screen.queryByRole("button", { name: "Add endpoint" })).not.toBeInTheDocument();
});
```

- [ ] **Step 3: Run frontend RED**

Run from `E:\codex_workspace\agent_spot_welding\ml-platform\frontend`:

```powershell
npm test -- src/api/securityNotifications.test.ts src/components/NotificationCenter.test.tsx src/pages/ProjectGovernanceTabs.test.tsx
```

Expected: missing API client/components and translation keys fail.

- [ ] **Step 4: Implement typed API client**

Define `NotificationEndpoint`, `NotificationSubscription`, `InAppNotification`, `PlatformAuditEvent`, and `DeliveryStatus` types. Keep URLs and `{items,total,offset,limit}` normalization in `securityNotifications.ts`; components do not build raw paths or infer project access from platform role.

- [ ] **Step 5: Implement notification center and project governance tabs**

`NotificationCenter` supports loading, empty, error, unread badge, severity, title/body, timestamp, mark-read, and archive. `ProjectGovernanceTabs` renders Members, Audit, and Notifications; Notifications has endpoint table, channel-specific forms, subscriptions, owner/editor controls, and admin delivery state. Never render stored credentials after submit.

- [ ] **Step 6: Add header button and accessible names**

Add `BellOutlined` and `Badge` to `AppLayout`, load unread count on mount, refresh after read/archive, and use explicit tooltip/`aria-label` text for notification, read, archive, test, and delete icon buttons. Keep stable dimensions so badge changes do not shift the header.

- [ ] **Step 7: Add bilingual parity**

Add identical `securityNotifications` and `projectGovernance` key trees in `ZH` and `EN`, covering channels, endpoints, recipients, severity, delivery/audit states, errors, confirmations, empty/loading/denied text, and action labels. Extend translation parity tests to compare recursive key paths.

- [ ] **Step 8: Verify frontend GREEN and build**

```powershell
npm test -- src/api/securityNotifications.test.ts src/components/NotificationCenter.test.tsx src/pages/ProjectGovernanceTabs.test.tsx
npm test
npm run build
```

Expected: focused and full tests pass, translation keys are symmetric, build succeeds, and rendered output contains no endpoint credential.

### Task 11: Add Browser, Manifest, and Production-Stack Acceptance

**Files:**
- Create: `ml-platform/frontend/e2e/security-notifications.spec.ts`
- Create: `ml-platform/backend/tests/test_notification_production_stack.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`
- Modify: `ml-platform/backend/tests/test_suite_manifest.py` only if a Week 10 ownership assertion is needed.

- [ ] **Step 1: Write browser RED flow**

```typescript
test("project governance and notification delivery", async ({ page }) => {
  await loginAs(page, "owner");
  await page.goto(`/projects/${projectId}`);
  await page.getByRole("tab", { name: /Notifications|通知/ }).click();
  await page.getByRole("button", { name: /Add endpoint|添加端点/ }).click();
  await page.getByLabel(/Channel|通道/).selectOption("webhook");
  await page.getByLabel(/URL|地址/).fill("https://receiver.example.invalid/hook");
  await page.getByRole("button", { name: /Save|保存/ }).click();
  await expect(page.getByText(/receiver.example.invalid/)).toBeVisible();
});
```

- [ ] **Step 2: Run browser RED**

```powershell
npm run test:e2e -- --project=chromium --grep "project governance and notification delivery"
```

Expected: governance tabs or notification center are absent.

- [ ] **Step 3: Implement isolated production receiver tests**

Use unique PostgreSQL, Redis, Celery, SMTP receiver, WeCom/Webhook controlled receiver, network, and port names. Upgrade to `20260720_10_security_notifications`; seed owner/editor/operator/viewer/outsider; verify four channels and clean only resources with the Week 10 prefix. Controlled WeCom tests inject the transport after validating the official host contract; they do not call a real enterprise account.

- [ ] **Step 4: Add security assertions to production test**

Cover registration role injection, compute/annotation/platform UUID probing, project-admin outsider hiding, endpoint encryption, metadata/private/redirect Webhook blocking, payload/timeout/recipient caps, outbox duplicates, retry/dead-letter, and platform audit access. Persist only redacted evidence.

- [ ] **Step 5: Register each Week 10 module exactly once**

```python
10: [
    "test_security_hardening",
    "test_platform_audit",
    "test_notification_models",
    "test_notification_outbox",
    "test_notification_channels",
    "test_api_notifications",
    "test_notification_production_stack",
],
```

Run the manifest test before registration to observe unowned modules, then after registration to require exact one-week ownership.

- [ ] **Step 6: Verify focused, Week 10, and browser suites**

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform\backend
python -m unittest tests.test_security_hardening tests.test_platform_audit tests.test_notification_models tests.test_notification_outbox tests.test_notification_channels tests.test_api_notifications tests.test_suite_manifest -v
python run_suite.py --week 10
cd ..\frontend
npm run test:e2e -- --project=chromium --grep "project governance and notification delivery"
```

Expected: all seven Week 10 modules pass and Chromium verifies governance tabs, unread state, controlled delivery, redaction, and outsider/permission-denied behavior.

### Task 12: Integrate Shared Production Files and Close Evidence

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.github/workflows/ci.yml`
- Modify: `ml-platform/backend/Dockerfile`
- Modify: `ml-platform/backend/Dockerfile.worker`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `PLATFORM_STATUS.md`
- Modify: `docs/delivery/PRODUCTION_INFRASTRUCTURE.md`
- Modify: `docs/delivery/USER_GUIDE.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Wire production settings through the primary integrator**

Add notification master-key secret file, SMTP settings, and stable Celery task registration. Health/readiness returns only `notification_crypto_configured` and `notification_worker_registered` booleans. Never expose passwords, WeCom/Webhook tokens, signing secrets, or master keys in environment summaries, logs, images, or docs.

- [ ] **Step 2: Add CI quality gates**

Run Week 10 backend, frontend unit/build, Chromium, Alembic double upgrade/current/check, source secret scan, dependency audit, and isolated notification integration. Use bounded build retries and unique resources; PostgreSQL/Redis/Celery evidence is mandatory.

- [ ] **Step 3: Run complete local verification**

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform\backend
python run_suite.py --week 10
python -m compileall -q app
git diff --check
cd ..\frontend
npm test
npm run build
npm audit --registry=https://registry.npmjs.org
npm run test:e2e -- --project=chromium
```

Expected: backend Week 10 passes, compile/diff checks are clean, frontend tests/build pass, npm audit has no unresolved vulnerability, and Chromium passes.

- [ ] **Step 4: Run isolated production evidence**

Verify migration head, worker task registration, endpoint encryption, domain-event/outbox atomicity, four-channel delivery, retry/dead-letter, platform/project audit, and role matrix. Bind evidence to Git commit, image digest, migration head, environment manifest, raw test results, and remote CI URL.

- [ ] **Step 5: Update status and reusable experience**

Append exact counts, migration head, production evidence, root causes, solutions, prevention, and remaining Week 11 dependency to `DEVELOPMENT_PLAN.md`; update `PLATFORM_STATUS.md`; append reusable experience with behavior, verified root cause, solution, verification, and prevention to the shared experience file. Preserve all history and record no credential.

- [ ] **Step 6: Run final contract scan**

```powershell
$bad = @('TO' + 'DO', 'TB' + 'D', 'FIX' + 'ME', 'Not' + 'Implemented')
Select-String -Path docs/superpowers/plans/2026-07-20-week10-security-notifications.md -Pattern $bad
rg -n "20260720_10_security_notifications|20260720_09_production_inference|DomainEventRecorder|in_app|wecom|email|webhook|403|404" docs/superpowers/plans/2026-07-20-week10-security-notifications.md
```

Expected: the first scan returns no matches; the second finds migration ordering, recorder contract, all four channels, and authorization semantics.

## Final Acceptance Checklist

- [ ] Public registration rejects a role field and creates all normal accounts as `engineer`.
- [ ] Compute, Annotation, sample, auto-label, and Platform API routes authorize before target/provider access and hide foreign IDs with `404`.
- [ ] Global admin does not bypass project membership; visible members without a permission receive `403`.
- [ ] Platform security events are append-only, redacted, request-correlated, filterable, and actor-delete preserving.
- [ ] Week 10 has one linear migration head at `20260720_10_security_notifications` and cleanly downgrades to `20260720_09_production_inference`.
- [ ] `OutboxDomainEventRecorder.record(db, event)` only adds/flushes and shares the business transaction.
- [ ] Endpoint configuration is encrypted and APIs expose destination hints only.
- [ ] In-app, WeCom, email, and Webhook use the same safe event envelope and stable result contract.
- [ ] SSRF, redirects, payload, timeouts, signing, and recipient limits are tested.
- [ ] Claiming, idempotency, retries, dead-letter, and operator alerts are durable and restart-safe.
- [ ] Members, Audit, Notifications, and the header unread entry are bilingual, permission-aware, and browser-tested.
- [ ] Every Week 10 module has one manifest owner and all local/production gates pass before status updates.
