# Week 16 多集群与资源治理实施计划

> For agentic workers: execute the tasks in order, keep each checkbox independently reviewable. 本计划是 [2026-09-24 Week 13–17 计划](2026-09-24-week13-17-development.md) Task 4 的细化执行入口；设计合同见 [Week 16 技术方案](../../technical-proposals/2026-09-28-week16-multi-cluster-governance.md)。前置：Week 13–15 已通过退出门禁。

**Goal:** 交付多集群路由（可解释、fail-closed）、存储绑定（不越界）、配额/并发预留（不超卖）、K8s 用量快照（带时效），单集群行为保持兼容，并通过双 kind 集群 smoke（一健康一不健康）。

**Architecture:** 提交链路在 Week 14/15 submit 前插入"路由 → DB 预留 → submit"钩子；终态/孤儿/过期统一释放；scheduler beat 驱动 reconcile、用量采集（Summary API）与快照清理；治理 API 独立前缀，既有页面零破坏。

**Tech Stack:** Week 13–15 全部既有设施、K8s Summary API（API server proxy）、React/Vitest。

**Spec:** [Week 16 技术方案](../../technical-proposals/2026-09-28-week16-multi-cluster-governance.md)、[Week 13–17 计划](2026-09-24-week13-17-development.md)、DEVELOPMENT_PLAN.md §4–§5。

## Global Constraints

- 状态 `planned`；Week 13–15 未收口不得开始集群侧实现。
- 单集群兼容是硬门禁：无策略时路由退化直选，既有页面/API 行为不变。
- 预留只在 DB 事务内创建（唯一约束 + 聚合校验），四条释放路径幂等；配额校验不依赖前端禁用。
- 存储绑定拒绝任意 hostPath；object_prefix 必须匹配 `projects/{project_id}/` 受控前缀。
- 用量采集失败 → stale 标记，不阻塞提交；禁止用主机 nvidia-smi 数据冒充集群 GPU 监控。
- 迁移计划名 `20260924_65_resource_governance.py`（以实现日空闲号为准）。

## File map

Create:

- `ml-platform/backend/app/models/resource_governance.py`
- `ml-platform/backend/app/schemas/resource_governance.py`
- `ml-platform/backend/app/services/cluster_scheduler.py`（路由 + 预留）
- `ml-platform/backend/app/services/resource_governance.py`（配额/绑定/快照服务）
- `ml-platform/backend/app/services/storage_mounts.py`（绑定校验与挂载注入）
- `ml-platform/backend/app/api/cluster_governance.py`
- `ml-platform/backend/alembic/versions/20260924_65_resource_governance.py`
- `ml-platform/backend/tests/test_multi_cluster_scheduler.py`、`test_resource_governance.py`、`test_storage_mounts.py`、`test_cluster_observability.py`
- `ml-platform/frontend/src/api/clusterGovernance.ts`、`src/pages/ClusterGovernancePage.tsx`、`src/pages/ClusterGovernancePage.test.tsx`

Modify:

- Week 14 `kubernetes_executor.py` / Week 15 `notebook_service.py`（提交前路由 + 预留钩子、终态释放钩子）
- `app/tasks/celery_app.py`（采集/清理 beat）、`app/models/__init__.py`、`app/config.py`（`governance_*` 设置）、`app/main.py`
- `frontend/src/App.tsx`（`/cluster-governance` 路由）、`components/AppLayout.tsx`、`i18n/index.tsx`（`QUOTA_*`/`NO_ELIGIBLE_CLUSTER`/`STORAGE_*` 错误码）
- `tests/week_manifest.py`（新增 `16:` 键）、`frontend/src/weekAcceptance.test.ts`（第 16 周）

## Task 16.1 模型与迁移（RED → 实现）

- [ ] RED：五张表唯一键（policy `(project_id, priority)`、reservation `operation_id` 唯一、quota `(scope, scope_id)` 唯一）；quota_json 键白名单与非负校验；空库 upgrade / downgrade / `alembic check`。
- [ ] 实现 `resource_governance.py` 模型 + 迁移 `20260924_65`。

## Task 16.2 路由器（RED → 实现）

- [ ] RED（`test_multi_cluster_scheduler.py`）：无策略单集群退化（reason=`default_single_cluster`）；策略按 priority 生效；能力/region/cost 排序确定性；stale/`connectivity_failed` 集群排除；GPU 需求无匹配容量排除；拒绝结果逐集群携带排除原因；`routing/preview` 不落预留。
- [ ] 实现 `cluster_scheduler.py` 路由部分。

