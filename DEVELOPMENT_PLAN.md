# 当前开发计划

> 更新时间：2026-09-24。本文档是当前状态台账；完整历史执行记录已保存到 [2026-09-24 归档快照](DEVELOPMENT_PLAN.history-2026-09-24.md)。最近开发重点是 Week 13–17，详细实施步骤见 [Week 13–17 云原生与数据探索开发计划](ml-platform/docs/superpowers/plans/2026-09-24-week13-17-development.md)。

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
| 通用平台 Task 14 | in_progress | 当前 SHA 的完整收据链、远程门禁和发布判断仍需独立收口 | 按 2026-09-15 通用平台一致性计划执行 |
| Week 13 | planned | Kubernetes 集群、命名空间、资源组、节点发现、凭据引用和连通性检查 | 先完成 Task 0 决策与 Week 13 基础门禁 |
| Week 14 | planned | Kubernetes Job/Pod 执行器、状态、日志、取消、超时、垃圾回收和恢复 | 依赖 Week 13 |
| Week 15 | planned | Notebook、镜像目录/构建、GPU 资源类和配额 | 依赖 Week 13–14 |
| Week 16 | planned | 多集群路由、存储挂载、配额、并发、成本和资源监控 | 依赖 Week 13–15 |
| Week 17 | pending_decision | SQL Lab、数据探索、质量报告及结构化审核扩展范围未确认；多模态 Label Studio 已延后 | 先完成产品决策，不直接编码 |
| Week 18–20 | deferred | RAG、LLM 网关、AIHub、全产品交付不在本轮范围 | 保持搁置 |

## 3. 最近开发计划：Week 13–17

| 周次 | 交付目标 | 主要产物 | 退出门禁 |
|---|---|---|---|
| Week 13 | Kubernetes 基础接入 | 集群登记、credential_ref、命名空间/资源组、节点能力、连通性 API 和管理页 | real/kind 集群只读发现；跨项目访问、失效凭据、超时和审计回归通过 |
| Week 14 | Kubernetes 执行闭环 | Job/Pod manifest、统一 executor、watch/poll、日志 cursor、取消/超时/回收、恢复和任务页 | 幂等、终态不可逆、watch 重连、日志脱敏、重启恢复和真实集群 smoke 通过 |
| Week 15 | Notebook、镜像和 GPU | Notebook 会话、不可变镜像 digest、rootless 构建适配、GPU 资源类和配额 | 不使用 Docker socket；GPU 无设备时明确 skipped；会话/构建权限和密钥回归通过 |
| Week 16 | 多集群与资源治理 | 路由策略、存储绑定、资源预留/释放、配额、并发、成本、集群/节点/Pod/GPU 监控 | 不健康集群排除、配额并发不超卖、存储不能越界、单集群兼容和多集群 smoke 通过 |
| Week 17 | 决策后数据探索 | 推荐 DuckDB 只读查询、质量 profile、报告 Artifact、查询和报告页；Superset 为独立选项 | 只有范围获批才实现；查询只读、限时/限量、项目隔离、审计和报告下载回归通过 |

执行顺序固定为 Week 13 → Week 14 → Week 15 → Week 16 → Week 17。Week 17 的 Label Studio、多模态同步、iframe 和训练数据回流不在当前承诺范围。

详细文件边界、接口、测试步骤、环境和证据要求见 [Week 13–17 计划](ml-platform/docs/superpowers/plans/2026-09-24-week13-17-development.md)。

## 4. 进入条件与横向合同

1. 先完成 Task 0：冻结现有通用平台合同；确认 Kubernetes 测试集群、镜像仓库、凭据引用、GPU 节点可用性和 Week 15 builder 路径。
2. 复用现有项目权限、审计、ArtifactService、DatasetVersion、DurableOperation、Redis/Celery、通知和前端 API client；不另建平行权限或任务状态机。
3. 集群凭据只保存 Secret/credential 引用；工作负载默认禁止 privileged、hostPath、hostNetwork、hostPID、Docker socket 和未批准镜像。
4. 所有写操作提供 X-Request-ID、Idempotency-Key、操作 ID、脱敏错误和可恢复状态；迟到事件不得覆盖终态。
5. ORM 变更必须有 Alembic 迁移、SQLite/PostgreSQL 兼容验证、迁移 head 检查和旧数据保留断言。
6. 每个新后端测试模块登记到唯一周次；每个新前端测试文件登记到唯一周次；不把历史点焊测试重新纳入通用 active suite。

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

## 7. 计划归档索引

- [实施计划索引](ml-platform/docs/superpowers/plans/README.md)：当前、历史、已替代和合并子计划的统一入口。
- [2026-09-24 归档快照](DEVELOPMENT_PLAN.history-2026-09-24.md)：本次压缩前的完整 2026-09-23 及之前记录，原文保留。
- [2026-09-03 归档](DEVELOPMENT_PLAN.history-2026-09-03.md)。
- [2026-08-23 归档](DEVELOPMENT_PLAN.history-2026-08-23.md)。

## 8. 维护记录

- 2026-09-24：归档本文件压缩前的完整历史，新增 Week 13–17 详细开发计划和实施计划索引；当前文档只保留最新状态、依赖、门禁、风险和归档入口。Week 13–16 保持 planned，Week 17 保持 pending_decision；没有因整理文档提升任何实现状态。
- 后续每个周次完成后，先绑定当前 SHA 和实际证据更新本台账，再把详细执行记录追加到新的日期归档；不得用计划文本、历史测试或旧收据宣称完成。
