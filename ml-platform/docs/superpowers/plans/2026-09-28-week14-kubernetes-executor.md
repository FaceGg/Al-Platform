# Week 14 Kubernetes Job/Pod 执行闭环实施计划

> For agentic workers: execute the tasks in order, keep each checkbox independently reviewable. 本计划是 [2026-09-24 Week 13–17 计划](2026-09-24-week13-17-development.md) Task 2 的细化执行入口；设计合同见 [Week 14 技术方案](../../technical-proposals/2026-09-28-week14-kubernetes-executor.md)。前置：Week 13 已通过退出门禁。

**Goal:** 在 Week 13 集群底座上交付幂等的 Job 提交、状态 watch、cursor 日志、取消/超时/回收与重启恢复，并通过 kind/WSL 真实集群 smoke；为 Week 15 Notebook/构建提供统一执行器。

**Architecture:** API（execution.operate 权限 + 审计）→ executor 服务（校验 → 先落库 `KubernetesJobRun` + `DurableOperation(queued)` → 派发）→ celery `kubernetes_tasks.py`（submit/watch，租约 + resourceVersion 续点）→ scheduler beat reconcile（对账/超时/GC）。数据库先行，终态恰好一次。

**Tech Stack:** 既有 Celery/Redis、`kubernetes` client（Week 13 适配器）、DurableOperation/operation_lifecycle（既有）、React/Vitest。

**Spec:** [Week 14 技术方案](../../technical-proposals/2026-09-28-week14-kubernetes-executor.md)、[Week 13–17 计划](2026-09-24-week13-17-development.md)、DEVELOPMENT_PLAN.md §4–§5。

## Global Constraints

- 状态 `planned`；门禁全绿前不得宣称完成。Week 13 未收口前不得开始本计划的集群侧实现。
- 权限：所有端点 `execution.operate`（owner/editor/operator）；跨项目隐藏式 404；写操作带 `X-Request-ID`，提交必带 `Idempotency-Key`。
- 集群资源创建前幂等行必须已提交；迟到事件不得覆盖终态；失败不伪装。
- 镜像必须 digest 引用且命中批准前缀清单（默认空 = 全拒绝）；manifest 禁 privileged/hostPath/hostNetwork/hostPID/hostPort/socket；制品绑定非空显式拒绝。
- 迁移接在 Week 13 之后（计划名 `20260924_63_kubernetes_executions.py`，以实现日空闲号为准）。

## File map

Create:

- `ml-platform/backend/app/models/kubernetes_execution.py`
- `ml-platform/backend/app/schemas/kubernetes_execution.py`
- `ml-platform/backend/app/services/kubernetes_executor.py`
- `ml-platform/backend/app/tasks/kubernetes_tasks.py`
- `ml-platform/backend/app/api/kubernetes_jobs.py`
- `ml-platform/backend/alembic/versions/20260924_63_kubernetes_executions.py`
- `ml-platform/backend/tests/test_kubernetes_executor.py`、`test_kubernetes_job_api.py`、`test_kubernetes_recovery.py`、`test_kubernetes_logs.py`
- `ml-platform/frontend/src/api/kubernetesJobs.ts`、`src/pages/JobRunsPage.tsx`、`src/pages/JobRunsPage.test.tsx`

Modify:

- `app/tasks/__init__.py`、`app/tasks/celery_app.py`（include 注册）、`app/services/operation_lifecycle.py`（如需 job 专属 helper）、`app/config.py`（`kubernetes_job_*` 设置）、`app/models/__init__.py`、`app/main.py`
- `frontend/src/App.tsx`（`/kubernetes/jobs` 路由）、`components/AppLayout.tsx`（`t.nav.job_runs` 导航）、`i18n/index.tsx`
- `tests/week_manifest.py`（新增 `14:` 键）、`frontend/src/weekAcceptance.test.ts`（新增第 14 周）

## Task 14.1 模型与迁移（RED → 实现）

- [ ] RED（`test_kubernetes_job_api.py` 模型段或独立）：`operation_id` 唯一；status 枚举守卫；镜像字段必须 digest 形式（模型层校验）；空库 upgrade / downgrade 保留无关表 / `alembic check`。
- [ ] 实现 `kubernetes_execution.py` + 迁移 `20260924_63`（down_revision 接 Week 13）。

## Task 14.2 Executor 核心（RED → 实现）

