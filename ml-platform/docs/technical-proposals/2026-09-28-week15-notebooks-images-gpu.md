# Week 15 Notebook、镜像与 GPU 技术方案

**日期：** 2026-09-28
**状态：** 评审稿。Week 15 为 `planned`，依赖 Week 13（集群/命名空间/节点发现）与 Week 14（统一执行器）；镜像在线构建路径受 Task 0 决策门约束（§4.3、§12）。
**范围：** Notebook 会话生命周期、镜像目录与登记、rootless 构建适配、GPU 资源类与配额校验
**不包含：** 多集群路由与存储治理（Week 16）、数据探索（Week 17）、JupyterHub 平台化部署、Docker-in-Docker / 宿主 socket 挂载

## 1. 目标与方案定位

在 Week 14 的统一执行器上叠加三类开发资源：**交互式会话**（Notebook）、**镜像资产**（不可变 digest 目录 + 获批后的构建）、**GPU 资源类**（请求到已验证容量的封闭映射）。所有会话与构建都是 Week 14 语义下的"作业"——复用幂等、租约、对账与审计，不新建执行机制。

## 2. 与既有合同的关系

| 既有合同 | Week 15 用法 |
|---|---|
| Week 14 执行器 | Notebook 会话的创建/停止以 Job 形态执行（`linkraft.io/role=notebook` 标签），生命周期由平台拥有 |
| Week 13 节点发现 | GPU 容量来源：`kubernetes_clusters.capabilities` 快照 + 实时 `list_nodes` 复核 |
| DurableOperation / 审计 / 权限 | 会话启停幂等；审计动作 `notebook.start/stop/delete`、`image.register/update` |
| 仓库代理先例（compose `tensorboard-gateway`） | 浏览器到集群内服务的转发先例；Notebook 访问路径复用其"凭据只在服务端"思想（§4.1） |

## 3. 核心领域模型

新增 `app/models/developer_resources.py`，迁移计划名 `20260924_64_developer_resources.py`（以实现日空闲号为准）。

### 3.1 NotebookSession（表 `notebook_sessions`）

| 字段 | 类型 | 说明 |
|---|---|---|
| id / project_id / user_id | PK / FK / FK | 会话归属项目与创建者；一人一项目可多会话，并发数受配额约束（Week 16 治理，本周按 Settings 上限） |
| cluster_id / namespace | FK / VARCHAR(63) | 目标（同 Week 14 约束） |
| operation_id | FK durable_operations, 唯一 | 启动幂等 |
| image_ref | VARCHAR(512) | digest 引用，必须命中镜像目录或批准前缀 |
| resource_json | JSON | cpu/mem/可选 GPU 类名 |
| status | VARCHAR(24) | `starting/running/stopping/stopped/failed/terminated` |
| access_path | VARCHAR(255) NULL | 会话代理路径令牌（非集群凭据） |
| idle_timeout_seconds | INT | 空闲回收阈值 |
| last_activity_at / started_at / terminated_at / error_code | — | 空闲扫描与终态回填 |

### 3.2 ContainerImage（表 `container_images`）与 ImageBuild（表 `image_builds`）

- ContainerImage：`registry/repository`、`digest`（不可变，唯一键）、`visibility(project/platform)`、`scan_status(unknown/pending/passed/failed)`、`scan_report_ref`（Trivy 报告制品引用）、`source(manual_registry/build)`、登记人与时间。**digest 一经登记不可修改**，换 digest 即新记录。
- ImageBuild：`source_artifact_id`、`builder_image`、`operation_id`、`status`、`log_ref`、`output_image_id`。**是否可执行受 §4.3 决策门约束**；未获批时表结构与校验先落（合同冻结），构建端点返回 501 `IMAGE_BUILD_NOT_APPROVED`。

### 3.3 GpuResourceClass（表 `gpu_resource_classes`）

| 字段 | 说明 |
|---|---|
| name / cluster_id | 项目内唯一（`cluster_id, name`） |
| resource_name | 固定 `nvidia.com/gpu` 起步，预留 vendor 扩展 |
| memory_gb / vendor | 描述性 |
| node_selector_json / tolerations_json | 调度约束（仅允许平台受控值，不接受任意键） |
| max_per_session | 单会话上限 |
| allocatable_snapshot_json / snapshotted_at | 来自节点发现，供请求校验与 stale 判定 |

## 4. 关键技术决策

### 4.1 Notebook 访问路径：平台内同源代理（已核实先例后决策）

**决策：经后端 FastAPI 反向代理到 K8s API service proxy**（`/api/v1/namespaces/{ns}/services/{svc}:{port}/proxy`），浏览器只访问 `/api/notebooks/{id}/access?token=...`：

- 集群凭据/SA token 只在服务端，浏览器永不接触（比 NodePort/Ingress 暴露面小）。
- 访问令牌为 HMAC 签名短时令牌（≤15 分钟，绑定 session_id + user_id），复用平台 secret，无状态可撤销（删会话即失效）。
- 代理有请求体大小、超时与 WebSocket 升级支持（Jupyter 需要 WS）；代理路径拒绝携带 `X-` 平台头注入。
- 依据：compose 中已有 `tensorboard-gateway` 独立网关先例（浏览器访问集群内 TensorBoard，凭据不出服务端）；选择平台内 API 代理而非新建网关服务，直接复用 `get_current_user` 与项目隔离。

### 4.2 GPU 请求封闭映射