## Task 16.3 预留与配额（RED → 实现）

- [ ] RED（`test_resource_governance.py`）：事务内聚合校验（并发多线程预留总和 ≤ quota，超卖必须失败）；`operation_id` 唯一；四条释放路径（terminal/orphaned/expired/manual-internal）幂等且记录 release_reason；配额 CRUD 带 revision 与审计。
- [ ] 实现 `cluster_scheduler.py` 预留部分 + `resource_governance.py` 配额服务。
- [ ] Week 14 executor / Week 15 notebook 服务接入钩子：submit 前路由 + 预留（失败 `QUOTA_EXCEEDED`/`NO_ELIGIBLE_CLUSTER`），终态与 reconcile 孤儿判定后释放；既有单集群路径回归断言不变。

## Task 16.4 存储绑定（RED → 实现）

- [ ] RED（`test_storage_mounts.py`）：PVC 属主与命名空间校验；object_prefix 必须 `projects/{project_id}/` 前缀（越界 422）；read_only 绑定注入只读挂载；hostPath 永远 422；绑定变更审计。
- [ ] 实现 `storage_mounts.py` + 绑定 API 校验。

## Task 16.5 用量采集（RED → 实现）

- [ ] RED（`test_cluster_observability.py`）：Summary API fake 响应解析（node/pod cpu/mem）；每轮每 scope ≤100 条截断 + `truncated` 标记；采集失败 → stale 标记且不抛出到提交路径；GPU 无 device plugin → `unavailable`；快照过期清理；手动采集端点 502 封闭。
- [ ] 实现采集器（API server proxy 调用）+ beat 注册（默认 60s）+ `resource_governance.py` 快照查询。

## Task 16.6 治理 API 与前端（RED → 实现）

- [ ] RED（API 权限/校验用例并入各测试文件）：策略/绑定/配额端点 `resource.*` 权限矩阵、跨项目 404、审计、X-Request-ID。
- [ ] RED（`ClusterGovernancePage.test.tsx`）：策略/配额/绑定表渲染、配额用量对比条、stale/truncated 提示、路由预演面板（逐集群排除原因）、配额拒绝错误的本地化呈现。
- [ ] 实现 `cluster_governance.py` + 前端页 + 路由 + 导航 + i18n。

## Task 16.7 清单登记与聚焦门禁

- [ ] `week_manifest.py` 新增 `16: ["test_multi_cluster_scheduler", "test_resource_governance", "test_storage_mounts", "test_cluster_observability"]`；`weekAcceptance.test.ts` 第 16 周。
- [ ] 聚焦门禁（模式同前几周，替换 `--week 16` 与新文件名）：pytest 四模块 → `run_suite.py --week 16` → compileall → alembic → 前端三件套 → `git diff --check`。

## Task 16.8 双 kind 集群 smoke 与证据

- [ ] WSL 内建第二个 kind 集群；两集群均完成 Week 13 式登记（各自凭据引用/allowlist 条目）。
- [ ] 场景：双健康 → 路由按策略可解释选择；人为停掉其一 API server → 排除并给原因；正常集群提交 → 预留出现 → 终态释放；并发提交触顶 → `QUOTA_EXCEEDED`；用量快照采集出现且断源集群标记 stale；移除策略 → 单集群回归路径与 Week 13–15 一致。
- [ ] 证据写入 `temp_test/week16-local/`，绑定当前 SHA（两集群版本、namespace、预留/释放记录、快照样本）；Playwright：治理页展示 + 配额拒绝呈现。

## Task 16.9 台账收口

- [ ] 先更新 DEVELOPMENT_PLAN.md，再归档详细记录；单集群兼容回归结果必须显式记录，Week 16 保持 `in_progress` 直至门禁全绿。

## Exit gate

- 不健康集群被排除且原因可解释；配额并发不超卖（竞态测试固化）；存储不能越界；单集群默认行为保持；多集群 smoke 全绿；快照带时效与截断语义；聚焦测试/迁移/前端门禁通过；证据绑定当前 SHA。

## Explicit exclusions

- 不对接计费系统；不做跨集群数据复制；不改 `/api/monitor` 主机监控；不做 Week 17 数据探索；不以 mock 或本文档宣称完成。
