# 通用自动建模与数据标注平台当前开发计划

> 文档状态：仅汇总未完成、待验证、风险和已延后工作。
> 文档更新日期：2026-09-03
> 当前工作树：`E:\codex_workspace\agent_spot_welding\.worktrees\general-automl-annotation-20260902`
> 当前分支：`general-automl-annotation-20260902`

## 1. 使用规则

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
| [通用自动建模与数据标注平台实施计划](ml-platform/docs/superpowers/plans/2026-09-02-general-automl-annotation-platform.md) | Task 1–14 的文件边界、接口、测试和依赖 | `planned` |
| [通用平台验收矩阵](ml-platform/docs/acceptance/2026-09-02-general-platform-acceptance-matrix.md) | 19 项验收编号、执行上下文和证据责任 | `planned` |
| [通用化迁移基线清单](ml-platform/docs/migrations/2026-09-02-genericization-inventory.md) | 去行业化迁移盘点与门禁 | `planned` |
| [导出与离线运行时清单](ml-platform/docs/acceptance/2026-09-02-export-runtime-checklist.md) | 导出包和离线推理输入合同 | `planned` |

## 4. 项目阶段状态

| 阶段 | 工作范围 | 状态 | 当前口径 |
|---|---|---|---|
| Week 1–12 | 已交付的平台基础、生产化、权限通知与历史验收 | `passed` / `completed` | 已归档，不作为当前待办。 |
| 通用自动建模与数据标注平台 | 2026-09-02 实施计划 Task 1–14 | `planned`（未开始开发） | 方案、实施计划和验收资料已准备；尚未开始代码、迁移、测试或运行时工作。 |
| Week 13 | Kubernetes 基础接入 | `planned`（未开始） | 后续工作，见 BKL-04。 |
| Week 14 | Kubernetes Job/Pod 执行器 | `planned`（未开始） | 依赖 Week 13，见 BKL-05。 |
| Week 15 | Notebook、镜像与 GPU | `planned`（未开始） | 依赖 Kubernetes 基础能力，见 BKL-06。 |
| Week 16 | 多集群与资源治理 | `planned`（未开始） | 依赖 Week 13–15，见 BKL-07。 |
| Week 17 | 数据探索、质量报告、标注审核与数据回流 | `pending_decision` | 待产品范围确认，见 BKL-08、BKL-09。 |
| Week 18 | RAG 与工业智能体 | `deferred` | 暂时搁置，见 BKL-10。 |
| Week 19 | LLM 网关与 AIHub | `deferred` | 暂时搁置，见 BKL-11。 |
| Week 20 | 全产品验收、交付与培训 | `deferred` | 暂时搁置；不影响通用平台 Task 14 的独立验收。 |

## 5. 当前主交付计划

所有 Task 仍为 `planned`，且尚未开始开发。文档评审、历史局部功能或 Week 1–12 验收均不构成实现完成状态。按依赖执行，不得跳过 Task 1 的去行业化基线。

| ID | 工作项 | 依赖 | 状态 |
|---|---|---|---|
| Task 1 | 全项目去行业化迁移基线 | 无；阻塞后续实现 | `in_progress` |
| Task 2 | 数据导入、数据版本和统一输入合同 | Task 1 | `planned` |
| Task 3 | AutoML 四种任务类型和训练合同 | Task 1、Task 2 | `planned` |
| Task 4 | 标签 schema、类型校验和修订历史 | Task 1、Task 2 | `planned` |
| Task 5 | 标注任务状态机、任务列表和预览 | Task 2、Task 4 | `planned` |
| Task 6 | 三种自动标注策略和特征重要性加权 KMeans | Task 3、Task 4、Task 5 | `planned` |
| Task 7 | 标注员独立认证、主体映射和服务边界 | Task 1、Task 2、Task 4 | `planned` |
| Task 8 | 指派、重叠样本并发、自动保存和回传锁 | Task 4、Task 5、Task 7 | `planned` |
| Task 9 | 回传结果列表、数据管理验收和站内通知 | Task 4、Task 5、Task 8 | `planned` |
| Task 10 | 模型候选手动注册和模型库生命周期 | Task 2、Task 3、Task 4、Task 5 | `planned` |
| Task 11 | 模型导出包和离线 `predict`/`annotate` | Task 2、Task 3、Task 6、Task 10 | `planned` |
| Task 12 | 主平台和标注员门户前端 | Task 5、Task 7、Task 8、Task 9、Task 10、Task 11 | `planned` |
| Task 13 | 异步 worker、幂等、恢复、清理和安全门禁 | Task 2、Task 5、Task 7、Task 8、Task 9、Task 10、Task 11 | `planned` |
| Task 14 | 全量验收、文档同步和发布门禁 | Task 1–13 | `planned` |

### 当前执行入口