会话/作业请求 GPU 时：必须解析到 `active` 的 GpuResourceClass → 实时 `list_nodes` 复核 `allocatable`（Week 13 快照过期则刷新）→ 配额/上限校验 → 注入 `resource_json` 与 class 的 selector/tolerations。任一环节缺失（无类、无设备插件标签、容量为 0、配额不足）→ 显式错误 `GPU_CLASS_UNAVAILABLE` / `GPU_CAPACITY_EXCEEDED`。**没有 GPU 环境 = smoke 记 `skipped`（带原因），不折算 passed。**

### 4.3 镜像构建路径：预构建目录为基线，Kaniko 为获批增量（Task 0 决策门）

- **基线（本周默认交付）**：预构建镜像目录——外部（CI/运维）构建并推送后，在平台登记 digest + Trivy 扫描引用；扫描状态 `failed` 的镜像禁止被会话/作业引用。
- **增量（获批后才实现）**：rootless Kaniko 构建任务（经 Week 14 执行器提交，builder 镜像 + source artifact + 专用低权限 SA + 输出 registry 凭据走 `env:` 引用）。**任何情况下不引入 DinD、不挂载宿主 docker socket。**
- 推荐基线的理由：Task 0 镜像仓库决策仍开放，构建闭环依赖 registry 凭据与存储；目录登记不依赖它们即可交付资产化价值，且与本机无 Kaniko 验收环境的现状一致（DEVELOPMENT_PLAN §6 风险项）。

## 5. 接口边界

前缀 `/api/notebooks`、`/api/images`，认证同前；权限：会话启停/镜像登记 = `execution.operate` + `resource.create`（登记为资源创建），查看 = `project.read`：

| 方法 路径 | 语义 | 主要错误 |
|---|---|---|
| POST `/notebooks` | 启动会话（Idempotency-Key；image 必须命中目录/批准前缀；GPU 走 §4.2） | 422 镜像/资源/GPU；409 集群非 active；429 并发上限 |
| GET `/notebooks`、GET `/notebooks/{id}` | 列表/详情（含 idle 剩余时间） | 404 隐藏式 |
| POST `/notebooks/{id}/access` | 换取短时代理 URL（≤15min） | 409 非 running |
| POST `/notebooks/{id}/stop` | 停止（幂等；终态一次） | 409 已终态 |
| DELETE `/notebooks/{id}` | 终止并回收（幂等） | — |
| GET/POST/PATCH `/images` | 目录 CRUD（digest 不可变；`scan_status=failed` 拒绝被引用） | 409 digest 冲突；422 校验 |
| POST `/images/builds` | 构建入口（决策门：未获批 501 `IMAGE_BUILD_NOT_APPROVED`） | — |

空闲回收：scheduler beat 每 5 分钟扫描 `last_activity_at` 超时的 `running` 会话 → 自动 stop（审计 `notebook.idle_timeout`）。

## 6. 前端交互方案

- `NotebookPage`（`/notebooks`）：会话列表（状态、镜像 digest、资源、idle 倒计时）、启动表单（镜像选择限目录内、GPU 类下拉含容量提示）、打开/停止按钮（服务端状态驱动）、代理新窗口打开。
- `ImageCatalogPage`（`/images`）：目录表（digest 短形式、扫描徽标、可见性）、登记表单、构建入口仅在决策获批后渲染。
- i18n 补 `NOTEBOOK_*`/`IMAGE_*`/`GPU_*` 错误码；测试登记 `weekAcceptance.test.ts` 第 15 周。

## 7. 测试与验收标准

1. `test_notebook_api.py`：项目/用户隔离、启停幂等、idle 扫描、代理令牌过期/会话删除后失效、响应不含集群 token。
2. `test_image_catalog_api.py`：digest 不可变与冲突、scan_status 联动引用拒绝、可见性隔离。
3. `test_image_build_security.py`：未获批 501；获批路径（fake builder）断言无 socket/无特权/凭据走引用；构建日志脱敏。
4. `test_gpu_scheduling.py`：类解析、容量复核（快照过期刷新）、selector/tolerations 注入、无设备显式错误、配额上限。
5. kind smoke：无 GPU 环境 → GPU 用例记 `skipped`（原因：无 NVIDIA 节点）；Notebook 会话用预载镜像起真实容器 → 代理访问 200 → stop 回收；镜像登记 → 会话引用成功/扫描失败拒绝。
6. 已认证 Playwright：会话启动 → 打开 → 停止；镜像登记。
7. 清单：`week_manifest.py` 新增 `15:` 键。

## 8. 开放决策点（Task 0）

| 决策项 | 本方案默认 | 状态 |
|---|---|---|
| 构建路径 | 预构建目录基线；Kaniko 获批后增量 | **开放**（Task 0；未批前构建端点 501） |
| Notebook 代理形态 | 平台内 API 反代 | 已决策（§4.1，基于 tensorboard-gateway 先例） |
| GPU 类清单 | 默认空（所有 GPU 请求显式失败） | 开放（依赖真实 GPU 节点，未具备前保持 skipped 口径） |
| Notebook 基线镜像 | 目录登记一个 python+jupyter digest（kind 预载） | smoke 时定 |

## 9. 显式排除项

- 不做 JupyterHub 多用户平台化、不做跨集群会话（Week 16）、不做数据探索（Week 17）。
- 不引入 DinD/socket/特权 builder；不在无 GPU 环境伪造 GPU 通过；不以 mock 宣称构建闭环完成。

## 10. 方案结论

Week 15 把"开发资源"收敛到既有执行与权限合同上：会话是带角色的作业，镜像是不可变资产，GPU 是封闭映射的资源类。构建闭环显式受决策门约束——门未开时交付资产目录与全部合同，门开后只增不改。
