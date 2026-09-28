# Week 14 Kubernetes Job/Pod 执行闭环技术方案

**日期：** 2026-09-28
**状态：** 评审稿。Week 14 为 `planned`，依赖 Week 13 交付（集群登记、凭据引用、命名空间）；完成周度门禁前不得宣称完成。
**范围：** Kubernetes Job/Pod 提交、状态、日志、取消、超时、垃圾回收、重启恢复及作业运行页
**不包含：** Notebook 会话与镜像目录（Week 15）、多集群路由与配额治理（Week 16）、数据探索（Week 17）、长驻服务 Deployment

## 1. 目标与方案定位

把 Week 13 登记的集群变成"可提交、可观测、可取消、可恢复"的短时批量作业执行底座。Week 15 的 Notebook 会话与镜像构建、Week 16 的资源治理都叠加在本方案的统一执行路径上，因此本方案的核心义务是：**终态恰好一次、幂等可重放、失败不伪装**。

本周期只处理批量 Job（有终态），不处理长驻服务；只在单集群范围（Week 16 才引入路由）。

## 2. 与既有合同的关系

| 既有合同 | Week 14 用法 |
|---|---|
| `DurableOperation`（`app/models/operation.py`） | 每次提交对应一行：`resource_key` + `idempotency_key` 唯一约束实现重放幂等；`state/stage/progress` 承载执行进度；`lease_owner/lease_expires_at/heartbeat_at` 承载 worker 租约 |
| `operation_lifecycle`（`claim_operation` / `heartbeat_operation` / `complete_operation` / `fail_operation` / `recover_expired_operations`） | worker 领取、续租、终态写入与重启恢复的唯一入口，不另建状态机 |
| Celery（`app/tasks/celery_app.py` include 列表、scheduler beat） | 注册 `kubernetes_tasks.py`；周期 reconcile/回收挂 scheduler |
| Week 13 集群/命名空间/凭据引用 | 作业只提交到 `active` 集群的已登记命名空间；凭据仍只以 `env:`/`file:` 引用解析 |
| 审计 / `X-Request-ID` / 隐藏式 404 | 同 Week 13；新增 `k8s_job.submit/cancel/reconcile` 审计动作 |

2026-09-28 已核实：`DurableOperation` 含 `request_fingerprint`、`result_artifact_id`、`checksum` 字段，`recover_expired_operations` 可直接复用，无需扩展模型。

## 3. 总体架构

~~~text
POST /api/kubernetes/jobs (Idempotency-Key 必带)
        |
        v
kubernetes_jobs.py（API：认证、execution.operate 权限、审计）
        |
        v
kubernetes_executor.py（领域服务）
   1) 校验（镜像 digest + 批准前缀、env 白名单、资源边界、timeout）
   2) 先写 KubernetesJobRun + DurableOperation（queued）并提交数据库
   3) 派发 celery 任务
        |
        v
kubernetes_tasks.py（worker）
   submit：按 operation 行生成 manifest 并创建 K8s Job → submitted
   watch ：list/watch Job与Pod（resourceVersion 续点 + 有界轮询兜底）→ running/终态
   日志  ：按 cursor 读 pod log
        |
        v
scheduler beat：reconcile（非终态对账、超时标记、GC、孤儿检测）
~~~

**硬规则：数据库先行。** 集群资源创建之前，幂等行必须已提交；崩溃在"已落库未建 Job"或"已建 Job 未更新状态"之间时，由 reconcile 以 DB 为准收敛，绝不产生第二个 Job。

## 4. 核心领域模型

新增 `app/models/kubernetes_execution.py`，迁移接在 Week 13 之后（计划名 `20260924_63_kubernetes_executions.py`，以实现日空闲号为准）。

### KubernetesJobRun（表 `kubernetes_job_runs`）

| 字段 | 类型 | 说明 |
|---|---|---|
| id / project_id / cluster_id | PK / FK / FK | 属主与目标集群 |
| namespace | VARCHAR(63) | 目标命名空间名（须为该项目在 Week 13 登记的 namespace） |
| operation_id | FK durable_operations, 唯一 | 一作业一 operation |
| job_name | VARCHAR(128) | 集群内确定性名称（见 §5.1） |
| image_ref | VARCHAR(512) | 必须 `repo@sha256:...` digest 形式 |
| command_json / args_json / env_json | JSON | env 只存白名单键 |
| resource_json | JSON | cpu/memory 请求与限制（有上限校验） |
| input_bindings_json / output_bindings_json | JSON | Week 14 保留字段，非空值拒绝提交（见 §5.4） |
| status | VARCHAR(24) | 见 §6 状态机 |
| status_detail / error_code | — | 脱敏后的人类可读解释与机器错误码 |
| revision | INT | 同一 operation 的重试代次 |
| timeout_seconds | INT | 提交时确定，≤ 设置上限 |
| exit_code / submitted_at / started_at / finished_at | — | 终态回填 |