1. 从 Task 1 的引用盘点、迁移边界和 RED 测试开始。
2. Task 2 完成后，Task 3 与 Task 4 可以并行；其余任务按上表依赖推进。
3. 每个 Task 的精确文件、接口、RED/GREEN 步骤和命令以实施计划为准；本文件不创建平行的实现步骤。
4. Task 14 必须在实现完成后的新 SHA 上重新生成证据，不能复用归档中的 Week 9–12 运行态制品。

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

- 通用平台尚未开始业务实现。迁移、运行时测试、构建、浏览器验收、导出验证、恢复演练、提交、推送和远程门禁均不能记为已完成。
- Task 1 必须先完成全项目行业特定引用盘点和迁移边界，禁止向新代码继续引入固定行业字段、路由、服务或工作流。
- 自动标注、认证、回传、导出和清理都涉及跨服务状态；每个 Task 需保留幂等、revision、权限和失败回执的测试证据。
- 对恢复、备份、升级和安全验收，脚本路径存在不等于可执行：必须记录容器/宿主机边界、环境变量、证书、Compose 服务、镜像和证据目录。
- Windows 产生的 CRLF shell 文件不能直接作为 WSL runner 的语法或运行结论；以 Linux/CI checkout 或独立 LF 副本为准。

## 9. 文档维护与本次整理记录

- 每次 Task 完成后，在本文件更新当前状态、未完成项、风险和下一步；完成明细、旧失败和历史证据追加到归档，不回写旧事实。
- 2026-09-03：将整理前的完整 `DEVELOPMENT_PLAN.md` 保存为 `DEVELOPMENT_PLAN.history-2026-09-03.md`。Week 1–12 及历史执行记录已从当前视图分离。
- 2026-09-03：从 `DEVELOPMENT_PLAN.history-2026-08-23.md` 回收尚未实现的工作流、数据治理、SSO、云原生、数据探索、RAG/AIHub 和优化候选，并按 `planned`、`pending_decision` 或 `deferred` 进入第 7 节。
- 2026-09-03：没有提升任何业务状态；通用平台 Task 1–14、遗留验证项和 backlog 均保持未完成状态。
- 2026-09-03：用户确认 Week 1–12 已完成，Week 13–16 未开始，Week 17 待定，Week 18–20 暂时搁置；同时确认通用自动建模与数据标注平台实施计划尚未开始开发。当前汇总据此更新，不将任何计划或文档工作记为实现完成。
- 2026-09-03：整理顶层 `README.md`，补充以 PowerShell 7 为默认宿主环境的本地启动、测试、构建和 WSL Docker Compose 入口；明确历史行业化文档的参考边界，并标明通用平台 Task 1–14 仍为 `planned`。本次仅完成文档整理，未执行通用平台代码、迁移、测试或运行时验收。
- 2026-09-03：启动通用平台 Task 1。已建立 `GenericAnnotationTask`、通用 `/api/annotation-tasks` 与 `/api/automl-tasks` 入口、旧点焊创建入口的结构化 `410 GENERIC_API_REQUIRED` 边界、旧质量运行迁移适配器、初始去行业化盘点和契约测试；当前状态为 `in_progress`。由于 Python 3.14 环境缺少 `fastapi`/`httpx`，聚焦测试和完整 manifest 验证尚未执行通过，不能提升为 `passed`。
- 2026-09-03：Task 1 修复轮次补充通用任务 Alembic revision `20260903_15`、显式 `X-Request-ID`/`Idempotency-Key` 和 Pydantic 请求合同、旧运行迁移的 run/project/actor 授权、并发幂等回读、源样本/修订/快照元数据及稳定 checksum 校验。前端生产导航和旧服务彻底去行业化仍是 Task 1 remaining，未标记完成；测试仍受后端依赖缺失阻断。
- 2026-09-03：本地分支整理的详细记录为：任务范围仅限本地 Git 分支引用；依据 `git branch --merged main`、祖先关系和工作树占用安全删除 16 个已被 `main` 完整包含的历史/临时本地分支；保留当前 `main`、链接工作树占用分支和仍有未合并独有提交的分支；未删除远端分支、链接工作树或缓存/未跟踪文件。验证结果为本地分支从 23 个减少到 7 个，`main`、`origin/main` 与当时基线一致；后续清理需用户明确指定范围。
- 2026-09-03：按用户要求发布本次变更：功能分支提交 `f29191ba8980f0066a98b8dd8af26e70890d78d2` 已推送到 `origin/general-automl-annotation-20260902`；随后与根 `main` 的分支整理提交合并为 `f6c8bff64458f305f1568f67ab3f8479983431f4` 并推送到 `origin/main`。README 未加入任何提交，仅在本地工作树和根 `main` 工作树同步保留。
- 2026-09-03：发布前验证记录：README 以外的工作树变更已提交并推送，`git diff --check` 退出码为 0；后端标准套件因 `python` 命令仅指向 WindowsApps 占位符、Python 3.14 环境未安装 `fastapi`，前端因缺少 `node_modules` 未执行测试和构建。上述环境缺口不计为测试通过，也不改变通用平台 Task 1–14 的 `planned` 状态。
