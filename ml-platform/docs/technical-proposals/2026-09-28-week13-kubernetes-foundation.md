# Week 13 Kubernetes 基础接入技术方案

**日期：** 2026-09-28
**状态：** 评审稿。Week 13 整体仍为 `planned`；本方案获批后按[实施计划](../superpowers/plans/2026-09-28-week13-kubernetes-foundation.md)执行，完成周度门禁前不得宣称完成。Task 0 的 Week 13 子集五项决策已于 2026-09-28 收口（§12）。
**范围：** Kubernetes 集群登记、凭据引用、命名空间、资源组、节点能力发现、连通性检查及对应管理页
**不包含：** Job/Pod 执行（Week 14）、Notebook/镜像/GPU（Week 15）、多集群路由与配额执行（Week 16）、数据探索（Week 17）、开发排期与任务拆分

## 1. 目标与方案定位

Week 13 为 Week 14–16 的执行闭环、Notebook 和资源治理建立 Kubernetes 控制面底座，回答四个问题：

1. 一个项目如何登记一个集群，并证明"平台当前真的连得上它"。
2. 平台如何在不保存任何凭据材料的前提下使用集群凭据。
3. 项目如何映射到集群命名空间，并携带后续周次需要的配额/调度描述。
4. 管理页如何呈现集群健康、节点能力和命名空间状态，且失败时明确示警而不是伪装正常。

本周期内对集群只做**只读发现**（连通性、命名空间、节点）和两处幂等写（登记、命名空间 ensure）。任何业务负载的创建都在 Week 14 之后。

## 2. 与现有合同的关系

Week 13 不新建权限、审计、任务状态或幂等机制，全部复用既有合同：

| 既有合同 | Week 13 用法 |
|---|---|
| `get_current_user`（`app/api/auth.py`） | 所有端点的认证入口 |
| `ProjectAccessService`（`app/services/project_access.py`） | 项目归属裁决；`require` 用于管理操作，`accessible_project_query` 用于列表过滤 |
| `AuditService` / `redact_changes`（`app/services/audit.py`） | 写操作与连通性检查的审计链 |
| Alembic 线性迁移 | 新增迁移接在当前 head `20260926_61` 之后 |
| 前端 `client.ts` / `i18n/index.tsx` / `weekAcceptance.test.ts` | API client、错误本地化、测试周次登记 |

硬性边界：

1. 不改变通用平台 Task 1–14 的任何 API、schema 或行为；不新增点焊字段、路由或专用工作流依赖。
2. 跨项目资源一律返回既有隐藏式 404 语义，不通过错误消息、列表或 ID 泄露存在性。
3. 凭据材料（token、kubeconfig 内容、客户端证书）**永远不落库、不进 Settings 值、不进 API 响应、日志或审计 payload**，只允许以引用形式存在（见 §5）。
4. 迁移必须提供 SQLite/PostgreSQL 兼容、`upgrade head` + `alembic check` 证据和旧数据保留断言。

## 3. 总体架构

~~~text
主平台前端 KubernetesPage (/kubernetes)
        |
        v
