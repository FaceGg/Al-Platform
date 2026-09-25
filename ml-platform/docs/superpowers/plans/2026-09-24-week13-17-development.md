# Week 13–17 云原生与数据探索开发计划

> For agentic workers: execute the tasks in order, keep each checkbox independently reviewable, and use the repository verification rules before claiming completion.

**Goal:** 在不破坏现有通用 AutoML 与数据标注合同的前提下，按依赖完成 Week 13–16 的 Kubernetes、执行、Notebook、镜像、GPU、多集群与资源治理能力，并为 Week 17 的数据探索与质量报告建立一个经过产品决策门控制的实现入口。

**Architecture:** 先建立由项目权限保护的 Kubernetes 控制面资源模型，再通过统一执行器抽象连接 Job/Pod、Notebook 和镜像构建。所有长操作都使用现有 DurableOperation、任务派发、幂等键和审计机制；集群凭据只保存引用，不把 kubeconfig 或 token 写入数据库、API 响应或日志。Week 17 先完成范围决策，批准后以只读、项目隔离的数据探索服务生成可追溯质量报告；多模态 Label Studio 集成保持延后。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy、Alembic、PostgreSQL/SQLite 兼容层、Redis/Celery、Kubernetes Python client、React/TypeScript、Ant Design、Vitest、Playwright、Linux/WSL kind 或等价测试集群、Artifact Storage；Week 17 推荐使用 DuckDB 读取不可变 DatasetVersion 制品。

**Spec:** DEVELOPMENT_PLAN.md、DEVELOPMENT_PLAN.history-2026-08-23.md §4、OPTIMIZATION_PLAN.md §7，以及 ml-platform/docs/technical-proposals/2026-09-01-general-automl-annotation-platform.md。

## Global Constraints

- Week 13–16 的当前状态为 planned；Week 17 为 pending_decision。计划建立和文档通过不等于功能完成。
- 通用平台边界优先于历史行业化代码；新模块不得增加点焊字段、路由、服务或专用工作流依赖。
- 所有 API 读写都通过现有 get_current_user、ProjectAccessService 或等价项目资源权限合同；写操作进入 AuditService，跨项目资源返回既有隐藏式 404/403 语义。
- 集群凭据使用 credential_ref/Secret 引用和最小权限 ServiceAccount；禁止明文 secret、任意 kubeconfig、任意 hostPath、privileged、Docker socket 和未审计外部 URL。
- 数据库模型变更必须提供线性 Alembic 迁移、SQLite 兼容测试、upgrade/check 证据和旧数据保留断言；不得以 create_all 代替迁移。
- 所有创建、提交、取消、重试和回收操作带 X-Request-ID、Idempotency-Key、操作 ID 和脱敏错误；迟到的 watch 或 worker 结果不能覆盖终态。
- 本地单元测试、API 集成、真实 Kubernetes/WSL、浏览器和当前 SHA 发布收据分开记录；failed、skipped、cancelled、blocked、not_run 均不能折算为 passed。
- Week 17 未经产品确认不得部署 Superset、Label Studio、iframe、外部查询代理或多模态回流链路。

## Review Focus

1. 跨项目集群、命名空间、Job、Notebook 和数据集访问必须被服务端拒绝，并且不能通过 ID、分页或错误消息侧信道泄露资源。
2. 失效凭据、TLS/endpoint 配置错误、watch 断线和集群重启必须收敛为可恢复的 connectivity_failed、orphaned 或 retryable 状态，不能伪造成功。
3. 取消、超时、重试和回收存在竞态时，只允许一个最终状态和一份审计记录，迟到的 Pod 事件不能重新打开任务。
4. GPU、CPU、内存和存储配额必须同时约束请求与实际调度标签，不能仅靠前端禁用按钮防止超配。
5. SQL 查询和质量分析必须只读、项目隔离、有行数/字节/时间上限，禁止任意数据库连接、文件路径读取和结果制品越权下载。

---

## 1. Scope and dependency graph

