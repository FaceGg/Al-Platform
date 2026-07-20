# Weeks 9-12 Production Inference and MLOps Core Design

## 1. Goal

Weeks 9-12 turn the existing model registry and basic ONNX runtime into a production inference service, close authorization and audit gaps, add reliable enterprise notifications, establish performance and operational baselines, and complete the MLOps core acceptance cycle.

Development starts in parallel, but completion remains dependency-aware:

- Week 9 owns production inference behavior and inference domain events.
- Week 10 owns authorization hardening, security audit, notification subscriptions, and delivery.
- Week 11 owns integration and performance tooling, then measures the frozen Week 9-10 contracts.
- Week 12 owns acceptance tooling immediately, but final acceptance waits for Weeks 9-11 to pass.

## 2. Confirmed Decisions

- Use three dependency-aware parallel tracks instead of four fully independent branches.
- Keep one linear Alembic history. Week 10 migrations depend on the Week 9 revision.
- Deliver in-app, WeCom, email, and generic Webhook notification channels.
- Include model cards in Week 9.
- Keep the backend control plane and the internal ONNX Runtime data plane separated.
- Keep the existing JWT inference endpoint for authenticated console testing.
- Add a separate API-key-authenticated production inference endpoint.
- Production rate limiting fails closed when Redis is unavailable.
- Store no inference records, predictions, credentials, storage URIs, or raw exceptions in request logs, audit events, or notifications.
- Week 11 performance thresholds remain candidates until three repeatable runs on the fixed acceptance environment establish the baseline.

## 3. Parallel Delivery Architecture

### 3.1 Track A: Week 9 Production Inference

Track A delivers:

- immutable deployment revisions and weighted version targets;
- canary and rolling rollout state machines;
- automatic and manual rollback;
- deployment-scoped API keys;
- Redis-backed rate limits;
- redacted request logs and aggregate metrics;
- model cards;
- production inference operations UI;
- inference domain events for notification consumers.

### 3.2 Track B: Week 10 Authorization and Notifications

Track B delivers:

- immediate fixes for self-registration privilege escalation and cross-user IDOR paths;
- explicit resource authorization classes and centralized resolvers;
- platform-level security audit events;
- transactional notification outbox and delivery attempts;
- in-app, WeCom, email, and generic Webhook adapters;
- member, audit, subscription, and delivery operations UI.

Track B consumes safe Week 9 domain-event envelopes. It does not own or mutate the inference rollout state machine.

### 3.3 Track C: Weeks 11-12 Verification Infrastructure

Track C may begin immediately with independent files and fixtures:

- reproducible performance harnesses and environment manifests;
- current-baseline measurements;
- backup and restore scripts;
- N-1 upgrade fixtures;
- security scanning jobs;
- broader browser error detection;
- acceptance report and evidence-manifest templates.

Final Week 11 measurements and all Week 12 conclusions wait for stable Week 9-10 APIs, schemas, and migration revisions.

### 3.4 Serial Integration Points

The primary integrator owns changes to:

- `docker-compose.yml`;
- `.github/workflows/ci.yml`;
- application settings and startup registration;
- Alembic revision ordering;
- backend and frontend week manifests;
- frontend routes and translation trees;
- `DEVELOPMENT_PLAN.md`, `PLATFORM_STATUS.md`, and final acceptance documents.

## 4. Week 9 Persistence Model

### 4.1 DeploymentRevision

An immutable release configuration for one stable `InferenceDeployment` service identity.

- `id`: UUID primary key.
- `deployment_id`: required deployment foreign key.
- `revision_number`: monotonic integer unique within a deployment.
- `strategy`: `immediate`, `canary`, or `rolling`.
- `status`: `draft`, `candidate`, `stable`, `superseded`, or `failed`.
- `created_by_id`, `created_at`, and activation timestamps.

Once activation starts, its targets and strategy cannot be edited. A new change creates another revision.

### 4.2 DeploymentTarget

One revision contains one or more approved model-version targets.

- `revision_id` and `model_version_id` form a unique pair.
- `weight_bps` is an integer from 0 to 10000.
- all active target weights must total 10000.
- `role` is `stable` or `candidate`.

