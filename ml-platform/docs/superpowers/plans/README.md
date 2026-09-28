# 实施计划索引

> 更新时间：2026-09-28。当前执行入口是 Week 13–17 计划；本索引只负责告诉读者哪一份计划有效，具体状态以顶层 DEVELOPMENT_PLAN.md 为准。

## 当前执行计划

| 文档 | 范围 | 状态 | 使用规则 |
|---|---|---|---|
| [2026-09-24 Week 13–17 云原生与数据探索开发计划](2026-09-24-week13-17-development.md) | Kubernetes 基础、Job/Pod、Notebook、镜像、GPU、多集群、资源治理；Week 17 决策门 | active | 当前主要开发入口；按 Week 13 → 17 顺序执行 |
| [2026-09-28 Week 13 Kubernetes 基础接入实施计划](2026-09-28-week13-kubernetes-foundation.md) | Week 13 集群登记、凭据引用、命名空间、资源组、节点发现、连通性检查 | planned | Week 13–17 计划 Task 1 的细化执行入口；迁移修订号以本计划为准（`_61` 已被占用） |
| [2026-09-28 Week 14 Kubernetes 执行闭环实施计划](2026-09-28-week14-kubernetes-executor.md) | Week 14 Job/Pod 提交、状态、日志、取消、超时、回收、恢复 | planned | Week 13–17 计划 Task 2 的细化执行入口；前置 Week 13 收口 |
| [2026-09-28 Week 15 Notebook、镜像与 GPU 实施计划](2026-09-28-week15-notebooks-images-gpu.md) | Week 15 Notebook 会话、镜像目录、构建决策门、GPU 资源类 | planned | Week 13–17 计划 Task 3 的细化执行入口；构建路径受 Task 0 约束 |
| [2026-09-28 Week 16 多集群与资源治理实施计划](2026-09-28-week16-multi-cluster-governance.md) | Week 16 路由、存储绑定、配额/并发/成本、用量监控 | planned | Week 13–17 计划 Task 4 的细化执行入口；单集群兼容为硬门禁 |
| [2026-09-28 Week 17 数据探索与质量报告实施计划](2026-09-28-week17-data-exploration-quality.md) | Week 17 只读查询、质量 profile、报告 Artifact | 决策门控 | Week 13–17 计划 Task 5 的细化执行入口；Task 17.0 决策门未全批不得越过 |
| [2026-09-15 通用平台一致性实施计划](2026-09-15-general-platform-conformance.md) | 通用 AutoML 与数据标注方案的跨模块一致性、运行态和发布证据 | in_progress | Week 13–17 不得破坏其合同；Task 14 收据仍是独立发布门禁 |
| [2026-09-02 通用自动建模与数据标注平台实施计划](2026-09-02-general-automl-annotation-platform.md) | Task 1–14 的具体文件、接口和测试 | in_progress | 前置合同和剩余 Task 的唯一实现依据 |
| [2026-09-15 API 管理与应用编排统一实施计划](2026-09-15-api-management-and-orchestration-combined.md) | API 管理先于应用编排 | in_progress | 与 Week 13–17 并行时保持 API-first 顺序，不把编排当作 API 目录 |

## 已完成或已替代的计划

这些文件保留原文用于追溯，不再作为新代码的执行入口。

| 文档 | 归档原因 |
|---|---|
| [2026-08-19 AutoML 详细报告](2026-08-19-automl-detailed-report.md) | 文件自身标记全部步骤 completed |
| [2026-08-19 AutoML 结果注册](2026-08-19-automl-result-registration.md) | 历史组件计划；实现与验证记录已并入当前开发计划归档 |
| [2026-08-19 数据标注任务列表](2026-08-19-data-annotation-task-list.md) | 历史页面计划，已由通用平台入口合同替代 |
| [2026-08-19 实验与 AutoML 一对一](2026-08-19-experiment-single-automl.md) | 历史数据模型计划，状态以归档快照为准 |
| [2026-08-20 数据标注任务重构](2026-08-20-data-annotation-task-redesign.md) | 已被 2026-09-02 通用平台计划取代 |
| [2026-08-22 Week 9–12 验收收口](2026-08-22-week9-12-acceptance-closure.md) | Week 9–12 已完成并进入历史验收归档 |
| [2026-08-26 全部任务列表](2026-08-26-all-task-lists.md) | 已完成的历史列表统一计划 |
| [2026-08-26 统一列表表格](2026-08-26-unified-list-tables.md) | 已完成的历史 UI 统一计划 |
| [2026-08-27 工作台实时统计](2026-08-27-dashboard-realtime-stats.md) | 已完成的历史仪表盘计划 |
| [2026-08-27 统一任务删除确认](2026-08-27-unified-task-delete-confirmation.md) | 已完成的历史交互计划 |
| [2026-08-27 弱监督兜底规则](2026-08-27-weak-supervision-fallback-rule.md) | 已完成并纳入通用标注合同的历史计划 |
| [2026-08-28 手动标注状态](2026-08-28-manual-annotation-status.md) | 已完成的显示层计划；不改变后端原始状态 |
| [2026-08-31 多标签与标注员门户](2026-08-31-multilabel-annotation-annotator-portal.md) | 文件自身标记为历史归档，已由通用平台计划取代 |

## 已合并的子计划

| 文档 | 现行归属 |
|---|---|
| [2026-08-28 API 管理完成](2026-08-28-api-management-completion.md) | 作为历史子计划，执行入口改为 2026-09-15 API 管理与应用编排统一计划 |
| [2026-08-28 应用编排完成](2026-08-28-agent-orchestration-completion.md) | 作为历史子计划，必须等待 API 管理门禁后再执行 |

## 历史状态台账

- [2026-09-24 当前计划前的完整快照](../../../../DEVELOPMENT_PLAN.history-2026-09-24.md)：保留 2026-09-23 及之前的完整执行记录。
- [2026-09-03 之前的计划归档](../../../../DEVELOPMENT_PLAN.history-2026-09-03.md)。
- [2026-08-23 之前的计划归档](../../../../DEVELOPMENT_PLAN.history-2026-08-23.md)。

## 仓库级参考计划

- [产品优化方案（去除大模型能力版本）](../../../../OPTIMIZATION_PLAN.md)：2026-07-23 的候选方案，仅作历史背景；其 Week 13–17 内容由当前计划重新拆分，Label Studio 按 2026-08-18 决策保持延后，不作为当前执行入口。

## 维护规则

1. 新开发只修改当前执行计划和顶层 DEVELOPMENT_PLAN.md；历史计划不回写新状态。
2. 每周门禁完成后，先在顶层台账记录状态、SHA、测试和未验证范围，再把已完成的详细记录追加到日期归档。
3. 计划、实现、聚焦测试、真实运行、浏览器和远程发布收据分别记录；缺少任一必需门禁不能写成 completed。
4. Week 17 的 pending_decision 在获得产品范围、数据权限、审计、隔离和成本确认前保持不变。