| 阶段 | 交付范围 | 依赖 | 当前门禁 |
|---|---|---|---|
| Week 13 | 集群登记、凭据引用、命名空间、资源组、节点发现、连通性检查 | 当前项目权限/审计/制品合同 | 真实或 kind 集群只读发现与失败封闭 |
| Week 14 | Job/Pod 提交、状态、日志、取消、超时、垃圾回收、重启恢复 | Week 13 集群和命名空间 | 同一操作幂等、watch 重连、终态不可逆 |
| Week 15 | Notebook 会话、镜像目录与 rootless 构建、GPU 资源类和配额 | Week 13、14 | 无 Docker socket 的构建；GPU 无设备时明确 skipped |
| Week 16 | 多集群路由、存储挂载、配额/并发/成本治理、集群节点 Pod GPU 监控 | Week 13–15 | 单集群默认行为保持；跨集群调度有可解释拒绝原因 |
| Week 17 | SQL Lab/数据探索/质量报告决策；批准后实现只读查询和报告；多模态标注保持延后 | DatasetVersion、项目权限；若接入执行则依赖 Week 14 | 先决策后编码；未批准项保持 pending_decision |

执行顺序固定为 Week 13 → Week 14 → Week 15 → Week 16 → Week 17。Week 17 的只读数据探索可以在 Week 13 的数据权限合同稳定后做设计准备，但不得绕过决策门进入生产路由。

## 2. File and interface map

### Week 13 files

- Create: ml-platform/backend/app/models/cloud_resources.py
- Create: ml-platform/backend/app/schemas/cloud_resources.py
- Create: ml-platform/backend/app/services/kubernetes_client.py
- Create: ml-platform/backend/app/services/kubernetes_cluster.py
- Create: ml-platform/backend/app/api/kubernetes_clusters.py
- Create: ml-platform/backend/alembic/versions/20260924_61_cloud_resources.py
- Modify: ml-platform/backend/app/models/__init__.py, ml-platform/backend/app/config.py, ml-platform/backend/app/main.py
- Test: ml-platform/backend/tests/test_kubernetes_client.py, test_kubernetes_cluster_api.py, test_cloud_resource_migrations.py
- Create: ml-platform/frontend/src/api/kubernetes.ts, ml-platform/frontend/src/pages/KubernetesPage.tsx, ml-platform/frontend/src/pages/KubernetesPage.test.tsx
- Modify: ml-platform/frontend/src/App.tsx, ml-platform/frontend/src/components/AppLayout.tsx, ml-platform/frontend/src/i18n/index.tsx

### Week 14 files

- Create: ml-platform/backend/app/models/kubernetes_execution.py
- Create: ml-platform/backend/app/schemas/kubernetes_execution.py
- Create: ml-platform/backend/app/services/kubernetes_executor.py
- Create: ml-platform/backend/app/tasks/kubernetes_tasks.py
- Create: ml-platform/backend/app/api/kubernetes_jobs.py
- Create: ml-platform/backend/alembic/versions/20260924_62_kubernetes_executions.py
- Modify: ml-platform/backend/app/tasks/__init__.py, ml-platform/backend/app/main.py, ml-platform/backend/app/services/operation_lifecycle.py
- Test: ml-platform/backend/tests/test_kubernetes_executor.py, test_kubernetes_job_api.py, test_kubernetes_recovery.py, test_kubernetes_logs.py
- Create: ml-platform/frontend/src/api/kubernetesJobs.ts, ml-platform/frontend/src/pages/JobRunsPage.tsx, ml-platform/frontend/src/pages/JobRunsPage.test.tsx
- Modify: ml-platform/frontend/src/App.tsx, ml-platform/frontend/src/components/AppLayout.tsx

### Week 15 files

- Create: ml-platform/backend/app/models/developer_resources.py
- Create: ml-platform/backend/app/schemas/developer_resources.py
- Create: ml-platform/backend/app/services/notebook_service.py
- Create: ml-platform/backend/app/services/image_build_service.py
- Create: ml-platform/backend/app/services/gpu_scheduler.py
- Create: ml-platform/backend/app/api/notebooks.py, ml-platform/backend/app/api/images.py
- Create: ml-platform/backend/alembic/versions/20260924_63_developer_resources.py
- Test: ml-platform/backend/tests/test_notebook_api.py, test_image_catalog_api.py, test_image_build_security.py, test_gpu_scheduling.py
- Create: ml-platform/frontend/src/api/notebooks.ts, ml-platform/frontend/src/api/images.ts, ml-platform/frontend/src/pages/NotebookPage.tsx, ml-platform/frontend/src/pages/ImageCatalogPage.tsx
- Test: ml-platform/frontend/src/pages/NotebookPage.test.tsx, ml-platform/frontend/src/pages/ImageCatalogPage.test.tsx
- Modify: ml-platform/frontend/src/App.tsx, ml-platform/frontend/src/components/AppLayout.tsx, ml-platform/frontend/src/i18n/index.tsx