The control plane validates target approval and project ownership before persistence. The database retains uniqueness and range constraints; service code validates the cross-row total in the same transaction.

### 4.3 DeploymentRollout

A mutable, durable saga record for moving traffic between revisions.

- `from_revision_id` and `to_revision_id`;
- `state`: `pending`, `preloading`, `progressing`, `paused`, `completed`, `failed`, or `rolled_back`;
- `current_step`, `lock_version`, stable error code, and timestamps;
- frozen rollout thresholds and step schedule.

Only one active rollout may exist for a deployment. Row locking or version compare-and-swap prevents concurrent commands from advancing different candidates.

### 4.4 InferenceApiKey

- Deployment-scoped key identity and safe display prefix.
- Secret hash, never reversible plaintext.
- Scopes, expiry, revoked timestamp, and last-used timestamp.
- Plaintext is returned once after creation or rotation.

Key lists, logs, audits, exports, and errors never contain the secret.

### 4.5 InferenceRequestLog and InferenceMetricBucket

Request logs contain only:

- request ID;
- deployment, revision, and actual model-version IDs;
- API-key identity, never its secret;
- batch size, duration, status, and stable error code;
- bounded timestamps and retention metadata.

Minute buckets aggregate request counts, success and error counts, limited requests, batch sizes, latency distribution, traffic weights, and load failures. Dashboards query buckets rather than scanning raw logs.

### 4.6 ModelCard

Each immutable model version has a model card with:

- intended use and limitations;
- training-data lineage and source artifacts;
- input and output schemas;
- frozen metrics and approval history;
- current deployment and release status;
- risk notes and user-maintained operational guidance.

System-generated lineage, schemas, metrics, and approvals cannot be edited through public APIs. Human-authored guidance is versioned and audited.

### 4.7 Compatibility

The current `InferenceDeployment.model_version_id` initializes the first stable revision during migration. Existing deployments retain their IDs, names, desired states, and API URLs. New rollout code reads revisions after migration and does not mutate the legacy version reference.

## 5. Week 10 Persistence and Authorization Model

### 5.1 Resource Authorization Classes

Every API resource is classified as one of:

- project-bound;
- user-private;
- platform-admin-only;
- explicitly public.

Indirect resources resolve ownership through one centralized service. Unknown resource classes and unknown permissions fail closed.

Immediate hardening covers:

- public registration cannot select a platform role;
- compute resources cannot be read or modified across owners;
- annotation tasks, samples, and automatic-label operations cannot cross owners or projects;
- API marketplace resources require authentication and ownership or explicit public access;
- member-management authorization occurs before target-user or membership lookup.

### 5.2 PlatformAuditEvent

Existing project audit events continue to represent project actions. A separate platform security stream records authentication, platform user administration, role changes, and other non-project security events without weakening existing project foreign-key and deletion semantics.

Both streams use request IDs, stable action names, explicit outcomes, bounded safe changes, and recursive redaction.

### 5.3 NotificationSubscription

A subscription selects:

- project scope;
- event types and minimum severity;
- recipient roles or explicit recipients;
- one notification endpoint;
- enabled state and audit metadata.

### 5.4 NotificationEndpoint

Supported channel kinds are `in_app`, `wecom`, `email`, and `webhook`.

Credentials and signing material use authenticated encryption under a production-required environment master key. Public responses expose only safe endpoint metadata and redacted destination hints.

### 5.5 NotificationOutbox and NotificationDelivery

Business state and its safe event envelope commit in one database transaction. The outbox row contains a globally unique event ID and idempotency key.

Workers claim events atomically and create one delivery per matching subscription. Delivery records store attempts, next retry time, provider-safe response metadata, stable error code, and final state. Duplicate claims cannot duplicate successful sends.

### 5.6 InAppNotification

In-app notifications support recipient queries, unread counts, read state, and archive state. They retain only the safe rendered event payload.

## 6. Shared Domain Event Contract

The event envelope contains:

- event ID and idempotency key;
- project ID when applicable;
- event type and severity;
- occurrence time and actor reference;
- resource type and resource ID;
- allowlisted safe payload.