索引：`project_id`、`cluster_id`、`status`、`operation_id` 唯一。

## 5. 作业合同

### 5.1 命名与标签

- Job 名：`lr-{project_id 前 8 位}-job-{operation_id 前 8 位}-{revision}`，DNS-1123 子域安全，长度 ≤ 128。重试同 opid 递增 revision，名称确定可重放。
- 必带标签：`app.kubernetes.io/managed-by=linkraft`、`linkraft.io/project-id`、`linkraft.io/operation-id`、`linkraft.io/task-id`（可空）、`linkraft.io/revision`。reconcile 与 GC 一律按标签选择器对账。

### 5.2 镜像与环境批准

- `image_ref` 必须是 **digest 引用**（`@sha256:...`），且 registry/repository 前缀命中 Settings `kubernetes_job_approved_image_prefixes`（列表，默认空 = 拒绝一切）。**机制本周冻结，清单值属运维/Task 0 镜像仓库决策**；smoke 用 `kind load docker-image` 预载并登记 digest，allowlist 临时含对应本地前缀。
- env 键必须命中 `kubernetes_job_allowed_env_keys` 白名单；拒绝注入任何凭据形态的值（值不落库原文，仅存键与长度）。
- 资源请求：cpu/mem 上限由 Settings 限定（默认 4 core / 8Gi），超过即 422。

### 5.3 Manifest 安全基线

生成器只产生以下形状，其余一律 422 `KUBE_JOB_MANIFEST_FORBIDDEN`：禁 `privileged`、`hostPath`、`hostNetwork`、`hostPID`、`hostPort`、docker socket 挂载、serviceAccountName 指向非平台 SA、未批准镜像。`backoffLimit=0`（失败快速可见）、`activeDeadlineSeconds=timeout_seconds`、`ttlSecondsAfterFinished=3600`（集群侧 GC，数据库记录保留）。

### 5.4 制品绑定（范围决策）

`input_bindings_json`/`output_bindings_json` 为 Week 14 合同字段（对齐 Week 13–17 计划接口），但**本周只实现校验与显式拒绝**：非空提交返回 422 `KUBE_JOB_BINDINGS_UNSUPPORTED`。制品物化/收集需要 PVC 与 helper 流程，归入 Week 15/16 演进；Week 14 退出门禁（提交/取消/日志/恢复）不依赖它。

## 6. 状态机

~~~text
queued → submitted → running → succeeded | failed
                    ↘ cancelled（用户取消）
                    ↘ timed_out（activeDeadline 触发）
任意非终态 → orphaned（Job/集群消失或 reconcile 无法找到资源，且非用户取消）
~~~

规则：

1. 仅 queued/submitted/running 可流转；终态写入走 `complete_operation`/`fail_operation`，**迟到 watch 事件在服务层被状态守卫丢弃，不可重开终态**。
2. `cancelled` 记录 actor 与 reason；`timed_out` 由 activeDeadline + reconcile 双通道确认，两通道只允许一次终态写入（operation 行乐观守卫）。
3. `orphaned` 是可诊断终态：带 `error_code=KUBE_JOB_ORPHANED` 与最近已知 resourceVersion/UID。

## 7. 日志合同

`GET /api/kubernetes/jobs/{id}/logs?cursor=<byte offset>&limit_bytes=...`：

- 单次响应 ≤ 256KB（Settings 可调），响应带 `next_cursor` 与 `end_of_stream` 标记；前端按 cursor 增量拉取，不做 WebSocket。
- UTF-8 以替换字符解码（不因多字节截断报错）；对已注册的 env 值与常见 token 形态做脱敏后再返回。
- 只读 pod log；Pod 已消失时返回已有缓冲的 `end_of_stream`，不伪装成在线日志。

## 8. 取消、超时与回收