### Week 16 files

- Create: ml-platform/backend/app/models/resource_governance.py
- Create: ml-platform/backend/app/schemas/resource_governance.py
- Create: ml-platform/backend/app/services/cluster_scheduler.py
- Create: ml-platform/backend/app/services/resource_governance.py
- Create: ml-platform/backend/app/services/storage_mounts.py
- Create: ml-platform/backend/app/api/cluster_governance.py
- Create: ml-platform/backend/alembic/versions/20260924_64_resource_governance.py
- Test: ml-platform/backend/tests/test_multi_cluster_scheduler.py, test_resource_governance.py, test_storage_mounts.py, test_cluster_observability.py
- Create: ml-platform/frontend/src/api/clusterGovernance.ts, ml-platform/frontend/src/pages/ClusterGovernancePage.tsx, ml-platform/frontend/src/pages/ClusterGovernancePage.test.tsx
- Modify: ml-platform/frontend/src/App.tsx, ml-platform/frontend/src/components/AppLayout.tsx, ml-platform/frontend/src/i18n/index.tsx

### Week 17 files after approval only

- Create: ml-platform/backend/app/models/data_exploration.py
- Create: ml-platform/backend/app/models/quality_report.py
- Create: ml-platform/backend/app/schemas/data_exploration.py, ml-platform/backend/app/schemas/quality_report.py
- Create: ml-platform/backend/app/services/query_service.py, ml-platform/backend/app/services/quality_profile.py
- Create: ml-platform/backend/app/api/data_exploration.py, ml-platform/backend/app/api/quality_reports.py
- Create: ml-platform/backend/alembic/versions/20260924_65_data_exploration_quality.py
- Test: ml-platform/backend/tests/test_data_exploration_api.py, test_query_limits.py, test_quality_reports.py
- Create: ml-platform/frontend/src/api/dataExploration.ts, ml-platform/frontend/src/api/qualityReports.ts, ml-platform/frontend/src/pages/DataExplorationPage.tsx, ml-platform/frontend/src/pages/QualityReportPage.tsx
- Test: ml-platform/frontend/src/pages/DataExplorationPage.test.tsx, ml-platform/frontend/src/pages/QualityReportPage.test.tsx
- Modify: ml-platform/frontend/src/App.tsx, ml-platform/frontend/src/components/AppLayout.tsx, ml-platform/frontend/src/i18n/index.tsx
- Do not create Label Studio service, iframe, sync worker or multimodal return endpoint in this plan.

### Cross-week files

- Modify: ml-platform/backend/tests/week_manifest.py and ml-platform/frontend/src/weekAcceptance.test.ts to register every new test exactly once under its owning week.
- Create: ml-platform/backend/tools/acceptance/run_week13_17_acceptance.sh and ml-platform/backend/tools/acceptance/week13_17_fixture.py for Linux/WSL evidence collection.
- Modify: .github/workflows/ci.yml only after local focused gates and the kind/WSL runner are reproducible; the workflow must upload evidence bound to the tested SHA.
- Update: DEVELOPMENT_PLAN.md and ml-platform/docs/superpowers/plans/README.md after every weekly gate; do not use a second status ledger.

## 3. Task 0: Freeze contracts and decide external dependencies

**Files:** Documentation only: DEVELOPMENT_PLAN.md, ml-platform/docs/superpowers/plans/README.md, this plan.

**Interfaces:** The existing project access, ArtifactService, DatasetVersion, DurableOperation, task dispatcher, audit and notification contracts are inputs. This task produces the Week 13–16 API boundary and a Week 17 decision record.