Initial Week 9 event types include rollout started, rollout failed, rollout completed, rollback completed, runtime load failed, rate limit threshold exceeded, and inference error-rate threshold exceeded.

Events exclude inference input, prediction output, API keys, credentials, object-storage locations, and raw exception messages.

## 7. Rollout and Inference Flows

### 7.1 Rollout

1. Authorize and audit the command.
2. Create a candidate revision and durable rollout.
3. Preload all candidate targets in the runtime.
4. Run runtime health checks and schema-compatible smoke inference.
5. Activate traffic steps, defaulting to 0, 10, 50, and 100 percent candidate traffic.
6. Observe the frozen error-rate, latency, and load-health thresholds at every step.
7. Pause and restore stable traffic automatically if a threshold fails.
8. Mark the candidate stable only after the final observation window succeeds.
9. Drain and unload targets no longer referenced by active revisions.

Celery tasks are idempotent. Reconciliation reconstructs runtime state from the database after backend, worker, or runtime restart.

### 7.2 Rollback

Rollback uses the same state machine and is safe to repeat. It restores the selected previously stable revision, verifies runtime availability, atomically applies stable weights, and then drains the failed revision. A rollback failure leaves the last known working weights unchanged.

### 7.3 Request Routing and Rate Limiting

Production inference authenticates an API key, checks scope and expiry, and applies a Redis atomic token bucket keyed by API-key identity and deployment. Redis unavailability fails closed in production with a stable 503 error.

A server-side stable hash selects the weighted target. Responses include the actual deployment revision and model version. The runtime remains private and cannot be invoked directly outside the production network.

## 8. Notification Delivery Flows

1. A business transaction persists its state and outbox event atomically.
2. A worker atomically claims the event and resolves active subscriptions.
3. The worker creates channel-specific delivery records with deterministic idempotency keys.
4. In-app delivery persists locally. External adapters perform bounded network calls.
5. Network errors, rate limits, and provider 5xx responses retry with exponential backoff and jitter.
6. Permanent validation and authorization errors fail without retry.
7. Exhausted deliveries enter a queryable dead-letter state and create an in-app operator alert.

WeCom destinations must match official endpoints. Generic Webhooks reject loopback, private, link-local, metadata, and disallowed redirected destinations unless a platform administrator configures an explicit destination allowlist. Email validates recipient limits and uses configured SMTP transport security.

## 9. API Surface

Existing Week 8 routes remain compatible. New route groups provide:

- rollout create, read, pause, resume, and rollback commands;
- current revision, targets, weights, and rollout history;
- API-key create, list, rotate, and revoke commands;
- API-key-authenticated production prediction;
- paginated request logs and time-window metric queries;
- model-card read, audited guidance update, and export;
- project member and permission-matrix queries;
- project and platform-security audit queries;
- notification subscription and endpoint management;
- endpoint test commands that never reveal credentials;
- in-app notification list, unread count, read, and archive commands;
- administrator delivery-status and retry commands.

All request bodies use strict schemas and reject unknown fields. Indirect project resources preserve hidden 404 behavior for outsiders and 403 behavior for visible members without the required permission.

## 10. Frontend Operations Experience

The existing model operations page gains focused work views for:

- release progress and version traffic;
- rollback;
- API-key management;
- request metrics and redacted logs;
- model-card review and operational guidance.

The project detail experience gains Members, Audit, and Notifications tabs. The application header gains an in-app notification entry with unread state.

Notification configuration uses channel-specific controls:

- in-app recipient roles or members;
- WeCom robot or application-message settings;
- email recipients, copies, and severity threshold;
- Webhook URL, signature mode, timeout, and safe custom headers.

The UI preserves existing Ant Design patterns, compact operational density, bilingual translation-tree parity, explicit accessible names, loading and empty states, permission-denied states, and confirmation for destructive commands. API-key plaintext is displayed in one creation or rotation dialog only.

## 11. Error Handling

New stable error groups cover:

- revision conflicts and invalid weights;
- rollout already active, rollout health failure, and rollback failure;
- API-key invalid, expired, revoked, or out of scope;
- rate limited and rate-limit backend unavailable;
- metric or request-log query limits;
- notification endpoint invalid or forbidden;
- notification credential unavailable;
- notification delivery retry exhausted;
- resource hidden and permission denied.

External provider response bodies and raw exceptions remain in bounded redacted server diagnostics only. Public APIs, audit rows, rollout rows, outbox rows, and delivery rows store stable codes and safe messages.

## 12. Verification Strategy

### 12.1 Week 9

- rollout state transitions, concurrent command exclusion, weighted routing, and idempotent rollback;
- preload failure, health-threshold failure, automatic stable-weight restoration, and restart reconciliation;
- API-key one-time plaintext, hashing, scope, expiry, rotation, revocation, and leak scanning;
- multi-process Redis rate-limit correctness and stable `429` plus `Retry-After`;
- request-log redaction, retention, metric aggregation, and model-card integrity;
- frontend operations, production Compose, Chromium, and Week 9 manifest coverage.

### 12.2 Week 10

- table-driven resource-class and role coverage;
- self-registration privilege escalation and cross-user UUID probing regression tests;
- success, denied, and failed audit outcomes with atomicity and redaction;
- outbox atomicity, worker claim idempotency, retries, dead-letter behavior, and duplicate suppression;
- in-app, WeCom, email, and Webhook adapter contracts;
- SSRF, redirect, credential encryption, payload-size, timeout, and recipient-limit tests;
- frontend member, audit, subscription, and delivery-state coverage.

### 12.3 Week 11 Candidate Performance Gates

Use a fixed 4-vCPU, 8-GiB environment and run three measured iterations after warmup.

- Core read APIs at 20 concurrent users: p95 at most 300 ms, p99 at most 800 ms, error rate below 0.1 percent.
- Warm single-record ONNX inference at 20 concurrent users: p95 at most 200 ms, p99 at most 500 ms, error rate below 0.1 percent.
- Task enqueue p95 at most 1 second.
- Full welding workflow completes within 90 seconds and succeeds 10 of 10 times.
- Rollout and rollback produce less than 1 percent 5xx responses and no continuous outage longer than 5 seconds.
- Automatic rollback recovery completes within 2 minutes.

Cold model load and warm inference are reported separately. Threshold changes require recorded hardware, raw results, bottleneck evidence, and review; lowering load to manufacture a pass is forbidden.

### 12.4 Week 12 Acceptance Gates

- PostgreSQL and MinIO backup and restore with RTO at most 30 minutes and documented RPO at most 24 hours.
- Restored database counts, key foreign-key relationships, and object SHA-256 values match completely.
- N-1 production snapshot upgrades to head without business-data loss; migration is repeatable and compatibility windows are documented.
- Dependency, source, container, secret, and web-security scans run as explicit CI gates with reviewed exception records.
- Browser acceptance covers production rollout, rollback, rate limiting, all four notification channels through controlled receivers, audit visibility, and the four project roles plus outsider behavior.
- Final evidence binds Git commit, image digest, migration head, environment manifest, raw performance results, scan reports, backup and upgrade records, and remote CI run URL.

## 13. Deliverables

- Week 9 production inference code, migration, tests, operations UI, model cards, and production evidence.
- Week 10 authorization hardening, security audit, notification services, four channel adapters, management UI, and production evidence.
- `docs/week11-performance-baseline.md` plus raw machine-readable results and environment manifest.
- `docs/week12-acceptance.md` plus security, backup, restore, upgrade, browser, and remote CI evidence.
- Updated week manifests, deployment documentation, platform status, development plan, and reusable experience records.

## 14. Out of Scope

- Kubernetes execution and autoscaling, which begin in Week 13.
- GPU inference scheduling and multi-cluster routing.
- SMS, DingTalk, Feishu, Slack, and Teams native adapters; generic Webhooks may integrate them externally.
- Arbitrary user code or pickle loading in the inference runtime.
- Storing prediction payloads for drift analysis. A future privacy-reviewed design must define retention and consent before enabling payload capture.