- 取消 = `DELETE Job（PropagationPolicy=Foreground）` + 立即标记 cancelled（乐观守卫）；集群侧确认由 reconcile 兜底，删除失败转 retryable 错误而非假成功。
- 超时：`activeDeadlineSeconds` 触发 Job failed（reason=DeadlineExceeded）→ reconcile 映射 `timed_out`。
- 回收：scheduler beat 周期任务回收超过 TTL 的已完成 Job（幂等）+ `cleanup_orphan_artifacts` 既有机制清理临时制品；DB 记录永久保留。

## 9. 接口边界

前缀 `/api/kubernetes`，权限统一 `execution.operate`（owner/editor/operator——Week 13 决策 4 的保守口径在本周放宽到执行域，与既有 AutoML/训练执行权限一致）：

| 方法 路径 | 语义 | 主要错误 |
|---|---|---|
| POST `/jobs` | 提交；`Idempotency-Key` 必带，重放返回原 operation 与作业（200 + `replayed=true`） | 422 镜像/env/资源/manifest；409 集群非 active；424 `KUBERNETES_SUBMIT_FAILED`（已落库未建集群资源时转 retryable，由 reconcile 收敛） |
| GET `/jobs`、GET `/jobs/{id}` | 列表/详情（带 operation stage/progress） | 404 隐藏式 |
| POST `/jobs/{id}/cancel` | 取消（actor/reason 入审计） | 409 已终态 |
| POST `/jobs/{id}/reconcile` | 手动对账（管理员排障用，幂等） | — |
| GET `/jobs/{id}/logs` | cursor 增量日志 | 404；410 资源已回收 |

## 10. Watch 与重启恢复

- watch celery 任务持有 operation 租约（`claim_operation` + 30s 心跳）；从上次 `resourceVersion` 续点，410 Gone 或断线时退避重连（1s→30s 上限），连续失败回落到 30s 有界轮询。
- worker/主机重启：启动时 `recover_expired_operations` 收回过期租约 + reconcile 按 `managed-by=linkraft` 标签对账非终态 operation；集群整体不可达时 converge 为 `connectivity_failed` 语义的 retryable 状态（不改写已提交终态）。

## 11. 配置与依赖

| 项 | 值 |
|---|---|
| `kubernetes` 客户端 | Week 13 已引入，复用适配器 |
| 新 Settings | `kubernetes_job_approved_image_prefixes=[]`、`kubernetes_job_allowed_env_keys=[]`、`kubernetes_job_max_cpu_cores=4`、`kubernetes_job_max_memory_gb=8`、`kubernetes_job_max_timeout_seconds=3600`、`kubernetes_job_log_chunk_bytes=262144`、`kubernetes_job_ttl_seconds_finished=3600` |
| 迁移 | `20260924_63_kubernetes_executions.py`（以实现日空闲号为准） |

## 12. 测试与验收标准

1. 单测（`test_kubernetes_executor.py`）：确定性命名、幂等重放、镜像/env/资源/manifest 校验、标签完整性。
2. API 测试（`test_kubernetes_job_api.py`）：权限（execution.operate）、项目隔离、Idempotency-Key 重放、审计、X-Request-ID。
3. 恢复测试（`test_kubernetes_recovery.py`）：取消竞态双写、超时双通道、迟到 Pod 事件不重开终态、worker 重启 reconcile、租约过期重领。
4. 日志测试（`test_kubernetes_logs.py`）：cursor 分页、UTF-8 截断、脱敏、end_of_stream。
5. kind/WSL smoke：`kind load docker-image` 预载短时镜像 → 提交（echo 任务）→ succeeded → 日志读取 → cancel 场景 → 重启 reconcile 场景；记录镜像 digest、namespace、SA、K8s 版本、证据路径。
6. 已认证 Playwright：提交 → 状态流转 → 日志查看 → 取消。
7. 清单登记：`week_manifest.py` 新增 `14:` 键；`weekAcceptance.test.ts` 新增第 14 周。

## 13. 显式排除项

- 不做长驻服务/Deployment、CronJob、跨集群调度（Week 16）、Notebook 会话（Week 15）。
- 不执行制品绑定（§5.4 显式拒绝）；不引入 DinD/socket；不以 mock 宣称真实集群行为。

## 14. 方案结论

Week 14 用"数据库先行 + 统一 executor + 租约对账"把 K8s 执行变成可恢复的普通长操作：幂等由 `DurableOperation` 唯一约束保证，终态由服务层守卫保证，可见性由状态机与 cursor 日志保证。Week 15/16 的会话、构建与治理全部走同一执行与对账路径。
