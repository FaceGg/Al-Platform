# 当前开发计划

> 更新时间：2026-09-30。本文档是当前状态台账；完整历史执行记录已保存到 [2026-09-24 归档快照](DEVELOPMENT_PLAN.history-2026-09-24.md)。最近开发重点是 Week 13–17，详细实施步骤见 [Week 13–17 云原生与数据探索开发计划](ml-platform/docs/superpowers/plans/2026-09-24-week13-17-development.md)。

## 1. 状态口径

- planned：已进入计划，尚未开始实现。
- in_progress：已有实现或验证工作，但仍有必需工作或证据未收口。
- pending_decision：产品、权限、成本或部署边界尚未确认，不能开始承诺范围内的实现。
- completed：实现、必要测试和当前版本所需验收均已完成；历史记录必须绑定可复核证据。
- failed、blocked、skipped、cancelled、not_run 不折算为 completed。
- 聚焦单测、真实运行、浏览器验收、远程 CI 和发布收据分开记录；历史 SHA 不能替代当前 SHA 证据。

## 2. 当前阶段总览

| 范围 | 状态 | 当前结论 | 下一步 |
|---|---|---|---|
| Week 1–12 | completed | 平台基础、生产化、权限通知和历史验收已归档 | 不作为当前开发入口 |
| 通用平台 Task 1–13 | 实现记录已收口，发布随 Task 14 统一门禁 | 保留通用 AutoML、数据版本、标注、回传、模型导出和门户合同；不因历史局部记录宣称整个平台发布完成 | 维护兼容性，继续使用当前有效合同 |
| 通用平台 Task 14 | completed | 主分支 SHA `3fc246980b32c463a9c120573a0b0058bed8d9e7` 的完整六项 CI、64 文件最终 manifest、19 项 receipt，以及同 SHA 的 CLU-02、AUTH-02、AUTO-02、REL-01 真实运行证据均已通过；容量门槛按用户确认支持 10,000 样本 | 归档 Task 14 收口记录；Week 13 仍须先完成 Task 0 决策和基础门禁 |
| Week 13 | completed | 本地与远端门禁全部收口（2026-09-29）：4 张云资源表 + 迁移 `20260928_62`（head，5 处 head 常量已同步）、凭据引用/allowlist/状态机合同、`/api/kubernetes` 端点、KubernetesPage；聚焦测试 37 passed、`run_suite --week 13` 3/3、alembic upgrade/check、前端 Vitest 368 passed/tsc/build、Week 12 安全模块直跑 159 passed；kind v0.34 + K8s v1.37.0 真实集群 smoke 12/12 PASS（证据 `ml-platform/backend/temp_test/week13-local/EVIDENCE.md`）；已认证 Playwright 流程 1 passed；`run_week13_17_acceptance.sh` OVERALL passed；远端 CI 收据 run 36504250668（Quality ubuntu + windows 全绿，绑定 SHA `ff82e0f`） | 无；Week 14 依赖本周期集群/命名空间合同 |
| Week 14 | completed | 本地实现、真实集群 smoke、浏览器验收与远端 CI 全部收口（2026-10-08）：4 个后端测试模块（executor 16 + logs 6 + recovery 11 + job_api 16 = 49 用例，另迁移 upgrade/downgrade/check 3 用例）全绿；`run_suite --week 14` 4/4、`--week 13` 回归 3/3、compileall OK；前端 JobRunsPage 6 用例 + 路由/导航/i18n/错误码（全量 Vitest 410 passed/19 skipped、tsc、build）；kind v1.37.0 真实集群作业 smoke **19/19 PASS**（echo→succeeded+日志、cancel 恰好一次终态+审计、超时→timed_out、无 watcher 恢复对账→succeeded、kubectl 删 Job→orphaned；证据 `ml-platform/backend/temp_test/week14-local/EVIDENCE.md`）；已认证 Playwright **1 passed**（提交→状态流转→日志 marker+end_of_stream→UI 取消→终态禁用，截图 3 张，`e2e/week14-jobruns.spec.ts`）；`run_week13_17_acceptance.sh week14` OVERALL passed（8 步 manifest 绑定 SHA）；**远端 CI 收据 run 37736316661（Quality ubuntu + windows 全绿，绑定 SHA `3329e0c`，Week 14 代码随 `9148965`/`edb4227` 入库）**。smoke 期间修复 6 项实现缺陷（真实客户端缺作业面、manualSelector、命名空间限定调用、1.27+ 无 job-name 标签、1.37 FailureTarget/SuccessCriteriaMet 条件映射、WSL 重启后集群重建）；浏览器验收发现 5177 端口需 `FRONTEND_ORIGIN_ALIASES` 放行 CORS（否则 403） | 无；Week 15 依赖本周统一执行器，且仍受 Task 0 开放项（镜像仓库、GPU 节点、rootless builder 路径）约束 |
| Week 15 | completed | 本地实现、真实集群 smoke、浏览器验收与远端 CI 全部收口（2026-10-09，代码随 `a42248d` 入库）：四模块 32 用例全绿（notebook 13 + image_catalog 5 + build_security 4 + gpu 10）；`run_suite --week 15/14/13` 全过、alembic upgrade/check（新 head `20261008_66`，5 处常量 + fixture 同步）、production 22 passed；前端 NotebookPage 4 + ImageCatalogPage 4 用例（全量 Vitest 421 passed/19 skipped、tsc、build）；kind v1.37.0 smoke **18/18 PASS**（镜像目录登记/digest 不可变 → 会话启动（真实 jupyter/base-notebook digest 预载）→ K8s service proxy 访问真实 Jupyter 200 → 篡改 token 401 → 构建门 501 → GPU 无节点记 skipped → stop 回收集群资源清零 → scan-failed 拒绝 → 审计 start/stop）+ 空闲回收实测（60s 阈值、审计 notebook.idle_timeout、资源清零）；已认证 Playwright **1 passed**（登记镜像 → 启动 → 代理打开真实 Jupyter → 停止，截图 4 张）；`run_week13_17_acceptance.sh week15` OVERALL passed。预构建目录基线执行：构建端点 501 `IMAGE_BUILD_NOT_APPROVED`（决策门未开），无 DinD/socket；GPU 类空表按 skipped 口径。smoke/浏览器期间修复 5 项缺陷（RealKubernetesClient 作业字段必填假设、V1ServiceSpec 参数名、Week14 RBAC 缺 services/services:proxy、notebook 启动表单缺 namespace 字段、代理端点改自包含 HMAC 令牌——浏览器导航无法带 JWT 头）；**远端 CI 收据 run 37911977130（Quality ubuntu + windows 全绿，绑定 SHA `3fc710c`，Week 15 代码随 `a42248d` 入库）** | 无；Week 16 依赖本周会话与镜像合同 |
| Week 16 | completed | 本地实现、双集群 smoke、浏览器验收与远端 CI 全部收口（2026-10-10，代码随 `95e9047`+`9a4c335`+`d701ffc` 入库）：四模块 28 用例全绿（scheduler 10 + governance 8 + storage 5 + observability 5）；`run_suite --week 16/15/14/13` 全过、alembic upgrade/check（新 head `20261010_67`，5 处常量 + fixture 同步）、production 22 passed；前端 ClusterGovernancePage 4 用例（全量 Vitest 427 passed/19 skipped、tsc、build）；**双 kind 集群 smoke 19/19 PASS**（第二个集群 linkraft-w16b @46618：无策略确定性选择、双候选带原因、停 B 后路由Away并给 `cluster_not_active`、健康 A 提交 succeeded + 预留 `terminal` 释放、配额收紧后 422 `QUOTA_EXCEEDED`、Summary API 采集 12 行（gpu utilization=unavailable 不伪造）、删策略后单集群退化保持；证据 `ml-platform/backend/temp_test/week16-local/EVIDENCE.md`）；已认证 Playwright **1 passed**（治理页表格 + 路由预演排除原因 + 配额拒绝呈现，截图 2 张）；`run_week13_17_acceptance.sh week16` OVERALL passed；**远端 CI 收据 run 绑定 SHA `d701ffc`（Quality ubuntu + windows 全绿，含 Week 16 代码 `95e9047`）**。CI Windows 曾两次失败：首次为两处与本改动无关的 flaky（重跑后消失），第二次为治理页预演测试的 projectId 竞态（`d701ffc`/`9a4c335` 修复）。预留防超卖并发竞态测试固化（8 线程争 4 cpu 恰好 4 成）；执行器/Notebook 提交前预留钩子 + 终态/孤儿/过期/手动四条幂等释放路径（单集群回归 W13–15 测试全过）；采集失败收敛 stale 不阻塞提交。smoke 期间修复 3 项缺陷（RealKubernetesClient 缺 node_summary——Summary API 经 API server proxy、Week14 RBAC 补 nodes/proxy、cluster B 的 SA 名不匹配致 system:anonymous 403） | 无；Week 17 依赖本周配额与路由合同 |
| Week 17 | planned | 数据探索与质量报告范围已获批（§4.2，2026-09-28）：DuckDB 只读查询 + 质量 profile + 报告 Artifact，不部署 Superset；上限行 1,000/10MB/30 秒/并发 2；SavedQuery 首期不纳入 | 按 2026-09-28 Week 17 实施计划自 Task 17.1 起实现 |
| Week 18–20 | deferred | RAG、LLM 网关、AIHub、全产品交付不在本轮范围 | 保持搁置 |
| 多模态标注集成（Label Studio） | deferred | 2026-09-28 决策评审后用户决定暂缓（D1）；方案归档备查，D2–D8 结论已记录（§4.3） | 用户明确重新立项前不得自行启动 |

## 3. 最近开发计划：Week 13–17

| 周次 | 交付目标 | 主要产物 | 退出门禁 |
|---|---|---|---|
| Week 13 | Kubernetes 基础接入 | 集群登记、credential_ref、命名空间/资源组、节点能力、连通性 API 和管理页 | real/kind 集群只读发现；跨项目访问、失效凭据、超时和审计回归通过 |
| Week 14 | Kubernetes 执行闭环 | Job/Pod manifest、统一 executor、watch/poll、日志 cursor、取消/超时/回收、恢复和任务页 | 幂等、终态不可逆、watch 重连、日志脱敏、重启恢复和真实集群 smoke 通过 |
| Week 15 | Notebook、镜像和 GPU | Notebook 会话、不可变镜像 digest、rootless 构建适配、GPU 资源类和配额 | 不使用 Docker socket；GPU 无设备时明确 skipped；会话/构建权限和密钥回归通过 |
| Week 16 | 多集群与资源治理 | 路由策略、存储绑定、资源预留/释放、配额、并发、成本、集群/节点/Pod/GPU 监控 | 不健康集群排除、配额并发不超卖、存储不能越界、单集群兼容和多集群 smoke 通过 |
| Week 17 | 决策后数据探索 | 推荐 DuckDB 只读查询、质量 profile、报告 Artifact、查询和报告页；Superset 为独立选项 | 只有范围获批才实现；查询只读、限时/限量、项目隔离、审计和报告下载回归通过 |

执行顺序固定为 Week 13 → Week 14 → Week 15 → Week 16 → Week 17。Week 17 的 Label Studio、多模态同步、iframe 和训练数据回流不在当前承诺范围。

详细文件边界、接口、测试步骤、环境和证据要求见 [Week 13–17 计划](ml-platform/docs/superpowers/plans/2026-09-24-week13-17-development.md)。各周细化设计与执行入口：Week 13 [技术方案](ml-platform/docs/technical-proposals/2026-09-28-week13-kubernetes-foundation.md) / [实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week13-kubernetes-foundation.md)；Week 14 [技术方案](ml-platform/docs/technical-proposals/2026-09-28-week14-kubernetes-executor.md) / [实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week14-kubernetes-executor.md)；Week 15 [技术方案](ml-platform/docs/technical-proposals/2026-09-28-week15-notebooks-images-gpu.md) / [实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week15-notebooks-images-gpu.md)；Week 16 [技术方案](ml-platform/docs/technical-proposals/2026-09-28-week16-multi-cluster-governance.md) / [实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week16-multi-cluster-governance.md)；Week 17 [技术方案](ml-platform/docs/technical-proposals/2026-09-28-week17-data-exploration-quality.md) / [实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week17-data-exploration-quality.md)。全部为评审稿，不改变各周 planned 状态；Week 17 的决策记录见 §4.2。

## 4. 进入条件与横向合同

1. 先完成 Task 0：冻结现有通用平台合同；确认 Kubernetes 测试集群、镜像仓库、凭据引用、GPU 节点可用性和 Week 15 builder 路径。
2. 复用现有项目权限、审计、ArtifactService、DatasetVersion、DurableOperation、Redis/Celery、通知和前端 API client；不另建平行权限或任务状态机。
3. 集群凭据只保存 Secret/credential 引用；工作负载默认禁止 privileged、hostPath、hostNetwork、hostPID、Docker socket 和未批准镜像。
4. 所有写操作提供 X-Request-ID、Idempotency-Key、操作 ID、脱敏错误和可恢复状态；迟到事件不得覆盖终态。
5. ORM 变更必须有 Alembic 迁移、SQLite/PostgreSQL 兼容验证、迁移 head 检查和旧数据保留断言。
6. 每个新后端测试模块登记到唯一周次；每个新前端测试文件登记到唯一周次；不把历史点焊测试重新纳入通用 active suite。

### 4.1 Task 0 Week 13 子集决策记录（2026-09-28）

Week 13 技术方案 §12 的五项决策按仓库与环境证据收口（细则与依据见该节）：

1. 测试集群：WSL2 内新建 kind 集群；WSL Docker Server 29.7.2 已可用，kind/kubectl 随 Task 13.6 环境准备安装。
2. 开发/测试 `kubernetes_endpoint_allowlist`：`127.0.0.1`（kind 端口转发）+ 备用 WSL IP，smoke 时回填终值；生产值由运维部署时配置。allowlist 默认为空、fail-closed 的合同不变。
3. 凭据引用：`env:LINKRAFT_*_TOKEN` + `file:` CA/证书，与既有 `*_file` 密钥引用惯例同构；凭据材料不落库、不进日志。
4. 权限映射：管理写操作复用 `resource.create/update/delete`（owner + editor），只读发现复用 `project.read`（全体成员角色）；不新增 permission 字符串，不给平台 admin 新增项目旁路。
5. TLS：默认全程验证，kind 以 `file:` 引用 kind CA；`insecure_tls` 仅为 WSL IP 访问导致 SAN 不匹配的兜底，保持集群标记 + 设置双开关并审计。

Task 0 其余项（镜像仓库、GPU 节点可用性、Week 15 builder 路径）仍开放；不阻塞 Week 13 实现，但阻塞 Week 15。Week 17 范围决策见 §4.2。

### 4.2 Week 17 范围决策记录（2026-09-28）

按 Week 17 技术方案 §8 的七个决策项逐项收口；第 1/3/4/5 项由用户于 2026-09-28 确认，第 2/6/7 项按仓库证据收口（依据见该节）：

1. 功能范围：批准 DuckDB 只读查询 + 质量 profile + 报告 Artifact；不部署 Superset（若未来需要，另立集成计划）。
2. 数据访问角色：查询 `execution.operate`（owner/editor/operator）、报告生成 `resource.create`、查看/下载 `project.read`（viewer 只读）；不新增 permission 字符串。
3. 资源上限：行 1,000 / 结果 10MB / 30 秒 / 并发 2（Settings 可配）。
4. 审计与保留：查询审计保留 90 天（新增可配设置，仿 `inference_log_retention_days` 惯例）；语句原文不入审计。
5. SavedQuery：首期不纳入，二期再议。
6. 结构化审核扩展：维持现状，既有标注指派/回传/验收为基线，不新增重复 API。
7. 成本预算：API 进程内执行，零新增基础设施；如需作业化（依赖 Week 14）另行批准。

结论：Week 17 决策门全部通过，状态由 `pending_decision` 转为 `planned`，实现按 [Week 17 实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week17-data-exploration-quality.md) 自 Task 17.1 起；完成全部周度门禁前不得宣称 completed。

### 4.3 多模态标注集成（Label Studio）决策记录（2026-09-28）

按 Label Studio 集成技术方案 §10 的 D1–D8 决策清单收口，结论为**暂缓**：

1. D1：用户决定**暂缓，不立项**——多模态标注本轮不启动。
2. D2–D8 结论已记录（D2 深度集成、D3 先 compose 落地、D4 表格不迁移、D5 provisioning+网关、D6 LS 完成不自动回传、D7 StorageBinding 优先、D8 运维完整接受；依据见技术方案 §10），**条件生效**：未来重新立项时按既定结论直接进入实施，除非届时条件变化。
3. 轨道状态由 `pending_decision` 转为 `deferred`（用户暂时搁置，不得自行启动）；技术方案与实施计划归档备查，表格标注自研门户与 Week 13–17 计划不受影响。

## 5. 周度验收门禁

### Week 13–16

- 聚焦后端单测/API/迁移/compileall 和前端 Vitest/TypeScript/build。
- Linux/WSL kind 或等价真实集群 smoke，记录 Kubernetes 版本、namespace、ServiceAccount、镜像 digest、资源 profile 和证据路径。
- 已认证 Playwright：集群登记、Job 提交/取消/日志、Notebook 生命周期和资源路由说明。
- 任何 failed、skipped、blocked、not_run 或旧 SHA 收据都保持对应周次 in_progress。

### Week 17

- 先记录产品批准范围、数据权限、查询隔离、审计保留、结果大小/时间限制和成本预算。
- 未获批时只完成决策文档，状态保持 pending_decision。
- 获批后再运行只读查询、质量报告、迁移、API、前端和浏览器门禁；报告 Artifact 必须绑定 dataset_version、schema_hash、参数和当前 SHA。

## 6. 当前风险和不纳入范围

- 当前主机没有可直接复用的 Kubernetes、GPU、JupyterHub 或镜像仓库验收环境；环境准备与代码测试分开记录，不能用 mock 客户端替代真实集群证据。
- Task 14 的通用平台发布收据尚未成为 Week 13–17 的完成证明；两条计划分别维护状态。
- Week 15 在线构建若无法提供 rootless Kaniko 或等价安全 builder，只交付不可变预构建镜像目录，不引入 Docker-in-Docker。
- Week 17 不实现 Label Studio、Superset 部署或任意 SQL 代理，除非另有批准的专项计划。
- 不在本轮新增 RAG、LLM 网关、AIHub、动态工作流、画布与代码互转或行业化作业模板。

## 6.1 通用平台 Task 14 本次收口记录（2026-09-24）

本次在隔离工作树、当前 SHA `fe723a48e6794d9c58aa264a4d8e875dc854af0d` 上完成了本地验收收口，但没有把远端发布门禁误记为完成：

- 后端完整测试：`1995 passed, 110 skipped, 329 warnings, 759 subtests passed`；数据库迁移 `upgrade head` 和 `alembic check` 通过。
- 前端门禁：主前端 `356 passed, 19 skipped`，构建通过；标注前端 `113 passed`，构建通过；标注后端门户测试 `30 passed`。
- Task 14 合同测试：接受清单/套件清单 `11 passed`；数据库、导出、离线推理、安全、异步操作合同 `49 passed`；Week 12 安全门禁直接运行 `160 tests passed`。完整 `run_suite.py` 在 Week 12 安全模块超过单模块 300 秒阈值而退出，直接模块运行已通过；该超时记录为门禁限制，不折算为套件全绿。
- WSL/Docker 真实运行：Compose 配置通过；使用当前 SHA 的安全镜像覆盖启动核心服务，`/api/ready` 返回 200 且数据库、Redis、Celery、存储、MLflow、TensorBoard、推理运行时和通知项均 ready。性能、备份/恢复、迁移升级、运行时镜像、浏览器验收、通用平台 19 项收据均已生成。
- 证据清单：`ml-platform/temp_test/week11-12-local/manifest.json` 为 `status=passed`，绑定当前 SHA，共 63 个文件；`generic-platform-acceptance/acceptance-manifest.json` 为 19 项收据且全部绑定当前 SHA。安全汇总包含容器镜像、Trivy、前端依赖、Python 依赖、Gitleaks、Bandit 和 Web 18 项检查，均为 passed。
- WSL 空间处理：已删除此前项目镜像并清理 Docker builder cache；清理后 WSL 根盘曾回收至约 26 GB 可用空间（45% 使用率），后续构建和运行期间保持约 18 GB 可用（64% 使用率）。已执行 `wsl --manage Ubuntu --set-sparse true --allow-unsafe`，并由 `fsutil sparse queryflag` 确认 `ext4.vhdx` 为 sparse；逻辑文件大小仍为 `49,302,994,944` 字节，离线 `diskpart compact vdisk` 在当前权限环境中被取消，因此物理空间缩减未验证。最终口径为“旧镜像/cache 清理完成、VHDX 稀疏化完成、物理压缩未验证”。
- 发布状态：远端当前 SHA 的完整 CI/发布收据尚未运行；已有远端记录中，运行 `35870469911` 仅覆盖质量门禁，旧运行 `35855270973` 绑定的是历史 SHA。Task 14 继续保持 `in_progress`，直到当前 SHA 的远端全门禁和发布判断完成；Week 13–17 计划状态不因本地 Task 14 收口改变。

## 6.2 通用平台 Task 14 最终 SHA 门禁复核（2026-09-25）

本节追加记录本轮最终代码变更、远程门禁和语义审计；不改写 6.1 的历史结论。

- 最终代码变更：PR [#25](https://github.com/FaceGg/Al-Platform/pull/25) 将 CI 与 Compose 中不可访问的 `quay.io/minio/minio:latest` 替换为可拉取且固定 digest 的 Chainguard MinIO/MinIO Client 镜像，并同步健康检查、初始化命令、验收脚本和合同测试；合并后的代码 SHA 为 `b185ead4f93068cf457a10fa5079d8be138ab88f`。
- 本地门禁：当前修复分支 `git diff --check` 通过；`alembic upgrade head` 和 `alembic check` 通过（无新升级操作）；后端全量 **1998 passed、110 skipped、759 subtests passed**；主平台前端 **64 files / 359 passed、19 skipped**，TypeScript 与生产构建通过；标注员前端 **15 files / 115 passed**，TypeScript 与生产构建通过；标注员后端门户 **30 passed**。
- 远程 full CI：首轮 `36101302944` 因 Quay MinIO 401 失败；修复后的首次 `36107534697` 在 warm-inference 延迟门槛上失败；同一代码 SHA 重跑的最终 [Run 36112327185](https://github.com/FaceGg/Al-Platform/actions/runs/36112327185) 绑定 `b185ead4f93068cf457a10fa5079d8be138ab88f`，Production integration、Production experiment integration、Quality Ubuntu、Quality Windows、Chromium acceptance、Week 11–12 verification 六个作业全部 `success`，无 `skipped`。
- 远程证据产物：已下载 `week11-12-verification-evidence`。`final-evidence-manifest.json` 为 `status=passed`、`commit=b185ead4f93068cf457a10fa5079d8be138ab88f`、`migration_head=20260921_60`，共 64 个文件，逐文件 SHA-256 和 size 校验无错误；`acceptance-manifest.json` 包含完整 19 个 ID，全部 `status=passed`、全部绑定该 SHA，证据源哈希与最终 manifest 一致。远程产物目录为 `temp_test/remote-full-36112327185/`。
- 四项语义复核仍未通过：
  - **CLU-02：未完成。** Receipt 只引用 `test_annotation_task_state.py` 和 `test_annotation_task_state_api.py`；源文件确实断言了 `all_rows`、评估样本数/hash 和边界分页，但实际夹具仍是 1–6 行（另有 501 行有界批处理回归），没有 10,000 样本容量运行、该规模下的全量赋簇证明或浏览器分页不加载全量的真实证据。
  - **AUTH-02：未完成。** Receipt 只引用标注员门户 `test_portal_api.py`，覆盖路由、会话、Cookie 和代理转发；没有主平台与门户双服务的真实 CORS/CSRF/限流/密码哈希/服务 JWT 或 mTLS 运行证据。主平台 `test_security_contract.py` 未进入该 receipt 的 evidence paths。
  - **AUTO-02：未完成。** Receipt 只引用被 mock API 的 `automl-multioutput.spec.ts`，只验证浏览器提交配置；没有真实 worker 产出完整候选、用户手动注册和重复注册返回同一版本的浏览器/服务联调证据。`test_model_registration_contract.py` 的单测不能替代该运行态证据。
  - **REL-01：未完成。** Receipt 只引用异步合同和安全单测；没有真实 broker/worker 进程的租约过期重领、重启恢复、幂等副作用和临时制品 TTL 清理（保留已提交制品）演练。Week 11 的备份/恢复产物不等价于该 worker 恢复证据。
- Task 14 决定：**保持 `in_progress`，不关闭、不宣称发布就绪**。下一步必须补齐上述四项真实运行证据，在补齐后的新当前 SHA 重新生成 receipt 和 manifest，并再次执行完整远程门禁；Week 13–17 计划状态不因本轮 Task 14 复核改变。

## 6.3 主分支 SHA `99f18abb` 重跑复核（2026-09-25）

- PR [#26](https://github.com/FaceGg/Al-Platform/pull/26) 只合并了计划台账和证据边界文档，没有改变功能代码；主分支 SHA `99f18abb81b10024d8c7960ce4275d19150baac3` 的完整 [Run 36127334563](https://github.com/FaceGg/Al-Platform/actions/runs/36127334563) 首次只在 `warm-inference` p95 轻微越过 200 ms 门槛，保持门槛不变重跑后六个作业全部 `success`。
- 成功重跑的 `week11-12-verification-evidence` artifact 已下载并核对：`final-evidence-manifest.json` 为 `status=passed`、`commit=99f18abb81b10024d8c7960ce4275d19150baac3`、迁移 head 为 `20260921_60`，64 个文件的存在性、size 和 SHA-256 均匹配；`acceptance-manifest.json` 与 19 份 receipt 的 ID、状态、当前 SHA 和证据哈希完全一致。成功 artifact 为 `10862988788`，本地核对目录为 `temp_test/remote-main-36127334563-rerun/evidence-id10862988788/`。
- 该重跑只补足当前 SHA 的远程门禁与收据链，不改变 6.2 的四项语义结论；Task 14 仍为 **`in_progress`**，不关闭、不宣称发布就绪。

## 6.4 CLU-02 容量范围调整（2026-09-25）

- 用户将当前 Task 14/CLU-02 的必需容量从 1,000,000 样本调整为 10,000 样本；当前验收矩阵和后续计划以 10,000 样本为准。
- 历史归档和原始方案修订前范围记录中的“百万样本”文字保留为历史记录，不代表当前必须实现的发布门槛。
- 本次只调整范围和台账，没有启动真实容量运行或补齐其他真实运行证据；Task 14 继续保持 `in_progress`，待 10,000 样本容量与分页证据实际生成后再单独评估 CLU-02。

## 6.5 四项真实运行证据补齐（2026-09-25）

本节是 6.4 范围调整后的追加结果；6.4 保留当时尚未运行的历史判断，不回写历史检查点。全部结果绑定当前完整 SHA `6d47e49e64d3001e2f2cdcd176c2deeae6d86d14`，原始运行输出和四份 supplemental receipt 位于 `temp_test/task14-real-6d47e49/`（该目录按约定被忽略，不替代最终 19 项发布收据目录）。

- **CLU-02：真实运行通过。** 当前 SHA 标签运行栈中的真实 Celery worker 创建 10,000 行数据，preview/operation 完成，`evaluation_mode=all_rows`、`evaluation_sample_count=10000`、`total_sample_count=10000`，两簇各 5,000 行；Playwright 通过 Vite 真实 API 以 50 行 limit 和 cursor 连续读取，响应总量为 10,000 且没有 10,000 项响应。原始结果：`clu02-runtime.json`、`clu02-browser.json`。
- **AUTH-02：真实双服务安全链路通过。** 主平台 HTTP 实证覆盖未知/允许 CORS、CSRF 缺失与有效双提交、登录限流（第 19 次返回 `RATE_LIMITED`）、PBKDF2 密码哈希和服务 JWT；独立 annotator 容器实证覆盖未登录 401、注册、管理员激活、门户登录、session/me 和网关生成服务 JWT 调用 backend 内部通知 API 200。原始结果：`auth-runtime-final.json`、`auth-gateway-runtime-final.json`。
- **AUTO-02：真实端到端通过。** 新鲜 API run 任务 `7530ff41-df26-4502-880d-2eb2c18ee0da` 由 worker `celery@a18098088c46` 完成，候选为 `random_forest`；手动注册第一次 201、相同 `Idempotency-Key` 重放 200 且返回同一 `model_version_id`，Playwright 页面渲染完成状态、模型结果和注册操作。早先探索运行中的一次派发竞态未纳入本次 receipt；最终 receipt 使用无需人工重排、从 queued 直接 completed 的重跑。
- **REL-01：真实恢复演练通过。** 隔离 harness 使用真实 Redis broker 和 worker，注入 worker 进程终止并推进租约过期，验证同一 operation 恢复、重复投递无重复结果；`result_count=5000`，中断 attempt 1、恢复 attempt 3。当前手工 harness 将执行 gate 显式置为 `preview_ready`，原因是现行 manual task 合同在 preview 完成后会转入 `awaiting_annotation`；该适配已记录在 receipt，不隐藏。
- **运行 provenance 与发布边界：** backend/worker 等当前 SHA 镜像由现有镜像 `docker commit` 快照加 revision label 运行，backend app/requirements 与基线镜像的差异核对为空；Dockerfile 重新构建在 Wolfi `apk add` 下载步骤受网络阻塞。因此四项 supplemental receipt 证明真实运行行为，但尚未证明 Dockerfile 当前 SHA 重建成功。
- **当前门禁结论：** 四项 supplemental receipt 均通过 `generic_acceptance_evidence._validate_receipt` 的 SHA、路径和哈希校验；尚未把它们并入完整 19 项最终 manifest，也未在该 SHA 重新触发远程 full CI。Task 14 继续为 `in_progress`，不关闭、不宣称发布就绪。

## 6.6 当前收口复核与最终提交门禁（2026-09-26）

本节记录本轮实际执行顺序。最终 supplemental 目录使用 `temp_test/task14-real-<commit_sha>/` 命名，四份 receipt 的 `commit_sha`、证据路径和 SHA-256 哈希以该目录中的 JSON 为准；旧章节中的 SHA 和目录保留为历史检查点。

- **真实运行证据：** CLU-02 真实 worker 完成 10,000 行聚类，`all_rows` 评估和 50 行 cursor 分页通过；AUTH-02 真实主平台与独立 annotator 网关覆盖 CORS、CSRF、限流、PBKDF2、服务 JWT、注册/激活/会话链路；AUTO-02 真实 worker 完成候选、手动注册第一次 201、同键重放 200 且返回同一版本，并以 Playwright 验证完成页；REL-01 在隔离 Redis DB 上终止首个 worker、推进租约过期、同一 operation 恢复 5,000 条结果，重复投递无重复副作用。探索性派发竞态运行不纳入通过证据。
- **迁移与后端：** WSL Compose 数据库容器 `alembic check` 返回 `No new upgrade operations detected`。当前迁移目录实际 head 为 `20260926_61`，同步更新 evidence/upgrade fixture、升级脚本和相关测试中的旧 `20260921_60` 账目；旧历史文档不回写。首次后端全量运行在 `2004 passed、110 skipped、3 failed` 结束，3 个失败均为旧 head 常量；同步后针对性 3 项测试通过，完整复跑为 **2007 passed、110 skipped、329 warnings、759 subtests passed**（15:09）。
- **前端：** 主平台 Vitest 全量 **64 files、361 passed、19 skipped**，TypeScript 与生产构建通过；标注员门户 Vitest **15 files、118 passed**，TypeScript 与生产构建通过。浏览器运行证据与单元套件分开记录。
- **运行环境：** WSL Ubuntu Docker 是本轮唯一真实 Compose 环境；旧项目镜像和 builder cache 已按用户授权清理，通用旧栈容器已停止以释放资源，Task 14 证据栈保持运行。worker/scheduler 的 Compose HTTP healthcheck 对 Celery-only 子镜像显示 `unhealthy`，但 worker 日志和四项真实运行结果均通过；该状态作为 healthcheck 设计边界披露，不改写为服务 HTTP 健康。
- **发布边界：** 本地 `git diff --check`、四项 supplemental receipt 校验、19 项 receipt 汇总、最终 evidence manifest 和远程 full CI 必须全部绑定同一个最终干净 SHA。未完成远程 full CI、下载并核对 19 项 receipt/manifest 前，Task 14 保持 `in_progress`，不合并或关闭。

## 6.7 备份恢复源库增长竞态修复（2026-09-26）

第二轮当前 SHA `a1b658308465cf9f6f07718f655133334d8ea172` 的远程 full CI 中，性能摘要本身为 `passed`，但 Week 11–12 收据将备份时刻的源库快照（`inference_request_logs=5799`）与恢复校验时仍在增长的源库（`6000`）比较，报告 `row_counts_equal=false`。该结果是验收证据竞态，不是 PostgreSQL restore 丢数据。

本轮修复在执行 `pg_dump` 前采集并规范化数据库快照，将其签名嵌入 PostgreSQL 备份 operation receipt；恢复校验优先使用签名快照，只实时读取恢复库并继续校验外键、对象哈希和 RPO/RTO；旧收据没有快照时保留实时源库回退。新增源库继续增长的回归测试，`tests/test_week11_12_tools.py` **111 passed、5 subtests passed**，后端全量为 **2008 passed、110 skipped、759 subtests passed、329 warnings**。

该修复提交后的 Docker 运行证据、四项 supplemental receipt、19 项最终 manifest 和远程 full CI 尚未完成；Task 14 继续保持 `in_progress`，所有旧 SHA 收据不作为新提交的通过证据。

## 6.8 通用平台 Task 14 最终收口（2026-09-26）

本节覆盖 6.6–6.7 之后的最终收口。证据以远程 artifact 的 `commit`、本地 supplemental receipt 的 `commit_sha` 和 Git 当前提交为准；历史章节保留原结论，不回写旧 SHA。

- **CLU-02：** WSL Ubuntu Docker 栈中的真实 Celery worker 完成 10,000 行聚类；`evaluation_mode=all_rows`、评估样本数和总样本数均为 10,000，两簇各 5,000 行。Playwright 以 50 行 limit 和 cursor 连续读取两页，API 总量为 10,000，单次响应没有返回全量样本。
- **AUTH-02：** 真实主平台与独立 annotator 网关通过未知/允许 CORS、CSRF 缺失与有效提交、登录限流、PBKDF2 密码哈希、服务 JWT、注册/激活/门户会话和网关到 backend 内部通知 API 的双服务链路。
- **AUTO-02：** HTTP API 创建任务后由真实 Celery worker 完成候选；浏览器显示已完成和 Random Forest 结果；手动注册第一次返回 201，相同 `Idempotency-Key` 重放返回 200 且复用同一 `model_version_id`。
- **REL-01：** 隔离 Redis DB 的真实 broker/worker 演练终止首个 worker、推进租约过期并恢复同一 operation，5,000 条结果完成；重复投递没有重复副作用，receipt 同时保留中断/恢复 attempt 和 worker 日志哈希。
- **本地门禁：** 后端全量 **2009 passed、110 skipped、759 subtests passed、328 warnings**；主前端 **64 files / 361 passed、19 skipped** 并成功构建；标注员前端 **15 files / 118 passed** 并成功构建；标注员后端 **30 passed**；容器内 Alembic 重复升级、head `20260926_61` 和 `alembic check` 通过；`git diff --check` 通过。
- **远程 full CI：** GitHub Actions Run [36212304250](https://github.com/FaceGg/Al-Platform/actions/runs/36212304250) 绑定代码 SHA `9943be7f2af6355f4a026e11d7f456a2e13f83de`，Production integration、Production experiment integration、Quality Ubuntu、Quality Windows、Chromium acceptance、Week 11–12 verification 六个作业全部 `success`，无 `skipped`；Week 11–12 的实时 acceptance、安全门禁、迁移/备份恢复和最终 manifest 均通过。
- **远程 artifact 核验：** `final-evidence-manifest.json` 绑定该 SHA，包含 64 个文件；每个文件的存在性、size 和 SHA-256 均复核通过。`generic-platform-acceptance/acceptance-manifest.json` 恰好包含 19 个必需 ID，全部 `passed`、绑定同一 SHA，receipt 与 manifest 内容一致，证据源哈希按 Git blob 原始内容复核通过。
- **运行边界：** WSL worker/scheduler 使用 Celery-only 镜像，而 Compose 继承的 HTTP healthcheck 显示 `unhealthy`；worker 日志、真实 broker 演练和四项运行结果通过，因此该状态记录为 healthcheck 设计边界，不改写为 HTTP 健康。当前容量门槛按用户确认支持 10,000 样本，不承诺百万样本。
- **台账结论（该节记录当时的 f0e 工作树）：** 四项 supplemental evidence 和 f0e SHA 的 19 项 receipt 已完成核验；该结论由下方主分支回归记录覆盖，不单独作为当前发布关闭依据。

## 6.9 通用平台 Task 14 当前主分支门禁回归（2026-09-26）

第 6.8 节的 f0e 工作树收口完成后，PR #28 合并产生主分支 SHA `d615cbd04b0477b8a39d2c60d1954f96eceda9be`。同一完整工作流 Run [36220608544](https://github.com/FaceGg/Al-Platform/actions/runs/36220608544) 已对失败作业连续重跑三次，三次均在 Week 11–12 verification 的 `warm-inference` 性能门禁失败；因此旧 SHA 的通过收据不能提升为当前主分支发布通过。

- **作业结果：** Production integration、Production experiment integration、Quality Ubuntu、Quality Windows、Chromium acceptance 五个作业均 `success`；失败仅为 Week 11–12 verification 的实时 warm-inference 门禁。
- **失败证据：** 第三次尝试的三轮 warm-inference p95 为 `190.24 ms`、`180.38 ms`、`206.73 ms`，阈值为 `200 ms`；p99 最高 `478.42 ms` 未超过 `500 ms`，2,000/2,000 请求返回 HTTP 200，error rate 为 0。前两次尝试同样因该 p95 门禁失败，不能按瞬时抖动改写为通过。
- **其余 Week 11 证据：** cold-model-load、core-read、enqueue、welding-e2e、安全文件、迁移 head `20260926_61` 和当前提交 provenance 均通过；失败使该运行没有生成当前 SHA 的 `final-evidence-manifest.json` 和 19 项 `generic-platform-acceptance/acceptance-manifest.json`。
- **处理决定：** 不放宽 200 ms 门槛，不以 WSL 本地低于阈值的结果替代 GitHub runner 的发布门禁。Task 14 保持 `in_progress`，不关闭；四项 supplemental evidence 仍作为已通过的独立运行证据保留，待修复或稳定性能门禁后在新的最终 SHA 重新生成并核对完整 manifest/19 项 receipt。

## 6.10 通用平台 Task 14 当前主分支最终关闭（2026-09-26）

在第 6.9 节记录的性能门禁回归后，台账修正合并产生主分支 SHA `8ffa1629c65f483300f636ac4c3575176534683d`。完整工作流 Run [36229313373](https://github.com/FaceGg/Al-Platform/actions/runs/36229313373) 的六个作业全部 `success`：Production integration、Production experiment integration、Quality Ubuntu、Quality Windows、Chromium acceptance 和 Week 11–12 verification。

- **性能与运行门禁：** Week 11–12 verification 的 `performance/summary.json` 为 `passed`，warm-inference 三轮均低于 200 ms p95 门槛，全部 2,000 请求返回 HTTP 200，error rate 为 0；summary provenance 与当前 SHA 一致。
- **最终证据：** 下载的 `final-evidence-manifest.json` 状态为 `passed`，绑定 `8ffa162`，包含 64 个文件；每个文件的存在性、size 和 SHA-256 均复核通过。`generic-platform-acceptance/acceptance-manifest.json` 恰好包含 19 个必需 ID，全部 `passed` 并绑定同一 SHA；receipt 内容、manifest 内容和 Git blob 哈希均复核通过。
- **数据库与安全：** environment 记录迁移 head `20260926_61 (head)`，安全扫描、备份/恢复、升级和浏览器 artifact 均随同一次完整运行通过。
- **关闭结论（当时的 `8ffa162`）：** 四项 supplemental evidence（CLU-02、AUTH-02、AUTO-02、REL-01）与该 SHA 的完整远程证据链均已通过；该结论由下方新的主分支回归记录覆盖。容量范围按用户确认支持 10,000 样本，不承诺百万样本。

## 6.11 通用平台 Task 14 主分支性能门禁再次回归（2026-09-26）

PR #30 的台账收口提交合并产生主分支 SHA `74be1ce9aee0c5b61c7ed09608215a9b1b118f39`。完整 Run [36233922421](https://github.com/FaceGg/Al-Platform/actions/runs/36233922421) 的五个前置作业均 `success`，Week 11–12 verification 对失败作业重跑一次后仍 `failure`。

- **作业范围：** Production integration、Production experiment integration、Quality Ubuntu、Quality Windows、Chromium acceptance 均通过；失败仅为 Week 11–12 verification 的 warm-inference 性能门禁。
- **两次失败数据：** 第一次尝试三轮 p95 为 `217.19 ms`、`197.40 ms`、`195.89 ms`；失败作业重跑后三轮 p95 为 `204.56 ms`、`187.52 ms`、`190.00 ms`。两次均只有第 1 轮超过 `200 ms`，p99 均低于 `500 ms`，每轮 2,000/2,000 请求 HTTP 200、error rate 为 0，provenance 均匹配当前 SHA。
- **证据边界：** 性能门禁失败使该 SHA 没有生成 `final-evidence-manifest.json` 和 19 项当前 SHA receipt；上一轮 `8ffa162` 的 64 文件 manifest 与 19 项 receipt 仍是最后一轮完整通过证据，不能跨 SHA 直接替代。
- **处理决定：** 不放宽 `200 ms` p95 门槛，也不把 WSL 本地结果当作 GitHub runner 发布门禁。Task 14 回到 **`in_progress`**，不关闭；待当前主分支性能门禁稳定通过后再生成同 SHA manifest/19 项 receipt，并重新评估关闭。

## 6.12 warm-inference 首轮预热缺口修复（2026-09-26）

对 `74be1ce` 两次失败样本、`8ffa162` 通过样本和压测执行顺序逐项核对后，确认正式 `run_performance.sh` 虽然工具已支持 `--warmup`，却没有在 warm-inference 测量前执行预热。失败均为首轮单独越过 200 ms，后两轮回落，且请求全为 HTTP 200；这与模型已在 fixture 阶段加载、但 backend 两个进程的认证/运行时首次并发路径未被预热相符。

- **最小修复：** 每个 warm-inference 测量轮次增加 `--warmup 20`（20 路并发、每路 20 个请求，即 400 个同路径预热请求）；正式测量仍固定为 20 路 × 100 请求、2,000 请求和原有 `p95 <= 200 ms`、`p99 <= 500 ms` 门槛。
- **证据约束：** 原始 warm-inference receipt 记录预热请求/错误计数；summary 对预热计数执行 accounting 校验并要求 `errors == 0`，预热失败保持 fail-closed。没有把预热请求计入正式测量样本。
- **本地验证：** 新增的预热 receipt、预热失败门禁和 acceptance runner 合同先在现状下失败，修复后 `tests.test_week11_12_tools` **114 passed**；`git diff --check` 和经 CRLF 归一化输入的 `run_performance.sh` `bash -n` 通过。远程完整 CI 尚未在该修复 SHA 运行，Task 14 仍为 **`in_progress`**。

## 6.13 通用平台 Task 14 最终主分支收口（2026-09-26）

本节追加记录 6.12 之后的真实执行结果；6.1–6.12 的历史结论保留，不回写旧 SHA。最终发布代码为主分支合并提交 `3fc246980b32c463a9c120573a0b0058bed8d9e7`，其 Git tree 与修复分支 `f7e3fdb749c8a99d7ea57edcdd63b181dd62f88b` 一致，后者只包含已验证的 warm-inference 预热门禁修复。

- **远程 full CI：** GitHub Actions [Run 36247830654](https://github.com/FaceGg/Al-Platform/actions/runs/36247830654) 的 Production integration、Production experiment integration、Quality Ubuntu、Quality Windows、Chromium acceptance、Week 11–12 verification 六个作业全部 `success`，无 `skipped`。Quality Ubuntu/Windows 完成后端全量、前端全量、构建和服务 smoke；Chromium acceptance 为 12 项通过；Week 11–12 完成迁移、备份/恢复、升级、安全扫描、冻结 Web 安全门禁和 live acceptance。
- **最终 evidence manifest：** 下载目录为 `temp_test/remote-main-36247830654/`。`final-evidence-manifest.json` 为 `status=passed`、`commit=3fc246980b32c463a9c120573a0b0058bed8d9e7`、迁移 head `20260926_61`、64 个文件；逐文件存在性、size 和 SHA-256 均匹配，镜像 digest 为 `sha256:d3d3e37ce1122f6e17eb8bdb8d648bf982f1b05828bae9dfcf2277835dadac4f`。
- **19 项 receipt：** `generic-platform-acceptance/acceptance-manifest.json` 恰好包含 19 个必需 ID，全部 `passed` 并绑定该 SHA；receipt 文件、manifest 内容和每个 evidence path 的 Git blob SHA-256 均复核通过。`performance/summary.json` 的 provenance 与当前 SHA 一致，warm-inference 三轮均为 2,000 个测量请求、400 个预热请求、错误数 0；p95 为 `192.04/196.12/191.17 ms`，p99 为 `263.01/424.39/408.34 ms`，均未改变既有门槛。
- **CLU-02 真实证据：** `temp_test/task14-real-3fc246980b32c463a9c120573a0b0058bed8d9e7/clu02-runtime.json` 记录真实 Celery worker 完成 10,000 行聚类，`evaluation_mode=all_rows`、评估样本数和总样本数均为 10,000，两簇各 5,000 行；`clu02-browser.json` 记录 Playwright 真实 API 分页，每页最多 50 行、cursor 已使用、总量 10,000，任何响应没有返回 10,000 项。
- **AUTH-02 真实证据：** `auth-runtime-final.json` 和 `auth-runtime-enrichment.json` 记录未知 Origin 403、允许 Origin preflight 200、CSRF origin/token 门禁、PBKDF2 哈希、登录第 19 次触发 `RATE_LIMITED`、缺少 service token 401；`auth-gateway-runtime-final.json` 记录独立 annotator 网关注册、管理员激活、门户登录/session/me，以及网关生成 service JWT 调用 backend 内部 notifications 200。两服务镜像均以 `3fc246…` 标签构建。
- **AUTO-02 真实证据：** `auto02-runtime-final.json` 记录 HTTP API → Redis/Celery worker 完成 `random_forest` 候选，任务状态 `completed`；手动注册第一次 201、同一 `Idempotency-Key` 重放 200，两个响应复用同一 `model_version_id`。`auto02-browser-final.json` 记录 Playwright 页面显示完成状态、模型结果、Random Forest 候选和注册操作。
- **REL-01 真实证据：** `rel01-final-v2/receipt.json` 记录隔离 Redis broker 上真实 worker 的中断/重启恢复：首个 worker 在 `materializing`、attempt 1 被终止并推进租约过期，attempt 3 恢复同一 operation，5,000 条结果完成；重复投递无重复结果，worker 日志 SHA-256 同 receipt 保存。该演练显式使用 `preview_ready` 执行门状态，适配现行 manual task 合同并已记录。
- **运行边界：** `runtime-images.json` 和 `stack-status-final.txt` 绑定 `3fc246…` 的当前镜像。backend、inference、tensorboard、annotator 健康；worker/scheduler 仍显示 Compose 继承的 HTTP healthcheck `unhealthy`，但 Celery 日志、真实四项演练和 broker 恢复均通过，这是 Celery-only 子镜像没有 HTTP endpoint 的已知设计边界，不改写为服务 HTTP 健康。
- **台账结论：** 当前主分支完整 CI、最终 manifest、19 项 receipt 和四项同 SHA 真实运行证据均通过，Task 14 标记为 **`completed`** 并归档；Week 13–17 计划仍按 Week 13 → Week 14 → Week 15 → Week 16 → Week 17 顺序执行，未因 Task 14 收口而提前开始。

## 7. 计划归档索引

- [实施计划索引](ml-platform/docs/superpowers/plans/README.md)：当前、历史、已替代和合并子计划的统一入口。
- [2026-09-24 归档快照](DEVELOPMENT_PLAN.history-2026-09-24.md)：本次压缩前的完整 2026-09-23 及之前记录，原文保留。
- [2026-09-03 归档](DEVELOPMENT_PLAN.history-2026-09-03.md)。
- [2026-08-23 归档](DEVELOPMENT_PLAN.history-2026-08-23.md)。

## 8. 维护记录

- 2026-10-10（Week 16 实现与收口）：按 [Week 16 实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week16-multi-cluster-governance.md) 完成 RED→GREEN 实现与双集群验收。**后端**：① `resource_governance` 五表 + 迁移 `20261010_67`（5 处 head 常量 + fixture 同步）；② `cluster_scheduler` 路由器（无策略单集群退化 `default_single_cluster`、策略按 priority、region/capability/cost 确定性排序、stale/非 active/GPU 无容量逐集群排除原因、`routing/preview` 不落预留）+ 预留（事务内聚合校验 `SUM(active)+request<=quota`、`operation_id` 唯一、SQLite BEGIN IMMEDIATE / PG FOR UPDATE 串行化并发防超卖——8 线程争 4 cpu 恰好 4 成的竞态测试固化、四条释放路径幂等：terminal/orphaned/expired/manual）；③ `resource_governance` 服务（配额 CRUD revision+审计、Summary API 采集——经 API server proxy `nodes/proxy`，每 scope ≤100 条截断标记、失败收敛 stale 不阻塞提交、GPU utilization 无设备插件即 `unavailable` 不伪造、快照过期清理）+ `storage_mounts`（object_prefix 必须 `projects/{project_id}/` 前缀、hostPath 永远非法、read_only 注入）；④ Week 14/15 提交链路插入"预留→submit"钩子（QUOTA_EXCEEDED 回滚新建行并 422）与终态/孤儿/过期释放钩子——**W13–15 既有测试全过即单集群兼容回归**；⑤ beat 新增 `governance-usage-collect`(60s)/`governance-reservation-sweep`(300s)。**API+前端**：`/api/cluster-governance`（策略/绑定/配额 CRUD + 预留只读列表 + 用量查询 + 手动采集 502 封闭 + 路由预演）与 ClusterGovernancePage（五表 + stale/truncated 提示 + 预演面板逐集群排除原因）。**验证**：后端四模块 28 passed、`run_suite --week 16/15/14/13` 全过、alembic、production 22 passed；前端 4 用例 + 全量 427 passed/19 skipped + tsc + build；**双 kind 集群 smoke 19/19 PASS**（第二个集群 linkraft-w16b@46618 当周新建；停 B→路由排除并给 `cluster_not_active`；A 提交 succeeded→预留 terminal 释放；配额收紧→422 QUOTA_EXCEEDED；Summary 采集 12 行；删策略→单集群退化保持；证据 `temp_test/week16-local/EVIDENCE.md`）；Playwright **1 passed**（治理页+预演+配额拒绝，截图 2 张）；week16 验收 profile OVERALL passed。**过程中修复**：RealKubernetesClient 缺 `node_summary`、Week14 RBAC 补 `nodes/proxy`、cluster B 的集群级 Binding 指向 linkraft-w16 而平台 token 是 linkraft-w14（请求以 system:anonymous 403）、执行器/Notebook 预留钩子失败时回滚新建行。**余项已收口**，**Week 16 转 completed**。Week 16 期间 WSL 再次空闲重启一次（keepalive 已续）。
- 2026-10-09（Week 15 实现与收口）：按 [Week 15 实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week15-notebooks-images-gpu.md) 完成 RED→GREEN 实现与真实集群验收。**决策前置（Task 15.1）**：构建路径按台账既定保守基线执行——预构建镜像目录，构建端点 501 `IMAGE_BUILD_NOT_APPROVED`（`image_build_approved` 默认 False，适配器合同冻结，Kaniko 获批后增量）；GPU 类空表，无 NVIDIA 节点用例按 skipped 口径；Notebook 基线镜像 `jupyter/base-notebook@sha256:8c903974…`（宿主按 digest 拉取 → ctr 导入节点，kubelet 零外网拉取）。**后端**：① `developer_resources` 四表 + 迁移 `20261008_66`（5 处 head 常量 + `run_upgrade_fixture.sh --target` 同步）；② `notebook_service`——会话=Week 14 执行器上 `linkraft.io/role=notebook` 作业（数据库先行/幂等重放/并发上限 429/终态一次）、每会话 ClusterIP Service、HMAC 短时代理令牌（15 分钟、绑定 session+user、删会话即失效）、idle 扫描（beat `notebook-idle-sweep` 300s，审计 `notebook.idle_timeout`）；③ `notebooks.py` API（含 `/access` 与 `/proxy` 反代——经 K8s service proxy，凭据只在服务端）与 `images.py`（登记 409/digest 不可变 422/可见性隔离/scan-failed 引用拒绝/构建门 501）；④ `gpu_scheduler`（类解析显式错误、快照 stale 刷新、容量复核、受控 selector/tolerations、`probe_gpu_nodes` skipped 语义）；⑤ client 增 service 面与 `proxy_service_request`。**前端**：`api/notebooks.ts`、NotebookPage（启动表单限目录内镜像 + 联动集群命名空间下拉）、ImageCatalogPage（短 digest/扫描徽标行内更新）、路由/导航/i18n 中英 + NOTEBOOK_*/IMAGE_*/GPU_* 错误码。**验证**：后端 4 模块 32 passed、`run_suite --week 15/14/13` 全过、alembic、production 22 passed；前端 8 用例 + 全量 421 passed/19 skipped + tsc + build；kind smoke **18/18 PASS** + 空闲回收实测（证据 `temp_test/week15-local/EVIDENCE.md`，绑定 HEAD `268efe6` 之上的工作树）；Playwright **1 passed**（截图 4 张）；week15 验收 profile OVERALL passed（`acceptance-20261009T091939Z.json`）。**过程中修复**：RealKubernetesClient 作业字段必填假设（notebook 无 activeDeadline）、V1ServiceSpec `type` 参数名、Week14 RBAC 补 services/services:proxy、NotebookPage 启动表单补 namespace 字段（原会话全落 default 被 SA 403）、代理端点改自包含 HMAC 令牌（浏览器导航无法带 JWT 头）。**余项已收口**：远端 CI 收据 run 37911977130（Quality ubuntu + windows 全绿，绑定最终 SHA `3fc710c`，含 Week 15 代码 `a42248d`；`a42248d` 自身的 run 被并发新推送取消，收据以最终 SHA 为准）。**Week 15 转 completed。** Week 15 期间 WSL 空闲重启两次杀掉 kind 容器，均已恢复；kind kubeconfig 端口漂移需重设 46617。
- 2026-10-03（续3）：**闭环演示 500 修复与全栈数据恢复（用户反馈"点击开始演示报错500"）**：根因链——WSL 重建栈时 postgres 与 **MinIO 容器均被重建**，MinIO 数据目录无卷挂载（容器层存储），重建即清空：全部模型制品/数据集文件丢失，但 postgres 结构化数据（含 `dataset_samples` 行数据、模型注册表元数据、demo_loop 配置）经前次旧卷恢复后完好。predict 500 = 部署 11 当前指向的自动重训模型 e64dcb41 的 lightgbm.joblib 在 MinIO 中 NoSuchKey。**恢复**：① 重训数据集从 postgres `dataset_samples` 行数据整体重建（46 行 × 74 列，新制品 `07c3ab20`）并更新闭环配置指向；② 直接触发重训（celery 接单，约 90s 完成），最优候选注册批准后**部署 11 自动切换**至新模型 5a1ad46c；③ 真实 fault=1 行预测 PRED=1、错误回流、阈值告警全部复验通过。**顺带修复 2 个恢复暴露缺陷**：(a) `complete_retrain_swap` 固定模型名撞 `registered_models (project_id,name)` 唯一约束（第二轮重训必失败）→ 模型名追加 job id 后缀周期唯一；(b) 闭环健壮性——报错数据集存储文件丢失时 `_error_artifact` 自愈新建；`_load_model` 存储读取失败转 `DEMO_LOOP_MODEL_ARTIFACT_MISSING` 明确错误（不再 500）。测试 20 passed。**用户侧剩余动作**：原始 CSV 文件（labeled_features.csv/labeled1.csv 等）随 MinIO 丢失不可恢复，演示前需重新上传原始数据；已恢复的重训数据集（46 行）可直接用于自动重训。backend 已重建部署。改动已提交推送 `135a19a`。
- 2026-10-03（续）：**新建编排弹窗转圈修复（用户反馈"创建按钮一直转圈，关闭按钮点击没反应"）**：根因是 `OrchestrationPage` 用单一 `creating` 状态同时控制 Modal `open` 与 OK 按钮 `confirmLoading`——弹窗一打开 creating 即为 true，OK 按钮立即进入 antd loading 态（转圈且吞掉点击），表单提交永不触发。修复：拆分为 `modalOpen`（弹窗开关）+ `submitting`（提交 loading）两个独立状态，createWorkflow 改 setSubmitting 且 finally 归位；新增「Cancel 关闭弹窗且不调 API」测试（6 项全绿）。真实浏览器验证：OK 初始不转圈、Cancel 正常关闭、创建「浏览器验证服务图」成功跳转 `/workspace/{id}` 且算子面板加载。已提交推送 `d857d0c`。
- 2026-10-03（补记，跨天会话）：**导航「应用编排」改造为方案 B 服务图工作台（用户指示"我需要从导航栏的应用编排进入"）**：`OrchestrationPage` 由多智能体演示骨架改造为服务图工作台——项目选择器（自动加载并选中）、该项目工作流列表（名称/描述/更新时间）、每行操作「编辑图」（进画布）/「发布为 API」（保存→发布版本→注册编排 API，门禁错误明细直出）/删除（确认气泡）、顶部「新建服务图」（Modal 创建空图并跳画布）与「前往 API 市场」直达、操作提示 Alert 说明闭环算子拖入方式；旧多智能体演示页下线（`OrchestrationPage.test.tsx` 全量重写为 5 项工作台测试：列表/创建（form submit 派发替代 antd Modal onOk 合成点击）/发布按钮存在且可用/删除气泡弹出/空态）。**测试基建教训**：jsdom + React 18 + antd Table 行按钮合成点击与 Popconfirm 确认点击不稳定（事件到达 DOM 但 React 委派不派发），UI 点击流改在真实浏览器验证；`react-router-dom` mock 必须含 `useLocation`（AppLayout 依赖），否则渲染树崩坏导致后续交互全部失效。**事故与恢复**：部署验证时发现 postgres `projects` 表被清空——根因为 compose 中 postgres 数据目录使用**匿名卷**，`wsl --shutdown` 后全栈重建时容器被重建生成新匿名卷，旧数据卷（cdec06ba…，含点焊项目/4 工作流/3 API/闭环配置）被弃用但未删除；通过 `docker run -v 旧卷:/v postgres:16` 启动临时实例确认数据完整（1 项目/5 用户/1 部署）后，停双 postgres、辅助容器 `cp -a` 将旧卷内容整体复制回当前卷，重启后数据完整恢复（projects=1/demo_loop=1/apis=3/workflows=4）。**真实浏览器验证**（localhost 登录→导航进入应用编排）：列表显示点焊项目 4 个工作流；「特征工程」发布触发门禁错误 toast（服务图缺少 api_input 节点）；「planb-serving-ec0ee6」发布成功 toast（v2）；API 市场确认 v2 出现且 Published。**注意**：docker 构建基础镜像（node:20-alpine）本地缓存被清且 docker daemon 代理指向 127.0.0.1:7897（Windows 代理未运行/未镜像）导致无法拉取——临时以本地 nginx:stable-alpine + 已构建 dist 打预构建镜像绕过（temp_test/fe_prebuilt），网络恢复后建议 `docker compose build frontend` 回归正常构建。新增演示操作手册 `ml-platform/docs/闭环系统演示操作手册.md`。
- 2026-10-08（续2）：CI 三连红修复（run 37709022255/37719748335/37733906529，双平台同挂 `Run backend suite`）。**根因**：`8ac68c8`（wheelhouse 离线安装 + aliyun 默认镜像源）违反两条固化生产契约——`test_ci_workflow::test_production_python_dockerfiles_use_default_pypi_index`（Dockerfile 默认索引必须 pypi.org 且全文不得出现 aliyun）与 `test_image_security_contracts::test_wolfi_images_install_recorded_python_and_keep_non_root_runtime`（xgboost/catboost pip 安装命令为录制冻结串，不得插入 --find-links/--index-url）；docs-only 提交也红印证为 Dockerfile 状态问题，与本会话监控改动无关。**修复**：`Dockerfile`/`Dockerfile.worker` 恢复 e65396b 绿色版本（`3329e0c`），本地 WSL 契约测试 75 passed + 146 subtests。**未竟事项（留给并行会话/用户决策）**：wheelhouse 离线安装诉求与生产契约冲突——合规路径是走契约评审修改 `test_ci_workflow`/`test_image_security_contracts` 的录制串（例如允许追加 `--find-links /wheels` 于行尾或 ARG 白名单），本地临时构建仍可用 `--build-arg`+pip cache mount；`wheelhouse/` 目录保留在磁盘未跟踪。**另注**：日志中 `no such table: inference_metric_buckets` 出现在 PASSED 的 `test_week11_contracts` 内，属负路径测试预期日志，非失败。**推送插曲**：github.com 主站持续不可达（api.github.com 可用）——DoH 解析真实 IP `20.205.243.166`，本地 7897 起 CONNECT 钉 IP 代理完成 push/fetch（修复两轮：CONNECT 请求头不得转发给目标 TLS 端；用完即撤）。推送 `3329e0c`（连同并行会话本地提交 `edb4227` kubernetes smoke 修复），CI run 37736316661 双平台全绿收口（conclusion=success，绑定 SHA `3329e0c`）。
- 2026-10-08（Week 14 恢复开发）：按 [Week 14 实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week14-kubernetes-executor.md) 自 Task 14.1 恢复并完成本地实现（RED→GREEN）与真实集群 smoke。**后端**：① executor 重构——提交顺序修正（DurableOperation 先建、run 带 operation_id 一次 commit，修复 WIP 首提交必触发 operation_id NOT NULL 的缺陷）、fetch/apply 拆分、终态接线（succeeded 走 claim+complete（checksum 需 `sha256:` 前缀），其余走 fail_operation，取消错误码 KUBE_JOB_CANCELLED）；② `RealKubernetesClient` 补齐 Week 14 作业面（此前只有 Fake 有）——create/get/delete Job、list pods、read pod log，K8s 1.37 适配（manualSelector、命名空间限定调用、`linkraft.io/operation-id` pod 选择器、FailureTarget/SuccessCriteriaMet 条件映射、410→KUBERNETES_GONE）；③ 新增 `app/tasks/kubernetes_tasks.py`（watch 租约+resourceVersion 续点+退避回落轮询、reconcile sweep、超时双通道 sweeper、TTL GC）并注册 celery include + beat（60s/300s）；④ API 修复——submit 权限检查改按 `cluster.project_id`（WIP 误传 cluster_id）、namespace 改为校验登记（不再改写集群默认值）、响应附 operation_state/progress。**前端**：`api/kubernetesJobs.ts`、`JobRunsPage.tsx`（状态徽标/stage/progress、cursor 增量日志+end_of_stream、终态禁用取消、timeout/orphaned 解释文案）、`/kubernetes/jobs` 路由、导航「作业运行」、i18n 中英 + KUBE_JOB_* 错误码。**清单**：`week_manifest.py` 新增 `14:` 四模块；`weekAcceptance.test.ts` 新增第 14 周。**验证**：后端 4 模块 50 passed、`run_suite --week 14` 4/4、`--week 13` 3/3、compileall、前端 6 用例 + 全量 410 passed/19 skipped + tsc + build、`git diff --check` 干净；kind v1.37.0 作业 smoke 19/19 PASS（五场景全过，证据 `temp_test/week14-local/EVIDENCE.md`；过程中 WSL 空闲重启杀掉 kind 节点容器，已按固定端口 46617 重建并重载 digest 镜像）。主体实现已随 `9148965` 入库。
- 2026-10-08（Week 14 浏览器验收与收口）：① 已认证 Playwright 流程 **1 passed**（chromium，`e2e/week14-jobruns.spec.ts`，9.3s）：admin 登录 → API 造项目/集群登记/连通性/命名空间 → API 提交 echo+长作业 → JobRunsPage 列表显确定性作业名 → 状态经 reconcile 转 succeeded → 日志抽屉显 `w14-browser-log-marker` + `end_of_stream` → UI 取消 → cancelled + 取消按钮禁用；截图 3 张入 `temp_test/week14-local/playwright/`。spec 在测试侧周期调 reconcile（e2e 栈无 celery worker）。**环境注记**：e2e 用 5177 端口时后端 403 `CORS_ORIGIN_FORBIDDEN`——本地 CORS 白名单只放宽到 5175，需 `FRONTEND_ORIGIN_ALIASES=http://127.0.0.1:5177`（与 2026-10-06 续2 的 5176 教训同源）；vite 代理必须 `VITE_API_PROXY_TARGET=http://127.0.0.1:8000`（localhost 解析 ::1 教训同源）。② `run_week13_17_acceptance.sh` 新增 week14 profile（四后端模块 + JobRunsPage/weekAcceptance 前端用例），本机运行 **OVERALL passed**（8 步全绿，manifest `acceptance-20261008T054823Z.json` 绑定 SHA）。**余项**：绑定最终 SHA 的远端 CI 收据——已取得：run 37736316661（Quality ubuntu + windows 全绿，绑定 SHA `3329e0c`，该 SHA 包含 Week 14 全部代码 `9148965`/`edb4227`）。**Week 14 转 completed。**
- 2026-10-08（续2）：资源监控卡片尺寸统一（用户反馈"统一一下各个组件的大小"）。`MonitorPage`：`MetricCard` 增加 `zone` 插槽（网络/磁盘 I/O 速率对并入同一卡片骨架，替换原先独立 Card + 手排布局）；CSS 实现等高——`.monitor-grid > .ant-col` flex 拉伸 + 卡片 `flex:1/width:100%/body 100%` 纵向 flex，新增固定 132px `monitor-gauge-zone`（仪表与速率读数垂直居中对齐），趋势图 `margin-top:auto` 钉在卡片底部（统计行数量不一致时底部仍对齐）。验证：tsc、MonitorPage 5 passed、build 通过；frontend 镜像单独重建部署（新 bundle `index-CmkCFTO6.js`），浏览器实测两行卡片等高、仪表/速率区与标题/趋势图基线对齐。改动未提交。
- 2026-10-08（续）：资源监控新增组件 + 特效降级为平台风格（用户先问"能否支持更多组件"，实现中追加反馈"稍微减少点特效，和主平台整体样式更契合一些"）。**后端**（`monitor.py`）：`collect_metrics()` 新增 `load`（load1/5/15 + cpu_cores）、`net`（rx/tx 累计字节，非 lo 接口聚合）、`disk_io`（read/write 累计字节，排除 loop/ram/dm/sr 设备）、`uptime_seconds`；采集以 `psutil`（新增依赖 `psutil==7.1.*`）为主、`/proc/net/dev`+`/proc/diskstats`+`/proc/uptime`+Win32 `GetTickCount64` 为回退，跨平台可用；历史缓冲自动携带新字段。**前端**（`MonitorPage` v3，特效按反馈全面降级）：移除扫描线/发光/强制暗底/等宽字体/HUD 角标/LIVE 呼吸灯/自绘弧形仪表，回归 antd Card + `Progress dashboard` + 平台色板（#47C3A0/#D9AC52/#E66F75/#2F9BF5）+ 主题 CSS 变量，页头对齐其他页面的 `page-header/page-title` 模式（右侧副文本显示"已运行/更新于"+ 刷新按钮）；**新增三张卡片**——负载（仪表 = load1/核数 %，附 1m/5m/15m）、网络 I/O（↓下载/↑上传实时速率，前端按服务端时间戳对相邻采样做差值计算）、磁盘 I/O（读/写速率）；速率序列同样经 `/monitor/history` 回填（含时间戳差值），计数器回绕（重启）区间自动跳过；多 GPU/温度/显存/无 GPU 兼容保留。**测试**：`test_api_monitor` 15 passed（新增 load/net/disk_io/uptime/history 字段 6 用例）；前端 MonitorPage 5 passed（新增网络/磁盘/负载/运行时长断言；速率断言暴露并用服务端时间戳替代客户端时钟计算区间——客户端时钟与后端缓冲偏差会使速率失真，属真实缺陷修正）+ 全量 411 passed/19 skipped + tsc + build。**部署**：frontend/backend/worker 三镜像重建（假代理 + 阿里云 pip 源方案复用），`up -d` 全栈 healthy，正式 5173 新 bundle `index-CNMsv6M_.js`；浏览器实测暗/浅双主题：新卡片实时速率真实跳动（网络 ↓1.1 KB/s ↑827 B/s、磁盘写入 31.8 KB/s 尖峰），负载/运行时长/无 GPU 提示正常。改动未提交。
- 2026-10-08：WSL docker 部署更新 + 磁盘清理/扩容 80G（用户反馈"看到的页面还是旧版"，随后指示"清理、压缩 wsl 空间，扩容到 80G"）。**旧版原因**：正式入口 5173 是 WSL docker compose 的 nginx 容器（打包构建产物），此前所有改动只在代码库，容器跑旧镜像（bundle `index-CxwEC5qj.js`）。**部署过程四连障及处置**：① WSL docker daemon 代理 `127.0.0.1:7897` 失效致基础镜像元数据解析失败——在 WSL 本地起直连转发假代理（/tmp/dummy_proxy.py，不动 daemon 配置，用完即撤）；② 清华 PyPI 源 DNS 失效——按 Dockerfile 文档化的 `--build-arg PIP_INDEX_URL` 改用阿里云源；③ 磁盘满（49G 用 99%，镜像导出 no space left）——`compose down + image/builder prune` 释放 26G；④ WSL VM 空闲自动关机反复带走后台任务（/tmp 清空、假代理死亡、容器全组重启），放置 4 小时 keepalive（`setsid nohup timeout 14400 sleep 循环`）后收敛。**压缩+扩容**：清理后（22G/49G）`wsl --shutdown` → `wsl --manage Ubuntu --set-sparse true --allow-unsafe`（官方通道，VM 停止后需放行标志）→ 稀疏 vhdx 在线 resize 报 0xc03a001a → 按 `sparse false → resize 80G（e2fsck 自动扩文件系统）→ sparse true` 三步完成。结果：**df 79G 总/54G 空**，vhdx 稀疏化按需增长自动归还 Windows。**部署结果**：四镜像重建（backend/worker/frontend/annotator-frontend）+ `migrate` 服务把用户 Postgres 迁移链完整应用到 `20261006_65` + `up -d` 全栈恢复（13 容器 healthy）。冒烟验证：正式 5173 服务新 bundle `index-B48dykCj.js`；浏览器实测 /monitor 新 HUD（内存 93% 正确红色告警、磁盘 46.1/78.4G 即新盘；容器无 GPU 直通故显示"未检测到 GPU"，与临时后端不同属预期）、/compute 新 Tabs（计算节点/边缘设备、筛选器、中文导航「计算资源」）。**注意**：① keepalive 4 小时后过期，VM 可能再次空闲关机（历史遗留问题），永久解法为 `.wslconfig` 设 `vmIdleTimeout` 或保持 keepalive，待用户决定；② 容器部署无 GPU 直通，资源监控 GPU 卡显示"未检测到 GPU"为预期；③ 此前心跳/筛选验证数据在隔离测试库，正式库计算资源表为空属正常。仓库文件无新增改动（temp_test 部署脚本已清理），运维操作记录于此。
- 2026-10-06（续6）：CI `test_week11_12_tools` 修复（run 37480832512 双平台同挂）：`test_release_n_minus_one_contract_targets_current_merge_head` 断言 `tools/acceptance/run_upgrade_fixture.sh` 的 `--target` 必须等于 alembic head（该测试的 `EXPECTED_HEAD` 经 `tools/upgrade_fixture.py` 导入，已在续2 随 `_65` 同步），但脚本本体的 `--target 20261001_64` 漏改。修复：脚本 `--target` 更新为 `20261006_65`。验证：本地 WSL 单测 + `test_database_production` 23 passed + 3 subtests。**环境注记**：本地同模块 `test_performance_runner_uses_backend_container_after_recreation` 因 WSL 下脚本被非 bash 解释器执行（`set -o pipefail` 报错）而失败，为本地环境差异，CI Ubuntu 该用例通过且本次未触及 `run_performance.sh`。教训：**迁移 head 前进时除 4 处常量外，还必须同步 `tools/acceptance/run_upgrade_fixture.sh` 的 `--target`**（后续考虑让脚本读 `upgrade_fixture.py` 的常量消除双源）。改动未提交（将随本次推送收口）。
- 2026-10-06（续5）：三平台时间显示少 8 小时修复（用户反馈主平台/标注员门户/管理员审核多处时间比实际少 8 小时）。**根因**：后端统一存/返回无时区标记的 naive UTC（ISO 串无 Z），前端 `new Date(串)` 按规范解析为**本地**墙上时间 → UTC+8 环境统一慢 8 小时。仓库内已有正确模式（`utils/time.ts` 的 `parseBackendTime` 补 Z 解析，13 文件在用；`NotificationInbox`/`ReturnAcceptancePanel`/`DataAnnotationPage` 亦各自实现过），但存在漏网点。**修复（12 处，全部走统一解析不改后端契约）**：主平台 7 处——NotificationCenter 通知时间、ComputeResourcePage 心跳时间、KubernetesPage 最近检查时间、DataAnnotationPage 任务截止日、ModelLibraryPage API Key 过期判定、DemoLoopPage 告警新鲜度判定（原恒 false 导致"刚告警"高亮不亮）、AssignmentDialog `toLocalInputValue`（**数据性缺陷**：指派弹窗预填的截止时间按本地误读 UTC，用户不改直接保存经 toISOString 回写会每次编辑再偏 8 小时）；ReturnAcceptancePanel/DataAnnotationPage 的两份重复 `formatBackendTimestamp` 收敛为委托 `parseBackendTime`。标注员门户 5 处——新建 `annotator/frontend/src/utils/time.ts`，修 AdminQueuePage/AdminReviewPage 格式化函数、TaskCard 截止日、TaskQueuePage 逾期计数（原偏差 8 小时）、NotificationInbox 内联补 Z 改用统一 util。**测试**：新增 `utils/time.test.ts` 5 用例（naive 视为 UTC、带时区原样、空/非法 null；formatLocalTime 断言与时区无关以免 UTC CI 假失败）并登记 weekAcceptance week 17；`DataAnnotationPage.test.tsx` 指派预填断言由旧错误行为（UTC 墙上时间直填）改为时区无关的正确语义断言。**验证**：主前端 404 passed/19 skipped + tsc + build、标注员前端 130 passed + tsc + build；WSL 临时后端（UTC）+ vite :5176 实测：22:36 本地时间触发心跳，最近心跳列显示 2026/10/6 **22:36:47**（修复前显示 14:36:47）。**注记**：新增前端测试文件需登记 weekAcceptance 清单门禁（本次已登记）；Backend Dockerfile/.gitignore 仍为并行会话改动未动。已随 `0649253` 推送。
- 2026-10-06（续4）：HUD 控制台跟随应用主题（用户反馈浅色主题下界面也应浅色）：`MonitorPage.css` 全部颜色收敛为 `--hud-*` CSS 变量（控制台底/网格线/卡片底与边/括号/刻度/轨道/页脚等），新增 `.hud-console--light` 浅色变体（浅底深字、对比度加深的青/琥珀/红色板、柔和光晕）；组件接入 `useTheme()` 按 `theme` 切换类名，SVG 轨道/刻度描边改走 CSS 变量，告警色板双主题各自定义（light: #0da48a/#c07f14/#d94350）。验证：tsc、全量 Vitest 399 passed/19 skipped、build 通过；真实环境浅色/暗色双主题截图验收（浅色呈浅底仪器屏效果，暗色与续3版本一致无回归）。**组件扩展性结论**（用户询问"是否支持更多组件"）：支持——卡片网格为 `auto-fit` 自适应，新增组件即新增一个 `HudCard` 数据项（标题/百分比/统计行/趋势序列五个入参），栅格自动排列；无需后端改动即可加的组件如"系统概况汇总条/告警计数（由现有 CPU/内存/磁盘/GPU 派生）"；网络 IO、磁盘 IO、进程列表等需要后端在 `monitor.py` 的 `collect_metrics()` 增采样项（历史缓冲对新增字段自动生效）。改动未提交。
- 2026-10-06（续3）：资源监控页 HUD 科幻化改版（用户指示"重新设计资源监控的显示样式，更科幻一些"，视觉语言对齐既有 demo-showcase 大屏）。`MonitorPage` 数据层不变（/monitor/current 3s 轮询 + /monitor/history 回填 + 多 GPU），渲染层整体重写：新增 `MonitorPage.css`（独立文件，`hud-` 前缀类，不污染 global.css）——自含式暗色 HUD 控制台（浅色主题下呈嵌入仪器屏效果）：工程网格背景 + 扫描线动画、顶部 SYSTEM MONITOR // REALTIME 眉题 + 发光标题 + LIVE 呼吸灯 + 实时时钟 + HUD 风格刷新按钮；四张指标卡改为自绘 SVG 260° 弧形仪表（刻度环、渐变发光进度弧、中心大号等宽数字、<60 青/61-80 琥珀/>80 红 + 卡片红框脉冲告警）、四角括号装饰、发光趋势折线（渐变面积填充）；GPU 卡显示温度与 VRAM；底部状态栏（SAMPLING 3s · BUFFER 120 / UPDATED 时间）；`prefers-reduced-motion` 关闭动画。antd Progress 依赖移除。验证：tsc、全量 Vitest 399 passed/19 skipped、build 通过（MonitorPage 既有 4 用例不动全过——标题/GPU N/温度/无 GPU 文案格式保持兼容）；WSL 临时后端 + vite :5176 真实环境截图验收两轮（暗色/浅色主题、真实 GPU/内存/磁盘数据、81% 触发 danger 态）；首版进度弧 dashoffset 数学错误（环恒显满弧）已改为直接按进度设 dasharray 并修正网格列宽为 4 卡一行。临时服务已清理。改动未提交。
- 2026-10-06（续2）：资源监控 / 计算资源功能补全（用户指示"补全功能"，接同日功能完整度评估）。**后端**：① 新迁移 `20261006_65`（head，4 处常量同步：test_database_production、test_inference_production_stack、evidence_manifest、upgrade_fixture）给 `compute_nodes` 加 `last_heartbeat`；② `compute.py` 新增 `POST /api/compute/nodes/{id}/heartbeat`（上报存活，可选带 status/current_load，负载钳位 0-100、非数值 422）与 `POST /api/compute/devices/{id}/heartbeat`（存活 + 可选 model_deployed/version，供边缘代理上报运行时信息）；列表/详情响应新增 `last_heartbeat`/`heartbeat_stale`（阈值 `COMPUTE_HEARTBEAT_STALE_SECONDS` 默认 180s，过期即标记）。**前端**：③ `ComputeResourcePage` 重构为 Tabs——「计算节点」Tab 增加状态/用途筛选器（接后端既有 query 参数）、最近心跳列（从未上报/心跳正常/心跳超时）与"上报心跳"操作；新增「边缘设备」Tab 完整 CRUD（分组/IP/类型/状态/部署模型/版本/心跳展示，补齐后端已有但无入口的设备管理）；④ `MonitorPage` 挂载时拉取 `/monitor/history?limit=60` 回填趋势线（此前刷新即清零），GPU 改为逐卡渲染（单卡标题仍为"GPU"保持兼容，多卡 GPU 1/2/…，无卡显示"未检测到 GPU"），GPU 卡显示显存与温度；i18n 增 `monitor.temperature`/`monitor.no_gpu`（中英）。**测试**：`test_api_compute` 20 passed（新增 5 心跳用例）；`test_database_production` 22 passed + 3 subtests（全新 SQLite 完整 upgrade→head 链含 `_65`）；前端全量 399 passed/19 skipped、tsc、build 通过；`ComputeResourcePage.test.tsx` 新建 8 用例并登记 weekAcceptance week 12。**真实环境 E2E**（WSL venv + 隔离 SQLite e2e.db 起 uvicorn :8010，前端 vite :5176 代理）：登录 → 创建节点"GPU-训练机-01" → 上报心跳（从未上报→心跳正常）→ 创建设备"车间边缘盒-01" → 设备心跳 → 状态筛选（选"离线"表格变 No data，恢复后节点重现）→ /monitor 真实数据渲染（CPU 28%/内存 5.6/7.8G/磁盘 36.4/48.9G/真实 GPU 11% + 温度 59°C，趋势图含历史回填）。**环境注记**：vite 代理目标需用 `127.0.0.1`（`localhost` 在 Node 下解析 ::1 而后端仅听 IPv4，报 502）；vite 5173-5176 被占是因此前 TaskStop 只杀 shell 未杀 node 子进程，已手动清理；CORS 白名单本地模式只扩展到 5175，5176 需 `FRONTEND_ORIGIN_ALIASES`。**遗留**：心跳依赖节点侧代理定时调用新端点（平台侧暂无内置 agent）；compute 页面文案保持中文硬编码风格未接 i18n（与该页现状一致）。改动未提交。另：工作区存在非本会话所改的 `backend/Dockerfile`（PyPI 镜像 ARG）与未跟踪 `backend/.gitignore`，未动。
- 2026-10-06（续）：左侧导航「Compute」标签中文化（用户反馈应显示中文）：`AppLayout.tsx` 该项硬编码 `label: "Compute"`，而 i18n 早已定义 `nav.compute`（zh「计算资源」/ en「Compute Resources」），改为引用 `t.nav.compute`。验证：AppLayout 两组单测 12 passed、tsc 通过；浏览器实测中文侧边栏显示「计算资源」且点击进入 `/compute` 高亮正确，切 EN 显示「Compute Resources」后切回中文正常。另应用户询问完成「资源监控 / Compute 功能完整度」代码级评估（结论见会话回复）：两页前后端链路真实可用，但有明确边界——资源监控仅本机指标、多 GPU 只显示第一卡、`/monitor/history` 前端未消费；Compute 后端的边缘设备（`/api/compute/devices`）CRUD 无前端入口，节点 status/current_load 为手工字段非自动采样。已随补全功能一并改动，见上条。
- 2026-10-06：Kubernetes 集群页归位主布局（用户反馈：左侧导航点击「Kubernetes 集群」后跳到无侧边栏的独立页面）。`KubernetesPage.tsx` 此前未像其他页面一样用 `AppLayout` 包裹（返回裸 `<div style={{padding:24}}>`，而 `App.tsx` 路由直接渲染页面），导致该路由缺少侧边栏/顶栏。修复：引入并包裹 `AppLayout`、去掉自带 padding（Content 已有 24px），与 `ComputeResourcePage`/`MonitorPage` 等页面模式一致；页面功能与测试 mock 不变。验证：`tsc --noEmit` 通过、`KubernetesPage.test.tsx` 7 passed；本地 Vite 实测注入 token 后直接访问 `/kubernetes` 与从工作台点击导航进入，均渲染完整侧边栏（17 个菜单项）+ 顶栏且「Kubernetes 集群」菜单项正确高亮（截图核验）。已提交并推送 `8640136`。
- 2026-10-01（续）：后端修复后 CI 仍红一轮（Run [36811727009](https://github.com/FaceGg/Al-Platform/actions/runs/36811727009) @ `009eb0a`：Quality 双平台 backend suite 均转绿，前端 `LabelSchemaEditor.test.tsx` 1 failed/374 passed）。根因仍是 `50e52be`（统一标签列定义）：`LabelSchemaEditor` 新增"标注用途不提供纯范围"规则（`allowRangeOnly = purpose !== "annotation"`，select 不再渲染 `range` 选项），旧用例"rejects empty or type-mismatched enum values and empty ranges"仍 `fireEvent.change(约束方式, "range")`，jsdom 中无效选项使范围输入不渲染，`getByLabelText("最小值 1")` 抛 TestingLibraryElementError。修复：该段改走 `enum_range`（标注用途下可用，且保存校验对 range/enum_range 同样拒绝缺最大值），用例意图不变。验证：worktree 内 `npm ci` + `vitest run LabelSchemaEditor.test.tsx` 12 passed。注：并行会话本地 main 停在 `50e52be` 且其未提交改动含 `week_manifest.py`/`DEVELOPMENT_PLAN.md`，与 `009eb0a` 重叠，其下次推送需先并入 `009eb0a` 并丢弃重复修复；本会话不再快进本地 main 以免覆盖其编辑。

- 2026-10-01：main CI 三连红→修复（Run [36676042604](https://github.com/FaceGg/Al-Platform/actions/runs/36676042604) @ `8e5958a`、Run [36678153553](https://github.com/FaceGg/Al-Platform/actions/runs/36678153553) @ `2263107`、Run [36806477852](https://github.com/FaceGg/Al-Platform/actions/runs/36806477852) @ `50e52be`，三-run Quality 双平台均在 backend suite 失败，失败面一致）。两项根因均来自 `8e5958a`（自动标注标签展示功能）：① 新增 `test_model_export_annotation_lineage.py` 未登记周归属，周清单门禁 `test_every_backend_test_module_has_one_week_owner` 报 discovered−assigned = {'test_model_export_annotation_lineage'}（与 2026-09-30 `test_waveform_samples` 同类）；② `/api/internal/portal/tasks/{id}/samples` 响应新增 `automatic_labels`/`manual_modified` 字段（`annotator_internal.py` 有意变更，前端展示自动标注），旧用例 `test_internal_portal_task_and_sample_reads_are_subject_scoped`（`test_portal_internal_api.py:510`）的精确断言未同步。修复：`week_manifest.py` 将 `test_model_export_annotation_lineage` 登记到 week 17（与 `test_model_exports_api` 等导出模块同组）；旧断言补 `"automatic_labels": None, "manual_modified": False`（无自动标注 fixture 下确定性取值）。验证（WSL `~/venv` 已补全整个 requirements.txt，此前缺 optuna/jwt/tensorboard 等）：portal 模块 86 passed、lineage 模块 5 passed（其中 `test_worker_export_embeds_resolved_annotation_payload` 首次本地失败为缺 tensorboard 的 import 断链，补依赖后通过，非代码 bug）、manifest 门禁 5 passed + 2 subtests（含此前 environment-blocked 的两个 gated-stack 用例）。修复在独立 worktree（origin/main `50e52be`）完成，不触碰并行会话的主工作区未提交改动。
- 2026-10-01：**全项目测试轮（用户指示"测试整个项目，修复测试出来的bug，测试完成关闭计算机"）**。后端全量套件 `run_suite`（模块超时改为可配置 `SUITE_MODULE_TIMEOUT_SECONDS`，本次 900s——原 300s 硬编码在本机会误杀 Week 12 安全模块 635s 的真实耗时）：**exit 0、142 个测试模块全 PASSED**（唯一 FAILED 为 `test_run_suite` 自身的故意失败上报探针 test_fake，预期输出）；Week 12 直跑 160 tests/635s OK。标注员后端 31 passed、标注员前端 130 passed、主前端 vitest **381 passed**（此前记录的 LabelSchemaEditor 失败在本轮未复现，判为间歇性）+ tsc/build 通过。**测试又修复 2 个真 bug**：(a) `tools/acceptance/run_upgrade_fixture.sh` 升级验收夹具脚本硬编码旧 head `20260928_63`（此前 head 同步遗漏的第六处）→ 同步至 `20261001_64`，test_week11_12_tools 114 passed；(b) `services/demo_loop.py` 直连 `spot_weld_features` 违反通用化生产源门禁（genericization 契约禁止非桥接文件引用行业模块）——改为经 `operators/processing.py`（登记桥接文件）新增的通用入口 `build_fixed_feature_frame` 取特征清单与解码，服务源不再含行业模块引用；期间发现边改代码边跑套件会让子进程抓到中间态（annotator_auth 等 3 模块假失败 ImportError），最终确认轮全部复绿。至此后端全量 142 模块 + 前端 381 用例 + 标注员 161 用例全绿。改动未提交。
- 2026-10-01：**全项目测试轮（用户指示"测试整个项目，修复测试出来的bug，测试完成关闭计算机"）**。后端全量套件 `run_suite`（模块超时改为可配置 `SUITE_MODULE_TIMEOUT_SECONDS`，本次 900s——原 300s 硬编码在本机会误杀 Week 12 安全模块 635s 的真实耗时）：**exit 0、142 个测试模块全 PASSED**（唯一 FAILED 为 `test_run_suite` 自身的故意失败上报探针 test_fake，预期输出）；Week 12 直跑 160 tests/635s OK。标注员后端 31 passed、标注员前端 130 passed、主前端 vitest **381 passed**（此前记录的 LabelSchemaEditor 失败在本轮未复现，判为间歇性）+ tsc/build 通过。**测试又修复 2 个真 bug**：(a) `tools/acceptance/run_upgrade_fixture.sh` 升级验收夹具脚本硬编码旧 head `20260928_63`（此前 head 同步遗漏的第六处）→ 同步至 `20261001_64`，test_week11_12_tools 114 passed；(b) `services/demo_loop.py` 直连 `spot_weld_features` 违反通用化生产源门禁（genericization 契约禁止非桥接文件引用行业模块）——改为经 `operators/processing.py`（登记桥接文件）新增的通用入口 `build_fixed_feature_frame` 取特征清单与解码，服务源不再含行业模块引用；期间发现边改代码边跑套件会让子进程抓到中间态（annotator_auth 等 3 模块假失败 ImportError），最终确认轮全部复绿。至此后端全量 142 模块 + 前端 381 用例 + 标注员 161 用例全绿。改动未提交。**全闭环进编排图（2026-10-01，用户指示"闭环演示中所有的操作应该均能在应用编排中实现，应用编排好之后应该能支持发布到api市场，然后可以通过API市场进行调用等"）**：新增三个闭环算子（`app/operators/serving_operators.py`）：`append_error_dataset`（报错分支行追加到错误数据集制品，行级锁+元数据更新）、`notify_admins`（站内通知项目所有者+平台管理员）、`retrain_threshold`（双输出端口 triggered/continue，从错误数据集制品元数据读取累计行数与滚动周期基数 cycle_base，达标时经 `trigger_retrain_job` 触发 AutoML，完成后经 `complete_retrain_swap` 自动注册+批准+替换部署模型）；`OperatorContext`/`DAGExecutor` 新增 `operator_id` 透传（invoke 传 workflow.created_by）；`closed_loop_actions.py` 共享闭环动作模块抽自 demo_loop（demo_loop 改为调用共享函数，消除重复）；发布门禁允许这些算子（不在 TRAINING_OPERATOR_IDS 中）。测试：`test_api_workflow_publication` 新增 test_06 全闭环图 E2E（发布→逐行 invoke→错误行回流→告警通知→阈值触发 AutoML→模拟完成→换模型→部署 FK 验证）5 项全绿（01-06）；`test_demo_loop` 14 passed。**顺带修复**：共享算子 DataFrame 真值歧义（`inputs.get("data") or []` 对 DataFrame 报 ValueError → 改为显式 None 检查）。backend/frontend 已重建部署（health ok）。改动未提交。
- 2026-10-01：**全项目测试轮（用户指示"测试整个项目，修复测试出来的bug，测试完成关闭计算机"）**。后端全量套件 `run_suite`（模块超时改为可配置 `SUITE_MODULE_TIMEOUT_SECONDS`，本次 900s——原 300s 硬编码在本机会误杀 Week 12 安全模块 635s 的真实耗时）：**exit 0、142 个测试模块全 PASSED**（唯一 FAILED 为 `test_run_suite` 自身的故意失败上报探针 test_fake，预期输出）；Week 12 直跑 160 tests/635s OK。标注员后端 31 passed、标注员前端 130 passed、主前端 vitest **381 passed**（此前记录的 LabelSchemaEditor 失败在本轮未复现，判为间歇性）+ tsc/build 通过。**测试又修复 2 个真 bug**：(a) `tools/acceptance/run_upgrade_fixture.sh` 升级验收夹具脚本硬编码旧 head `20260928_63`（此前 head 同步遗漏的第六处）→ 同步至 `20261001_64`，test_week11_12_tools 114 passed；(b) `services/demo_loop.py` 直连 `spot_weld_features` 违反通用化生产源门禁（genericization 契约禁止非桥接文件引用行业模块）——改为经 `operators/processing.py`（登记桥接文件）新增的通用入口 `build_fixed_feature_frame` 取特征清单与解码，服务源不再含行业模块引用；期间发现边改代码边跑套件会让子进程抓到中间态（annotator_auth 等 3 模块假失败 ImportError），最终确认轮全部复绿。至此后端全量 142 模块 + 前端 381 用例 + 标注员 161 用例全绿。改动未提交。**全闭环进编排图（2026-10-01，用户指示"闭环演示中所有的操作应该均能在应用编排中实现，应用编排好之后应该能支持发布到api市场，然后可以通过API市场进行调用等"）**：新增三个闭环算子（`app/operators/serving_operators.py`）：`append_error_dataset`（报错分支行追加到错误数据集制品，行级锁+元数据更新）、`notify_admins`（站内通知项目所有者+平台管理员）、`retrain_threshold`（双输出端口 triggered/continue，从错误数据集制品元数据读取累计行数与滚动周期基数 cycle_base，达标时经 `trigger_retrain_job` 触发 AutoML，完成后经 `complete_retrain_swap` 自动注册+批准+替换部署模型）；`OperatorContext`/`DAGExecutor` 新增 `operator_id` 透传（invoke 传 workflow.created_by）；`closed_loop_actions.py` 共享闭环动作模块抽自 demo_loop（demo_loop 改为调用共享函数，消除重复）；发布门禁允许这些算子（不在 TRAINING_OPERATOR_IDS 中）。测试：`test_api_workflow_publication` 新增 test_06 全闭环图 E2E（发布→逐行 invoke→错误行回流→告警通知→阈值触发 AutoML→模拟完成→换模型→部署 FK 验证）5 项全绿（01-06）；`test_demo_loop` 14 passed。**顺带修复**：共享算子 DataFrame 真值歧义（`inputs.get("data") or []` 对 DataFrame 报 ValueError → 改为显式 None 检查）。backend/frontend 已重建部署（health ok）。改动未提交。**演示操作手册（2026-10-01，用户指示"整理演示操作步骤"）**：新增 `ml-platform/docs/闭环系统演示操作手册.md`，覆盖：演示前准备（部署/标注员/重训数据集确认）、方案 A 闭环演示页操作流程（配置→数据回放→闭环副作用验证→重置）、方案 B 编排+市场操作流程（服务图搭建含完整算子参数表→发布为 API→市场管理→程序化调用）、大屏演示页（演示/实时双模式）、演示亮点话术表、常见问题排除表。

- 2026-10-01：新增「闭环演示」功能（方案 A：推理走既有模型部署 + 轻量闭环控制器，用户需求为推理→错误数据回流→阈值告警→可选人工审核→自动重训→自动换模型的完整自动化演示）。后端：新表 `demo_loop_configs`/`demo_loop_events`（迁移 `20261001_64`，head 常量 4 处同步：test_database_production、test_inference_production_stack、evidence_manifest、upgrade_fixture）；服务 `app/services/demo_loop.py`（单行预测加载部署当前模型制品、报错行追加写报错数据集制品（行级锁 + 旧对象清理）、阈值告警写站内通知（项目所有者 + admin）、告警自动创建通用标注任务并分配标注员、达到重训行数自动创建 AutoML 任务（light 强度/bayesian/自动建实验与绑定，复用 TrainingJob + LocalTrainingDispatcher 契约）、完成后自动注册最优候选为模型版本并批准、直连替换部署模型）；API `/api/projects/{id}/demo-loop/{config,predict,status,reset}`。前端：`/demo-loop` 页（项目/部署/报错类别/阈值/审核/重训配置，CSV 上传逐行调用进度动效、告警横幅、审核与重训任务链接、报错数据文件行数、模型替换动效、事件 Timeline）+ 导航「闭环演示」+ i18n nav 键。测试登记：`test_demo_loop` → week 17、`DemoLoopPage.test.tsx` → weekAcceptance 17；另将 HEAD 上已存在但未登记的 `test_model_export_annotation_lineage` 补登记（50e52be 引入的清单缺漏，非本次代码）。验证：`test_demo_loop` 7 passed（真实 sklearn 模型 + 全链路 API）；test_api_platform + test_models_misc 22 passed；test_suite_manifest + test_database_production 27 passed（迁移在全新 SQLite 上完整 upgrade→head + 双跑一致）；前端 DemoLoopPage 3 passed、AppLayout 9 passed、weekAcceptance 7 passed、全量 377 passed/19 skipped + tsc + build；真实 uvicorn 冒烟 SMOKE PASS（登录→配置→逐行预测→3 行回流→阈值告警→事件流→状态）。**遗留与边界**：① 全量前端 1 failed 为 `LabelSchemaEditor.test.tsx > rejects empty or type-mismatched enum values`——50e52be 修改组件未同步测试的既有失败（文件不在本次改动，隔离运行可复现），未处理；② `test_inference_production_stack` 本机 gated-stack skipped（environment-blocked，head 断言已同步，以 CI 为准）；③ 模型替换为部署 `model_version_id` 直连替换并记录事件，未走 rollout/金丝雀（生产语义建议保留人工批准 + rollout，注册版本 lifecycle 已按 approved 落库）；④ 报错数据集制品按追加语义原地改写（行级锁串行化），并发多 worker 部署需改为队列化写入；⑤ 改动未提交。**同日部署收口**：迁移首版在 Postgres 上失败（BOOLEAN 列 `server_default=0` 在 PG 报 DatatypeMismatch，SQLite 宽松导致本地未发现）——改为 `server_default=sa.text("false")` 后经 migrate 服务成功应用（`20260928_63 -> 20261001_64`，postgres 中 `demo_loop_configs`/`demo_loop_events` 已建）；WSL docker compose 已重建 backend/migrate/worker/frontend 镜像并重启（前端构建前经 daocloud 镜像源预拉 `nginx:stable-alpine` 并重打标签，绕开 docker.io 直连），实测 8001 `/openapi.json` 含 4 条 demo-loop 路由、5173 新 bundle（`index-Cv3NTvTU.js`）含「闭环演示」导航与 demo-loop 路由。**用户实测反馈 500 修复（同日）**：demo-loop predict 直接 joblib 加载 `source_artifact_id` 并按裸 sklearn 模型调 `.predict`，而部署模型制品为 dict 打包结构 → `AttributeError: 'dict' object has no attribute 'predict'`。修复：`_run_prediction` 改为**优先走推理运行时**（WeightedTargetRouter 路由 + InferenceRuntimeClient，与生产 predict 路径一致；按 `version.feature_schema`（兼容 dict/str 两种形态）过滤特征列并校验数值、非数值特征返回 422 而非 500），运行时不可用或未配置时回退进程内 joblib（支持 dict 制品解包 model/estimator/clf/pipeline/best_model，无可推理估计器时报清晰错误）。测试：`test_demo_loop` 9 passed（新增运行时优先路径、特征过滤、非数值 422 三个用例）；已重建 backend 镜像并重启，容器内用用户真实部署模型（73 特征、ONNX、revision 路由）实测 runtime predict 返回 `[0]` + 概率，SMOKE 复核通过。**用户反馈缺列 422 → 预处理开关升级为特征工程算子（同日）**：用户上传原始报告 CSV 缺 59 个派生/波形统计列（current_ratio/power_*/spatter_*/current_mean 等）触发 DEMO_LOOP_RECORD_INVALID。按用户指示把「数据预处理」开关改为**自动特征工程算子**：缺列且开关开启时调用 `build_feature_frame`（spot_weld_features，报告 14 字段 + cvei/cvev/cver/cvep 波形 → 固定 73 特征 schema）逐行补齐派生列后再送运行时；失败时 422 明确列出所需报告字段与波形列；开关关闭时缺列提示引导开启开关或改用已做特征工程的数据集。前端开关文案同步为「自动特征工程（原始点焊报告数据 → 73 特征）」。测试：`test_demo_loop` 12 passed（新增特征工程补列、未开启开关引导、工程失败报所需列三个用例）。**用户再反馈开关未生效（同日）**：DB 实证 `preprocess_enabled=f`——界面打开开关但未点「保存配置」，predict 仍走未开启分支。处置：① 直接 UPDATE 用户配置置 true 立即解锁；② PUT 改用 `model_dump(exclude_unset=True)` 修复部分保存静默重置开关的隐患（+`test_13`）；③ 前端「开始演示」前自动 `validateFields`+保存当前表单（开关所见即所用），tooltip 注明生效规则；已重建 backend/frontend 并重启（health ok）。`test_demo_loop` 终态 13 passed。**独立大屏演示页（同日，用户要求"单独做一个非常炫酷的网页演示整个流程，要有各个节点和数据流动的效果"）**：新增单文件 `frontend/public/demo-showcase.html`（零依赖，构建时随 dist 发布，由前端容器直接服务 `/demo-showcase.html`，无需登录）：1600×900 自适应缩放舞台，Canvas 星空/网格背景 + 12 个发光节点（数据上传→逐行调用→特征工程→模型推理→分类判断；报错分支 错误回流→报错数据集(行数计数)→阈值监测→告警通知→人工审核(可选)→自动建模→模型替换）+ 贝塞尔边标签（正常·继续下一条/报错/达到阈值/最优模型/报错数据积累→触发重训/闭环·新模型上线）+ 拖尾粒子流动、节点脉冲、模型替换冲击波与版本徽标 v1→v2 翻转、HUD 计数缓动（已调用/正常/报错回流/告警/线上模型/预估准确率随换模型提升）、toast 事件叙事；控件：播放/暂停/重置/×1×2×4 倍速；**演示模式**（自动剧本：32% 报错率、每 5 行告警、积累 12 行触发 AutoML→换模型→准确率提升）与**实时模式**（填项目 ID+Token 轮询 `/api/projects/{id}/demo-loop/status`，真实事件映射为对应节点脉冲/粒子/HUD）。闭环演示页顶部新增「大屏动画演示」按钮直达；DemoLoopPage 测试 3 passed、weekAcceptance 10 passed、build 通过，frontend 已重建部署；浏览器实测截图两轮验收：首屏渲染/粒子流动正常，26 秒后告警 5 次、模型自动替换 v2、准确率 86.4%→89.7%、报错数据集 24 行——全闭环动画剧本自动跑通。**节点专属设计升级（同日，用户要求"每个节点都有单独的设计样式"）**：12 个节点各自独立造型与专属动效——数据上传（虚线环+云上传+顶部跑马灯）、逐行调用（终端窗口：红黄绿窗控点+`POST /predict {row}` 循环打字）、特征工程（旋转齿轮+`73F` 闪烁徽标）、模型推理（CPU 芯片带两侧引脚+金色内核脉冲）、分类判断（六边形剪影+SVG 描边+绿/红决策灯）、错误回流（粗红左边框+回旋虚线箭头）、报错数据集（数据库圆柱+等宽数字计数+5 格堆叠条）、阈值监测（SVG 仪表盘随积累进度填充）、告警通知（铃铛触发时摆动+红色告警计数徽标）、人工审核（清单+绿色对勾描画动画）、自动建模（双卫星轨道环绕+射线星标）、模型替换（金色循环换箭旋转）；全部边增加流动虚线动画，节点错峰入场。重建 frontend 后浏览器两轮截图验收：终端打字/芯片/六边形灯/计数条/铃铛徽标/v2 换模型全部生效。**重训阈值判断节点（同日，用户要求"自动建模节点前也需要有阈值判断"）**：新增圆形「重训阈值」节点（SVG 进度环 + `x / y` 计数，位于报错数据集→自动建模之间）：每条报错数据沿 e14 流入判定体，未达 `retrainAt` 沿 e16 虚线弹回报错数据集（"未达标 · 继续积累"），达标沿 e15 放行进入自动建模（"达标 · 触发建模"）；换模型后阈值重置为新周期（画面实证 13/25）；实时模式连接时读取真实配置 `retrain_threshold_rows` 驱动进度环。顺带修复告警判定竞态：告警改在回流落账瞬间判定（与后端 `error_count % threshold` 语义一致），粒子随后沿监测链流动——修复前粒子在途时判定可能被跳过（实证 6 行回流告警为 0，修复后 13 行正好告警 2 次）。**大屏实时模式升级与真实数据端到端验证（同日，用户问"能否连接真实数据"）**：实时模式升级为项目下拉框（`GET /api/projects` 拉取当前登录用户可见项目，记住上次选择）+ 自动读取同浏览器 `localStorage.token`；连接后轮询 status 并读取 config 的 `retrain_threshold_rows` 驱动阈值环。浏览器注入真实登录态端到端验收（项目"点焊"）：报错数据集 3 行、告警徽标 3、阈值环 3/12、连接绿点、事件驱动节点脉冲全部来自真实后端。修复三个真实数据问题：① 实时回放不再走随机分支（row_predicted → 仅视觉主链，ok 计数来自真实事件；error_row 与 error_appended 不再对同一行重复计数）；② 告警 HUD 同步真实 `alert_count`；③ 事件去重水位线不能用 UUID 字符串比较（无时间序，会随机跳事件）——改为"倒序列表遇水位线即停"。已知边界：后端事件流只返回最近 50 条，"已调用"反映可见事件窗口内的回放，报错/告警为权威计数字段；页面内直接 fetch 登录会被平台 CSRF 策略拦截，Token 需来自主界面登录（同浏览器自动读取）或手填。**方案A复现完整性核对与真实链路补验（2026-10-01，用户问"方案A是否已经全部复现"）**：六大环节此前均有实现，但两条链路只到桩测试级别——补写两个隔离库真实验证脚本（temp_test/verify_review_chain.py、verify_automl_chain.py，DATABASE_URL 指向临时 sqlite + 真实组件不复桩）。补验发现并修复 4 个真实缺陷：① **本地模式重训任务永不执行**（`LocalTrainingDispatcher.enqueue` 只登记，须显式 `start(task_id)` 才起线程；Celery 模式不受影响）——闭环服务补 `start` 调用 + `test_06` 增加 started 断言；② 闭环自动创建的实验编造 `mlflow_experiment_id`（"demo-loop-..."）→ AutoML worker `start_run` 找不到实验失败——改为经 `resolve_tracking_configuration` + `MlflowClient.ensure_experiment` 注册真实追踪实验（占位符 `pending-{uuid}` 避开全局唯一约束冲突）；③ 人工审核链路创建任务用 `draft` 状态被 `create_assignments` 状态机拒绝——闭环流程跳过手工 draft→发布步骤直接落 `awaiting_annotation`；④ `create_assignments` 以 UUID 集合做成员判断而配置存字符串恒不匹配——服务层转为 UUID。验证结论（隔离库）：审核链路真实标注员→任务(awaiting_annotation)→标签schema→样本范围→分配全落库；AutoML 全链真实 Optuna 搜索约 45s 完成→最优候选注册为模型版本→自动批准→部署直连替换（4ae3a493→505f12ca 等）→事件流完整。`test_demo_loop` 终态 14 passed（新增 test_14 审核链路回归）。**遗留注意**：本地 local 模式下受管 MLflow 文件后端被新版 mlflow 拒绝（`MLflow tracking unavailable`），local 模式重训需设 `MLFLOW_TRACKING_URI`/`MLFLOW_ARTIFACT_ROOT`（验证脚本已如此配置）；用户 docker 部署为 production 模式 + mlflow 服务，不受影响。backend 已重建部署（health ok）。改动未提交。**方案B实现（2026-10-01，用户指示"实现方案B"——工作流编排发布为 API 并按行调用）**：① 新增两个服务算子（`app/operators/serving_operators.py`）：`api_input`（接收 invoke 注入的单行记录，OperatorContext/DAGExecutor 新增 payload 透传）与 `load_model_artifact`（按制品 ID 加载冻结模型，支持模型库/AutoML dict 打包结构自动解包估计器并重序列化）；② 编排发布服务（`api_publication.py`）：`publish_workflow_version`（门禁=服务图形状：必须含 api_input+apply_model、禁止训练/搜索算子；幂等 unique(source_kind,source_id,version)）、`unpublish_workflow_version`（下线/暂停）、`sync_workflow_publication`（两条工作流删除路径接入，编排 API 自动下线）；运行记录门禁被有意省略——服务图含 api_input 在画布普通运行中必然失败，形状门禁+调用时校验才是有效约束；③ 同步调用运行时（`platform_api.py`）：`POST /api/platform/apis/orchestration/{version_id}/invoke`——加载冻结 workflow_version 快照 → payload 注入执行推理子图（拓扑序末节点为输出节点，condition 输出按命中分支取 records）→ 累计 total/success/failed 计数；④ 前端：画布顶部「发布为 API」按钮（保存→发布版本→注册编排 API 一气呵成，错误明细直出）；市场页编排类型徽标/筛选此前已预留零改动。测试：新增 `test_api_workflow_publication` 4 项（形状门禁/训练算子拒绝/发布幂等+双分支调用+计数+下线拒绝/删除同步下线），登记 week 17；`test_demo_loop` 14 + 新 4 = 全绿；前端 tsc/build + WorkspacePage/weekAcceptance 16 passed。**顺带修复共享算子真实缺陷**：`condition` 算子 `==/!=` 原按字符串比较，DataBus 往返把整数预测变成 float64（1→1.0）导致分支永远走错——改为数值列优先数值比较、文本列回退字符串比较。**真实环境 E2E（点焊项目）**：用部署 11 的真实模型制品（73 特征 XGBClassifier dict 包）建服务图 → 版本发布 → 编排 API 发布 → 逐行调用 branch=false、records=1、prediction=0.0（哑数据两类均判 0；true 分支在隔离测试断言覆盖）→ 市场列表 orchestration/published/调用计数 2。**环境插曲**：WSL VM 空闲自动关停导致整组容器被干净关闭（postgres "fast shutdown"），已放置 2 小时 keepalive 并全栈恢复；用户正常使用不受影响。改动未提交。**四项生产级补验全部完成（2026-10-01，用户指示"都做"）**：① **真实波形特征工程闭环**——`labeled1.csv`（101 行，91 列含 cvei/cvev/cver/cvep 真实波形）的真实行经闭环 predict（自动特征工程开启）→ 真实 `build_feature_frame` 补齐 73 特征 → 推理运行时出预测（prediction 0），全链真实数据通过；② **生产环境真实重训→换模型**——重训配置绑定原始训练集 `labeled_features.csv` + 目标列 `fault`，报错回流触发后 celery worker 接单、真实 Optuna 搜索 **50 秒完成**、最优候选注册为模型版本 e64dcb41 并批准、**生产部署 11 已实际切换到新模型**（可经模型注册表回退）；③ **审核门户体验**——`create_portal_session`（登录等价）签发 jing 会话，标注员门户队列可见「闭环演示-人工审核-4」（awaiting_annotation，4 样本，assignment 指向 jing）；④ **浏览器点击流**——localhost 域名登录（127.0.0.1 不在后端 CORS 白名单，报 CORS_ORIGIN_FORBIDDEN，非缺陷）→ 画布点「发布为 API」→ toast 确认 v2 发布 → 市场页 Orch. API 筛选可见 3 条编排 API（含 v1/v2 与调用计数）。**补验过程再修复 3 个生产级 bug**：(a) `_automl_dispatcher` 从错误模块导入 `CeleryTrainingDispatcher`（实际在 app/api/training.py）→ 生产 celery 模式重训触发必 ImportError；(b) 重训每轮复用同一实验 → `experiment_automl_bindings` 主键（experiment_id）第二轮冲突——每轮重训改用独立实验（名称含周期 error_count）；(c) 失败兜底在已回滚会话上写事件二次崩溃——兜底先 rollback。至此**方案 A 与方案 B 六大环节全部具备生产环境真实验证证据**。改动未提交。**API 市场删除操作（2026-10-01，用户指示"API市场添加删除操作"）**：删除按来源分权——自定义与编排 API 可在市场直接删除（编排 API 由重新发布幂等重建，清理测试残留正需要）；模型 API 保持禁止（由部署生命周期管理，删除按钮不显示）。后端 `delete_api` 放开 orchestration 来源 + 前端 Actions 列对编排行显示 DeleteConfirmation（确认气泡按可见 danger 按钮定位）。测试：后端 `test_05_delete_orchestration_api_allowed_model_forbidden`（编排 200 / 模型 409），前端市场页新增删除流测试 8 项全绿（含模型行隐藏编辑/删除断言）。**测试基建修复**：多模块同进程测试登录触顶登录 IP 限流（5/15min）→ conftest 设 `LOGIN_IP_RATE_LIMIT_CAPACITY=100`（组合回归 46 passed）。浏览器实测（localhost 登录→市场→删 planb-serving-ec0ee6 v1→确认气泡→行消失、总数 4→3、模型行无删除按钮）。backend/frontend 已重建部署。改动未提交。
- 2026-09-30：main CI 后端套件红→修复（Run [36655603398](https://github.com/FaceGg/Al-Platform/actions/runs/36655603398)，main `4b28501`，Quality Ubuntu/Windows 双双在 "Run backend suite" 失败）：唯一真实失败为 `tests.test_suite_manifest::test_every_backend_test_module_has_one_week_owner`——`17494b9` 新增的 `test_waveform_samples` 未登记周归属（discovered−assigned = {'test_waveform_samples'}）；CI 日志中的 `>>> test_fake: FAILED` 为 `test_run_suite` 失败上报探针的预期输出，非真实失败。修复：`week_manifest.py` 将 `test_waveform_samples` 登记到 week 17（标注门户模块组，与 `test_portal_internal_api` 同组）；该模块为 pytest 风格，`run_suite.detect_test_framework` 会自动选 pytest。本地验证（WSL `~/venv`）：manifest 门禁与 week11–12 归属用例 ok、`test_waveform_samples` 6 passed（venv 按 requirements 补装 pytest==9.1.1/httpx==0.28.*/minio 后）；两个 gated-stack subprocess 用例本地因 venv 缺 optuna 等可选 ML 依赖 environment-blocked，与本改动无关，以 CI 重跑为准。**CI 重跑实证（Run [36658560227](https://github.com/FaceGg/Al-Platform/actions/runs/36658560227)，SHA `3f14291`）**：首轮 Quality Ubuntu 全绿（backend suite 含周清单门禁通过）；Quality Windows 实际测试步骤全绿（backend suite/frontend tests/build/smoke），仅 setup-node/checkout 两个 Post 清理步骤启动即无声失败（日志无错误文本、无 timeout、无并发取消，判定 runner 基础设施抖动），`--failed` 重跑后 Windows 全绿；run 最终 conclusion=success（生产集成/Chromium/Week 11–12 在 push 事件按 workflow `if` 门控设计跳过，仅 schedule/手动 full 触发）。Task 14 已于 2026-09-26 收口（`completed`），本修复不改变该结论。

- 2026-09-29：门户浏览器返回键行为修复（审核工作区→评审任务列表、标注工作区→任务队列）：门户原为纯 state 切页（无路由、不写历史），浏览器返回直接退出应用。`App.tsx` 接入 History API：`navigate()` 同步 pushState/replaceState；`popstate` 按 URL（`?task=&assignment=`、`?page=adminQueue`）恢复页面（角色感知）；顶部导航与两个工作区的返回按钮统一走 `navigate`；深链（含管理平台 `?viewer=admin&task=` 跳转）进入工作区前先垫一条列表历史，返回键落在列表而非退出。测试：新增 2 个浏览器返回回归用例（jsdom history.back），App.test 的 `./api/tasks` mock 补齐 TaskWorkspacePage 依赖导出（vitest 对未 mock 导出访问即抛错并卸载整树）；annotator 前端 125 passed + tsc/build 通过，已部署 8443（bundle 含 popstate 处理）。改动未提交。

- 2026-09-29：删除阻断修复（用户复现：项目"点焊"删除 500、AutoML 任务删除 500）：根因同一处——`model_library.training_job_id → training_jobs.id` 是普通（NO ACTION）外键且可空，两条删除路径都未解除该引用（`DELETE /api/training/automl/jobs/{id}` 直接 ORM 删除；`_purge_project` 只在排序图中断开 model_library↔training_jobs 环，从未落地置空 SQL）。修复：① `training.py` 新增 `_detach_job_references`（置空引用该任务的模型库条目，注册模型本身保留）并接入 automl 删除；② `_purge_project` 在删除前对断环列执行 UPDATE ... SET NULL。③ 测试加固：SQLite 默认不校验外键（本地/测试与 postgres 行为分叉，两个 bug 均未被现有测试覆盖）——新增 `ML_PLATFORM_SQLITE_FOREIGN_KEYS` 开关（应用默认不变）并接入 conftest 与 run_suite 子进程环境，使测试与生产外键语义一致；新增回归 `test_14_delete_project_with_circular_model_library_reference`、`test_automl_delete_detaches_registered_model_reference`。测试：projects 14 / automl_tracking 66（含 subtests）/ datasets 19 / training 11 / annotations 17 / concurrency 26 / portal 84 / experiments 11 / model_library 12 在外键强制下全过；unittest runner 路径亦验证通过。WSL 部署实证（postgres）：用户的 AutoML 任务 c743a24b 删除返回 200、任务行消失、两条模型库记录保留且 training_job_id 置空；带环形引用的临时项目删除返回 204 且 project/job/model/experiment 全部清空（未删除用户"点焊"项目本身——该操作会清空项目全部数据，留给用户自行点击）。改动未提交。

- 2026-09-29：门户波形区两列布局与宽度适配：`.waveform-channels` 改为 `repeat(2, minmax(0,1fr))` 两列（四个通道两行显示），移除此前 480px 限宽以适配页面宽度，≤960px 单列回退；SVG 随列宽等比缩放。annotator 前端 123 passed + tsc/build 通过。**部署插曲（环境问题）**：`docker compose build annotator-frontend` 静默失败——WSL 内 docker 走代理 `127.0.0.1:7897`（当前不可达）解析 `nginx:1.27-alpine` 元数据超时，而基础镜像本地已被清理，故镜像未更新、容器继续服务旧产物；且 `... | tail -1 &&` 管道掩盖了退出码。已用本地 `nginx:alpine` 经临时 Dockerfile（/tmp，非仓库文件）重建同名镜像并 `up -d --force-recreate --no-build` 恢复部署，实测服务新产物（`index-BJXGhFIi.css` 含两列规则、`index-iXPHt1JW.js`、portal 200）。注意：当前门户镜像基础版本为 nginx 1.31.6（临时基线），代理恢复后执行一次 `docker compose build annotator-frontend` 即回归仓库锁定的 `nginx:1.27-alpine`。

- 2026-09-29：自动建模任务"排队中"卡死修复（用户环境实证 bc576aca）：① 派发/认领竞态——`_dispatch_job` 原先先投递 celery 任务再提交 queued 状态，空闲 worker 毫秒级认领时行尚不可见（`skip_locked` 查询返回空），执行器 3ms 内返回 skipped，而周期恢复任务只处理 running/cancel_requested，无人补派 → 任务永久"排队中"（worker 日志与 DB 双证据）。修复：先提交 queued 再投递（`training.py`）。② 自愈：`reconcile_stale_training_jobs` 增加对 pending/queued 且无活跃 celery 任务、超过 `training_redispatch_after_seconds`（新配置，默认 60s）的任务补派，心跳时间戳兼作限流；`training_tasks.py` 消费 `redispatched_job_ids`；活跃检测扩展 active+reserved+scheduled（避免繁忙 worker 下重复投递噪声）。测试：recovery 11 + tasks/automl_tracking 82 + training/automl_search/catalog 24 全过（`test_training_recovery` 已在周清单登记，新增 4 用例覆盖补派/限流/在途保护）。WSL 已重建 backend+worker 并重启 frontend；实证：卡死任务 bc576aca 被恢复任务自动补派（`redispatched:1` 日志）并正常训练中；新建任务 15c930dd 全程 queued→running→completed 15s（修复前必现卡死），验证数据已删除。另注：期间一次后台测试运行出现 85 分钟异常挂起，复跑 recovery+tasks 9.6s 稳定通过，判定为一次性环境抖动。改动未提交。

- 2026-09-29：项目删除级联重建 + 工作台数据集计数修正（用户环境复现"项目删除失败、工作台数据集个数不符"）：① 旧 `delete_project`/`batch-delete` 仅手工清理 5 类表，而 31 张表外键指向 projects（WSL postgres 实测全部 CASCADE/SET NULL，仅 `model_library` NO ACTION 直接阻断），任何带数据的删除都 500；重构为 `_purge_project`：由 SQLAlchemy 元数据运行时推导全部传递依赖表、Tarjan SCC 断环（可空环边置 NULL，如 model_library↔training_jobs）、子表在前拓扑序 Core 批量删除（绕过冻结数据集 ORM 事件，属项目删除硬边界；datasets/orchestration_apps/audit_events 按 SET NULL 语义脱钩保留；artifact 存储文件成为孤儿为已知限制）。开发中发现首版拓扑序写反（父先于子）导致传递子表漏删，测试捕获后修正为子表在前。② 工作台 `total_datasets`/`total_samples` 对齐数据管理列表口径（排除 archived 与 normalized 内部产物）。测试：新增 `test_13_delete_project_cascades_dependent_records`；projects 13/datasets 19/dashboard 8/labeling 8 passed（隔离库）。**事故记录**：直接 `pytest tests/test_api_*` 未设 `DATABASE_URL`，这些模块使用全局 engine，把测试项目/数据写入真实开发库 `backend/ml_platform.db`（28 个测试项目、3207 孤儿样本、孤儿 label_columns/schema_columns 等）；已用 `_purge_project` 脚本 `cleanup_test_projects.py`（已删除）全部清除并逐表核验（用户数据 spot_weld_quality_samples 120 完好，audit_events 2125 按设计保留）；后续此类模块必须经 run_suite 或显式 `DATABASE_URL` 隔离运行。WSL backend 已重建部署，实测：dashboard 与数据列表计数一致（0/0）、临时项目"上传→计数 1→删除 204→404→计数 0"全链路通过。改动未提交。

- 2026-09-29：数据集删除引用检查排除已归档任务：任务删除是软归档（`archived_at`），但 `DELETE /api/datasets/{id}` 的 `DATASET_IN_USE` 检查（`datasets.py`）未排除已归档的通用标注任务，导致"任务已删除"后数据集永远报 409（用户实测 unlabeled.csv 复现）。修复为仅统计 `archived_at IS NULL` 的任务；新增回归 `test_03c2_delete_allows_dataset_used_only_by_archived_task`（`test_api_datasets.py` 19 passed）。WSL 部署重建 backend 并重启 frontend（nginx IP 缓存）；用真实 unlabeled.csv（67c6b78b）端到端验证：DELETE 204、列表不再显示（软删除可经 `/api/datasets/{id}/restore` 恢复）。另：批量编辑列表样本显示由完整 UUID 改为"第 N 条 · 短ID"（编号与工作区跳转/进度同语义，TaskWorkspacePage.tsx，annotator 前端 123 passed，已部署）。改动未提交。

- 2026-09-29：标注员门户会话 cookie 作用域收紧（本地部署缺陷修复）：门户 cookie（`portal_session`/`admin_portal_session`）原先 `path="/"`，而 cookie 按域不按端口隔离，同机 `localhost:5173` 主平台登录请求会带上门户会话 cookie，触发平台 cookie-CSRF 策略返回 `CSRF_TOKEN_REQUIRED`（r12 使 HTTP 门户 cookie 可存储后暴露）。`annotator/backend/app/services/session.py` `cookie_options()` 的 path 收紧为 `/portal`（门户全部路由均在该前缀下，平台侧 `annotator_internal.py:91` 的 Set-Cookie 仅服务间使用不动）。验证：annotator 后端 31 passed；WSL 部署重建 annotator 并连带强制重建 annotator-frontend（nginx 上游 IP 缓存，重建 backend/annotator 后必须重启对应 nginx 前端容器，否则 502）；真实登录返回 200 且 `Set-Cookie: ...; Path=/portal`；探测矩阵确认带旧 cookie 的主平台登录被 CSRF 拒绝、无 cookie 时 200。既有浏览器中旧 `path=/` cookie 需一次性手动清除。改动未提交。

- 2026-09-29：手动标注任务波形显示（cvei/cvev/cver/cvep）：新增服务 `app/services/waveform_samples.py`，按 base64→大端 int16→float64 规范解码波形列（2320 字符 base64→1740 字节→870 个采样点）；`GET /api/internal/portal/tasks/{id}/samples`（`annotator_internal.py`）对含波形列的样本返回 `items[].waveforms`（current/voltage/resistance/power，与质量报告通道语义一致）并从 `values` 隐藏原始 base64 串；无波形字段或解码失败的样本保持原返回形状（含逐字段精确断言）。标注员门户标注工作区新增 SVG `WaveformChart`（四通道、悬停读数、无新前端依赖）并在 `SampleStream` 集成。验证：真实 unlabeled.csv（项目 test 上传数据，101 行×4 通道）端到端解码与独立 struct 解析一致；后端 `test_waveform_samples` 6 passed、`test_portal_internal_api` 84 passed（含 2 个新波形用例）、genericization 生产源码门禁通过（新模块措辞避开 legacy 字样）；相邻模块 test_portal_admin_review / test_api_annotations / test_api_labeling 通过；标注员后端 31 passed；标注员前端 Vitest 123 passed、tsc、build 通过；全量 run_suite 本机再次在 Week 12 安全模块触发已记录的 300 秒阈值退出，该模块直跑 158 passed + 1 skipped + 1 例 StopIteration 偶发（单测重跑 passed），其后模块本轮 not_run（改动未触及）。用户实际运行环境为 WSL docker compose（主前端 5173、门户 8443，backend 8001→8000，代码随镜像打包）：已重建 backend/annotator/annotator-frontend 镜像并重启（数据卷未动），容器内实测 `decode_sample_waveforms` 就位、门户 bundle 含波形组件（`index-NyVPfHpa.js`），并对真实任务"点焊手动标注任务"（awaiting_annotation）经运行中 `/api/internal/portal/tasks/{id}/samples` 验证：返回 4 通道 × 870 点 waveforms 且原始 cvei 已从 values 隐藏（验证脚本 `tmp/verify_portal_waveforms.py`）；已 cancelled 的旧任务按现行为不可再读取（404）。

- 2026-09-24：归档本文件压缩前的完整历史，新增 Week 13–17 详细开发计划和实施计划索引；当前文档只保留最新状态、依赖、门禁、风险和归档入口。Week 13–16 保持 planned，Week 17 保持 pending_decision；没有因整理文档提升任何实现状态。
- 2026-09-28：起草多模态标注平台集成（Label Studio）技术方案与实施计划（独立立项）；同日决策评审：D1 用户决定暂缓，轨道转 `deferred`（§4.3）；D2–D8 结论归档、条件生效，重新立项需用户明确指示，不自行启动。
- 2026-09-29：Week 14 实现 WIP 暂存（用户指示暂停）：模型 + 迁移 `20260928_63`、客户端作业面与确定性 manifest 生成器、executor（幂等提交/终态守卫/取消/对账/日志）、`/api/kubernetes/jobs` 端点已写入并注册；compileall/导入/Week 13 聚焦测试 37 passed 无回归。未完成：测试 4 模块、celery 包装、前端 JobRunsPage、清单登记、kind 作业 smoke——恢复时按 [Week 14 实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week14-kubernetes-executor.md) 从 Task 14.1 RED 测试开始；迁移 head 现为 `20260928_63`（未推送，远端仍 `20260928_62`）。
- 2026-09-29：Week 13 收口完成：首轮远端 CI 失败（`test_database_production` 的 HEAD_REVISION 仍断言 `20260926_61`）——同步 5 处 head 常量后重推，run 36504250668 双平台 Quality 全绿（绑定 `ff82e0f`）。Week 13 转 `completed`；发布级验证工作流（Production integration、Chromium acceptance、Week 11-12 verification）属 Week 11-12 发布收据范畴，随后续发布收据运行。全量 run_suite 本机在 Week 12 安全模块触发已记录的 300 秒阈值退出，直跑 159 passed，与 2026-09-24 记录一致。
- 2026-09-28：Week 13 浏览器与验收收口：已认证 Playwright 流程 1 passed（真实 kind 集群：登记→连通性→节点表，截图证据）；`run_week13_17_acceptance.sh` Week 13 profile 建成，OVERALL passed（8 步全绿 manifest 绑定 SHA）。Week 13 唯一余项为远端 CI 收据。
- 2026-09-28：Week 13 本地实现推进：Task 13.0–13.5 完成并全部门禁绿（后端 37 passed、`run_suite --week 13` 3/3、alembic upgrade head `20260928_62` + check、前端 368 passed/tsc/build）；Task 13.6 kind v0.34 + K8s v1.37.0 真实集群 smoke 12/12 PASS（修复 5 个实现缺陷：`kubernetes.config.Configuration` 不存在、`_request_timeout` 元组、配额键翻译、`app/operators/optimization.py` sys.path 污染遮蔽 websocket 包、软删集群占用唯一键改部分唯一索引）。Week 13 状态转 `in_progress`；余项：Playwright 浏览器流程、验收收集脚本、远端 CI 收据。
- 2026-09-28：新增 Week 13–17 各周技术方案（评审稿）与实施计划；Task 0 的 Week 13 子集五项决策收口（§4.1）；Week 17 七项范围决策获批（§4.2），状态由 `pending_decision` 转为 `planned`；Week 13–17 计划迁移修订号顺延（Week 13 `_62`、Week 14–17 `_63`–`_66`）。Week 13–16 状态保持 planned 不变。
- 后续每个周次完成后，先绑定当前 SHA 和实际证据更新本台账，再把详细执行记录追加到新的日期归档；不得用计划文本、历史测试或旧收据宣称完成。

## 9. 合并自 origin/main 的历史执行记录（2026-09-24）

> main 在本分支创建后新增的 Ubuntu 安装包、HTTP 兼容性和历史验收记录保留在本节；前面的当前状态台账仍是本文件的权威入口。

### 2026-09-28 门户 HTTP 登录会话丢失：Secure cookie 硬编码（r12）

- 现象：外网（非 localhost）通过 `http://10.12.18.6:8443` 登录门户，接口返回 200 但会话立即丢失——服务器日志呈 `POST /portal/auth/login 200 OK` 紧跟 `GET /portal/auth/me 401` 循环；本地 localhost 登录正常。
- 根因：`ml-platform/annotator/backend` 的 `cookie_options()` 与 logout 硬编码 `secure=True`。浏览器按规范丢弃经非安全传输（非 localhost 的 HTTP）下发的 Secure cookie，导致登录成功但浏览器未保存会话。
- 修复：新增 `ANNOTATOR_COOKIE_SECURE` 配置（默认 `true`），`cookie_options()` 与 logout 删除 cookie 统一走该开关；`docker-compose.yml` 的 annotator 服务注入该变量；`install-ubuntu.sh` 对新装与升级部署都写入 `ANNOTATOR_COOKIE_SECURE=false`（Ubuntu 安装包按纯 HTTP 部署设计），HTTPS 反代场景可改回 `true`（提交 `248a1b3`）。
- 验证：annotator backend `31 passed`（新增回归：`ANNOTATOR_COOKIE_SECURE=false` 时 cookie 不带 Secure 仍带 HttpOnly/SameSite）；`bash -n` 语法检查通过（仓库 blob 为 LF）。
- 发布记录（2026-09-28）：安装包 `output/linkraft-ubuntu-20260926-r12.tar.gz`，manifest 绑定 HEAD `1f4d87f`，SHA-256 `16cf3654723b9380da264ff77cda4df8c3cd1db789403695ab900015141b8f8b`，归档抽查确认 cookie 开关代码与安装脚本均已包含。更正一：首个 r12 归档（SHA-256 `8ac6d972...b182b`）的 `install-ubuntu.sh` 因 Windows 工作区覆盖带入了 CRLF 行尾，在服务器报 `/usr/bin/env: bash\r`；`build-package.sh` 已增加打包前 LF 归一化。更正二：第二个归档（SHA-256 `77061681...56e29`）的安装脚本在 `set -u` 下引用未声明的 `ANNOTATOR_COOKIE_SECURE` 报"未绑定的变量"；已在脚本头部补默认声明并重建。前两个哈希均作废，服务器现场可用 `ANNOTATOR_COOKIE_SECURE=false ./packaging/install-ubuntu.sh` 绕过。
- 待完成：目标服务器部署 r12 后外网登录 8443 并保持会话的端到端确认；外网 5175 的 `CORS_ORIGIN_FORBIDDEN` 与本地 5175 的对偶问题需用 `PUBLIC_ORIGIN`/`PUBLIC_ORIGIN_ALIASES` 收敛（运行时配置，无需发版）。

### 2026-09-26 标注员门户误报“质检反馈/需重做”（r11）

- 现象：标注员修改标签并重新回传后，任务列表显示质检反馈横幅和“需重做”徽章——但任务是正常等待验收，并非审核退回。
- 根因：`TaskCard` 的 `FEEDBACK_STATES` 把 `returned_pending_acceptance`（每次回传后的正常等待验收状态）与 `edit_for_return`（审核退回）一起算作质检反馈状态；`isFeedbackTask` 还把 `task.status === 'returned_pending_acceptance'` 也计入。
- 修复：`FEEDBACK_STATES` 收敛为 `['edit_for_return']`，“需重做”徽章与质检反馈横幅只在审核真正退回后出现（提交 `fad3723`）。
- 验证：审核员门户全量 `118 passed`（新增回归：待验收任务不显示横幅/徽章、`isFeedbackTask` 仅对 `edit_for_return` 为真）；`tsc --noEmit` 通过。
- 发布记录（2026-09-26）：安装包 `output/linkraft-ubuntu-20260926-r11.tar.gz`，manifest 绑定 HEAD `e2d2779`，SHA-256 `e72e5bd3ea22898facc540251a5a6e592992a788830f73e7b7736690b680daae`，归档抽查确认修复代码已包含。r11 同时包含 r10 的回传死锁自愈。
- 待完成：目标服务器端到端验收（SQL 解锁 → 重新回传 → 冻结 completed → 合格验收，且任务列表不再误报需重做）；提交尚未推送（本地 main 领先 origin 15 个提交）。

### 2026-09-26 回传死锁自愈：冻结失败后允许重新回传（r10）

- 现象：部署 r9（列宽迁移已生效）后审核员验收仍报 `RETURN_BATCH_NOT_READY`。服务器证据：`durable_operations` 无新记录，只有两条 09-25 的 `failed` 旧操作——旧批次是终态，验收/退回均被 `_require_completed_frozen_batch` 挡住。
- 已验证根因（死锁）：`return_assignment` 在创建批次时同步把 assignment 锁进 `returned_pending_acceptance`；冻结失败后批次停留 `pending`，审核端 accept/reject 都要求冻结完成，标注员重新回传又被 assignment 锁拒绝（`AssignmentLockedError`）——无任何设计内恢复路径。
- 修复：`return_assignment` 遇到 `returned_pending_acceptance` 锁时，若该 assignment 的 pending 批次冻结操作全部 `failed`（或缺失 operation），放行重新回传，旧批次由既有 supersede 逻辑自动清理（提交 `a6128d1`）。
- 一次性运维：升级到 r10 前已卡死的 assignment，用 SQL 解锁 `UPDATE annotation_assignments SET state='pending' WHERE state='returned_pending_acceptance' AND id IN (SELECT assignment_id FROM annotation_return_batches WHERE state='pending')`，之后标注员重新回传即可（README 已收录）。
- 验证：`test_annotation_concurrency.py` 26 passed（含两个新回归：失败冻结后可自愈重新回传、运行中操作仍锁定）；回传/审核员套件 47 passed。
- 发布记录（2026-09-26）：安装包 `output/linkraft-ubuntu-20260926-r10.tar.gz`，manifest 绑定 HEAD `d282673`，SHA-256 `8c0c33ae7bda8c9708b0ec754291cc672a630a8eb763f2516172b90c1f484962`，归档抽查确认自愈代码已包含。
- 待完成：目标服务器执行 SQL 解锁 + 标注员重新回传 + 审核员验收的端到端确认；提交尚未推送（本地 main 领先 origin 12 个提交）。

### 2026-09-26 回传验收 409 真根因：任务状态列宽不足 + 框架错误码泄漏（r9）

- 现象：部署 r8 后回传验收仍报 `409 RETURN_BATCH_NOT_READY`，与本地工作树行为不一致。
- 已验证根因：`generic_annotation_tasks.status` 为 `VARCHAR(24)`，回传冻结 worker 写入 `returned_pending_acceptance`（27 字符）触发 PostgreSQL `StringDataRightTruncation`，回传校验操作全部 `failed`（服务器 `durable_operations` 两行证据，`error_details` 含完整 SQL）。SQLite 不强制 VARCHAR 宽度，因此测试与本地开发从未暴露；"工作树正常"的印象来自非 PostgreSQL 路径，工作树库同样存在 `VARCHAR(24)`。次级缺陷：`fail_operation` 的 `getattr(error, "code", ...)` 误取 SQLAlchemy `DBAPIError` 内部 `code` 属性，持久化为乱码 `9h9h`，掩盖真实错误。
- 修复：模型 `status`/`paused_from_status` 加宽至 `String(32)`；新增 alembic 迁移 `20260926_61`（仅 PostgreSQL 执行 `ALTER COLUMN ... TYPE VARCHAR(32)`，幂等守卫）；`annotation_return_tasks.domain_error_code` 只接受 UPPER_SNAKE 域码，其余回退 `ANNOTATION_RETURN_FAILED`。
- 验证：定向套件 `93 passed`（回传验收 + 状态机 + 迁移图）+ 回传/操作选择器 `28 passed`；alembic 全链 `upgrade head` 在 SQLite 干净通过至 `20260926_61`。新回归测试：状态值必须适配模型列宽、`domain_error_code` 拒绝框架内部码。
- 发布记录（2026-09-26）：提交 `ef0cb8d`（列宽 + 错误码修复）与 `6e0c855`（r9 打包配置）。安装包 `output/linkraft-ubuntu-20260926-r9.tar.gz` 已构建，manifest 绑定 HEAD `6e0c855`，SHA-256 `76c79d2b5fc71c90bcadcbc56e9076c61c41ca905c06a2b9b5c2eeeca3875732`。升级时 `migrate` 容器自动执行加宽迁移；升级前已 `failed` 的两条回传操作不会自动恢复，需标注员重新回传。
- 待完成：目标 Ubuntu 部署 r9 后确认迁移生效（列宽 32）并完成一次完整回传→验收；提交尚未推送（本地 main 领先 origin 8 个提交）。

### 2026-09-25 回传验收 409：异步冻结校验未完成时前端误触发验收链路

- 现象：标注员回传后，主平台打开回传卡片可能出现 `Request failed with status code 409`，审核员门户点击验收返回 `RETURN_BATCH_NOT_READY`。
- 已验证根因：回传批次先落库为 `pending`，由 worker 异步生成不可变快照；在 durable operation 仍为 `queued/running` 时，差异和验收接口按安全契约拒绝请求。主平台的查看摘要路径仍请求差异接口，审核员门户只判断存在 pending 批次，未判断校验操作状态。
- 修复：审核员任务列表/详情返回 `return_operation_state`、失败码和已校验样本数；主平台回传验收/数据管理列表在校验完成前不请求差异、不显示验收/退回按钮；审核员门户仅在操作 `completed` 时开放验收、退回和批注，并显示排队/校验中/失败状态。保留后端 `RETURN_BATCH_NOT_READY` 守卫。
- 验证：回传后端定向套件 `43 passed`；主平台回传组件 `14 passed`；审核员门户全量 `116 passed`；两端 TypeScript/生产构建通过。目标 Ubuntu 的 worker/Celery 实际执行及浏览器验收仍需用新包部署验证。
- 发布：源码安装包需在本次改动后重新生成并绑定新的 manifest/checksum，部署后先确认 worker 日志和批次 operation 从 `queued/running` 进入 `completed`，再进行验收。
- 发布记录（2026-09-26）：修复已分两个提交落库——`dc09b5e`（worker 地址空间限制延后，XGBoost ONNX 注册修复）与 `578aa66`（回传验收 UI 门控 + r8 打包配置）。安装包 `output/linkraft-ubuntu-20260925-r8.tar.gz`（2.5M）已构建，manifest 绑定 HEAD `578aa66`，SHA-256 `e8ffb9323ffe70f6a05ccf34ee0b0c911f144324ab90e810cb13c142538d3f04`；归档抽查确认回传门控与 worker 修复代码均已包含。目标 Ubuntu 部署 r8 后的 worker 实际执行与浏览器验收仍待完成；提交尚未推送（本地 main 领先 origin 5 个提交）。

### 2026-09-25 AutoML XGBoost 注册：延后 Linux 地址空间限制并重新打包 r7

- 现象：任务 `087b597f-19a0-4d81-88c0-ca14b2d73b71` 的 XGBoost joblib 制品大小和 SHA-256 均匹配，`XGBClassifier` 在 backend 容器内直接调用 `convert_xgboost` 成功，但注册接口返回 `MODEL_CONVERSION_FAILED`。
- 已验证根因：ONNX 转换 worker 在导入 `onnx_cpp2py_export` 等可选二进制扩展之前设置 `RLIMIT_AS=5298810880`；受限子进程报 `failed to map segment from shared object`，随后只返回稳定的通用错误码。
- 修复：worker 启动时只设置 CPU 时间限制；模型族对应的 ONNX/XGBoost/LightGBM/CatBoost 二进制依赖加载完成后，再设置地址空间上限并执行转换。保留原有转换白名单、超时和非 root 运行边界。
- 验证：回归测试先失败后通过；`tests.test_onnx_conversion` 为 12 tests OK（Windows 跳过 POSIX 资源限制用例）；模型注册服务/API 为 29 tests OK。目标 Ubuntu 容器需用新包重建 backend/worker 后重新执行实际注册。
- 发布：源码安装包升为 `linkraft-ubuntu-20260925-r7.tar.gz`，继续保留 CPUv1 MinIO、5175/8443、公网 CORS、源码构建和密钥引导约束。

### 2026-09-25 Ubuntu 安装包 r6：采用目标 CPUv1 镜像的 HTTP readiness 健康检查

- 现象：目标服务器确认 MinIO server 使用 `linux/amd64` 正常监听 9000/9001，但 r4 的 `mc ready local` 检查报 `mc: executable file not found`；目标部署提供的正确 Compose 使用 MinIO HTTP readiness endpoint。
- 修复：legacy Compose 将 MinIO healthcheck 对齐为 `curl -fsS http://127.0.0.1:9000/minio/health/ready`，增加 30 秒启动宽限期，并让 `minio-init` 继续依赖 `service_healthy` 后执行 alias 和建桶。安装包升为 `20260925-r6`。
- 兼容边界：仅更新 legacy CPU 发布 profile；保留 Debian Python 镜像、CPUv1 tag、5175/8443 端口、源码构建和上传目录权限修复，不把主线 Compose 的 ghcr.io MLflow 或端口默认值带回发布包。
- 验证边界：健康检查合同先失败后通过；合并 Compose、脚本语法和 r6 归档需绑定最终包。目标服务器需重建 MinIO/init 容器并确认 `minio-init` 成功退出、下游服务健康。

### 2026-09-25 Ubuntu 安装包 r5：CPUv1 MinIO 镜像不含 mc 导致健康检查失败

- 现象：目标服务器上的 `minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1` 进程正常启动并监听 9000/9001，但容器状态为 `unhealthy`；健康检查日志为 `exec: "mc": executable file not found in $PATH`。
- 根因：legacy CPUv1 MinIO server 镜像不包含 `mc` 可执行文件，而主线 Compose 的 `mc ready local` 健康检查会被合并继承到该容器。
- 修复：legacy Compose 对 MinIO 禁用继承的内部 `mc` 健康检查；由包含 `mc` 的 `minio-init` CPUv1 容器在 `service_started` 后执行 alias、ready 和建桶重试，完成后再放行所有依赖服务。安装包升为 `20260925-r5`。
- 验证边界：新增合同先失败后通过；Compose 合并配置和脚本语法通过。目标服务器需用 r5 重建 `minio`/`minio-init` 并确认 `minio-init` 成功退出、后端健康和上传流程。

### 2026-09-24 Ubuntu 安装包 r4：上传临时文件目录权限

- 现象：服务器部署后上传数据集返回 500，backend 日志在 `_stage_upload_sync` 写入 `/app/app/uploads/<uuid>_...` 时抛 `PermissionError: [Errno 13] Permission denied`。
- 根因：backend 镜像以 UID/GID `1000:1000` 非 root 运行；Compose 的宿主机 bind mount `./ml-platform/backend/uploads:/app/app/uploads` 会覆盖镜像构建阶段已经 `chown` 的目录，目标机解压/首次创建的宿主目录通常属于 root，导致应用不能创建临时文件。
- 修复：新增 `packaging/prepare-production-storage.sh`，使用已构建 backend 镜像临时以 root 修复 bind-mounted `data/` 与 `uploads/` 的 UID/GID；安装脚本改为先 build、修复存储、再启动，并提供已有部署的单独修复命令。安装包升为 `20260924-r4`。
- 验证边界：新增权限合同先失败后通过；脚本语法、Compose 配置、数据集上传定向回归和 r4 归档检查需绑定最终包。目标 Ubuntu 重新部署后需实测上传成功、已有文件可读和容器保持 UID/GID 1000。

### 2026-09-24 Ubuntu 安装包 r3：私网 HTTP 标注页空白与 8443 门户外网入口

- 现象：通过 `http://SERVER_IP:5175/data-annotation?view=tasks` 打开数据标注页时页面空白；`http://SERVER_IP:8443/` 从外部机器无法连接。
- 根因：私网 HTTP（非安全上下文）中 `crypto.randomUUID()` 不可用，`DataAnnotationPage` 初始化自动标注策略时直接抛 `TypeError`，React 根节点保持空；legacy CPU Compose 将 `annotator-frontend` 默认绑定在 `127.0.0.1:8443`，因此 8443 仅本机可见。
- 修复：主平台和标注员门户前端均新增 `utils/uuid.ts`，优先使用 Web Crypto，缺少 `randomUUID` 时生成 RFC 4122 v4 UUID，并替换请求/标注/回传 ID 生成点；legacy CPU Compose 和安装脚本将 `ANNOTATOR_BIND_ADDRESS` 默认设为 `0.0.0.0`，保留通过 `.env` 改为本机绑定的能力。Ubuntu 手册补充 8443 防火墙、CORS 和 nginx 上游重启说明，安装包升为 `20260924-r3`。
- 验证边界：前端 UUID/页面回归、Python 合同测试、Compose 合并配置、脚本语法和源码归档检查绑定 r3；目标 Ubuntu 全栈重建、8443 外网登录和 MinIO CPUv1 拉取仍需在目标服务器部署 r3 后验证。

### 2026-09-24 Ubuntu 安装包 r2：公网入口 CORS 源配置

- 现象：通过 `5175` 或直接 `5173` 登录时返回 `CORS_ORIGIN_FORBIDDEN`。
- 根因：生产 Compose 的 backend 环境未注入 `FRONTEND_ORIGIN`，后端始终使用 `http://localhost:5173` 默认值；生产模式也不会自动把服务器 IP、`localhost` 和 `127.0.0.1` 视为同源。
- 修复：Compose 将 `FRONTEND_ORIGIN`/`FRONTEND_ORIGIN_ALIASES` 传入 backend；安装脚本支持 `PUBLIC_ORIGIN` 和逗号分隔的 `PUBLIC_ORIGIN_ALIASES`，对已有 `.env` 只更新显式指定的 Origin。安装包版本更新为 `20260924-r2`。
- 使用：公网安装时执行 `PUBLIC_ORIGIN=http://SERVER_PUBLIC_IP:5175 ./packaging/install-ubuntu.sh`；修改已有部署后必须 `--force-recreate backend`。
- 验证：新增 CORS 配置合同先失败后通过；Compose 解析、脚本语法和归档敏感路径检查需绑定 r2 最终包；目标 Ubuntu 的真实登录仍需在目标地址验证。

### 2026-09-24 Ubuntu 安装包 r1：标注前端改为源码构建

- 现象：旧 CPU 安装包启动构建时，`annotator-frontend` 的 Dockerfile 执行 `COPY dist /usr/share/nginx/html`，目标机提示 `/dist: not found`。
- 根因：`dist/` 是被 Git 忽略的前端构建产物，源码包按设计不携带它；legacy CPU Compose 覆盖未替换标注前端的主线 Dockerfile。
- 修复：新增 `ml-platform/annotator/frontend/Dockerfile.legacy-cpu`，使用 Node 20 Debian 多阶段构建并复制构建阶段产物；legacy CPU Compose 为该服务指定 Dockerfile、host 网络和可配置 npm 镜像。安装包版本更新为 `20260924-r1`。
- 验证：专用合同回归先失败后通过；合并后的 Compose 配置通过；WSL Docker 实际构建 `annotator-frontend` 镜像通过。目标 Ubuntu 全栈启动、健康检查、外网访问和 CPUv1 MinIO 镜像可获取性仍需在目标服务器验证。

### 2026-09-23 full CI Run 35848118822 安全门禁修复

- 现象：提交 `bb03dddfafb026a9937cec1155e361ed815aed53` 的 full CI 中，Quality、Production integration、Production experiment integration 和 Chromium acceptance 均通过；Week 11–12 verification 最终失败。
- 根因：Trivy 对四个生产镜像安装的 `python-3.11=3.11.16-r1` 报告 HIGH `CVE-2026-7210`，报告给出的修复版本为 `3.11.16-r7`。安全汇总器将非 Web 扫描证据统一判为 `SECURITY_EVIDENCE_INVALID`；扫描与汇总之间的隔离栈 Compose 会按默认配置在仓库内创建 `ml-platform/backend/mlflow-wheel` 绑定目录，改变 Gitleaks 已绑定的源树摘要。
- 修复：四个 Dockerfile 和 `.github/contracts/python-base-image.json` 将 Python 固定版本升级为 `3.11.16-r7`，镜像合同测试同步；Week 11–12 verification 将 `MLFLOW_WHEEL_DIR` 指向 `${{ runner.temp }}/mlflow-wheel`，让 Compose 的宿主机绑定目录留在工作区之外。
- 当时状态：本地合同验证和新 SHA 的远程 full CI 待本轮完成；Run `35848118822` 仍绑定旧 SHA，不能作为本次修复通过证据。
- 后续验收记录：GitHub Run `35855270973` 第 2 次尝试于 2026-09-23 通过，六个作业全部成功；Week 11–12 证据清单 `passed`，绑定提交 `4a3c639d9ef34fe4962e873ec277f516b660d586`。四个生产镜像的 Trivy HIGH/CRITICAL 门禁和安全汇总通过，Python CVE `CVE-2026-7210` 未再出现在镜像报告中。
- 性能重跑：首次尝试同一 SHA 的 `warm-inference` 第 1、3 轮 P95 为 202.02/205.10 ms，略高于既有 200 ms 门槛；第 2 次尝试三轮为 195.60/175.78/191.80 ms，错误率均为 0。门槛未调整；首轮轻微超限未在同 SHA 重跑中复现，超限原因尚未证实。
- 后续 push Run `35863495070`（记录提交 `3318c51287be6b7fc56fbf0641254d3fb6fc9758`）：Windows 质量作业和 Ubuntu 后端套件通过；Ubuntu 前端测试在 `AnnotationCommentModerationPanel.test.tsx` 失败。失败快照同时显示 `offline` 告警和 accessible name 为 `loading 加载更多` 的分页按钮；测试在错误告警出现后立即重试，没有等待 `loading` 清除。测试现增加空闲按钮等待，定向用例 **3 passed**、主平台前端全量 **356 passed、19 skipped**；当时修复提交的远程 push 检查待完成（后续结果见下一项）。
- 后续验收（修复提交）：GitHub Push Run `35866990452` 绑定 `ea1ebc8f15dacfec21dc2378157db1bf7a3936c3`，Cross-platform quality gates **success**。Ubuntu 与 Windows 的后端套件、前端测试、前端构建及各自的平台服务 smoke test 均通过；Production integration、Production experiment integration、Chromium acceptance 和 Week 11–12 verification 按 push 事件条件跳过。此前 Week 11–12 full CI 的成功证据仍绑定 `4a3c639d9ef34fe4962e873ec277f516b660d586`（Run `35855270973`），与本次 push 质量门禁分开记录。

### 2026-09-23 标注工作区底部新增「跳转条目」

- 需求（用户提出）：在标注工作区最底部「第 X/Y 条」旁新增跳转输入框，输入数字跳到对应数据，超过最大数跳转到最后一条。
- 实现：
  - 后端 `annotator_internal.py` `internal_portal_samples` 新增 `offset` 查询参数（ge=0，作用在既有过滤/游标之后 `query.offset(offset).limit(limit+1)`），支持不逐页走游标链直达任意位置；网关 `tasks.py` `list_samples` 透传 `offset`（为 0 时不转发，保持既有转发参数契约不变）。
  - 前端 `api/tasks.ts` `listSamples` 增加第 5 参 `offset`；`TaskWorkspacePage.tsx` 新增 `loadPageAt(pageIndex, selectIndex)`（offset 分页加载）与 `jumpToSample`（1 起始、低于 1 回第一条、超过 `total_samples` 钳制到最后一条；同页仅本地切换不发请求）；`movePrev` 改为 offset 回退一页（跳转后游标链可能缺失）；`SampleStream.tsx` footer 在「第 X/Y 条」旁渲染数字输入框（过滤非数字）+「跳转」按钮，Enter 提交，输入框内不触发全局快捷键（既有 editable 守卫天然覆盖）。
- 测试：前端 vitest **111 passed**、tsc 通过（新增：输入 999 超界钳制到 120/120 最后一条 + 同页跳转零请求）；网关 30 passed（原参数转发契约用例保持不变）；主后端 portal 过滤套件 **235 passed / 5 skipped**。
- 部署：已重建 `annotator-frontend`（bundle `index-B-plsHaE.js`，含跳转 UI）与 `annotator` 网关容器（offset 透传），8443 登录链路验证 200。
- **运维教训**：重建/重启 `annotator`（网关）容器后其容器 IP 会变化，而 `annotator-frontend`（nginx）启动时解析一次上游主机名并缓存——不重启 nginx 会导致 8443 经 nginx 的登录/接口全部 502（直连 8444 正常）。**重建 annotator 容器后必须 `docker compose restart annotator-frontend`**（本轮已实操验证恢复）。
- 微调（用户截图反馈）：跳转输入框 placeholder「条数」→「样本」（aria-label 同步为「跳转样本」），`.stream-jump` 增加左右 8px margin 拉开与「第 X/Y 条」/「下一条」的间距。测试 111 passed，已部署 bundle `index-B6eOmWrO.js`。

### 2026-09-23 标注员门户三项修复：已验收任务终态展示、样本面板去分页、批量保存偶发冲突

- 需求（用户提出）：① 任务已验收后去掉质检反馈提示、任务列表显示「已验收」且不能再编辑；② 去掉标注工作区样本面板中的分页；③ 批量操作时不时会报错。
- 根因 1：验收通过后 `task.status="accepted"`（`refresh_task_return_state`），但 `assignment.state` 停留在 `returned_pending_acceptance`，前端 `isFeedbackTask`/「需重做」徽标按 assignment.state 误判为质检反馈；`statusLabels` 缺 `accepted` 映射导致任务卡片显示原始英文 "accepted"。
- 根因 2：样本面板（工作区左侧「样本」tab）含独立「分页」区块（上一页/第 N 页/下一页）。
- 根因 3：单样本保存成功后只更新了 `samplesRef`/`setSamples`，未同步 `sampleCacheRef`；`applyBatch` 优先从 `sampleCacheRef` 取 `base_revision`，读过时修订号触发后端 `RevisionConflict` 409，整批回滚并提示「批量保存存在版本冲突，整批未写入」。仅当所选样本在本次会话中被自动保存过时才复现，故表现为偶发。
- 修复（仅前端 `ml-platform/annotator/frontend`，后端契约不变——`read_only` 与 `_ensure_task_allows_label_write`/`_ensure_task_allows_return_edit` 已天然锁定已验收任务）：
  - `TaskCard.tsx`：`statusLabels` 增加 `accepted: '已验收'`；`isFeedbackTask` 排除 `status==='accepted'`；`rework` 徽标排除已验收；按钮文案已验收时为「查看任务」。
  - `TaskQueuePage.tsx`：状态筛选下拉新增「已验收」选项；逾期统计排除已验收任务。
  - `TaskWorkspacePage.tsx`：删除样本面板「分页」区块（样本流翻页仍由 下一题/方向键 自动加载）；页头状态已验收时显示「已验收」（优先于「回传后只读」）；回传面板已验收时显示「任务已验收，标注内容已锁定，不可再编辑或回传」并隐藏「编辑后回传」；`save()` 成功后同步 `sampleCacheRef`（批量修订号修复）；`applyBatch` 增加在途保存 ref 守卫（防 `blockers` 渲染滞后竞态）。
- 测试：前端 vitest **109 passed（14 文件，基线 94 → 新增/调整后全绿）**，`tsc --noEmit` 通过。新增用例：已验收任务卡片（已验收徽标/无需重做/查看任务/isFeedbackTask=false）、队列页（无质检反馈横幅/不计入逾期）、工作区（已验收只读、无编辑后回传）、批量修订号回归（单样本保存后 bulk 使用刷新后的 base_revision）。
- 未验证：8443 门户线上（docker 镜像）未重建部署；后端未改动无需重跑 pytest。
- **补充（用户截图反馈后）**：用户实测已验收任务仍显示英文 "archived"+「需重做」+质检反馈横幅——根因是验收后管理员又执行了归档（状态机 `accepted → archive → archived`，见 `annotation_task_state.py`），上轮只排除了 `accepted` 一种终态。修复：`TaskCard.tsx` 导出 `TERMINAL_STATUSES`（accepted/completed/archived/cancelled/failed），`isFeedbackTask` 与「需重做」徽标排除全部终态；`statusLabels` 补 `archived: '已归档'`；已验收/已归档任务按钮统一为「查看任务」；`TaskWorkspacePage.tsx` 页头与回传面板对终态（已验收/已归档/已完成/已取消）显示对应中文并隐藏「编辑后回传」；`TaskQueuePage.tsx` 逾期统计排除 `archived`。测试 vitest **110 passed**、tsc 通过。
- **部署注意**：annotator-frontend Dockerfile 仅 `COPY dist`（宿主机构建产物），改代码后必须先 `npm run build` 再 `docker compose build`，否则镜像内容不更新（本轮踩过：首次重部署时忘记重跑 build，curl 到的仍是旧 bundle，以 bundle hash + 内容 grep 验证为准）。已部署新 bundle `index-DI7NJEny.js` 到 8443 并验证含「已验收」「已归档」逻辑。

### 2026-09-23 远程 CI Python 依赖源慢

- 现象：远程 CI 构建生产后端镜像时，Python 依赖安装被固定导向阿里云 PyPI 镜像，下载较慢。
- 根因：CI 构建的 `backend`、`worker`、`inference`、`tensorboard` 四个 Dockerfile 都执行了 `pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/`；workflow 本身未配置该源。
- 修复：移除四个 Dockerfile 中的全局 pip index 覆盖，让 pip 使用默认 PyPI；保留原有重试、读取超时和 BuildKit 缓存。新增 CI 镜像合同测试，禁止这些 Dockerfile 设置阿里源或其他 `index-url` 覆盖。
- 验证：新增回归先对四个 Dockerfile 全部失败；修复后 `python -m unittest tests.test_ci_workflow -q` 为 **57 tests OK**，`git diff --check` 通过。
- 未验证：本轮没有构建 Docker 镜像，也没有在新 SHA 上运行远程 CI；实际 CI 下载耗时改善仍待该次运行数据确认。
- 合并整合补充（2026-09-23）：按用户指定以 `general-automl-annotation-20260902` 工作树为主合入 `main`。首次 push 质量 Run `35842676835`（SHA `3fc393f`）暴露两处合并合同问题：四个 Dockerfile 选成 Debian 后与工作树的 Wolfi 固定镜像合同冲突；Windows runner 的 `bash` 实际是 WSL 启动器且没有 Linux 发行版。已恢复工作树的 Wolfi 镜像、Quay MinIO 与 GHCR MLflow Compose 配置；MLflow wheel 挂载改为可由 `MLFLOW_WHEEL_DIR` 覆盖，缺少 wheel 时保留默认 PyPI 安装回退；保留生产密钥引导脚本的安全默认值。CI 合同改为断言当前 Compose/Image 行为，并仅在 Linux Bash 环境运行密钥脚本集成验证。上述修正尚待新 SHA 的远程质量与 full 门禁验证。

### 2026-09-23 CI Run 35802807330：Week 11 性能验收容器 ID 修复

- 现象：Run `35802807330` 的 Quality、生产集成和 Chromium acceptance 均通过；`Week 11-12 verification (Ubuntu)` 在 `Run live Week 11 acceptance evidence` 失败。作业日志及 `week11-12-verification-evidence` artifact 的 `performance/backend-failure.log` 记录 `No such container`，失败状态清单显示 backend 已由 Compose 重建并运行。
- 已验证根因：`run_performance.sh` 在 `docker compose up -d --force-recreate inference-runtime backend worker scheduler` 前缓存 backend 和 worker 的容器 ID；Compose 重建后，后续 `docker cp` 仍使用旧 backend ID，导致 Docker daemon 报容器不存在。
- 修复：先初始化容器 ID 变量以确保失败清理路径可用；强制重建后再按 Compose service 查询 backend、worker、redis 和 postgres 的当前 ID。新增运行真实验收 shell runner、用受控 Docker/Compose 函数模拟容器重建并验证 runner 使用新 backend ID 的回归测试。
- 验证：回归先因 `stale-backend-id-used` 失败，修复后通过；`pytest tests/test_week11_12_tools.py -q` 为 **110 passed、5 subtests passed**；完整后端 `pytest tests -q` 为 **1993 passed、109 skipped、751 subtests passed、41 warnings**；`bash -n ml-platform/backend/tools/acceptance/run_performance.sh` 和 `git diff --check` 通过。
- 状态：Run `35802807330` 绑定旧 SHA `55f184f7394a0318507240c5962ba2b6ee0ac330`，仍为失败。当前修复尚未提交或推送，也未在新 SHA 重跑远程 full CI；Task 14 继续 `in_progress`，19 项收据仍需由最终 SHA 的远程验收生成并核对。

### 2026-09-23 远程 CI 第三轮修复：generic-platform-acceptance 规格重写对齐两步向导 UI

- 需求：第二轮 full 模式 run 中 `browser-acceptance` 的 `generic-platform-acceptance.spec.ts` 2 例确定性失败（各重试 1 次仍败），规格严重落后于 09-20 的两步向导重构。
- 根因 1（测试 1）：任务单元格现渲染 `<strong>task-1</strong>` + `<span>自动标注 · task-1</span>`，`getByText("task-1")` strict mode 命中两元素；行内「执行」按钮已移除（预览完成后自动执行）。
- 根因 2（测试 2）：旧规格按单页表单编写——「启用聚类」复选框已被两步向导替代；创建端点应为 POST `/api/annotation-tasks`（旧 mock 的 `/api/automl-tasks` 已废）；「配置策略」弹窗流程已被向导内 Step 2（弱监督 select → 生成聚类预览 → LabelSchemaEditor 保存 schema 解锁 → 策略编辑器 → 保存策略并完成 → 最终预览 → 返回任务列表）替代。
- 修复：按当前 UI 重写两例。测试 1 改为 awaiting_return → 提交回传 → 验收 状态机流 + 指派按钮 disabled 断言 + 预览 drawer；测试 2 按两步向导全流程（含 schema 保存解锁策略编辑器、PUT configuration 的 `label_schema_id` 与 `cluster_labels` 机器键 `label-1` 断言、最终预览 `configuration_complete` 收尾、指派对话框 antd Select 交互）。策略编辑器容器为 div 无隐式 region role，用 `[aria-label="自动标注策略配置"]` 定位；「返回任务列表」header/footer 双按钮取 `.last()`。
- 环境事故（非规格问题）：本地 8000 端口 `--reload` 模式 uvicorn（违反本地后端约定）致 login 偶发失败，清理孤儿 reloader 及其 multiprocessing worker 后按约定以 `--host 0.0.0.0 --port 8000` 重启恢复；主平台 `/api/auth/login` 为 OAuth2 表单格式（非 JSON），curl 探测须用 `x-www-form-urlencoded`。
- 测试：本地 `npx playwright test e2e/generic-platform-acceptance.spec.ts --project=chromium` **2/2 passed**；回归 `generic-annotation-portal.spec.ts + automl-multioutput.spec.ts` **5/5 passed**。
- 遗留：待提交推送后重新 dispatch full 模式远程 CI，全绿后核对 `week11-12-verification-evidence` 产物中 19 份收据。

### 2026-09-22 远程 CI 第二轮 full 模式失败修复：BACKEND_PORT 对齐与 E2E 规格同步

- 需求：首轮修复（65e338a）推送后重新 dispatch 的 full 模式 run 中，`Production experiment integration` 与 `browser-acceptance`（含 `generic-annotation-portal.spec.ts` 3 例、`automl-multioutput.spec.ts` 1 例）仍失败。
- 根因 1（experiment-integration）：base compose 发布 `"${BACKEND_PORT:-8001}:8000"`，该 job 的 `/api/ready` 探测打 `127.0.0.1:8000`，端口不对齐导致 curl exit 7。修复：job env 显式设 `BACKEND_PORT: "8000"`（与 browser-acceptance 一致）。
- 根因 2（automl spec）：强度枚举在 2026-09-11 合同更正后为 light/medium/high/ultra（默认 medium），规格仍写旧值 `balanced` 导致选项不存在。修复：改为 `medium`。
- 根因 3（portal spec，多处规格漂移）：① App 挂载与登录后都探测 `/portal/auth/me`，未 mock 的请求抛 Unexpected request 或经 vite 代理 502——全部测试补登录前 401/登录后身份分支；② 队列按钮已改名「继续标注」（旧「打开工作区」不存在）；③ 工作区左侧改为 tab 面板且默认仅展开「指南」——样本筛选/批注/回传操作前需先点击对应 tab；④ 队列页请求带查询串（`?limit=50&sort=due_at`），glob `**/portal/tasks` 匹配不到，改为 `**/portal/tasks**` 并补 `/portal/notifications`、`/portal/comments` 轮询 mock；⑤ 第 4 例 task mock 缺 `label_schema` 导致标签区无输入框；⑥「标签已保存」strict mode 命中两元素，改 `{ exact: true }`。
- 测试：本地 `npx playwright test e2e/generic-annotation-portal.spec.ts e2e/automl-multioutput.spec.ts --project=chromium` **5/5 passed**（注意 Shell 带 `CI` 环境变量会使 `reuseExistingServer` 失效，需先 `Remove-Item Env:CI` 复用本地 dev server）。
- 遗留：远程 CI 需在本轮提交推送后重新 dispatch 验证；19 项收据的远程绿灯证据以最终 run 为准。

### 2026-09-22 远程 CI 首轮 full 模式暴露两处失败的修复

- 需求：`workflow_dispatch mode=full` 在 `general-automl-annotation-20260902` 分支远程执行，`Quality`（ubuntu + windows 同报）与 `Production experiment integration` 两个 job 失败；`browser-acceptance`、`week11-12-verification` 因依赖 quality 被跳过，19 项收据未生成。
- 根因 1（Quality，`DataAnnotationPage.test.tsx:562`）：任务列表日期断言写死本地渲染格式 `/2026\/9\/16/`、`/2026\/10\/1/`；组件 `formatBackendTimestamp`/due 列使用 `toLocaleString()`/`toLocaleDateString()`（locale/时区感知），CI runner 为 en-US + UTC，渲染为 `9/16/2026, 8:30:00 AM` 与 `9/30/2026`（本地 zh-CN + UTC+8 才是断言值）。修复：断言改为按同一 `Date` + `toLocale*` 动态计算期望文本，跨 locale/时区恒等；确认 `due_at: new Date(...).toISOString()` 的 PUT 断言两侧对称不受影响。
- 根因 2（experiment-integration）：`docker-compose.yml` mlflow 服务挂载开发者个人宿主机路径 `/home/jingms/mlflow-wheel`，CI runner 上不存在 → Docker 自动创建空目录 → `pip install --no-index` 找不到 wheel → 容器启动即退出（日志中 Started 后 0.5s Error）→ unhealthy → `compose up --wait` 失败。修复：命令改为条件安装——wheel 存在则按原离线路径安装，否则 `pip install --no-deps psycopg==3.3.5 psycopg-binary==3.3.5`（CI 有网络出口）；开发机行为不变。
- 测试：`TZ=UTC` 与本地时区分别运行 `DataAnnotationPage.test.tsx` 均 **60/60 passed**；`pytest tests/test_ci_workflow.py tests/test_image_security_contracts.py -q` 为 **67 passed、138 subtests passed**（compose 合同含镜像安全断言不受影响）；compose YAML 解析与折叠命令断言通过；`git diff --check` 对两处改动文件无问题。
- 遗留：本轮远程 run 的完整绿灯证据（含 19 项收据）待用户提交这两处修复后重新 dispatch 生成；日志中镜像构建阶段的 pip dependency resolver 冲突为警告性质，不阻断。

### 2026-09-22 Task 14 收据接入修复：19 项 receipt 纳入 CI 最终证据链

- 需求（Task 14 唯一剩余缺口）：CI 中已生成的 19 项通用验收收据落在 `temp_test/generic-platform-acceptance/`，与 `ML_PLATFORM_EVIDENCE_DIR`（`temp_test/week11-12`）分离——`evidence_manifest` 最终 manifest 的哈希文件清单和 `Upload verification evidence` 产物均不包含收据，证据链断裂；且 AUTH-02 的 source_map 指向不存在的 `ml-platform/annotator/backend/tests/test_portal_internal_api.py`，CI 步骤会在该项以 `EVIDENCE_FILE_MISSING` 失败。
- 实现（`.github/workflows/ci.yml` week11-12-verification job）：① 收据目录改为 `ML_PLATFORM_EVIDENCE_DIR/generic-platform-acceptance`，使 `evidence_manifest.generate` 的 rglob 文件清单收录全部 19 份收据（`files[].sha256`）并随 `week11-12-verification-evidence` 产物上传；② 嵌套 manifest 更名为 `acceptance-manifest.json`，避免与顶层 `final-evidence-manifest.json` 混淆；③ AUTH-02 证据路径修正为实际存在的 `ml-platform/annotator/backend/tests/test_portal_api.py`（门户后端套件，覆盖会话/Cookie/身份边界）；④ 保留 `validate_acceptance_manifest(current_sha=GITHUB_SHA, repository_root=workspace)` 的 fail-closed 文件哈希校验和 source_map 与 19 项 ID 的一致性断言。
- 测试：新增 `test_ci_workflow.py::test_week11_generic_receipts_feed_the_final_evidence_manifest`（锁定收据目录在 `ML_PLATFORM_EVIDENCE_DIR` 下、`acceptance-manifest.json` 命名、收据→最终 manifest→上传的步骤顺序、最终 manifest 步骤无 `always()` 保持 fail-closed、上传路径覆盖 `temp_test/week11-12`）；`pytest tests/test_ci_workflow.py tests/test_acceptance_manifest.py -q` 为 **62 passed、138 subtests passed**。
- 本地链路验证：以当前 HEAD `2740ea1` 模拟 CI 步骤在本地生成 19 份收据 + acceptance-manifest.json，`validate_acceptance_manifest` 通过（含逐文件 SHA-256 哈希比对），并用 `evidence_manifest._evidence_entry` 确认 20 个收据文件全部通过敏感信息/绝对路径安全检查、可被最终 manifest 哈希收录；模拟产物已清理。
- 边界与未验证项：本修复在工作树中完成，未提交、未推送，远程 CI 尚未在新 SHA 上执行——19 项收据的 `passed` 状态仍需远程 `week11-12-verification` job 在最终干净 SHA 上实际生成后才能作为发布证据。收据哈希绑定的是测试源文件（矩阵 2026-09-15 语义更正的边界仍适用：CLU-02 百万样本实测、AUTH-02/AUTO-02 双服务真实证据、REL-01 真实 worker 恢复演练不因测试文件存在而自动关闭）。

### 2026-09-22 修复交接遗留问题：写接口幂等头、批注草稿保留、ONNX 转换兼容与全量回归

- 需求（HANDOVER.md 第 6 节遗留问题）：① `spotWeldQuality.ts` createQualityRun 缺幂等头（违反技术方案 §12.0 写接口合同）；② AdminReviewPage 批注草稿在自动保存失败后切换样本丢失；③ pyarrow 缺失导致 parquet 测试 skip；④ 主后端全量套件在 20260921_60 链头完整重跑并修复新暴露失败；⑤ 前端三套件回归。
- 实现（frontend `api/spotWeldQuality.ts`）：createQualityRun 增加 `X-Request-ID` + `Idempotency-Key` 头（Idempotency-Key 作为默认参数 `crypto.randomUUID()`，与 annotationTasks/annotatorAssignments 既有模式一致）；后端 `spot_weld_quality.py` create_run 不强制该头，纯增强无破坏。
- 实现（annotator frontend `pages/AdminReviewPage.tsx`）：新增 `unsavedRef`（Map<sampleId, draft>）保留保存失败/防抖未触发的草稿——保存成功即清除；切换样本时恢复草稿并提示「上次批注未保存成功，已恢复草稿」；后台顺序重试其他样本的失败草稿（绕开单飞锁 savingRef）。
- 根因与修复（backend ONNX 转换）：全量套件暴露 `test_onnx_conversion.py` 两个子测试失败（extra_trees/hist_gradient_boosting，RF 同样受影响）——onnx 1.22（protobuf 7）对 `AttributeProto.ints` 字段严格化，拒绝 bool 值；skl2onnx 1.19.1 在树集成节点属性 `nodes_missing_value_tracks_true` 传入原始 bool。修复：venv 升级 skl2onnx 1.19.1 → 1.20.0（修复 RF/ET 路径）+ `onnx_worker.py` 新增 `_apply_skl2onnx_bool_compat()`（HGB 路径 1.20.0 仍传 bool，monkeypatch `tree_ensemble.add_node` 强转 int）+ `requirements.txt` 钉住 `skl2onnx==1.20.*`。注意：该问题影响生产环境的树模型 ONNX 导出功能，非仅测试问题。
- 测试时序修复（frontend `pages/DataAnnotationPage.test.tsx`）：全量跑挂 4-5 例——React 在 datasets 异步加载期间重挂载 select 导致测试捕获的旧节点脱离文档、fireEvent.change 在 option 渲染前执行导致 value 重置为空。修复：waitFor 内每次重新 getByLabelText 并等待目标 option 出现再 change；5 处 spot-weld POST 断言补幂等头第三参数。
- 测试：**后端全量 `pytest tests -q`：1991 passed / 2 failed / 109 skipped（修复后 test_onnx_conversion 10 passed + 4 subtests、test_offline_inference_contract + test_inference_production_stack 4 passed/2 skipped）；主平台前端全量：vitest 356 passed / 19 skipped、tsc 通过、build 通过；标注员门户：105 passed、tsc/build 通过（草稿保留新增 2 用例）**。
- 说明与未验证项：① admin 会话无吊销（无状态 JWT TTL 30min）为设计取舍，仅记录不改动；② 浏览器端到端实测因 Windows→WSL mirrored 网络端口转发失效（容器内 8443 正常、Windows localhost 超时）降级为 curl 链路验证（网关→后端 200）；中文列名导出端到端因需先造数据未实测；③ pyarrow 25.0.1 已装入 venv，parquet 相关 3 例由 skip 转通过。

### 2026-09-21 回传结果卡片显示原始待标注文件与已保存数据制品

- 需求：回传结果卡片补充显示①原始待标注文件名；②已验收并保存到数据管理后的数据制品名。
- 实现（backend `services/annotation_returns.py` `list_return_batches`）：items 新增 `source_dataset_name`（task.dataset_version_id → DatasetVersion.original_artifact_id → Artifact.name，批量 IN 查询）与 `saved_dataset_name`。关键点：accept 创建的数据版本不带 artifact，数据制品仅在 export-dataset 时创建且不回写批次——通过导出版本 parse_contract.return_batch_id 反查（`DatasetVersion.parse_contract["return_batch_id"].as_string().in_(batch_ids)`，与 ModelLibrary.params["source"] 同款 JSON 索引查询，SQLite/Postgres 通用），每批次取 version 最新的导出（支持多次导出）。
- 实现（frontend）：`annotationReturns.ts` ReturnBatch 补两个可选字段；`ReturnBatchList` 卡片在任务 ID 上方显示"原始文件 xxx.csv"、下方（有时）显示"已保存制品 xxx.csv"（均 code 样式 + title 悬浮全名，与既有行样式一致）。
- 测试（backend `test_annotation_return_acceptance.py`）：list 关联测试新增 source 原始文件断言——注意 DatasetVersion 有 immutable ORM 事件（任何 UPDATE 均抛错），测试中用 Core `sa.update` 绕过并 `db.expire_all()` 刷新缓存；export 测试追加三次导出后 `saved_dataset_name == "带后缀.csv"`（最新导出）断言。（frontend）`ReturnBatchList.test.tsx` 新增已保存制品渲染用例 + 未导出不显示断言。**test_annotation_return_acceptance 18 passed；ReturnBatchList + DataManagePage 11 passed；tsc 通过**。

### 2026-09-21 数据管理"回传结果"面板信息增强与统一样式

- 需求：数据管理页"回传结果"面板显示粗糙（仅批次 ID + 修订 + 状态 + 操作按钮，卡片为简易 card-surface），要求信息更全、样式与其他模块一致。
- 实现（frontend `components/ReturnBatchList.tsx`）：重写为与"回传验收"（ReturnAcceptancePanel）/"任务操作记录"面板一致的样式——`table-surface data-annotation__operations-surface` 容器 + `data-annotation__section-head`（标题 + 批次汇总"共 N 个批次 · M 个待验收"）+ `data-annotation__operations` 自适应卡片网格（minmax(280px, 1fr)）。
- 卡片信息增强：任务名（code 样式，title 悬浮全名，缺省批次 ID 前 8 位）、状态 Tag（待验收 orange/已验收 green/已退回 red）、标注员（姓名优先，回退 subject_id 前 8 位，title 显示完整 subject_id）、样本数（validated_row_count）、任务修订号、任务 ID（前 8 位，title 全量）、回传时间（formatLocalTime 本地时区）。
- 交互保留两步退回（退回 → 填原因 → 确认退回 disabled 直至有原因），新增"取消"退出退回编辑；验收/退回按钮仅 pending 批次显示（antd 原生 ant-btn 类按钮，避免 antd Button 对两字中文自动插空格导致 aria-label 断言失效）；加载/空态用 Spin/Empty 对齐参照面板。
- CSS（`styles/global.css`）：新增 `.return-batch-list`（margin-top 20px 与区块间距约定一致）、`__summary`、退回 textarea、`table-row-actions` 换行起点对齐。
- 测试：`ReturnBatchList.test.tsx` 由 1 个扩展为 3 个（两步退回流程保留、元数据渲染断言、accepted 批次无验收/退回按钮）。**ReturnBatchList + DataManagePage 10 passed；tsc 通过**。

### 2026-09-21 数据管理预览显示全部数据

- 需求：数据管理页（/data，DataManagePage）点击"预览"只显示 10 行，应显示数据集全部行。
- 根因：双重 10 行限制——后端 `api/datasets.py` `preview_dataset` 固定 `df.head(10)`；前端 `DataManagePage.tsx` 再 `rows.slice(0, 10)`。
- 实现（backend）：`GET /datasets/{id}/preview` 新增可选 `limit` 查询参数（默认 10，`ge=0`；`limit=0` 返回全部行），既有调用方（AutoMLPage、TrainingJobsPage、DataBrowserPage、test_api_project_access）不传参数行为不变；`total_rows` 始终为全量行数。
- 实现（frontend）：`api/datasets.ts` `getDatasetPreview` 增加 `options.limit` 参数；`DataManagePage` 预览请求 `limit=0` 并移除 slice 截断，模态框内表格改为 `maxHeight: 60vh` 双向滚动，顶部显示"共 N 行"（≥500 行时提示滚动查看）。
- 测试：`test_api_datasets.py` 新增 `test_03_preview_limit_returns_all_rows_when_zero`（15 行 CSV：默认 10 行、limit=2 → 2 行、limit=0 → 15 行）；`DataManagePage.test.tsx` 新增 `previews every dataset row instead of a fixed cap`（断言请求 `?limit=0`、渲染全部 15 行与行数说明）。**test_api_datasets 18 passed；test_api_project_access 16 passed + 24 subtests；DataManagePage 7 passed；tsc 通过**。

### 2026-09-21 指派标注员信息增强 + 已指派排除 + 验收导出数据集补文件后缀

- 需求（三项合并）：① 指派标注员时应能看到可指派标注员的信息；② 指派时应看到本任务已指派的标注员，且下拉中去掉已指派过的；③ 已验收批次保存到数据管理时名称没有文件后缀（如 .csv）。
- 实现（backend `api/annotator_internal.py`）：`GET /api/annotators` 响应 items 增加 `email` 字段（与 `/api/admin/annotators` 对齐），供指派下拉展示标注员详情。
- 实现（frontend `components/AssignmentDialog.tsx` + `pages/DataAnnotationPage.tsx`）：
  - 下拉选项改为富信息渲染（antd optionRender）：用户名（加粗）+ 邮箱 · 已审核通过 · 已授权本项目（无邮箱时仅状态行）；搜索同时匹配用户名与邮箱。
  - 新增 `assignedIds` prop：`openAssignmentDialog` 并行拉取 `listAnnotatorSubjects` 与 `listTaskAssignments(task.id)`，下拉 options 排除已指派的 subject_id；抽屉内新增「已指派标注员（N）」信息块（用户名列表，不在可指派列表中的显示 subject_id 前 8 位）；全部已指派时下拉空态提示「该项目标注员均已指派」。
- 实现（backend `services/annotation_returns.py`）：`export_return_batch_dataset` 的 artifact 名补源文件后缀——`{name}.{file_format}`（用户名已以该后缀结尾时不重复添加）；`_unique_export_dataset_name` 去重序号改为插在扩展名之前（`验收结果集-2.csv` 而非 `验收结果集.csv-2`；无扩展名/异常后缀回退原逻辑）。
- 测试：backend `test_annotator_auth.py` 补 email 断言（含 None）、`test_annotation_return_acceptance.py` 断言名带 `.csv`、重名 `-2.csv`、已带后缀不重复（**18 passed**）；frontend `AssignmentDialog.test.tsx` 新增标注员详情/已指派排除/全部已指派空态 3 用例、`DataAnnotationPage.test.tsx` 指派用例补 assignments 调用与排除断言（**67 passed**）、tsc 通过。
- 说明：后端 `--reload` 运行则自动生效；已保存的历史导出数据集名不带后缀，不回填。

### 2026-09-21 自动建模任务详情页模型结果 Accuracy 显示为 "-"

- 现象：自动建模（AutoML）任务详情页"模型结果"表格中 Accuracy 列显示 "-"，AUC/F1 正常；详情弹窗与试验表格正常。
- 根因：后端 `automl_execution.py` 写入 `all_results`/`algorithm_results` 的结果行只有 `score`（家族搜索为 `best_score`）键——分类任务的搜索得分即 accuracy（`scoring="accuracy"`，排序键也把 `item["score"]` 当 accuracy 用），但从不写 `accuracy` 键。前端 `AutoMLTaskPage.tsx` 主表 Accuracy 列与排序只查 `accuracy`/`Accuracy` 键（含嵌套 metrics/evaluation/scores），找不到即回落 "-"。
- 修复（frontend，最小改动且可兼容已落库的历史任务指标）：`AutoMLTaskPage.tsx` 主表 Accuracy 列渲染与排序的键列表扩为 `["accuracy", "Accuracy", "best_score", "score"]`，与详情弹窗既有的 `best_score ?? accuracy ?? score` 兜底语义对齐。回归任务不受影响（回归路径渲染 R2/RMSE/MAE 列）。
- 测试：`AutoMLTaskPage.test.tsx` 新增 `shows accuracy from score and best_score when results lack an explicit accuracy key`（all_results 分别携带 score/best_score，断言主表渲染 0.9500/0.9000 而非 "-"）。**AutoMLTaskPage 12 passed；frontend tsc --noEmit 通过**。

### 2026-09-21 自动标注任务 MODEL_INPUT_MISSING：创建时前置校验与错误信息增强

- 现象：新建自动标注任务（不启用弱监督，`clustering=false, strategy="model"`）时创建成功，但生成预览报 MODEL_INPUT_MISSING 且 details 为空，无从定位。
- 根因：所选数据集为原始 90 列版本，而模型（automl-job - XGBoost，d3bee360）训练于特征工程后的数据集版本（6fc046ee…，74 列 46 行）；模型输入契约要求 73 列（14 原始 + 59 工程特征如 current_mean/voltage_pp/power_wld1 等），模型包 preprocessing 仅含 `drop_rows_before_training`，不含特征工程变换，无法从原始列推导。检查逻辑本身正确，但只在预览执行时暴露且不透明。
- 修复（backend）：
  - `api/generic_tasks.py`：新增 `_model_input_columns()`（从冻结的 conversion_metadata.input_contract.feature_columns/input_columns 取输入列，fallback feature_schema）；`create_generic_task` 自动模式在模型版本解析后立即校验数据集 schema 列覆盖输入契约，缺列即 422 MODEL_INPUT_MISSING，message 列出缺失列名（前 10 个）。该校验同时覆盖弱监督与不启用弱监督两种模式（聚类也要跑模型推理）。
  - `services/annotation_strategies.py`：`_model_outputs_from_package` 的 MODEL_INPUT_MISSING 错误信息携带缺失列（`preview rows are missing N model input columns: ...`），不再为空。
- 修复（frontend）：
  - `api/client.ts`：`localizeApiError(code, message?)` 支持 `{message}` 占位符模板，保留后端缺失列详情；无 code/无模板时行为不变。
  - `i18n/index.tsx`：zh/en apiErrors 新增 MODEL_INPUT_MISSING 词条（带 `{message}` 占位符，提示选择模型训练时使用的数据集版本）。
- 测试：`test_annotation_task_state_api.py` 新增 `test_automatic_task_creation_rejects_dataset_missing_model_inputs`（数据集缺 `feature` 列 → 422 MODEL_INPUT_MISSING，任务不落库）；既有 `test_automatic_task_rejects_invalid_strategy_before_persisting` 补齐 DatasetSchemaColumn（原只建样本未建 schema 列，被前置校验拦截）。**test_annotation_task_state_api 26 passed；annotation 相关全量 202 passed / 18 skipped；前端 vitest 347 passed / 19 skipped、tsc 通过**。
- 说明：正确解法是用户选择模型训练时的数据集版本（6fc046ee…，74 列 46 行）；平台现已在创建任务时提前拦截并明确列出缺失列，无需等到预览才发现。

### 2026-09-21 修复自动标注任务模型版本全部显示「未审批启用」

- 现象：新建自动标注任务时模型版本下拉全部禁用并显示「未审批启用」（MODEL_VERSION_NOT_ENABLED）。
- 根因：模型版本存在两条审批路径——新路径 `transition_model_version`（approve 同时设 `lifecycle_state='enabled'` + `approval_status='approved'`），但审批 API `POST /api/model-versions/{id}/approve` 实际走旧路径 `ModelRegistryService.approve()`，后者只设 `approval_status` 不改 `lifecycle_state`（注册默认 `pending_review`）。`/api/projects/{id}/annotation-model-versions` 的可选性判定要求 approved + enabled 双条件，导致历史审批过的版本全部被禁用（本地库 86 个版本中 84 个为 approved+pending_review 不一致状态）。
- 修复（backend）：
  - `services/model_registry.py`：`approve()` 主路径同步设置 `lifecycle_state='enabled'`；对已 approved 但 lifecycle 仍为 pending_review 的遗留行，重复调用 approve() 时自动治愈为 enabled（不触碰显式 disabled/revoked 行）；`archive()` 同步设置 `lifecycle_state='archived'` 并治愈遗留行。
  - `database_migrations.py`：`ensure_schema_compatibility`（本地 SQLite 兼容路径）新增幂等数据回填——approved+pending_review → enabled、archived+pending_review → archived，仅治愈不一致行。
  - 新增 Alembic 迁移 `20260921_60_model_version_lifecycle_backfill`（生产 Postgres 同源回填，downgrade 为 no-op）；`tools/upgrade_fixture.py`、`tools/evidence_manifest.py`、`tools/acceptance/run_upgrade_fixture.sh`、`tests/test_database_production.py`、`tests/test_inference_production_stack.py` 的 head 修订号同步更新为 20260921_60。
- 测试：`test_model_registry_service.py` 新增 approve 启用+遗留治愈用例；`test_database_migrations.py` 新增回填幂等用例；`test_api_model_registry.py` approve 断言补 lifecycle_state。**test_model_registry_service + test_database_migrations + test_api_model_registry 34 passed；test_database_production + test_annotation_task_state_api + test_model_registration_contract 54 passed；alembic heads = 20260921_60（单头）**。本地 ml_platform.db 重启后已治愈（86 个 approved 全部 enabled，1 个 pending）。
- 说明：治愈后 onnx_artifact 来源的 84 个版本仍会被 MODEL_SOURCE_UNSUPPORTED（「仅支持平台训练产物」）禁用——自动标注仅支持平台训练 joblib 产物为既有设计；当前可选项为 2 个 `automl-job - XGBoost` 平台产物版本。`test_inference_production_stack` 的 head 断言已同步但该重型套件未在本机完整运行。

### 2026-09-21 全量算子契约审计与修复（82 个算子）

- 审计（backend 临时脚本，已清理）：对全部 82 个注册算子的 id/name/description/version、端口（重名/类型/标签/必填输入）、参数（类型/默认值/options/range/required）做结构化检查，共发现 118 条告警。
- 修复（不合理项，3 类）：
  - 参数类型 `bool` → `boolean` ×3（`io_operators.py` overwrite、`processing.py` invert / with_replacement）——前端 NodeConfigPanel 只识别 `boolean`（Switch 控件），`bool` 会退化为文本输入框，存在把字符串 "true" 传给后端的风险。
  - 补齐 7 个 ml 算子缺失的 description（logistic_regression / kmeans_clustering / dbscan / apriori / fp_growth / random_forest_regression / svm_regression），中英双语，消除算子面板空白提示。
  - 端口类型词汇统一：结构化输出端口 `Params`(14) / `table`(7) → `JSON`(21)，涉及 evaluation / visualization / control / processing / mechanism 五个文件（含 confusion_matrix_plot 的 metrics 输入端口，输出输入两侧同步改）；端口类型仅用于前端 tooltip 展示与 DAG 校验不检查类型，重命名零功能风险。
- 保留不改（合理设计）：io 导入类与 mechanism 仿真类算子无输入端口（数据源/纯参数驱动）；mechanism 输出的标量类型（str/float/int/boolean/list[str]）如实描述标量值，不强行归一。
- 测试：算子/工作流/引擎相关测试 **471 passed / 1 failed**（唯一失败为 `test_database_production` alembic 基线漂移，属环境预存问题）；全量后端套件 1978 passed / 8 failed，失败均为迁移基线/发布修订号/Docker 契约类预存问题，与本次改动无关。

### 2026-09-21 修复多端口算子的半圆端口超出节点圆角边框

- 现象：Spot Weld Feature Engineering 等多输出端口算子，右侧半圆端口标签落在节点 30px 圆角弧区（顶部 <17% / 底部 >83%），视觉上凸出圆弧轮廓外。
- 根因：`CustomNode.tsx` 的 `portStyle` 通用分布公式 `(index+0.5)/total*100%` 未避开圆角弧区；spot-weld 3 输出有专用紧凑布局（34/50/66%）不受影响，但端口数 ≠3 的节点（如快照中保存了 4+ 输出）底部端口会落在 87.5%/91.7% 处。
- 修复（frontend `CustomNode.tsx`）：spot-weld 3 输出紧凑布局放宽为 20/50/80%（30% 间距）；所有 4 输出端口的算子采用同风格均匀分布 20/40/60/80%（20% 间距，同处 20%–80% 直边带）；其余端口数走通用公式 `16 + ((index+0.5)/total)*68`（16%–84% 带，带边缘对 30px 圆弧凸出为亚像素级）；单端口 50% 不变；应用户要求多轮放宽间距并对 4 输出算子统一风格。
- 测试：`CustomNode.test.tsx` 回归用例同步更新（3 输出 20/50/80%，4 输出 20/40/60/80%）；该文件 + `WorkspacePage.test.tsx` **23/23 passed**，tsc 通过。

### 2026-09-21 测试工作流算子链合理性验证

- 算子链验证（backend 冒烟脚本，已清理）：用清洗后数据（剔除 101 个纯逗号空行，保留 46 条真实记录）直接跑 `build_feature_frame`，产出标准 73 特征 schema（46×73），特征工程算子链本身可用。结论：`csv_import → spot_weld_feature_engineering → write_csv` 合理；当前工作流中的 `missing_value_handler(mean)` 不合理——源数据缺失值全部来自垃圾空行（均值填充无法修复 base64 波形列，还会静默改写真实数据），建议删除该节点并清洗源文件，或在 csv_import 后用 `filter_examples` 过滤空行（registry 共 82 个算子，端口契约一致）。
- 说明：同日曾做过工作流画布算子样式重设计（紧凑卡片 + 状态色条 + 圆形端口），应用户要求已全部撤销，`global.css` 与 `CustomNode.test.tsx` 恢复原样（176×176 方形卡片 + 外凸条形端口）。

### 2026-09-21 工作流导出数据集版本失败：operator_id 以字符串写入 UUID 列触发 'str' object has no attribute 'hex'

- 现象：工作流运行在持久化数据集版本时报 `(builtins.AttributeError) 'str' object has no attribute 'hex'`，INSERT INTO dataset_versions 失败，运行整体 failed。
- 根因：`services/workflow_execution.py` 以 `operator_id=str(workflow.created_by)` 构造 DAGExecutor；`services/artifact_service.py` 的 `create_dataset_version_from_artifact` 将该字符串直接写入 `DatasetVersion.operator_id`（`models/data_version.py` 中为 `UUID(as_uuid=True)`，外键 users.id），SQLAlchemy Uuid 绑定处理器调用 `value.hex` 时对字符串抛 AttributeError。其余字段（project_id/original_artifact_id）为 UUID 对象故未触发。
- 修复（backend `services/artifact_service.py`）：`create_dataset_version_from_artifact` 入口统一 `operator_id = uuid.UUID(str(operator_id))`，与 `create_from_file` 对 project_id 的边界转换约定一致，同时保护所有调用方（含 `api/datasets.py` 回填路径）。
- 测试：`test_artifact_service.py` + `test_operator_artifacts.py` + `test_workflow_execution_service.py` **17/17 passed**（miniconda Python）。
- 说明/限制：本地 SQLite 已存在的历史 failed 运行不会自动恢复，需重跑工作流；后端以 --reload 运行则修复自动生效。

### 2026-09-20 「保存到数据管理」标签列名检测：中文名称必须重命名为英文标识符

- 需求（接上轮）：标签名称也需要检测——如果标签名称为中文，则需要用户修改为英文才能保存到数据管理。
- 实现（backend `services/annotation_returns.py` + `api/annotation_returns.py`）：
  - `_validate_export_renames`：导出请求新增 `renames`（machine_key → 新列名），新列名必须匹配 `^[A-Za-z_][A-Za-z0-9_]*$`、不得与源数据其他列/其他标签列/已用目标名冲突、key 必须是已知标签列，否则 EXPORT_LABEL_NAME_INVALID(422)。
  - `export_return_batch_dataset` 应用重命名：列定义名、样本值键、parse_contract.label_renames 均改用新名；string 标签值映射在新列名下写入。
- 实现（frontend `api/annotationReturns.ts` + `components/ReturnAcceptancePanel.tsx` + i18n + global.css）：
  - `exportReturnBatchDataset` 增加 renames 参数（POST body {name, renames}）。
  - 中文名检测 `needsEnglishName = /[^\x00-\x7F]/.test(key)`：含中文名列时即使值类型为数值也不直接保存，而是展示确认区（红色「中文名称 · 需改为英文」标签 + 英文名输入框，校验英文标识符格式）；所有中文名列未填合法英文名前「确认映射并保存到数据管理」禁用；提交时只携带已填写的 renames。关闭 Drawer 一并重置。
  - apiErrors 补充 EXPORT_NAME_REQUIRED / EXPORT_LABEL_VALUE_UNMAPPED / EXPORT_LABEL_NAME_INVALID 中英文翻译。
- 测试：backend 新增 `test_export_renames_label_columns_to_english_identifiers`（合法重命名落列名/样本/契约、中文目标、冲突目标、未知列四种拒绝）——**18/18**；frontend ReturnAcceptancePanel.test.tsx 新增中文名重命名用例（含确认按钮禁用/启用与 renames 透传断言），既有断言更新为三参调用——面板 **8/8**、全量 vitest **346 passed / 19 skipped（63 文件）**、tsc 通过。
- 说明/限制：线上端到端验证未执行——当前 admin 仅剩「点焊」项目且无回传批次（原含已验收批次的 test 项目已删除），中文列名场景由后端/前端单测覆盖；后端 --reload 已自动生效。

### 2026-09-20 向导蓝框四调：机器键/标签名称同行 + 契约预填默认列 + 删除列保护 + 策略编辑器保存 schema 前锁定

- 需求（接上轮）：①机器键和标签名称放到一行；②默认标签列预填模型输出契约信息（名称、类型）；③添加删除操作——新增列可删、契约默认列可改不可删、至少保留一个标签列；④必须先填写标签列定义并保存 schema，之后才能编辑自动标注策略。
- 实现（frontend `components/LabelSchemaEditor.tsx` + `pages/DataAnnotationPage.tsx` + `styles/global.css`）：
  - 组件：卡片头部改为「机器键只读徽标 + 标签名称输入」同行（`__card-head/__identity`），值类型/约束方式第二行并排栅格（`__grid--pair`）；新增 `isDefault` UI 态标记与「删除列 N」按钮（仅非默认列且列数 > 1 时显示），契约默认列可修改但不可删除。
  - 向导：蓝框 initialColumns 在未保存 schema 时按 `selectedGenericOutputColumns` 预填（machine_key=label-N 只读、display_name/value_type 取契约、isDefault=true）；左侧策略编辑器在 `genericAutoSchema` 为空时替换为虚线锁定提示卡（「请先在右侧填写标签列定义并保存 schema」），保存后渲染编辑器并按新列重建草稿；`saveGenericStrategy` 强制要求已保存 schema（去掉自动创建 fallback），「保存策略并完成」按钮同步加 `!genericAutoSchema` 禁用。
  - 行为变化：策略配置 JSON 的标签 key 由契约 machine_key（如 fault/label）变为保存 schema 的列键 label-N（display_name 仍取契约名，策略编辑器可见文案不变）；后端 PUT 校验 0 列 schema 的 LABEL_SCHEMA_REQUIRED 防线依旧兜底。
- 测试：LabelSchemaEditor.test.tsx 新增默认列不可删/新增列可删例（9 例）；DataAnnotationPage 4 个向导用例（cluster 保存、重命名同步、导入策略、rule 保存）增加「填枚举值 → 保存 schema → 解锁」步骤并锁定态断言，PUT 断言键改为 label-1，导入策略 mock payload 键同步 label-1，保存 schema 名称断言用重命名后任务名（创建时已同步）。
- 验证：组件+页面 69/69；前端全量 vitest **345 passed/19 skipped（63 文件）**、`tsc --noEmit`、`npm run build` 通过。
- 说明/限制：保存 schema 后再次修改蓝框列不会自动重新保存（需再点保存 schema，且策略已按旧列保存的场景建议重新核对）；「配置策略」Modal 与标签 schema 管理页不受锁定影响（Modal 走独立保存流）。

### 2026-09-20 「保存到数据管理」导出改为真实文件制品：保持源数据集文件类型，修复预览报错

- 需求：数据管理中点击导出数据集的「预览」报错 `Artifact file is missing`；要求导出制品与原始文件保持相同类型（源为 csv 则导出 csv），文件类型自动跟随不允许修改，重名自动改名。
- 根因：上轮导出直接在 DB 创建 Artifact（storage_path=""、无 storage_uri、format="annotation"），而预览/下载走 `ArtifactService.materialize` → 无文件可读。
- 实现（backend `services/annotation_returns.py`）：
  - `_export_file_format`：从验收版本的 parse_contract.source_dataset_version_id 找到源 DatasetVersion → 其 original_artifact 的 format（csv/xlsx/xls/parquet），类型自动跟随源文件、用户不可选；无源制品时回退 csv；不支持的类型报 EXPORT_FILE_TYPE_UNSUPPORTED。
  - `_write_export_table_file`：csv 用标准库逐行写（表头=列名，string 标签已映射为整数）；xlsx/parquet 走 pandas。
  - 导出改用 `build_artifact_service(db).create_from_file(...)` 落真实文件（storage_uri、file_size、sha256、format 由文件后缀决定），数据管理预览/下载/物化与上传数据集完全一致；parse_contract 增加 source_file_format。重名 -2 后缀逻辑保持。
- 测试：test_annotation_return_acceptance.py 导出用例改注入 `ArtifactService(db, LocalStorage(tmp_path))`（monkeypatch app.services.annotation_returns.build_artifact_service），新增断言 artifact.format=="csv"、storage_uri 非空、materialize 读出文件内容 ["feature,result","1,0","2,1"]——**17/17**。
- 线上验证：删除上轮生成的无文件坏制品（ass 验收导出）；重新导出后 GET /api/datasets/{id}/preview 正常返回（147 行、75 列、label int64、前 10 行数据完整）。后端 --reload 自动生效。

### 2026-09-20 回传验收新增「保存到数据管理」：已验收批次导出为命名数据集，string 标签自动映射为整数

- 需求：主平台回传验收 Drawer（红框位置）为已验收任务添加「保存到数据管理」按钮；需要输入名称并检测标签类型——int/float 标签直接保存，string 标签需建立映射（标签值 → 0,1,2,3,…）。
- 实现（backend `services/annotation_returns.py` + `api/annotation_returns.py`）：
  - `GET /api/annotation-return-batches/{id}/export-preview`：校验批次 state=accepted 且 accepted_dataset_version_id 存在（否则 EXPORT_BATCH_NOT_ACCEPTED），基于任务快照 label_schema 逐列返回 {machine_key, value_type, mapping}；string 列扫描验收版本样本收集去重值，按枚举顺序优先、其余按首次出现顺序编号 0,1,2…。
  - `POST /api/annotation-return-batches/{id}/export-dataset`（body {name}）：创建 Artifact(type=dataset, metadata.source="annotation_return_export"，项目内重名自动 -2 后缀) + DatasetVersion（original_artifact_id 关联，version=项目最大+1，status=ready，parse_contract 记录 source_dataset_version_id/label_mappings）；样本复制验收版本并应用映射，string 标签列 dtype 写为 int；验收版本本身不被修改；写入 AuditEvent(annotation_return.exported_dataset)。权限与 accept/return 一致（require_return_batch_project_owner）。
  - 错误码：EXPORT_BATCH_NOT_ACCEPTED(409)、ACCEPTED_DATASET_VERSION_NOT_FOUND(404)、EXPORT_NAME_REQUIRED(422)、EXPORT_LABEL_VALUE_UNMAPPED(409)。
- 实现（frontend `api/annotationReturns.ts` + `components/ReturnAcceptancePanel.tsx` + global.css）：Drawer 中 state=accepted 的批次在底部新增「保存到数据管理」区块——名称输入（必填）+「检测标签并保存」按钮；preview 全为数值列时直接保存；含 string 列时展示每列映射表（标签值→整数）并由「确认映射并保存到数据管理」提交；成功提示数据集名与行数。关闭 Drawer 重置导出状态。
- 测试：backend test_annotation_return_acceptance.py 新增 3 例（未验收批次拒绝导出/预览、预览返回 string 映射 {pass:0,fail:1}、导出创建命名数据集+int 化标签+验收版本不变+重名 -2 后缀）——**17/17**；回归 `-k "portal or return or annotator or dataset or assignment"` 301 passed（8 个失败均为预先存在：7 个缺 pyarrow/fastparquet 环境、1 个陈旧测试 test_api_annotations 调用已删除的旧端点）。frontend ReturnAcceptancePanel.test.tsx 新增 2 例（string 映射确认流程、数值列直接保存无映射步骤）——面板 **7/7**、全量 **344 passed / 19 skipped**、tsc、build 通过。
- 线上验证：后端 --reload 自动生效；任务「ass」已验收批次（147 条，label 为 int）实测 export-preview 返回类型检测、export-dataset 创建「ass 验收导出」（v10，147 行 75 列，label 列 dtype=int），数据管理列表 GET /projects/{id}/datasets 第一位可见且 schema 完整。

### 2026-09-20 向导蓝框 schema 编辑器三调：去「最大字节数」+ 卡片式分区重排 + 样式对齐页面板块

- 需求（接上轮）：①去掉 string 类型的「最大字节数」输入，默认后端兜底不溢出即可；②重新设计文字/选择框位置排布，更清晰美观；③样式与页面其他板块一致。
- 实现（ml-platform/frontend `components/LabelSchemaEditor.tsx` + `styles/global.css`）：
  - 移除「最大字节数」输入与保存时的 `max_length` 透传（后端 `max_length ≤ 65536` 上限校验兜底，无输入即不限制）；类型切换时也不再清理该字段。
  - 布局重排为「每列一张卡片」：卡片内第一行为四字段自适应栅格（机器键只读徽标 | 标签名称 | 值类型 | 约束方式），枚举值区（值标签横排 + 「+」追加 + 行删除）与范围区（最小值/最大值并排栅格）仅在对应约束方式下出现，列说明全宽垫底；工具栏左侧新增「标签列定义」标题，右侧集中用途（可选展示）/添加列/保存 schema（主按钮样式）；枚举值与列说明 label 内嵌灰色 hint 小字（「点击 + 逐个添加；值须与所选类型匹配，不能为空」/「选填，展示给标注员的填写指引」）。
  - CSS 重写为页面同款视觉语言：`--border-default` 边框 + `--bg-surface` 卡片、8px 圆角、12px 次级色加粗 label、34px 高输入/选择框（与 `.data-annotation__setup` 表单完全一致）、antd 按钮类（ant-btn-sm / 主按钮）、机器键虚线边框等宽字体徽标。
- 验证：`LabelSchemaEditor.test.tsx` 8 例（aria-label 全部保持不变，无需改动）+ DataAnnotationPage 60/60 通过；前端全量 vitest **342 passed/19 skipped（63 文件）**、`tsc --noEmit`、`npm run build` 通过。
- 说明/限制：aria-label 与交互契约与上轮一致（机器键只读、约束必选默认枚举值、+ 添加枚举值），仅视觉与信息架构调整；标签 schema 管理页与「配置策略」弹窗同步获得新样式。

### 2026-09-20 向导蓝框 schema 编辑器再调整：机器键只读、约束必选默认枚举值、枚举值 + 逐个添加与类型校验

- 需求（接上轮蓝框调整）：①机器键默认 `label-1`（自动递增），去掉输入框不可修改；②约束方式去掉「无约束」，默认枚举值；③枚举值改为「+」按钮逐个添加值（每值一行、可删除），并加校验——值与所选类型必须匹配且不能为空。
- 实现（ml-platform/frontend `components/LabelSchemaEditor.tsx`）：
  - 机器键由 `<input>` 改为只读 `<span>` 徽标展示（等宽字体灰底），新建列 `label-N` 自动递增，保存时直接采用；仍保留键唯一性校验（回显数据兜底）。
  - `constraint_mode` 类型收窄为 `enum | range | enum_range`（去掉 none），新列默认 `enum`；旧数据回显无约束时兜底为枚举值；string 列仅可选枚举值。
  - 枚举值区块重写为值列表：每行一个输入框（string 为 text、int/float 为 number）+ 行删除按钮，底部「+」按钮追加一行；类型切换时清空约束值。
  - 保存校验：枚举值不能为空且必须匹配所选类型（int 须整数、float 须有限数字、string 非空）；范围方式下最小值/最大值必填且匹配类型、min ≤ max；错误提示带列名与期望类型。
- 样式：global.css 新增 `.label-schema-editor__machine-key`（只读徽标）与 `.label-schema-editor__enum(-row)`（枚举行纵排）。
- 验证：`LabelSchemaEditor.test.tsx` 重写 8 例（只读机器键、默认枚举方式、enum_range 保存、空值/类型不匹配/缺范围拒绝、string 仅枚举、+ 添加与行删除、showPurpose=false、用途与列说明）；DataAnnotationPage 60/60；前端全量 vitest **342 passed/19 skipped（63 文件）**、`tsc --noEmit`、`npm run build` 通过。
- 说明/限制：任务列表「配置策略」弹窗与标签 schema 管理页共用该编辑器，回显旧无约束 schema 时约束方式兜底显示为枚举值（需补填枚举值后才能保存）；向导默认列 `label-1` 未保存 schema 时策略编辑器仍按契约列（fault）展示。

### 2026-09-20 管理员门户孤儿任务过滤：项目已删除的任务不再出现在评审列表

- 需求：管理员审核门户出现多个主平台（数据标注/数据管理）中看不到的任务。
- 根因（DB 复盘）：项目删除是硬删除（projects.py 只级联清理 TrainingJob/Experiment/Dataset/OrchestrationApp，**不处理 GenericAnnotationTask**），这些任务的 project_id 指向已不存在的项目成为孤儿任务；主平台任务列表要求 `project_id ∈ 可访问项目`（annotation_task_state.list_annotation_tasks L494-503），孤儿任务永远不显示；而管理员门户列表（annotator_internal.internal_admin_tasks）只过滤 `owner_id == admin AND archived_at IS NULL`，不校验项目存在，孤儿任务全部列出且项目列显示"—"（如 d4731b02/b0c52048/a8d4772a/9ab26fdc，均为 9/14-9/15 创建、项目已删）。
- 实现（backend annotator_internal.py）：internal_admin_tasks 查询增加 `GenericAnnotationTask.project_id.in_(select(Project.id))`，与主平台口径一致——项目已删除的孤儿任务不再返回（total 同步减少）。sqlalchemy 导入增加 select。
- 测试：test_portal_admin_review.py 新增 `test_admin_task_list_excludes_tasks_of_deleted_projects`（构造 project_id 指向不存在项目的任务 → 列表不含该任务且其余任务不受影响）。
- 验证：test_portal_admin_review.py **24/24**；回归 `-k "portal or return or annotator or concurrency or assignment"` **240 passed / 6 skipped**；本地后端 --reload 自动生效，网关 8444 实测 admin/admin123 登录后 GET /portal/admin/tasks 已不含 4 个孤儿任务（列表 6 条均带真实项目名）。
- 说明/限制：仅过滤列表展示，孤儿任务数据未删除（若未来做项目删除级联需另行评估）；任务详情/样本/批注等单任务端点未加项目存在性校验（深链不可达，风险低）。

### 2026-09-20 向导蓝框标签 schema 编辑器简化：去「用途」、默认列 label-1/标签-1、必填固定、约束方式按类型限定

- 需求（新建自动标注任务向导第 2 步蓝框）：①去掉「用途」选择；②默认列不再预填契约列名 fault，左侧机器键默认 `label-1`（自动递增），右侧为「标签名称」；③去掉「必填」勾选，默认必填；④约束方式按类型限定——int/float 可选 枚举值/范围/枚举值且范围（外加默认无约束），string 只能选枚举值。
- 实现（ml-platform/frontend `components/LabelSchemaEditor.tsx`）：
  - 新增 `showPurpose` 属性（默认 true 展示用途；向导蓝框传 false 固定 annotation，标签 schema 管理页等其他使用处不受影响）。
  - 默认列工厂 `label-N`/`标签-N`（按现有键去重递增），右侧输入 aria-label/占位改为「标签名称」；移除「必填」勾选，保存时 `required` 恒为 true。
  - 每列新增「约束方式」下拉（无约束/枚举值/范围/枚举值且范围；string 隐藏后两项），枚举值与最小值/最大值输入仅在对应方式下出现；约束方式存 UI 态 `constraint_mode`（不随空枚举值回退为无约束），已保存 schema 回显时按已有约束值推导；切换列类型时清空约束并重置方式选择。
  - 机器键校验正则放宽允许连字符（`[A-Za-z_][A-Za-z0-9_-]*`）。
- 实现（其他）：
  - 后端 `schemas/labeling.py` machine_key 校验同步允许连字符（向后兼容放宽）；`tests/test_label_schema_api.py` 新增 `test_schema_machine_key_allows_hyphen`（创建 label-1 后 GET 回读校验）。
  - `DataAnnotationPage.tsx` 向导蓝框：`showPurpose={false}`；未保存 schema 时默认一列 `label-1`/`标签-1`（不再预填契约列 fault）。
- 验证：`LabelSchemaEditor.test.tsx` 重写/扩充 6 例（默认列命名、约束方式先选后填、string 仅枚举、showPurpose=false 隐藏用途且 required 恒 true 等）；DataAnnotationPage 60/60；前端全量 vitest 63 文件 340 passed/19 skipped（此前一次全量出现 TrainingJobsPage 偶发超时，复跑全绿）、`tsc --noEmit`、`npm run build` 通过；后端 labeling 套件 23 passed。

### 2026-09-20 标注员/管理员门户会话兼容：viewer 改 sessionStorage 按标签页隔离 + 「[object Object]」错误修复 + 登出只清当前身份

- 需求：标注员门户与管理员审核门户仍互不兼容——登录管理员账号后，已登录的标注员标签页报错「[object Object]」；刷新标注员门户会被自动跳转到管理员门户。
- 根因（两个独立缺陷）：
  - viewer 身份提示（`portalViewer`）原存 localStorage，同源所有标签页共享：管理员标签页登录后写入 `admin`，其他已打开的标注员标签页随后的所有请求都带 `X-Portal-Viewer: admin`，网关据此把请求路由到 admin 会话 → 标注员请求 403/结构化错误；刷新时 App.tsx 的 me() 也按 admin 会话解析 → 显示管理员界面（表现为「自动跳转」）。
  - 前端错误提取 `payload?.detail?.message ?? payload?.detail`：当 detail 是 `{code: ...}` 而无 message 时，整个对象成为 Error message，React 渲染为 `[object Object]`。
- 实现：
  - annotator/frontend `api/client.ts`：`getPortalViewer/setPortalViewer` 从 localStorage 改为 **sessionStorage**（每标签页独立、刷新保持、新标签默认 annotator），管理员登录不再影响其他标签页；错误提取改为类型判断——detail 为字符串用之，否则依次取 `detail.message`/`detail.code`，最后回退 `Request failed (status)`，并把 `error.response = {status, data}` 附在 Error 上供组件读 code。
  - annotator/backend `api/auth.py` logout：新增 `X-Portal-Viewer` Header 参数，只删除当前 viewer 对应的 cookie（annotator 删 `portal_session`、admin 删 `admin_portal_session`），管理员登出不再杀掉共存标注员会话。
- 测试：annotator/frontend 新建 `api/client.test.ts` 6 例（sessionStorage 而非 localStorage、默认 annotator、每请求带头、结构化 detail 不出现 "[object Object]"、message 优先于 code、字符串/缺 detail 回退）；后端 test_portal_api.py 更新登出测试并新增 `test_portal_logout_admin_viewer_only_clears_admin_cookie`。
- 验证：门户全量 vitest **103 passed（14 文件）**、`tsc --noEmit`、`npm run build`（bundle index-UEkagjaR.js）；网关 `pytest tests/` **30 passed**；`docker compose build annotator annotator-frontend && up -d && restart annotator-frontend` 部署完成，8443 返回页已引用新 bundle、网关 logout 健康检查 204。
- 说明/限制：旧 localStorage 中的 portalViewer 残留不再读取，无需清理；两个门户标签页需 Ctrl+F5 强刷各一次，之后管理员与标注员可在同一浏览器并存互不干扰。

### 2026-09-20 回传 ANNOTATION_NOT_READY：确认后保存使确认失效，前端自动重新确认并重试

- 需求：标注员门户完成标注后，在「回传」页点击「确认任务」再点「发起回传」报错 `the whole task scope must be confirmed before return`（ANNOTATION_NOT_READY，422）。
- 根因（线上 DB 复盘任务 473ca645「ass」，147 样本）：确认后任何一次标签保存（如 600ms 防抖自动保存/排队保存与确认并发落库）都会把任务状态从 awaiting_return 重置为 in_progress（save_labels 的契约行为），该样本在当前修订上的确认随之失效；`return_assignment` 校验 `task.status != "awaiting_return"` 即拒绝。前端 `confirmed` 标记与后端状态可短暂不一致（保存与确认的响应顺序），用户看到的是一条无解释的英文错误。用户重试（再次确认→回传）实际能成功（06:52 批次已建，06:57 被管理员退回为 returned_for_changes，属正常流程）。
- 实现：
  - annotator/frontend TaskWorkspacePage.tsx：①`confirm()` 先冲刷所有 dirty 草稿（清防抖定时器并 await save，任一保存失败则中止确认），杜绝「确认后保存」窗口；②`sendReturn()` 捕获 `ANNOTATION_NOT_READY`（读 `err.response.data.detail.code`，新增 `apiErrorCode` 助手）时自动重新 `confirmTask` 并重试一次回传，成功则提示「检测到确认后有新的修改，已自动重新确认并发起回传」；重试仍失败则显示中文指引（任务范围尚未全部确认…重新点击「确认任务」），不再暴露裸英文错误码。
  - backend annotation_concurrency.py：`return_assignment` 的 ANNOTATION_NOT_READY 报错文案改为 `labels changed after confirmation; confirm the task again before return`（更准确指向根因；无测试匹配旧文案）。
- 测试：TaskWorkspacePage.test.tsx 新增 2 例（回传遇 ANNOTATION_NOT_READY 自动重确认+重试成功；重确认仍失败时显示友好中文提示）。
- 验证：组件 49/49、门户全量 vitest **97 passed（13 文件）**、`tsc --noEmit`、`npm run build`（bundle index-Cjnbn_ru.js）；后端 `pytest -k "portal or return or annotator or concurrency or assignment"` **239 passed / 6 skipped**；annotator-frontend 容器已重建部署，8443 已引用新 bundle。
- 说明/限制：「确认后修改会使确认失效、需重新确认」是既定安全契约（防止未审内容被回传），本次不改后端状态机，只修复前端竞态窗口与自动恢复；本地后端若以 --reload 运行则新文案自动生效。

### 2026-09-20 聚类向导蓝框：恢复标签 schema 编辑器 + 策略库（保存/导入策略）+ 执行发布 LABEL_SCHEMA_REQUIRED 根因修复

- 需求：新建自动标注任务报 `LABEL_SCHEMA_REQUIRED`；同时按截图要求——若 schema 必填，则在蓝框位置（聚类效果预览生成后、策略编辑器右侧）添加标签 schema 编辑器，并在同位置提供「保存策略」（保存当前页面管理员配置的标注规则）与「导入策略」（从已保存策略导入到左侧自动标注策略编辑器）按钮。
- 根因（LABEL_SCHEMA_REQUIRED）：发现任务创建时 `task.task_snapshot` 写入空占位 label schema 且之后永不更新；PUT /configuration 换绑新 schema 后权威快照在 `annotation_task_revision_snapshots`，但执行 worker `_publish_execution_label_state` 仍读取过期的 `task.task_snapshot` → 解析出 0 列 → LABEL_SCHEMA_REQUIRED。
- 实现（后端）：
  - `tasks/annotation_execution_tasks.py`：`_publish_execution_label_state` 改用 `current_annotation_task_snapshot(db, task)`（按 task_revision 解析 revision 快照，无则回退 task_snapshot），再回退 `task.label_snapshot`。
  - 新增可复用策略存储：`models/labeling.py` 新表 `saved_annotation_strategies`（project_id+name 唯一，新表由启动 create_all 创建，无需迁移）；`schemas/labeling.py` 新增 `SavedAnnotationStrategyCreate`（校验 payload.strategy ∈ {cluster, rule, cluster_rule}）；`api/annotations.py` 新增 `GET/POST /api/annotations/saved-strategies`（列表用 `project.read`、保存用 `resource.create` 权限；同项目同名 upsert 覆盖更新）。
- 实现（前端，ml-platform/frontend）：
  - 新增 `api/savedStrategies.ts`（listSavedStrategies / saveAnnotationStrategy）。
  - `DataAnnotationPage.tsx` 向导第 2 步：聚类预览（全宽）下方恢复 `cluster-split` 双栏——左侧自动标注策略编辑器，右侧（蓝框）为 LabelSchemaEditor + 策略库块（策略名称输入 + 保存策略按钮；已保存策略下拉 + 导入策略按钮）；恢复 `genericAutoSchema` 状态，`effectiveAutoColumns` 优先用已保存 schema 列；`saveGenericStrategy` 优先绑定已保存 schema，未保存时仍按模型输出契约列自动创建（流程不中断）；进入第 2 步聚类流程时自动加载项目已保存策略；导入时以当前列集合补齐 otherValues/rules 兜底。
  - `i18n/index.tsx` 更新 clusterPreviewReadyHint 中英文；`global.css` 新增 `.data-annotation__strategy-library(-row)` 样式。
- 测试：后端新增 `test_saved_annotation_strategies_api.py`（upsert/列表/权限/非法 payload，已登记 week_manifest）与 `test_annotation_task_state.py` 回归 `test_execute_worker_publishes_with_rebound_schema_after_discovery_strategy_save`（task_snapshot 留空占位 + revision 快照换绑 → 执行成功发布标签；task_snapshot 有不可变保护，测试经 Core update 改写）。
- 验证：后端 3+71+22（labeling 套件）全部通过；前端 DataAnnotationPage 60/60（新增导入策略测试、保存策略断言改正向）、`tsc --noEmit`、`npm run build` 通过；全量 vitest 337 passed/19 skipped，1 例 TrainingJobsPage 偶发超时单独复跑通过（与本次改动无关）。
- 说明/限制：策略 payload 直接存前端 camelCase 草稿，跨模型复用时导入端按当前输出列合并兜底；标签列名对不上时需管理员重新核对映射。

### 2026-09-20 门户刷新已删除任务：工作区降级为友好提示页而非裸错误码

- 需求：标注员门户在浏览器点刷新时报 `ANNOTATION_TASK_NOT_FOUND`，页面只显示一行裸错误码、无返回入口。
- 根因：深链 `?task=` 会在刷新后重新打开对应工作区；若任务此后被删除（如管理员删除回传任务），`getTask` 返回 404，TaskWorkspacePage 的 `error && !task` 分支只渲染 `<p className="error">{error}</p>`（原始错误码、无按钮）。
- 实现（ml-platform/annotator/frontend）：
  - TaskWorkspacePage.tsx：新增 `taskMissing` 状态，初始加载 catch 中读取 `err.response.status`（client.ts 已附带），404 时置位；`error && !task` 分支改为友好页——「标注工作区」标题 + `任务不存在或已被删除，无法打开标注工作区`（非 404 仍显示原始错误）+ 「返回任务列表」按钮（onBack）。
  - AdminReviewPage.tsx：同样在任务加载 catch 中对 404 显示 `任务不存在或已被删除，无法打开评审工作区`（该页本就有返回按钮，仅替换裸错误码文案）。
- 测试：TaskWorkspacePage.test.tsx 新增 1 例（getTask 拒绝 404 → alert 显示友好文案且不含裸错误码、返回按钮触发 onBack）。
- 验证：组件 47/47、门户全量 vitest **95 passed（13 文件）**、`tsc --noEmit`、`npm run build` 通过（bundle index-DuFeNypf.js）；`docker compose build annotator-frontend && up -d` 已部署，8443 返回页引用新 bundle。
- 说明/限制：任务被删除后门户端 404 行为本身正确（契约：已删除任务的门户端点一律 404），本次仅修复前端兜底展示；用户需 Ctrl+F5 强刷门户页拿到新 bundle。

### 2026-09-20 回传验收面板重设计：与「任务操作记录」卡片网格同款样式

- 需求：主平台数据标注页中的「回传验收」区块重新设计，样式与上方「任务操作记录」保持一致。
- 实现（ml-platform/frontend）：
  - ReturnAcceptancePanel.tsx 重构：外层改为 `table-surface data-annotation__operations-surface` + `data-annotation__section-head`（h3「回传验收」+ ant-btn-sm 刷新按钮）；批次从「左侧按钮列表 + 右侧固定详情栏」两栏布局改为与操作记录相同的 `data-annotation__operations` 自适应卡片网格（minmax(280px,1fr)），每张卡片复用 `data-annotation__operation` 结构——head（任务名 code + 状态 Tag：待验收/已验收/已退回）、meta（标注员 · 样本数）、任务短 id 行、创建时间、操作按钮（pending 且 operation_state=completed 时「打开验收」，否则「查看摘要」）；空态 Empty「暂无回传批次」、加载 Spin、加载更多按钮均与操作记录一致。
  - 验收操作从右侧常驻详情栏移入 antd Drawer（480px，rootClassName=annotation-return-panel-drawer）：任务/标注员/批次状态/样本数/修订/质量风险摘要、跳转标注员门户按钮（`?task=&viewer=admin`）、退回原因 textarea 与验收/退回按钮（仅 pending 且操作完成时渲染）；不再自动选中首个批次，打开抽屉才加载 diff 计算质量风险。
  - global.css：删除旧 `annotation-return-panel__batch*` 卡片样式，新增 `__notices`（错误/成功提示条）、`__action`、抽屉正文 p/textarea 与 `annotation-return-panel-drawer` portal 选择器、保留 `__hint`。
- 测试：ReturnAcceptancePanel.test.tsx 重写为 5 例（卡片上下文与无样本明细、抽屉内验收含门户跳转、退回必填原因、非 pending 批次仅摘要、空态）。
- 验证：组件 vitest 5/5、主前端全量 **337 passed / 19 skipped（63 文件）**、`tsc --noEmit`、`npm run build` 通过；5173 为 Vite dev server，HMR 自动生效无需部署。
- 说明/限制：面板文案保持中文（与既有实现一致）；行为契约（验收/退回/门户深链/质量风险口径）未变，仅 UI 结构与样式重排。

### 2026-09-20 聚类向导第 2 步布局：删除 schema 编辑器、聚类预览全宽展示、重命名同步

- 需求（用户截图三处标注）：①删除聚类完成后向导第 2 步中的「自定义标签 schema」编辑器（红框）；②聚类预览面板（绿框）向右拉伸占满主列，K 指标等文字不得遮挡散点图的簇点；③任务因重名被后端自动改名时，右侧冻结契约摘要中的任务名称（蓝框）需同步为新名称。
- 实现（ml-platform/frontend）：
  - DataAnnotationPage.tsx：
    - 删除向导第 2 步 cluster-split 内的 LabelSchemaEditor 块与 `genericAutoSchema` 状态、`saveGenericAutoSchema` 函数；向导不再单独编辑标签列。
    - `saveGenericStrategy` 改为保存策略时自动以模型输出契约列创建 schema（`{任务名}-labels`，purpose=annotation）并随 PUT /configuration 换绑（`label_schema_id`），流程保持一步完成；`createGenericTaskFromSetup` 的 label_schema_id 展开同步简化（仅 manual schema 路径）。
    - `notifyAutoRenamedTask` 在提示 toast 的同时 `setGenericTaskName(task.name)` 同步向导与冻结契约摘要展示名；`saveGenericStrategy` 在 PUT 返回后同样调用（PUT 改名亦走 `_unique_task_name` 后缀），保证后续提交的是重命名后的名称。
    - 向导第 2 步聚类完成后移除 `data-annotation__cluster-split` 双栏，ClusterPreviewPanel 与策略编辑器在 setup-field 内纵向排列，聚类预览占满主列宽度（绿框拉伸）。
  - global.css：`.data-annotation__cluster-preview-body` 改单列（图表在上、簇数/评分等指标文字在下，不再与散点同排遮挡簇点；配置策略弹窗同组件同步受益）；散点图 svg max-width 420→560px。
  - i18n：clusterPreviewReadyHint 更新为「标签列将直接采用模型输出契约列」（中英）。
- 测试：DataAnnotationPage.test.tsx 移除 chooseUserLabelSchema 辅助与两处调用；第一个聚类测试补「保存 schema 按钮不存在」断言；新增「重命名同步」回归测试（创建返回 `聚类发现任务-2` → 契约摘要显示新名称，保存策略 PUT 携带新名称 + label_schema_id）。
- 验证：DataAnnotationPage + ClusterPreviewPanel 套件 65/65；全量 `npm test` 334 passed / 19 skipped（63 文件，基线 333+1 新增）；`tsc --noEmit`、`npm run build` 通过。
- 说明/限制：向导内不再支持自定义标签列（枚举值/边界等），如需自定义可在任务列表「配置策略」弹窗（占位任务 frozenLabelColumnCount==0 仍有 LabelSchemaEditor）完成；保存策略每次点击会新建一个 `{任务名}-labels` schema（与旧编辑器逐次保存行为一致）；浏览器实测待部署后补验（散点全宽、K 指标在图表下方、重名任务摘要同步）。

### 2026-09-20 双 cookie 会话隔离 + 已删除任务过滤 + 门户间进度同步

- 需求（四项）：1) 标注员账号与管理员账号在门户内必须严格区分（用户建议必要时新开 8444 管理员门户）；2) 管理员审核门户不得出现已删除任务；3) 主平台回传验收不得出现已删除任务；4) 各门户间任务进度完全同步。
- 方案选型：浏览器 cookie jar 不区分端口，同 hostname 的 8444 门户无法隔离会话；改为**双 cookie 名**——标注员 `portal_session`（DB 会话）、管理员 `admin_portal_session`（无状态 JWT）——配合 `X-Portal-Viewer` 请求头声明当前身份，同一浏览器可同时保持两个独立会话。
- 实现（主后端 ml-platform/backend）：
  - app/services/annotator_identity.py：新增 `ADMIN_PORTAL_COOKIE_NAME`；`resolve_portal_identity(request, db, *, viewer)` 按 viewer 分流——annotator 只读 `portal_session`（DB 会话查不到直接 PORTAL_SESSION_INVALID，旧 admin JWT 残留不再被误解析）；admin 只读 `admin_portal_session`（JWT kind=portal_admin）。
  - app/api/annotator_internal.py：portal_me 读 `X-Portal-Viewer` 头（默认 annotator）传给 resolve；portal_logout 同时删除两个 cookie（均带 secure/httponly/samesite）；`internal_admin_tasks` 每项新增 `completed_samples`（`AnnotationAssignmentSample` 中 `length(values) > 2` 的计数，与标注员门户同口径）与 `project_name`；任务列表本就过滤 `archived_at.is_(None)`（问题 2 经核为跨项目未删除的空名测试任务，加 project_name 辅助辨识）。
  - app/services/annotation_returns.py（问题 3）：`_project_rows` 查询补 `GenericAnnotationTask.archived_at.is_(None)` 过滤；`_batch_or_error` 对 archived 任务抛 ANNOTATION_TASK_NOT_FOUND（批次操作 404）。
- 实现（网关 ml-platform/annotator/backend）：
  - services/session.py：`require_portal_session` 读 `X-Portal-Viewer` 头选择 cookie 名，转发 `resolve_portal_session(token, viewer, cookie_name)`；services/platform_client.py me 请求携带对应 cookie 名与 viewer 头。
  - api/auth.py：login 依次匹配两种 Set-Cookie（**admin 名须先测**，因 `admin_portal_session=` 含子串 `portal_session=`）并把网关签发的 token 以正确 cookie 名落盘；logout 删除两个 cookie。
- 实现（门户前端 ml-platform/annotator/frontend）：
  - api/client.ts：`getPortalViewer/setPortalViewer`（localStorage），所有请求带 `X-Portal-Viewer` 头；api/auth.ts 登录成功后按返回 kind 写入 viewer。
  - App.tsx：挂载解析 `?viewer=admin` 深链参数（主平台回传面板「在标注员门户查看明细」按钮改为 `?task=&viewer=admin`）；顶栏 user-chip 增加身份徽标（管理员/标注员）。
  - api/admin.ts `AdminTaskListItem` 补 completed_samples/project_name；AdminQueuePage 显示 `进度 x/y` 与项目名。
- 测试：主后端 test_portal_admin_review.py 更新双 cookie 断言并新增共存/互斥 2 例（admin JWT 放入 annotator cookie 被拒）；test_annotation_return_acceptance.py 新增 `test_return_batches_of_deleted_tasks_are_hidden_and_actions_404`；AdminQueuePage.test.tsx 断言进度与项目名。主后端过滤套件 **229 passed / 5 skipped**、网关 **29 passed**、门户前端 **94 passed** + tsc + build（bundle index-Dk9b285a.js）、主前端 **333 passed / 19 skipped** + tsc + build；容器已重建部署（annotator + annotator-frontend + restart annotator-frontend 刷新 nginx IP 缓存）。
- 端到端实测（8443 线上）：jingms 真实登录 + 同 jar 铸 admin JWT——me 按 viewer 分别解析出 annotator/admin；admin 打 /portal/tasks → 403 PORTAL_ANNOTATOR_REQUIRED；admin tasks 返回 147/147 进度与项目名（任务 as，returned_pending_acceptance）；logout 一次性清双 cookie（删除头均带 Secure/HttpOnly/SameSite=lax）；清空 cookie 后 me → 401。
- 说明/限制：浏览器需重新登录两个账号（旧 `portal_session` 中的 admin JWT 会按 PORTAL_SESSION_INVALID 拒绝，属预期）；管理员会话仍为无状态 JWT（TTL 30 分钟，无吊销）；验证用临时脚本与含 token 的 jingms.txt 已清理。

### 2026-09-20 管理员登录后 SERVICE_SUBJECT_INVALID：门户前端旧 bundle + 网关 admin 会话误入标注员路由

- 需求：管理员在门户用 admin 账号登录成功后页面报 SERVICE_SUBJECT_INVALID，无法进入评审页。
- 根因（两层）：
  1. **门户前端容器跑的是旧 bundle（index-Dlpxkt6r.js，凌晨「侧栏 200px」会话的产物，早于管理员评审功能）**：旧前端不认识 `me()` 返回的 `kind=admin`，把管理员当普通标注员路由到 TaskWorkspacePage，深链 `?task=` 走标注员任务接口。
  2. **网关标注员路由对 admin 会话铸造坏 subject claim**：api/tasks.py、api/comments.py、api/notifications.py 全部 `subject_id=str(principal.subject_id)`，而 admin principal 的 subject_id 为 None → `"None"` 被写进 service token 的 `annotator_subject_id` claim → 主后端 `uuid.UUID("None")` 解析失败 → SERVICE_SUBJECT_INVALID。
- 实现（网关 ml-platform/annotator/backend）：
  - services/session.py 新增 `require_annotator_session`（以 `Depends(require_portal_session)` 作为子依赖，保持 FastAPI dependency_overrides 测试模式有效）：principal.subject_id 为 None（admin 会话）时 403 `PORTAL_ANNOTATOR_REQUIRED`。
  - api/tasks.py、api/comments.py、api/notifications.py 全部路由的会话依赖从 `require_portal_session` 换为 `require_annotator_session`；admin 路由（api/admin.py）与 me 不变。
  - tests/test_portal_api.py 新增 `test_portal_annotator_routes_reject_admin_sessions_with_clear_code`（admin principal 打 /portal/tasks、/portal/notifications、/portal/comments → 403 PORTAL_ANNOTATOR_REQUIRED）。
- 部署：`docker compose build annotator annotator-frontend && up -d && restart annotator-frontend`（重建 annotator 后必须重启 annotator-frontend 刷新 nginx 缓存的网关容器 IP）。**门户前端新 bundle index-uJowFCJs.js（含管理员评审页面）**，与「管理员登录评审」条目记录的 hash 一致。
- 验证：网关 `pytest tests -q` **29 passed**（28 基线 + 1 新增）；curl 实测——admin 门户 JWT 经 8443：me→200 kind=admin、/portal/admin/tasks→200 返回任务列表、admin 打 /portal/tasks→403 PORTAL_ANNOTATOR_REQUIRED（不再透出 SERVICE_SUBJECT_INVALID）。
- 说明/限制：本地主后端进程（uvicorn --reload）代码为最新无需重启；此前复现一度误报 SERVICE_ADMIN_REQUIRED，系复现脚本 UUID 抄写错误（`994221` 写成 `994421`），非系统问题；管理员此刻应 Ctrl+F5 强刷门户后重试登录评审。

### 2026-09-20 门户登出修复：Secure cookie 删除头缺 Secure 属性致浏览器忽略删除

- 需求：标注员门户点「退出」后界面回到登录页，但浏览器里 `portal_session` cookie 实际未被删除（登录页只是前端清了本地状态）；再从主平台回传面板点「在标注员门户查看明细」时 `me()` 仍解析出原标注员（jingms）身份，深链进的是标注员工作区而非管理员评审页，管理员无法用自己的账号登录评审。
- 根因：登录时网关 `response.set_cookie(COOKIE_NAME, token, httponly=True, secure=True, samesite="lax", path="/")` 带 `Secure`；登出时 `response.delete_cookie(COOKIE_NAME, path="/")` 生成的删除 Set-Cookie 不带 `Secure`/`HttpOnly`。按 RFC 6265bis「strict secure cookies」规则（Chrome/Edge/Firefox 已实现），删除带 `Secure` 标志的 cookie 时删除头也必须带 `Secure`，否则浏览器静默忽略该删除。curl 不校验 Secure 属性故服务端自测无法暴露此问题。
- 实现：
  - ml-platform/annotator/backend/app/api/auth.py logout：`delete_cookie` 补齐 `secure=True, httponly=True, samesite="lax"`（与 cookie_options() 一致）。
  - ml-platform/backend/app/api/annotator_internal.py portal_logout：同样补齐（登录 cookie 同为 secure=True 写入）。
  - 网关 tests/test_portal_api.py 新增 `test_portal_logout_deletes_cookie_with_matching_secure_flags`：断言登出 Set-Cookie 含 `portal_session=""`、`Max-Age=0`、`Secure`、`HttpOnly`、`SameSite=lax`。
- 验证：网关 `pytest tests -q` **28 passed**（27 基线 + 1 新增）；主后端 `-k "portal or return or comment or annotator"` **226 passed / 5 skipped**（与基线一致）。docker compose 重建 annotator 网关容器（注意：重建后需 `docker compose restart annotator-frontend` 刷新 nginx 缓存的网关容器 IP，否则 502）；curl 全链路实测：login（Set-Cookie 带 Secure）→ logout（删除头带 Secure/HttpOnly/SameSite=lax）→ me 返回 401 PORTAL_SESSION_REQUIRED。
- 说明/限制：主后端 portal_logout 不经浏览器直接调用（门户前端全部走网关），改动仅为一致性防御；登出仍只删浏览器 cookie，DB 中 AnnotatorSession 记录保留至 TTL 过期（30 分钟内被窃取的 cookie 值理论上仍可用，属既有设计）；管理员此刻重新操作：门户退出 → 主平台点「在标注员门户查看明细」→ 登录页用 admin 账号登录 → 直达 AdminReviewPage。

### 2026-09-20 管理员登录标注员门户评审（验收/退回/批注）

- 需求：管理员在主平台点「在标注员门户查看明细」后，用自己的管理员账号登录标注员门户：只看到自己创建的未归档任务；对已回传（存在 state=pending 回传批次）的任务可合格验收、退回修改、批注（逐条浏览样本+标注结果、批注自动保存）；未回传任务三项操作禁用并提示原因；管理员不能编辑标签值（只读）；普通标注员行为完全不变。
- 主后端（ml-platform/backend）：
  - app/services/annotator_identity.py：新增无状态管理员门户 JWT（`issue_admin_portal_token`，payload kind=portal_admin，复用 annotator_service 密钥/算法，TTL annotator_session_ttl_seconds，避免改 AnnotatorSession.account_id 非空 schema）；`resolve_portal_identity` 统一解析门户 cookie（先 DB 会话→annotator，失败再 JWT→admin）；`PortalSession`/`ServicePrincipal` 扩展 kind/user_id/admin_user_id 字段；`service_token_for_project` 支持 admin_user_id claim。
  - app/api/annotator_internal.py：login 端点先查 AnnotatorAccount 决定分支（annotator 账号存在时密码错不 fallback admin 路径），admin 登录签发 JWT cookie；me 返回 kind/user_id；新增 6 个内部端点 `/api/internal/portal/admin/tasks[/{task_id}[/samples|/comments|/accept|/return]]`——owner+未归档范围过滤、search（名称/短 id）、cursor 分页、样本按 row_index 排序（labels 取 AnnotationSampleCurrent 任务级当前值、values 按 visible_columns 过滤）、批注列表/创建（author_id=管理员 users.id，无 pending 批次 409 RETURN_BATCH_REQUIRED、越界样本 403）、accept 调 `accept_return_batch`、return 调 `reject_return_batch`（AnnotationReturnError→409）。
- 网关（ml-platform/annotator/backend）：
  - services/session.py：PortalPrincipal 支持 admin（subject_id=None、user_id）；services/platform_client.py service token 携带 admin_user_id claim（无 subject 时不加 annotator_subject_id）。
  - api/auth.py me 透传 kind/user_id；新增 api/admin.py 7 个 `/portal/admin/*` 路由（kind 校验 403 PORTAL_ADMIN_REQUIRED，读 admin_review:read/写 admin_review:write，结构化错误透传）；main.py 注册。
- 门户前端（ml-platform/annotator/frontend）：
  - api/auth.ts me 类型加 kind/user_id（kind 缺省视为 annotator）；新建 api/admin.ts（7 个端点封装）。
  - App.tsx：admin 分支路由（评审任务/评审工作区导航、`?task=` 深链直达评审页、admin 不渲染通知收件箱）。
  - 新建 AdminQueuePage：任务卡片（状态/模式/样本数/创建时间/标注员/回传状态：待验收/已验收/已退回/未回传）；合格验收/退回修改/批注三按钮仅 pending_return_batch_id 存在时可用，否则禁用+tooltip「任务未回传，不能验收/退回/批注」；验收确认弹窗（成功提示生成数据版本）、退回弹窗必填原因；操作后刷新列表。
  - 新建 AdminReviewPage：顶部任务名+返回+样本位置 x/N；上一条/下一条（按钮+←/→）；样本数据卡片网格（字段名小灰字+值加粗）+标注结果只读（label_schema 列名+当前值）；批注列表（作者/时间/内容）+输入框 800ms debounce 自动保存（内容非空且与上次已保存不同才 POST，保存后清空输入，Ctrl+Enter 或按钮手动提交）；无 pending 批次显示「任务未回传，无法批注」并禁用输入。
  - styles.css 追加 admin 样式（复用现有 token）。
- 测试：主后端新增 tests/test_portal_admin_review.py 21 例（admin 登录/me、annotator 不受影响、admin JWT 过期、service token admin claim、任务列表 owner 范围/搜索、详情只读、样本浏览/过滤、批注创建/越界/无批次、accept/return 全流程含冻结批次与数据版本生成）并登记到 tests/week_manifest.py week 8；网关 test_portal_api.py 更新 me 断言并新增 4 例（admin 身份、非 admin 403、admin 转发与 scope、结构化错误透传）；门户前端新增 AdminQueuePage.test.tsx 7 例、AdminReviewPage.test.tsx 7 例、App.test.tsx 补 2 例 admin 分支。
- 验证：主后端 `-k "portal or return or comment or annotator"` **226 passed / 5 skipped（8 subtests）**、test_suite_manifest **5 passed**；网关 **27 passed**；门户前端 vitest **94 passed（13 文件）**、`tsc --noEmit`、`npm run build` 通过（bundle index-uJowFCJs.js）。主后端全量套件 1957 passed / 109 skipped / **19 failed**，其中 18 个为与本功能无关的既有失败（pyarrow 缺失致 test_dataset_import_contract 7 例、Alembic 迁移头/发布证据常量与工作树未提交迁移不一致 5 例、Dockerfile 断言 2 例、离线推理子进程 1 例、onnx 转换子测试 2 例、升级夹具 1 例），1 个（test_suite_manifest 缺新模块登记）已由本次 week_manifest 登记修复并复验通过。
- 说明/限制：管理员门户会话为无状态 JWT（无 DB 会话记录、无吊销能力，TTL 30 分钟内有效）；admin 在门户不展示通知收件箱（通知端点为 subject 范围）；批注保存失败的草稿在切换样本时丢弃（错误状态已即时提示）。

### 2026-09-20 回传验收：批次关联任务/标注员、明细改门户查看

- 需求：回传验收面板此前只显示批次 ID，无法与上方任务关联；面板内逐样本「源数据/回传标签」明细太长导致无法验收。要求批次显示所属任务、标注员信息；验收页不再展开样本明细，明细在跳转标注员门户后查看。
- 后端（app/services/annotation_returns.py）：
  - `list_return_batches` 每项新增 `task_id`/`task_name`/`annotator_subject_id`/`annotator_name`（批量 in_ 查询 AnnotationAssignment → GenericAnnotationTask.name、AnnotatorAccount.username(subject_id)，无 assignment 时字段缺省）。
  - diff 端点不变（仍可用于质量风险统计）。
- 前端（ml-platform/frontend）：
  - api/annotationReturns.ts：ReturnBatch 类型扩展上述字段。
  - ReturnAcceptancePanel.tsx 重构：批次卡片显示「任务名 (短 task id) + 标注员 + 样本数 + 状态徽标」（无任务信息时回退批次短 id）；明细区只保留摘要（任务/标注员/状态/样本数/修订/质量风险）与提示文案；删除逐样本表格（源数据/回传标签不再渲染，diff 仅用于计算空标签风险数，超出扫描范围时注明）；新增「在标注员门户查看明细」按钮，window.open 打开门户新标签页，URL 为 `VITE_ANNOTATOR_PORTAL_URL` 或 `{protocol}//{hostname}:8443` + `?task={task_id}`。
  - global.css 新增批次卡片样式（annotation-return-panel__batch 等）。
- 标注员门户（annotator/frontend/src/App.tsx）：支持 `?task=&assignment=` 深链——登录态下 me() 解析后自动打开对应任务工作区，未登录时先展示登录页，登录后同样跳转。
- 测试：后端 test_annotation_return_acceptance.py 列表测试补 AnnotatorAccount/任务名并断言 4 个新字段（13/13 通过）；前端 ReturnAcceptancePanel.test.tsx 重写（断言任务/标注员展示、无表格、门户跳转 URL、验收流程，2/2 通过）。
- 验证：主前端 vitest 333 passed / 19 skipped、tsc、build 通过；门户 78/78、tsc、build 通过；后端 `-k return` 115 passed / 5 skipped。
- 说明/限制：管理员平台账号与标注员门户账号体系独立，跳转门户后需以（被授权的）标注员账号登录查看；如需管理员免登录只读评审门户任务，需新增管理员只读会话能力（涉及权限契约，未在本次实现）。

### 2026-09-20 自动标注向导：最终预览限高内部滚动

- 需求：新建自动标注任务第 2 步的「最终预览」区块（全量统计 summary JSON 含超长 visible_columns 数组 + 分页样本逐条 JSON）不受高度约束，页面被撑得很长，需滚动很久才能到底部按钮。
- 实现：global.css 新增 `.data-annotation__final-preview` 规则——max-height 340px、overflow-y auto、卡片化（边框/圆角/浅底）；内部 `pre` 去外边距、12px 字号、pre-wrap 换行；样本列表 grid 收紧间距。「加载更多预览样本」按钮随区块内部滚动。
- 验证：DataAnnotationPage.test.tsx 58/58 通过、`npm run build` 通过。
- 说明：仅 CSS 改动，无逻辑变化；聚类预览分支（ClusterPreviewPanel）不受影响。

### 2026-09-20 聚类发现任务：标签改为聚类之后定义（去掉向导第 2 步前置 schema 编辑器）

- 需求：新建自动标注任务向导第 2 步中，聚类预览之前的「自定义标签 schema」编辑器（红框内容）删除；标签列应在聚类完成后、保存标注策略之前再定义并保存。
- 后端实现：
  - app/services/annotation_strategies.py：`label_schema_contract_from_snapshot` 新增 `allow_empty` 参数（cluster discovery 任务在用户定义标签前列之前冻结快照可携带空占位 schema）；`apply_preview_annotation_strategy` 调整解析顺序——先取 config，再以 `allow_empty=config.cluster_discovery` 解析 schema。
  - app/api/generic_tasks.py：
    - 创建端点：discovery 配置（`{clustering: true, cluster_discovery: true}`）且未提供 label_schema_id 时不再报 WEAK_SUPERVISION_SCHEMA_REQUIRED，改为 `create_label_schema(..., columns=[], commit=False)` 创建占位空 schema（满足 label_schema_id NOT NULL 约束，避免 SQLite 存量表列变更）；非 discovery 的聚类配置仍要求用户 schema。
    - `_validate_automatic_configuration`：同样以 `allow_empty=config.cluster_discovery` 放宽；占位任务保存带 strategy 的配置（cluster_discovery=False）时仍 422 LABEL_SCHEMA_REQUIRED。
    - 更新端点（PUT /configuration）：`GenericTaskConfigurationUpdate` 新增 `label_schema_id`（用 `model_fields_set` 区分「未提供」与「显式提供」）；提供时校验项目归属（404 LABEL_SCHEMA_NOT_FOUND）与列非空（422 LABEL_SCHEMA_REQUIRED）、仅限 automatic 任务（422 LABEL_SCHEMA_IMMUTABLE）；换绑更新 task.label_schema_id/label_snapshot 并以 **Core 层 `update()`** 更新 AnnotationTaskLabel binding（ORM before_update 事件对标注历史一律抛 IMMUTABLE_LABEL_HISTORY，而换绑仅发生在 draft/failed/needs_review 无标注任务上，故绕过 ORM 事件）；`_snapshot_with_configuration` 新增 label_schema 参数，快照 label_schema 与 config_hash 随新 schema 重建。
  - app/tasks/annotation_preview_tasks.py：`snapshot.get("label_schema")` 两处 None 安全访问（占位 schema 存在但列空，防御性处理）。
- 前端实现（ml-platform/frontend）：
  - api/annotationTasks.ts：`GenericTaskConfigurationPayload` 新增 `label_schema_id?`。
  - DataAnnotationPage.tsx：删除第 2 步聚类前的「自定义标签 schema」编辑器整块与 `genericAutoLabelSource` 死状态；`startGenericDiscovery` 不再要求/提交 label_schema_id；聚类完成后（ClusterPreviewPanel 与策略编辑器之间）插入 LabelSchemaEditor（初始列来自模型输出契约列）；`saveGenericStrategy` 增加未保存 schema 守卫并提交 label_schema_id；任务列表「配置策略」弹窗对占位任务（frozenLabelColumnCount==0）同样先渲染 LabelSchemaEditor 再保存策略（saveAutomaticConfigSchema 创建 `${task.name}-labels` schema 并随 payload 提交）。
  - i18n：clusterPreviewReadyHint 更新为「请先在上方定义并保存标签列，再选择策略…」。
- 测试：后端 test_annotation_task_state_api.py 新增 3 例——discovery 无 label_schema_id 创建（201 + 占位空 schema + binding 指向占位 schema）、PUT 带 label_schema_id + rule 策略换绑（task_revision+1、快照 label_schema/config_hash 重建、binding 更新）、占位任务无 schema 保存策略（422 LABEL_SCHEMA_REQUIRED、revision 不变）；前端 DataAnnotationPage.test.tsx 两个 discovery 向导测试的 `chooseUserLabelSchema()` 移至聚类完成后，PUT 断言新增 label_schema_id。
- 验证：后端受影响套件（test_annotation_task_state.py + test_annotation_task_state_api.py + test_async_operation_contract.py）**115 passed**；前端 `npm test` **333 passed / 19 skipped（63 文件）**（首轮 1-2 例 TrainingJobsPage 时序 flaky，复跑全绿）、`tsc --noEmit` 通过、`npm run build` 通过。
- 说明：占位 schema 名为 `{任务名}-pending-labels`（零列）；聚类发现 worker 不依赖标签 schema（聚类用模型包特征重要性，发现决策为 pending_configuration 空值）；换绑后 AnnotationTaskLabel 以 Core SQL 更新，绕过标注历史不可变 ORM 事件（此时任务尚无任何标注）。

### 2026-09-20 标注门户：光标默认落在标签框

- 需求：标注详细页光标默认放在 label 中；每次标注上一条/下一条切换样本后，光标位置默认回到标签框。
- 实现（annotator/frontend）：
  - SampleStream.tsx：新增 `firstLabelRef` + `useEffect`（依赖 sample_id/disabled），样本变化（含初始加载、上一条/下一条/跳过/保存并下一样本）后自动 focus 第一个标签输入框（enum 为 select、text/number 为 input，均加 `data-label-input="true"` 标记）；锁定/批量保存中不聚焦。
  - TaskWorkspacePage.tsx `handleShortcut`：标签框内按 Enter 同样触发「保存并进入下一样本」（Ctrl/Meta/Alt 修饰键除外）；按 Esc 将光标移出标签框以恢复全局快捷键（数字 1-9 快捷选项、空格跳过等在标签框内输入时不触发，属预期行为——用户在输入标签值）。
  - ShortcutHelp.tsx 更新帮助文案（Enter 标签框内同样有效、Esc 可移出标签框、1-9 标签框内输入数字时除外）。
- 测试：TaskWorkspacePage.test.tsx 新增 3 例——焦点初始落在 category-s-1 且随上一条/下一条切换重新聚焦；标签框内 Enter 保存并在 600ms 后前进且焦点回到新样本标签框；Esc 移出标签框后数字快捷选项恢复。
- 验证：annotator 前端 `npm test` **78 passed（11 文件）**、`tsc --noEmit` 通过、`npm run build` 通过（新 bundle index-D3fV_Uf_.js）。

### 2026-09-20 标注任务与数据文件重名自动加后缀

- 需求：标注任务不能重名，数据管理中的文件也不能重名；重名时自动添加后缀区分。
- 实现（后端，项目内去重，软删除/归档不占用名称）：
  - app/api/generic_tasks.py 新增 `_unique_task_name`：查询项目内未归档任务名集合，重名时追加 `-2`、`-3`…；应用于 POST /api/annotation-tasks 创建（`name=_unique_task_name(...)`）与 PUT /configuration 改名（`exclude_task_id` 排除自身，改回自身当前名保持稳定）。任务快照不含任务名，config_hash 不受影响。
  - app/api/datasets.py 新增 `_unique_dataset_name`：查询项目内 type=dataset、未归档 Artifact 名集合，重名时在扩展名前追加 `-2`、`-3`…（`rows.csv` → `rows-2.csv`）；应用于全部上传入口——datasets/upload、datasets/batch、datasets/batch-upload、datasets/import-zip（逐成员）、dataset-imports（异步导入 source_name）及 `_store_uploaded_dataset`；batch-upload 与 import-zip 响应改返回 `artifact.name`（去重后真实名称）。
- 前端（DataAnnotationPage.tsx）：新增 `notifyAutoRenamedTask`，两个任务创建入口（常规创建、聚类发现 startGenericDiscovery）在返回名称与提交名称不一致时提示「任务名称与现有任务重复，已自动改为「xxx」」（中英文）；数据集上传无需改动，列表按后端返回名称展示。
- 测试：test_annotation_task_state_api.py 新增 `test_generic_task_name_collisions_get_suffixed_suffix`（同名三次创建 → 原名/-2/-3；改名撞名继续顺延；改回自身名保持）；test_dataset_import_contract.py 新增 `test_upload_handler_suffixes_duplicate_dataset_names`（同名二次上传 → rows-2.csv，上传已带后缀名 → rows-2-2.csv）。
- 验证：后端 `pytest tests/test_annotation_task_state.py tests/test_annotation_task_state_api.py tests/test_async_operation_contract.py` **112 passed**；`pytest tests/test_annotation_task_state_api.py tests/test_dataset_import_contract.py` 56 passed（7 个失败为本机 venv 缺少 pyarrow 的既有环境问题，与本次改动无关，均为 parquet 相关测试）；前端 `npm test` **333 passed / 19 skipped（63 文件）**、`tsc --noEmit` 通过。
- 说明：去重范围按项目（project_id）划分，不同项目允许同名；内部中间产物 Artifact（normalized.parquet 等）参与名称占用判断但本就不对用户展示；异步 dataset-import 的去重在提交时点判定，导入过程中撞名（并发）仍可能产生极小概率重复，无唯一约束兜底。

### 2026-09-20 去掉「发布」「执行」按钮：预览完成后自动发布/自动执行

- 需求：任务列表操作列去掉「发布」「执行」按钮；新建标注任务后，手动任务在预览完成后自动「发布」（preview_ready → awaiting_annotation），自动任务自动「执行」（创建 execution durable operation → executing）。
- 后端实现：
  - app/services/annotation_task_state.py `mark_preview_completed`（唯一将任务置 preview_ready 的位置）：previewing → preview_ready 后新增自动推进——manual 任务直接置 awaiting_annotation 并记录 `annotation_task.auto_published` audit 事件；automatic 任务调用 `request_annotation_execution`（幂等创建 durable operation，内部 commit 置 executing）记录 `annotation_task.auto_execute_requested` 事件（含 operation_id），并将 operation_id 暂存到 `task._auto_execution_operation_id`。聚类发现未配置（configuration_complete=False 或 needs_review_count>0）仍置 needs_review，保持「配置策略」流程不变。
  - app/tasks/annotation_preview_tasks.py worker 成功路径：`complete_operation`（内部 commit 提交上述 pending 变更）之后，若存在 `_auto_execution_operation_id` 则调用 `enqueue_annotation_execution` 派发执行任务（celery delay / local daemon thread），避免在 preview 操作租约内嵌套派发。
  - 后端 publish/execute API 端点保留（仅前端移除入口）；manual 任务已 awaiting_annotation 后 execute 请求返回 409 TASK_STATE_INVALID。
  - 前置修复（既有 dirty 遗留）：`list_annotation_tasks` 此前会话已由 owner 过滤改为 accessible_project_query 项目范围过滤，但 `test_all_project_task_api_paginates_without_losing_owner_scope` 未同步更新——测试中为请求用户补加 second 任务项目的 ProjectMember（editor）成员关系使其保持可见，与新的项目范围语义一致。
- 前端实现（DataAnnotationPage.tsx）：
  - 删除任务行「执行」按钮与 `executable` 判断、`executeGenericTask` 函数、`genericTaskActionItems` 中「发布」项及 `runGenericTaskAction` 的 publish 分支、`transitionGenericTask` action 联合类型中的 "publish"；删除向导 `confirmGenericExecution` 函数与页脚「确认执行」按钮，改为「返回任务列表」（resetGenericScopeDraft + returnToTaskList）。
  - manual 任务创建成功后自动调用 `createAnnotationPreview`（configHash 取自 task_snapshot.config_hash，存在时），提示「任务已创建，预览完成后将自动发布」；configHash 缺失时保持旧提示。
  - 最终预览就绪 hint 改为「最终标签预览已完成，任务将自动开始执行。」
  - 新增任务列表轮询：isTaskList 且存在 previewing/executing 状态任务时每 2s 调 refreshGenericTaskData（无 loading 闪烁），无过渡任务时不轮询。
- 测试：后端 test_annotation_task_state.py（manual 自动发布 audit 断言、automatic 自动执行 + enqueue 派发断言、pause/resume 重写为直接置 preview_ready、audit 事件测试重置状态）、test_annotation_task_state_api.py（execute 端点改 409、local dispatch 断言 awaiting_annotation）、pagination 测试补 ProjectMember；前端 DataAnnotationPage.test.tsx——原「执行按钮」测试改写为「preview_ready 任务无发布/执行按钮」、新增「previewing 任务轮询刷新」（真实计时器，2s 间隔）、manual 创建测试补 config_hash 并断言创建后自动 POST /preview。
- 验证：后端 `pytest tests/test_annotation_task_state.py tests/test_annotation_task_state_api.py tests/test_async_operation_contract.py` **111 passed**；前端 `npm test` **333 passed / 19 skipped（63 文件）**、`tsc --noEmit` 通过、`npm run build` 通过。
- 说明：自动执行依赖 recovery 任务周期性 re-dispatch queued 执行操作，进程崩溃后可恢复；重新生成预览/配置策略后的新预览完成同样走自动发布/执行路径（按钮移除后唯一前进方式）；前端列表轮询仅在存在过渡态任务时激活，不产生常驻轮询负载。

### 2026-09-20 任务列表操作列「···」下拉改为全部行内显示

- 需求：主平台数据标注任务列表操作列中收纳在「···」下拉里的操作按钮全部直接显示，不再收进菜单。
- 实现：DataAnnotationPage.tsx——操作列删除 Dropdown「···」触发按钮，`genericTaskActionItems` 生成的操作项（编辑任务/重试预览/配置策略/批注管理/发布/暂停/恢复/取消/提交回传/验收/完成/归档/重开/恢复归档，按任务状态条件渲染）改为行内 `ant-btn-sm` 按钮直接渲染（支持 danger 样式透传）；`.data-annotation__row-actions` 已有 `flex-wrap: wrap`，按钮自动换行防挤压。global.css 删除不再使用的 `.data-annotation__more-trigger` 规则。DataAnnotationPage.test.tsx 4 处「更多操作 → menuitem」两步点击改为直接点击行内按钮（验收/编辑任务/重新生成预览/配置策略）。
- 验证：DataAnnotationPage.test.tsx 57/57；主平台前端全量 `npm test` 332 passed / 19 skipped（63 文件，与基线一致）；`tsc --noEmit` 通过；`npm run build` 通过。
- 说明：菜单项本就按状态互斥生成，单行最多 8 个小按钮（预览/指派/执行 + 最多 4 个状态操作 + 删除），配合换行规则不会挤压其他列；工作台导出下拉（CSV/XLSX）不受影响。

### 2026-09-20 数据标注页三处数据展示修复（时区 / 操作任务对应 / 标题语义）

- 需求（用户截图三问）：①任务创建时间比真实时间少 8 小时；②操作卡片 ID 无法与任务列表 ID 对应；③任务列表 4 个任务却有 7 条"运行中的操作"令人困惑。
- 根因（查 SQLite 与后端代码确认）：①后端以 UTC 存储时间（`datetime.now(timezone.utc).replace(tzinfo=None)`），API 返回无时区标记的 ISO 字符串，前端 `new Date(value)` 解析无偏移字符串时按本地时区原样显示 UTC 值（比北京少 8 小时）；②操作卡只展示 durable_operations 自身 UUID，未展示 task_id；③操作列表是任务操作日志（含已完成历史，每任务可有多条——预览每次重试都新增一条，41bb29b9 有 3 条、337b23d7 有 2 条），并非"仅运行中"，标题有误导。
- 实现：DataAnnotationPage.tsx 新增 `formatBackendTimestamp`（无时区标记的 ISO 字符串补 "Z" 后按本地时区格式化，已有 tz 标记则原样），应用于任务表创建时间列与操作卡创建时间；操作卡新增「任务 + 8 位短 ID（主色 code，title 悬停全 ID）」行，与任务列表短 ID 一一对应；操作卡 ID 改 8 位短 ID（title 悬停全 ID）；i18n operationsSection「运行中的操作/Running operations」改「任务操作记录/Task operations」，空态文案同步「暂无任务操作记录」。
- 测试（DataAnnotationPage.test.tsx）：操作 mock id 改真实 UUID 形态，断言 8 位短 ID（d471a117/bbbbbbbb）与 task_id 展示；创建时间断言不受影响（日期部分不变）。
- 验证：主平台前端 `npm test` **332 passed / 19 skipped（63 文件）**；`tsc --noEmit` 通过；admin 浏览器实测——ass 创建时间 2026/9/19 15:18→23:18（+8 正确）、操作卡显示「任务 226a1258/41bb29b9/337b23d7/584ae2cc」与任务列表一一对应、标题已改「任务操作记录」。
- 说明：统计条「运行中操作」计数仅统计未完成操作（state 非 completed/failed/cancelled），语义保持准确；due_at 为用户输入的日期（无时间偏移问题），未改动；其他模块页面的时间显示（如 NotificationCenter）未在本次范围。

### 2026-09-19 工作区侧栏再窄 + 面板控件紧凑化

- 需求：①左侧导航栏再窄一些；②侧栏内的上一页/下一页等按钮字体小一点、更美观。
- 实现：styles.css——workspace 侧栏 240→200px（1100px 断点 220→190px）；新增 .side-panel-body 控件紧凑规则：按钮 font-size 12px、padding 5px 10px、圆角 4px（primary 6px 12px 加粗），输入/下拉/文本域 13px、padding 6px 10px，muted 文字 12px。
- 验证：75/75 通过、tsc 与构建通过；部署 8443（bundle index-Dlpxkt6r.js）；浏览器实测——侧栏 200px，分页按钮 12px/38px 宽、"应用到所选样本" 12px/26px 高、下拉框文字无截断（5 个下拉 textFits 全 true）、无按钮溢出换行。

### 2026-09-19 工作区真实进度与全局样本计数 + 侧栏变窄

- 需求：①样本区域计数应显示任务全部样本（此前仅当前页 50 条）；②顶部进度须为真实进度（此前为当前页本地统计，50/50=100% 误导）；③左侧导航栏变窄。
- 实现：TaskWorkspacePage.tsx——新增 totalSamples=task.total_samples、completedCount=task.completed_samples（后端任务详情 /portal/tasks/{id} 已返回指派范围真实值，sample_query.count + values 非空统计）、globalPosition=page*50+selected+1（全局位置）；顶部"样本 x / y"、进度条"已标注 x / y + 百分比"、底部"第 x/y 条"全部改用任务级数值，task 字段缺失时回退本地页统计（测试 fixture 兼容）；新增 refreshTaskStats（静默 getTask 刷新 completed/total，忽略失败），单条保存成功与批量保存成功后调用，保证进度实时且不虚增（已计入的样本重新保存不重复计数）；定义位置在 save useCallback 之前避免 TDZ；styles.css 侧栏 300→240px（1100px 断点 260→220px）。
- 验证：75/75 通过、tsc 与构建通过；部署 8443（bundle index-j8-TX3Nv.js）；jingms 浏览器实测两轮——页面显示"样本 1/147、已标注 3/147、2%、第 1/147 条"与接口返回 total_samples=147/completed_samples=3 完全一致（此前误显示 50/50 100%）；保存标签后进度不虚增（重新保存已计入样本 completed 保持 3）；翻页验证第 2 页显示 51/147、第 3 页 101/147、"下一条"到 102/147，第 3 页（末页 47 条）"下一页"正确禁用；侧栏实测 240px。

### 2026-09-19 标注工作区左栏手风琴化（右栏合并 + 一屏布局）

- 需求：①右侧面板（指南/样本/批量/回传/批注）内容移到左侧对应标签栏下方展开；②去掉右侧独立区域；③样本数据一行显示更多列；④整页保持一屏、不需要滚动。
- 实现：TaskWorkspacePage.tsx 删除 aside.right-panel，新增组件内 renderPanel(key) 渲染函数，五个面板内容在 side-tabs 的 map 中以 div.side-panel-group 包裹（tab 按钮 + side-panel-body 手风琴展开，多面板共存不变）；styles.css——workspace 改两栏（300px 1fr）、修复高度约束链（.workspace-main 加 min-height:0、.workspace-center 改 flex column、.sample-stream 由 height:100% 改 flex:1 + min-height:0，使 grid 行高不再被内容撑开）、side-tabs overflow-y:auto 内部滚动、field-grid minmax 200→150px（5 列）、field-item 紧凑化（浅灰底圆角小卡、字段名 11px、值 13px、padding 4px 6px）、stream-sample 去 900px 宽度限制并压缩各级 padding/margin、删除 right-panel/guideline 独立样式改为 .side-panel-body 内嵌（.guideline 嵌入覆盖）、响应式 960px 以下侧栏横排单列；响应式断点 1280→1100px。
- 验证：标注员前端 75/75 通过；tsc 与生产构建通过（CSS 25.59kB）；部署 8443（bundle index-7x3gc7c4.js）；jingms 浏览器实测（两轮）——第一轮发现整页滚动 1261px（grid 子项被内容撑高），补修 min-height 约束链后复验全部通过：整页 scrollHeight=clientHeight（diff=0）无滚动、footer"保存并下一样本"常驻视口、左栏三面板展开后侧栏内部滚动（576px 限高）、样本 74 字段卡 5 列在 stream-sample 内部滚动、标签保存功能正常（修订号 9→11）。
- 说明：样本字段数量多（74 个）时字段区仍需容器内部滚动（5 列下约 15 行），属一屏布局下的预期折衷；侧栏展开多面板后底部按钮需侧栏内滚动可见。

### 2026-09-19 算法平台数据标注模块布局重设计（三页面：首页/工作台/向导）

- 需求：重设计主平台（ml-platform/frontend）数据标注模块各页面样式与布局，保持与平台现有设计令牌一致（--accent-primary #187fd4、page-header/table-surface 卡片、Antd 小表格），标注员门户不动。
- 实现（DataAnnotationPage.tsx）：
  - 首页（tasksView）——页头下新增 4 卡任务统计条（进行中任务/待配置策略/待验收回传/运行中操作，彩色圆点+等宽数字，提示文案计数为 0 时隐藏）；操作列由最多 14+ 按钮收纳为「预览/指派标注员/执行 + ··· 更多下拉 + 删除图标」，更多菜单按任务状态动态生成（编辑/重试预览/配置策略/批注管理/发布/暂停/恢复/取消/提交回传/验收/完成/归档/重开/恢复归档），保留原禁用逻辑；任务列表卡片内用 antd Segmented 页签（全部任务/进行中 n/历史任务 n，默认全部保持旧行为）合并通用任务表与历史任务表两区块；「运行中的操作」为任务列表卡片下方的全宽独立卡片，操作以多列网格卡片（auto-fill 280px）呈现（id/类型·阶段/状态 Tag/进度条/错误码/查看结果），加载更多按钮独立内边距类 data-annotation__operations-more；执行结果从操作卡片内嵌套改为独立 Drawer（720px，region/aria 不变）；回传验收面板位于运行中操作之后。
  - 标注工作台（workspaceView）——大 page-header 压缩为两级窄条：面包屑栏（数据标注 / run 短 id + 状态 Tag + 返回/导出/保存/刷新按钮）+ 元信息栏（模式/样本数/进度条百分比）；「当前样本数据」由两列行表改多列紧凑卡片网格（CSS auto-fill 190px，字段名小字在上、值加粗在下，主色左边条）。
  - 创建向导（genericSetupView）——Steps 恢复标准尺寸；第 2 步改左右分栏（1fr + 300px sticky 侧栏）：右侧新增「冻结契约摘要」常驻侧栏（任务名称/数据版本含行数/模型版本/样本范围/输出列/契约状态已冻结）；聚类预览就绪时 ClusterPreviewPanel 与 AutomaticAnnotationStrategyEditor 改 `.data-annotation__cluster-split` 左右分栏（向导第 2 步与「配置自动标注策略」Modal 两处）。
  - ClusterPreviewPanel.tsx——内部重组为「左图表（散点+簇分布条）/右信息（K/评估方式/评估样本/权重来源+K 分数）」分栏，类名与文案全部保留。
- 布局调整（用户反馈）：首页初版为「任务列表 + 320px 右侧操作栏」双栏；按用户要求「运行中的操作」改为任务列表下方全宽显示（单栏纵向流：统计条 → 任务列表 → 运行中操作 → 回传验收），操作卡片改带边框圆角的网格卡片，移除 layout/rail 双栏 CSS。
- 样式（global.css）：新增 data-annotation__stats/stat/tabs/row-actions/more-trigger/operations/operation/progress-track/operations-more、spot-weld-annotation__topbar/crumb/metabar/meta-item、setup-step2/contract-aside/contract-row、cluster-split/cluster-preview-body 等规则，全部使用现有主题令牌（深浅双主题适配），1100px 断点响应式折叠。
- 测试（DataAnnotationPage.test.tsx）：4 处按钮（验收/编辑任务/重新生成预览/配置策略）移入更多菜单，测试改为先点「更多操作」再点 menuitem；其余契约（region aria-label、按钮名、页脚类名）不变。
- 验证：主平台前端 `npm test` **332 passed / 19 skipped（63 文件）**；weekAcceptance 7/7；`tsc --noEmit` 与生产构建通过；admin 浏览器实测（127.0.0.1:5173 规避 portal_session cookie CSRF 误拦）——统计条四色卡片、Segmented 页签过滤与历史切换、··· 菜单弹出、运行中操作全宽网格卡片（任务列表下方、回传验收之前）、工作台两级窄条+卡片网格、向导第 2 步分栏+冻结契约摘要全部生效，控制台无 JS 错误。
- 遗留（非本次范围）：旧版「开始手动标注」创建 run 失败——spotWeldQuality.ts createQualityRun 未携带后端要求的 X-Request-ID/Idempotency-Key 头（通用任务流程已携带），属既有功能缺陷待后续修复。

### 2026-09-19 标注员门户按 style-1-light-enterprise 设计稿全面对齐

- 需求：按 `design-showcase/annotator-portal/style-1-light-enterprise.html`（829 行设计稿）的风格样式实现标注员门户，补齐此前未接线的设计元素。
- 实现：index.html 引入 Inter/JetBrains Mono 字体（preconnect + Google Fonts）；App.tsx 顶栏改为设计稿形态——64px 白色半透明毛玻璃（rgba 0.92 + blur 12px）、导航改为胶囊分段容器（灰底描边、激活项白底蓝字带阴影）、退出改为 36px 图标按钮、user-chip 改白底描边胶囊 + 浅蓝头像；LoginPage 标题对齐设计稿（eyebrow "Annotator Portal" + h1 "标注员门户"）、登录页改双角径向渐变背景、卡片 40px 内边距；统计卡去 stat-dot、改为彩色大数值（待标注蓝/进行中青/待回传橙/已逾期红）+ 大写小标签 + auto-fit 网格；TaskCard 重构为设计稿 DOM（task-main/task-title 行内状态标签/1fr-auto 网格/日历图标）；FeedbackBanner 改 info 圆圈图标 + "质检反馈："粗体前缀；工作区侧栏 56px 图标栏改 220px 图标+文字侧栏（side-tab 横排、激活浅蓝底、底部 side-divider+帮助），stream-meta 增加进度条（已标注 x/y + 蓝色 progress-bar + mono 百分比，labeledCount 按 clean/saved 状态统计）；响应式 1280px 侧栏收窄为图标、960px 隐藏右栏；删除全失效的 TaskQueuePage.css（queue-controls/task-row 规则均已死代码）。
- 验证：标注员前端 75/75 通过；tsc --noEmit 与生产构建通过（CSS 25.45kB）；部署 8443（bundle index-Dbso6Kz5.js / index-D_UqhuP9.css）；jingms 浏览器实测全部通过——登录页卡片/文案、顶栏胶囊分段与图标按钮、四色统计卡、任务卡行内标签、220px 侧栏、进度条 100%、样本/批量右栏面板布局无错位。

### 2026-09-19 Light Enterprise 主题迁移缺口补齐（样式导入修复 + 测试契约对齐）

- 需求：新主题迁移后核对缺口并补齐（审计发现 3 处，其中 NotificationInbox 由组件级 CSS 覆盖为伪缺口，实际缺 `stream-fields`、`portal-page`）。
- 实现：styles.css 新增 `.stream-fields`（样本流字段容器纵向布局）与 `.portal-page`（通用页面容器，对齐 app-main 规范）；**关键修复**——迁移时丢失的 `import './styles.css'`（App.tsx）与 `import './TaskQueuePage.css'`（TaskQueuePage.tsx）补回，此前新主题整体未进包（产物 CSS 仅 2.2kB）。测试契约对齐用户迁移后的组件变更：LoginPage 按钮/props（onLogin、登录到任务中心）、TaskQueuePage 新 props（user 对象，移除 onLogout/username）、工作台返回按钮更名"← 返回任务列表"、只读状态并入样本计数段落、双面板分页并存（上一页×2）、空列表隐藏分页、删除已迁移至 App 顶栏的用户名显示测试；App.tsx assignmentId null→undefined、login() 去除 remember 字段保持请求契约。
- 验证：标注员前端 75/75 通过；tsc 与生产构建通过（CSS 2.2kB→23.9kB）；已部署 8443（bundle index-BVZjvbJe.js / index-B1joRJve.css），部署产物含 stream-fields/portal-page/app-topbar 规则；jingms 浏览器实测队列页与工作台浅色企业主题渲染正常，无无样式区域。

### 2026-09-19 标注工作台顶栏三处精简（去用户信息/返回按钮归位/顶栏变窄）

- 需求：①去掉标注详细页顶栏的用户信息栏（通知铃铛/头像/用户名/退出）；②"返回任务"按钮固定在左侧导航栏最下方；③顶栏变窄。
- 实现：工作台（TaskWorkspacePage）顶栏仅保留"快捷键"按钮与任务状态，用户信息元素只存在于任务队列页；"← 返回任务"按钮渲染于侧栏 tab-rail 之后（左栏最下方）；styles.css 顶栏紧凑化——`.workspace` padding-top 28→14px、eyebrow 与标题同行（baseline 对齐）、h1 20→18px、topbar padding-bottom 10→8px、workspace-grid margin-top 12px。
- 验证：标注员前端 76/76 通过（修正 2 处按钮可访问名"返回任务"→"← 返回任务"）；`tsc --noEmit` 与生产构建通过；重建 annotator-frontend 镜像部署 8443（bundle index-CI1dHXER.js），部署产物 CSS/JS 校验含全部新规则与 `back-to-queue` 结构；jingms 浏览器登录实测三点全部生效（顶栏无用户信息、返回按钮在左栏最下方、顶栏紧凑单行）。

### 2026-09-19 标注工作台四项交互修改（批量分页/多面板导航/标签必填/标签类型对齐）

- 需求：①样本区"上一页/下一页"分页移入"批量"分区；②左侧导航支持同时展开多个面板；③指南中标签改为必填（不再可选）；④样本标签类型与管理员创建标注任务时选择的类型一致。
- 实现：分页控件移至"批量"面板顶部，批量面板独立分页游标（翻页仅影响勾选列表，不改变右侧样本流）；左侧导航由单面板改为 `openTabs` 集合，多面板可同时展开、各自独立收起；`LabelSchemaEditor.tsx`/`DataAnnotationPage.tsx` 标签默认必填，标签类型跟随管理员所选模型输出合同；数据修正脚本将活动任务 "as"（ID 584ae2cc）存量标签更新为必填。
- 验证：标注员前端 76/76、主平台前端 61/61、weekAcceptance 7/7 全部通过；jingms 登录浏览器验证四项生效；部署 http://localhost:8443（bundle index-CNqoUy17.js）。另修复 weekAcceptance.test.ts 中 ClusterPreviewPanel.test.tsx 未注册问题。

### 2026-09-19 重启后门户登录 500 修复（8000 端口孤儿进程 + WSL 中继）

- 问题：电脑重启后标注员门户登录报 500。Docker 容器自动恢复但本地链路两处中断：①uvicorn 以 `--host 127.0.0.1` 启动且旧 `--reload` 孤儿进程占用 8000 端口，WSL 容器无法访问 Windows 127.0.0.1；②WSL TCP 中继（8100）未自启，而它是容器到本地后端的必经通道。
- 修复：清理占用 8000 端口的孤儿 worker（PID 23708）与绑定 127.0.0.1 的 uvicorn（PID 860/20028），以 `--host 0.0.0.0 --port 8000 --reload` 重启本地后端；重跑 `temp_test/wsl_relay.py` 恢复 8100 监听。
- 验证：容器内访问 host.docker.internal:8100/api/health 与门户登录 API（jingms）均返回 200，登录恢复。重启电脑后的恢复清单（见"数据打通"节运维要求）：本地后端必须以 `--host 0.0.0.0` 启动、重跑中继命令、清理 8000 端口残留 python 子进程。

### 2026-09-18 标注员门户重设计 P0（样本流 + 快捷键 + 反馈横幅）

- 范围：按 `ml-platform/docs/technical-proposals/2026-09-18-annotator-portal-redesign.md` §4/§5/§8 实施 P0，纯门户前端（annotator/frontend），不改主平台契约、不做 P1/P2（无仪表盘、跳过不回队尾、无撤销历史侧栏、无重做上限）。
- 工作台（TaskWorkspacePage）：默认"样本流"模式——左栏 `GuidelinePanel`（任务说明+标签说明快照，可折叠）、中央当前样本（visible_columns 字段分组高亮）、右栏标签控件（沿用原生 select/input，枚举列加数字角标快捷选项 chips）、底栏 ← 上一条|第 n/N 条|下一条 →|跳过|保存并下一样本；顶栏"快捷键"按钮与"浏览全部"模式开关（翻页浏览保留全部既有交互：样本侧栏筛选/分页/批量编辑/回传/批注）。保存成功 600ms 自动前进，队尾显示"本次连续完成 N 条"汇总。全局 keydown 快捷键（window 监听、最新闭包 ref 转发、输入框聚焦不触发）：1-9 按显示顺序切换枚举选项（再按取消）、Enter 保存前进、Space 本地跳过（preventDefault 防滚动/按钮触发）、←/→ 翻样本、Ctrl+Z 撤销（前端栈 20 步，仅标签值变更入栈，undo 恢复不二次入栈并走防抖自动保存）、F1/? 帮助浮层（Esc 关闭）。`save` 改返回 boolean 供前进判断；自动保存防抖、修订号乐观锁、冲突确认弹窗、批量、评论、beforeunload 拦截全部原样保留。
- 队列页（TaskQueuePage）：`FeedbackBanner`——列表项 `state` ∈ {returned_pending_acceptance, edit_for_return}（或任务状态待验收）时显示"有 N 条反馈待处理"警示横幅，点击滚动并高亮首个退回任务卡（`TaskCard` 含"需重做"徽标）；任务卡展示任务名/状态 tag/我的进度 x/y（无进度字段不显示）/截止时间/[继续标注]，搜索/筛选/排序/游标分页原样保留。
- 新增组件（src/components/，同目录 *.test.tsx）：GuidelinePanel、ShortcutHelp、SampleStream、TaskCard、FeedbackBanner；`api/tasks.ts` Task 类型补 `state?`（后端 `_task_view` 本就返回该字段，纯前端补类型）。
- 验证：annotator 前端 `npm test` **71 passed**（10 文件：工作区 41（含新增 10 项样本流/快捷键用例）、队列 7（含反馈横幅 2 项）、新组件 16、登录/通知/任务 API 不变全过）；`npx tsc --noEmit` 通过；`npm run build` 生产构建通过；`git diff --check` 通过。既有测试仅队列页 3 处按钮名选择器"打开工作区"→"继续标注"随任务卡重构同步更新。
- 未尽：P1/P2（仪表盘、跳过回队尾服务端标记、撤销历史侧栏、重做上限/申诉）；队列列表数据无未读批注字段，反馈横幅按指派退回状态判定；帮助浮层为门户自有 dialog 样式（门户未引入 antd，沿用现有弹窗视觉）。

### 2026-09-18 标注员项目授权闭环（修复指派 TASK_STATE_INVALID / ANNOTATOR_FORBIDDEN）

- 问题：指派标注员确认时报两个错——①`TASK_STATE_INVALID`：后端 `_ensure_task_allows_assignment` 仅允许 preview_ready/awaiting_annotation/in_progress，但前端指派按钮无条件可点；②`ANNOTATOR_FORBIDDEN`：`create_assignments` 要求被指派者在 `project_annotator_grants` 有该项目 active 授权，本地库该表为空且全平台无项目授权 UI。
- 后端（`api/annotator_internal.py`）：`GET /api/annotators` 新增可选 `project_id`（join ProjectAnnotatorGrant status=active，仅返回项目内已授权 active 标注员）；新增 `GET /api/admin/annotators/{subject_id}/grants`（admin-only，返回 `{items:[{project_id,status}]}` 全部状态记录）；既有 `POST/DELETE /api/internal/projects/{project_id}/annotators/{subject_id}/grant` 原先无角色校验（仅登录），按同文件 admin 端点惯例补 `admin.role != "admin"` → 403 ADMIN_REQUIRED。
- 前端：`api/annotatorAssignments.ts` `listAnnotatorSubjects(query, projectId?)` 传 `project_id`，新增 `listAnnotatorProjectGrants`/`grantAnnotatorProject`/`revokeAnnotatorProject`；`DataAnnotationPage` 指派按钮按任务状态禁用（非三态 disabled + 中英 title 提示），`openAssignmentDialog` 按 `task.project_id` 过滤加载（保留前端 active 双保险）；`AssignmentDialog` 空列表非加载中时提示"该项目暂无已授权标注员，请先在用户管理 → 标注员管理中完成项目授权"；`UserManagementPage` 标注员管理卡 active 行新增"授权项目"Modal（多选项目，确认时 diff 调 grant/revoke，成功提示"项目授权已更新"，失败 formatApiError）；i18n apiErrors 更新 TASK_STATE_INVALID 中文、新增 ANNOTATOR_FORBIDDEN 中英（后端"未授权/非 active"共用该码，文案取授权语义）。
- 验证：后端 `test_annotator_auth.py` **10 passed**（project_id 过滤有/无授权断言、grants 端点 403+正常返回）+ `test_portal_internal_api.py`+`test_security_contract.py` 共 97 passed；前端 `UserManagementPage.test.tsx`(4) + `DataAnnotationPage.test.tsx`(57，新增指派禁用/项目过滤用例) + `AssignmentDialog.test.tsx`(3) + `annotatorAssignments.test.ts`(6) + `client.test.ts`(8) 共 **78 passed**；`tsc --noEmit` 与生产构建通过。
- 取舍：撤销授权后端即撤回该项目全部指派（既有服务语义），Modal 提示文案已说明；grants 端点返回全部状态（含 revoked）供前端仅取 active 做初选。

### 2026-09-18 指派标注员接口补全与下拉选择

- 问题：点击"指派标注员"报 Not Found——前端 `listAnnotatorSubjects()` 调用的 `GET /api/annotators` 后端无实现（此前仅 e2e mock）。同时用户要求抽屉内用下拉菜单选择标注员。
- 后端（`api/annotator_internal.py`）：新增 `GET /api/annotators`（登录用户可访问，`q` 可选按用户名模糊搜索）：仅返回 active（已审核通过）账号，`id` 为指派创建所需的 subject_id，按用户名排序。
- 前端（`components/AssignmentDialog.tsx`）：搜索框+复选框列表改为 antd `Select` 多选下拉（内置搜索 `optionFilterProp="label"`、加载中/无匹配提示），提交逻辑与重叠警告、截止时间、范围摘要保持不变；移除未使用的 `onSearch` prop。
- 验证：后端 `test_annotator_auth.py` **9 passed**（新增：仅返回 active、q 过滤、id 为 subject_id）；前端 `AssignmentDialog.test.tsx`（下拉选择→提交携带选中 id）+ `DataAnnotationPage.test.tsx` + `annotatorAssignments.test.ts` 共 61 passed；`tsc --noEmit` 通过。线上实测：`GET /api/annotators` 返回 active 账号（annotator-review-test、jingms），`q=review` 过滤正确。
- 运维备注：uvicorn `--reload` 热重载崩溃会遗留"父进程死、子进程持有 127.0.0.1:8000 套接字"的孤儿（本次 PID 37616，父 38628 已亡但 netstat 仍显示父 PID 持有）；重启前用 `Get-NetTCPConnection -LocalPort 8000 -State Listen` 定位并杀掉 python 子进程。

### 2026-09-18 数据标注页指派抽屉与操作列表三处改进

- 需求：①"指派标注员"从居中弹窗改为右侧抽屉且只可选已审核通过（active）标注员；②预览/指派两个抽屉打开时点击左侧原页面（遮罩）即关闭；③任务软删（archived_at）后其操作不再出现在"运行中的操作"。
- 前端：`AssignmentDialog.tsx` 自定义 Modal 改为 antd `Drawer`（placement right、宽 min(560px,100vw) 对齐 PreviewDrawer，title "指派任务" 自动关联 aria-labelledby，保留多选/搜索/重叠警告/截止时间逻辑，props 不变）；`PreviewDrawer.tsx` 在侧栏外新增遮罩层（`.annotation-preview-drawer__mask`，z-index 999 低于抽屉 1000）点击关闭；`DataAnnotationPage.tsx` 加载标注员后过滤 `status === "active"`。
- 后端：`services/annotation_task_state.py` `list_annotation_operations` 过滤条件新增 `GenericAnnotationTask.archived_at.is_(None)`——与 `list_annotation_tasks` 既有软删过滤一致，操作中心与任务列表口径统一。
- 验证：前端 `DataAnnotationPage.test.tsx` 56 + `AssignmentDialog.test.tsx` 2 + `PreviewDrawer.test.tsx` 4（各新增遮罩关闭/抽屉渲染回归）+ `client.test.ts` 8 全部通过；`tsc --noEmit` 与生产构建通过；后端 `test_annotation_task_state.py` 69 passed/1 failed（`test_all_project_task_api_paginates_without_losing_owner_scope`，经移除本改动复跑仍失败，系工作树中 `list_annotation_tasks` 改按可访问项目过滤的既有未提交改动所致，与本任务无关）、操作中心相关 3 项含新增软删回归全过、`test_annotation_task_state_api.py` 21 passed。
- 取舍：`GET /api/annotators` 后端本无实现（e2e 靠 mock 返回 `status`），前端 `AnnotatorSubject` 类型已含 `status?`，故标注员过滤采用前端方案，未新增后端接口。

### 2026-09-18 API 错误信息按界面语言本地化

- 需求：后端错误如 `TASK_ACTIVE: Cancel the active task before deleting it.` 中文界面显示中文、英文界面显示英文。
- 实现：i18n 字典（`frontend/src/i18n/index.tsx`）新增 `apiErrors` 中英对照表，首批覆盖标注任务域 9 个错误码（TASK_NOT_FOUND/TASK_ACTIVE/TASK_REVISION_CONFLICT/TASK_STATE_INVALID/MODEL_VERSION_IMMUTABLE/DATASET_VERSION_NOT_FOUND/LABEL_SCHEMA_REQUIRED/SAMPLE_SCOPE_INVALID/ASSIGNMENT_NOT_FOUND）；`formatApiError`（`api/client.ts`）按 `localStorage.lang`（与 LangProvider 同一键）查表返回译文，无译文的错误码保持 `CODE: message` 原样兜底。
- 验证：`client.test.ts` **8 passed**（新增 3 项：默认中文、英文、未知码兜底）；`tsc --noEmit` 与生产构建通过。
- 后续扩展：新错误码只需在 `apiErrors` 两张表中各加一行，无需改代码逻辑。

### 2026-09-18 删除标注任务 CSRF 误拦修复

- 问题：主平台删除标注任务报 `CSRF_TOKEN_REQUIRED: csrf token is required`。根因：`enforce_request_security` 注释声明"Bearer-token requests do not need a CSRF token"但实现从未检查 Authorization 头——只要请求携带 `portal_session` cookie 就强制 CSRF 双提交校验。本地开发中 8443 门户与 5173 主平台同用 `localhost`（cookie 不区分端口），门户登录后的会话 cookie 会随主平台请求一起发送，导致 Bearer 认证的 DELETE/POST/PATCH 被 403 误拦。
- 修复（`services/security.py`）：状态变更请求若带显式 `Authorization` 头则跳过 CSRF 校验——跨站页面无法在不窃取 token 的前提下设置该头，CSRF 针对的"环境 cookie 认证"不适用；纯 cookie 认证路径（Origin/Referer + 双提交 token）保持不变。
- 验证：`test_security_contract.py` **8 passed**（新增回归：Bearer+portal_session cookie 跳过 CSRF）+ `test_ci_workflow.py` 63 passed/138 subtests；端到端实测——Bearer+cookie DELETE 返回 204（用户场景修复），仅 cookie 无 Origin 返回 403 CSRF_ORIGIN_REQUIRED（保护仍在）。

### 2026-09-18 标注员审核删除操作与标注员管理

- 需求：标注员账号审核支持删除操作；新增"标注员管理"卡片管理已审核通过的标注员。
- 后端：`annotator_identity.py` 新增 `delete_annotator`（撤销该主体所有未撤销指派 → 显式删除 sessions/subject mappings/project grants/account，SQLite 无 FK 级联强制因此显式删除保证双后端一致）；`annotator_internal.py` 新增 `DELETE /api/admin/annotators/{subject_id}`（204，仅管理员，账号不存在返回 409）。
- 前端：用户管理页拆分为两个卡片——"标注员账号审核"只显示 pending/rejected（pending 行：通过/拒绝/删除；rejected 行：删除），"标注员管理"显示 active/disabled（active 行：停用/重置密码/删除；disabled 行：启用/删除）；重置密码弹窗调用既有 `POST /api/internal/annotators/{subject_id}/reset-password`（8-128 位、二次确认）。
- 验证：后端 `test_annotator_auth.py` **8 passed**（新增 3 项：删除撤销指派并清理身份、账号不存在报错、DELETE 接口管理员权限/204/409）；前端 `UserManagementPage.test.tsx` **3 passed**（新增审核/管理卡片数据分流与删除确认调用断言）；`tsc --noEmit` 与生产构建通过。
- 端到端（API 实测）：对 relay-test 依次 PATCH disabled（200）→ PATCH active（200）→ DELETE（204）→ 列表不再包含；浏览器确认两卡片渲染与按钮正确。浏览器内 POST/PATCH 一律 `net::ERR_ABORTED`（登录表单同样症状，PowerShell 同请求正常），判定为嵌入式浏览器环境问题，非本改动缺陷。
- 运维备注：本地 uvicorn `--reload` 在热重载时可能崩溃（WinError 233）并遗留孤儿子进程占用 127.0.0.1:8000 遮蔽新进程的 0.0.0.0 绑定；重启后端后需 `netstat -ano | findstr :8000` 检查并终止孤儿 PID（本次为 reloader 子进程 32320）。

### 2026-09-18 标注员门户（8443）与主平台（5173）数据打通

- 问题：8443 门户注册"成功"但 5173 用户管理页看不到申请。根因是双后端双数据库——8443 的 annotator 容器把认证转发到 Docker 栈 backend 容器（PostgreSQL），而 5173 本地开发栈查询的是 Windows 本地 uvicorn（SQLite `ml_platform.db`），两库互不相通。
- 方案（本地开发链路，不改生产配置）：新增 `docker-compose.override.yml` 将 annotator 容器的 `ANNOTATOR_API_ORIGIN` 指向 `http://host.docker.internal:8100`（`extra_hosts: host-gateway`）；新增 `temp_test/wsl_relay.py` 作为 WSL 内 TCP 中继（0.0.0.0:8100 → localhost:8000）。链路：容器 → host-gateway（WSL docker bridge）→ WSL 中继 8100 → WSL localhost（mirrored 网络）→ Windows uvicorn 0.0.0.0:8000。选择中继是因为 Windows 防火墙拦截容器对宿主 WLAN IP 的入站访问且无管理员权限加规则；host-gateway 在纯 WSL dockerd 下指向 WSL 内部网关而非 Windows。
- 数据迁移：将 Docker PostgreSQL 中已有的 7 条门户注册（portal-debug-20260918e/jingms/荆茂盛/jing/annotator-portal-test/annotator-portal-ui-test/jin）一次性迁移到本地 SQLite `annotator_accounts`（id/subject_id 去连字符、按 username 去重）；迁移脚本用后已删除。
- 验证（2026-09-18 端到端）：本地 backend 以 `--host 0.0.0.0 --reload` 运行；容器经中继访问本地后端返回 200；8443 注册 relay-test → 本地后端立即出现 pending；5173 用户管理"标注员账号审核"显示全部迁移账号与 relay-test；浏览器审核 relay-test 通过（"标注员账号已通过审核"）；8443 用 relay-test 登录成功进入"我的任务"工作台。注册→审核→登录闭环完成。
- 运维要求：WSL 重启后需重跑中继：`wsl sh -c "nohup python3 /mnt/e/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/temp_test/wsl_relay.py >/dev/null 2>&1 &"`；本地 backend 必须以 `--host 0.0.0.0` 启动。`docker-compose.override.yml` 仅用于本地开发，生产部署不受影响。
- 遗留：Docker `frontend`/`nginx` 容器仍处重启循环（5173 端口被本地 vite 占用 + frontend 网络沙箱损坏），修复需停 vite 后 `docker compose up -d --force-recreate frontend nginx`；4 条用户真实注册（荆茂盛/jingms/jing/jin 等）为 pending，待管理员在 5173 自行审核。

### 2026-09-18 标注员注册审核入口与接口修复

- 注册账号默认状态为 `pending`，不能直接登录标注员门户；管理员审核入口位于主平台“用户管理”页面顶部的“标注员账号审核”区域。
- 管理员可查看用户名、邮箱、申请时间和状态，并将待审核账号设为“通过”或“拒绝”。通过后账号才能登录 `http://localhost:8443/`。
- 修复审核 API 路径与主平台 `/api` 前缀不一致导致的 404：正式接口为 `GET /api/admin/annotators` 和 `PATCH /api/admin/annotators/{subject_id}/status`。
- 验证：当前工作树 OpenAPI 已注册上述接口；标注员身份服务 Python 编译通过；既有标注员认证测试待运行时数据库配置可用后执行。当前运行中的旧后端进程仍需重启后才能加载本次路由修复。
- 复验（2026-09-18）：运行中后端（uvicorn --reload）已加载路由——OpenAPI 含 `/api/admin/annotators` 与 `PATCH /api/admin/annotators/{subject_id}/status`，带 token 直连返回 200；浏览器端到端走通：`POST /portal/auth/register` 注册 pending 账号 → 用户管理页"标注员账号审核"显示待审核行 → 确认"通过" → 状态变"已通过"并提示成功。此前报告的 404 为旧进程时期日志，已消除。
- 门户注册 500 排查与复验（2026-09-18）：`http://localhost:8443/` 注册报 "Request failed (500)" 的根因是 Docker 栈 `postgres/redis/minio` 容器被停止（Exited (0)）→ 主平台 backend 容器启动失败（psycopg 解析不了 `postgres` 主机，unhealthy）→ annotator 容器把 `/portal/auth/register` 转发到 `http://backend:8000` 抛 `httpx.ConnectError` → 500。修复为 `docker start postgres/redis/minio` + `docker restart backend`，全部恢复 healthy；API 直连注册返回 201，浏览器 UI 注册成功显示"注册已提交，等待审核"。
- 遗留（2026-09-18）：Docker 主平台 `frontend`/`nginx` 容器处于重启循环——`frontend` 需绑定宿主 5173 端口，与本机 vite dev server（5173）冲突；且 `frontend` 网络沙箱损坏（restart 报 sandbox not found），需停本地 vite 后 `docker compose up -d --force-recreate frontend nginx` 恢复。不影响 8443 标注员门户与 8000 本地开发服务。

### 2026-09-18 数据标注四项行为严格对齐第七章及数据管理

- 修复任务列表无项目时只显示空列表的问题：前端支持可选 `project_id`，后端按当前用户可访问项目过滤未归档通用任务，避免 owner-only 漏项和越权泄露。
- 修复自动标注数据选择：数据版本只保留与数据管理一致的 active、非 normalized dataset artifact 来源；归档/删除来源不再出现在新建自动标注任务。
- 新建向导每次打开显式清空样本范围条件、自定义 schema 和相关草稿状态，删除的范围条件不会残留到后续任务。
- 弱监督聚类任务强制使用用户指定 label schema；模型 output contract 仅作为内部来源，缺少用户 schema 时后端返回 `WEAK_SUPERVISION_SCHEMA_REQUIRED`。
- 验证：前端数据标注/API 定向测试 **61 passed**；后端任务/自动创建定向测试 **3 passed**；前端 TypeScript/Vite 生产构建通过；`git diff --check` 通过。
- 边界：真实 PostgreSQL、Celery/Redis、浏览器登录和 Docker/WSL 运行态仍未执行。

### 2026-09-18 修复标签 schema 422 与数据版本列表 500

- 标签 schema 创建接口由“仅项目 owner”改为项目 `resource.create` 权限，与通用任务创建权限保持一致，项目编辑者不再因权限解析返回 422。
- 数据版本列表的 workflow-export 回填对不可用/越出存储根目录的历史 artifact 做隔离跳过并记录告警，避免单个坏 artifact 使整个 `/dataset-versions` 请求返回 500。
- 验证：标签 schema、数据版本、自动任务相关后端测试 **8 passed**；Python 编译和 `git diff --check` 通过。

### 2026-09-18 自动标注 §7.3/§7.4 四项偏差修复与聚类预览效果

- 背景：§7 实现审计发现 4 处与技术方案字面要求的偏差——置换重要性未接入聚类回退链、one-hot 聚合与未映射交互维度阻断未接入生产路径、加权特征空间“至少 2 个不同向量”只在评估抽样上检查、预览/执行错误载荷未携带 `details`（受影响样本数/样本标识）。
- 修复（后端）：`weighted_clustering.py` 新增置换重要性回退（原生/|coef_| 不可用时在冻结评估子集上按 `sklearn.inspection.permutation_importance` 计算，逐目标等权、clip 非负、方法与种子入工件 `importance_method`，全不可用仍返回 `FEATURE_IMPORTANCE_UNAVAILABLE`）；流式与内存两条路径在加权全空间断言“至少 2 个不同向量”，违反返回新错误码 `CLUSTER_DEGENERATE_FEATURE_SPACE`；`FeatureMap.restore_with_unmapped` 区分数值一维映射与无法归属的交互维度，`aggregate_model_importance` 遇未映射维度抛 `FEATURE_IMPORTANCE_UNMAPPED_DIMENSIONS:{索引}`。`annotation_strategies.py` 的 `_cluster_package_contract` 接入冻结 `feature_map`（`source_columns`+`one_hot_dimensions`）：编码宽度向量按逐目标 L1 归一化+one-hot 求和聚合回原始列并记录 `importance_encoding=one_hot_aggregated`，宽度超出的交互维度阻断；模型推理失败返回稳定错误码 `MODEL_INFERENCE_FAILED`。
- 修复（7.6）：预览失败 `error` 携带 `details`（`_ExecutionOutputError` 的受影响样本数/样本标识等），执行 worker 返回载荷与预览序列化新增 `error_code`/`error_details`，前端聚类预览失败直接展示服务端错误码。
- 新增（聚类预览效果）：预览 worker 汇总新增 `cluster_evaluation`（selected_k、逐 K 轮廓系数、evaluation_mode、评估样本数/总数、importance_method）；前端新组件 `ClusterPreviewPanel` 渲染逐簇样本数与占比条形、K 选择、评估方式（全量/确定性抽样）与权重来源，接入向导簇发现完成态、任务列表“配置策略”弹窗与 `PreviewDrawer`（summary.clusters 非空时显示“聚类预览”区）。
- 测试：新增/更新用例覆盖置换回退成功与全来源不可用失败、`MODEL_INFERENCE_FAILED`、内存/流式退化空间阻断、one-hot 聚合与未映射维度阻断、`ClusterPreviewPanel` 4 项与向导发现流程断言；后端 `test_annotation_strategies.py`+`test_annotation_task_state.py` 102 passed、`test_annotation_task_state_api.py`+`test_portal_internal_api.py` 100 passed；前端 `DataAnnotationPage.test.tsx` 56 passed、组件 4 passed，`tsc --noEmit` 与生产构建通过。
- 边界：SHAP 重要性仍按方案“经批准”条件未实现（无审批机制，缺失即失败封闭）；`>10 万`行置换回退仅使用 5 万确定性评估子集（已在工件记录方法与种子）；真实浏览器验收与 PostgreSQL 迁移执行仍未完成。

### 2026-09-17 自动标注创建流程严格对齐 §7.1 步骤 6-7

- 修复：自动标注向导创建草稿后立即生成最终配置预览；聚类模式先完成簇发现和策略保存，再以新任务修订生成最终预览。最终预览轮询完成后在向导内展示全量统计与分页样本，仅当预览完成、配置完整、无 `needs_review` 且样本已加载时启用“确认执行”，调用执行接口并返回任务列表。
- 验证：`DataAnnotationPage.test.tsx` 56 passed；前端 TypeScript 检查与生产构建通过。
- 边界：真实登录浏览器验收、真实 PostgreSQL 迁移执行仍需单独完成。

### 2026-09-17 自动标注向导内簇发现闭环（§7.1 步骤 3-7 严格实现）

- 问题：技术方案 §7.1 要求启用聚类时"先生成最终簇分配（步骤 3）→三选一策略（步骤 4）→配置簇映射/规则/兜底值（步骤 5）→预览冻结（步骤 6）→确认执行（步骤 7）"在向导内一气呵成；旧实现把簇打标签推迟到创建后任务列表『配置策略』弹窗，向导第 2 页无从看到簇、无法完成簇映射，违反步骤顺序且流程割裂。
- 修复（仅前端，后端合同已支持）：第 2 页弱监督=是时新增向导内闭环——未生成任务显示"生成聚类预览"按钮（`startGenericDiscovery`：复用向导校验→`POST /annotation-tasks` 以 `{clustering:true, cluster_discovery:true}` 落库→`createAnnotationPreview`→记录 previewId）；预览期间显示 Spin；失败显示错误+重试（重新 `createAnnotationPreview`）；完成后渲染 `AutomaticAnnotationStrategyEditor` 并注入预览 `summary.clusters`（`clusterOptionsForTask`），三选一策略/簇映射/规则/兜底值全部在向导内完成，footer"保存策略并完成"经 `saveGenericStrategy` 以 `PUT /annotation-tasks/{id}/configuration` 提交全量配置（task_revision/name/visible_columns/instructions/completion_criteria/due_at/configuration）。轮询 effect 每秒 `getAnnotationPreview` 直至 completed/ready 或 failed/cancelled；任务创建后第 1 页数据版本/模型版本/样本范围冻结（disabled）防止配置漂移；footer 主按钮四分支（下一页/创建通用任务/生成聚类预览/保存策略并完成，预览未完成禁用保存）。i18n zh/en 对称新增 9 条文案（聚类预览标题/进行中/失败/重试/生成/步骤提示/就绪提示/保存策略/已保存）。
- 竞态修复：原"预览进行中"判定 `genericDiscoveryPreviewId && 未完成` 在 previewId 尚未设置的窗口（任务已创建、`createAnnotationPreview` 在飞）会误渲染 clusters=[] 的空策略编辑器，随后被 Spin/最终编辑器替换——脱离 DOM 的 select 上派发的 change 事件不会冒泡到 React 根，导致策略切换静默丢失（rule 策略端到端测试失败根因）；判定改为 `(!genericDiscoveryPreviewId || 未完成) && !error`，该窗口全程显示 Spin，策略编辑器仅在簇数据就绪后渲染。
- 验证：前端 `DataAnnotationPage.test.tsx` 56 passed（2 个用例重写为向导内簇发现闭环端到端：cluster 策略断言 post 落库 discovery 配置+put 提交 `selected_clusters/cluster_labels/other_values`；rule 策略断言 put 提交 `rules/other_values` 完整配置；"上一页"用例改断言可返回并重新生成预览）；前端全量 `313 passed | 19 skipped`（62 文件）；`tsc --noEmit` 与生产构建通过。
- 边界：浏览器真实登录验收、真实 PostgreSQL 迁移执行仍未完成。

### 2026-09-17 新建自动标注向导化与模型版本可见性修复（§7.1 严格复现）

- 问题（用户报告 4 项）：1) "已启用模型版本"下拉看不到模型库注册的多数版本——列表端点静默过滤未审批/非 platform_joblib/合同无效版本，用户无从得知原因；2) 缺"下一页"分步流程，"是否启用聚类"混在基本信息页；3) 第 2 页缺"上一页"返回；4) 缺"是否启用弱监督标注"选择（否=模型原始输出，是=先聚类再按策略生成标签，对应技术方案 §7.1 步骤 2-3）。
- 修复（后端）：`GET /api/projects/{id}/annotation-model-versions` 改为返回全部非 archived/revoked 版本并附加 `selectable`/`ineligible_reason`（MODEL_VERSION_NOT_ENABLED / MODEL_SOURCE_UNSUPPORTED / MODEL_OUTPUT_CONTRACT_INVALID；合同无效时输出兜底 view `output_contract: null`），选项禁用+原因后缀替代静默消失；执行端约束不变（仍要求 approved/enabled/platform_joblib/有效合同）。
- 修复（前端）：genericSetupView 改造为两步向导（antd Steps 指示条）：第 1 页基本信息（数据版本+模型版本+冻结合同+样本范围+可见字段+说明+完成标准+截止时间，footer"下一页"），第 2 页标注规则（"是否启用弱监督标注" select：否→`{clustering:false, strategy:"model"}` 模型原始输出直出；是→渲染策略编辑器，规则策略创建即提交完整 rules/other_values，按簇/簇加规则以簇发现模式落库并提示后续"配置策略"补全；footer"上一页"+"创建通用任务"）。校验抽取 `genericSetupBasicsIncomplete` 供两按钮共用；`AnnotationModelVersion` 类型补 `selectable`/`ineligible_reason`（output_contract 可空）；i18n zh/en 对称补 13 条文案（步骤标题/弱监督/下一页/上一页/模型不可选原因等）。
- 验证：前端 `DataAnnotationPage.test.tsx` 56 passed（54 既有更新：4 个自动任务创建用例补"下一页"导航与弱监督 select、automatic setup 断言改"下一页"；2 个新增：不可选模型选项禁用+原因显示、上一页返回第 1 步）；前端全量 `313 passed | 19 skipped`；`tsc --noEmit` 与生产构建通过。后端新增 `test_annotation_model_version_listing_flags_eligibility`（pending→NOT_ENABLED、onnx→SOURCE_UNSUPPORTED、approved platform→selectable），`test_annotation_task_state_api.py` 21 passed，相关模块组合 90 passed。
- 边界：ONNX 来源版本仍不可用于自动标注预览（预览 worker 仅 joblib.load 平台产物，硬约束，以禁用+原因呈现）；簇发现模式下策略补全仍需"生成预览→任务列表『配置策略』"链路（§7.1 步骤 4-5，表单提示已说明）；浏览器真实登录验收、真实 PostgreSQL 迁移执行仍未完成。

### 2026-09-17 新建自动标注任务接入策略编辑器（§7.1 流程补全）

- 问题：新建自动标注任务表单（genericSetupView automatic 分支）仅有模型版本选择、冻结标签合同展示与"启用聚类"复选框；`genericAutomaticDraft` 状态存在但无任何编辑入口（死状态），且创建时 `automaticConfigurationFromDraft` 的 discovery 参数恒等于 `genericClustering`——聚类任务一律以簇发现模式落库，用户无从表达策略意图，规则/兜底值无处配置，也无流程指引。
- 修复（仅前端，后端合同已支持）：启用聚类且已选模型时渲染 `AutomaticAnnotationStrategyEditor`（clusters=[]，创建阶段无簇，编辑器自动隐藏簇映射区）；聚类开/关分别补 §7.2/§7.3 说明文案；按所选策略显示提示——"按规则"可在本页直接完成规则与全部兜底值配置，"按簇/簇加规则"提示簇映射需在簇分配生成后于任务列表『配置策略』中完成。创建序列化修正：rule 策略提交 `{clustering:true, strategy:"rule", rules, other_values}`（规则条件按数据版本 dtype 类型化校验）；cluster/cluster_rule 仍以 `{clustering:true, cluster_discovery:true}` 落库（后端约束：cluster 策略要求已选簇且簇须来自发现预览，cluster_discovery 要求空配置），创建成功提示分别引导后续步骤。i18n 补 zh/en 六条文案。
- 验证：前端 `DataAnnotationPage.test.tsx` 54 passed（更新原"按簇策略创建落库簇发现模式"用例：断言策略编辑器可见且默认按簇；新增"按规则策略创建提交 rules/other_values 完整配置"用例）；前端生产构建（tsc --noEmit + vite build）通过。
- 边界：cluster/cluster_rule 策略在创建页填写的规则/兜底值不落库（受后端簇发现约束），须生成预览后经任务列表『配置策略』弹窗补全，表单提示已说明该流程；浏览器真实登录验收、真实 PostgreSQL 迁移执行仍未完成。

### 2026-09-17 数据标注页任务列表区排布与显示整理

- 问题：任务列表区多个表格堆叠无标题区分——同一 `table-surface` 内通用任务表与历史（QualityRun）任务表贴连（`.data-annotation__generic-tasks` 此前无任何样式），历史表在无数据时常驻渲染空表；通用任务表 7 列 + 十余个行操作按钮且 `.table-row-actions` 为 `nowrap`，操作列溢出挤压；第一列列头误用"通用任务列表"；"刷新操作"按钮游离无归属；运行中的操作/执行结果两个区块也无标题。
- 修复（仅布局显示，不改功能逻辑）：新增 `.data-annotation__section-head` 区块标题样式，任务列表区加"任务列表"标题、历史任务子区加"历史任务"标题且仅 `runs.length > 0` 时渲染（通用任务为空时改显 Empty 空态，消除双重空表）；通用任务表第一列列头改为"任务"、增加 `scroll={{ x: 1180 }}`，行操作按钮允许换行（`flex-wrap`）；"运行中的操作"与"执行结果"区块加标题，刷新按钮并入标题行；各区块间 `margin-top: 20px` 分隔；新文案接入 zh/en i18n（tasksSection/legacySection/operationsSection/executionResults）。
- 验证：`DataAnnotationPage.test.tsx` 53 passed（调整 2 个用例：历史表改为数据驱动渲染后列头断言移至数据出现之后；区块标题与页面 h2 重名冲突改文案解决）；前端生产构建通过。

### 2026-09-17 修复本地库缺列导致"任务列表操作页" 500（durable_operations）

- 现象：创建任务成功后跳回任务列表，`GET /api/annotation-operations` 报 `sqlite3.OperationalError: no such column: durable_operations.project_id`。根因同上一条：迁移 `20260916_48_durable_operation_context` 新增的 `project_id`/`task_id`/`preview_id`/`resource_type` 4 列及 `ix_durable_operations_project_created`/`ix_durable_operations_task_created` 2 索引未同步 `ensure_schema_compatibility`，本地库 `create_all` 无法给已有表补列。
- 修复：`app/database_migrations.py` 的 `_SQLITE_COLUMNS`/`_SQLITE_INDEXES` 补齐上述 4 列 2 索引；本地库经该逻辑升级完毕（列与索引全部就位，幂等验证通过）。
- 验证：`tests/test_database_migrations.py + test_app.py + test_annotation_task_state_api.py` 33 passed。
- 备注：本地库（alembic_version 停在 `20260910_43`）对迁移 44-58 的列级需求现已全部由 `ensure_schema_compatibility` 覆盖；如再遇同类 500，优先比对该机制与新迁移的差集。

### 2026-09-17 修复本地库缺列导致"创建手动标注任务" 500

- 现象：`POST /api/annotations/label-schemas` 报 `sqlite3.OperationalError: table label_schemas has no column named purpose`。根因：本地开发库 `ml_platform.db`（alembic_version 停留在 `20260910_43`）由 `create_all` 演进，而本地模式的列级兼容机制 `ensure_schema_compatibility` 未同步迁移 55/56/57/58 的新增列——`label_schemas.purpose`、`label_columns.instruction`、`annotation_comments.parent_id/status/resolved_by/resolved_at`、`generic_annotation_tasks.name/completion_criteria/due_at`（后三个为本工作区新迁移引入，属遗漏）。
- 修复：`app/database_migrations.py` 的 `_SQLITE_COLUMNS` 补齐上述 9 列（加性、幂等，风格与既有条目一致）；本地库经该逻辑完成升级（列已全部就位，验证幂等）。本地库 `alembic_version` 版本戳仍为 `20260910_43`，本地模式不校验版本戳，无需处理；生产模式走完整 Alembic 链不受影响。
- 教训（共享经验候选）：在本地 SQLite 模式下新增 ORM 列时，除 Alembic 迁移外必须同步 `database_migrations._SQLITE_COLUMNS`，否则已有本地库在 `create_all`（只建新表不加列）后启动即 500。
- 验证：`tests/test_database_migrations.py + test_app.py + test_artifact_migration.py + test_artifact_service.py` 21 passed；`tests/test_database_production.py + test_annotation_task_state_api.py` 40 passed、2 failed 为预存失败（`test_production_inference_revision_*`，与本次无关）。

### 2026-09-17 数据标注功能对照第 6/7/8/9/13 章差距复核与创建合同补齐

- 以技术方案第 6、7、8、9、13 章为基准复核数据标注全链路。已确认覆盖：§6.1 名称/说明/范围/可见字段/多选指派、§7 自动策略全流程与失败重试、§8.2 指派（固定范围+截止时间+覆盖提醒）、§8.4 批注管理、§9.1 全状态机操作入口、§9.2/§9.3 回传验收面板（差异明细/空标签风险/验收/退回）、§13.1 列表操作中心/预览/回传列表、§13.2 门户队列与工作区基础。
- 补齐 §6.1 创建合同剩余字段：`GenericAnnotationTask` 新增 `completion_criteria`（Text，进 task_snapshot 参与 config_hash 冻结）与任务级 `due_at`（可空时间戳，不进快照），迁移 `20260917_58`；创建与配置更新接口、服务层序列化同步两字段；前端创建表单新增完成标准（textarea）、截止时间（date，提交为当日 23:59:59 本地时间 ISO）、标签列填写指引（透传 schema 列 instruction）；编辑弹窗同步两字段；任务列表新增截止时间列；i18n 补 zh/en 文案。
- 验证：后端 `tests/test_annotation_task_state_api.py` 20 passed（name 往返测试扩展覆盖 completion_criteria/due_at 创建-列表-配置更新全链路）；前端 `DataAnnotationPage.test.tsx` 53 passed（创建断言扩展完成标准/截止时间/列指引 payload，编辑断言扩展两字段，列表断言截止时间列）；前端生产构建通过；`tests/test_database_production.py` 20 passed、2 failed 为预存失败（`test_production_inference_revision_*`：测试仅升级到 `20260718_08` 而 ORM 已含迁移 45 的 `artifacts.archived_at`，与本次无关）。
- 已知剩余差距（未纳入本次）：§6.2 门户队列缺四类筛选（授权字段/标签完成状态/本人最近修改时间/批注状态），需门户前端→annotator 代理→主平台内部 API 三层联动；§9.3 不阻断风险提示仅空标签计数，标签分布/策略覆盖率/人工修改统计需后端汇总接口；schema 复用入口未实现。

### 2026-09-17 主平台通用任务创建/编辑/列表功能对照技术方案补齐

- 对照技术方案 §6.1/§9.1/§13.1/§16.2 修复主平台数据标注页通用任务缺口：后端 `GenericAnnotationTask` 新增 `name` 列（迁移 `20260917_57`，`server_default=""`），创建与配置更新接口支持名称（strip + 200 上限），服务层序列化补 `name`/`created_at`；`HEAD_REVISION` 测试常量同步 `20260917_57`。
- 前端创建表单新增任务名称（必填）、样本范围（全量/按条件筛选，条件按列 dtype 序列化为规则 DSL 的数值/字符串比较，条件间 AND，is_null/not_null 传 true）、可见字段勾选（默认全选，非空校验）；任务列表新增名称（缺失回退短 ID）、状态、样本数（快照 scope.sample_count）、创建时间、修订列与“加载更多任务”游标分页；draft/failed/needs_review 行新增“编辑任务”配置弹窗（名称/说明/可见字段，乐观并发 task_revision），draft/failed 行新增“重新生成预览”重试入口（复用 preview 幂等）；新增文案接入 zh/en i18n。
- 验证：主平台后端 `tests/test_annotation_task_state_api.py` 20 passed（含新增 name 往返/配置更新回归）；`tests/test_database_production.py` 40 passed、2 failed 为预存失败（`test_production_inference_revision_*`：测试仅升级到 `20260718_08` 而 ORM 已含迁移 45 的 `artifacts.archived_at`，与本次无关）；前端 `DataAnnotationPage.test.tsx` 53 passed（含新增 scope 筛选序列化、草稿编辑+失败重试用例）；前端生产构建通过。
- 边界：schema 复用（列表/选择既有 schema）未纳入本次；浏览器真实登录验收、真实 PostgreSQL 迁移执行仍未完成。

### 2026-09-16 第七章预测输出形状校验

- 自动标注模型推理在构造逐样本标签前，强制校验预测行数和冻结 schema 的目标列数；拒绝多行、少行、标量和错误维度，统一返回 `MODEL_OUTPUT_INVALID`，避免 `zip` 静默截断。
- 单目标预测接受 `(N,)` 和 `(N, 1)`，多目标必须为 `(N, T)`；保留原样本顺序和逐值类型校验。
- 新增回归先复现 4 failed、1 passed；修复后策略与任务状态组合为 83 passed、136 warnings。警告来自聚类重复点、依赖弃用和模型训练特征名。
- 本次不关闭第 6–9 章；自动预览有界内存、完整门户/回传链路及真实跨服务验收仍需继续。

> 文档状态：仅汇总未完成、待验证、风险和已延后工作。
> 文档更新日期：2026-09-15

### 2026-09-16 第七、八章容量门禁与门户队列补齐

- 第七章：预览创建前新增样本数、源字段数和标签字段数容量预检；超过首期基线时返回 `ANNOTATION_CAPACITY_EXCEEDED`、结构化 counts/limits/exceeded 明细，未知冻结样本范围返回 `ANNOTATION_CAPACITY_UNKNOWN`，且不创建 preview 或 durable operation。相同执行键的已存在 preview 先复用，避免配额变化破坏幂等重放。
- 第八章：主平台内部门户任务队列和 annotator proxy 新增服务端搜索、任务状态筛选、指派状态筛选、创建时间/截止时间/状态排序和游标翻页；门户前端新增对应控件、上一页/下一页、加载/失败重试和过期响应保护，继续保持服务端分页。
- 验证：后端自动标注任务/API 与门户组合 `108 passed、9 warnings`；主平台门户单测 `24 passed、2 warnings`；annotator backend `4 passed、2 warnings`；annotator frontend 队列 `4 passed`，生产构建通过，`git diff --check` 通过。
- 边界：当前容量检查仅覆盖样本数和列数，尚未完成内存、CPU、对象存储、队列配额的预估及执行前资源检查，不能关闭第 15.1 节。门户查询的组件/API 回归不能替代真实登录浏览器验收；同人同任务多次指派仍存在工作区仅解析最新指派的问题。标签 schema 编辑器、批量标注/批注完整前端、回传差异/质量风险 UI、真实 PostgreSQL 并发、真实 broker 租约恢复、完整 Chromium/WSL Docker 验收仍未完成。

### 2026-09-16 标注员门户批注交互补齐

- 工作区现在加载任务相关批注，按当前样本显示样本级批注和任务级批注，并支持提交新的样本级批注；提交失败保留输入内容并显示错误。
- 验证：annotator 工作区/队列定向前端 `21 passed`，annotator 前端生产构建通过；主平台自动标注、门户和任务状态组合 `110 passed`。
- 边界：主平台回传验收差异/质量风险界面和真实认证浏览器验收仍未完成。

### 2026-09-16 第九章回传验收与第六章 schema 编辑器补齐

- 主平台数据标注任务页新增回传验收面板：服务端分页读取回传批次，读取冻结差异明细，展示源数据/标签值、空标签质量风险，支持验收生成新数据版本和填写原因退回修改。
- 标签 schema 编辑器新增 schema 用途和列级说明字段，并在创建 schema 请求中传递 `purpose`、`instruction`。
- 修复 `AssignmentDialog` 对冻结任务范围 `frozen_task_scope` 的类型处理，避免前端构建因读取不存在的 `sample_ids` 失败。
- 验证：主平台回传/API/任务页定向前端 `56 passed`，主平台生产构建通过；annotator 工作区/队列 `21 passed`，annotator 构建通过；后端第六至第九章组合 `166 passed`。
- 边界：回传面板仍需真实登录浏览器验收；质量风险当前展示空标签风险，尚未接入更丰富的 schema 级质量规则摘要；真实 PostgreSQL、Celery 租约恢复、WSL Docker 和最终发布证据仍未完成。
> 当前工作树：`E:\codex_workspace\agent_spot_welding\.worktrees\general-automl-annotation-20260902`
> 当前分支：`general-automl-annotation-20260902`
> 当前整理基线：`190b55c`（当前工作树含未提交的自动标注与验收修正）

### 2026-09-16 AutoML 搜索强度合同回归修正

- 按技术方案第 10.4 统一测试合同为 `light=10`、`medium=30`、`high=80`、`ultra=200`，修正 AutoML tracking 测试中残留的旧枚举、旧资源断言和错误缩进；前端测试同步当前“轻度/中/高/Ultra”选项文案。
- 验证：后端 AutoML 搜索、多输出和 tracking 聚焦套件 `94 passed、10 subtests passed、52 warnings`；前端 AutoML 页面/API 聚焦套件 `14 passed、19 skipped`；Python 编译和 `git diff --check` 通过。
- 边界：该回归只证明当前搜索强度合同及相关页面测试一致，不代表技术方案第 1–17 章的真实数据制品、worker、自动标注跨服务流程、容量、恢复、浏览器和最终发布收据已完成；整体继续保持 `in_progress`。

## 1. 使用规则

### 2026-09-15 全方案一致性实施（当前口径）

- 导入身份合同续修：确认 sample_id 列时重建 row_locator 并同步嵌套解析选项，避免冻结样本使用用户 ID 而合同仍引用临时生成 ID。两处断言分别观察到失败后修复；完整运行态与整体方案仍未验收。

- 导入制品类型续修：确认阶段不再从 CSV 中转文件读取，归一化制品和确认后的版本制品均使用 Parquet；新增 `"001"`、空字符串、`None` 和显式类型转换回归，先观察到前导零丢失，修复后导入合同 40 passed。原始制品、异步 worker、迁移和容量验收仍未整体关闭。

- 导入资源边界续修：格式探测改为文件流读取 4096 字节，消除 `read_bytes()[:4096]` 先分配完整上传文件的问题。新增回归先失败，修复后导入合同 38 passed；该验证不代表完整解析器资源隔离或百万样本容量验收通过。

- 本轮续执行：回传列表游标改为在当前项目查询内解析，拒绝其他项目批次 ID；新增回归先失败，修复后回传/并发组合 14 passed、2 个依赖弃用警告。该证据仅覆盖查询隔离，不关闭待验收版本、全局完成、恢复或整体复现验收。

- 归档边界续修：数据集制品、DatasetVersion 和通用标注任务新增可逆 `archived_at`；DELETE 改为归档，不再删除对象存储或数据库记录；默认列表/详情隐藏归档对象，并提供恢复接口。新增迁移 `20260916_45`，SQLite 兼容层同步补列。数据集导入合同当前 40 passed；API 数据集历史测试因复用未升级的旧 SQLite 文件而出现 `archived_at` 缺列，需在 fresh/迁移后的数据库上重跑，不能记为通过。

- 全局回传完成条件续修：标注员范围确认后由服务端按冻结任务快照合并全部指派的最新样本修订，逐样本执行冻结 schema 完整性校验；仅全部样本合法时进入 `awaiting_return`，后续编辑自动恢复 `in_progress`。并发、状态机和回传组合当前 61 passed；真实门户、broker、数据库迁移和跨服务运行态仍未验收。

- 回传验收状态续修：验收事务在结果版本发布后同步将任务从 `returned_pending_acceptance` 推进到 `completed`；fresh SQLite 上数据集 API 套件 17 passed，回传/并发组合 14 passed。历史数据库兼容、真实门户和跨服务运行态仍保持待验证。

- 回传异步可靠性续修：回传批次新增 durable `operation_id`；门户回传接口返回 `202`、批次幂等复用原 operation；新增回传 worker、Celery 注册和 recovery dispatcher 分支，沿用租约、校验和和失败状态语义。回传/并发/Celery 聚焦套件 33 passed、4 subtests；真实 Redis/Celery broker 和重启恢复仍未验证。

- 迁移漂移修复：fresh SQLite Alembic upgrade 后 `alembic check` 首次发现 operation 外键及两个 `archived_at` 索引未入迁移；已补入 `20260916_45/46` 和 SQLite 兼容索引。当前 fresh upgrade/check 为通过，回传/Celery 聚焦仍为 33 passed、4 subtests。

- 2026-09-16 当前工作树运行态续验：从工作树根目录重新构建并强制重建 worker/scheduler，确认容器实际使用 `celery -A app.tasks.celery_app:celery_app`，连接 Compose Redis，注册 `ml_platform.execute_annotation_return`，并在固定 WSL 会话中观察 worker/scheduler 持续运行；Postgres、Redis、MinIO、MLflow 和 TensorBoard gateway 均达到健康状态。后端导入、并发和回传验收聚焦套件为 54 passed、2 个依赖弃用警告。此前一次无固定 WSL 会话的容器整体退出记录保留为环境生命周期问题，不能作为通过证据；真实回传 operation 停机、lease 过期、recovery 重派发和重复投递演练仍未完成，因此第 3、9、16、17 章及全方案仍为 `in_progress`。
- 2026-09-16 真实 broker 派发续验：在固定 WSL Compose 会话中执行 `celery inspect ping` 返回 worker `pong`，并通过 Redis 投递 `ml_platform.recover_operations`；worker 日志确认实际收到并完成该任务，返回 `{"recovered_operation_ids": [], "count": 0}`。该证据证明当前 worker/broker 的基础派发链路可用，但没有待恢复操作，尚未证明真实回传 operation 的停机、租约过期、重派发、重启完成和副作用幂等；相关章节继续保持 `in_progress`。
- 2026-09-16 自动标注/AutoML 路由边界修正：技术方案规定自动标注草稿使用 `/api/annotation-tasks`，AutoML 训练使用独立 `/api/automl-tasks`/训练合同；前端通用标注创建 helper 原先按 `mode=automatic` 错发 `/automl-tasks`，造成两类任务语义混用。已改为手动和自动标注均提交 `/annotation-tasks`，同步更新 API/page 回归；同时让任务列表对测试或旧数据中缺失的 `id` 做安全渲染。前端定向测试 **53 passed**、生产构建和 `git diff --check` 通过。真实 AutoML 训练 API、真实自动标注跨服务链路和最终 SHA 收据仍未完成，整体保持 `in_progress`。
- 2026-09-16 后端路由边界收口：`POST /api/automl-tasks` 原先错误复用通用标注任务创建器，现改为真正 AutoML `start_automl` 的规范别名；错误的通用路由已移除，自动标注继续使用 `/api/annotation-tasks` 并显式携带 `mode=automatic`。相关通用任务状态 API、AutoML tracking 和模型注册回归 **72 passed、10 subtests passed**。该修复只纠正路由领域归属，不代表真实数据制品到 AutoML worker 的端到端运行态或最终方案验收完成。
- 2026-09-16 AutoML 规范路由回归：发现训练 router 的前缀会把初始别名错误生成到 `/api/training/automl-tasks`；新增无前缀 `spec_router` 并在主应用注册，使技术方案要求的 `/api/automl-tasks` 精确进入同一 AutoML 训练处理器。新增规范路径回归与自动标注策略回归 **3 passed**；旧 `/api/training/automl/run` 兼容入口保持通过。真实数据制品、真实 worker 完整训练和候选注册仍待端到端验收。

- 2026-09-16 标注员门户任务队列续修：内部 `/api/internal/portal/tasks` 原先一次性读取全部 assignment 并固定返回空游标，已改为按当前标注员和有效项目授权过滤、按 assignment UUID 稳定倒序排序、支持 `cursor`/`limit`（最大 200）和非法/跨主体游标拒绝；annotator backend proxy 与前端 `listTasks` 同步转发分页参数。主平台门户组合回归为 14 passed。现有回传幂等测试合同同步为方案要求的 HTTP 202；annotator 子项目当前没有独立可用 Python 虚拟环境，门户 API/前端对应分页测试尚未执行，保持未验证。

- 2026-09-16 通用任务指派路由续补：前端使用的 `/api/annotation-tasks/{task_id}/assignments` 之前没有主平台实现，浏览器 route mock 掩盖了真实 404；新增任务归属校验、冻结 sample scope/标注员授权复用、HTTP 202 创建响应和 `GET` 游标列表（最大 200）。相关通用任务状态/API 组合为 23 passed，模块编译和 diff 检查通过。该路由仍需补齐全局写接口的请求 ID/幂等持久化及真实浏览器、跨服务运行态验证，不能关闭第 8、12、13、16 章。

- 2026-09-16 指派幂等续修：`annotation_assignments` 新增可空 `idempotency_key` 及 `(task_id, created_by, idempotency_key)` 唯一约束，服务层同键同请求复用原 assignment、同键不同范围/主体返回 `IDEMPOTENCY_CONFLICT`；通用创建路由要求 `Idempotency-Key`，前端生成并发送请求头。新增迁移 `20260916_47`，fresh SQLite `upgrade head` 与 `alembic check` 通过；幂等回归和相关后端组合共 30 passed，前端 assignment API 2 passed。真实并发 PostgreSQL 约束、浏览器和跨服务验证仍未完成。

- 2026-09-16 回归汇总：自动标注策略、任务状态、回传验收、门户和数据导入组合为 125 passed、8 个依赖/模型警告；主平台前端 `tsc --noEmit` 与生产构建通过。构建产物写入既有 `temp_test/frontend-dist` 验证目录，仍未作为发布制品；全量浏览器、annotator 子项目独立环境、真实跨服务指派幂等和最终 SHA 收据继续保持未验证。

- 2026-09-16 导出/离线运行时合同复核：模型导出、签名/SBOM/checksum、绑定自动标注策略、离线 `predict/annotate`、输入拒绝和输出格式组合为 20 passed、3 个依赖/模型警告。该结果证明当前实现具备聚焦合同覆盖，不证明干净 Docker/WSL 运行时、真实模型注册链路、当前 SHA 发布收据或容量验收已完成。

- 2026-09-16 指派请求审计字段续修：通用任务指派创建同时要求 `X-Request-ID` 与 `Idempotency-Key`，前端请求生成并发送二者，符合写接口审计/幂等入口约束；相关任务状态/API 回归 21 passed，前端 assignment API 2 passed，前端生产构建通过。跨服务重复请求、审计记录和真实浏览器仍待验证。

- 用户已确认按原技术方案第 1–17 章完整实施。当前入口为 [全方案一致性实施台账](ml-platform/docs/superpowers/plans/2026-09-15-general-platform-conformance.md)，详细原始任务步骤继续参考 2026-09-02 实施计划；发生冲突以技术方案为准。
- 下方历史 Task 1–13 `passed` 和“业务实现完成”不能作为本轮完整复现结论。数据导入、门户、回传、AutoML、离线导出和验收定义均有已确认缺口，整体保持 `in_progress`。
- 已开始：导入确认合同、独立导出运行时、门户 schema 编辑/自动保存/分页；草稿创建权限已按集中 `resource.create` 修复并通过相关 API 组合 30 tests、24 subtests（2 warnings）。
- 未完成：各条款生产链路、完整测试与迁移、真实浏览器、WSL Docker/broker/recovery、容量和备份恢复证据。局部绿灯不能关闭对应章节。
- 保留本轮开始前的 Compose 构建网络修复及其记录，不覆盖或提交该独立改动。

### 自动标注方案一致性补齐（进行中）

- 本次按技术方案第 7 章重新核验，历史 Task 6/12 passed 不作为当前端到端一致性证据。
- 已补：规则按标签列选择数值最小的优先级；同优先级冲突保持 needs_review；显式目标簇范围和规则簇过滤；配置类型校验；已启用模型版本选择和 output_contract 冻结；多列其他兜底、规则命中与簇映射编辑；确定性 K 评估抽样、冻结预处理/中心和发现工件复用。旧快照未声明目标簇时保持历史范围。
- 待补：聚类发现 -> 策略配置 -> 最终预览 -> 执行/指派的完整浏览器链路，以及真实 Docker/WSL、broker/recovery 运行态复核。当前不因组件或 route-mock 通过而宣称完整自动标注流程完成。
- 验证：策略和任务状态组合已覆盖发现工件、最终配置复用与多输出工件重要性；浏览器已覆盖通用预览/执行/回传/验收状态链路。完整最终验证结果需在补齐剩余运行态门禁后更新。
- 2026-09-16 增量：执行统计已从 `durable_operations.result_summary.stats` 拆为独立的可游标分页聚合表；历史摘要回填、UUID 往返和重复升级已验证。预览与执行 worker 的源行、结果、标签发布、样本明细和 checksum 已改为固定批次读取/写入，任务状态套件 **56 passed、8 warnings**。
- 当前剩余：自动聚类仍需完成百万样本资源预检与有界特征物化；真实 PostgreSQL/WSL Docker、Celery 租约恢复和完整 Chromium 链路尚未作为当前工作树最终证据执行。

- 开发前读取本文件、`AGENTS.md`、共享经验文档、技术方案和对应实施计划。
- Windows 宿主命令默认使用 PowerShell 7（`pwsh`）；Docker 命令在 WSL 中执行。
- 不覆盖用户已有改动；禁止使用 `git reset --hard`、`git clean` 或破坏性 `git checkout`。
- 严格区分 `planned`、`in_progress`、`blocked`、`passed`、`failed`、`cancelled` 和 `skipped`；未执行不能记为通过。
- `planned` 表示范围和计划已确认、但代码、迁移、测试、构建和浏览器验证均未开始；`pending_decision` 表示需要产品决策；`deferred` 表示用户暂时搁置，不得自行启动。
- 一项工作只有在实现、测试、运行时证据、文档和对应发布门禁均满足后才能标记完成。
- 完成项、旧失败和被后续结论覆盖的历史状态移入归档，不在本文件重复展开；归档原文不可改写。

## 2. 已完成范围与归档边界

Week 1–12 及 Week 9–12 最终验收已经关闭，不是当前待办。其证据、已完成工作和历史失败/阻断记录保留在以下文件：

- [2026-09-03 当前计划整理前的完整快照](DEVELOPMENT_PLAN.history-2026-09-03.md)
- [2026-08-23 之前的历史开发计划](DEVELOPMENT_PLAN.history-2026-08-23.md)

Week 9–12 的最终闭环证据为 GitHub Actions Run `33363122355`，验收代码 SHA 为 `3752794001c58b91d6a0e5f9c139f5635989a963`。该结果不能替代本计划所列通用平台任务的实现、迁移、浏览器、导出、恢复或发布证据。

## 3. 当前权威资料

| 文档 | 作用 | 当前状态 |
|---|---|---|
| [通用自动建模与数据标注平台技术方案](ml-platform/docs/technical-proposals/2026-09-01-general-automl-annotation-platform.md) | 产品、数据、接口、安全和验收合同 | 已评审，作为实现依据 |
| [通用自动建模与数据标注平台实施计划](ml-platform/docs/superpowers/plans/2026-09-02-general-automl-annotation-platform.md) | Task 1–14 的文件边界、接口、测试和依赖 | `in_progress` |
| [通用平台验收矩阵](ml-platform/docs/acceptance/2026-09-02-general-platform-acceptance-matrix.md) | 19 项验收编号、执行上下文和证据责任 | `in_progress` |
| [通用化迁移基线清单](ml-platform/docs/migrations/2026-09-02-genericization-inventory.md) | 去行业化迁移盘点与门禁 | `in_progress` | Task 1 后端边界已通过；下游生产导航和完整迁移仍待完成。 |
| [导出与离线运行时清单](ml-platform/docs/acceptance/2026-09-02-export-runtime-checklist.md) | 导出包和离线推理输入合同 | `in_progress` | 已有导出/离线实现和聚焦测试；完整当前 SHA 收据仍待 Task 14。 |

## 4. 项目阶段状态

| 阶段 | 工作范围 | 状态 | 当前口径 |
|---|---|---|---|
| Week 1–12 | 已交付的平台基础、生产化、权限通知与历史验收 | `passed` / `completed` | 已归档，不作为当前待办。 |
| 通用自动建模与数据标注平台 | 2026-09-02 实施计划 Task 1–14 | `in_progress` | 业务实现和远程六项 required jobs 已通过；通用 19 项 receipt 尚未接入 CI 的最终证据链，Task 14 暂不关闭。 |
| Week 13 | Kubernetes 基础接入 | `planned`（未开始） | 后续工作，见 BKL-04。 |
| Week 14 | Kubernetes Job/Pod 执行器 | `planned`（未开始） | 依赖 Week 13，见 BKL-05。 |
| Week 15 | Notebook、镜像与 GPU | `planned`（未开始） | 依赖 Kubernetes 基础能力，见 BKL-06。 |
| Week 16 | 多集群与资源治理 | `planned`（未开始） | 依赖 Week 13–15，见 BKL-07。 |
| Week 17 | 数据探索、质量报告、标注审核与数据回流 | `pending_decision` | 待产品范围确认，见 BKL-08、BKL-09。 |
| Week 18 | RAG 与工业智能体 | `deferred` | 暂时搁置，见 BKL-10。 |
| Week 19 | LLM 网关与 AIHub | `deferred` | 暂时搁置，见 BKL-11。 |
| Week 20 | 全产品验收、交付与培训 | `deferred` | 暂时搁置；不影响通用平台 Task 14 的独立验收。 |

## 5. 当前主交付计划

Task 1–14 的业务实现、迁移、测试和远程 required jobs 已完成；发布收据链仍需把通用 19 项 receipt 接入 CI 并在同一最终 SHA 上重新验证。文档评审、历史局部功能或旧 SHA 验收不替代本次发布证据。

| ID | 工作项 | 依赖 | 状态 |
|---|---|---|---|
| Task 1 | 全项目去行业化迁移基线 | 无；阻塞后续实现 | `passed` |
| Task 2 | 数据导入、数据版本和统一输入合同 | Task 1 | `passed` |
| Task 3 | AutoML 四种任务类型和训练合同 | Task 1、Task 2 | `passed` |
| Task 4 | 标签 schema、类型校验和修订历史 | Task 1、Task 2 | `passed` |
| Task 5 | 标注任务状态机、任务列表和预览 | Task 2、Task 4 | `passed` |
| Task 6 | 三种自动标注策略和特征重要性加权 KMeans | Task 3、Task 4、Task 5 | `passed` |
| Task 7 | 标注员独立认证、主体映射和服务边界 | Task 1、Task 2、Task 4 | `passed` |
| Task 8 | 指派、重叠样本并发、自动保存和回传锁 | Task 4、Task 5、Task 7 | `passed` |
| Task 9 | 回传结果列表、数据管理验收和站内通知 | Task 4、Task 5、Task 8 | `passed` |
| Task 10 | 模型候选手动注册和模型库生命周期 | Task 2、Task 3、Task 4、Task 5 | `passed` |
| Task 11 | 模型导出包和离线 `predict`/`annotate` | Task 2、Task 3、Task 6、Task 10 | `passed` |
| Task 12 | 主平台和标注员门户前端 | Task 5、Task 7、Task 8、Task 9、Task 10、Task 11 | `passed` |
| Task 13 | 异步 worker、幂等、恢复、清理和安全门禁 | Task 2、Task 5、Task 7、Task 8、Task 9、Task 10、Task 11 | `passed` |
| Task 14 | 全量验收、文档同步和发布门禁 | Task 1–13 | `in_progress` |

### 当前执行入口

1. 当前工作树已复核：Task 5 预览完成状态会同步回任务列表；页面/组件/台账回归为 **60/60**，生产构建通过，后端 Task 5/异步组合为 **75 passed、5 warnings**。
2. 后端测试基础设施复核：`tests.test_run_suite` 为 **7/7 OK**，pytest 版本为 **7 passed**，Week 17 聚合为 **21/21 模块通过、0 失败**；`git diff --check` 通过。
3. 上述均为带未提交修改的当前工作树验证，不是可绑定到 Git SHA 的发布收据；用户本地 `README.md` 继续排除，不暂存、不覆盖、不提交。
4. Task 5 的真实 broker 派发、worker 重启恢复、结果去重、任务列表刷新后的预览状态保持、操作中心和结果/统计分页已在实现及聚焦验收中收口；后续仅需在最终稳定 SHA 上重生成发布收据。
5. Task 6–13 继续补齐跨服务、浏览器、导出/离线、恢复和安全运行态证据。
6. Task 14 的后端/前端全量测试、Playwright、Alembic、Docker/WSL 恢复演练和远程 required jobs 已有证据；通用 19 项 receipt 的文件哈希与 CI 接入（收据纳入 `ML_PLATFORM_EVIDENCE_DIR` 最终 manifest 与上传产物、AUTH-02 证据路径修正）已在当前工作树完成并锁定回归，仍需在最终干净 SHA 提交并远程重跑 CI 后才能作为发布收据。
7. 每个 Task 的精确文件、接口、RED/GREEN 步骤和命令以实施计划为准；本文件不创建平行的实现步骤。

## 6. 遗留验证任务

这些条目已有局部代码或文档记录，但缺少当前可复现的完整验证。它们不应被标记为已完成，也不应绕开 Task 1 的通用化边界。

| ID | 未完成工作 | 来源 | 当前处理 | 状态 |
|---|---|---|---|---|
| LEG-01 | 验证历史注册模型的自动标注输入适配：在具备后端依赖的环境运行 API 回归，并以真实注册模型和数据集执行一次自动标注。 | `DEVELOPMENT_PLAN.history-2026-09-03.md` 的原 §7A | Task 1 决定保留迁移适配器还是移除行业特定依赖；若保留，必须补测试和运行时证据。 | `planned` |
| LEG-02 | 验证标注 CSV/XLSX 导出保留原始数据列：执行完整 API 回归，并在真实登录浏览器下载后人工复核文件内容。 | 归档原 §85 | 若 Task 1、Task 4 或 Task 11 改动导出路径，纳入相应 Task 的回归和 Task 14 证据。 | `planned` |
| ENV-01 | 在 Linux/CI checkout 或独立 LF 校验副本中验证 Week 11 验收 shell runner；当前 Windows `core.autocrlf` 物化的 CRLF 文件不能作为 WSL 直接执行结论。 | 归档原 §99 | Task 14 的恢复验收必须使用 LF 环境，并记录实际执行环境和回执。 | `risk` |

## 7. 从历史计划继承的产品待办

以下范围来自历史计划的未实现功能与优化候选。它们已纳入最新汇总，但不与通用自动建模和数据标注平台的 Task 1–14 混为同一承诺；除非另行立项，均不得抢占当前主交付计划。

| ID | 范围 | 状态 | 当前处置 |
|---|---|---|---|
| BKL-01 | 工作流导入导出、多人协作编辑、节点级断点续跑和调度优先级 | `planned` | Task 14 完成后单独制定工作流增强计划。 |
| BKL-02 | 数据集版本、完整生命周期和 ZIP 等历史入口统一 | `planned` | 与 Task 2 的数据版本合同衔接；通用化实施结束后再补齐非核心入口。 |
| BKL-03 | SSO 和更细粒度的资源级授权 | `planned` | 第 7 周角色审计和四通道通知已完成；SSO 与资源级授权需独立安全设计、迁移和验收。 |
| BKL-04 | Kubernetes 集群、命名空间、资源组、节点发现、凭据和连通性检查 | `planned`（Week 13 未开始） | Kubernetes 基础接入。 |
| BKL-05 | Kubernetes Job/Pod 提交、状态、日志、取消、超时和垃圾回收 | `planned`（Week 14 未开始） | 依赖 BKL-04。 |
| BKL-06 | Notebook、镜像构建、GPU 调度和资源配额 | `planned`（Week 15 未开始） | 依赖 BKL-04 和 BKL-05。 |
| BKL-07 | 多集群路由、存储挂载和资源治理/监控 | `planned`（Week 16 未开始） | 在单集群执行和 GPU 资源模型稳定后推进。 |
| BKL-08 | SQL Lab、数据探索、数据质量报告 | `pending_decision`（Week 17） | 需要明确数据权限、查询隔离、审计和成本边界。 |
| BKL-09 | 多模态标注、审核和数据回流 | `pending_decision`（Week 17） | Label Studio 集成已明确延后；仅在确认多模态需求后立项。 |
| BKL-10 | 生产级 RAG、检索评估、权限过滤和可靠智能体执行 | `deferred`（Week 18） | 暂时搁置，作为独立知识与智能体子项目处理。 |
| BKL-11 | LLM 网关、AIHub、一键开发、一键微调和一键部署 | `deferred`（Week 19） | 暂时搁置，依赖模型、资源、权限和交付生命周期稳定。 |
| BKL-12 | 全产品 E2E、性能、安全、备份恢复、升级、培训和交付资料 | `deferred`（Week 20） | 暂时搁置；通用平台 Task 14 的验收范围不受此状态影响。 |
| BKL-13 | MLflow SDK autolog、模型阶段流转、运行级缓存、错误分支、可配置重试和 Webhook/Event 触发 | `planned` | 拆分为训练治理与工作流增强两个计划，避免与现有运行时语义冲突。 |
| BKL-14 | 全链路类型化端口强校验、动态工作流、画布与工作流代码互转 | `deferred` | 先定义兼容边界和迁移策略，当前静态 DAG 继续作为稳定基线。 |
| BKL-15 | 可复现训练环境打包 | `planned` | 与 Task 11 的导出包区分；后续单独覆盖训练依赖、镜像和运行时锁定。 |
| BKL-16 | 行业化算子作业模板 | `deferred` | 当前核心平台必须保持通用；如未来需要模板，只能建立在通用数据合同之上。 |

## 8. 当前风险与门禁

- 通用平台仍处于 `in_progress`：Task 1–4 已通过各自当前本地聚焦证据，Task 5–14 尚未完成。迁移、运行时测试、构建、浏览器验收、导出验证、恢复演练和远程门禁均不能整体记为已完成。
- Task 1 必须先完成全项目行业特定引用盘点和迁移边界，禁止向新代码继续引入固定行业字段、路由、服务或工作流。
- 自动标注、认证、回传、导出和清理都涉及跨服务状态；每个 Task 需保留幂等、revision、权限和失败回执的测试证据。
- 对恢复、备份、升级和安全验收，脚本路径存在不等于可执行：必须记录容器/宿主机边界、环境变量、证书、Compose 服务、镜像和证据目录。
- Windows 产生的 CRLF shell 文件不能直接作为 WSL runner 的语法或运行结论；以 Linux/CI checkout 或独立 LF 副本为准。

## 9. 文档维护与本次整理记录

- 2026-09-04：Task 3 首轮实现经过独立复核未通过：生产 worker 会直接拒绝 `multioutput_*` 任务，2 折 CV 被错误排除，iterative stratification 仅为标记，API 幂等/取消、四档搜索强度、class-weight、完整 per-target/aggregate 持久化和 durable worker 接线均缺失。Task 3 状态保持 `in_progress`；此前实现提交和聚焦测试记录保留为历史证据，不代表任务完成。

- 2026-09-04：Task 3 修复轮次 1。补齐 2 折配置、multi-output worker 合同入口和联合标签频次校验；模型注册兼容完成的 AutoML candidate artifact，并在注册时补建满足现有 ModelVersion 外键的 ModelLibrary lineage。验证：`test_automl_multioutput.py` 8 passed；model registry service/API 27 passed（1 warning、2 subtests）；相关模块 py_compile 与 `git diff --check` 通过。Task 3 仍为 `in_progress`，真实多目标制品持久化、迭代分层折分配、折内预处理、搜索控制、幂等取消恢复和完整 AUC 分层尚未完成。
- 2026-09-04：Task 3 修复轮次 1 追加回归。修正注册平台版本的 AutoML 信任判定，使 artifact-only 候选可用匹配的 `model_artifact_id` 完成血缘校验；新增完整注册事务回归。验证：artifact-only 1 passed；AutoML/registry/API 合并套件 36 passed（1 warning、2 subtests）。Task 3 仍保持 `in_progress`。
- 2026-09-04：Task 3 修复轮次 1 收口并暂停。当前提交 `7a99fa9`、`16d8a98` 已补齐 2 折配置、multi-output worker 合同入口、联合标签频次校验、artifact-only candidate 注册兼容和血缘回归；`test_automl_multioutput.py` 8 passed，AutoML/registry/API 合并套件 36 passed（1 warning、2 subtests），相关模块 `py_compile` 与 `git diff --check` 通过。Task 3 仍为 `in_progress`，真实多目标制品持久化、迭代分层、折内预处理、搜索控制、幂等/取消/恢复、完整 AUC 分层及前端接线仍待完成；按用户要求暂停开发，明日从这些阻断和 scoped re-review 继续，不启动 Task 4。

- 每次 Task 完成后，在本文件更新当前状态、未完成项、风险和下一步；完成明细、旧失败和历史证据追加到归档，不回写旧事实。

- 2026-09-08：Task 7 开发推进。新增独立标注员账号、不可变 subject、门户会话、会话版本撤销、主体映射、项目授权和服务令牌校验；新增独立门户 FastAPI 应用及 Compose `annotator` 服务，默认端口通过 `ANNOTATOR_PORT` 配置为 8443。TDD 聚焦验证 `test_annotator_auth.py` 与 suite manifest 为 10 passed、2 subtests；Alembic upgrade、模块编译和 diff check 通过。Docker Compose 验证因当前环境未安装 Docker 无法执行。Task 7 保持 `in_progress`，门户任务/指派 API、生产密钥配置和浏览器/远程验收待后续 Task 8/Task 14 收口。
- 2026-09-08：Task 5 增量开发继续。按 TDD 先补预览列表所有者隔离、cursor 分页和状态转移审计回归，初始 3 项失败；随后在独立通用状态服务中实现任务所有者校验、预览 cursor 分页及 `annotation_task.transition` 成功审计事件。验证：状态机/API 聚焦测试 10 passed（含 1 warning），相关模块 `py_compile` 与 `git diff --check` 通过。Task 5 仍为 `in_progress`，任务快照持久化、异步预览 worker、统计结果和页面接线仍未完成。
- 2026-09-08：Task 5 快照合同增量。按 TDD 新增服务端快照测试，先验证请求字段未注册而失败；随后新增 `task_snapshot` 持久化字段和迁移，创建任务时校验数据版本归属、固定样本 ID、生成可见列/标签 schema/指令/配置 hash，并以 ORM 事件拒绝已冻结快照更新。验证：Task 5 状态/API/manifest 聚焦测试 16 passed（1 warning、2 subtests），Alembic upgrade/check、相关模块编译和 `git diff --check` 通过。Task 5 仍为 `in_progress`，异步 preview worker、样本统计与预览结果分页、页面操作中心接线待完成。
- 2026-09-08：Task 5 预览运行态增量。按 TDD 新增进度单调递增、完成时间、失败信息和 owner-scoped 详情回归；新增预览 `progress/error/completed_at` 字段及迁移 `20260908_27`，状态服务支持运行态更新并拒绝进度回退，详情接口返回可恢复所需运行态。验证：Task 5 状态/API/manifest 聚焦测试 18 passed（2 warnings、2 subtests），Alembic upgrade/check、相关模块编译和 `git diff --check` 通过。Task 5 仍为 `in_progress`，真实异步 worker、样本统计和预览结果分页、页面操作中心接线待完成。
- 2026-09-08：Task 5 worker 增量。新增通用 Celery `execute_annotation_preview` 任务并注册 worker 发现列表；worker 仅读取不可变 `task_snapshot`，写入 running/completed 进度和样本/可见列/标签列摘要。直接 worker 回归通过；当前 API 创建仍返回 queued，尚未在无 broker 环境强制派发，恢复调度和真实 broker 验证仍待完成。Task 5 保持 `in_progress`。
- 2026-09-08：Task 5 生命周期与错误回归收口。修正测试先运行 preview worker 后再验证 publish/execute；worker 异常时持久化 `failed`、单调 progress 和脱敏 error，并将任务从 `previewing` 置为 `failed`；任务列表在 cursor 前计算完整 total；新状态 API 错误统一包含 `request_id`、`code`、`message`、`details` 并保留 `detail.code`。验证：状态/API 聚焦套件 19 passed、1 warning，相关模块编译和 `git diff --check` 通过。Task 5 仍待真实 broker、恢复调度、前端详情接线及完整验收，状态保持 `in_progress`。
- 2026-09-08：Task 6 核心服务增量。按 TDD 新增通用规则 DSL、三种自动策略互斥/兜底校验、逐列来源优先级与冲突 `needs_review`，以及重要性聚合和确定性加权 KMeans（大样本 silhouette 评估上限 50,000、最终分配覆盖全量）。新增不可变 `AnnotationStrategyArtifact` 模型与迁移 `20260908_29`，测试注册到 week manifest。验证：`tests/test_annotation_strategies.py` **7 passed**；相关模块 `py_compile` 与 `git diff --check` 通过。Task 6 API/worker/前端接线、完整迁移和浏览器验收仍未完成，状态保持 `in_progress`。
- 2026-09-08：Task 8 并发与回传锁增量。按 TDD 新增重叠指派、样本级 revision 冲突、完整服务端标签集合、回传幂等、回传后只读锁及显式 edit-for-return 流程测试；新增 `AnnotationAssignment`、`AnnotationAssignmentSample`、`AnnotationReturnBatch` 模型、迁移 `20260908_31`、通用并发服务、annotator 请求 schema 和主平台指派/保存/确认/回传 API。验证：`tests/test_annotation_concurrency.py tests/test_annotator_auth.py` **8 passed**；相关模块 `py_compile` 通过。Task 8 仍未完成：项目/标注员授权、任务暂停/撤销守卫、独立门户接线、评论与回传 worker、真实 API 集成和完整迁移升级验证待继续。
- 2026-09-08：Task 6 运行时增量。按 TDD 先验证自动预览未持久化策略工件而失败；随后新增冻结快照策略编排入口，通用 preview worker 持久化每个任务 revision/config hash 对应的不可变 `AnnotationStrategyArtifact`，并写入逐样本策略决策。聚类配置缺失可信模型重要性时统一失败封闭为 `needs_review`，不伪造等权重；预览详情只提供策略和复核数量摘要，不暴露样本来源链。验证：Task 5/6 状态、API、worker 与策略聚焦套件 **30 passed、7 warnings**；`py_compile`、Alembic `upgrade/check`、`git diff --check` 通过。Task 6 完整模型工件加载/加权聚类执行、前端策略配置和浏览器验收仍未完成，状态保持 `in_progress`。
- 2026-09-03：将整理前的完整 `DEVELOPMENT_PLAN.md` 保存为 `DEVELOPMENT_PLAN.history-2026-09-03.md`。Week 1–12 及历史执行记录已从当前视图分离。
- 2026-09-03：从 `DEVELOPMENT_PLAN.history-2026-08-23.md` 回收尚未实现的工作流、数据治理、SSO、云原生、数据探索、RAG/AIHub 和优化候选，并按 `planned`、`pending_decision` 或 `deferred` 进入第 7 节。
- 2026-09-03：没有提升任何业务状态；通用平台 Task 1–14、遗留验证项和 backlog 均保持未完成状态。
- 2026-09-03：用户确认 Week 1–12 已完成，Week 13–16 未开始，Week 17 待定，Week 18–20 暂时搁置；同时确认通用自动建模与数据标注平台实施计划尚未开始开发。当前汇总据此更新，不将任何计划或文档工作记为实现完成。
- 2026-09-03：整理顶层 `README.md`，补充以 PowerShell 7 为默认宿主环境的本地启动、测试、构建和 WSL Docker Compose 入口；明确历史行业化文档的参考边界，并标明通用平台 Task 1–14 仍为 `planned`。本次仅完成文档整理，未执行通用平台代码、迁移、测试或运行时验收。
- 2026-09-03：启动通用平台 Task 1。已建立 `GenericAnnotationTask`、通用 `/api/annotation-tasks` 与 `/api/automl-tasks` 入口、旧点焊创建入口的结构化 `410 GENERIC_API_REQUIRED` 边界、旧质量运行迁移适配器、初始去行业化盘点和契约测试；当前状态为 `in_progress`。由于 Python 3.14 环境缺少 `fastapi`/`httpx`，聚焦测试和完整 manifest 验证尚未执行通过，不能提升为 `passed`。
- 2026-09-03：Task 1 修复轮次补充通用任务 Alembic revision `20260903_15`、显式 `X-Request-ID`/`Idempotency-Key` 和 Pydantic 请求合同、旧运行迁移的 run/project/actor 授权、并发幂等回读、源样本/修订/快照元数据及稳定 checksum 校验。前端生产导航和旧服务彻底去行业化仍是 Task 1 remaining，未标记完成；测试仍受后端依赖缺失阻断。
- 2026-09-03：Task 1 修复轮次 2 明确前端生产导航/API client 全面替换属于 Task 12；Task 1 仅验收后端通用边界、旧写入口关闭、迁移适配器和禁止新代码依赖行业 feature builder 的 adapter 标记与清单。迁移 revision 对已有部分表执行补列、约束和索引的幂等升级；迁移完整性和 410 统一请求合同测试已补充，运行验证仍需依赖就绪环境。
- 2026-09-03：本地分支整理的详细记录为：任务范围仅限本地 Git 分支引用；依据 `git branch --merged main`、祖先关系和工作树占用安全删除 16 个已被 `main` 完整包含的历史/临时本地分支；保留当前 `main`、链接工作树占用分支和仍有未合并独有提交的分支；未删除远端分支、链接工作树或缓存/未跟踪文件。验证结果为本地分支从 23 个减少到 7 个，`main`、`origin/main` 与当时基线一致；后续清理需用户明确指定范围。
- 2026-09-03：按用户要求发布本次变更：功能分支提交 `f29191ba8980f0066a98b8dd8af26e70890d78d2` 已推送到 `origin/general-automl-annotation-20260902`；随后与根 `main` 的分支整理提交合并为 `f6c8bff64458f305f1568f67ab3f8479983431f4` 并推送到 `origin/main`。README 未加入任何提交，仅在本地工作树和根 `main` 工作树同步保留。
- 2026-09-03：发布前验证记录：README 以外的工作树变更已提交并推送，`git diff --check` 退出码为 0；后端标准套件因 `python` 命令仅指向 WindowsApps 占位符、Python 3.14 环境未安装 `fastapi`，前端因缺少 `node_modules` 未执行测试和构建。上述环境缺口不计为测试通过，也不改变通用平台 Task 1–14 的 `planned` 状态。
- 2026-09-04：Task 1 收口。使用 backend `.venv` 执行 `python -m unittest tests.test_genericization_contract tests.test_suite_manifest -v`，23/23 通过；从 `ml-platform/backend` 根运行源码去行业化门禁返回空违规；`alembic check` 与 `alembic upgrade head` 均通过；相关模块 `py_compile` 和 `git diff --check` 通过。Task 1 状态提升为 `passed`，README 仍为本地专用未提交文件。
- 2026-09-04：启动 Task 2。依赖检查确认 pandas/openpyxl 可用，但 `.venv` 尚缺 pytest、pyarrow 和 XML 安全解析依赖；先按 TDD 写入 `test_dataset_import_contract.py` 并执行 RED，缺失的解析/版本/输入合同模块导致测试失败后再实现。Task 2 状态为 `in_progress`，整体通用平台保持 `in_progress`。
- 2026-09-04：Task 2 收口。新增 CSV/Excel/Parquet/JSON/XML 安全解析、重复键/列与非标量拒绝、文件/行/列/深度/字段/耗时限制、稳定 hash/sample_id、原始与归一化制品补偿、不可变数据版本/列/样本/导入记录、统一输入合同、数据版本导入/查询 API、Alembic 迁移和 SQLite 兼容。`pytest tests/test_dataset_import_contract.py tests/test_database_migrations.py tests/test_artifact_storage_integration.py tests/test_genericization_contract.py tests/test_suite_manifest.py -q` 为 46 passed（1 warning、2 subtests）；`alembic upgrade head`、`py_compile`、`git diff --check` 均通过。完整后端套件、浏览器验收和远程 CI 未执行；Task 3/4 仍为 `planned`。
- 2026-09-04：Task 2 Round 3 同步。当前本地提交 `b1caac6a5fd6f5e9544b7e98d5080560da091671` 已补齐 API 补偿清理失败显式 `DATA_CLEANUP_FAILED`、不可变 `DatasetVersion` 制品删除 `409 DATA_IMMUTABLE_ARTIFACT` 防护，以及 ZIP 路径、单成员和累计展开字节的预检与流式二次计数。当前 SHA 的聚焦证据为：`test_dataset_import_contract.py` 32 passed、`test_api_datasets.py` 15 passed、迁移/存储/通用化/manifest 聚焦集 28 passed（2 subtests）、`alembic check`、`alembic upgrade head`、`compileall app tests` 与 `git diff --check` 均通过。Task 2 在本地聚焦合同和 API 范围内为 `passed`；完整后端套件、浏览器 E2E、远程 CI 和 Task 13 parser process isolation 仍为 `pending`，不能外推为整体发布或平台验收通过。Task 3、Task 4 保持 `planned`。
- 2026-09-04：Task 2 Round 4 同步。额外审计确认批量和 ZIP 结构化条目在 `freeze_dataset_version()` 内已经提交不可变版本；修复提交 `2ab41655a75e7ba106a78ba07047eaa3287be346` 将外层补偿范围收窄为未版本化 legacy artifact，避免后续条目失败时删除已提交版本引用的原始/归一化制品。新增批量与 ZIP 回归均通过；Task 2 在聚焦本地合同/API 范围内保持 `passed`，Task 3/4 依赖已满足。完整后端套件、浏览器 E2E、远程 CI 和 Task 13 parser process isolation 仍为 `pending`。

- 2026-09-05：Task 3 fix round 4 实现检查点。生产 multi-output AUC 已改为聚合全部 CV fold 的 binary/multiclass 连续分数，任一目标分数不完整即标记 incomplete，不再回退旧报告；worker 增加有界 trial 循环、deadline、共享 split、持久化取消轮询和 heartbeat；AutoML 启动增加用户作用域 `Idempotency-Key`、请求指纹和迁移 `20260905_19`。聚焦套件 99 passed（57 warnings、12 subtests），编译、迁移 upgrade/check 和 diff check 通过。Task 3 仍为 `in_progress` 等待 scoped re-review，Task 4 保持 `planned`；全 family 搜索、真正 iterative multilabel stratification、前端/浏览器和远端 CI 仍未完成。

- 2026-09-05：Task 3 fix round 5 实现检查点。worker 合并而非覆盖幂等请求指纹；legacy SQLite 增加 owner/key 唯一索引；Celery Beat 调度 TrainingJob recovery，AutoML stale job 无 checkpoint 可安全 requeue；multi-output 按 `algorithm_ids` 运行 catalog/grid family trial，采用确定性 iterative multilabel 分层及 fold-local imputer/scaler pipeline；timeout 保留已完成 trial。目标 RED 为 6 failed/1 passed，GREEN 7 passed；扩展聚焦集 129 passed（1 个可选 LightGBM 环境测试 deselected、59 warnings、16 subtests）。Task 3 仍为 `in_progress`，Task 4 保持 `planned`。

- 2026-09-05：Task 3 fix round 5 实现检查点。worker 合并而非覆盖 `automl_contract`，完成后仍可按原幂等键回放；SQLite compatibility 增加 `(user_id, automl_idempotency_key)` 唯一索引；Celery Beat 实际调度 stale TrainingJob recovery，AutoML 可无 checkpoint 安全重排；multi-output 按 `algorithm_ids` 运行 catalog family/grid trial，采用确定性 iterative multilabel 分层和 fold-local imputer/scaler pipeline；timeout 保留已完成 trial 并标记预算耗尽。RED 为 6 failed/1 passed，目标 GREEN 7 passed，扩展聚焦集 129 passed（1 个未安装 LightGBM 用例 deselected、59 warnings、16 subtests）。Task 3 仍为 `in_progress` 等待 scoped re-review，Task 4 保持 `planned`。

- 2026-09-05：Task 3 fix round 6 实现检查点。multi-output timeout 保留 best-so-far artifact/reports/metrics 并以 completed + `budget_exhausted` 收口；`search_strength` 实际注入 family resource 参数；grid 使用 Cartesian combinations，尊重 `algorithm_ids` 与 `max_trials`。目标回归通过，Task 3 仍为 `in_progress`，Task 4 保持 `planned`。


- 2026-09-05：Task 3 fix round 7 实现检查点。single-output Optuna 在已有成功 trial 时对 timeout 采用 best-so-far 部分成功语义并持久化 artifact/reports/metrics；multi-output 低 `max_trials` grid 先保证每个请求且可用 family 至少一个 trial，再公平轮询剩余槽位。目标回归和 AutoML/multioutput 聚焦集通过（64 passed、10 subtests）；Task 3 仍为 `in_progress`，Task 4 保持 `planned`。

- 2026-09-07：Task 3 继续开发。多输出 trial 规划新增五种搜索方法的可观测参数序列：`random` 对搜索空间采样，`bayesian` 产生确定性可重放探索，`evolutionary` 逐参数变异，`multi_fidelity` 使用 family resource rung；保留旧任务缺省 `strength` 兼容路径，并将缺省 `class_weight` 按合同解释为启用。新增非网格搜索差异性回归。验证：`python -m pytest tests/test_automl_tracking.py -q` 为 **63 passed、11 warnings、10 subtests**；`python -m pytest tests/test_automl_multioutput.py tests/test_automl_report.py -q` 为 **23 passed、2 warnings**。Task 3 仍为 `in_progress`；可选 LightGBM、前端完整浏览器/远程 CI、完整后端门禁仍未完成，Task 4 保持 `planned`。

- 2026-09-07：Task 3 收口并启动 Task 4。多输出 `random`、`bayesian`、`evolutionary`、`multi_fidelity` 已接入与单输出共享的 Optuna family search，使用真实 sampler/pruner 和 trial 分数反馈；`grid` 与 legacy `strength` 路径保持兼容。最终验证：Task 3 后端套件 **146 passed、10 warnings、12 subtests**；前端 Task 3 聚焦测试 **20 passed、19 个历史 skipped**；完整前端套件 **262 passed、19 个历史 skipped**；生产构建、Alembic upgrade/check、模块编译、`git diff --check` 和 Chromium AutoML E2E **1 passed**。可选依赖 `xgboost 3.2.0`、`lightgbm 4.6.0`、`catboost 1.2.10` 均可导入。Task 3 状态提升为 `passed`；Task 4 按依赖进入 `in_progress`。远程 CI 仍属于后续发布/Task 14 门禁，不外推为已通过。
 - 2026-09-07：Task 3 收口并启动 Task 4。多输出 `random`、`bayesian`、`evolutionary`、`multi_fidelity` 已接入与单输出共享的 Optuna family search，使用真实 sampler/pruner 和 trial 分数反馈；`grid` 与 legacy `strength` 路径保持兼容。最终验证：Task 3 后端套件 **146 passed、10 warnings、12 subtests**；前端 Task 3 聚焦测试 **20 passed、19 个历史 skipped**；完整前端套件 **262 passed、19 个历史 skipped**；生产构建、Alembic upgrade/check、模块编译、`git diff --check` 和 Chromium AutoML E2E **1 passed**。可选依赖 `xgboost 3.2.0`、`lightgbm 4.6.0`、`catboost 1.2.10` 均可导入。Task 3 状态提升为 `passed`；Task 4 按依赖进入 `in_progress`。远程 CI 仍属于后续发布/Task 14 门禁，不外推为已通过。

- 2026-09-07：Task 4 完成当前本地聚焦范围。新增冻结的多列标签 schema、列级约束、任务 schema 绑定快照、当前值与不可变修订历史、评论/确认表、legacy 单列回填迁移和原子 `base_revision` 并发写入；通用任务创建校验 schema 属于项目并自动创建绑定，样本读写/确认拒绝未绑定或错误绑定任务。验证：标签服务、API、通用任务、迁移和 suite manifest 聚焦套件 **36 passed、1 warning、2 subtests**；前端 LabelSchemaEditor、DataAnnotationPage 和 week manifest **48 passed**；`npm run build`、Alembic upgrade/check、模块 `py_compile` 与 `git diff --check` 通过。Task 4 状态提升为 `passed`；Task 5 继续 `planned`。Task 4 未实现样本初始化、任务状态机、完整列表和预览，这些仍属 Task 5。全量后端历史回归仍有 25 个失败，集中在旧点焊 API 测试未提供新请求关联头，以及既有证据/迁移基线假设；不计入 Task 4 聚焦门禁，已保留为后续兼容性工作。
- 2026-09-07：Task 5 启动。新增通用任务 revision、预览操作幂等、状态转移守卫、项目/所有者隔离列表分页接口和预览列表接口；新增独立状态服务、schema、迁移、前端预览抽屉与 API 客户端。当前状态为 `in_progress`，待完成完整任务快照、异步 worker、样本统计/预览分页及页面操作中心接线。
- 2026-09-07：Task 5 边界修正。状态与预览逻辑已从历史兼容适配器中隔离到独立通用服务和路由；任务创建保留 `draft` 初始状态，预览按 `(task_id, task_revision, config_hash)` 幂等，非法 cursor 和未授权预览返回结构化错误。验证：Task 5 后端聚焦 **10 passed、1 warning、2 subtests**；前端预览组件与 manifest **8 passed**；构建、迁移检查、编译和 diff check 通过。Task 5 仍为 `in_progress`。
2026-09-09：Task 8 并发授权与状态守卫增量。修复冻结任务快照之外的样本指派、暂停任务仍可写入、required 标签未在确认时校验、重叠指派未统一修订历史等缺口；新增快照范围与项目/标注员授权校验、任务状态 fail-closed、冻结 schema 校验、AnnotationRevision 持久化及重叠 assignment 同步。API 传递平台 actor 作为 revision author；预览 recovery 改为延迟导入以消除 worker 注册循环依赖。验证：test_annotation_concurrency.py 6 passed；门户/回传/并发组合 17 passed；状态/异步/安全/策略组合 60 passed。Task 8/13/14 的完整迁移、浏览器、恢复和远程 CI 门禁仍未完成。

- 2026-09-09：当前 SHA 验证检查点为 `e94862af844ea95a31203423c24a8ececd7553d6`。已验证：既有 Task 5–9/13 聚焦后端证据、`alembic check` 无新升级操作、fresh SQLite `alembic upgrade head` 到 `20260909_40`、前端生产构建、`git diff --check` 退出码 0（仅有 Windows 换行转换提示）。完整后端 active suite（134 个模块）退出码 1：部分历史数据库/通知检查失败，安全门禁模块超过 300 秒超时；不能记为全量通过。前端全量 Vitest 退出码 1：56 个文件通过、1 个文件失败、274 个测试通过、19 个历史 skipped；失败为 `weekAcceptance.test.ts` 的测试台账遗漏五个新测试文件。当前环境无 Docker，真实 broker、Compose、Playwright、导出/离线、恢复和远程 CI 尚无当前 SHA 通过收据。
- 2026-09-09：进度决定保持 Task 5–14 为 `in_progress`，不生成发布完成结论。下一执行入口：先补齐前端测试台账并重跑 manifest/全量 Vitest，再隔离修复后端全量失败，之后继续 Task 5 的 broker 派发、恢复调度、结果分页和操作中心接线。

- 2026-09-09：进度整理复核。针对上一条记录的前端台账遗漏，先运行 `npm test -- --run src/weekAcceptance.test.ts`，结果为 **7 passed**；随后运行完整 Vitest，结果为 **57 个测试文件通过、275 个测试通过、19 个历史 skipped，退出码 0**。后端 `tests.test_celery_workflows` 重新执行为 **19/19 OK**，确认时间辅助函数拆分后的 worker 导入回归保持通过。此前后端完整 active suite 的失败/超时、Docker/真实 broker/Playwright/导出离线/恢复/远程 CI 缺口仍然有效，未被本次聚焦证据覆盖。
- 2026-09-09：整理后的状态不提升任务等级：Task 1–4 仍仅在已记录的本地聚焦范围内为 `passed`，Task 5–14 保持 `in_progress`；当前分支仍未提交或推送，`README.md` 继续作为用户本地修改排除在外。下一入口为隔离后端全量失败并继续 Task 5 的 broker 派发、恢复调度、结果分页和操作中心接线，随后收集 Task 6–13 的完整运行态证据。
- 2026-09-09：新增测试基础设施风险记录：`run_suite.py` 当前对每个模块固定调用 `unittest`，对 pytest 风格模块会出现 `NO TESTS RAN`，因此 Week 17 的自动化套件结果在修复前不能作为有效门禁。下一轮先在 `tests/test_run_suite.py` 增加框架识别/执行策略回归，再重跑受影响周次。

## 10. 2026-09-09 当前进度快照（整理）

| 范围 | 当前结论 | 已验证或已存在 | 未完成门禁 |
|---|---|---|---|
| Task 1–4 | `passed`（仅限已记录的本地聚焦范围） | 实现、迁移、聚焦测试和源码检查已有当前记录 | 完整后端、远程 CI 和平台级发布门禁仍由 Task 14 统一负责 |
| Task 5 | `passed` | 状态转移、任务快照、预览/执行幂等、进度/错误/详情/列表接口、结果/统计分页、统一操作中心和通用预览/执行 worker 已完成 | Task 14 仍需在最终干净 SHA 重新绑定全量发布收据 |
| Task 6 | `passed` | 规则 DSL、互斥策略、重要性聚合、确定性加权聚类、策略工件持久化和模型工件加载；API/worker/前端聚焦接线与回归已验证 | Task 14 仍需在最终干净 SHA 重新绑定完整发布收据；浏览器和跨服务运行态证据不属于本地 Task 6 聚焦结论 |
| Task 7 | `passed` | 独立账号、会话撤销、主体映射、项目授权、门户代理 API、服务身份校验及独立门户前后端聚焦验证已完成 | Task 14 仍需在最终干净 SHA 验证 Compose/生产密钥、完整浏览器和远程证据；当前主机无 Docker 命令 |
| Task 8 | `passed` | 重叠指派、样本 revision 冲突、回传幂等、回传锁、显式重新编辑、状态守卫和门户授权接线已通过聚焦验证 | Task 14 仍需在最终干净 SHA 验证容器、真实 broker/recovery、完整浏览器和远程证据 |
| Task 9 | `passed` | 回传、数据管理验收和通知聚焦验证已通过 | Task 14 仍需在最终干净 SHA 重新绑定完整发布收据 |
| Task 10 | `passed` | 模型候选注册和模型库生命周期聚焦验证已通过 | Task 14 仍需在最终干净 SHA 重新绑定完整发布收据 |
| Task 11 | `passed` | 模型导出包和离线推理合同、前端控制与浏览器聚焦验证已通过 | Docker/真实部署导出运行及 Task 14 收据仍待完成 |
| Task 12 | `passed` | 主平台任务中心、通用创建入口、预览/指派/回传组件、独立标注员门户及 Chromium 聚焦流程已验证 | 完整后端、Docker/WSL 持续运行、最终 SHA 收据和远程 CI 仍由 Task 14 负责 |
| Task 13 | `passed` | 异步 worker、幂等、lease recovery、清理报告校验和 Web 安全合同聚焦验证已通过 | Docker/WSL、真实跨服务运行态、完整 active suite 和 Task 14 发布证据 |
| Task 14 | `in_progress` | 当前 SHA 的完整后端门禁、Playwright、Docker/WSL、导出/离线、恢复、安全和远程 CI 已通过；receipt 哈希回归已补齐；19 项 receipt 的 CI 接入（纳入最终 manifest 与上传产物、AUTH-02 路径修正）已在当前工作树完成 | 收据接入尚未在最终干净 SHA 上经远程 CI 实际生成验证；矩阵语义更正项（CLU-02/AUTH-02/AUTO-02/REL-01 真实运行态证据）仍按原边界执行 |

### 历史整理核验（2026-09-09）

- 当前 HEAD 为 `e94862af844ea95a31203423c24a8ececd7553d6`，与 `origin/general-automl-annotation-20260902` ahead/behind 均为 `0`；工作树仍有未提交变更，`README.md` 为用户本地修改，继续排除在外。
- `tests/test_run_suite.py` 当前为 **7 passed**；运行器已按 AST 选择 pytest/unittest，并以 unittest 最终摘要判断零测试，嵌套历史摘要误判回归已通过。
- `tests/test_label_schema_api.py` 当前为 **4 passed、1 warning**；测试夹具已创建项目所属数据版本，服务端项目归属校验保持不变。
- `tests.test_celery_workflows` 当前为 **19/19 OK**；前端台账和完整 Vitest 的既有当前 SHA 复核为 **7/7**、**57 个文件/275 个测试通过、19 个历史 skipped**。
- `git diff --check` 通过；当前环境无 Docker，真实 broker、Compose、Playwright、导出/离线、恢复和远程 CI 尚无当前 SHA 的完整通过收据。

### 历史下一执行顺序（已完成）

1. 继续 Task 5 的真实 broker 派发、恢复调度、结果分页和页面操作中心接线。
2. 按依赖收口 Task 6–13 的跨服务、浏览器、导出/离线和恢复证据。
3. 在同一当前 SHA 执行 Task 14 的全量发布门禁；保留后端全量、Docker/WSL、Playwright、导出/离线、恢复和远程 CI 的缺口记录。

本快照只整理进度，不提升任务状态、不生成发布结论，也不执行提交或推送。

### 2026-09-09 当前工作树复核更正

- 当前 HEAD 为 `e94862af844ea95a31203423c24a8ececd7553d6`，分支相对 `origin/general-automl-annotation-20260902` 为 `0/0`；测试执行时工作树包含未提交实现和文档变更，因此下列结果属于当前工作树证据，而非 SHA 绑定的发布收据。
- Task 5 前端状态回写回归已修复：预览轮询同时更新列表行的 `preview`、`task_revision` 和状态。复核 `npm test -- --run src/pages/DataAnnotationPage.test.tsx` 为 **39/39 passed**，`npm test -- --run src/weekAcceptance.test.ts` 为 **7/7 passed**，`npm test -- --run` 为 **57 个文件通过、276 个测试通过、19 个历史 skipped**，`npm run build` 退出码为 0。
- 运行器复核：`tests.test_run_suite` 为 **7/7 OK**，`pytest tests/test_run_suite.py -q` 为 **7 passed**，`run_suite.py --week 17` 为 **21/21 模块通过、0 失败、退出码 0**；`git diff --check` 通过。此前的 38/39 和 275 项前端记录保留为历史检查点，不再代表当前工作树结果。
- 状态不提升：Task 1–4 仅在既有聚焦范围内为 `passed`，Task 5–14 继续为 `in_progress`。后端完整 active suite、Docker/真实 broker、Playwright、导出/离线、恢复演练和远程 CI 仍无可发布的当前版本完整收据。
- 下一入口：先收口 Task 5 的真实 broker 和恢复调度及端到端操作流程，再按依赖补齐 Task 6–13 的跨服务运行态证据，最后在干净提交上执行 Task 14 发布门禁。

## 11. 2026-09-09 聚合复核（最新）

- 本次复核基于当前工作树 HEAD `e94862af844ea95a31203423c24a8ececd7553d6`；分支与远端仍为 `0/0`，工作树仍有未提交变更，`README.md` 继续作为用户本地文件排除，不暂存、不覆盖。
- 已完成本轮前置修复：`run_suite.py` 使用 AST 识别 pytest/unittest；`has_zero_tests()` 对 unittest 只依据最后一个 `Ran N test(s)` 摘要，避免嵌套输出造成零测试误判；标签 schema API 测试夹具改为创建项目所属数据版本。
- 当前验证：`tests.test_run_suite` **7/7 OK**；`pytest tests/test_run_suite.py -q` **7 passed**；`pytest tests/test_label_schema_api.py -q` **4 passed、1 warning**；`tests.test_celery_workflows` **19/19 OK**；`run_suite.py --week 17` **21/21 模块通过、0 失败、退出码 0**；`git diff --check` 通过。
- 聚合结果只证明 Week 17 模块级运行器和已纳入模块的当前本地测试可执行，不替代完整后端门禁，也不产生浏览器、真实 broker、Docker/WSL、导出/离线、恢复或远程 CI 收据。
- 任务状态不提升：Task 1–4 仍为已记录本地聚焦范围内的 `passed`；Task 5–14 继续保持 `in_progress`。Task 5 的真实 broker 派发、恢复调度、结果分页和页面操作中心接线仍是下一实现入口。
- 下一顺序：先继续 Task 5 未完成实现，再按依赖收集 Task 6–13 的跨服务和运行态证据，最后在同一当前 SHA 执行 Task 14 全量发布门禁；任何失败、超时、skipped、缺失或未执行证据都不能标记完成。

## 12. 2026-09-09 进度整理（当前工作树）

- 当前基线：分支 `general-automl-annotation-20260902`，HEAD `e94862af844ea95a31203423c24a8ececd7553d6`，相对 `origin/general-automl-annotation-20260902` 为 `0/0`。工作树存在大量未提交变更；用户本地 `README.md` 明确排除，不暂存、不覆盖、不推送。
- 状态口径：Task 1–4 继续保持已记录本地聚焦范围内的 `passed`；Task 5–14 继续为 `in_progress`。本次整理不提升任务等级，也不生成发布完成结论。
- 既有有效证据：运行器框架识别与嵌套摘要修复后的 Week 17 聚合为 **21/21 模块通过**；标签 schema API 为 **4 passed、1 warning**；worker 导入回归为 **19/19 OK**；这些证据仅覆盖对应本地套件。
- 当前新增 RED：在 `ml-platform/frontend` 执行 `npm test -- --run src/pages/DataAnnotationPage.test.tsx`，结果为 **39 个测试中 38 passed、1 failed**。失败用例是 `executes a generic task from the list once its preview is ready`。
- 已定位原因：预览轮询只更新 `PreviewDrawer`，未把 `preview_id/status` 回写 `genericTasks`；列表任务的 `task.preview` 仍为空，故“执行”按钮保持 disabled。当前尚未修改生产实现。
- 影响与门禁：Task 5 的页面操作中心接线仍未闭环；前端完整套件此前的 **57 文件/275 测试通过、19 个历史 skipped** 属于新增 RED 之前的记录，不能作为当前工作树全量通过结论，需修复后重新运行。
- 下一执行顺序：先完成列表状态回写和服务端 revision 传递回归，再重跑页面聚焦、周台账和前端全量测试；随后继续 broker、恢复、结果分页和操作中心，最后按依赖补齐 Task 6–14 的运行态与发布门禁。

## 13. 2026-09-09 进度整理复核（最新）

- 当前基线仍为分支 `general-automl-annotation-20260902`、HEAD `e94862af844ea95a31203423c24a8ececd7553d6`，相对 `origin/general-automl-annotation-20260902` 为 `0/0`。工作树仍有未提交实现和文档变更；用户本地 `README.md` 保持排除，不暂存、不覆盖、不提交、不推送。
- Task 5 刷新路径已补齐服务端合同：任务列表仅暴露当前 `task_revision` 的预览，并提供执行所需的预览 ID、操作 ID、修订号、状态、进度和摘要；旧修订预览不会被作为当前可执行预览返回。验证命令 `pytest tests/test_annotation_task_state.py tests/test_annotation_task_state_api.py tests/test_genericization_contract.py -q` 为 **52 passed、3 warnings**，对应模块 `py_compile` 通过。
- 前端重新验证：`DataAnnotationPage.test.tsx` 为 **39/39 passed**，周台账为 **7/7 passed**，完整 Vitest 为 **57 个文件通过、276 个测试通过、19 个历史 skipped**，生产构建退出码为 0。运行器回归为 unittest **7/7 OK**、pytest **7 passed**；Week 17 聚合为 **21/21 模块通过、0 失败**。
- 状态不提升：Task 1–4 继续仅在已记录的本地聚焦范围内为 `passed`；Task 5–14 继续为 `in_progress`。上述命令均运行于脏工作树，不能生成 SHA 绑定的发布收据。
- 当前下一入口：Task 5 仍需验证真实 broker 派发与恢复调度，补齐预览统计/结果分页和完整任务操作中心的端到端流程；随后按依赖收集 Task 6–13 的跨服务、浏览器、导出/离线、恢复和安全运行态证据。Task 14 必须在干净提交上重新执行全量门禁、生成同一 SHA 收据，并完成 Docker/WSL、Playwright 和远程 CI 验证。

## 14. 2026-09-09 Task 5 只读审计与进度整理（最新）

- 本次审计基于工作树 HEAD `e94862af844ea95a31203423c24a8ececd7553d6`；分支相对远端为 `0/0`，工作树仍有未提交变更，用户本地 `README.md` 明确排除，不暂存、不覆盖、不提交、不推送。
- Task 5 已存在且有局部证据的范围：状态守卫与转移审计、服务端冻结任务快照、预览幂等与 DurableOperation/worker、任务/预览/样本 cursor 列表、刷新后只返回当前 revision 预览、前端轮询回写列表状态。
- 当前局部验证：Task 5 状态/API/通用化回归 **52 passed、3 warnings**；DataAnnotationPage **39/39**；前端台账 **7/7**；完整 Vitest **57 个文件通过、276 个测试通过、19 个历史 skipped**；生产构建退出码 0；Week 17 聚合 **21/21 模块通过**；worker 导入回归 **19/19 OK**；`git diff --check` 通过。上述均为脏工作树验证，不是发布收据。
- Task 5 审计缺口：
  - **P0**：`execute` 目前只改变状态，没有创建执行 DurableOperation、派发执行 worker、持久化执行结果或提供执行恢复；本地非 Celery 模式的预览派发仍可能只返回空任务引用并停留在 queued；恢复任务只覆盖 preview，尚无真实 broker/重启回执。
  - **P1**：没有样本统计、cluster 统计、rule hits、final labels 的持久化和 cursor API；页面仍是分离的通用任务表与历史表，操作列只有 Preview/Assign/Execute，缺少完整 publish、pause/resume、cancel、return、accept、complete、archive 等状态矩阵和分页操作中心；配置变更尚无新 revision/旧预览失效接口。
- 全量后端当前不能记为通过：后端 `.venv` 未安装 `catboost`，但 `ml-platform/backend/requirements.txt` 声明 `catboost==1.2.*`；完整收集在 `tests/test_onnx_conversion.py` 处出现 `ModuleNotFoundError`。这是当前环境/依赖门禁，需在同一 `.venv` 补齐并复跑，不能改写为通过或归因于 Task 5 代码。
- 状态不变：Task 1–4 仅在既有本地聚焦范围内为 `passed`；Task 5–14 继续为 `in_progress`。下一顺序为：先修复后端依赖并重跑完整门禁；随后补 Task 5 执行 DurableOperation、local/Celery dispatch 与 recovery；再补结果/统计分页和统一操作中心；最后收集 Task 6–13 的跨服务、浏览器、导出/离线、恢复和安全证据，并在干净提交上执行 Task 14。

## 15. 2026-09-10 进度整理（Task 5 执行链路进行中）

- 本次整理基于分支 `general-automl-annotation-20260902`、HEAD `e94862af844ea95a31203423c24a8ececd7553d6`；相对 `origin/general-automl-annotation-20260902` 为 `0/0`。工作树仍有大量未提交变更，用户本地 `README.md` 继续排除，不暂存、不覆盖、不提交、不推送。
- Task 1–4 仍只在各自已记录的本地聚焦范围内为 `passed`；Task 5–14 保持 `in_progress`。本次只同步进度，不提升任务状态，也不生成发布收据。
- Task 5 当前新增实现处于验证前检查点：工作树出现执行结果模型/迁移、幂等执行请求服务及相关执行 worker/派发测试改动。代理仍在完成实现与回归，当前不能把这些文件视为完成或通过。
- 既有局部证据保持有效：Task 5 状态/API/通用化回归 **52 passed、3 warnings**；DataAnnotationPage **39/39**；前端台账 **7/7**；完整 Vitest **57 个文件/276 个测试通过/19 个历史 skipped**；生产构建通过；Week 17 聚合 **21/21 模块通过**；worker 导入回归 **19/19 OK**；`git diff --check` 通过。以上均来自脏工作树，不是 SHA 绑定发布证据。
- 当前环境门禁已重新核对：项目 `.venv` 中 `catboost 1.2.10` 可导入；`onnx`、`onnxmltools`、`skl2onnx` 仍未安装。因此此前“CatBoost 缺失”结论已更正为“CatBoost 已存在，ONNX 转换依赖仍缺失”。后端完整套件必须在依赖补齐后重新收集，不能把环境失败归因于实现。
- Task 5 未完成缺口仍包括：执行 worker 的完整 GREEN 回归和失败封闭、local/Celery 双模式可执行派发、真实 broker 与重启恢复、结果及 sample/cluster/rule/final-label 统计 cursor API、完整任务操作中心及配置 revision/旧预览失效。Task 6–14 的跨服务、浏览器、导出/离线、Docker/WSL、恢复和远程 CI 证据仍未齐备。
- 下一入口：先审阅并验证 Task 5 执行链路代理的实现和聚焦测试；随后在同一工作树复跑迁移、执行/异步契约、状态/API 回归与编译检查，再继续结果分页和操作中心。只有在形成干净提交后，才重新生成 Task 14 的当前 SHA 收据。

## 16. 2026-09-10 文档整理与发布前检查点

- 当前分支为 `general-automl-annotation-20260902`，HEAD 仍为 `e94862af844ea95a31203423c24a8ececd7553d6`，相对 `origin/general-automl-annotation-20260902` 为 `0/0`。工作树包含未提交实现、迁移、测试和文档变更；用户本地 `README.md` 明确排除，不暂存、不覆盖、不提交。
- Task 1–4 继续保持各自已记录本地聚焦范围内的 `passed`；Task 5–14 保持 `in_progress`。Task 5 执行结果模型/迁移、幂等执行请求、执行 worker、失败封闭、结果分页和恢复去重属于当前分支实现，但不生成独立 `passed` 验收收据。
- Task 5 当前工作树证据：执行链路代理报告 **59 passed、4 warnings**，后续审查复核报告 **61 passed、4 warnings**；前端 `DataAnnotationPage.test.tsx` 当前复核为 **41 passed**，周台账为 **7 passed**。这些结果运行于脏工作树，不能替代干净 SHA 收据。
- 本轮后端测试重新执行未启动：`ml-platform/backend/.venv/Scripts/python.exe` 的 `pyvenv.cfg` 指向已不存在的 `C:\Users\17723\AppData\Local\Programs\Python\Python314\python.exe`，属于环境阻断，不能写成后端通过或代码失败。前端页面和周台账测试仍可运行并通过。
- Task 5 尚未闭环的门禁包括真实 broker/Celery 派发、进程退出后的重启恢复、跨进程原子 recovery claim、非 sample 统计数据库分页、完整状态操作矩阵、配置 revision/旧预览失效 API、操作中心结果/统计消费和 cursor 加载，以及 Docker/Playwright/导出离线/远程 CI 证据。
- 本次只整理状态并发布当前分支，不提升任务等级。推送不代表 Task 5 或 Task 14 完成；修复 Python 环境并形成干净 SHA 后，仍需重跑 required gates。

## 17. 2026-09-10 登录失败修复检查点

- 问题现象：管理员使用默认凭据登录时，前端统一显示“用户名或密码错误”；在多次尝试后，服务端实际可能返回 429，损坏或历史格式密码哈希也可能被错误归类为认证失败。
- 根因：登录查询未处理复制粘贴空格和大小写差异；密码校验对未知哈希格式缺少 fail-closed 处理；前端未区分 401、429 和其他服务错误。测试还共享进程级限流状态，测试顺序可能制造非业务 429。
- 解决方法：后端登录名按大小写不敏感标识查询并去除首尾空格；未知/损坏哈希统一返回 401，成功登录时按当前策略自动升级哈希；前端对限流返回明确提示，对服务异常保留结构化错误；认证测试在每个用例前清理进程级限流器。
- 验证方式：`ml-platform/backend` 执行 `python -m pytest tests/test_api_users.py -q`，结果 **15 passed、2 warnings**；`ml-platform/frontend` 执行 `npm test -- --run src/pages/LoginPage.test.tsx src/api/auth.test.ts`，结果 **2 files、4 tests passed**；当前运行服务直接提交 `admin/admin123` 返回 HTTP 200；`git diff --check` 通过。
- 状态边界：本次只修复认证输入、哈希兼容和错误提示，不改变默认密码、不在启动时覆盖已有用户密码；Task 1–4 及 Task 5–14 状态保持原计划口径，未生成平台级验收结论。
- 剩余风险：真实部署数据库若已有自定义管理员密码，仍应使用该密码或通过受控管理员重置流程恢复；标注员门户账号与主平台账号保持独立，不能用主平台管理员凭据登录门户。

## 18. 2026-09-10 CORS 登录来源修复检查点

- 问题现象：登录请求返回 `CORS_ORIGIN_FORBIDDEN: request origin is not allowed`。
- 根因：后端默认只允许 `http://localhost:5173`；浏览器实际使用 `http://127.0.0.1:5173`，或 Vite 在默认端口被占用时切换到 `http://localhost:5174`，均未被安全策略和 CORS 中间件接受。
- 解决方法：本地模式新增受控 loopback 来源扩展，允许 `localhost`、`127.0.0.1` 和 IPv6 loopback 的 5173/5174 别名；增加 `FRONTEND_ORIGIN_ALIASES` 配置入口供自定义本地来源；生产模式不自动扩展来源，未知来源仍 fail closed。
- 验证方式：本地运行态对 `localhost/127.0.0.1` 的 5173、5174 登录均返回 HTTP 200；未知来源返回 HTTP 403；`tests/test_security_contract.py` 与 `tests/test_app.py` 共 **15 passed、1 warning**；相关 Python 编译和 `git diff --check` 待最终检查。
- 状态边界：本次仅修复本地来源匹配和配置边界，不使用通配符，不改变 Task 1–4 或 Task 5–14 状态，也不生成平台级验收结论。

## 19. 2026-09-11 CSRF 登录误报修复检查点

- 问题现象：主平台 Bearer Token 登录请求在浏览器携带标注员门户 `portal_session` 以外的无关 Cookie 时，被安全中间件返回 `CSRF_TOKEN_REQUIRED`。
- 根因：CSRF 策略将任意 Cookie 都当作会话 Cookie；主平台登录不建立 Cookie 会话，且 Bearer Token 请求不需要 CSRF 校验。
- 解决方法：`SecurityPolicy` 显式维护受保护会话 Cookie 名称，默认仅识别 `portal_session`；无关 Cookie 不触发 CSRF，门户会话仍要求可信来源和匹配的双提交令牌。
- 验证方式：`ml-platform/backend` 执行 `tests/test_security_contract.py tests/test_api_users.py`，结果 **22 passed、8 warnings**；`git diff --check` 通过。
- 状态边界：本次只修复 CSRF 会话识别范围，不改变 Bearer Token、门户 Cookie、Task 1–4 或 Task 5–14 状态；后端警告来自现有依赖和测试密钥配置，未作为本次修复范围处理。

## 20. 2026-09-11 前端 5175 来源修复检查点

- 问题现象：前端实际由 Vite 运行在 `http://127.0.0.1:5175`，登录请求返回 `CORS_ORIGIN_FORBIDDEN: request origin is not allowed`。
- 根因：本地来源扩展仅覆盖默认端口 `5173` 及一次回退端口 `5174`，未覆盖当前 Vite 进程因端口占用选择的 `5175`。
- 解决方法：本地模式在保持 loopback 主机白名单的前提下增加 `5175`，生产模式仍使用精确来源集合。
- 验证方式：`tests/test_security_contract.py tests/test_app.py` 结果 **16 passed、1 warning**；运行态请求使用 `Origin: http://127.0.0.1:5175` 登录返回 HTTP `200`，并返回匹配的 `Access-Control-Allow-Origin`；`git diff --check` 通过。
- 状态边界：本次只扩展本地受控来源，不使用通配符，不改变认证、CSRF、Task 1–4 或 Task 5–14 状态。

## 20. 2026-09-11 Task 5 本地预览派发修复

- 按 TDD 新增 local runtime 回归，先复现默认 `task_backend=local` 下预览派发返回空引用、预览停留 `queued` 的缺口。
- 修复 `annotation_preview_tasks.enqueue_annotation_preview`：local 模式通过 daemon thread 复用 `execute_annotation_preview.run`，Celery 模式保持 `.delay()`，并返回稳定的本地派发引用。
- 独立 SQLite 会话回归确认 durable operation 完成、预览进度为 100、任务进入 `preview_ready`；随后 Task 5/6/7/8/13 聚焦套件为 **88 passed、10 warnings**。
- 用户本地 `README.md` 未纳入本轮改动。Task 5–14 继续为 `in_progress`；真实 broker、进程重启恢复、完整操作中心、Docker/WSL、Playwright、导出/离线及远程 CI 仍需后续收据。

## 21. 2026-09-11 当前 SHA 发布复核

- 提交 `cd7cf07146cea6760c6af3b24a6800a917fef0dc` 已 fast-forward 推送到 `origin/general-automl-annotation-20260902`，远端 `ls-remote` 已核对为同一 SHA。
- 当前 SHA 验证：Task 5/6/7/8/13 后端聚焦 **88 passed、10 warnings**；安全/用户认证 **22 passed、8 warnings**；前端全量 **57 files passed、279 passed、19 skipped**；生产构建、Python `compileall`、`git diff --check` 通过；Alembic upgrade 后 `alembic check` 返回无新升级操作。
- 工作树只保留用户本地 `README.md` 未暂存修改；代码和开发计划已提交，README 未进入提交。
- 发布边界仍保持 fail-closed：未具备 Docker/WSL、真实 Redis/Celery broker、进程重启恢复、Playwright、导出/离线真实运行、完整后端 active suite 和远程 CI 的当前 SHA 通过收据，因此 Task 5–14 继续为 `in_progress`，不能宣称平台整体验收完成。
- 同一工作树执行 `run_suite.py --week 17`，结果 **21 passed、0 failed**；该聚合覆盖已登记模块，不替代完整后端 active suite、真实 broker、Docker/WSL 或远程 CI 门禁。

## 22. 2026-09-11 AutoML 搜索强度控制实验预算

- 新建 AutoML 任务页面移除“最大试验次数”输入和状态，提交请求不再携带 `max_trials`；“搜索强度”仍显示各档默认预算（轻度 10、标准 30、高度 80、Ultra 200）。
- 后端新搜索合同在省略 `max_trials` 时按标准化 `search_strength` 派生 `max_trials`，并以派生值写入任务合同；旧客户端显式传入该字段仍兼容，但新建页面不再允许用户直接控制。
- TDD RED/GREEN 验证：前端 `AutoMLPage` **10 passed、19 skipped**；后端 `test_automl_tracking.py` **64 passed、50 warnings、10 subtests**。完整后端此前在环境补齐后暴露历史失败，未将其改写为全量通过。

## 23. 2026-09-11 通用任务操作矩阵补齐

- 在任务列表补齐通用状态动作：`awaiting_return -> return`、`returned_pending_acceptance -> accept`、`accepted -> complete/archive`、`completed -> archive/reopen`、`cancelled -> archive`、`archived -> restore`；所有动作继续复用服务端 revision transition API。
- 新增 `returned_pending_acceptance` 验收动作回归，先 RED 后 GREEN；标注页面测试 **42 passed**，生产构建、Python 编译和 `git diff --check` 通过。
- Task 5 仍不提升为平台验收完成：真实 broker、重启恢复、Docker/WSL、Playwright、完整后端 active suite 和远程 CI 仍缺当前 SHA 收据。

## 24. 2026-09-11 当前 SHA 前端全量复核

- 在发布 SHA `3ecea9a61a4ae344322189feee001019c2f072e2` 上重跑前端全量套件：**57 个测试文件通过、280 passed、19 skipped**。
- 该结果覆盖通用任务动作矩阵和 AutoML 搜索强度表单后的前端回归；生产构建及此前后端聚焦证据仍有效。
- README 仍为唯一用户本地未暂存修改；后端完整 active suite、Docker/真实 broker、恢复、Playwright、导出/离线和远程 CI 仍未形成完整当前 SHA 收据。

## 25. 2026-09-11 AutoML 浏览器验收

- 在当前发布分支执行 `npm run test:e2e -- e2e/automl-multioutput.spec.ts`，Chromium **1 passed**；浏览器实际提交多输出 AutoML 合同并验证搜索强度请求字段。
- 该结果补齐 AUTO-02 的本地当前环境浏览器证据，但不替代真实远程验收栈、完整后端 active suite、Docker/WSL、broker/recovery 和远程 CI。

- 同一当前工作树执行模型导出、导出 API 和离线推理聚焦套件，结果 **9 passed、2 warnings**；该结果验证合同和本地运行路径，但尚未生成统一 receipts 目录中的 SHA 绑定收据。

## 26. 2026-09-11 通用平台 19 项合同收据

- 为验收矩阵 19 个 ID 写入实际聚焦测试、前端 E2E 和导出/离线命令的 receipts；文档提交完成后按最终发布 SHA 重新绑定。
- 最近一次 `validate_acceptance_manifest` 校验结果：**19 receipts valid**，全部绑定当时发布 SHA 且状态为 `passed`；收据目录为本地 `temp_test/generic-platform-acceptance/receipts/`。后续提交会使旧绑定失效，必须重新生成。
- 该结果只证明验收矩阵所列 19 个合同的本地收据完整，不替代完整后端 active suite、Docker/WSL、真实 broker/重启恢复、远程 CI 和真实部署导出运行。平台 Task 5–14 仍保持 `in_progress`，未生成整体完成结论。

## 27. 2026-09-11 Python/ONNX 验证环境修复

- 原项目 `.venv` 的 `pyvenv.cfg` 指向已不存在的 Python 3.14 安装；重建后按项目依赖恢复验证环境。
- 当前 Python 3.14 索引没有 `onnxruntime==1.22.*` 可用发行包，已将 `ml-platform/backend/requirements.txt` 的约束更新为 `onnxruntime==1.24.*`，实际安装并验证 `onnxruntime 1.24.1`、`onnx 1.22.0`、`skl2onnx 1.19.1`、`onnxmltools 1.16.0` 可导入。
- `pyarrow==20.*` 在当前 Python 3.14 环境未提供可用 wheel，源码构建因缺少 CMake 失败；这仍是完整依赖/完整后端门禁风险，不能记为全量通过。若需完整复现，应使用项目支持的 Python 3.11 环境或提供匹配的 PyArrow wheel。
- 在补齐当前聚焦依赖后，Task 5–8 后端聚焦回归为 **67 passed、46 warnings**；该结果只验证代码聚焦范围，不提升 Task 5–14 状态，也不覆盖完整后端、Docker/真实 broker、恢复或远程 CI。

### 2026-09-11 Python 3.11 复核更正

- 已安装 Python 3.11.9，并在 `ml-platform/backend/.venv311` 中按当前 requirements 完成安装；该环境可用 `pyarrow 20.0.0` 和 `onnxruntime 1.24.4`，`pip check` 无冲突。
- 3.11 聚焦验证：Task 5–8 **67 passed、10 warnings**；ONNX 转换 **10 passed、1 skipped**（跳过项仅为 Windows 不适用的 POSIX 资源限制测试）；模型导出、推理运行时和离线合同 **18 passed、3 warnings、2 subtests**。
- 3.14 环境的真实阻断是 `pyarrow==20.*` 没有可用 wheel、源码构建缺 CMake；这不等同于项目 3.14 虚拟环境本身失效。完整后端门禁尚未执行，Task 5–14 继续保持 `in_progress`。

### 2026-09-11 安全/门户组合复核

- 在同一 Python 3.11.9 环境执行 `tests/test_security_contract.py`、`tests/test_annotator_auth.py` 和 `tests/test_portal_internal_api.py`，结果为 **72 passed、2 warnings、2 subtests passed**。
- 实际导入版本再次核对为 `pyarrow 20.0.0`、`onnx 1.22.0`、`onnxruntime 1.24.4`、`skl2onnx 1.19.1`、`onnxmltools 1.16.0`；`pip check` 返回 `No broken requirements found.`。
- 该组合结果仍属于聚焦测试证据；完整后端 active suite、真实 Redis/Celery、重启恢复、Docker/WSL、Playwright、真实导出/离线运行和远程 CI 尚未全部形成当前 SHA 的通过收据，Task 5–14 继续保持 `in_progress`。

### 2026-09-11 Task 5 revision 快照读取修复

- 复核完整 Task 5 状态链路时发现：配置更新已持久化 `AnnotationTaskRevisionSnapshot`，但预览 worker 仍直接读取不可变任务初始 `task_snapshot`，导致新 revision 的预览可能使用旧的可见列、指令和策略配置。
- 按 TDD 新增回归：将任务推进到 revision 1 并写入新快照，worker 必须读取 revision 1 的 `visible_columns`；修复 `annotation_preview_tasks` 通过共享 `current_annotation_task_snapshot()` 读取当前 revision 快照。
- 验证：新增 RED 先观察到 worker 返回旧列 `feature`，GREEN 后 Task 5 状态/API/异步恢复及新增回归 **64 passed、4 warnings**；完整后端此前运行因历史失败和长时间安全扫描被主动中断，不记为通过。
- 任务状态边界不变：Task 5–14 继续 `in_progress`；真实 Redis/Celery、进程重启恢复、Docker/WSL、完整后端 active suite、Playwright、导出/离线真实运行和远程 CI 仍需独立当前 SHA 证据。

### 2026-09-11 深度学习算子可选依赖注册修复

- 当前 Python 3.11 验证环境未安装可选 `torch`；原 `dl_operators` 在导入失败时完全跳过注册，导致完整算子元数据测试看不到 `dl` 类别和三个标准算子。
- 保持运行时依赖边界：无 `torch` 时仍注册 `mlp_classifier`、`mlp_regressor`、`cnn1d_classifier` 的输入/输出/参数元数据，但执行路径 fail closed 返回 `TORCH_NOT_INSTALLED`，不生成伪造模型。
- 验证：算子注册、深度学习元数据和扩展算子聚焦回归 **9 passed**。完整后端首批剩余的登录错误属于历史测试共享进程级限流状态，生产限流语义未修改。

### 2026-09-11 当前 SHA 门禁复核

- 当前发布 SHA `7e6858591d0b3b339a8cf94cef69eebf874f3555` 已推送到 `origin/general-automl-annotation-20260902`，远端 SHA 一致；`README.md` 仍未暂存。
- 前端全量 Vitest：**57 个文件通过、280 passed、19 skipped**；前端生产构建、后端 `compileall` 和 `git diff --check` 通过。
- 后端完整 active suite 使用 Python 3.11 执行 `pytest -q --maxfail=20`，在 **187 passed、9 failed、11 errors** 后停止。失败集中于历史 API 测试重复登录触发共享进程级限流，以及首次暴露的可选 Torch 算子注册缺口；Torch 元数据缺口已修复并有 **10 passed** 当前 SHA 回归，认证测试隔离问题尚未修改生产限流语义。
- 因完整后端 active suite、真实 broker/重启恢复、Docker/WSL、Playwright、真实导出/离线运行和远程 CI 仍未全部通过，Task 5–14 继续保持 `in_progress`。

### 2026-09-11 历史 API 测试限流隔离修复

- 复现确认完整后端首批登录错误并非生产认证失败：历史测试共享进程级 `SlidingWindowRateLimiter`，`test_agents.py` 在同一模块内连续登录超过 5 次；模块级管理员初始化只清理一次状态。
- 测试隔离修复限定在 `tests/auth_test_support.py`、`test_api_compute.py` 和 `test_agents.py`：管理员初始化或测试 token 获取前清理 limiter；生产登录限额和 fail-closed 行为未修改。
- 验证：`tests/test_agents.py tests/test_api_chat.py tests/test_api_compute.py tests/test_api_users.py` 为 **46 passed、47 warnings**。该结果仅修复历史测试隔离，不替代完整后端 active suite 或平台级发布门禁。

### 2026-09-11 Alembic 历史边界与旧点焊接口复核

- 迁移聚焦失败的根因分为两类：AutoML 回填测试在旧 revision 上错误使用当前 ORM，导致插入不存在的 `automl_contract` 字段；实验跟踪和模型注册降级测试从最新通用平台 head 回退，错误穿越了后续不可逆通用迁移。
- 修复方式：回填测试改为使用历史表定义的 Core insert；`20260904_18`、`20260905_19`、`20260905_17` 和 `20260904_16` 增加可验证的结构降级；旧迁移降级测试改为在各自历史 revision 边界执行，不改变新通用任务的生产数据保留原则。
- 验证：`tests/test_database_production.py -k "automl_binding_revision_backfills_the_earliest_historical_job or experiment_tracking_revision_has_complete_downgrade or model_registry_revision_has_complete_downgrade"` 为 **3 passed、2 warnings**。
- 点焊历史测试统一注入每请求 `X-Request-ID` 和 `Idempotency-Key` 后，剩余失败均为生产路由明确返回的 **410 `GENERIC_API_REQUIRED`**，表明测试仍调用已退役 `/api/projects/{id}/spot-weld/runs`，不是新通用 API 的安全合同失败；不放宽生产路由，后续应迁移这些历史测试到 `/api/annotation-tasks` 或明确标记退役兼容测试。
- Task 5–14 仍保持 `in_progress`；完整后端 active suite、真实 broker/恢复、Docker/WSL、浏览器全平台和远程 CI 仍未闭环。

### 2026-09-11 Task 1 行业边界纠正

- 更正前一条记录的处置方向：通用平台不承担点焊业务，Task 1 的目标是去除行业专用实现依赖，不应把旧点焊 API 测试迁移成通用平台功能，也不应恢复 `/spot-weld` 写入口。
- 将 Week 17 中的 `test_spot_weld_quality_models`、`test_spot_weld_features`、`test_spot_weld_quality_service`、`test_api_spot_weld_quality`、`test_spot_weld_quality_tasks` 统一标记为历史 deprecated 模块；新增 pytest collection 规则，默认 active suite 跳过它们，只有显式 `INCLUDE_DEPRECATED_TESTS=1` 才运行。
- 验证：`test_suite_manifest.py` 与 `test_genericization_contract.py` **23 passed、2 subtests**；全后端 pytest 收集 **1830 tests collected**；生产旧点焊写入口仍由通用合同返回 `410 GENERIC_API_REQUIRED`。
- Task 1 的完整生产源码/前端导航去行业化扫描仍需继续；Task 5–14 仍保持 `in_progress`，历史点焊模块不计入通用平台 active acceptance。

### 2026-09-11 通用 active suite 与迁移夹具复核

- 完整 active acceptance suite 使用 `run_suite.py`（默认排除历史点焊模块）运行到数据库生产模块，已确认知识库测试的共享登录限流状态会制造 `access_token` 缺失；清理测试限流器后 `test_knowledge.py` 为 **10 passed**。
- 数据库生产迁移夹具曾在旧 `20260718_08` schema 上使用当前 `ModelVersion` ORM，实际插入不存在的 `lifecycle_state`；已改为旧列集合的 Core insert。生产推理回填和历史边界降级聚焦测试通过。
- 数据库基线测试的固定 head 常量已更新为当前 Alembic head `20260910_43`；旧的 57 表精确数量改为最低基线断言，允许后续通用平台迁移增加表而不产生伪失败。
- 当前 active suite 仍有后续模块待执行；本轮不将局部修复扩大为后端全量通过，也不重新纳入点焊历史模块。

### 2026-09-11 Task 5 全项目任务列表分页修复

- 根因：`GET /api/annotation-tasks` 在未提供 `project_id` 时绕过共享状态服务，直接截取前 `limit` 条任务并把本页数量作为 `total`；因此跨项目列表无法 cursor 翻页，且列表合同与按项目查询不一致。
- 解决：所有任务列表请求统一进入 `list_annotation_tasks`；服务按当前用户过滤，可选项目过滤，使用稳定排序后的任务集合执行 cursor 分页，并拒绝不属于当前用户/项目范围的 cursor。
- TDD 验证：新增跨项目列表回归先以 `total == 1` 暴露旧实现缺口，修复后 `tests/test_annotation_task_state.py -k all_project_task_api` 为 **1 passed**；Task 5 状态/API/异步组合为 **65 passed、4 warnings**。
- 状态边界：这是 Task 5 的列表合同修复，不代表 Task 5 验收完成。真实 Redis/Celery、进程重启恢复、完整浏览器链路、Docker/WSL、完整后端 active suite 和远程 CI 仍未齐备；Task 5–14 继续 `in_progress`。

### 2026-09-11 Task 5 操作中心 cursor 稳定性修复

- 根因：操作中心 cursor 依赖 `created_at` 与 UUID 的数据库比较；SQLite 同一秒创建多个操作时，下一页可能重复上一页操作。
- 解决：操作中心统一使用 owner/project 过滤后的稳定排序结果和 marker 位置分页，保留非法及越权 cursor 的 fail-closed 行为。
- 验证：新增两项跨页操作中心回归和任务列表回归，目标测试 **2 passed**；Task 5 状态/API/异步组合 **65 passed、4 warnings**；Task 5 仍为 `in_progress`，真实 broker、重启恢复、Docker/WSL、完整 active suite 和远程 CI 仍待完成。

### 2026-09-11 Task 5/6 前端回归复核

- 当前发布分支 `559fd7e` 上执行 `npm test -- --run src/pages/DataAnnotationPage.test.tsx src/weekAcceptance.test.ts`，结果为 **2 个测试文件、49 passed**。
- 该结果覆盖通用任务列表、预览状态回写、操作中心 cursor 加载和自动标注页面入口；策略底层已由通用预览 worker 接线并由后端策略回归覆盖。
- 状态边界：前端聚焦通过不等于 Task 5 或 Task 6 完成；真实 broker/恢复、完整策略 API/浏览器链路、Docker/WSL、完整后端 active suite 和远程 CI 仍未齐备，Task 5–14 保持 `in_progress`。

### 2026-09-11 Task 8/9 当前分支 API 复核

- 在当前分支 `4def21a` 的 Python 3.11.9 环境执行 `tests/test_annotation_concurrency.py tests/test_annotation_return_acceptance.py tests/test_annotator_auth.py tests/test_portal_internal_api.py`，结果为 **22 passed、2 warnings**。
- 该结果覆盖指派范围、样本级并发冲突、回传幂等与锁、回传验收生成新数据版本、独立标注员认证和门户内部 API。
- 当前环境未安装 Docker，且没有可用 Redis 服务；真实 Celery broker、Compose/WSL、进程重启恢复和浏览器门户验收仍未执行。Task 8/9 继续 `in_progress`，不将本地聚焦结果升级为完整验收。

## 2026-09-11 WSL Docker 运行态复核

- 已确认 WSL Ubuntu 中 Docker Engine `29.7.2` 和 Compose `v5.5.0` 可用；Compose 基础配置在补齐一次性验收变量和证书路径后通过 `docker compose config --quiet`。
- 首次镜像构建因宿主机新增 `.venv311` 未被后端 `.dockerignore` 排除，构建上下文达到约 1.5 GB；按 TDD 新增构建合同回归并将 `.venv/` 改为 `.venv*/`，`tests/test_ci_workflow.py` 为 **47 passed、79 subtests passed**。
- 修复后镜像成功构建并启动迁移、PostgreSQL、Redis、MinIO、MLflow、推理运行时和 Celery worker；迁移成功退出，worker 日志确认连接真实 Redis broker 并报告 `ready`，任务列表包含通用预览和执行任务。
- 运行态仍未通过：首次临时密钥不是合法 Fernet key，修正为 URL-safe 32 字节 key 后容器重建；随后基础容器约一分钟后整体退出，backend 报 `failed to resolve host 'postgres'`，notification receiver/proxy 以 255 退出，worker 正常退出。该结果保留为运行态失败，不提升 Task 5–14 状态。
- 当前下一步：在 WSL Docker daemon 稳定后重新启动同一 Compose 项目，确认网络和依赖容器持续运行，再进行真实预览/执行派发、worker 停止重启和 recovery claim 验证。`.dockerignore` 修复需随当前分支发布；README 仍按用户要求在每次推送前检查并同步。

## 2026-09-11 核心 Compose 重试与聚焦回归复核

- 复用已成功构建的当前镜像后，核心 Compose 栈的 PostgreSQL、Redis、MinIO、TensorBoard 和迁移曾成功启动；MLflow 因启动命令运行时下载 `psycopg[binary]` 遇到 PyPI 超时而持续处于 `health: starting`，未形成完整依赖栈。
- 使用 `--no-deps` 启动 backend、worker 和 inference 后，worker 仍无法解析 `redis`，backend 无法解析 `postgres`；进一步检查确认两个基础容器已退出并从 Compose 网络移除，服务名 DNS 失败是容器生命周期问题。该运行态证据保持失败，不修改应用代码绕过依赖。
- 当前 Python 3.11.9 环境重新执行 Task 5/6/8/9/13 聚焦组合：`test_annotation_task_state.py test_annotation_task_state_api.py test_async_operation_contract.py test_annotation_strategies.py test_annotation_concurrency.py test_annotation_return_acceptance.py` 为 **85 passed、10 warnings**。
- 状态边界：聚焦回归通过不等于真实 broker、重启恢复或 Task 5–14 整体验收通过；所有任务继续保持 `in_progress`。下一步仍是获得稳定的 WSL Compose 基础服务持续运行证据，再执行真实预览/执行和 recovery claim。

## 2026-09-11 当前 SHA 非容器门禁复核

- 前端全量 Vitest：**57 个测试文件通过、280 passed、19 skipped**。
- 模型导出、离线推理和 ONNX 转换聚焦套件：**15 passed、1 skipped、4 subtests passed**。
- 后端 active suite 使用 Python 3.11 启动并运行到约 44% 后持续进行计算；因预计耗时较长且未产生失败摘要，本轮主动中止，不将其记为通过或失败。可复现命令为 `& (Resolve-Path .venv311\Scripts\python.exe).Path -m pytest -q --maxfail=10`。
- 状态边界：上述前端和导出证据属于当前工作树对应代码，但后端全量、Docker/WSL 持续运行、真实 broker/recovery、Playwright 和远程 CI 仍未形成完整发布收据；Task 5–14 继续 `in_progress`。

## 2026-09-11 当前 SHA 验收矩阵聚焦复核

- 数据导入、数据库迁移和标签 schema 聚焦组合：**49 passed、2 warnings**。
- AutoML 多输出与跟踪组合：**84 passed、51 warnings、10 subtests passed**。
- 安全合同与异步操作组合：**24 passed**。
- 标注员认证和门户内部 API：**12 passed、2 warnings**。
- 当前 `temp_test/generic-platform-acceptance/receipts/` 中仍有 19 份旧收据，绑定 SHA `1b35a30852f08d3837642f2ad57c84236671850d`，不能作为当前 SHA `64326dc55d61918fa7ef876879d7526f3d324e3f` 的发布证据；本轮只记录聚焦结果，不伪造或复用旧收据。
- Task 5–14 状态继续为 `in_progress`。完整后端 active suite、真实 Compose/broker/recovery、Playwright、当前 SHA 收据重生成和远程 CI 仍待完成。

## 2026-09-11 当前 SHA 前端构建与浏览器复核

- 前端生产构建通过：`npm run build`，TypeScript 检查和 Vite production bundle 均成功。
- 当前已有浏览器用例 `e2e/automl-multioutput.spec.ts` 在 Chromium 通过 **1 passed**，验证浏览器提交多输出 AutoML 合同及搜索强度字段。
- 已新增验收矩阵要求的 `e2e/generic-platform-acceptance.spec.ts`，以现有真实登录流程和通用 API route mock 验证任务列表、预览完成后的执行解锁、`execute -> return -> accept` 状态动作，以及页面不出现点焊业务入口；Chromium 命令结果为 **1 passed**。
- 状态边界：该用例补齐通用浏览器局部证据，但 Task 12/14 仍缺当前 SHA 收据重生成、真实 Compose/broker/recovery、完整后端 active suite 和远程 CI；Task 5–14 继续 `in_progress`。

## 2026-09-11 当前 SHA 收据增量与 active suite 长运行

- 当前提交 `25e3462182732150981fc218b22eb1454de994f5` 已重新执行并写入 12 项真实收据：DAT-01/02/03、LAB-01/02、CLU-01/02、CON-01/02、RET-01、AUTH-01、AUTO-02。对应聚焦结果为数据导入/迁移 **38 passed**、标签/并发 **17 passed**、策略/任务状态/回传 **62 passed**、标注员认证 **5 passed**，通用平台 Chromium **1 passed**。
- 后端 Python 3.11 全量 `pytest -q --maxfail=20` 从 0% 运行至约 44% 后进入长时间计算阶段，进程保持高 CPU 且没有新的失败摘要；等待超过 8 分钟后人工中断，退出码 1 仅表示中断，不能作为通过或代码失败证据。
- 当前收据目录仍有 LAB-03、AUTH-02、API-01、AUTO-01、EXP-01、INF-01、REL-01 绑定旧 SHA；验收 manifest 因此继续 fail closed。WSL 中两套历史验收 Compose 的 PostgreSQL/Redis/MinIO 等基础容器仍已退出，真实 broker/recovery 运行态尚未通过。
- Task 5–14 继续 `in_progress`；下一步优先补齐未绑定收据的精确命令和真实运行态证据，再重新执行 manifest、远程 CI 和发布门禁。

## 2026-09-11 验收合同复核与 Task 12 真实缺口

- 当前提交上继续执行了未绑定合同：`API-01` **9 passed**、`AUTO-01` **20 passed**、`EXP-01` **3 passed**、`INF-01` **2 passed**、`REL-01` **24 passed**、`LAB-03` **3 passed**、`AUTH-02` **3 passed**。门户测试实际复用 `ml-platform/backend/.venv311`，门户目录没有独立 `.venv`；此前路径错误仅为环境命令错误，不是产品测试失败。
- 代码审计确认 Task 12 仍有实现缺口：主平台“新建手动标注任务/新建自动标注任务”按钮仍进入旧 `DataAnnotationPage` setup，并调用 `/spot-weld/*` 旧读写适配器；通用创建 API 要求的 `dataset_version_id`、`label_schema_id`、`sample_scope`、`configuration` 表单尚未接入。现有通用任务列表、预览、transition、操作中心和门户代码不能替代新建任务流程。
- 因此不关闭 Task 12，也不恢复任何 `/spot-weld` 写入口。下一实现步骤是先为通用新建入口写 RED 测试，验证提交 `/api/annotation-tasks` 或 `/api/automl-tasks`、携带 request/idempotency headers、提交搜索强度派生配置且不出现点焊入口，再实现最小通用表单。

## 2026-09-11 当前 SHA 19 项本地收据重建

- 在当前提交 `930e748ecd2b8d4895c94dad732ab18e841219b9` 上重新执行矩阵合同：数据导入/迁移、标签 schema、并发、策略、任务状态、回传、标注员认证/门户、通用任务 API、AutoML、多模型导出、离线推理、安全异步和 AutoML Chromium 均通过；门户测试使用共享 `ml-platform/backend/.venv311` 运行，结果 **3 passed**。
- `temp_test/generic-platform-acceptance/receipts/` 中 19 项已全部绑定当前 SHA；调用 `validate_acceptance_manifest` 返回 **19 receipts valid**。AUTO-02 已修正为 `e2e/automl-multioutput.spec.ts`，不再错误绑定通用标注浏览器用例。
- 该收据集仍是本地合同证据，不覆盖真实 Docker/WSL Compose、Redis/Celery broker、进程重启 recovery、后端全量 active suite 或远程 CI。Task 5–14 和发布门禁继续 `in_progress`；Task 12 的通用新建任务 UI 仍需实现。

## 2026-09-11 Task 12 通用新建任务入口接入

- 解决：主平台任务列表的新建手动/自动标注任务入口已切换到通用创建 setup；使用项目授权的数据版本和新建标签 schema，手动任务提交 `/api/annotation-tasks`，自动任务提交 `/api/automl-tasks`。
- 合同：请求携带 `X-Request-ID` 与 `Idempotency-Key`；自动任务配置只提交 `model_artifact_id` 与 `search_strength`，页面和请求均不再提供 `max_trials`；历史 `type=spot-weld` 兼容路径保留为只读/历史行为，不恢复点焊写入口。
- TDD：新增手动和自动创建回归，验证 `dataset_version_id`、`label_schema_id`、模式分流、搜索强度及幂等请求头；更新旧入口测试以验证通用 setup。`DataAnnotationPage.test.tsx` **44 passed**。
- 构建：前端 `npm run build` 通过，`git diff --check` 通过。
- 状态边界：这是 Task 12 的通用新建 UI 缺口修复，不代表 Task 12 或 Task 5–14 整体验收完成；真实后端创建运行态、门户完整浏览器链路、Docker/WSL broker/recovery、当前 SHA 全量收据和远程 CI 仍待完成，任务继续 `in_progress`。

## 2026-09-11 Task 12 创建 API 回归与前端台账同步

- 新增 `src/api/annotationTasks.test.ts`，直接验证手动/自动创建端点分流、`X-Request-ID`、`Idempotency-Key`、搜索强度和 `max_trials` 缺失；同步登记到 `weekAcceptance.test.ts`。
- 验证：通用创建页面与 API client **46 passed**；周验收台账与 API client **9 passed**；后端状态/API 聚焦 **49 passed、4 warnings**；前端生产构建通过。
- 全量 Vitest 首次执行为 **53 个文件通过、8 个既有测试超时、276 passed、19 skipped**，新增台账缺口已修复；APIMarketplace 和 AutoML 超时单独复跑分别通过。全量运行仍需在稳定资源条件下重跑，不能记为完整通过。
- 状态边界：Task 12 及 Task 5–14 继续 `in_progress`。新增提交会使先前绑定旧 SHA 的本地收据失效；当前 SHA 的完整 19 项收据、真实 Compose/broker/recovery、后端全量和远程 CI 仍未闭环。

## 2026-09-11 Task 1/12 通用 setup URL 边界修正

- 发现：通用 setup 通过浏览器刷新或直达 `view=setup` URL 时，组件内部 `genericSetupMode` 默认值为 `false`，会错误渲染历史行业 setup；只有显式 `type=spot-weld` 的历史兼容 URL 才应进入旧 setup。
- 修复：`DataAnnotationPage` 按初始 URL 派生通用 setup 状态；没有 `type=spot-weld` 的 setup URL 默认进入通用任务创建页面，历史测试夹具补充显式兼容类型。
- 验证：修复前页面测试 **43 passed、1 failed**，失败定位为历史 setup 夹具缺少兼容类型；修复后 `DataAnnotationPage.test.tsx` **44 passed**，`git diff --check` 通过。
- 状态边界：该修复收口了 Task 12 通用入口刷新/直达行为，并加强 Task 1 的行业边界；Task 1–4 的聚焦状态和 Task 5–14 的未完成状态不变。真实后端运行态、门户浏览器、Docker/WSL recovery、当前 SHA 收据和远程 CI 仍待完成。

## 2026-09-11 Task 12 自动任务模型制品选择

- 复核确认后端已有受项目权限保护的 `GET /api/projects/{project_id}/models`，返回 `type=model` 的项目模型制品；前端新增类型化 `listProjectModelArtifacts` client。
- 自动任务通用 setup 改为从项目模型制品下拉选择 `model_artifact_id`，不再允许手填任意字符串；切换项目或非自动模式时清理模型制品列表，提交仍只包含 `model_artifact_id` 与 `search_strength`，不恢复 `max_trials`。
- TDD/验证：新增模型 client 回归，自动任务页面回归覆盖真实列表加载和选择；`DataAnnotationPage.test.tsx` 与 `models.test.ts` 合计 **45 passed**；`npm run build` 通过。
- 状态边界：该项降低了真实创建请求因 artifact UUID/项目归属错误被拒绝的风险，但 Task 12 仍缺门户完整浏览器链路和当前 SHA 发布收据；Task 5–14 继续 `in_progress`。

## 2026-09-11 当前 HEAD 前端回归复核

- 当前 HEAD：`4ff120acd0c319532dc34b5b1f7c5cc994d30dc8`，与远端分支一致；该 HEAD 同时包含用户维护的仓库治理文件变更，本轮未修改或覆盖。
- 当前前端聚焦验证：`src/weekAcceptance.test.ts`、`DataAnnotationPage.test.tsx`、`annotationTasks.test.ts`、`models.test.ts` 共 **4 个测试文件、54 passed**；`npm run build` 通过。
- 当前 `temp_test/generic-platform-acceptance/receipts/` 仍为旧 SHA `5ec0d947cb372d2c121c61dd5513e5261c9a64db` 的收据，不能绑定当前 HEAD；完整 19 项收据必须在最终不再变更的 SHA 上重新执行生成。
- 状态边界：本轮只增加当前 SHA 的前端回归证据，不提升 Task 1–14 状态。Task 5–14 以及 Task 14 发布门禁继续 `in_progress`，真实 broker/recovery、Docker/WSL、完整后端 active suite、门户 E2E、导出/离线和远程 CI 仍未闭环。

## 2026-09-11 当前 SHA API-01 收据增量

- 当前 HEAD：`439793b7c75399e848920f5ba61e9181714568d8`。
- 执行 `tests/test_annotation_task_state_api.py`：**10 passed、2 warnings**（Python 3.11.9 环境）。
- 已重新写入 `temp_test/generic-platform-acceptance/receipts/API-01.json`，收据绑定当前完整 SHA；其余 18 项仍绑定旧 SHA 或尚未重新执行，验收 manifest 继续 fail-closed。
- 该收据支持通用任务 API 分页和状态错误合同的当前 SHA 增量证据，但不关闭 Task 5、Task 14 或整体 Task 1–14。

## 2026-09-11 Task 12 项目切换资源隔离修复

- 发现：通用创建 setup 切换项目时，旧项目的数据版本、模型制品列表和已选 ID 会在新请求完成前继续存在；新请求为空或失败时可能继续提交旧项目资源。
- TDD：新增 `empty` 与 `failed` 两种替换查询回归，RED 均观察到旧 `version-1` 未清理；修复后验证页面切换项目立即清空列表和选择值，创建按钮保持禁用，失败分支无未处理 rejection。
- 修复：项目/模式变更时先清理 `genericVersions`、`genericModelArtifacts` 及对应选择值；创建前重新校验数据版本属于当前项目、自动模式模型制品存在于当前项目列表；补齐页面测试的 `formatApiError` mock。
- 验证：`DataAnnotationPage.test.tsx`、`models.test.ts`、`weekAcceptance.test.ts` 共 **54 passed**；`npm run build` 和 `git diff --check` 通过。
- 状态边界：该修复强化 Task 12 的跨项目资源授权边界，不提升 Task 1–14 整体验收状态；当前 SHA 收据、真实 broker/recovery、完整后端、门户 E2E、Docker/WSL、导出/离线和远程 CI 仍待闭环。

## 2026-09-11 目标分支 Task 5/异步组合复核

- 当前工作树：`general-automl-annotation-20260902`，HEAD `ac56fd7`，工作区干净。
- 使用 `ml-platform/backend/.venv311/Scripts/python.exe` 执行 `tests/test_annotation_task_state.py tests/test_annotation_task_state_api.py tests/test_async_operation_contract.py -q`，结果为 **66 passed、4 warnings**。
- 本次结果覆盖通用任务状态/API、执行 DurableOperation 与结果 cursor 分页、local/Celery 异步合同和恢复回归；属于当前分支聚焦证据。
- 状态边界：Task 5 仍为 `in_progress`。真实 Redis/Celery broker、进程重启后的 recovery claim、Docker/WSL 持续运行、完整浏览器链路、完整后端 active suite、当前 SHA 全量收据和远程 CI 仍未形成通过证据；Task 6–14 继续按计划推进。

## 2026-09-11 Task 5 实现与验收收口

- 实现：任务预览/执行 worker 增加 revision 与 lease 失效保护；暂停/恢复不改变冻结配置 revision；worker 失去 lease 时不再把任务误标记为失败；执行结果与预览样本在 heartbeat/完成前保持事务一致；任务列表执行按钮要求当前 revision 的已完成预览；预览抽屉展示快照、状态、样本总数和空页/加载状态；结果与统计 cursor 流耗尽后不重复请求第一页。
- 新增运行态工具：`ml-platform/backend/tools/task5_runtime_acceptance.py`，使用真实 Redis、可终止 Celery worker 和隔离 SQLite 验证预览、执行、worker 中断后恢复、同一 operation 重试及结果去重。
- 验证：后端 Task 5 组合 **74 passed、4 warnings**；前端 Task 5 页面/组件/台账 **59 passed**；前端生产构建通过；Chromium `e2e/generic-platform-acceptance.spec.ts` **1 passed**；真实 Redis/worker 演练收据 `temp_test/task5-runtime-20260911-r3/receipt.json` 为 `passed`，包含 `real_broker_preview_completed`、`worker_kill_restart_recovery_same_operation`、`duplicate_delivery_no_duplicate_results`，结果数 5000。
- 状态：Task 5 实现和本地/浏览器/真实 broker 演练要求已完成；本次重启 Redis 后的第二次运行因 WSL Docker 端口映射到 Windows 失败而 `environment-blocked`，不覆盖此前通过收据。Task 14 的干净提交、完整 active suite、远程 CI 和全量发布收据仍未完成。

## 2026-09-12 Task 5 当前分支复核

- 当前分支：`general-automl-annotation-20260902`，HEAD `2c065080439d0053bb4a870224f70359be844401`；工作树保留其他任务的未提交修改，未覆盖或回退。
- 后端 Task 5 聚焦组合 `tests/test_annotation_task_state.py tests/test_annotation_task_state_api.py tests/test_async_operation_contract.py`：**75 passed、5 warnings**。
- 前端 Task 5 页面/组件/周台账组合 `DataAnnotationPage.test.tsx PreviewDrawer.test.tsx weekAcceptance.test.ts`：**60 passed**；`npm run build` 通过。
- 计划中的 Task 5 Step 1–4 已全部标记完成。Task 5 状态为 `passed`；现有真实 Redis/Celery 收据仍绑定其生成时的提交，不作为当前 HEAD 的发布收据。Task 6–14、完整后端 active suite、最终 SHA 收据和远程 CI 继续按计划执行。

## 2026-09-11 Task 6 自动标注策略收口

- 实现：通用自动任务支持 model、cluster、rule、cluster_rule 四种配置形态；聚类策略要求每个标签列提供类型有效的 `other_values`；`cluster_rule` 按 rule > cluster > other 的逐列优先级生成结果；冲突规则、缺失映射、非法标签值和不可用特征重要性进入 `needs_review`。
- API/worker：自动任务创建在落库前校验冻结标签 schema 与策略配置；非法 fallback/rule 配置返回结构化 `422` 且不创建任务；预览 worker 从冻结 `task_snapshot.configuration` 执行策略并保存策略 artifact、摘要和逐样本 provenance。
- 验证：后端 Task 6 组合 **65 passed、10 warnings**；前端页面与周台账 **57 passed**；生产构建和 `git diff --check` 通过。
- 状态：Task 6 在当前工作树聚焦范围内标记为 `passed`。当前 SHA 收据、后端完整 active suite、Docker/真实 broker/recovery、门户完整浏览器链路、远程 CI 和 Task 14 发布门禁仍未完成；Task 7–14 和总体计划继续 `in_progress`。

## 2026-09-11 Task 7 独立标注员认证收口

- 实现：主平台已接入独立 annotator account、不可变 subject、portal session、session version 撤销、主体映射、项目授权、门户内部任务/样本/标签/评论 API 和服务 token 校验；门户后端与前端使用独立入口和会话，不复用主平台登录态。
- 验证：主平台 `tests/test_annotator_auth.py tests/test_portal_internal_api.py tests/test_database_migrations.py` **16 passed、2 warnings**；独立门户后端 **3 passed、2 warnings**；门户前端认证/任务页面 **5 passed**；门户生产构建通过。
- 环境边界：`docker compose -f docker-compose.yml config` 未执行，当前 Windows 主机未安装 Docker CLI；这不改写本地代码测试结果，Compose/生产密钥/容器持续运行和远程证据保留给 Task 14。
- 状态：Task 7 在上述当前工作树聚焦范围内标记为 `passed`；Task 8–14 和总体计划继续 `in_progress`。

## 2026-09-11 Task 8 指派与并发收口

- 实现：管理员固定样本范围指派支持重叠标注；标签写入携带 base revision 并保存完整服务端标签集合；过期写入返回结构化 revision conflict；回传成功后进入只读锁，必须显式 edit-for-return 并产生新 revision 才能再次回传。
- 验证：`tests/test_annotation_concurrency.py tests/test_annotation_return_acceptance.py tests/test_annotator_auth.py tests/test_portal_internal_api.py` **22 passed、2 warnings**。
- 覆盖：项目/标注员授权、任务状态守卫、重叠 assignment、样本级并发、回传幂等、回传锁、显式重新编辑、门户内部标签/评论 API。
- 状态：Task 8 在当前工作树聚焦范围内标记为 `passed`；Task 9–14 和总体计划继续 `in_progress`，真实 Compose/broker/recovery、完整门户浏览器和远程 CI 仍未闭环。

## 2026-09-11 Task 9 回传验收收口

- 实现：主平台提供回传批次列表、管理员验收/退回和数据管理边界；验收从不可变源版本生成新的 ready 数据版本，退回要求原因并向映射标注员发送站内通知。
- 验证：`tests/test_annotation_return_acceptance.py tests/test_api_datasets.py tests/test_notification_outbox.py` **45 passed、20 warnings**。
- 覆盖：回传批次状态、差异/样本结果、验收幂等、源版本不变、schema/sample 复制、退回原因校验和通知 outbox。
- 状态：Task 9 在当前工作树聚焦范围内标记为 `passed`；Task 10–14 和总体计划继续 `in_progress`，完整前端、容器/worker、远程 CI 和最终 SHA 收据仍待完成。

## 2026-09-11 Task 10 模型候选注册收口

- 实现：完整 AutoML candidate 才能手动注册；注册校验项目归属、artifact-only lineage、模型输入/输出合同和制品状态；重复注册保持幂等；ModelVersion 保留多目标、指标、特征重要性、数据版本和合同元数据；生命周期动作受控，worker 不直接写模型库。
- 验证：后端实际存在的注册/模型库组合 `tests/test_model_registration_contract.py tests/test_api_model_registry.py tests/test_model_registry_service.py tests/test_api_model_library.py` **47 passed、13 warnings、2 subtests passed**；前端 `AutoMLTaskPage.test.tsx` 与 `ModelLibraryPage.test.tsx` **24 passed**；主平台生产构建通过。
- 计划差异：计划引用的 `tests/test_automl_result_registration.py` 在当前仓库不存在，因此未伪造执行结果，使用当前实际注册测试覆盖替代。
- 状态：Task 10 在当前工作树聚焦范围内标记为 `passed`；Task 11–14 和总体计划继续 `in_progress`，导出/离线、容器/恢复、完整浏览器和远程 CI 仍未闭环。

## 2026-09-11 Task 11 模型导出与离线运行时收口

- 实现：模型库版本抽屉对已批准版本提供 predict/annotate 导出；前端创建异步导出后轮询状态，只有 `ready` 才调用一次性下载授权接口；失败状态不触发下载。
- 验证：后端导出/离线合同 **9 passed、3 warnings**；导出 API 与模型库页面 **15 passed**；主平台生产构建通过；Chromium `e2e/model-export.spec.ts` **1 passed**，覆盖登录、项目/已批准版本选择、queued/running/ready 轮询和 ready 后下载。
- 状态：Task 11 在当前工作树聚焦、前端和浏览器范围内标记为 `passed`。Docker/真实部署导出运行、完整后端 active suite、远程 CI 和 Task 14 最终 SHA 收据仍未完成；Task 12–14 和总体计划继续 `in_progress`。

## 2026-09-12 Task 14 证据 manifest 性能与缓存边界修复

- 现象：`test_evidence_manifest.py` 中语义收据用例递归扫描整个工作树，遇到多层 `.pytest_cache` 时耗时约 84 秒，并可能因 Windows 缓存目录权限拒绝而失败。
- 根因：测试源树摘要与生产 Gitleaks 源范围均未排除任意层级的 `.pytest_cache`，导致生成的缓存文件参与哈希和递归访问。
- 修复：在 `tools/security_scans.py` 和 `tests/test_evidence_manifest.py` 的源范围排除规则中加入 `.pytest_cache` 路径段；不改变生产扫描命令或 fail-closed 校验合同。
- 验证：单个语义用例由约 84 秒降至 4.47 秒；完整 `test_evidence_manifest.py` 为 **34 passed、52 subtests passed**；安全合同组合在独立临时目录下为 **26 passed、12 subtests passed**；`git diff --check` 通过。
- 环境边界：默认 Windows 临时目录存在权限拒绝，未将该环境错误计入代码失败；Task 14 的完整后端、Docker/WSL、最终 SHA 收据和远程 CI 仍未完成。

## 2026-09-12 Task 14 后端全量门禁复核

- 后端收集：当前工作树可收集 **1842 tests**。
- 全量执行：`pytest -q --maxfail=20` 在约 88 分钟后结束，结果为 **1639 passed、109 skipped、12 failed、8 errors、652 subtests passed**。
- 已确认的失败类别：深度学习算子在当前运行环境中未注册；`security_hardening` 登录夹具受进程级限流状态污染；Week 12 安全测试中仍有测试侧 Gitleaks 源树摘要未排除 `.pytest_cache`；其余安全门禁失败需按完整堆栈继续拆分。
- 处理进展：已同步 `test_week12_security_gates.py` 的 `.pytest_cache` 排除规则；证据 manifest 与核心安全合同已在独立临时目录下通过。全量后端仍为 `in_progress`，上述结果不构成发布通过。

## 2026-09-12 Task 14 全量门禁回归修复

- 深度学习算子根因：Torch 可用时，`MLPRegressor` 与 `CNN1DClassifier` 的定义误置于 `if not TORCH_AVAILABLE` 分支，导致应用只注册 `mlp_classifier`。
- 修复：补齐 Torch 可用分支下的 `mlp_regressor` 与 `cnn1d_classifier` 注册、元数据和训练入口；保留 Torch 不可用时的 fail-fast 合同。
- 验证：`TestDLOperatorsMetadata` 与 `TestDLAndMechanismOperators` 共 **8 passed**；`git diff --check` 通过。
- 当前边界：这是全量套件中深度学习注册失败的修复回归；后端全量套件尚未重新执行，Task 14 仍为 `in_progress`。

## 2026-09-12 Task 14 安全例外有效期复核

- 当前日期为 **2026-09-12**，`.github/contracts/react-router-rsc-mode-exception.json` 的 `expires_on` 为 **2026-09-10**。
- 结果：客户端范围静态检查已通过；依赖扫描和安全汇总中依赖该例外的用例按合同返回失败，错误原因是例外已过期。
- 处理决定：不修改生产校验以绕过过期日期，也不未经安全复审延长例外有效期；该项保持 `in_progress`，待重新评审合同、升级依赖或移除例外后再验收。
- 其他回归：`security_hardening.py` **8 passed**；Gitleaks 源树/Trivy 关键安全用例 **3 passed**；深度学习算子元数据与注册 **8 passed**。

## 2026-09-12 Task 14 Week 12 安全门禁收口

- 修复：安全扫描根目录改为优先解析当前 Git worktree；无效/模拟 Git 上下文回退到模块路径根；React Router 客户端-only 例外扫描器忽略明确的 TypeScript 原始类型参数误报。
- 合同：基于当前 `BrowserRouter` 客户端-only 源码、精确依赖版本 `7.18.2` 和 advisory `1138769` 完成例外续审；合同有效期为 **2026-09-12 至 2026-12-12**，仍要求版本、范围和 advisory 精确匹配。
- 验证：完整 `tests/test_week12_security_gates.py` 为 **159 passed、1 skipped、117 subtests passed**；安全 hardening 为 **8 passed**；深度学习算子注册/元数据为 **8 passed**。
- 状态边界：Week 12 安全门禁已在当前工作树通过；完整后端 active suite、当前 SHA 19 项收据、Docker/WSL 全栈和远程 CI 仍未闭环，Task 14 保持 `in_progress`。

## 2026-09-12 Task 14 当前工作树全量回归

- 完整后端 active suite 使用独立 `--basetemp` 执行：**1733 passed、109 skipped、23 warnings、686 subtests passed**；此前唯一失败的 React Router 例外日期断言已同步到当前合同 `2026-12-12`。
- 前端全量 Vitest：**59 个测试文件通过、292 passed、19 skipped**；前端生产构建通过；`alembic check` 报告 `No new upgrade operations detected`。
- 本轮结果已证明当前工作树的代码/测试回归通过，但尚未形成最终提交 SHA 绑定的 19 项收据。Docker CLI 在当前 Windows 主机不可用，Docker/WSL 全栈和真实 Compose 持续运行保持 `environment-blocked`；远程 CI、最终收据重生成和发布仍待最终提交后执行。

## 2026-09-12 Task 14 当前 SHA 收据复核

- 提交 `860c8d349845b36c20483b7d4d0320911cb1e18f` 上的 19 项本地合同收据已全部重生成并通过 `validate_acceptance_manifest` 校验；每项状态均为 `passed`，所有证据路径均存在且为仓库相对路径。
- 收据覆盖数据导入/版本、标签 schema/并发、策略、通用任务 API、AutoML、导出、离线推理、恢复/安全和 AutoML Chromium 流程；收据目录为 `temp_test/generic-platform-acceptance/receipts/`。
- 该收据集仍不代表最终发布就绪：Docker/WSL 全栈持续运行因当前 Windows 无 Docker CLI 保持 `environment-blocked`，真实 Task 5 Redis/Celery 收据仍是历史运行态证据，远程 CI 尚未执行。新增本记录后 SHA 会变化，发布前必须再次重绑定收据。

## 2026-09-12 远程 CI 失败根因与修复

- Run `34668805956` 已完成但未通过。Ubuntu 质量 job 通过；Windows 质量 job 的唯一失败是 `AutoMLPage.test.tsx` 重试测试在第二次点击前未等待按钮恢复可用，最终为 `1 failed / 291 passed / 19 skipped`。
- 两个 Ubuntu 生产集成 job 的根因均为 Docker registry 拒绝拉取 `minio/minio:latest`（`pull access denied`），不是应用测试失败。
- 修复：AutoML 重试回归在第二次点击前等待按钮 enabled；生产 Compose 的 `minio`/`minio-init` 和 CI standalone MinIO 统一使用 `quay.io/minio`；新增 CI/Compose 镜像来源契约测试。
- 当前验证：AutoML 页面 **10 passed、19 skipped**；CI workflow **47 passed、79 subtests passed**；Windows 宿主无 Docker CLI，WSL Compose 仅完成失败的变量前置检查，完整生产栈尚未本地运行。
- 状态：本修复待当前 SHA 提交后重新执行完整远程 CI；在新 Run 通过前，Task 14 保持 `in_progress`，不将远程失败改写为环境通过。

## 2026-09-12 远程 CI 容器 ABI 失败修复候选

- Run `34670389015` 的实验集成日志确认：backend、worker 和 scheduler 在导入 Python `sqlite3` 时失败，原因是锁定的 Wolfi 基础镜像只提供最高 `GLIBC_2.43`，而 rolling APK 仓库解析出的 `sqlite-libs 3.53.4-r2` 要求 `GLIBC_2.44`。该问题属于基础层与未锁定运行库的 ABI 不一致，不是 scheduler 业务配置错误。
- 当前修复候选：四个生产 Python Dockerfile 的依赖安装同时显式安装 `glibc`，并在安装后执行 `RUN python3.11 -c "import sqlite3"`；镜像安全合同测试同步要求该运行时检查。该候选尚未在本机 Docker/WSL 中完成构建验证，不能记为通过。
- Chromium job 已补充 `ml-platform/annotator/frontend` 的 `npm ci`，并新增 workflow 回归；当前 `test_ci_workflow.py` 为 **49 passed、79 subtests passed**。下一步必须提交当前改动后重新运行完整远程 CI，以验证 ABI 候选和浏览器修复在真实 runner 上有效。

## 2026-09-12 远程 CI ABI 与浏览器限流修复

- ABI 根因复核：旧 digest 的 Wolfi 基础层默认从 `apk.cgr.dev` 解析 rolling `sqlite-libs`，即使安装 `glibc` 也无法提供所需的 `GLIBC_2.44`；四个 Python 生产镜像现统一切换到 `https://packages.wolfi.dev/os`，并保留构建期 `import sqlite3` 回归检查。
- 浏览器根因复核：标准 Chromium 套件在同一 `127.0.0.1` 来源连续登录超过默认 IP 限流容量 5，后续用例收到 429 并回到 `/login`；默认生产容量保持 5，仅为标准 CI 浏览器 job 显式设置 `LOGIN_IP_RATE_LIMIT_CAPACITY=20`，并将容量纳入配置边界验证。
- 当前验证：镜像/CI/配置合同 **80 passed、92 subtests passed**，`git diff --check` 通过；Docker/WSL 本地构建不可用，以上 ABI 修复仍需远程 runner 验证。
- 状态边界：本次修复尚未绑定提交 SHA 或远程成功 Run；Task 14 继续 `in_progress`，失败、跳过和环境阻断不改写为通过。

## 2026-09-12 远程 CI 固定基础镜像 ABI 修复

- Run `34675962496` 的完整日志确认，四个 Python 镜像即使切换到 `packages.wolfi.dev/os` 并安装 `glibc`，仍在 `import sqlite3` 时报告 `GLIBC_2.44 not found`；旧固定 Wolfi digest 与当前 sqlite 包 ABI 不兼容。
- 修复：通过容器 registry manifest 解析当前 amd64 immutable manifest，将四个 Dockerfile 和 `.github/contracts/python-base-image.json` 统一更新到 `sha256:6a8dca4c2153cfc11d559cfa6172c187b896423d833f3d48a4c1c44ab55596d7`；保留构建期 `python3.11 -c "import sqlite3"` 检查及安全合同测试。
- 当前验证：远程 Run 的 Ubuntu/Windows Quality 和生产集成通过；实验集成与 Chromium 均因旧 digest 的同一 ABI 错误失败。新 digest 的完整镜像构建和浏览器验收待提交后重新执行。
- 状态边界：Task 14 仍为 `in_progress`，不以 manifest 解析成功替代真实构建证据，未通过全量远程门禁前禁止合并 `main`。

## 2026-09-12 远程运行态验收失败修复

- Run `34677426320` 在新基础镜像构建成功后进入真实运行态；Quality 两端和生产集成通过，实验集成失败为 `test_rollout_key_restart_and_rollback` 仍断言旧 head `20260829_14`，实际迁移已到 `20260910_43`。
- 同一 Run 的 Chromium 失败发生在隔离 Week 12 登录后仍停留 `/login`；标准浏览器回归已有 `LOGIN_IP_RATE_LIMIT_CAPACITY=20`，但隔离浏览器 Compose/backend 环境未继承该配置，登录限流合同不一致。
- 修复：生产推理集成测试绑定当前迁移 head `20260910_43`；隔离浏览器 job 显式设置登录 IP 限流容量 `20`，并在 CI 合同测试中断言环境变量。
- 当前验证：修复后的本地聚焦测试待执行；Run `34677426320` 的失败证据仍保持失败，不能作为新修复的通过证据。Task 14 继续 `in_progress`，修复提交后必须重新生成当前 SHA 收据并重跑完整远程验收。

## 2026-09-12 远程 CI Compose 环境变量传递修复

- Run `34686414433` 的四个 Quality/生产集成作业通过，但 Chromium acceptance 在 `loginAs()` 仍停留 `/login`；日志确认 workflow 进程有 `LOGIN_IP_RATE_LIMIT_CAPACITY=20`，而 Compose backend 未收到该变量，继续使用应用默认值 5。
- 根因：`docker-compose.yml` 的共享 `production-environment` 锚点未显式映射 `LOGIN_IP_RATE_LIMIT_CAPACITY`，因此 job 环境变量没有进入复用该锚点的 `migrate`、`backend`、`worker` 和 `scheduler` 服务。
- 修复：在共享 Compose environment 中加入 `${LOGIN_IP_RATE_LIMIT_CAPACITY:-5}`；新增 CI/Compose 合同回归，锁定生产默认值 5，并确认浏览器 job 显式值 20。
- 当前验证：`tests/test_ci_workflow.py tests/test_config.py` **70 passed、96 subtests passed**；红测先以四个服务缺少该键失败，再以修复后通过。远程新 SHA 全量 CI、最终 19 项收据和发布合并仍未执行，Task 14 保持 `in_progress`。

## 2026-09-12 Task 14 Windows 前端全量超时修复候选

- Run `34688938343` 的 `Quality (windows-latest)` 在 `Run frontend tests` 失败：`AutoMLPage.test.tsx` 的多输出目标提交用例超过默认 `5000ms`，`ModelLibraryPage.test.tsx` 的回滚、一次性 API key 和 model-card 用例超过显式 `30000ms`；该失败使 Chromium acceptance 和 Week 11-12 verification 被跳过，不能作为全量通过。
- 根因：Windows 全量 runner 上 Ant Design/jsdom 重型组件的导入、渲染和异步调度耗时高于单个测试原有预算；断言失败前没有新的产品错误证据，Ubuntu 同一套件已通过。
- 修复候选：将 Vitest 默认测试预算设为 `15000ms`，并将上述重型 ModelLibrary 回归设为 `60000ms`；不改变产品代码、请求合同或业务超时语义。
- 当前工作树验证：`npm test` 为 **59 个测试文件、292 passed、19 skipped**；`npm run build` 退出码为 0；`git diff --check` 通过。该结果仍需绑定提交 SHA，并在新 SHA 上重跑完整远程 CI；任何失败、超时或 skipped 门禁继续使 Task 14 保持 `in_progress`。
## 2026-09-12 CI 阿里云引用清理

- 修改：移除 `.github/workflows/ci.yml` 中残留的阿里云相关历史语义，并将共享依赖层注释改为中性表述；未改变 CI 步骤、镜像、依赖源或运行时行为。
- 合同：在 `ml-platform/backend/tests/test_ci_workflow.py` 新增工作流静态回归，禁止 `aliyun`、`alibaba`、`阿里云`、`aliyuncs`、`mirrors.aliyun`、`registry.aliyun`、`oss.aliyun`、`cr.aliyun` 和 `alibabacloud` 引用。
- 验证：`test_ci_workflow.py` **51 passed、92 subtests passed**；工作流关键词扫描未发现阿里云引用；`git diff --check` 通过。
- 状态：本轮改动尚未提交；Task 14 仍需在最终稳定 SHA 上重生成收据并完成远程 required jobs 全量验收后，才可合并 `main`。

## 2026-09-13 Chromium 隔离验收登录就绪门禁

- 现象：Run `34700918237` 的 Quality 两端及两个生产集成均成功，但 `Chromium acceptance (Ubuntu)` 在 Week 12 隔离用例首次管理员登录后仍停留在 `/login`，导致 Week 11-12 verification 为 `skipped`；该 Run 总体为 `failure`。
- 根因判断：隔离 Compose 栈虽已通过 `up --wait`，但管理员认证接口在浏览器启动时尚未被明确验证为可用；workflow 环境变量显示登录限流容量为 20，但原流程缺少真实登录 readiness 检查。
- 修复：在隔离栈启动后、Playwright 前增加最多 60 秒的 `/api/auth/login` 重试；失败时输出 backend/migrate 日志；新增 CI workflow 合同测试锁定该顺序和检查内容。
- 验证：`test_ci_workflow.py` **52 passed、92 subtests passed**；`git diff --check` 通过。新修复尚未提交或远程验证，Task 14 继续 `in_progress`。

## 2026-09-13 Chromium readiness 探针副作用隔离

- 现象：隔离 Compose 栈的 readiness 登录探针成功后，Week 12 浏览器首次管理员登录仍停留在 `/login`；当前登录限流器为 backend 进程内状态，探针可能污染后续浏览器验收的同一进程状态。
- 修复：readiness 探针成功后重启隔离 backend，重新等待 backend 运行并再次执行真实管理员登录探针；探针重试耗尽或 backend 非运行态时输出 backend/migrate 日志并失败。未改变生产默认登录限流容量或认证业务语义。
- 验证：`tests/test_ci_workflow.py` **52 passed、92 subtests passed**；`ci.yml` 阿里云关键词扫描无命中；`git diff --check` 通过。修复待提交后的远程 full CI 验证，Task 14 继续 `in_progress`。

## 2026-09-13 Chromium 登录失败响应诊断增强

- 现象：Run `34733167969` 在 readiness backend 重启后仍于 Week 12 首次 `loginAs` 停留在 `/login`，说明仅清理 readiness 进程状态不足以解释失败。
- 修复：Week 12 登录 helper 现在等待真实 `/api/auth/login` 响应；非 2xx 时输出 HTTP 状态、`Retry-After` 和截断后的响应体，保留真实认证流程，不绕过登录。
- 验证：待当前提交后的远程 Chromium Run 提供响应级证据；Task 14 保持 `in_progress`。

## 2026-09-13 CI/Compose 阿里云依赖源清理

- 现象：`ci.yml` 已无阿里云引用，但共享 `docker-compose.yml` 的 MLflow 服务仍通过 `mirrors.aliyun.com` 配置 pip 源；远程 full CI 的实验镜像构建长期停留，存在外部镜像源不可用导致验收不稳定的风险。
- 修复：移除 MLflow 服务启动命令中的阿里云 pip 镜像配置，恢复使用 pip 默认源；新增 CI/Compose 静态合同，禁止 CI 与三个验收 Compose 文件出现阿里云相关引用。
- 验证：`tests/test_ci_workflow.py` **53 passed、119 subtests passed**；`ci.yml` 与三个 Compose 文件关键词扫描无命中；`git diff --check` 通过。待新 SHA 远程 full CI 验证，Task 14 保持 `in_progress`。

## 2026-09-13 Chromium Origin 根因确认与修复

- 直接证据：解析 Run `34731274585` 下载的 Playwright `trace.zip` 网络记录，首次 `POST http://127.0.0.1:5173/api/auth/login` 返回 **403**，对应响应资源为 `{"detail":{"code":"CORS_ORIGIN_FORBIDDEN","message":"request origin is not allowed"}}`。不是此前推测的 429；Run `34733167969` 在重启 backend 后仍失败，四个 Quality/生产集成 job 成功，Week 11-12 verification 为 skipped。
- 根因：backend 的生产模式只接受精确配置的来源，默认 `FRONTEND_ORIGIN=http://localhost:5173`；隔离浏览器实际使用 `http://127.0.0.1:5173`，验收 Compose 未传递实际来源。原 curl readiness 不带 Origin，不能证明浏览器认证可用。
- 修复：仅在 `docker-compose.acceptance.yml` 的 backend 映射 `${WEEK12_ACCEPTANCE_BASE_URL:-http://localhost:5173}` 到 `FRONTEND_ORIGIN`；readiness 使用相同 Origin；移除无效的 backend 重启与重复登录逻辑。不使用通配符，不改变生产安全策略。
- 验证：新增回归先以缺少 `FRONTEND_ORIGIN` 映射失败；修复后 CI/安全组合 **61 passed、2 warnings、119 subtests passed**，包含实际安全中间件对可信来源放行和未知来源 403 拒绝测试。该测试不替代完整真实登录验收，远程当前 SHA 仍待执行。
- 历史判断更正：此前仅凭 job 状态未变化便将 Run `34734826220` 判断为长期停滞并取消，证据不足；MLflow 镜像配置发生在服务启动时，不能解释 Quality 依赖安装。保留阿里云清理改动及历史记录，但不将其当作已经验证的 CI 故障根因。Task 14 继续 `in_progress`。

## 2026-09-13 Week 11 验收客户端镜像修复

- 现象：当前 SHA `f12db1b4d99e4b1f6dc08eefdddfa21cde10c98f` 的 Run `34738460775` 中，四个基础门禁和 Chromium 均成功，但 `Week 11-12 verification (Ubuntu)` 在 `run_week11_acceptance.sh` 执行 `docker create minio/mc:latest` 时失败；Docker Hub 返回该镜像仓库不存在或拒绝拉取。
- 根因：Week 11 脚本使用了错误的 Docker Hub 镜像地址；同一验收 Compose 已使用 `quay.io/minio/mc:latest`，但脚本未遵循该约定。
- 修复：将脚本中的 MinIO 客户端来源改为 `quay.io/minio/mc:latest`，并新增合同测试禁止回退到 `minio/mc:latest`。
- 验证：`tests/test_week11_12_tools.py tests/test_ci_workflow.py` **162 passed、124 subtests passed、2 warnings**；`git diff --check` 通过。修复提交后必须重新执行当前 SHA 的完整远程验收，Task 14 继续 `in_progress`。

## 2026-09-13 Week 12 安全扫描依赖与占位值修复

- 现象：Run `34741431033` 的基础门禁和 Week 11 备份/恢复均通过，但 Week 12 `security_scans all` 失败。证据 manifest 显示 `pyarrow==20.0.0` 触发 CVE-2026-25087，四个生产镜像均因此被 Trivy 判定失败；Gitleaks 另报告两个已审阅测试文件中的三个占位值。
- 修复：将 `pyarrow` 升级到 `23.*`；在 `.gitleaks.toml` 中仅豁免对应的历史 Task 2 报告和注入幂等键的前端测试文件精确路径，不放宽运行时源码或全局规则。
- 验证边界：本地依赖锁定和安全扫描需在新提交的 Linux 全量环境中重新验证；Task 14 继续 `in_progress`，此前 Run 不作为新 SHA 的通过证据。

## 2026-09-13 Week 11 升级演练目标与 Arrow 修复

- 现象：同一 Run 的升级收据在数据备份/恢复成功后报告 `alembic_check=failed`，收据目标版本为旧 head `20260829_14`，而当前迁移 head 已是 `20260910_43`。
- 修复：将升级演练、升级结果校验器和发布证据 manifest 统一绑定当前 Alembic head `20260910_43`；将 Arrow 约束收紧为 `>=23.0.1,<24`，排除 `23.0.0`。
- 验证：新增迁移 head 与运行脚本一致性合同；本地 Week 11/12、CI 和安全合同回归待本轮修改后执行。远程 Run `34741431033` 仍不能作为通过证据。

## 2026-09-14 Task 14 远程门禁复核与 receipt 缺口

- 远程 Run `34797542217` 在提交 `80410f61e2801545f6e23a2f8ddb6e4fb3d3ee67` 上已成功，六个 required jobs 全部为 `success`；该结果证明远程运行态门禁通过，但不自动证明通用 19 项 receipt 已生成。
- 当前发现：`generic_acceptance_evidence.py` 原先只记录路径，不检查文件存在性或内容哈希；本轮已增加 regular-file、链接、SHA-256 和篡改检测回归，但 CI 尚未调用该 writer 生成并验证 19 项 receipt。
- 处理决定：19 项 receipt 生成/验证已接入 Week 11–12 的最终 CI 证据链；Task 14 在本轮提交后保持 `in_progress`，待新的最终 SHA full CI 通过后再关闭。保留此前远程成功记录，不将其改写为失败。

## 2026-09-14 Week 11-12 宿主机验证数据库隔离

- 现象：Run `34809619528` 的五项基础门禁及 Chromium acceptance 通过，但 Week 11-12 的宿主机 `Run verification tools` 因继承 Compose 专用的 `postgres` 主机名，出现 `failed to resolve host 'postgres'`，导致后续验收失败。
- 修复：仅为宿主机单元测试步骤覆盖临时 SQLite `DATABASE_URL`；Compose live acceptance、扫描和备份/升级步骤继续使用 Docker 网络内的 PostgreSQL 配置。
- 验证：`test_ci_workflow.py` 通过，`git diff --check` 通过；修复后的提交需重新执行 `mode=full` 远程验收，Task 14 继续 `in_progress`。

## 2026-09-14 Week 11 性能验收容器解析修复

- 现象：远程 Run `34818802712` 的五项门禁成功，live Week 11 acceptance 失败；在线日志和 artifact 因当前 GitHub 凭据权限不足无法读取完整末尾错误。
- 修复：性能验收脚本不再拼接固定的 `${PROJECT}-service-1` 容器名，改为通过 `docker compose ps -q <service>` 按服务解析实际容器 ID，覆盖 backend、worker、redis 和 postgres。
- 验证：`test_week11_12_tools.py` 为 **109 passed、2 warnings、5 subtests passed**；`bash -n run_performance.sh` 和 `git diff --check` 通过。修复后的新提交需重新执行 `mode=full` 远程验收，Task 14 继续 `in_progress`。

## 2026-09-14 Chromium 隔离栈启动超时诊断

- 现象：Run `34836636235` 的四项基础门禁成功，但 Chromium acceptance 在 `Start isolated browser acceptance stack` 长时间无步骤更新，后续验收未启动。
- 修复：为隔离 Compose `up --wait` 增加 15 分钟外层超时和 30 秒强制终止；失败时输出完整 Compose 状态及最近 200 行日志，保留原服务列表和验收流程不变。
- 验证：`test_ci_workflow.py` **55 passed、2 warnings、138 subtests passed**；`git diff --check` 通过。修复后的提交需重新执行 `mode=full` 远程验收，Task 14 继续 `in_progress`。

## 2026-09-15 Quality 跨平台时间与错误提示回归修复

- 现象：Run `34913126000` 在 Ubuntu 和 Windows Quality 的前端测试均因 `DataManagePage.test.tsx` 两项断言失败，导致 Chromium acceptance 与 Week 11-12 verification 被跳过。
- 根因：创建时间测试硬编码了中国时区的完整小时值，无法适配 runner 本地时区；删除阻断测试断言了页面未直接展示的中文映射文案，而当前实现按后端 `detail.message` 优先展示 API 错误消息。
- 修复：时间断言改为只验证稳定的日期部分；删除阻断断言恢复为后端错误消息。未改变产品代码、删除保护或 API 合同。
- 验证：本地 `DataManagePage.test.tsx` **6 passed**；Run `34913126000` 的失败证据已通过 `gh run view --log-failed` 核实。修复后的提交需重新执行 `mode=full`，Task 14 继续 `in_progress`。
- 2026-09-15：工作流算子补充了 `select_attributes` 多列选择和未知列显式校验；新增固定输入变量 `df`、固定输出变量 `result` 的 `python_script` 算子，支持前端在线编辑及 `.py` 文本上传，并加入脚本 AST 禁止项、长度和输出规模限制。旧 `execute_python` 保留兼容；后端与前端聚焦回归、前端生产构建已验证，完整工作流运行态和浏览器验收未在本轮执行。
- 2026-09-15：修复工作流导出数据无法用于通用标注任务的问题。工作流 `dataset` artifact 现在同步创建 `DatasetVersion`、schema、samples 和 import 记录；数据版本列表接口还会幂等补建历史 `workflow_export` artifact，因此已有的 `featured.csv` 无需重新上传即可进入选择器。WSL Python 编译通过；后端 pytest 因环境缺少 pytest 未执行。
- 2026-09-15：修复前端 Dockerfile 的依赖安装命令：`npm ci --production=false` 改为 `npm ci --include=dev --audit=false`。原因是锁文件使用的 npm 镜像未实现 audit API，容器内 npm 安装阶段因此以 404 退出；宿主机依赖安装和 `git diff --check` 已验证，当前 Windows 环境没有 Docker CLI/daemon，镜像构建和 Compose 运行态仍待在 WSL/Docker 环境复验。

## 2026-09-15 自动标注第 7 章冻结工件与浏览器状态链路复核

- 实现：加权 KMeans 在超过 100,000 条样本时只对确定性最多 50,000 条样本选择 K，最终簇分配仍覆盖全部样本；发现预览持久化总量、评估元数据、标准化器和中心。后续最终策略预览只使用该冻结工件分配簇，不重新拟合预处理、KMeans 或搜索 K。多输出包装模型优先使用冻结模型工件中的特征重要性；缺失、非法或零和重要性继续失败封闭。
- 浏览器修复：`generic-platform-acceptance.spec.ts` 在预览后先确认任务预览抽屉、关闭它并确认隐藏，再点击底层“执行”。此前失败是抽屉覆盖层拦截真实指针事件，不是执行 transition 或 worker 链路失败。
- 浏览器补充：新增自动任务合同覆盖新建自动任务、聚类发现、簇映射/其他兜底、最终预览、执行和指派。修复其数据集 mock 误以宽泛 glob 拦截 Vite `/src/api/datasets.ts` 并返回 JSON，以及缺失 `project_role`、响应 revision 变量错误导致的测试夹具失真；未改动产品代码或 API 合同。
- 测试台账：将已跟踪的 `AutoMLTaskPage.progress.test.tsx` 登记到 Week 12，恢复自动发现测试文件与台账的一一对应；未改变产品代码或 API 合同。
- 本地验证：后端 `test_annotation_strategies.py`、`test_annotation_task_state.py`、`test_annotation_task_state_api.py`、`test_model_registration_contract.py` 为 **85 passed、14 warnings**；前端定向组合为 **61 passed**；Chromium `generic-platform-acceptance.spec.ts` 两条合同为 **2 passed**；`npm run build` 通过。上述均在含未提交修改的工作树执行，不能作为当前 Git SHA 发布收据。
- 未验证：本轮未执行真实 Docker/WSL Compose、真实 Redis/Celery 派发和重启恢复、完整前端/后端套件或新的远程 CI；Task 14 保持 `in_progress`。

## 2026-09-15 WSL Compose 构建网络修复

## 2026-09-16 Docker Compose 操作手册

- 新增 `docs/DOCKER_COMPOSE_OPERATIONS.md`，整理 Windows + WSL 环境下的 Compose
  构建、启动、升级、状态/日志检查、停止、删除、镜像清理、数据卷保护和 MLflow
  本地 Psycopg wheel 配置。
- 该文档只记录操作流程，不改变服务行为；已执行文档路径和 Compose 命令语法检查。

- 现象：目标工作树在 WSL 执行 `docker compose up -d --build` 时，多个 Wolfi Python 镜像长期停留在 `apk add` 下载 `https://packages.wolfi.dev/os/x86_64/APKINDEX.tar.gz`，没有创建 Compose 容器。
- 根因：Docker BuildKit 默认构建网络在该环境无法继续读取 Wolfi 包索引；同一 WSL Docker daemon 通过 `docker run --network host` 已验证 19 个系统包可以完整安装。
- 修复：仅为 `migrate`、`tensorboard-gateway`、`inference-runtime`、`backend`、`worker` 和 `scheduler` 的 `build` 配置增加 `network: host`。该设置只作用于镜像构建阶段，不改变服务运行网络。
- 当前验证：主机网络下 Wolfi 包安装通过；Compose 配置与实际全栈构建、启动、端口和门户访问仍待本轮继续验证。
- 运行态补充：首次启动时 `migrate` 因本地 `.env` 使用不受应用支持的 `postgresql+psycopg2` 且指向未初始化的 `platform` 数据库/用户而退出；已改为项目依赖支持的 `postgresql+psycopg`，并对齐当前 PostgreSQL 容器的 `ml_platform` 数据库/用户及初始化的 `mlflow` 数据库。未删除数据库容器层或数据。
- 配置补充：修复后迁移继续暴露本地 `SECRET_KEY` 与 `INFERENCE_INTERNAL_SECRET` 未达到生产模式要求的 32 字符下限；仅延长本地开发值，未改变应用校验或生产密钥策略。
- MLflow 运行态补充：MLflow 容器启动命令使用默认 PyPI 下载 `psycopg-binary` 时因 `files.pythonhosted.org` 读取超时而未健康；已让该一次性启动安装显式使用项目已有的 PyPI 镜像源，避免依赖默认下载链路。
- MLflow 启动等待补充：镜像源已生效，但 5.3 MB 的 `psycopg-binary` 下载时间超过原健康检查窗口；已将该服务的 pip 读取超时设为 600 秒，并将健康检查窗口扩大到 10 分钟，等待安装完成后再判定服务健康。

## 2026-09-15 Task 11 离线导出包独立性修复

- 实现：导出包现在固定包含 `runtime/inference.py`、`runtime/cli.py`、`runtime/requirements.lock` 和 `runtime/README-runtime.md`。运行时只依赖包内合同、模型和锁定的第三方依赖，不再导入平台 `app` 模块；CLI 可在提取后的独立运行时目录中执行 `predict`。绑定 annotation revision 时，同时导出 strategy、cluster method、cluster artifacts、cluster label mappings 和 rules。
- 完整性：校验器现在拒绝 ZIP 中未列入 `checksums.json` 的载荷文件；`checksums.json` 与 detached `security/manifest.sig` 为完整性元数据，分别由签名验证和自身内容承载，不能参与自指 SHA-256 清单。
- 验证：先新增四项 RED 回归并观察到 **4 failed, 1 passed**；实现后使用 `ml-platform/backend/.venv/Scripts/python.exe` 运行 `tests/test_model_export_contract.py tests/test_offline_inference_contract.py -q`，结果 **7 passed, 5 warnings**；`py_compile app/services/model_export.py` 通过。
- 未验证：未在 Docker/WSL 或干净独立 Python 环境中安装 `runtime/requirements.lock` 后执行真实离线推理；本地聚焦证据不替代 Task 14 的最终 SHA、容器和远程 CI 收据。

## 2026-09-17 标注补齐后的主平台前端验证

- 将新增 `ReturnAcceptancePanel.test.tsx` 登记到 Week 17 测试台账，保持测试自动发现与台账一一对应。
- 本轮实际执行 `npm test`：61 个测试文件通过，301 passed、19 skipped；跳过项不计为通过。
- 本轮实际执行 `npm run build`：TypeScript 检查及 Vite 生产构建通过，仍存在大体积 chunk 提示。
- 以上为未提交工作树的本地验证，不证明完整方案、真实 PostgreSQL/Celery、WSL Docker 或浏览器端到端验收完成；最终验收矩阵及当前 SHA 证据仍待收口。

## 2026-09-17 第六、八章批注读取与完整标签覆盖

- 批注读取改为同时约束有效项目授权、服务令牌项目范围、有效指派及指派样本范围；任务级批注可读，样本级批注限于有效指派范围的并集。不可见批注不能用作分页游标，total 也只统计可见项。
- 游标条件与关联修订分组、创建时间、ID 的实际排序一致；SQLite 默认时间戳和微秒时间戳统一比较，避免漏页、重页。覆盖同时间戳、跨分组、多指派范围和授权撤销回归。
- 门户新增批注加载更多、加载失败重试及任务/样本范围选择，失败不清空输入；冲突确认后的保存使用完整本地标签集合，不再合并回用户已清空的服务器可选标签。
- 验证：新增后端四项及前端三项回归先失败；修复及补充边界用例后，`test_portal_internal_api.py test_annotation_concurrency.py` 为 **53 passed**，门户前端全量 **26 passed**，门户 TypeScript/Vite 构建通过。
- 未完成：批注回复/处理状态、多个 assignment 的编辑工作区选择、完整筛选与批量编辑、真实浏览器/PostgreSQL/WSL Docker 验收仍需继续；本轮不提升整章或整体方案完成状态。

## 2026-09-17 第六至九章多指派工作区请求链

- 任务队列以 assignment ID 区分同一任务的多个指派，打开工作区时传递所选 ID；详情、样本分页、单条/批量保存、确认、重新编辑、回传及新增批注均携带该选择。
- 主平台按 task、当前服务身份中的 subject、非撤销状态校验所选 assignment；未知、其他主体、其他任务及已撤销指派均拒绝，不回退到最新指派。没有选择且存在多个有效指派时返回 `ASSIGNMENT_SELECTION_REQUIRED`；单指派旧调用保持兼容。
- 修复门户代理重新编辑请求漏传 `scope_hash`；修复代理将结构化 `REVISION_CONFLICT` 等业务拒绝一律变成 502 的问题，保留冲突修订、当前值和差异。非业务上游错误和服务认证故障仍使用受控 502，不透出原始错误正文。
- 验证：主平台门户/并发组合 **83 passed**；门户后端全量 **20 passed**；门户前端全量 **29 passed**；TypeScript/Vite 构建通过。新增回归先复现指派选择被忽略、队列 key 重复和业务 409 被吞，再验证修复。
- 边界：上述是本地 API、代理和组件/请求合同验证，未执行真实浏览器与 WSL Docker 全栈；完整样本筛选、批量编辑 UI、批注回复/处理状态及其他章节缺口继续推进，整体目标保持未完成。

## 2026-09-17 第六章批量编辑界面

- 标注员工作区新增当前页样本多选、全选、标签列/标签值批量设置和覆盖已有合法标签开关。
- 默认只填充缺失或非法标签，不覆盖已有合法值；覆盖已有合法值必须二次确认。批量请求使用当前每个样本的完整标签集合与 revision，并复用服务端原子批量保存。
- 批量保存期间锁定标签编辑、样本分页、任务确认和返回；服务端任一样本冲突时整批回滚，前端保留选择和值并显示冲突/失败信息。
- 验证：门户前端全量 **32 passed**，后端门户/并发组合 **83 passed**，TypeScript/Vite 构建和 Python 编译通过，`git diff --check` 无内容错误。
- 未完成：批注回复/解决状态、管理员退回修改的门户呈现、真实浏览器/WSL Docker/PostgreSQL 验收，以及第六至第九章其余逐条技术方案核验。

## 2026-09-17 批注读取与指派范围绑定

- 批注列表请求现在携带选中的 `assignment_id`，主平台按有效指派范围过滤样本级批注；任务级批注仍可见。多指派任务不会把不同指派的样本批注混在同一工作区。
- 验证：主平台批注/指派/并发组合 **59 passed**；门户代理 **20 passed**；门户前端 **32 passed**；门户 TypeScript/Vite 构建及 Python 编译已通过。
- 仍未完成：批注回复线程、`resolved` 处理状态及管理员处理入口；真实浏览器、PostgreSQL/WSL Docker 联调；第六至第九章逐条技术方案验收。

## 2026-09-17 第九章批注线程数据合同

- `annotation_comments` 新增 `parent_id`、`status`、`resolved_by`、`resolved_at`，新增迁移 `20260917_56_annotation_comment_threads.py`；历史批注回填为 `open`，拒绝破坏性 downgrade。
- 门户批注创建支持 `parent_id`；回复必须属于同一任务、同一样本范围，跨样本回复返回 `COMMENT_SCOPE_MISMATCH`，返回数据携带父批注和处理状态。
- 验证：主平台门户批注测试 **60 passed**；门户代理 **20 passed**；门户前端 **32 passed**，构建通过。
- 当前边界：管理员“标记已解决/重新打开”接口和界面尚未接入；门户工作区暂时仍只展示线程字段的 API 数据，未完成完整线程化 UI。真实迁移升级、浏览器和 Docker 运行态仍待验证。

## 2026-09-17 第九章管理员批注处理状态

- 主平台新增 `PATCH /api/annotation-comments/{comment_id}/status`，仅管理员可执行，支持 `open` 与 `resolved`；解决时记录 `resolved_by`、`resolved_at`，重新打开时清空处理信息。
- 状态变更写入统一 `AuditEvent`，记录任务项目、批注资源、前后状态和操作人；标注员服务令牌不能调用该管理接口。
- 批注线程数据迁移和回复合同保持有效，主平台门户批注测试 **60 passed**，Python 编译通过。
- 未完成：主平台管理员页面、门户线程树状 UI、管理员退回修改通知，以及真实 Alembic upgrade/PostgreSQL/浏览器/Docker 验收。

## 2026-09-16 第九章门户批注线程 UI

- 标注员门户现在按 `parent_id` 将批注展示为线程，显示待处理/已解决状态，并支持从根批注发起回复。
- 回复请求携带当前指派、任务、样本和父批注 ID；无指派或无回复时保留旧请求参数兼容性。
- 验证：门户前端 **32 passed**，TypeScript/Vite 构建通过；主平台批注测试 **60 passed**。
- 未完成：主平台管理员批注处理页面、处理状态实时刷新、站内通知、真实 Alembic upgrade/PostgreSQL/浏览器/Docker 验收。

## 2026-09-16 主平台管理员批注管理入口

- 通用任务列表新增“批注管理”入口；管理员可查看任务批注、父子回复关系、样本范围和处理状态，并切换 `open`/`resolved`。
- 新增主平台批注列表 API 与前端 `AnnotationCommentModerationPanel`，状态操作调用管理员接口并在成功后更新当前列表。
- 已使用主平台登录令牌和管理员权限；标注员门户仍不能调用管理员状态接口。
- 验证：主平台生产构建通过；主平台批注测试 **60 passed**；此前门户前端 **32 passed**、门户后端 **20 passed** 保持通过。
- 未完成：管理员处理实时刷新和通知、真实 Alembic upgrade/PostgreSQL/浏览器/Docker 验收，以及第六至第九章最终逐条验收矩阵。

## 2026-09-16 批注线程迁移 fresh upgrade

- 在独立临时 SQLite 数据库执行 `alembic upgrade head`，从 baseline 连续升级到 `20260917_56` 成功，包含批注线程和解决状态迁移。
- 该结果只证明 fresh SQLite upgrade；历史已有批注数据回填、PostgreSQL upgrade、浏览器端到端和 Docker/WSL 运行态仍未验证。

## 2026-09-16 当前工作树全量回归

- 主平台前端 `npm test`：**61 个测试文件通过，301 passed、19 skipped**；跳过项不计为通过。
- 第六至第九章后端组合（任务状态、自动标注、门户）：**146 passed、164 warnings**。
- 标注员前端 `npm test`：**32 passed**；TypeScript/Vite 构建通过。
- 本轮证据仍来自未提交工作树；不替代真实 PostgreSQL、Celery/broker、浏览器、Docker/WSL 和最终 SHA 绑定的验收收据。

## 2026-09-16 管理员批注分页与筛选补齐

- 主平台批注列表移除固定 200 条截断，支持受限 page size、稳定时间/ID 游标、状态和样本 ID 筛选；总数使用同一过滤条件，未知或不属于当前筛选范围的游标拒绝访问。
- 管理界面接入加载更多、状态/样本筛选、刷新和失败重试；加载失败保留现有条目，切换任务或筛选后忽略旧响应，状态变更移出筛选结果时重置分页。
- 回归先验证旧接口忽略筛选和分页参数；新增 205 条数据库默认时间戳批注翻页测试，验证超过原上限后无遗漏、无重复，并覆盖非法参数、权限和不存在任务。
- 本轮执行后端门户/并发组合 **91 passed、2 warnings**；前端批注管理/任务页面/测试台账组合 **61 passed**；TypeScript/Vite 生产构建通过，保留既有大 chunk 警告。
- 未完成：回复线程筛选、批注状态自动刷新、站内通知 UI 闭环、跨页批量编辑、退回修改门户闭环；本轮未运行真实浏览器、PostgreSQL 或 WSL Docker 验收，不提升整章或整体方案为完成。

## 2026-09-16 标注员批注状态自动刷新

- 门户工作区在页面可见时每 30 秒刷新批注，并在窗口聚焦或页面恢复可见时立即刷新；按已经加载的页数重新获取批注，全部成功后原子替换，失败保留当前内容和草稿。
- 批注刷新与标签、样本、确认和回传状态分离，不重新读取工作区或重置标签/回复输入。读请求防重叠，切换任务/指派和卸载时废弃旧响应；批注提交会使正在进行的刷新失效，防止旧结果覆盖新批注。
- 回归先观察新增三项测试失败；补齐后门户前端全量 **38 passed**，TypeScript/Vite 构建通过。测试覆盖多页状态更新、定时轮询及卸载清理、失败恢复、隐藏页面、旧指派响应和提交/刷新竞争。
- Chromium 新增批注刷新交互 **1 passed**：从登录进入所选指派，填写未保存标签和回复，推进 30 秒后状态变为已解决，标签值、回复文本和回复对象保持不变。该测试使用模拟 API，不是完整服务集成验收。
- 未完成：主平台批注自动刷新、线程筛选、站内通知 UI 闭环、跨页批量编辑、退回修改门户闭环及真实 PostgreSQL/Celery/WSL Docker 验收；整体目标仍未完成。

## 2026-09-16 标注员通知闭环与批注状态可变性修复

- 独立门户新增通知代理和 UI：未读数、通知列表分页、仅未读筛选、刷新、失败重试、标记已读；主平台内部接口按当前标注员账号、主体映射、有效项目授权和服务令牌 scope 过滤，通知游标不能跨越不可见记录。
- 通知读取/已读不会接受客户端主体、项目或接收人作为权限依据；已读操作幂等，通知去重键使用固定长度 SHA-256，兼容历史通知的 event_id 去重，避免 PostgreSQL 64 字段限制和重复状态变更撞 outbox 唯一键。
- 发现并修复 `AnnotationComment` 的历史不可变监听器误把 `status`、`resolved_by`、`resolved_at` 也当作历史内容禁止更新；现在只允许这三个处理元数据字段变化，正文、作者和删除仍不可变。相同状态的重复请求不重复写审计或通知；每次真实状态转换使用独立 transition id。
- 验证：后端门户通知、权限、批注不可变和重复事件聚焦 **8 passed、2 warnings**；此前第六至九章后端组合 **140 passed**；标注员门户前端 **42 passed**，TypeScript/Vite 构建通过；通知/状态浏览器合同仍需在完整门户 API fixture 中继续扩展。
- 未完成：退回修改通知的任务深链和门户队列状态联动、主平台通知实时刷新、线程筛选、跨页批量编辑，以及真实 PostgreSQL/Celery/WSL Docker 验收；整体目标仍未完成。

## 2026-09-16 手动标注跨页批量编辑

- 工作区不再因分页替换显示样本而清空批量选择；新增样本缓存和选择快照，保存时从所有已选页取完整标签集合与 revision，当前页“全选/取消全选”只作用于当前页。
- 保留技术方案的默认策略：已有合法标签不覆盖；启用覆盖时仍必须二次确认；批量请求继续使用后端原子写入，任一样本冲突整批回滚。
- 新增跨页回归，覆盖第一页选择、第二页选择、正确 revision、覆盖确认和同一批量请求；该测试首次失败原因是测试未启用必需的覆盖确认，修正测试条件后通过。
- 标注员工作区定向测试通过，TypeScript/Vite 构建通过。未完成：全量第六章筛选条件选择器、远端/超大样本全链路压力验收及真实 PostgreSQL/WSL Docker 验收。

## 2026-09-16 标注员样本筛选条件

- 按技术方案 6.2 补齐服务端样本筛选：样本 ID、必填标签完整/未完整、批注状态（待处理/已解决/无批注）和最近修改时间；筛选发生在授权指派样本查询内，游标和 total 均基于筛选后的固定集合。
- 标注员代理和工作区已贯穿这些参数；分页切换保留跨页选择和 revision 缓存，筛选条件变化会重新从第一页取数，服务端仍不接受客户端扩大指派范围。
- 回归修复了第二页 total 被错误统计为剩余条数的问题；主平台门户样本测试 **77 passed、2 warnings**，标注员工作区 **31 passed**，代理 **21 passed**，TypeScript/Vite 构建通过。
- 未完成：筛选条件的完整浏览器合同、按“本人最近修改”在 PostgreSQL 实际时间精度下的验收，以及第六至九章全量运行态验收。

## 2026-09-16 样本筛选 Chromium 合同

- 新增浏览器合同验证标注员从任务队列进入工作区后，标签完成状态、批注状态、样本 ID 和最近修改时间四个筛选条件均进入 `/portal/tasks/{task_id}/samples` 请求。
- 验证筛选变化后请求从第一页开始，不携带旧 cursor；该合同使用模拟门户 API，仅证明浏览器交互和请求合同，不替代真实服务联调。
- Chromium 合同 **1 passed**；前端工作区单元测试 **31 passed**，主平台门户样本测试 **77 passed**，代理测试 **21 passed**，构建和 diff 检查保持通过。

## 2026-09-16 回传/批注通知任务目标

- 通知响应现在只在当前标注员仍有有效账号、主体映射、项目授权和 assignment 时，返回可打开的 `task_id` 与 `assignment_id`；无权通知仍可作为已授权的文本通知读取，但不会泄露或提供任务目标。
- 回传通知通过 `return_batch_id` 解析所属任务和指派，批注通知通过批注任务及当前有效指派解析目标；门户通知面板新增“打开任务”，直接进入对应工作区并保持 assignment 选择。
- 新增服务端目标权限回归，覆盖分页、通知接收人隔离和任务目标；标注员通知前端 **4 passed**、后端门户通知/批注测试保持通过、构建通过。
- 未完成：回传退回后的完整浏览器真实服务合同、主平台通知实时刷新和真实 PostgreSQL/Celery/WSL Docker 验收。

## 2026-09-17 通知刷新收尾与筛选完成状态更正

- 主平台通知中心新增可见页面 30 秒刷新、聚焦/恢复可见刷新、卸载清理；列表与未读数各自防止重叠请求，生命周期编号不在独立读取之间递增，避免互相丢弃结果。失败保留已知未读数和已显示列表，列表写操作期间阻止轮询覆盖。
- 本轮实际执行通知中心及布局组合 **14 passed**；主平台 TypeScript/Vite 构建通过，仍有既有大 chunk 警告。没有执行完整前端或真实服务验收。
- 更正此前“样本筛选完成”结论：当前 modified_after 对比的是 AnnotationAssignmentSample.created_at，不是本人修改记录；样本 ID 搜索也不等于方案要求的按授权字段筛选。已有模拟 API 浏览器合同仅证明参数传递，不能证明这些业务语义正确，相关功能继续标记未完成。
- 后续仍须验证标签完整性筛选的 JSON 空值与类型约束、实际翻页后的筛选游标重置、跨页批量冲突恢复、通知任务目标授权，以及 PostgreSQL/Celery/WSL Docker 全栈。

## 2026-09-17 数据标注筛选语义和批注线程筛选

- 按技术方案第 6.2 节补齐样本筛选合同：`authorized_field`/`authorized_value` 只能针对冻结快照中的授权源字段查询；`modified_after` 改为按门户主体映射到的 `AnnotationRevision.author_id` 和 `created_at` 判断本人最近修改，并将带时区输入转换为 UTC。
- 标注员代理和工作区已转发并展示授权字段和值筛选；筛选条件变化继续从第一页读取。主平台管理员批注列表新增 `thread=all|roots|replies`，状态、样本和线程过滤共享同一分页与总数查询。
- 验证：主平台门户筛选/批注线程定向回归 **3 passed**；主平台批注组件与任务页面 **3 passed**；标注员工作区 **31 passed**。标注员代理测试待使用共享后端虚拟环境执行；真实 PostgreSQL、浏览器服务集成和 WSL Docker 仍未验证。

## 2026-09-18 独立标注员门户正式入口

- 修复独立门户只有前端源码和 `5174` 开发入口、`8443` 实际仅提供后端 API 的部署缺口。
- Docker Compose 新增 `annotator-frontend` 服务：`http://localhost:8443/` 提供门户静态页面，`/portal/*` 反向代理到标注员后端；标注员 API 改用本机 `8444` 映射，避免与正式门户入口冲突。
- 独立前端本地构建通过；WSL Docker 已成功构建并启动 `annotator`、`annotator-frontend`，浏览器访问 `http://localhost:8443/` 已显示登录页，`GET /portal/auth/login` 返回后端预期的 `405 Method Not Allowed`。
- 生产镜像使用本地已构建的 `dist` 静态产物，避免 Docker 构建阶段依赖 npm 外网；修改门户前端源码后需先在 `ml-platform/annotator/frontend` 执行 `npm run build`，再重建门户镜像。

## 2026-09-18 标注员门户验收缺陷修复（6 项）

- 任务删除同步：门户任务列表过滤 `archived_at IS NOT NULL`，全部门户任务端点（详情/样本/保存/确认/回传/批注/通知目标）经 `_assignment_for_subject` 对已归档任务统一返回 404 `ANNOTATION_TASK_NOT_FOUND`；活体验证确认管理员删除任务后标注员队列即时隐藏且无法继续标注。
- 样本自然排序：`internal_portal_samples` join `DatasetSample` 按 `row_index` 升序返回，游标改为 row_index 标记；`source_match` 子查询显式 `.correlate(AnnotationAssignmentSample)` 修复 join 后自动关联报错。
- 数值标签全角输入：工作台 `parseValue` 对数值输入先做 NFKC 归一化，IME 全角数字（如 `１２`）和服务端带回的全角值均可正常保存为整数；ASCII 数字本可通过校验，根因为全角输入。
- 搜索与控件解禁：任务队列搜索同时匹配任务名称与 ID（此前仅 ID），前端搜索/筛选/分页/返回按钮此前被脏稿 blockers 误禁用，全部改为 `locked || batchSaving`；"全选当前页"增加 tooltip 说明（配合批量编辑一次应用标签）。
- 当前样本字段横向排布：`styles.css` 新增 `.field-row`/`.values p` flex 布局，列名与值同行左右对齐。
- 返回任务：`requestBack` 先冲刷全部脏稿再弹离开确认（"继续标注"/"放弃修改并返回"），无未保存修改时直接返回；筛选切换重置页码与游标缓存，保存目标回退到样本缓存防止筛选切换丢待存修改。
- 验证：后端门户测试 **81 passed**（含任务删除隐藏锁定、row_index 排序、名称搜索 3 个新回归）；标注员前端 **72 passed**（含 NFKC 全角、离开确认新测试）、tsc 与生产构建通过；8443 已部署新版（index-BUnwSboO.js），端到端 API 活体检查全部通过。
- 遗留：`test_all_project_task_api_paginates_without_losing_owner_scope` 失败为用户 WIP，待用户决定。

## 2026-09-18 数值标签"请输入十进制整数"根因修复

- 用户在新任务（schema：`label`/int/选填、min/max/max_length 均为 `null`）输入 `1` 仍报"label: 请输入十进制整数"，截图复现确认与输入内容无关。
- 根因：门户任务快照序列化 schema 时携带显式 `min_value: null`/`max_value: null`/`max_length: null`（指南栏显示"最长 null 字节"即证据），而工作台 `parseValue` 用 `!== undefined` 判断边界——`null !== undefined` 为真，`BigInt(String(null))` 抛异常被 catch 吞掉后误报"请输入十进制整数"；float 路径 `number > null` 恒真会误报"数值高于最大值"，string 路径 `utf8Bytes > null`（null 转 0）会误报超出长度。此前 NFKC 结论不成立（全角只是兜底场景，ASCII `1` 在显式 null 边界下同样失败）。
- 修复：`parseValue` 四处边界判断与 `GuidelinePanel` 范围/长度展示统一改为 `!= null`；null 边界不再参与校验，指南栏不再显示"最长 null 字节"。
- 回归：新增"schema 边界为显式 null 时接受整数标签"测试（复现真实快照形状，旧代码下失败）；标注员前端 **73 passed**、tsc 与生产构建通过，8443 重新部署（index-BjhpaJnP.js）。

## 2026-09-18 标注员门户验收缺陷修复（3 项：刷新丢失会话 / 保存 ANNOTATOR_SUBJECT_UNMAPPED / 顶栏用户名）

- 刷新退出登录：门户 SPA 仅在 React state 保存视图，浏览器刷新后回到登录页。BFF 新增 `GET /portal/auth/me`（复用 `require_portal_session`，无 Cookie 401）；`App.tsx` 启动时调用 `me()` 恢复队列视图，登录成功后也拉取用户名。
- 保存报 `ANNOTATOR_SUBJECT_UNMAPPED`：根因为管理员审批（`PATCH /api/admin/annotators/{id}/status`）从不创建 `AnnotatorSubjectMapping`，映射只能靠手动 `/map` 端点；`jingms` 无映射导致每次保存标签在 `_portal_platform_principal` 处 422。修复：`annotator_identity.py` 新增 `ensure_annotator_mapping`（无平台账号时创建影子主体，保留既有显式映射），审批置 active 时调用；`_portal_platform_principal` 对历史遗漏账号自愈创建影子主体，批注创建端点同步复用。
- 顶栏用户名：`TaskQueuePage` 顶栏右侧以 `.portal-user` 样式显示登录用户名（超长省略，title 提示完整名）。
- 验证：后端 `test_annotator_auth` + `test_portal_internal_api` **93 passed**（新增审批建映射/映射保留、缺映射保存自愈 2 个回归）；BFF **23 passed**（新增 me 路由测试）；标注员前端 **76 passed**（新增 App 会话恢复 2 例、顶栏用户名 1 例）、tsc 与生产构建通过。
- 部署与活体验证：重建并重启 `annotator`、`annotator-frontend` 容器（8443 新资源 index-DJTCKfrH.js，`/portal/auth/me` 无 Cookie 返回 401）；用 BFF 同款服务令牌对活体后端走通样本读取+保存（200），确认 `jingms` 映射自动创建。注意：本地 uvicorn `--reload` 已自动加载后端修复。


## 2026-09-18 标注工作区左侧标签页布局重构

- 需求：把工作区红框内容（标注指南、筛选器+样本列表、批量编辑、回传、批注）集中到页面左侧，做成标签页形式。
- `TaskWorkspacePage.tsx`：新增 `activeTab` 状态（`samples|guide|batch|return|comments`，默认 `samples`）与 `workspaceTabs` 常量；布局改为两列——左侧 `aside.side-tabs`（`role=tablist` 五个 tab 按钮 + 条件渲染的 `role=tabpanel` 面板），右侧 `section.editor` 只保留样本流/浏览编辑主区。原 stream 模式独立指南列、编辑器底部批量编辑、右侧 actions 侧栏全部移入对应 tab；指南移入 tab 后两种模式均可用，删除 `with-guideline` 布局变体。
- `styles.css`：`.workspace-grid` 改为 `300px minmax(0,1fr)` 两列；新增 `.side-tabs`/`.tab-bar`/`.tab(.active)`/`.tab-panel` 样式；`.side-tabs .guideline` 去内边框避免卡片套卡片；清理 `.sample-list`/`.actions` 旧规则与媒体查询残留。
- 测试：`TaskWorkspacePage.test.tsx` 新增 `openTab` 辅助，约 20 个用例按新交互补充标签切换（批注/批量/回传/指南）；"stream 模式指南栏"改为"指南标签页"，模式切换用例改为验证两种模式下指南 tab 均可用。
- 验证：标注员前端 **76 passed**、tsc 与生产构建通过；已重建部署 `annotator-frontend` 容器（8443 新资源 index-Dd59Ls8a.js），浏览器活体冒烟确认五个标签渲染与切换正常、控制台无错误。

## 2026-09-18 标注工作区纵向导航与样本流布局重构

- 需求：五块功能改为左侧纵向导航栏（类似算法平台侧边导航）；移除浏览模式，仅保留样本流；右侧主区按"样本数据字段横向排列 → 标签 → 操作条（上一条/下一条等）"从上到下排布。
- `TaskWorkspacePage.tsx`：删除 `WorkspaceMode` 类型、`mode` 状态与"浏览全部/返回样本流"切换按钮；侧栏改为 `aside.side-tabs` 内 `nav.tab-rail`（`role=tablist aria-orientation=vertical`，五项：样本/指南/批量/回传/批注）+ 右侧条件渲染面板；新增 `openSamplesPanel()` 供汇总页"打开样本列表"跳转；快捷键与 `advanceStream` 去除模式判断。
- `SampleStream.tsx`：`onBrowseAll` prop 改名 `onOpenSamples`；标注字段改为 `field-cells` flex-wrap 横向小卡片网格；`.stream-sample` 改单列，主区顺序为数据字段 → 标签编辑 → 底部操作条。
- `styles.css`：`.workspace-grid` 改 `420px minmax(0,1fr)`；新增 `.side-tabs`（`104px` 纵向导航 + 面板区两列）、`.tab-rail .tab(.active)` 纵向导航按钮样式；新增 `.field-cells`/`.field-cell` 字段卡片样式；删除全部 `.field-row` 旧规则。
- 测试：模式切换用例替换为"stream-only 模式 + 纵向导航面板切换"；`SampleStream.test.tsx` 更新 prop 与按钮名（"浏览全部"→"打开样本列表"）；**76 passed**、tsc 与生产构建通过。
- 部署与活体验证：重建 `annotator-frontend` 容器（8443 新资源 index-CD4GRxIl.js）。活体验证链路：jingms 密码未知 → 创建测试账号 `layout-smoke`（active + 项目授权 + 任务 'as' 指派，`temp_test/create_smoke_annotator.py`，注意 SQLite 中 UUID 为 32 位无横线存储、SQLAlchemy UUID(as_uuid=True) 列必须传 `uuid.UUID` 对象）；浏览器验证全部通过——左侧纵向导航五项及面板切换、顶栏无"浏览全部"、右侧字段网格→标签→操作条顺序、指南/批量/回传/批注面板正常、控制台无错误。
- 临时数据：两枚铸造会话（jingms/layout-smoke）已删除；`layout-smoke` 账号及其任务 'as' 指派保留用于后续验收（如需删除：主平台"用户管理→标注员管理"删除账号即可，或运行 `temp_test/cleanup_sessions.py` 同目录脚本扩展）。

## 2026-09-19 标注工作区手风琴导航与批量勾选整合

- 需求（用户四点）：①左侧导航点击后面板在按钮**正下方**展开（手风琴式）；②"全选当前页"及样本勾选移入"批量"面板；③右侧数据改进显示样式便于查看区分；④以 jingms/12345678 活体验证。
- `TaskWorkspacePage.tsx`：侧栏改手风琴结构——`workspaceTabs.map` 渲染 `div.tab-item`（tab 按钮 + `activeTab === key` 时面板在其下方），移除"104px 导航 + 右侧面板"两列结构；样本面板只保留搜索/筛选/样本导航按钮/分页（复选框与 `.sample-selection` 包装全部移除）；批量面板新增"全选当前页"复选框、`.batch-samples` 当前页样本勾选列表、"已选择 N 条样本"计数，与既有标签列/标签值/覆盖/应用控件整合。
- `SampleStream.tsx`：字段展示由 `field-cells` 卡片改为 `field-table` 表格（表头"字段/值"两列、`td.field-name`/`td.field-value` 分列）。
- `styles.css`：`.side-tabs`/`.tab-rail`/`.tab-item` 改单列手风琴；`.side-tabs .tab-panel` 加边框底色；新增 `.batch-samples`（max-height 280px 纵向滚动、`overflow-x: hidden` 防横向滚动）与 `.batch-sample-id`（`overflow-wrap: anywhere; min-width: 0`）；新增 `.field-table` 表格样式（斑马纹、标注字段组青绿高亮表头/字段名列）；删除 `.field-cells`/`.field-cell`/`.values p` 残留规则；`.workspace-grid` 侧栏 420px→360px。
- 测试：`TaskWorkspacePage.test.tsx` 四处批量用例改为先 `openTab('批量')` 再勾选；"纵向导航"用例新增"样本面板无全选/勾选、批量面板有"断言；**76 passed**、tsc 与生产构建通过。
- 部署与活体验证：重建部署两次（最终 8443 资源 index-YTmV6zr2.js / index-CynRGhPC.css，含批量面板横向滚动条修复）。jingms 已有任务 'as' 指派（`temp_test/ensure_jingms_assignment.py` 确认，无需新建）；浏览器以 jingms/12345678 验证全部通过——手风琴式五导航面板下方展开、样本面板无勾选、批量面板勾选列表完整、右侧表格（字段/值表头+斑马纹+高亮）→标签→操作条、控制台无新增 JS 错误，截图三张（样本面板/批量面板/表格特写）。
- 追加（同日）：`.side-tabs` 加 `position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow-y: auto`，左侧导航栏固定悬浮不随页面滚动，面板过长时侧栏内部滚动。部署 8443（index-jnd5RnGz.css），浏览器验证通过：滚动 800px 后左侧栏仍完整悬浮、批量面板展开时侧栏内部滚动且其余导航按钮可点（截图 scroll-verify-sidebar-sticky.png / batch-panel-expanded.png）。
- 追加（同日第二轮，三点需求）：①"样本"面板移除编号样本列表（`samples.map` 按钮块删除），只留搜索/筛选/分页，样本切换统一走右侧流式"上一条/下一条"，样本 ID 仍可在"批量"勾选列表查看；汇总页按钮改名"筛选样本"。②`.workspace-grid` 侧栏 360px→280px 统一变窄。③`SampleStream.tsx` 字段表改 `.field-grid` 多列紧凑卡片（`repeat(auto-fill, minmax(190px,1fr))`，字段名小字在上/值加粗在下，标注字段组青绿高亮），替换 `.field-table` 两列表格。测试：6 处样本按钮点选改用"下一条 →/← 上一条"（`moveNext` 与列表点选等价），"纵向导航"用例改为断言样本面板无列表；**76 passed**、tsc/构建通过。部署 8443（index-DZaGvPNw.js），浏览器验证通过（注意：需刷新页面加载新 bundle，否则旧 JS 渲染旧结构）。
- 追加（同日第三轮，四点需求）：①样本分页（上一页/第 N 页/下一页）移入"批量"面板顶部，样本面板只留搜索+筛选；②左侧导航改**多开手风琴**——`activeTab` 单值改 `openTabs: ReadonlySet`，tab 点击只打开不切换关闭，各面板头部加"收起"按钮独立关闭（指南面板除外）；③④根因是任务创建数据而非门户渲染：聚类弱监督路径 `LabelSchemaEditor` 空白未预填契约列且新增列默认 `required: false`。修复：`LabelSchemaEditor.add()` 默认 `required: true`；`DataAnnotationPage.tsx` 聚类 schema 编辑器预填 `genericAutoSchema`/冻结输出契约列（machine_key/value_type/required），手动任务路径也默认必填。
  - 测试：`TaskWorkspacePage.test.tsx` 5 处适配（分页断言移至批量面板上下文、`chooseUserLabelSchema` 改为直接保存预填 schema、纵向导航用例新增多开/收起/分页位置断言），annotator **76 passed**；主平台 `LabelSchemaEditor.test.tsx` 两处 required 断言更新、`DataAnnotationPage.test.tsx` `chooseUserLabelSchema` 简化，**61 passed**；修复分支既有 `weekAcceptance.test.ts` 清单失登（补 `ClusterPreviewPanel.test.tsx`，week 4 `CustomNode.test.ts` 与 week 12 `.tsx` 为两个真实文件非重复），**7 passed**；双端 tsc/构建通过。
  - 数据手术：jingms 活跃分配指向任务 584ae2cc（'as'，schema 103d5ad1，label 列 `int/required=0`）——`temp_test/surgery_task_as_required.py` 将 `label_columns.required=1` 并同步 `task_snapshot.label_schema.columns[0].required=true`，验证通过；最新任务 f606991a 已是 fault/int/必填（无需处理）。
  - 部署与活体验证：annotator-frontend 重建部署 8443（index-CNqoUy17.js），浏览器以 jingms/12345678 验证四点全部通过——①样本面板无分页、批量面板顶部有分页；②样本/指南/批量三面板同时展开、批量收起后其余保留；③指南显示"label · 整数 · 必填"；④标签输入框 type=number 与 int 契约匹配。
- 追加（同日第四轮，三点需求）：①导航面板格式统一——移除面板内 panel-head 双重标题（样本/批量编辑/回传/批注 h2）；②tab 改**点击展开/再次点击收起**（toggle）——`openPanel` 点击改 `togglePanel` 切换 Set 成员，删除四个面板的"收起"按钮与 `closePanel`（`openSamplesPanel` 程序化打开保留只开不切语义）；③侧栏再变窄 `.workspace-grid` 280px→**220px**，`.tab-panel` padding 12px→10px，删除 `.panel-head`/`.panel-collapse` 样式。
  - 运维：一次部署事故——在 ml-platform 目录跑 `npx vite build` 因 cwd 错误失败，但 docker build 复用旧 dist 仍"成功"，8443 hash 未变；须在 annotator/frontend 目录构建后确认 dist 新 hash 再 docker build。
  - 测试与验证：`TaskWorkspacePage.test.tsx` 垂直导航用例重写为 toggle 断言（无收起按钮、再点同一 tab 收起且其他面板保留、样本默认开再点关闭），**76 passed**、tsc/构建通过。部署 8443（index-CBAzxZv8.js），浏览器验证①②通过（无标题行/收起按钮、toggle 与多开正常）；③线上 CSS 确认 `220px minmax(0,1fr)` 且无 panel-head 规则——子代理测得 652px 系其视口 ≤1080px 触发既有单列响应式（`@media (max-width:1080px)` 侧栏全宽），宽屏下即 220px。
- 追加（同日第五轮，四点需求）：①导航样式统一——`GuidelinePanel` 删除头部（h2"标注指南"+折叠按钮），指南面板与样本/批量/回传/批注格式完全一致（面板内无标题、内容直出）；styles.css 删 `.guideline-head`/`.side-tabs .guideline` 特例，`.guideline` 改纯内容网格（装饰由外层 `.tab-panel` 提供）。②指南折叠按钮已随①移除（`GuidelinePanel.test.tsx` 折叠用例改为"无按钮+内容直出"断言）。③**批量分页独立化**——新增 `batchSamples/batchPage/batchPageCursors/batchNextCursor` + `loadBatchPage`（独立 generation 防竞态），批量面板分页/全选/勾选列表全部改用批量状态；初始/筛选变化时批量页与右侧流同步重置为第一页，右侧样本流（samples/selected/moveNext 翻页）不再受批量翻页影响。④`.field-grid` `minmax(190px,1fr)`→`minmax(150px,1fr)`，一行容纳更多列。
  - 测试与验证：`TaskWorkspacePage.test.tsx` 'replaces pages via next_cursor' 重写为 'pages the batch checklist independently without moving the stream sample'（断言批量列表换页且右侧 `category-s-1` 不变、`category-s-2` 不出现）、'keeps selections across pages' 改等 `选择样本 s-2`、指南相关断言 `标注指南`→`任务说明`；**76 passed**、tsc/构建通过。部署 8443（index-B6Py_PRu.js），浏览器活体验证：①②④ PASS（指南无标题/按钮、格式统一；批量翻页右侧保持"第 1/50 条"不变、上一页返回第一页）；④线上 CSS 确认 `minmax(150px,1fr)`（子代理 699px 窄视口 <760px 触发单列响应式致误报 1 列，宽屏生效）。
- 追加（同日第六轮，三点需求）：①导航顺序「指南」移到第一位（workspaceTabs：指南/样本/批量/回传/批注，默认展开仍为样本）。②批量面板分页按钮缩小匹配小控件格式（`.pagination button` padding 3px 10px、12px 字号、`.pagination` 12px 文字）。③左侧导航栏样式重设计——tab 按钮改圆角胶囊（transparent 背景/边框、hover 浅灰、激活浅青绿背景 #e3f1f0 + 边框 #b7d8d5 + **左侧 3px 青绿指示条** inset box-shadow、0.15s 过渡），`.tab-rail` gap 8→4、`.tab-item` gap 8→6、`.tab-panel` 加左右 4px 内缩进。
  - 验证：annotator **76 passed**（在 annotator/frontend 目录）、tsc/构建通过、weekAcceptance 7 passed；部署 8443（index-Drb2J2HF.js），浏览器活体验证三点全部 PASS（tab 顺序、分页按钮 3px 10px/12px、导航视觉含指示条）。注意：在 ml-platform 根目录跑 vitest 会因 workspace 配置致 annotator 测试全挂（43 failed）与 weekAcceptance 4 failed——**必须分别在 annotator/frontend 与 frontend 目录运行**。
- 追加（同日第七轮，两点需求）：①导航默认展开第一项「指南」——`openTabs` 初始值改 `workspaceTabs[0][0]`（guide）。②解答"保存标签"按钮作用（无需改码）：`SampleStream` 标签输入框下方的「保存标签」仅保存当前样本标签并停留在当前样本（onSave），与底部操作条的「保存并下一样本」（onSaveAndNext，保存后自动推进）互补，前者适合改完复查、后者适合连续标注流。
  - 测试适配：默认开面板由样本改指南后，3 个用例更新——'renders every frozen schema field'/'shows the guideline tab' 去掉 `openTab('指南')`（toggle 语义下再点会关闭默认开的指南），垂直导航用例改为断言默认指南开、样本未开，再 openTab('样本') 验证多开与收起；**76 passed**、tsc/构建通过。部署 8443（index-CGrawXE4.js），浏览器验证 PASS（指南默认展开激活态、其余未展开、toggle 正常）。
- 追加（同日第八轮，一屏布局需求："整个页面显示在一个屏幕内不需要滚动查看"）：工作区页改为**视口锁定布局**——`.workspace`（portal-page.workspace）`height:100vh; overflow:hidden; display:flex; flex-direction:column`，topbar `flex-shrink:0`，`.workspace-grid` `flex:1; min-height:0; align-items:stretch`，`.editor` `overflow-y:auto; min-height:0`（样本数据在编辑区内部局部滚动），`.stream-footer`（底部操作条）`position:sticky; bottom:0` 白底上边框始终可见；`.side-tabs` 在此布局下改 `position:static; max-height:100%`（不再需要 sticky）。≤760px 窄屏单列时 `grid-template-rows: minmax(0,auto) minmax(0,1fr)` + side-tabs `max-height:45vh` 保持一屏（数据区仍内部滚动）。
  - 验证：**76 passed**、tsc/构建通过；部署 8443（index-CvhWsaLy.js / CSS index-f4kwVJWj.css）。浏览器活体验证两轮误报后第三轮确认生效：workspaceH=718=viewport、editorScroll 1849>clientHeight（内部滚动）、操作条无需滚动可见——**前两轮失败系浏览器子代理停留在未刷新旧页面（三次数值完全相同），需关闭旧标签新开导航重测**。窄视口（699px）下编辑区高度仅 153px 偏挤，用户宽屏（>760px 双列）正常。
- 追加（同日第九轮，通知栏迁移+用户区重设计）：①移除 App 层外挂的"站内通知 0"顶栏（`App.tsx` 不再渲染 `NotificationInbox`），改为**铃铛按钮**——SVG 铃铛 + 未读红色徽章（unread>0 才显示），aria-label 保留 `站内通知（N 条未读）` 格式（测试兼容）。②`NotificationInbox.css` 重写：`.notification-inbox` 改 relative，`.notify-bell` 36px 圆形图标按钮（激活态青绿），`.notify-dropdown` absolute 右对齐 380px 白卡阴影 z-40。③用户区重设计（两页统一）：`.user-chip` 胶囊（青绿首字母圆形头像 `.user-avatar` + 用户名 `.portal-user`）+ `.ghost-btn` 小号退出按钮（hover 红）。④`TaskQueuePage` topbar-actions = 铃铛+用户胶囊+退出；`TaskWorkspacePage` 新增 props `username/onLogout/onOpenNotification`，topbar-actions = 快捷键+状态+铃铛+用户胶囊+退出。
  - 测试：`TaskQueuePage.test.tsx`/`TaskWorkspacePage.test.tsx` 补 `vi.mock('../api/notifications')`（两页现在渲染 NotificationInbox）；`App.test.tsx` mock 已有无需改；NotificationInbox aria-label 未变故组件测试全兼容。**76 passed**、tsc/构建通过。部署 8443（index-pyFWEcvf.js），浏览器验证两页全部 PASS（无独立通知横条、铃铛下拉展开/收起、用户胶囊 J+jingms+退出、工作区右上角完整）。

## 2026-09-21 后端 9 个预存测试失败修复（迁移账目与契约基线）

- 背景：全量后端套件 1978 passed / 8 failed（--lf 定位共 9 个失败），全部为迁移账目过期、测试基线漂移或 Dockerfile 契约过期，与算子元数据改动无关。
- 新迁移：`alembic/versions/20260921_59_saved_annotation_strategies.py`——为 `app/models/labeling.py` 的 `SavedAnnotationStrategy` 补齐缺失建表迁移（autogenerate check 失败根因），遵循 `sa.Uuid()` 约定；down_revision=20260917_58。
- head 账目统一：`tools/evidence_manifest.py` MIGRATION_HEAD、`tools/upgrade_fixture.py` EXPECTED_HEAD、`tools/acceptance/run_upgrade_fixture.sh` --target、`tests/test_database_production.py` HEAD_REVISION、`tests/test_inference_production_stack.py` alembic_head 断言。本轮先统一为 59；随后并行会话新增 `20260921_60_model_version_lifecycle_backfill.py`（model_versions lifecycle 回填）并已将上述账目提升为 20260921_60。
- 测试基线漂移修复（旧修订点用当前 ORM 模型插入 → 新列导致 INSERT 失败）：
  - `test_database_production.py` `_seed_legacy_registry`：ORM `Artifact` 改为 `sa.table()` Core 插入（仅 rev-08 列集，metadata 用 json.dumps），移除未用 import；`source/onnx_artifact_id` 引用改用捕获的 artifact_id。
  - `test_annotation_execution_statistics_migration.py`：ORM `GenericAnnotationTask` 改为 `sa.table()` Core 插入（仅 rev-47 列集，JSON 列显式 `sa.JSON()` 类型），task_id 预生成 uuid4；移除未用 import。注意不能用 `__table__.insert()`（Python 端默认值仍会带上 rev-47 缺失的 name/completion_criteria/due_at 列）。
- Dockerfile 契约更新（`test_image_security_contracts.py`）：四个 Dockerfile 已改为 xgboost/catboost `--no-deps` 单独安装 + sed 剔除后装其余的新 pip 布局，chown 多行块新增 /var/lib/tensorboard 与 /var/lib/ml-platform；断言改为行续行归一化（`re.sub(r"\s*\\\s*\n\s*", " ", content)`，需吃掉反斜杠前尾随空格）后匹配新命令。
- `test_notification_models.py`：head→WEEK9 降级断言由特指 `generic_annotation_tasks` 拒绝消息改为通用 `Refusing destructive downgrade`——链上 45-58 号迁移各自先抛拒绝，特指消息已过期且每次新增迁移都会再碎。
- 验证：image_security+statistics 12 passed；evidence_manifest+week11_12+notification 151 passed（含 57 subtests）；database_production+inference 22 passed 2 skipped；全量套件 1986 passed / 1 failed（即 notification，修复后单文件 8 passed 转绿）。遗留未验证：全量套件未在 20260921_60 链头下完整重跑（与并行会话编辑冲突风险），但 60 号迁移相关的全部 head 账目测试已针对性复跑通过。

## 2026-09-24 Ubuntu legacy CPU 安装包重新整理

- 发布包改为独立的 `packaging/docker-compose.legacy-cpu.yml` 配置层：主线 Compose 继续服务 CI 基线，Ubuntu 包通过 `packaging/compose-ubuntu.sh` 强制使用 CPUv1 MinIO/mc、`0.0.0.0:5175` 公网入口和本地管理端口。Compose `!override` 用于替换而非追加主线端口映射。
- Python 服务使用包内 Debian `python:3.11-slim-bookworm` Dockerfile，移除 Wolfi 和 pip 不支持的 `--resume-retries`；MLflow 改为包内构建。前端使用包内 Debian Node 20 Dockerfile，默认 npmmirror 并带 npm 有限重试；Python 默认镜像源仍可通过 `PIP_INDEX_URL` 覆盖。
- 安装脚本保留已有 `.env`，只补齐公网端口变量，并调用幂等的 `prepare-production-secrets.sh` 创建缺失的通知密钥目录/文件；打包脚本使用 HEAD 归档加当前工作树覆盖，排除 `.env`、`secrets/`、数据库、缓存和依赖目录。
- 验证：WSL Docker 已构建迁移、MLflow、TensorBoard、推理、后端、worker、scheduler 和前端镜像；Compose 合并配置、端口/镜像合同与各 shell 文件语法通过。当前 WSL Docker Hub 对两个 CPUv1 MinIO 标签返回 `pull access denied`，因此目标机必须预加载同名镜像或配置可访问的批准仓库；目标 Ubuntu 主机上的完整 `up`、健康检查和外网访问仍需在目标环境执行。

## 2026-09-30 主平台模型导出/模型库命名/自动标注策略与标注员门户五项修复

- 模型库导出 not found 修复：前端 `ml-platform/frontend/src/api/modelExports.ts` 与 `ModelLibraryPage.tsx` 原调用后端不存在的 `POST /api/projects/{id}/model-exports`（缺 `Idempotency-Key`、字段 `export_kind/include_annotation` 不符、轮询 `ready` 状态），全部对齐后端真实契约：`POST /api/model-versions/{versionId}/exports`（幂等键 `createUuid()`），轮询 `completed/failed`，`GET /api/model-exports/{id}/download`；标注包以 `annotation_task_revision: 0` 绑定版本当前策略载荷；e2e `model-export.spec.ts`、`modelExports.test.ts` 与 `ml-platform/docs/api_reference.md` §16.6 同步。
- 模型库注册名加入实验名：`ModelRegistryService._create_automl_registered_model` 命名改为 `{job.name} - {experiment.name} - {算法名}`（无绑定实验时回退旧格式），新增回归 `test_automl_registration_includes_experiment_name_in_model_library`。
- 弱监督"其他兜底值"可选并移至规则/簇映射下方：编辑器新增 `useOtherValues` 开关（缺省开启，向后兼容旧策略库载荷）；后端 `validate_strategy_config` 不再强制每列 fallback（`CLUSTER_FALLBACK_REQUIRED` 仅用于非对象），`apply_annotation_strategy` 无候选且无兜底时落 `needs_review`（provenance source `none`）；`strategyDraftFromTask` 按快照 other_values 回填开关（显式空对象=关闭）。
- 弱监督按簇样本范围收窄：`annotation_concurrency.py` 新增 `annotator_visible_sample_ids` + `frozen_cluster_sample_ids`，`_resolve_assignment_scope` 对 ids 与 frozen_task_scope 两种指派都按最新策略 artifact 的 `cluster_id ∈ selected_clusters` 过滤（全空返回 `SAMPLE_SCOPE_EMPTY_AFTER_CLUSTER_FILTER`），`_refresh_global_annotation_state` 同步收窄；执行 worker `_execution_cluster_filter` 跳过范围外预览样本（不物化、不发布、不计 needs_review），避免部分簇+无兜底配置卡死发布。
- 标注员门户自动标注结果：`GET /api/internal/portal/tasks/{id}/samples` 新增 `label_source`（按当前值对应最新 revision 的 source）；`SampleStream.tsx` 对 automatic 样本显示"自动标注结果"面板并把右侧编辑框标题改为"标注员修改"，标注员保存/批量保存后缓存置 `manual`（服务端 save_labels 本就以 manual revision 覆盖自动值）；枚举严格校验此前已三层齐备（前端 select/chips 仅枚举、服务端 `LABEL_ENUM_INVALID`、发布校验），未改动；顺带修复 `AdminQueuePage` 模式标签键 `auto`→`automatic` 不匹配。
- 验证（本机 Windows，临时 venv `temp_test/export-test-venv`）：后端聚焦套件 `test_model_exports_api+test_model_export_contract` 18 passed、`test_model_registry_service` 19 passed、`test_api_model_registry+test_model_registration_contract` 18 passed+2 subtests、`test_annotation_strategies` 34 passed、`test_annotation_concurrency` 28 passed、`test_annotation_task_state+test_annotation_task_state_api` 97 passed、`test_portal_internal_api` 85 passed、`test_portal_admin_review+test_annotation_return_acceptance+test_async_operation_contract` 65 passed；主平台前端 Vitest 370 passed/19 skipped、`tsc --noEmit`、生产构建通过；标注员门户前端 Vitest 127 passed、tsc、生产构建通过。`git diff --check` 未发现空白错误。
- 边界与未验证项：真实 Redis/Celery 下的异步导出与执行、真实浏览器 e2e（`model-export.spec.ts`、`generic-platform-acceptance.spec.ts` 更新后未重跑 Chromium）和远程 CI 未在本机闭环；标注包的 annotation 策略文件内容来自 `ModelVersion.conversion_metadata["annotation"]`，当前没有任何流程写入该元数据，因此"导出标注包"虽可产出含 annotation 目录的合法签名包，但策略文件为空对象——该数据链路缺口仍是遗留问题；已存在的注册模型名称不回填实验名。

## 2026-09-30 标注包内容链路收口（导出标注包接入弱监督策略血缘）

- 链路：回传验收导出产生的数据版本自带 `parse_contract.task_id` 与 `original_artifact_id`，AutoML 注册的 `ModelLibrary.dataset_artifact_id` 即该 artifact。`app/services/model_export.py` 新增 `resolve_annotation_payload(db, model_version)`：`ModelVersion.source_model_library_id → ModelLibrary.dataset_artifact_id → DatasetVersion(original/normalized_artifact_id, parse_contract.task_id) → GenericAnnotationTask（automatic、弱监督配置完整、同项目）→ 当前修订快照 configuration + 最新 AnnotationStrategyArtifact/Decision`，产出 `{strategy, rules, cluster_method, cluster_artifacts(assignments), cluster_label_mappings}`。
- 打包：`build_export_package`/`create_model_export` 新增可选 `annotation_payload`，非空时替代 `conversion_metadata["annotation"]` 写入 `annotation/*.json`（旧元数据路径保留为回退）；`execute_model_export` 在 `annotation_task_revision` 非空时调用解析器。任一血缘缺失返回 None，导出保持空注解目录而非错误策略。未选中簇样本的 assignments 同样写入，离线 `cli.py annotate` 对无映射样本按 `needs_review` 处理，与平台侧弱监督语义一致。
- 验证：新增 `tests/test_model_export_annotation_lineage.py`（血缘解析 3 正 2 反 + 真实 `execute_model_export` 端到端断言 zip 内注解内容）5 passed；`test_model_export_contract.py` 新增 payload 驱动打包 + 离线 runtime annotate 子进程用例（簇0 映射 ready、簇1 未映射 needs_review）；导出四件套合计 26 passed；`test_annotation_strategies+concurrency+task_state+model_registry_service` 152 passed 无回归。
- 边界：血缘依赖"验收后执行回传导出"产生的数据版本（`parse_contract.task_id`）；直接上传的 CSV 或未导出的验收版本仍解析不到任务，导出标注包退化为空注解目录（保持原行为，不猜测绑定）。真实 Celery 异步与浏览器 e2e 仍未在本机闭环。

## 2026-09-30 标签列机器键随用户输入的标签名称生成

- 现象：新建自动标注任务向导中定义标签列后，保存的 schema、策略配置（other_values/rules/cluster_labels）、回传验收数据版本与"保存到数据管理"导出文件的标签列名都是 `label-1/label-2`。根因有两处：`DataAnnotationPage` 向导预填标签列时丢弃模型输出契约的真实 `machine_key` 改写为 `label-${index+1}`；`LabelSchemaEditor` 新增列固定 `label-${index}` 且机器键只读，用户输入的标签名称不参与键生成。回传验收/导出链路以 `machine_key` 作为标签列名（`annotation_returns.py`），因此错误名称直达数据管理文件。
- 修复：`LabelSchemaEditor` 机器键随标签名称实时生成（去除首尾空白、空白串转下划线；名称清空时保留原键占位），保存时校验键唯一与标识符合法性（`/^[\p{L}\p{N}_][\p{L}\p{N}_-]*$/u`，非法时给出友好报错）；向导预填改用模型输出契约的真实 `machine_key`；后端 `LabelColumnCreate.validate_key` 放宽为 Unicode 标识符 `[\w][\w-]*`（支持中文键，空格/括号等仍拒绝）。既有未改名列保持原键不变，兼容历史 schema 回显与"配置自动标注策略"对话框。
- 验证：`LabelSchemaEditor.test.tsx` 新增中文名生成键、契约键保留、非法名称拒绝三例（12 passed）；`DataAnnotationPage.test.tsx` 61 passed（策略配置键断言改为契约键 `label`）；主平台前端全量 373 passed、tsc、生产构建通过；e2e `generic-platform-acceptance.spec.ts` 期望键改为 `quality`；后端 `test_label_schema(+api)+test_annotation_task_state_api+test_annotation_return_acceptance+test_portal_internal_api` 147 passed。
- 边界：修复仅影响新保存的 schema；既有任务中已绑定的 `label-N` 列不回填改名。真实浏览器 e2e 未在本机重跑。

## 2026-09-30 标注任务创建与管理改进（截止时间预填、统一标签列定义、列说明与字段解释）

- 指派截止时间预填：`AssignmentDialog` 新增 `defaultDueAt`，打开时按任务 `due_at` 填入 datetime-local（本地时间格式化），可修改；未设置截止时间的任务保持空的“可选”提示。
- 手动标注任务标签定义统一：新建手动任务向导移除单字段“标签字段/标签类型/填写指引”表单，改用与自动任务相同的 `LabelSchemaEditor`（标签列定义，每列含名称、类型、约束、列说明，可增删列）；创建任务前必须先“保存 schema”（未保存时创建按钮禁用并提示），任务通过 `label_schema_id` 绑定该 schema，不再内联创建单列 schema。
- 列说明同步到门户指南：列 `instruction` 本已冻结进 `task_snapshot.label_schema`，门户 `GuidelinePanel` 的“标签说明”现渲染该说明；`LabelColumn` 类型补充 `instruction` 字段。
- 字段解释文件：向导新增“字段解释文件”上传（csv/txt/tsv，每行“字段名,描述”，逗号或制表符分隔），前端解析为 `field_descriptions` 并随任务创建提交；后端 `GenericTaskCreate` 新增 `field_descriptions`（键≤256、值≤2000字符、总≤64 KiB，超出 422），写入 `task_snapshot.field_descriptions`，且策略配置更新重建快照时保留；门户任务视图返回 `field_descriptions`，工作区当前样本对匹配列显示“字段名 + 描述 + 数据”，未匹配列仅显示“字段名 + 数据”。
- 验证：主平台前端 375 passed（新增截止时间预填、字段解释解析两例；手动任务两例改为先保存标签列定义）、tsc、生产构建通过；标注员门户 129 passed（新增指南列说明、字段描述匹配/未匹配两例）、tsc、生产构建通过；后端 `test_label_schema(+api)+test_annotation_task_state(+api)+test_annotation_concurrency+test_portal_internal_api+test_annotation_return_acceptance+test_annotation_strategies` 282 passed（新增字段说明快照保留与校验、门户返回字段说明两例）。
- 边界：字段解释文件解析在浏览器端完成（不落后端文件存储）；自动任务向导同样支持上传，字段说明随创建写入快照；真实浏览器 e2e 未在本机重跑。

## 2026-09-30 本地验收环境（WSL Docker）镜像重建：修复"改了代码页面不变"

- 现象：多次修复提交后页面仍显示旧界面（主平台 5173、标注员门户 8443）。排查确认：本地验收环境整栈运行在 WSL Docker Compose（15 个服务，容器当时已运行约 6 小时），主平台/门户前端与后端全部是**镜像内烘焙的构建产物**（无源码 bind-mount），运行中的 `agent_spot_welding-frontend-1` 镜像构建于 2026-09-29 15:23，早于当日 11:02/14:00/14:25 的修复提交，容器 bundle 内检索不到新代码标记。
- 重建流程（可复用）：① 门户前端 Dockerfile 为 `COPY dist`，必须先 `ml-platform/annotator/frontend` 执行 `npm run build` 产出宿主 `dist/`；② WSL 内 `docker compose build backend worker scheduler frontend annotator-frontend`；③ `docker compose up -d` 同样的五个服务（`migrate` 为一次性服务，随 up 重跑；Postgres 数据在卷中不受影响）。主前端 Dockerfile 在镜像内执行 vite 构建，无需宿主预构建。
- 验证：镜像构建与容器重建 exit 0；`backend`/`frontend` 健康检查 healthy、`annotator-frontend` running；主前端容器 `DataAnnotationPage-xuceov2f.js` 含「字段解释文件」「随标签名称生成」标记，入口 bundle 换为 `index-M0jY0FXU.js`；门户容器 bundle 与宿主构建一致（`index-D6o7XDy3.js`）且含「自动标注结果」「field-item-description」；后端容器 `generic_tasks.py` 含 `field_descriptions`（6 处）；`curl :8443` 返回新 bundle，`:8001/api/health` 200。
- 说明：本次仅重建本机 WSL 验收栈；目标服务器（`packaging/install-ubuntu.sh` 发布链路）未同步，如需远端生效须走发布流程。浏览器若仍显示旧页面，需强刷（Ctrl+Shift+R）绕过缓存。

## 2026-09-30 手动标注任务：schema 名称自动派生 + 创建页布局重构

- schema 名称：删除手动向导的「标签 schema 名称」输入框（原先默认值 `labels`、填什么都无实际用途——该字段只在数据库唯一键与预览抽屉的原始快照 JSON 中出现，标注员门户、数据管理导出、前端列表都不展示）。名称改由 `schemaNameForTask(taskName)` 统一派生为 `${任务名称}-labels`，与弱监督任务的既有约定完全一致（服务端同名自动升 version）；保存标签列定义前给出只读提示「保存标签列定义时会自动使用 schema 名称「X-labels」」。评估结论：不使用列机器键（label-1/label-2）代替——schema 是"一组标签列"的集合，用单列键命名任意且与列键语义混淆。
- 布局重构：新建任务向导第 1 步由扁平字段流改为按用途分区（`data-annotation__setup-section` 卡片 + 标题）：数据来源（项目/数据版本）→ 任务信息（任务名称/截止时间）→ 标签设置（手动：标签列定义；自动：模型与标签合同）→ 样本范围与可见字段 → 字段解释 → 任务说明（标注说明/完成标准）。`LabelSchemaEditor` 与字段解释上传从两列紧凑网格移出为整块卡片，避免大组件被塞进网格列；新增分区样式并复用既有 CSS 变量。
- 验证：主平台前端 375 passed（手动任务用例新增分区标题断言与派生名称断言 `name: "Q3 复检任务-labels"`）、`tsc` 无错、生产构建通过；重建 frontend 镜像并重建容器（BUILD/UP exit 0，容器 healthy）；容器内与 HTTP 实测确认新入口 bundle `index-DZTEjlsV.js`、`DataAnnotationPage-CtIk7_bG.js` 含「数据来源/任务信息/标签设置/自动使用 schema 名称」，CSS bundle 含 `setup-section`。
- 边界：浏览器内视觉确认未完成——本地实例 admin 密码非 e2e mock 值，未做密码尝试；分区布局的观感需用户在强刷后确认。既有 `labels` 等历史 schema 记录保留不变。

## 2026-10-03 标注值严格约束 + 自动/人工双结果保留与对照

- 标注值只能选定义值：① 自动任务标签列由模型输出合同的 classes 冻结为 `enum_values`（类型转换+去重+非法项丢弃，`_contract_enum_values`），弱监督策略值同样受 schema 枚举校验；② 主平台标签列定义在标注用途（annotation）下不再提供纯范围约束（历史范围列按「枚举值且范围」回显补齐枚举），训练/推理用途保留；③ 门户 `parseValue` 对 int/float 列补枚举校验（此前仅字符串列有），枚举列 UI 只渲染下拉，未匹配枚举的提交一律拒绝。
- 自动/人工双结果：`GET /portal/tasks/{id}/samples`（标注员）与 `GET /portal/admin/tasks/{id}/samples`（审核员）新增 `automatic_labels`（最近一次 automatic/initialize 修订的冻结值）与 `manual_modified`（当前值≠自动结果）。标注员工作区永久保留「自动标注结果」面板（人工修改后不消失），被修改的列带「已修改」徽标，右侧编辑框标题为「标注员修改（人工结果）」；审核员界面同屏显示人工值+自动值对照与「已人工修改」标记，并提示导出规则。
- 导出取值规则固化：回传批次冻结当前值——有人工修改的列用人工结果，未修改的列用自动结果（自动结果发布后从未被修改时二者相同）。新增回归 `test_return_batch_uses_manual_edits_and_keeps_automatic_values`（真实任务+发布+确认+回传+worker 冻结全链路：frozen-1=manual、frozen-2=auto）。
- 验证：主平台前端 381 passed（编辑器纯范围隐藏/训练保留两用例）、门户 130 passed（双结果面板/已修改徽标）、后端 348 passed（合同类别派生枚举、标注员与审核员双结果返回、回传导出取值规则等新回归）；tsc 与生产构建全绿。
- 部署与排查记录：backend/worker/scheduler/frontend 镜像正常重建生效；`annotator-frontend` 的 `COPY dist` 层遭遇 BuildKit 上下文缓存陈旧 + WSL 代理（127.0.0.1:7897）失效且本地已无 `nginx:1.27-alpine` 基础镜像，无法重新 build。改用 `temp_test/update-portal-image.sh`（容器内替换资源 + `docker commit` + force-recreate）完成更新，容器与 HTTP 实测均为新 bundle（`index-DA8yB9OX.js`，标记 1/1/1）。该方案在代理恢复前可复用；代理恢复后建议走正常 `docker compose build`。

---

## 2026-10-05 AI对话RAG、Chat API发布与知识库自动图谱（按 2026-10-04 技术方案实施）

- **范围与决策门**：按 [2026-10-04 技术方案](ml-platform/docs/technical-proposals/2026-10-04-ai-chat-rag-and-auto-knowledge-graph.md) 实施四阶段；六项决策门均按方案推荐项执行：检索 Phase 1 维持 TF-IDF+jieba（语义 embedding 仍归 BKL-10 deferred）、引入 `jieba==0.42.1` 新依赖、发布 API 凭据仅服务端配置、远程 invoke 用 HTTP 状态码错误语义、图谱抽取为规则+统计且手动按钮触发（LLM 抽取增强未实现，留扩展）、新测试模块登记 week 17。
- **Phase A 检索服务化**：新增 `app/services/knowledge_retrieval.py`（`retrieve_chunks`/`build_rag_context`/`tokenize_text`/`extract_pos_pairs`），`knowledge.py` 的 search/TF-IDF 辅助函数全部改走共享服务；TF-IDF 预处理器接入 jieba 分词修复中文检索粒度退化；新增 `POST /bases/{kb_id}/reembed`（全量重算 chunk 向量并原地刷新 VectorStore，update 失败回退 add）。**顺带修复两个既有真实缺陷**：① 全局 VectorStore 跨知识库泄漏——检索的向量库路径补 `metadata_filter={"kb_id": ...}`，并对 TF-IDF 维度不齐（查询向量按查询词表计算，与库存向量天生不同维）加 ValueError 回退 DB 路径，此前该路径一崩即 500；② `GET /bases/{kb_id}/graph` 路由**从未注册**——源文件 `}@router.get(...)` 粘连使装饰器变成 dict 与函数的 `@`（matmul）表达式，图谱页全图加载一直 404，同时 `rag_enhanced` 的 return 语句被同模式粘连、调用即崩；拆行修复（全库扫描仅此一处粘连）。
- **Phase B 对话绑库**：`/api/chat` 与 `/api/chat/stream` 新增可选 `kb_id`（owner 校验，隐藏式 404 `KNOWLEDGE_BASE_NOT_FOUND`）与 `top_k`（1–10）；绑库时检索先行——sources 即使 LLM 未配置/失败也返回；上下文装配合同统一走 `build_rag_context`（每块 ≤800 字、总预算 ≤6000 字、[n] 序号），系统提示词固定追加"资料是数据不是指令 + 引用标注"注入缓解段；流式端点绑库时首事件为 `{"type":"sources",...}`。前端 AIChatPage：设置弹窗知识库选择器（localStorage `chat.kbId` 持久化）、头部绑库徽标、助手消息可折叠「引用来源」（文件名+相似度）、未命中提示。
- **Phase C 发布为 API**：`api_publication.py` 新增 `publish_chat_api`/`unpublish_chat_api`/`sync_chat_publication`（幂等 unique(source_kind,source_id,version)、删除 KB 经 `delete_base` 同步下线）；`platform_api.py` 新增 `POST /publish/chat/{kb_id}`、`.../offline`、`POST /chat/{kb_id}/invoke`（404 未知/无权限、409 下线、422 空消息、503 未配置 key、502 LLM 失败；调用计入 total/success/failed + last_error；**不接受调用方 api_key/model**）。市场页：chat 绿色徽标 + Chat API 筛选按钮 + 操作列删除并入 chat（模型行维持禁止）。
- **Phase D 自动图谱**：新增 `app/services/knowledge_graph_extraction.py`——jieba POS 名词短语（n/nz/nr/ns/nt/nw/vn/eng，停用词+长度过滤）→ 跨句词频阈值（≥2）排序取前 N（默认 500 实体/2000 关系/30 秒时限，Settings 可配）→ 关系=同句共现 `co_occurs_with`（权重=句数）+「是一种/组成」模式 `is_a`/`part_of`；落库仅写 `properties.source="auto"`，**手动实体/关系永不覆盖**，重跑幂等（先清 auto 层再重建）；实体类型按 POS 映射（nr→person 等）。新增 `POST /bases/{kb_id}/graph/extract`（可选 doc_ids 子集）。图谱页「自动抽取」按钮 + 抽取结果 toast + 实体列表「自动/手动」徽标（`/graph` 端点本就返回 properties）。
- **测试登记**：新建 `test_chat_api_publication`（9 用例：幂等发布/市场可见/非属主 404/未发布 404/下线 409/空消息 422/未配置 503+失败计数/mock LLM 成功路径+sources+成功计数/删库同步下线+市场删除）登记 week 17；`test_api_chat` 7→11（绑库 sources 在无 key 时也返回、未知库 404、流式 sources 首事件、不传 kb_id 合同不变）；`test_knowledge` 10→12（reembed+中文检索、抽取 auto 层+手动保留+重跑幂等+properties 透传、空文档 422）；前端 `AIChatPage.test.tsx` 新建（4 用例）登记 weekAcceptance 17；`APIMarketplacePage`（Chat 徽标/筛选/删除）、`KnowledgeGraphPage`（自动抽取）用例扩展。
- **验证**：后端 `test_api_chat`+`test_knowledge`+`test_chat_api_publication` **33 passed**；相邻回归 `test_api_platform`+`test_api_workflow_publication`+`test_engine_vector_store`+`test_suite_manifest` **35 passed**；`test_demo_loop`+`test_app` **23 passed**；前端 AIChatPage/KnowledgeGraphPage/APIMarketplacePage/weekAcceptance **22 passed** + `tsc --noEmit` + `npm run build` 通过（仅既有 chunk 体积警告）。环境说明：本机 `python` 别名失效（WindowsApps stub），测试统一经 `.venv/Scripts/python.exe`（3.11.9）执行；jieba 装入项目 venv。
- **未验证/遗留**：① LLM 成功路径仅在单测内 mock（本机与 CI 均无 `LLM_API_KEY`），真实模型回答质量、引用标注效果未实测——部署环境需冒烟；② 浏览器端到端（绑库对话→发布→远程 curl→自动抽取）未执行，属部署后验证；③ 图谱抽取的共现关系是统计信号（`co_occurs_with` 诚实命名），语义精度依赖后续 LLM 增强（未实现）；④ 旧知识库需手动执行一次 reembed 恢复中文检索质量；⑤ 工作区另有非本次改动（`demo_loop.py` 修改、`closed_loop_actions.py` 未跟踪）保留未动；⑥ 全部改动未提交。
- **收口补全（同日，用户要求"完全按照技术方案"后继续补全）**：逐条审计方案差异并全部收口——① `retrieve_chunks` 预留 `embedding_provider` 参数位（协议 `embed(texts)->vectors`，传入即替换 DB 路径的 TF-IDF 计算，为 BKL-10 语义 embedding 留真实接缝）；② 图谱实体归一化补 NFKC 全半角折叠；③ 新增 `knowledge_graph_max_extract_chars`（默认 200k），抽取选区超量返回 422 引导 `doc_ids` 分批；④ AIChatPage 发布成功 toast 附市场跳转链接（antd message 渲染在 Router portal 外，用普通锚点）；⑤ `api_model.py` 列注释补 chat；⑥ Chat API 名对齐方案为 `{kb.name} 对话`；⑦ 图谱 canvas 增加 mousemove 悬停提示（名称/类型/自动·手动/出处文档数）并同步实体列表。**测试缺口补齐**：空知识库无命中降级（`kb_warning`+纯 LLM）、抽取实体上限截断标记、超文档量 422、前端绑库改为设置弹窗真实交互断言 localStorage 持久化。**验证**：后端聚焦 36 passed（api_chat 12 + knowledge 15 + chat_api_publication 9）；前端 23 passed + tsc + build；alembic `upgrade head`+`check` 在全新 SQLite 双通过（历史 dev 库未触碰）；**真实 uvicorn HTTP 验收流 SMOKE PASS 15/15**（注册→建库→传文档→reembed→中文检索→绑库对话（本地 mock LLM 真实成功路径，回复含引用+sources）→发布 Chat API→市场可见（名称"冒烟知识库 对话"）→远程 invoke 成功+计数→自动抽取→auto 层→删库→API 自动下线；脚本 `temp_test/smoke_chat_rag_api.py` 可复跑）。`run_suite` 全量：week 1–11 在 `test_week12_security_gates` 处 300s 超时中断（npm audit/网络型模块，本机环境块，与本次改动无关），其余周分周重跑见后续记录；仍遗留：week12 模块与浏览器 UI 验收以部署/CI 环境为准。
- **收口验证终态（同日续）**：① 补 A2"jieba 可关闭"——新增 `retrieval_use_jieba` Settings 开关（关闭即回退旧分词，配合 reembed 使用），聚焦套件复跑 36 passed；② `run_suite` 全量按周执行：week 1–11、13、17 全部 PASSED（27 个模块零 FAILED/零 ERROR；week 14–16 尚无登记模块），**week 12 `test_week12_security_gates` 本机 environment-blocked**（300s/600s 双档超时挂起，子进程网络依赖，模块未被本次改动触碰，以 CI 为准）；③ 真实 uvicorn HTTP 验收流 **SMOKE PASS 15/15**（含 mock LLM 真实成功路径与远程 invoke 计数）。至此 2026-10-04 技术方案的全部实现差异与验证缺口（除浏览器 UI 验收与 week12 环境块项）均已收口；改动未提交。

---

## 2026-10-08 AI对话RAG/Chat API/自动图谱 部署验证收口

- **镜像构建**：docker 代理失效（127.0.0.1:7897 不可达）+ 容器内大文件下载停滞 → 新增 `wheelhouse/` 离线安装方案：WSL 宿主侧经阿里云镜像源 `pip download` 全量 141 个 wheel（含 jieba sdist），`Dockerfile`/`Dockerfile.worker` 的 pip 层改为 `--mount=type=bind,source=wheelhouse + --find-links /wheels --index-url ${PIP_INDEX_URL}`（wheelhouse 缺省时回退镜像源，CI 构建行为不变；`PIP_INDEX_URL` 默认阿里云可 build-arg 覆盖）。backend/worker/migrate/frontend 四镜像全部构建成功。期间 WSL 磁盘满（49G 83%）一次，`docker builder prune` 回收 8G 后通过。
- **部署验证（backend 容器内执行 `temp_test/deploy_smoke_chat_rag.py`）**：**DEPLOY-SMOKE PASS 18/18**——health、OpenAPI 7 条新路由、注册/登录、建库、传文档、reembed、中文检索、绑库对话（无 LLM key 时 sources 仍返回的确定性路径）、发布 Chat API（名称「UI验证知识库 对话」）、市场可见、远程 invoke 503 CHAT_LLM_NOT_CONFIGURED + 失败计数、自动抽取、auto 层+关系、删库 API 自动下线、市场清理。本地 mock-LLM 成功路径由 `temp_test/smoke_chat_rag_api.py` 15/15 覆盖（上一轮）。
- **部署环境既有问题修复（与本次功能无关但阻塞验证）**：① compose 补齐 postgres/redis/minio/worker `restart: unless-stopped`（此前 postgres 等停掉后无人拉起，backend DNS 解析失败 crash-loop；该状态在验证开始前已存在 34h+）；② `nginx.conf` upstream 改 `resolver 127.0.0.11 valid=5s` 动态解析 + `set $upstream` 变量（静态 `upstream` 在 daemon 重启重建容器后缓存旧 IP，UI 全部 502）。
- **未解决的环境既有问题**：WSL VM 与 dockerd 周期性重启（dockerd 每 40s–数分钟被 `systemctl restart`，`.bash_history` 显示用户此前已排查过同一现象）。它反复打断浏览器 UI 验证与长请求。UI 已验证部分：登录页、AI对话页新元素（未配置徽标/绑库前禁用的「发布为 API」/配置弹窗含「知识库（RAG）」选择器与提示文案）渲染正确（截图确认）；完整点击流（选库→保存→对话→发布→市场 Chat 筛选→图谱自动抽取按钮）待环境稳定后按 `temp_test/deploy_smoke_chat_rag.py` 的 18 步在浏览器复跑即可。
- 验证账号：`ui_verify_01`（部署库内，验证用知识库「UI验证知识库」kb_id 2695a7e2-10af-4ec0-afe3-ad656c426369）。改动未提交部分：`docker-compose.yml`（重启策略）、`nginx.conf`（动态解析）、`Dockerfile`/`Dockerfile.worker`（wheelhouse）、`.gitignore`（wheelhouse 排除+keep）。

---

## 2026-10-09 闭环去演示化命名 + 闭环四个真实缺陷修复 + 数据卷持久化收口

- **背景**：用户反馈「闭环演示点击开始演示报错500」「这不是演剧本，我需要的是真实的流程」，并要求把页面名称从演示/demo 改为正式名称、修复后真实浏览器验证、检查镜像重建后数据丢失问题、推送 GitHub。
- **数据恢复与根因**：MinIO 命名卷切换期间历史文件丢失（全部 dataset/model 工件 FILE_MISSING，部署 11 的模型文件缺失 → 预测 500）。恢复链：`labeled_features_demo.csv`（46 行 × 74 列真实数据）→ 重建重训数据集工件 → 触发真实 AutoML 重训（7 组试验，extra_trees 最优 score=1.0）→ 注册+批准+换模。
- **缺陷 1（绑定冲突）**：`experiment_automl_bindings` 以 `experiment_id` 为主键（实验↔AutoML 任务 1:1，手动 API 重复绑定即 409），闭环按 `{名称}-自动建模-{error_count}` 复用同名实验时绑定插入 UniqueViolation；且重训幂等指纹含实验名，同名会重放旧任务。修复：方案 A（`demo_loop.py`）与方案 B（`serving_operators.py` retrain_threshold 算子）实验/任务名均追加周期 token（uuid hex[:8]），每轮重训独立实验（兼顾审计血缘）。
- **缺陷 2（once-ever 换模守卫）**：`_swap_to_best_model` 以 `swapped_model_version_id` 非空为早退守卫，但该字段同时是前端换模水印、`reset()` 不清除——首次换模后闭环永远不再换模。修复：删除该守卫（上游 `refresh_retrain_status` 的 retrain_status 迁移已保证每个完成任务只换一次），水印每轮覆盖为新版本 id。回归 `test_07b_second_completed_job_swaps_again`。
- **缺陷 3（运行时换模不生效）**：运行时规格与 `WeightedTargetRouter` 都从最新 stable revision 的 target 取模且 revision/runtime_key 不可变，而 `complete_retrain_swap` 只改 `deployment.model_version_id` → 运行时永远尝试加载旧模型（本轮表现为 MODEL_ARTIFACT_INTEGRITY_FAILED，部署 observed_state=failed），闭环换模只在进程内回退生效。修复：`complete_retrain_swap` 轮换 revision（旧 stable → superseded，新建 stable revision + target 指向新版本，strategy=immediate），幂等条件为最新 stable 已指向该版本；提交后 best-effort `start()` 加载运行时。回归 `test_07c_swap_rotates_stable_revision_target`。
- **缺陷 3b（运行中 start() 不加载新别名）**：`InferenceDeploymentService.start()` 对 running/running 部署直接早退，新 revision 的别名 key（`{revision}:{version}`，即闭环预测路由键）永远不会加载 → DEPLOYMENT_NOT_READY → 静默回退进程内。修复：早退分支补 `_load_stable_aliases`（同身份 load 为运行时 no-op，安全）。回归 `test_start_while_running_loads_new_stable_alias`。
- **缺陷 4（幂等重放重复 approve）**：同一 job 重放换模时对已批准版本再次 approve 报 MODEL_VERSION_STATE_CONFLICT。修复：`approval_status != "approved"` 才执行 approve。
- **验证**：后端 `test_demo_loop`(16) + `test_inference_deployment` + `test_api_workflow_publication`(6) + `test_all_operators` + `test_inference_production_stack` = **119 passed, 2 skipped**；前端 DemoLoopPage/OrchestrationPage 9 passed。真实环境：重训任务 860a7f7c 完成（7 候选 joblib 全部真实上传 MinIO），部署 11 恢复 **running**，revision 3 stable → 模型 2e23837d（LightGBM v1），运行时按路由键 `c2639b33:2e23837d` 真实加载 ONNX 并对真实行返回预测 [0]；浏览器（页面上下文真实 token）3 次逐行调用 `/demo-loop/predict` 全部 200 无 500。
- **命名去演示化**：导航「闭环自动化」（i18n zh/en）、页面标题「推理-回流-重训 自动化闭环」、按钮「开始演示→启动闭环」「回放中→运行中」、卡片「数据回放→逐行推理调用」、大屏标题「闭环自动化运行大屏」与「模式：模拟」、后端审核任务指令文案、DB 现有配置名与报错数据集名（SQL UPDATE）、`DemoLoopConfig.name` 默认值、手册（路由地址 /demo-loop、按钮名、大屏章节、参数速查）全部更新；页面/接口路径 `/demo-loop` 保留（内部标识，非用户可见名称）。
- **数据持久化收口（用户点名复查）**：compose 的 postgres/minio 改挂命名卷 `postgres-data`/`minio-data`（此前匿名卷随容器重建丢失全部数据——本次 500 的上游根因）；实测 `docker compose up -d --force-recreate postgres minio` 后 projects/users/闭环配置/工件/部署状态全部完好，重建后全链路预测通过。redis 仍为匿名卷（仅缓存/broker，无用户数据）。全容器挂载审计完成，无其他匿名卷承载用户数据。
- **未验证/遗留**：① 页面「上传 CSV→启动闭环」的完整点击流未在浏览器执行（IAB 自动化不支持文件选择器；逐行端点已用页面上下文真实 token 验证 200，与页面按钮走完全相同的 API）；② WSL 空闲关停仍会停容器（`docker compose up -d` 恢复，数据卷已安全）；③ 工作树 `ml-platform/backend/wheelhouse/` 离线 wheel 目录保持未跟踪（.gitignore 策略）。

---

## 2026-10-10 工作流算子名称统一（去中英混用）+ 闭环任务列表（多任务 CRUD）

- **算子名称统一**：后端 87 个算子中 7 个（api_input/append_error_dataset/notify_admins/retrain_threshold/load_model_artifact/anomaly_eval/spot_weld_feature_engineering——多为闭环新增）缺 i18n 译名，算子面板回退显示后端英文名，与中文算子混排。修复：zh/en `operator` 映射各补 7 条（重训阈值判断/追加报错数据/通知管理员等）；画布节点 label 原取后端 `op.name`（英文）——OperatorPanel 拖拽载荷携带 `displayName`（当前语言译名），`workflowStore.addNode` 优先采用，画布节点与面板名称一致。
- **闭环任务列表**：`demo_loop_configs` 本就允许一项目多行（无唯一约束，事件 FK 级联），无需迁移。服务层 `list_configs`/`get_config_by_id`/`create_config`/`update_config`/`delete_config`（显式删事件行，不依赖 SQLite/Postgres 级联差异），`save_config` 字段校验抽取为 `_apply_config_fields` 共用。API 新增 `GET/POST /demo-loop/loops`、`PUT/DELETE /demo-loop/loops/{id}`、`POST .../predict|reset`、`GET .../status`；`_config_view` 增补 error_count/alert_count/retrain_status 供列表徽标。**旧端点 `/config|/predict|/status|/reset` 语义不变（首个配置），运行监控大屏兼容不受影响**。
- **前端**：`DemoLoopPage` 重构为任务列表模式——配置卡顶部工具栏（新建按钮）+ 任务列表（名称/回流计数/重训状态徽标/Popconfirm 删除/点击切换），新建草稿模式（表单默认值，按钮变「创建闭环」），切换任务加载各自状态与表单，轮询/预测/重置均按 `loops/{id}` 作用域；运行中禁用切换/新建/删除。API 模块新增 scoped 方法并保留旧函数。
- **修复的竞态（真实 UX bug）**：初次项目加载未完成时点击「新建闭环」，`loadProjectData` 完成回调会把创建状态/表单重置——`loadProjectData` 与选中 effect 完成回调均检查 `creatingRef`，草稿模式期间只更新列表与参照数据、丢弃迟到的选中结果（`loop-task-list` 容器始终渲染，等待它不等于数据就绪）。
- **测试**：后端 `test_15_loop_task_crud`（创建/列表含计数徽标/部分修改不清洗/删除/404）+ `test_16_loop_scoped_predict_status_reset_and_event_cleanup`（scoped 预测命中回流、状态 config_id 一致、重置清零、删除后事件级联清除）——`test_demo_loop` 18 passed；全受影响后端 **121 passed, 2 skipped**；前端 DemoLoopPage 5 用例（列表渲染/任务链接/创建流含必填交互/删除确认/空列表）3 连跑稳定，DemoLoop+Orchestration+OperatorPanel **12 passed**，`tsc --noEmit` 通过。
- **未验证/遗留**：① 画布拖拽节点后的 label 实际渲染未在浏览器自动化中验证（HTML5 drag 事件模拟不可靠，代码路径 displayName→addNode 已由单测间接覆盖）；② 算子 tooltip 描述仍为后端英文描述（属 87 条描述翻译，未在本次范围）；③ 部署后需浏览器验证闭环任务列表与算子面板。

---

## 2026-10-10（续） 闭环任务列表改版为独立表格卡 + 前端缓存头修复落地

- **界面改版（用户反馈"任务列表和配置混到一起，看不清楚"）**：任务列表从配置卡中拆出，独立为全宽「闭环任务」卡（antd Table：任务名称/回流行数/告警次数/自动建模徽标/删除操作；行点击切换、选中行蓝色高亮加粗；卡右上「新建闭环」）；「闭环配置」卡只留表单，标题以蓝色 Tag 标明正在编辑的任务名（新建模式为「新建任务」Tag）。
- **部署链修正**：frontend 容器 nginx 补缓存策略（index.html no-cache + assets immutable），浏览器启发式缓存 index.html 是用户始终看到旧版页面的根因——运行容器已 docker cp 热修生效；Dockerfile 同步改为持久形态并新增 `Dockerfile.prebuilt`（宿主 `npx vite build --outDir html-dist` → 本地 nginx 基础镜像打包，`DOCKER_BUILDKIT=0` 不查 registry），代理故障时用该链路部署（本次即用此链路上线，绕开 node:20-alpine 拉取失败）。
- **测试**：DemoLoopPage 5 用例全过、tsc 通过；真实浏览器回归新建→行切换→删除确认全流程通过（截图确认新布局层次）。
- **待推送**：42b4d8c（手册）、986de12（缓存头）、本次界面改版——本机代理 127.0.0.1:7897 不可达，恢复后推送。

---

## 2026-10-10（续二） 删除推理部署连带清理市场模型 API 行（孤儿行缺陷修复）

- **用户报告**：模型库中删除了所有模型与部署后，API 市场里的"11"仍然存在且无删除按钮。排查确认：市场删除按钮对模型 API 隐藏是设计（模型 API 行是部署的派生数据，生命周期归模型库）；**真实缺陷在部署删除接口**——`DELETE /api/inference-deployments/{id}` 只删部署行，未清理 `platform_apis` 中 `source_kind='model'` 的派生行，残留指向已删部署的 published 孤儿行（生产库已实测复现并手工清理 1 条）。
- **修复**：删除部署时同一事务内删除其市场派生行（`source_kind='model' AND source_id=部署id`）。回归 `test_12_deployment_delete_cleans_marketplace_row`：创建部署→启动（市场行自动发布）→运行中删除被 409 拒绝→停止→删除成功→市场行清零；test_api_model_registry 12 passed。
- **附注**：用户删除部署 11 前已通过任务列表删除了闭环任务（部署删除会导致闭环配置失去部署引用，属预期）；孤儿行清理后市场不再显示"11"。代理仍不可达，相关提交待推送。

---

## 2026-10-10（续三） 闭环自动建模多数据集合并+回流自动标签、大屏实时修复

- **用户报告三问题**：① 选「自动化闭环-报错数据」重训报"目标列 fault 不在重训数据集中"，且期望多数据集合并+回流数据自动打标签；② 大屏实时模式只在连接时刷新一次；③ 大屏「已调用/正常通过」应为推理条数而非 API 调用数。
- **多数据集重训（迁移 20261010_68）**：`demo_loop_configs` 新增 `retrain_dataset_artifact_ids` JSON（单列保留并同步首项，存量回填）与 `total_count`。API/服务层接受多选（校验逐个在项目内、去重保序）；`trigger_retrain_job` 多数据集按选择顺序合并，**物化为「…-合并数据集」新工件**作为 job 输入（worker 只读单数据集，直接取第一个会特征列不一致——本轮真实环境复现 AUTOML 输入列缺失）；多数据集列体系不同时**取列交集保行数**（否则并集列 NaN 全行被 drop_rows 策略丢弃，实测 52 行全丢）；回流元数据列 prediction/confidence 剔除防标签泄漏；标签混合数值与字符串做数值归一。
- **回流自动标签**：回流行落盘时自带目标列（`retrain_target_column`=预测类别，新建工件列随首行生成；`append_rows_to_dataset_artifact` 支持列演进——新键扩展 CSV 列，老行留空）；历史回流文件无目标列时，trigger 合并阶段用 prediction 列补齐（整列缺失则整列生成）。
- **计数语义**：`total_count` 每行推理 +1（reset 一并清零），状态/列表返回——「已推理=total，正常通过=total-error」。
- **连带缺陷修复（真实环境复现）**：① 审核任务幂等键 `demo-loop-review-{config}-{alert_count}` 在 reset 计数归零后重放撞历史任务唯一键 → IntegrityError 未捕获 → predict 500 且 PG 事务中止吞掉后续重训触发——键加周期短码，捕获列表加 IntegrityError（先 rollback 再降级为事件）；② 大屏指标渲染走 rAF 缓动，页面后台/未聚焦时 rAF 暂停数字冻结——applyLiveStatus 改直写 DOM。
- **大屏实时模式重构**：新增闭环任务下拉（项目切换联动加载）；轮询改 scoped `/loops/{id}/status`（旧单任务端点固定返回首个配置，多任务下看到的可能不是正在跑的任务——"连接后不再更新"的根因之一）；首连只同步计数与事件水位线（不回放全历史动画），此后新事件驱动动画。
- **验证**：后端 113 passed（新增 test_17：多数据集触发→合并工件 12 行/标签补齐/prediction 不进特征/计数 3）；真实环境（用户项目 test112）：报错行预测→回流(10行)→告警→审核任务创建→多数据集合并重训 **completed**→换模（swapped 9e95f7f8）；大屏两标签页指标实时同步（已推理/正常通过=真实行数）。
- **环境**：WSL 重启循环一次（栈反复重启），保活进程恢复；前端经 Dockerfile.prebuilt 链路部署。

---

## 2026-10-10（续四） 站内通知滚动 + 闭环配置弹窗化（新建/编辑）

- **站内通知（用户反馈"一屏显示不开"）**：通知面板列表区限高 `55vh` 滚动（overflow-y auto），不再整屏展开。
- **闭环配置弹窗化（用户反馈"配置不需要默认展开，新建时再弹出；列表任务支持编辑"）**：配置表单从页面常驻卡片移入 Modal——「新建闭环」打开创建弹窗（默认值预填），任务表每行新增 ✎ 编辑按钮打开该任务的编辑弹窗（预填当前值）；原配置卡位置改为「当前任务」摘要卡（部署/类别/阈值/重训配置一览 + 编辑配置入口）；「启动闭环」不再隐式保存表单（配置一律经弹窗显式保存）。删除了 creatingRef 草稿竞态守卫（弹窗模式天然隔离）。runDemo 逻辑简化。
- **测试**：DemoLoopPage 6 用例重写（含弹窗新建流/行内编辑流/摘要卡断言"配置表单默认不展开"），NotificationCenter 5 用例通过，tsc 通过；浏览器实测：编辑弹窗预填→改名保存→列表更新→弹窗关闭、新建弹窗打开/关闭、通知面板滚动样式（maxHeight 55vh + auto）。

---

## 2026-10-10（续五） 闭环卡片任务标识与同名任务区分

- **用户问题**：多任务时「逐行推理调用」「闭环状态」卡片看不出绑定哪个任务。改进：两卡标题加当前任务名 Tag（未选择显示「未选择任务」）；任务表新增「创建时间」列（后端 `_config_view` 补 created_at/updated_at），同名任务可按时间区分。浏览器实测：双同名任务列表带时间列、切换行后卡片标签与摘要卡跟随。
