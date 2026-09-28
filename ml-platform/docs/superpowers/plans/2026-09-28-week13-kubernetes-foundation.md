# Week 13 Kubernetes 基础接入实施计划

> For agentic workers: execute the tasks in order, keep each checkbox independently reviewable, and use the repository verification rules before claiming completion. 本计划是 [2026-09-24 Week 13–17 计划](2026-09-24-week13-17-development.md) Task 1 的细化执行入口；设计合同见 [Week 13 Kubernetes 基础接入技术方案](../../technical-proposals/2026-09-28-week13-kubernetes-foundation.md)。

**进度（2026-09-28）：** Task 13.0–13.5 完成——后端聚焦测试 37 passed（3 模块）、run_suite --week 13 3/3、compileall、alembic upgrade head（head=20260928_62）+ alembic check、前端 Vitest 368 passed/19 skipped、tsc、build 全绿；Task 13.6 kind/WSL 真实集群 smoke 12/12 PASS（kind v0.34 / K8s v1.37.0，证据 backend/temp_test/week13-local/EVIDENCE.md）。未完成：已认证 Playwright 流程、run_week13_17_acceptance.sh 收集脚本、远端 CI 收据。Week 13 状态为 in_progress。

**Goal:** 在不改变通用平台 Task 1–14 合同的前提下，交付项目级 Kubernetes 集群登记、凭据引用、命名空间、资源组、节点能力发现与连通性检查，并通过 kind/WSL 真实集群 smoke；为 Week 14 执行器提供集群身份与凭据引用底座。

**Architecture:** API 层（认证/项目权限/审计）→ 领域服务（登记校验、状态机、检查结果持久化）→ 客户端适配器（官方 kubernetes client + FakeKubernetesClient）→ credential resolver（调用时解析 `env:`/`file:` 引用）。Week 13 对集群只读发现 + 两处幂等写（登记、namespace ensure），无 Celery 任务、无长连接。

**Tech Stack:** FastAPI、Pydantic v2、SQLAlchemy、Alembic（当前 head `20260926_61`）、Kubernetes Python client（新增依赖）、React/TypeScript/Ant Design/Vitest、WSL2 kind。

**Spec:** [Week 13 技术方案](../../technical-proposals/2026-09-28-week13-kubernetes-foundation.md)、[Week 13–17 计划](2026-09-24-week13-17-development.md)、DEVELOPMENT_PLAN.md §4–§5。

## Global Constraints

- Week 13 状态为 `planned`；文档与 RED 测试不改变状态，完成 §13.7 全部门禁前不得宣称 completed。
- 所有 API 经 `get_current_user` + `ProjectAccessService`；跨项目资源隐藏式 404；写操作进 `AuditService` 并接受 `X-Request-ID`。
- 凭据材料不落库、不进 Settings 值、不进响应/日志/审计；只保存 `env:`/`file:` 引用。
- 端点 allowlist 默认为空（拒绝一切登记）；insecure http/TLS 需要"集群标记 + 设置开关"同时成立。
- 迁移线性接在 `20260926_61` 之后；SQLite/PostgreSQL 兼容、`upgrade head` + `alembic check` 证据、downgrade 保留无关表。
- 新测试模块只登记到 `week_manifest.py` / `weekAcceptance.test.ts` 的第 13 周，各登记一次。

> **迁移修订号更正（2026-09-28）：** Week 13–17 总计划编写时假设下一个空闲修订号是 `_61`；2026-09-26 main 已合入 `20260926_61_widen_annotation_task_status`。Week 13 使用 `_62`，Week 14–17 的计划迁移号依次顺延为 `_63`–`_66`，实际修订号以各周实现日的空闲号为准。

## File map

Create:

- `ml-platform/backend/app/models/cloud_resources.py`
- `ml-platform/backend/app/schemas/cloud_resources.py`
- `ml-platform/backend/app/services/kubernetes_client.py`
- `ml-platform/backend/app/services/kubernetes_cluster.py`
- `ml-platform/backend/app/api/kubernetes_clusters.py`
- `ml-platform/backend/alembic/versions/20260928_62_cloud_resources.py`
- `ml-platform/frontend/src/api/kubernetes.ts`
- `ml-platform/frontend/src/pages/KubernetesPage.tsx`
- `ml-platform/backend/tests/test_kubernetes_client.py`
- `ml-platform/backend/tests/test_kubernetes_cluster_api.py`
- `ml-platform/backend/tests/test_cloud_resource_migrations.py`
- `ml-platform/frontend/src/pages/KubernetesPage.test.tsx`

Modify:

- `ml-platform/backend/app/models/__init__.py`（导入 + `__all__`）
- `ml-platform/backend/app/config.py`（5 个 `kubernetes_*` 设置项）
- `ml-platform/backend/app/main.py`（`app.include_router(kubernetes_clusters.router)`）
- `ml-platform/backend/requirements.txt`（新增 `kubernetes`）
- `ml-platform/backend/.env.example`（设置示例与凭据引用说明）
- `ml-platform/backend/tests/week_manifest.py`（新增 `13: [...]`）
- `ml-platform/frontend/src/App.tsx`、`components/AppLayout.tsx`、`i18n/index.tsx`
- `ml-platform/frontend/src/weekAcceptance.test.ts`（新增第 13 周）

## Task 13.0 决策前置（Task 0 的 Week 13 子集）——已收口（2026-09-28）

**Files:** 文档 only：DEVELOPMENT_PLAN.md §4.1、本计划、技术方案 §12。

- [x] 测试集群形态：WSL2 内新建 kind 集群；WSL Docker Server 29.7.2 已可用，kind/kubectl 在 Task 13.6 安装。
- [x] 凭据引用约定：`env:LINKRAFT_*_TOKEN` + `file:` CA/证书，与仓库既有 `*_file` 密钥引用惯例一致。
- [x] 管理角色映射：复用 `resource.create/update/delete`（owner + editor）与 `project.read`（全体成员角色）；不新增 permission 串，不给平台 admin 新增项目旁路。
- [x] insecure http/TLS 豁免：默认全程 TLS 验证，kind 以 `file:` 引用 kind CA；`insecure_tls` 仅为 WSL IP SAN 不匹配兜底，双开关 + 审计。
- [ ] Task 13.6 smoke 时回填 allowlist 终值（`127.0.0.1:<端口>` + 备用 WSL IP）。
- [ ] Week 15 builder 路径与 Week 17 范围决策仍开放；不阻塞 Week 13 编码，但阻塞 Week 15/17。

Verification: 决策记录见 DEVELOPMENT_PLAN.md §4.1 与技术方案 §12；Task 0 其余项（镜像仓库、GPU 节点、Week 15/17）如实保持开放。

## Task 13.1 模型与迁移（RED → 实现）

- [x] 写 `test_cloud_resource_migrations.py` 失败测试：空 SQLite upgrade 到 head；四张表/索引/唯一约束存在；downgrade 保留无关表数据；`(project_id, name)`、`(cluster_id, name)`、`(cluster_id, project_id, name)` 唯一。
- [x] 写模型失败测试（并入上文件或 `test_kubernetes_cluster_api.py` 的模型段）：credential ref 格式校验拒绝明文 token/相对路径；namespace 名 RFC 1123 校验；quota_json 键与正数校验。
- [x] 实现 `cloud_resources.py` 四个模型并在 `app/models/__init__.py` 注册。
- [x] 实现 `20260928_62_cloud_resources.py`：down_revision=`20260926_61`；索引 `project_id`/`status`/`last_checked_at`；PostgreSQL 与 SQLite 双通过。
- [x] `alembic upgrade head` + `alembic check` 通过。

## Task 13.2 KubernetesClient 适配器（RED → 实现）

- [x] 写 `test_kubernetes_client.py` 失败测试：`KubernetesClientProtocol` 四方法（check_connectivity/list_namespaces/list_nodes/ensure_namespace）；超时映射 `KUBERNETES_TIMEOUT`；连接失败→`KUBERNETES_CONNECTIVITY_FAILED`；401/403→`KUBERNETES_AUTH_FAILED`；TLS 失败→`KUBERNETES_TLS_ERROR`；异常消息脱敏（不含 token/query/environ）；依赖缺失→`KUBERNETES_CLIENT_UNAVAILABLE`；FakeKubernetesClient 可编程注入成功/失败。
- [x] 实现 `kubernetes_client.py`：惰性导入官方 client；`build_kubernetes_client(cluster, credential_ref)` 组装配置并在此时解析 `env:`/`file:` 引用；每个调用显式 connect/read 超时；官方异常映射为技术方案 §6 错误码并脱敏。
- [x] `requirements.txt` 增 `kubernetes`；确认依赖缺失路径不破坏现有导入。

## Task 13.3 领域服务与 API（RED → 实现）

- [x] 写 `test_kubernetes_cluster_api.py` 失败测试：
  - 登记成功 201；同项目重名 409 `CLUSTER_NAME_EXISTS`；endpoint 非法 scheme/host 不在 allowlist/userinfo→422；credential ref 非法→422。
  - 列表/详情按项目过滤；跨项目 ID 隐藏式 404。
  - connectivity-check：成功持久化 `last_check_*` 且版本字段回填；Fake 注入失败时状态收敛 `connectivity_failed`、`credential ref` 与登记字段不变、返回 200 + error_code；stale 标记按 `kubernetes_stale_after_seconds`。
  - PUT namespaces 幂等：两次调用同一资源；非法名/配额 422。
  - 资源组 CRUD 校验与重名 409。
  - 审计事件存在且 payload 无凭据材料；写端点回显 `X-Request-ID`。