- [ ] Record that the current generic platform Task 14 release receipt is still a separate prerequisite for release claims; Week 13 work may be developed in isolation but cannot silently change the generic Task 1–14 contract.
- [ ] Confirm a test cluster profile: Kubernetes API endpoint, TLS mode, namespace bootstrap, ServiceAccount permissions, registry endpoint and whether a GPU node is available. Store only environment variable names and credential references in the plan.
- [ ] Approve the Week 15 builder path as rootless Kaniko or explicitly defer online builds to prebuilt immutable image digests. Do not permit Docker-in-Docker or host socket mounts.
- [ ] Decide Week 17 SQL Lab boundaries: project-visible DatasetVersion only, read-only queries, maximum rows/bytes/runtime, audit retention, saved query ownership and cost budget. The recommended implementation is DuckDB over artifact snapshots; a Superset deployment is a separate decision.
- [ ] Decide whether Week 17 includes structured-data review extensions. Multimodal Label Studio remains deferred until deployment, account, storage, security and return-contract decisions are recorded.

Verification: review the decision table, confirm every external dependency has an owner and environment, and leave Week 17 as pending_decision when any item is unanswered.

## 4. Task 1: Week 13 Kubernetes foundation

**Interfaces:**

- ClusterRegistration stores project_id, display name, API server URL after allowlist validation, provider/version/capabilities, default namespace, status and last connectivity result.
- ClusterCredentialRef stores a secret reference, namespace and allowed use; it never stores token or kubeconfig content.
- ClusterNamespace and ResourceGroup map a project to a cluster namespace and quota/scheduling policy.
- KubernetesClient exposes register, read-only connectivity check, list namespaces, list nodes and apply namespace quota. Every call has an explicit timeout and returns a typed error code.

Steps:

- [ ] Write failing model and migration tests for project ownership, unique cluster name per project, credential reference validation, namespace uniqueness and upgrade from an empty SQLite database.
- [ ] Implement cloud_resources.py and migration 20260924_61_cloud_resources.py. Add indexes for project_id, cluster_id, status and last_checked_at; add a downgrade test that preserves unrelated tables.
- [ ] Write API RED tests for create/list/get connectivity/nodes/namespace/resource-group endpoints, cross-project hidden access, invalid endpoint schemes, missing credentials, timeout and audit event creation.
- [ ] Implement kubernetes_client.py with the official client, a fake client adapter for tests, TLS/host allowlist validation, bounded connect/read timeouts and redacted exception messages.
- [ ] Implement kubernetes_cluster.py and kubernetes_clusters.py through existing project authorization and audit helpers. A failed connectivity check must persist status and error code without changing the registered credential reference.
- [ ] Add KubernetesPage with cluster list, connectivity action, node capability table and namespace/resource-group state. It must show stale/failed status and never display secret material.
- [ ] Run focused backend tests, frontend page tests, Python compileall, TypeScript check and git diff --check. Register tests in the Week 13 manifest.

Exit gate: a real or kind cluster can be registered, checked, and discovered; invalid or cross-project requests fail closed; migration and focused tests are green. No Job submission is included in this gate.

## 5. Task 2: Week 14 Kubernetes Job/Pod executor

**Interfaces:**

- KubernetesExecutor.submit receives project_id, cluster_id, namespace_id, image digest, command, allowlisted environment, resource request, input/output artifact bindings, timeout and idempotency key; it returns an ExecutionHandle with operation_id, job_name and status.
- KubernetesExecutor.get_status, stream_logs(cursor), cancel and reconcile are safe to retry. Job labels include project_id, operation_id, task_id and revision; manifests reject privileged, hostNetwork, hostPID, hostPath and unapproved images.
- Status mapping is queued, submitted, running, succeeded, failed, cancelled, timed_out and orphaned. Only queued/submitted/running may transition to a running or terminal state.

Steps:

- [ ] Write RED tests for deterministic Job naming, duplicate idempotency replay, resource and image validation, labels, cancellation races, timeout and a late Pod event after success.
- [ ] Implement kubernetes_execution.py, migration 20260924_62_kubernetes_executions.py and kubernetes_executor.py. Use server-side generateName only when the database operation is already durable; never create a cluster resource before the idempotency row is committed.
- [ ] Implement kubernetes_tasks.py for submit/watch/reconcile/reap. Watch must reconnect from resourceVersion, fall back to bounded polling, and persist a sanitized error when the cluster disappears.
- [ ] Implement logs with cursor/byte limits, UTF-8 replacement, secret redaction and an explicit end-of-stream marker. Cancel uses foreground propagation and records the actor and reason.
- [ ] Add kubernetes_jobs.py endpoints for submit/status/logs/cancel/reconcile. Reuse DurableOperation and request headers; responses contain current revision and operation ID.
- [ ] Add JobRunsPage with status timeline, bounded log viewer, cancel/refresh controls, timeout and orphaned explanations. Disable actions by server status, not only local UI state.
- [ ] Run executor, API, recovery and log tests; run a kind/WSL smoke with a short-lived image; register Week 14 tests and capture a current-SHA evidence manifest.

Exit gate: submit is idempotent, watch reconnects, logs are bounded/redacted, cancellation and timeout settle exactly once, restart reconciliation recovers non-terminal operations, and the real cluster smoke is green.

## 6. Task 3: Week 15 Notebook, images and GPU

**Interfaces:**

- NotebookSession represents a project/user session, backing Job/Pod reference, access URL, image digest, requested resources, idle timeout and terminal state. The browser receives a signed, short-lived launch URL or same-origin proxy reference, not a cluster token.
- ContainerImage stores registry/repository, immutable digest, visibility and scan status. ImageBuild stores source artifact, build operation, builder image, status, logs reference and output digest.
- GpuResourceClass records resource name, vendor, memory, node selector, taints/tolerations and allocatable/used snapshots. A request must resolve to an allowed class and quota.

Steps:

- [ ] Write RED tests for NotebookSession project/user isolation, start/stop/delete idempotency, idle timeout, image digest enforcement, build context path traversal, registry credential redaction and GPU request validation.
- [ ] Implement developer_resources.py, migration 20260924_63_developer_resources.py, notebook_service.py and notebooks.py using the Week 14 executor. Keep JupyterHub integration behind an adapter; session lifecycle remains owned by the platform.
- [ ] Implement image_build_service.py and images.py with immutable digest storage. The accepted build path is rootless Kaniko or the prebuilt-image fallback chosen in Task 0; no Docker socket or arbitrary registry push.
- [ ] Implement gpu_scheduler.py. Discover nvidia.com/gpu capacity from Week 13 node snapshots, translate profiles into Pod resources, and fail closed when drivers, labels or quota are missing.
- [ ] Add NotebookPage and ImageCatalogPage with project-scoped selectors, digest/status display, bounded build logs, session open/stop controls and explicit GPU quota errors.
- [ ] Run focused backend/frontend tests, kind smoke without GPU, and a separately labelled GPU smoke only when a real NVIDIA node is available. A missing GPU environment is skipped, not passed.

Exit gate: notebook sessions and builds use the same executor, image and registry secrets are never returned, GPU requests are scheduled only against verified capacity, and non-GPU environments have an explicit skipped receipt.

## 7. Task 4: Week 16 multi-cluster and resource governance

**Interfaces:**

- ClusterRoutingPolicy selects an eligible cluster by project, capability, health, region, queue and cost policy; selection returns a reason and policy revision.
- StorageBinding maps a project artifact/data version to a PVC or object-storage prefix with read-only input and isolated output semantics. Arbitrary host paths are invalid.
- ResourceQuotaPolicy limits CPU, memory, GPU, storage, concurrent Jobs and notebook idle time. ResourceUsageSnapshot records cluster/node/pod/GPU usage and collection time.

Steps:

- [ ] Write RED tests for deterministic routing, unhealthy cluster exclusion, no-capacity refusal, quota reservation/release, PVC path isolation, usage aggregation and concurrent reservation races.
- [ ] Implement resource_governance.py, migration 20260924_64_resource_governance.py, cluster_scheduler.py and storage_mounts.py. Use a database reservation row plus Kubernetes quota checks; release reservations on every terminal or orphaned path.
- [ ] Implement cluster_governance.py endpoints for policies, storage bindings, quotas, usage snapshots and reconciliation. Every mutation is project-authorized and audited.
- [ ] Add cluster/node/Pod/GPU metrics collection with bounded cardinality and stale-data markers. Do not claim GPU monitoring from the existing host nvidia-smi page; this gate requires Kubernetes resource identity.
- [ ] Add ClusterGovernancePage with route decision explanation, quotas, reservations, stale indicators and per-project usage. Keep the existing single-cluster compute page functional.
- [ ] Run scheduler, quota, storage and observability tests, then a multi-cluster kind/WSL simulation with one unhealthy cluster and one eligible cluster. Register Week 16 tests and produce the evidence manifest.