- [ ] RED（`test_kubernetes_executor.py`）：确定性 Job 命名（同 opid 同 revision 同名）；manifest 生成含必带标签、`backoffLimit=0`、`activeDeadlineSeconds`、`ttlSecondsAfterFinished`；拒绝清单逐项断言（privileged/hostPath/hostNetwork/hostPID/hostPort/socket/非批准镜像/未列 env 键/超资源上限）；制品绑定非空 → `KUBE_JOB_BINDINGS_UNSUPPORTED`；"先落库后建集群资源"顺序断言（fake client 记录调用序）。
- [ ] 实现 `kubernetes_executor.py`：submit（校验 → DB 行 + DurableOperation queued → 返回 handle）、status 映射（§6 状态机 + 终态守卫）、cancel（Foreground 删除 + actor/reason）、reconcile（按标签对账、orphaned 判定）。
- [ ] `test_kubernetes_logs.py` RED→实现：cursor 分页、256KB 上限、UTF-8 替换解码、脱敏、`end_of_stream`、Pod 消失返回缓冲尾。

## Task 14.3 Celery 任务与恢复（RED → 实现）

- [ ] RED（`test_kubernetes_recovery.py`）：watch 从 resourceVersion 续点、410/断线退避重连、回落轮询；租约过期重领（`recover_expired_operations`）；worker 重启后非终态对账收敛；取消与超时双通道只写一次终态；迟到 Pod 事件丢弃。
- [ ] 实现 `kubernetes_tasks.py`（submit/watch/log 收集），注册进 `celery_app.py` include；scheduler beat 注册 reconcile/GC 周期任务。

## Task 14.4 API 层（RED → 实现）

- [ ] RED（`test_kubernetes_job_api.py`）：`execution.operate` 权限矩阵（operator 可提交、viewer 403）、跨项目 404、Idempotency-Key 缺失 428/422、重放 200+`replayed=true`、审计事件（submit/cancel/reconcile）无敏感 payload、X-Request-ID 回显、409 集群非 active。
- [ ] 实现 `schemas/kubernetes_execution.py` + `kubernetes_jobs.py`（端点见技术方案 §9）+ `config.py` 设置 + `main.py` 注册。

## Task 14.5 前端 JobRunsPage（RED → 实现）

- [ ] RED（`JobRunsPage.test.tsx`）：列表渲染状态徽标与 stage/progress；日志查看器按 cursor 增量加载并显示 `end_of_stream`；取消按钮按服务端状态禁用（终态不可点）；timeout/orphaned 有解释文案。
- [ ] 实现 `api/kubernetesJobs.ts` + `JobRunsPage.tsx`；`App.tsx` 增 `/kubernetes/jobs`；`AppLayout.tsx` 增导航；i18n 补 `KUBE_JOB_*` 错误码与文案（中英）。

## Task 14.6 清单登记与聚焦门禁

- [ ] `week_manifest.py` 新增 `14: ["test_kubernetes_executor", "test_kubernetes_job_api", "test_kubernetes_recovery", "test_kubernetes_logs"]`；`weekAcceptance.test.ts` 新增第 14 周。
- [ ] 聚焦门禁（命令模式同 Week 13 实施计划，替换 `--week 14` 与新测试文件名）：后端四模块 pytest → `run_suite.py --week 14` → compileall → `alembic upgrade head` + `alembic check` → 前端 `npm test -- --run` / `tsc --noEmit` / `npm run build` → `git diff --check`。

## Task 14.7 kind/WSL 真实集群 smoke 与证据

- [ ] `kind load docker-image` 预载短时镜像（如 busybox 变体），digest 与临时 allowlist 前缀记入证据。
- [ ] 场景：echo 任务提交 → succeeded + 日志全文；长任务提交 → cancel（终态一次、审计含 actor/reason）；超时任务 → timed_out；提交后杀 worker → 重启 reconcile 收敛；删除集群内 Job 后 reconcile → orphaned。
- [ ] 证据写入 `temp_test/week14-local/`，绑定当前 SHA（镜像 digest、namespace、SA、K8s 版本、每场景命令与退出码）。
- [ ] 已认证 Playwright：提交 → 状态流转 → 日志 → 取消。

## Task 14.8 台账收口

- [ ] 先更新 DEVELOPMENT_PLAN.md（状态、SHA、测试数字、未验证范围），再归档详细记录；任何 blocked/failed 项如实记录，Week 14 保持 `in_progress`。

## Exit gate

- 提交幂等可重放；watch 断线重连/回落轮询；日志有界脱敏；取消/超时恰好一次终态；重启对账恢复非终态；真实集群 smoke 全绿；聚焦测试/迁移/前端门禁通过；证据绑定当前 SHA。**不含 Notebook、镜像目录与跨集群。**

## Explicit exclusions

- 不实现 Notebook/镜像/GPU（Week 15）、路由/配额/多集群（Week 16）、制品绑定执行（显式 422）。
- 不改通用平台 Task 1–14 合同；不引入 DinD/socket；不以 mock 或本文档宣称完成。