- [x] 实现 `schemas/cloud_resources.py`（请求/响应模型，响应不含 secret 字段）。
- [x] 实现 `kubernetes_cluster.py`：登记校验（§5.2 端点 + §5.1 引用）、状态机（§6）、检查结果持久化、命名空间 ensure、资源组服务。
- [x] 实现 `kubernetes_clusters.py` 路由（前缀 `/api/kubernetes`，端点与技术方案 §7 表一致），`config.py` 增设置，`main.py` 注册路由。
- [x] `.env.example` 增示例。

## Task 13.4 前端 KubernetesPage（RED → 实现）

- [x] 写 `KubernetesPage.test.tsx` 失败测试：集群列表渲染（状态徽标/最近检查/时延）；检查按钮失败时展示本地化错误码；stale 提示；断言页面不含 secret 字段；i18n 键存在。
- [x] 实现 `api/kubernetes.ts`（基于 `client.ts` 惯例，错误经 `localizeApiError`）。
- [x] 实现 `KubernetesPage.tsx`（结构见技术方案 §8）；`App.tsx` 增 `/kubernetes` 路由（ProtectedRoute + PageErrorBoundary）；`AppLayout.tsx` 增导航（ClusterOutlined + `t.nav.kubernetes`）；`i18n/index.tsx` 补中英文文案与全部 `KUBERNETES_*` 错误码。

## Task 13.5 清单登记与聚焦门禁

- [x] `week_manifest.py` 增 `13: ["test_kubernetes_client", "test_kubernetes_cluster_api", "test_cloud_resource_migrations"]`；`weekAcceptance.test.ts` 增第 13 周（KubernetesPage.test.tsx）。
- [x] 运行聚焦门禁（pwsh，仓库根）：

```powershell
Set-Location .\ml-platform\backend
.\.venv\Scripts\python.exe -m pytest tests/test_kubernetes_client.py tests/test_kubernetes_cluster_api.py tests/test_cloud_resource_migrations.py -q
.\.venv\Scripts\python.exe run_suite.py --week 13
.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check

Set-Location ..\frontend
npm test -- --run
npx tsc --noEmit
npm run build

Set-Location ..\..
git diff --check
```

## Task 13.6 kind/WSL 真实集群 smoke 与证据

- [x] WSL 内创建（或复用）kind 集群；创建最小权限 ServiceAccount（nodes get/list、namespaces get/list/create、resourcequotas get/list/create/update、events get/list）并生成凭据；RBAC 清单归档。
- [x] 本地 Settings：allowlist 增 kind endpoint；仅本地启用 `KUBERNETES_ALLOW_INSECURE_ENDPOINTS`；凭据以 `env:`/`file:` 引用提供。
- [x] 通过 API 或页面：登记 → connectivity-check（记录版本/时延）→ GET nodes（返回 kind 节点）→ PUT namespaces（集群内确认 namespace + ResourceQuota 对象存在）→ 用无效凭据重复检查（确认 `connectivity_failed` 收敛且登记未变）。
- [ ] 已认证 Playwright：登记 → 检查 → 节点表流程。
- [ ] 建 `ml-platform/backend/tools/acceptance/run_week13_17_acceptance.sh` 的 Week 13 profile（Week 14+ 复用并扩展），证据写入 `temp_test/week13-local/` 并绑定当前 SHA（Kubernetes 版本、namespace、ServiceAccount、RBAC 清单、证据路径、每条命令退出码）。

## Task 13.7 台账与索引收口

- [ ] 按 plans/README 维护规则：先更新 DEVELOPMENT_PLAN.md（状态、SHA、测试数字、未验证范围），再归档详细记录；任何 blocked/failed 项如实记录，Week 13 保持 `in_progress`。

## Exit gate

- kind/WSL 集群可登记、检查、发现（节点/命名空间）；invalid endpoint、失效凭据、超时全部收敛为显式失败状态且不伪造成功；跨项目访问隐藏式 404；迁移与聚焦测试全绿；前端测试/tsc/build 通过；证据绑定当前 SHA。**本周期不含任何 Job 提交。**

## Explicit exclusions

- 不实现 Job/Pod、Notebook、镜像、GPU、多集群路由、配额执行；不存储凭据材料；不引入 Celery 任务或 watch 长连接（Week 14 范围）。
- 不修改通用平台 Task 1–14 合同与历史点焊测试；不以 mock、本文档或历史收据宣称完成。