Exit gate: routing is deterministic and fail-closed, reservations cannot exceed quotas under concurrency, storage bindings cannot escape the project prefix, and the existing single-cluster path remains backward compatible.

## 8. Task 5: Week 17 decision gate and approved data exploration

### 8.1 Decision gate, always required

- [ ] Record product approval for SQL Lab/data exploration and quality-report scope, data access roles, query isolation, audit retention, result size/time limits and cost budget.
- [ ] Record whether structured annotation review/data return needs new APIs. Existing generic annotation assignment/return/acceptance remains the baseline and must not be duplicated.
- [ ] Record that Label Studio/multimodal is deferred unless a separate approved design provides deployment, identity, storage, security and return contracts.

If approval is absent, update the status to pending_decision and stop here. Do not create the migration, APIs or frontend routes below.

### 8.2 Implementation after approval

- [ ] Write RED tests for project-scoped DatasetVersion visibility, read-only SQL, blocked DDL/DML/attach/copy/file functions, row/byte/time limits, query cancellation, audit records and report artifact ownership.
- [ ] Implement query_service.py with DuckDB over immutable DatasetVersion artifacts, an allowlisted SQL grammar, per-request temporary database, bounded result serialization and no arbitrary connection strings. Implement quality_profile.py for null/unique/type/range/duplicate/outlier summaries with deterministic input hash.
- [ ] Add data_exploration.py, quality_reports.py, migration 20260924_65_data_exploration_quality.py and ArtifactService-backed report persistence. Reports include dataset version, schema hash, query/profile parameters, generator version and content hash.
- [ ] Add DataExplorationPage and QualityReportPage with project/dataset selectors, query timeout/row budget display, preview pagination, audit-friendly errors and report download through existing artifact authorization.
- [ ] Run query, quality, migration, API, frontend and authenticated browser tests. Add an evidence receipt that proves read-only enforcement and current-SHA binding.

Exit gate: only an approved, read-only, project-isolated scope is shipped. If the product selects Superset instead of DuckDB, keep the same contracts and create a separate integration plan; do not silently replace the query boundary.

## 9. Cross-week acceptance and release gates

- [ ] Add every new backend module to exactly one week in ml-platform/backend/tests/week_manifest.py; keep deprecated spot-weld modules excluded from the generic active suite.
- [ ] Add every new frontend test to exactly one week in ml-platform/frontend/src/weekAcceptance.test.ts; run the manifest test before the week suite.
- [ ] For each week run focused unit/API tests, migration upgrade/check, compile/type/build checks and git diff --check.
- [ ] For Weeks 13–16 run the Linux/WSL kind or equivalent real-cluster smoke and record cluster version, image digest, namespace, service account, resource profile, environment and evidence paths.
- [ ] For Week 15 mark GPU tests skipped when no NVIDIA device plugin/node exists; never convert an environment skip to a pass.
- [ ] Run authenticated Playwright flows for cluster registration, Job submission/cancel/logs, Notebook lifecycle, governance route explanation and approved Week 17 query/report flows.
- [ ] Bind the final manifest to the current commit SHA. Any stale, missing, failed, cancelled, skipped, blocked or not_run required receipt leaves the week in progress.
- [ ] Update DEVELOPMENT_PLAN.md after each gate and keep completed weekly records in DEVELOPMENT_PLAN.history-2026-09-24.md or a later dated archive; do not rewrite historical facts.

## 10. Explicit exclusions

- No RAG, LLM gateway, AIHub, agent orchestration redesign or dynamic workflow/画布代码互转.
- No new industry-specific operator templates or point-weld write routes.
- No Label Studio deployment, iframe, multimodal task synchronization or training-data return before the Week 17 decision gate is approved.
- No production claim based only on mocked Kubernetes clients, local tests, a historical SHA or a plan document.