主平台 API  /api/kubernetes/*
        |
        v
kubernetes_clusters.py（API 层：认证、项目权限、审计、序列化）
        |
        v
kubernetes_cluster.py（领域服务：登记校验、状态机、检查结果持久化）
        |
        v
kubernetes_client.py（客户端适配器）
   |-- KubernetesClientProtocol（check_connectivity / list_namespaces / list_nodes / ensure_namespace）
   |-- build_kubernetes_client(cluster, credential_ref)  -> 官方 kubernetes Python client
   |-- FakeKubernetesClient                              -> 单测与本地联调
        |
        v
credential resolver（调用时解析 env: / file: 引用，永不持久化）
        |
        v
真实集群或 WSL2 kind 测试集群
~~~

关键取向：

- **适配器隔离**：官方 `kubernetes` 包只在 `build_kubernetes_client` 内部导入；依赖缺失时降级为 `KUBERNETES_CLIENT_UNAVAILABLE`，不影响平台其余功能。
- **测试同路径**：单测通过 `FakeKubernetesClient` 注入成功、失败、超时和脱敏场景；mock 只用于单元层，真实集群证据必须来自 §11 的 kind/WSL smoke。
- **同步检查**：Week 13 的连通性检查是同步端点（总超时上限 10 秒），不引入 Celery 任务；watch/reconcile 等长连接机制属于 Week 14。

## 4. 核心领域模型

新增文件 `app/models/cloud_resources.py`，在 `app/models/__init__.py` 注册；主键沿用仓库惯例（UUID 存 CHAR(32) hex）。

### 4.1 ClusterRegistration（表 `kubernetes_clusters`）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(32) PK | UUID hex |
| project_id | FK projects.id | 属主项目；`(project_id, name)` 唯一 |
| name | VARCHAR(64) | 项目内唯一标识 |
| display_name | VARCHAR(128) | 展示名 |
| api_server_url | TEXT | 规范化后的 API server 地址（无 userinfo、无 query/fragment） |
| insecure_tls | BOOL | 默认 False；仅测试集群允许 True，且须与设置开关同时成立 |
| provider | VARCHAR(32) | `generic`（默认）/ `kind` 等，仅作描述，不驱动行为 |
| kubernetes_version | VARCHAR(32) NULL | 连通性检查发现 |
| capabilities | JSON | 节点能力汇总快照（gpu/存储类等），只由发现流程写入 |
| default_namespace | VARCHAR(63) NULL | 默认命名空间名 |
| status | VARCHAR(24) | `pending` / `active` / `connectivity_failed` / `disabled` |
| last_check_status / last_check_error_code / last_check_message / last_checked_at / last_check_latency_ms | — | 最近一次连通性检查结果；message 脱敏 |
| created_by | FK users.id | 审计归属 |
| created_at / updated_at / archived_at | — | 软删用 `archived_at`，不物理删除 |

索引：`project_id`、`status`、`last_checked_at`。

### 4.2 ClusterCredentialRef（表 `kubernetes_credential_refs`）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(32) PK | |
| cluster_id | FK，唯一 | 一 cluster 一凭据引用（Week 13） |
| secret_ref | VARCHAR(255) | `env:VARIABLE_NAME` 或 `file:/absolute/path`，格式见 §5.1 |
| ref_namespace | VARCHAR(63) NULL | 引用在集群内的作用域（预留，Week 13 仅记录） |
| allowed_use | VARCHAR(32) | `connectivity`（Week 13 唯一合法值）；`jobs`/`notebooks` 由 Week 14–15 扩展 |

**表内没有任何凭据内容字段**；校验层拒绝把疑似 token（长随机串、含空白、"Bearer " 前缀等）填入 `secret_ref`。

### 4.3 ClusterNamespace（表 `kubernetes_namespaces`）

| 字段 | 类型 | 说明 |
|---|---|---|
| id / cluster_id / project_id | PK / FK / FK | `(cluster_id, name)` 唯一 |
| name | VARCHAR(63) | RFC 1123 label（小写字母数字与 `-`，≤63） |
| status | VARCHAR(24) | `pending` / `active` / `failed` |
| quota_cpu_millicores / quota_memory_mb | INT NULL | 便于列表展示的常用配额摘要 |
| quota_json | JSON NULL | 完整配额/调度描述（结构在 §4.4 冻结） |
| last_synced_at | — | 最近一次与集群状态对齐时间 |

### 4.4 ResourceGroup（表 `kubernetes_resource_groups`）

| 字段 | 类型 | 说明 |
|---|---|---|
| id / cluster_id / project_id | PK / FK / FK | `(cluster_id, project_id, name)` 唯一 |
| name / description | VARCHAR(64) / VARCHAR(255) | |
| scheduling_policy_json | JSON | Week 13 只冻结必填键 `policy_type`（当前唯一合法值 `default`）；其余键 Week 16 扩展 |
| quota_json | JSON | 允许键：`cpu_cores`、`memory_mb`、`max_pods`；数值必须为正 |
| status | VARCHAR(24) | `active` / `disabled` |

Week 13 中 ResourceGroup 只是**登记和查询**：调度与配额的执行语义由 Week 16 实现，本周期不提供任何"按资源组调度"的入口。

## 5. 集群凭据与端点安全合同

### 5.1 凭据引用格式

`secret_ref` 只接受两种形式：

| 形式 | 示例 | 解析行为 |
|---|---|---|
| `env:VARIABLE_NAME` | `env:LINKRAFT_KIND_TOKEN` | 调用时读环境变量；`^[A-Z][A-Z0-9_]*$` |
| `file:/absolute/path` | `file:///etc/linkraft/kind/ca.crt` | 调用时读文件；路径必须绝对且存在 |

违规示例（一律 422 拒绝）：原始 token 字符串、含空白的值、`Bearer eyJ...`、相对路径、`env:` 后小写或空名。

解析时机：仅在 `build_kubernetes_client` 组装客户端配置的瞬间，由 credential resolver 读取；解析结果只在内存中，不写库、不写日志、不进错误消息（错误只报 `KUBERNETES_CREDENTIAL_MISSING` / `KUBERNETES_CREDENTIAL_INVALID`）。

### 5.2 端点校验（SSRF 封闭）

`api_server_url` 是用户输入，按以下顺序校验，任一失败即 422 并返回对应错误码：

1. scheme 仅允许 `https`；`http` 必须同时满足：集群 `insecure_tls=True` **且** Settings `kubernetes_allow_insecure_endpoints=True`（供 kind/本地测试）。
2. URL 不得携带 userinfo、query 或 fragment；总长 ≤ 2083。
3. host 必须匹配 Settings `kubernetes_endpoint_allowlist`（支持精确主机与 `*.suffix` 通配）；**allowlist 为空时拒绝一切登记**，默认值即空——fail-closed，具体值是 Task 0 决策项。
4. 禁止云元数据地址（如 `169.254.169.254`）与 loopback 上的非显式放行主机。

### 5.3 TLS 与最小权限

- 默认验证服务端证书；`insecure_tls=True` 仅在 §5.2 双开关成立时允许，且登记/更新行为进入审计。
- Week 13 所需 ServiceAccount 权限（kind smoke 使用独立 SA，不用集群管理员）：nodes get/list、namespaces get/list/create、resourcequotas get/list/create/update、events get/list。RBAC 清单随 smoke 证据归档。

## 6. 连通性状态机与失败语义

~~~text
             check ok            check ok
  pending ----------> active <----------- connectivity_failed
     |  check fail                        ^    |
     +------------------> connectivity_failed -+
                                  check fail（保持）

  active / connectivity_failed --手动禁用--> disabled（可手动恢复）
~~~

规则：

1. 检查结果（状态、错误码、脱敏消息、时延、时间戳）持久化到 `last_check_*`；**失败检查绝不改变集群 `status` 之外的任何登记字段，尤其不得改动 credential ref**。
2. `connectivity_failed` 是可恢复状态：下次检查成功即回到 `active`。不存在"半成功"。
3. 时效标记：`now - last_checked_at > kubernetes_stale_after_seconds`（默认 300 秒）时，列表与详情接口返回 `stale=true`，前端显示"结果已过期"，不自动触发新检查。
4. 错误码收敛（前端 i18n `apiErrors` 同步补齐）：

| 错误码 | 触发 |
|---|---|
| `KUBERNETES_ENDPOINT_INVALID` | scheme/host/长度/格式不合法 |
| `KUBERNETES_ENDPOINT_FORBIDDEN` | host 不在 allowlist 或命中禁用地址 |
| `KUBERNETES_CREDENTIAL_MISSING` / `KUBERNETES_CREDENTIAL_INVALID` | 引用无法解析 / 格式非法 |
| `KUBERNETES_CONNECTIVITY_FAILED` | 连接拒绝、DNS 失败、5xx |
| `KUBERNETES_TIMEOUT` | 超出 connect/read 超时 |
| `KUBERNETES_TLS_ERROR` | 证书验证失败 |
| `KUBERNETES_AUTH_FAILED` | 401/403 |
| `KUBERNETES_CLIENT_UNAVAILABLE` | 运行环境缺少 kubernetes 依赖 |
| `KUBERNETES_NAMESPACE_INVALID` / `KUBERNETES_QUOTA_INVALID` | 命名空间名或配额结构不合法 |

适配器把官方 client 的任意异常映射为上表之一，异常消息先经脱敏（剔除 URL query、token、environ 内容）再入库。

## 7. 接口边界

统一前缀 `/api/kubernetes`，全部经 `get_current_user`；写操作接受 `X-Request-ID` 并回显；错误体 `{code, message, details?}`。"管理"= 复用既有 `resource.create`/`resource.update`/`resource.delete` 权限（owner + editor，见 §12 决策 4）；"成员"= `project.read`（全体成员角色）。

| 方法 路径 | 权限 | 语义 | 主要错误 |
|---|---|---|---|
| POST `/clusters` | 管理 | 登记；`(project_id, name)` 冲突返回 409，不隐式覆盖 | 409 `CLUSTER_NAME_EXISTS`；422 §5/§6 错误码 |
| GET `/clusters` | 成员 | 项目内列表，带 `stale` 标记；分页 `limit/offset` | — |
| GET `/clusters/{id}` | 成员 | 详情；跨项目隐藏式 404 | 404 |
| PATCH `/clusters/{id}` | 管理 | 更新展示名/endpoint/credential ref/default namespace/insecure_tls | 422 同上 |
| DELETE `/clusters/{id}` | 管理 | 软删（`archived_at` + `status=disabled`），不物理删除 | 404 |
| POST `/clusters/{id}/connectivity-check` | 管理 | **同步**检查（≤10s）；结果持久化。HTTP 200 返回 `{check_status, error_code?, latency_ms, checked_at}`——集群连不上不是 HTTP 错误，只有请求本身不合法才 4xx | 404；503 `KUBERNETES_CLIENT_UNAVAILABLE` |
| GET `/clusters/{id}/nodes` | 成员 | 实时节点能力（`hostname/arch/cpu/memory/gpu/labels`，上限 100 条） | 502 §6 家族 |
| GET `/clusters/{id}/namespaces` | 成员 | 实时命名空间列表（只读） | 502 §6 家族 |
| PUT `/clusters/{id}/namespaces/{name}` | 管理 | **幂等 ensure**：不存在则创建，存在则对齐 quota；同参数重放返回同一资源 | 422 `KUBERNETES_NAMESPACE_INVALID` / `KUBERNETES_QUOTA_INVALID` |
| POST `/resource-groups`、GET `/resource-groups`、GET/PATCH `/resource-groups/{id}` | 管理 / 成员 | 资源组登记（仅数据库，无集群副作用） | 409 重名；422 校验 |

响应不包含任何凭据材料；`secret_ref` 原样回显（它本身只是引用名）。

## 8. 前端交互方案

新增路由 `/kubernetes`（`ProtectedRoute` + `PageErrorBoundary`），导航项使用 `ClusterOutlined` + `t.nav.kubernetes`；`i18n/index.tsx` 补齐中英文页面文案与全部 `KUBERNETES_*` 错误码。

`KubernetesPage` 结构：

1. **集群列表**（表格）：名称、endpoint、provider、状态徽标（pending/active/connectivity_failed/disabled）、最近检查时间 + 时延、stale 提示条。
2. **连通性检查**：行内按钮；结果为失败时展示本地化错误码与脱敏消息，页面不轮询、不自动重试。
3. **节点能力表**：从 `/nodes` 拉取，展示 CPU/内存/GPU/架构/关键标签。
4. **命名空间与资源组面板**：命名空间状态与配额摘要；资源组列表（Week 13 无调度语义，仅展示 policy_type 与 quota）。
5. **登记/编辑表单**：endpoint（附 allowlist 提示）、credential ref（`env:`/`file:` 前缀选择器）、default namespace、insecure_tls（仅在本地/测试模式暴露）。

红线：页面任何位置不出现 secret 材料；动作按钮的可用性以服务端状态为准，不引入前端专属状态机。

## 9. 权限与审计

- 项目隔离：所有读写先经 `ProjectAccessService`；跨项目 ID 一律 404。
- 审计（`AuditService.project_action`，payload 经 `redact_changes`）：`cluster.create/update/disable/archive`、`namespace.apply`、`connectivity.check`（含结果与耗时）、`resource_group.create/update`。只读发现不写审计。
- 审计内容不含凭据材料与完整异常栈；错误消息只保留脱敏后的 error_code + 摘要。

## 10. 配置与依赖

| 项 | 变更 |
|---|---|
| `requirements.txt` | 新增 `kubernetes`（官方客户端）；代码内惰性导入 |
| `app/config.py`（Settings 新增） | `kubernetes_endpoint_allowlist: list[str] = []`（默认拒绝一切）、`kubernetes_connect_timeout_seconds = 5`、`kubernetes_read_timeout_seconds = 10`、`kubernetes_stale_after_seconds = 300`、`kubernetes_allow_insecure_endpoints = False` |
| `.env.example` | 补充上述设置示例；注明凭据只通过 `env:`/`file:` 引用提供，模板中不出现真实 token |
| 迁移 | 新增 `20260928_62_cloud_resources.py`（接 `20260926_61` 之后；修订号以实现日空闲号为准） |

不新增任何 Settings 级 secret 字段；不引入 kubeconfig 文件挂载之外的集群访问方式。

## 11. 测试与验收标准

与 Week 13–17 总计划的周度门禁一致，分为四层，全部绑定当前 SHA：

1. **后端聚焦测试**（登记 `tests/week_manifest.py` 第 13 周，可 `run_suite.py --week 13`）：
   - `test_kubernetes_client.py`：协议符合性、超时、异常映射与脱敏、Fake 注入。
   - `test_kubernetes_cluster_api.py`：认证、项目隔离/隐藏式 404、端点与凭据校验、状态机收敛、审计事件、`(project, name)` 唯一性。
   - `test_cloud_resource_migrations.py`：空 SQLite upgrade、`alembic check`、downgrade 保留无关表、旧数据保留断言。
2. **前端**：`KubernetesPage.test.tsx`（列表/检查结果/stale/无 secret 字段/i18n），`npm test`、`tsc --noEmit`、`npm run build`；测试登记 `weekAcceptance.test.ts` 第 13 周。
3. **静态与迁移**：`compileall`、`git diff --check`、`alembic upgrade head` + `alembic check`。
4. **真实集群 smoke（kind/WSL）**：登记 kind 集群 → 连通性检查通过 → 节点发现返回 kind 节点 → ensure namespace 成功且集群内 quota 对象存在；记录 Kubernetes 版本、namespace、ServiceAccount、RBAC 清单和证据路径（`temp_test/week13-local/`）。已认证 Playwright 覆盖"登记 → 检查 → 节点表"。

**失败封闭原则**：环境缺少 kind 集群时，第 4 层记为 `blocked`（含原因），Week 13 保持 `in_progress`；任何 failed/skipped/blocked/not_run 均不得折算为通过。

## 12. 决策记录（Task 0 的 Week 13 子集，2026-09-28 收口）

五项决策按仓库与环境证据收口；环境相关的具体值（kind 端口等）在实施计划 Task 13.6 smoke 时回填。Week 15 builder 路径与 Week 17 范围同属 Task 0，仍保持开放，不阻塞 Week 13。

| # | 决策项 | 决策 | 依据与残留条件 |
|---|---|---|---|
| 1 | 测试集群形态 | **WSL2 内新建 kind 集群**（如 `linkraft-w13`） | 2026-09-28 实测：WSL Docker Server 29.7.2 可用，kind/kubectl 未安装——安装属 Task 13.6 环境准备，不改变决策 |
| 2 | `kubernetes_endpoint_allowlist` 内容 | 开发/测试值 = `127.0.0.1`（kind 端口转发）+ 备用 WSL eth0 IP，smoke 时回填终值；**生产值由运维部署时配置，Week 13 不预设** | 由决策 1 推导；仓库 Windows↔WSL 走 mirrored localhost（HANDOVER 恢复清单）；allowlist 默认为空、fail-closed 的合同不变 |
| 3 | 凭据引用约定 | `env:LINKRAFT_<CLUSTER>_TOKEN`（SA token）+ `file:`（CA/证书），与 §5.1 一致 | 仓库既有 `secret_key_file`、`minio_access/secret_key_file`、`tensorboard_session_secret_file`、`inference_internal_secret_file`、`notification_master_key_file` 共 6 处 `*_file` 引用与 `.env.example` 的 `/run/secrets/*` 惯例同构 |
| 4 | 管理角色映射 | 管理写操作（登记/更新/删除/连通性检查/namespace ensure/资源组写）复用 `resource.create`/`resource.update`/`resource.delete`（即 owner + editor）；只读发现复用 `project.read`（全体成员角色）；**不新增 permission 字符串，不给平台 admin 新增项目旁路** | `PERMISSIONS` 为封闭 frozenset，`require()` 对未知串抛 `ValueError`——新增串即修改共享合同；`is_platform_admin` 现仅用于 dashboard 平台统计，项目资源无旁路（`resolve()` 只认 owner_id 与成员关系） |
| 5 | insecure http/TLS 豁免范围 | 默认全程 TLS 验证；kind 优先以 `file:` 引用 kind CA（kubeconfig `certificate-authority-data`）完成验证；`insecure_tls` 仅作为经 WSL IP 访问导致 SAN 不匹配时的兜底，且保持"集群标记 + `KUBERNETES_ALLOW_INSECURE_ENDPOINTS`"双开关 + 审计 | 由决策 1/2 推导；§5.2/§5.3 双开关合同不变 |

决策 4 补充：连通性检查会改写 `last_check_*`，按 `resource.update` 归类（owner + editor）；曾考虑放宽到 `execution.operate`（含 operator），Week 13 取更保守口径，Week 14 执行器接入时再评估。

## 13. 显式排除项

- 不提交 Job/Pod、Notebook、镜像构建、GPU 调度、多集群路由、配额/并发/成本执行（Week 14–16）。
- 不存储 kubeconfig/token/证书内容；不挂载宿主 Docker socket；不引入 privileged/hostPath 工作负载描述。
- 不做 Label Studio、Superset、RAG/LLM 网关；不新增行业化（点焊）字段或路由。
- 不以 mock 客户端或本文档宣称任何完成状态。

## 14. 方案结论

Week 13 用最小面积建立"项目 → 集群 → 命名空间"的可信映射：凭据零落库、端点 fail-closed、发现只读、失败可恢复且可见。它为 Week 14 的执行器提供集群身份与凭据引用合同，为 Week 15 的 GPU/Notebook 提供节点能力与命名空间底座，为 Week 16 的治理提供资源组与配额载体。Task 0 决策收口并通过 §11 全部门禁后，Week 13 才能转为 `completed`。
