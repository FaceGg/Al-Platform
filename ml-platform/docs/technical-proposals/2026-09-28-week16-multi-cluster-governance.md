# Week 16 多集群与资源治理技术方案

**日期：** 2026-09-28
**状态：** 评审稿。Week 16 为 `planned`，依赖 Week 13–15（集群、执行器、GPU 类）；单集群既有行为保持兼容是硬门禁。
**范围：** 多集群路由策略、存储绑定、配额/并发/成本治理、集群/节点/Pod/GPU 用量监控
**不包含：** 数据探索（Week 17）、计费系统集成、跨集群数据搬迁、新增 RAG/LLM 能力

## 1. 目标与方案定位

把 Week 13–15 的单集群能力升级为**可治理的多集群能力**：作业与会话提交时由策略选出"当前最优且健康"的集群，资源使用在数据库预留与集群配额双通道下不超卖，存储绑定不越项目边界，用量可见且带时效标记。**单集群是本方案的退化特例**：只有一个 `active` 集群时路由退化为直选，既有页面行为不变。

## 2. 与既有合同的关系

| 既有合同 | Week 16 用法 |
|---|---|
| Week 13 集群/命名空间/资源组 | 路由候选集 = 项目内 `active` 且检查不 stale 的集群；ResourceGroup 升级为配额载体（`scheduling_policy_json`/`quota_json` 开始生效） |
| Week 14 执行器 | submit 前插入路由与预留钩子；终态/孤儿路径统一触发预留释放 |
| Week 15 GPU 类 | GPU 需求参与路由（无匹配容量的集群被排除并给出原因） |
| DurableOperation / 审计 / 权限 | 预留/释放幂等；策略与配额变更走 `resource.*` + 审计 |
| 既有主机监控 `/api/monitor`（CPU/内存/nvidia-smi 主机页） | **保持独立、互不代偿**：K8s 用量必须有 K8s 资源身份，禁止用主机 nvidia-smi 页面冒充集群 GPU 监控 |

## 3. 核心领域模型

新增 `app/models/resource_governance.py`，迁移计划名 `20260924_65_resource_governance.py`（以实现日空闲号为准）。

### 3.1 ClusterRoutingPolicy（表 `cluster_routing_policies`）

- `project_id`（NULL = 平台默认策略）、`priority`、`policy_json`：允许键 `region`、`capability_required`（gpu/storage_class 等）、`cost_weight`、`queue_limit`；`(project_id, priority)` 唯一。
- 路由结果必须返回 `selected_cluster_id + reason + policy_revision`，reason 取值枚举（`default_single_cluster` / `capability_match` / `cost_min` / `region_match` / …），拒绝时 `no_eligible_cluster` + 逐集群排除原因。

### 3.2 StorageBinding（表 `storage_bindings`）

- `project_id`、`cluster_id`、`mode(pvc|object_prefix)`、`pvc_name`（mode=pvc 时，须属于项目命名空间）、`object_prefix`（mode=object_prefix 时，必须等于 `projects/{project_id}/...` 受控前缀）、`access(read_only|read_write)`、`status`。
- 校验：`read_only` 绑定注入为只读挂载；**任意 hostPath 永远非法**；object_prefix 前缀不匹配即 422（越界防护在服务端，不依赖前端）。

### 3.3 ResourceQuotaPolicy（表 `resource_quota_policies`）

- `scope(project|resource_group)`、`scope_id`、`quota_json`：`cpu_cores`、`memory_mb`、`gpu_count`、`storage_gb`、`max_concurrent_jobs`、`max_concurrent_notebooks`、`notebook_idle_seconds`。
- `(scope, scope_id)` 唯一；数值非负；修改走审计并记录 revision。

### 3.4 ResourceReservation（表 `resource_reservations`）

- `project_id`、`cluster_id`、`operation_id`（FK durable_operations）、`quota_policy_id`、`reserved_json`（本次预留量）、`state(active|released|expired)`、`released_at`、`release_reason(terminal|orphaned|expired|manual)`。
- 唯一约束 `(operation_id)` —— 一个操作一份活跃预留；释放幂等。

### 3.5 ResourceUsageSnapshot（表 `resource_usage_snapshots`）

- `cluster_id`、`scope(cluster|node|pod|gpu)`、`subject`（节点名/Pod 名/GPU 序号）、`metrics_json`（cpu/mem/分配量）、`collected_at`。
- 基数约束：每集群每轮每 scope 最多 100 条（超出截断并标记 `truncated=true`）；快照保留期由 Settings 限定，过期清理走既有清理机制。

## 4. 关键技术决策

### 4.1 用量采集：K8s Summary API（零安装）而非 metrics-server

**决策：经 API server proxy 读取 kubelet Summary API**（`/api/v1/nodes/{node}/proxy/stats/summary`），不要求安装 metrics-server：

- kind 集群零额外安装即可采集 node/pod 用量；GPU 分配量取自 node status（`allocatable`/容量），**GPU 实时利用率仅在集群存在 device plugin 指标端点时采集，否则记 `unavailable`**，不伪造。
- 采集器由 scheduler beat 周期驱动（默认 60s，可配），失败收敛为 stale 标记，不阻塞提交路径。

### 4.2 预留/释放的双通道防超卖

- 提交路径：路由选中集群 → 在 `active` 预留行上以事务 + 配额聚合校验（DB 侧 `SUM(active reservations) + request ≤ quota`）→ 预留落库 → 才允许 Week 14 submit。集群侧 ResourceQuota 对象（Week 13 ensure 的 quota）作为第二道防线；两者语义不一致时以更严格者为准。
- 释放路径：Week 14 终态（succeeded/failed/cancelled/timed_out/orphaned）与 reconcile 的孤儿判定统一触发释放；beat 兜底回收 `expired`（操作行已终态但预留残留）。并发提交的竞态由唯一约束 + 行级事务断言（RED 测试覆盖）。

### 4.3 单集群兼容

- 无任何 RoutingPolicy 时，路由直接返回唯一 `active` 集群，reason=`default_single_cluster`，不写策略行；Week 13–15 页面与 API 行为不变（回归测试固化）。

## 5. 接口边界

前缀 `/api/cluster-governance`；权限：策略/绑定/配额写 = `resource.create/update/delete`，查看 = `project.read`；预留/释放由执行链路内部触发（不经手动端点），排障只读端点开放：

| 方法 路径 | 语义 | 主要错误 |
|---|---|---|
| GET/POST/PATCH/DELETE `/routing-policies` | 策略 CRUD（revision 递增） | 422 校验；404 隐藏式 |
| GET/POST/PATCH/DELETE `/storage-bindings` | 绑定 CRUD（前缀/PVC 校验） | 422 `STORAGE_BINDING_INVALID` |
| GET/POST/PATCH `/quota-policies` | 配额 CRUD（含 revision） | 422 校验 |
| GET `/reservations` | 预留列表（含活跃聚合） | — |
| GET `/usage` | 用量快照查询（按集群/scope/时间窗；stale/truncated 标记） | — |
| POST `/usage/collect` | 手动触发采集（排障） | 502 采集失败 |
| GET `/routing/preview` | 给定需求（cpu/gpu/能力）预演路由结果（含逐集群排除原因，不落预留） | — |

提交链路变更：Week 14 `POST /jobs` 与 Week 15 `POST /notebooks` 内部先走路由 + 预留；预留失败返回 `QUOTA_EXCEEDED` / `NO_ELIGIBLE_CLUSTER`（带排除原因）。

## 6. 前端交互方案

`ClusterGovernancePage`（`/cluster-governance`）：路由策略表（含 revision）、存储绑定表（前缀/只读徽标）、配额表（当前用量对比条）、活跃预留列表、用量快照（含 stale/truncated 提示）、路由预演面板（显示逐集群排除原因）。既有 Compute/Kubernetes/Notebook 页保持不变，仅在提交错误处透出新的配额/路由错误码。

## 7. 测试与验收标准

1. `test_multi_cluster_scheduler.py`：确定性路由（同输入同结果）、不健康/stale 集群排除、能力不匹配排除、单集群退化、逐集群拒绝原因完整。
2. `test_resource_governance.py`：配额 CRUD/revision；并发预留竞态（多线程断言不超卖）；终态/孤儿/过期/手动四条释放路径幂等；预留聚合校验。
3. `test_storage_mounts.py`：PVC 属主校验、object_prefix 越界拒绝、read_only 注入、hostPath 永远 422。
4. `test_cluster_observability.py`：Summary API 解析（fake 响应）、基数截断与 stale、GPU 无插件时 `unavailable`、快照过期清理。
5. kind/WSL 多集群 smoke：两个 kind 集群（其一人为断网/停 API server）→ 路由排除不健康者并给原因 → 正常集群提交成功 → 预留随终态释放 → 用量快照出现；单集群回归（移除策略后行为与 Week 13–15 一致）。
6. 已认证 Playwright：治理页策略/配额/预演展示；提交被配额拒绝时的错误呈现。
7. 清单：`week_manifest.py` 新增 `16:` 键。

## 8. 开放决策点

| 决策项 | 本方案默认 | 状态 |
|---|---|---|
| 成本模型 | `cost_weight` 参与排序 + `cost_price_json` 单价表（Settings，默认全 0，仅报表展示，不对接计费） | 已决策（范围封顶） |
| 用量采集 | Summary API 零安装 | 已决策（§4.1） |
| PVC storageclass | kind `standard`；生产值运维配置 | smoke 时回填 |
| 是否需要"预留手动释放"管理端点 | 仅只读列表，释放不由手动触发 | 已决策（防误操作） |

## 9. 显式排除项

- 不对接计费/财务系统；不做跨集群数据复制；不修改 `/api/monitor` 主机监控语义；不做数据探索（Week 17）。
- 不以主机 nvidia-smi 数据冒充集群 GPU 监控；不以 mock 宣告多集群 smoke 完成。

## 10. 方案结论

Week 16 用"策略可解释、预留防超卖、绑定不越界、快照带时效"四条合同把单集群能力治理化，且以单集群退化为兼容底线。Week 17 若获批接入执行（质量报告作业化），将直接复用本层的配额与路由合同。
