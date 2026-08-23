# 汽车焊接工业 AI 平台开发计划

> 文档状态：当前进度与未完成任务
> 更新日期：2026-08-23
> 项目目录：`E:\codex_workspace\agent_spot_welding`

## 1. 使用规则

- 开发前读取本文件、`AGENTS.md`、共享经验文档和验收计划。
- PowerShell默认使用PowerShell7，docker默认使用wsl中docker。
- 不覆盖用户已有修改，不使用 `reset`、`checkout` 等破坏性回退。
- `passed`、`failed`、`cancelled`、`skipped`、`blocked` 分开记录；未执行不算通过。
- 只有代码、测试、真实运行证据、文档和远程门禁全部满足时，任务才可标记完成。
- Week 9-12 的执行顺序以 [`ml-platform/docs/superpowers/plans/2026-08-22-week9-12-acceptance-closure.md`](ml-platform/docs/superpowers/plans/2026-08-22-week9-12-acceptance-closure.md) 为准。
- 历史记录已归档到 [`DEVELOPMENT_PLAN.history-2026-08-23.md`](DEVELOPMENT_PLAN.history-2026-08-23.md)，本文件只保留当前决策所需信息。

## 2. 总体进度

| 范围 | 当前状态 | 说明 |
|---|---|---|
| Week 1-8 | 已完成 | 已合并到 `main`，保留原有远程交付证据。 |
| Week 9 | 进行中 | 生命周期、Redis fail-closed 已通过；需在当前 SHA 重新绑定远程安全/Chromium 证据。 |
| Week 10 | 进行中 | 角色矩阵、四通道通知已通过；需在当前 SHA 重新绑定远程证据。 |
| Week 11 | 运行态已通过 | 固定资源性能、真实备份恢复、代表性数据 N-1 均已通过；等待当前 SHA manifest。 |
| Week 12 | 进行中 | 当前 SHA 镜像已重建；等待新远程 full run 的安全/Chromium artifacts 和最终 manifest。 |
| Week 9-12 总体 | 进行中 | 不得因远程 CI 全绿或合同测试通过提前关闭。 |

## 3. 当前冻结基线

- 源代码 SHA：`2356388f21001e23d8f157d74fcd183946053c74`
- 分支：`main`
- 远程 full run：待当前 SHA 推送后重新运行
- WSL Docker Engine：`29.7.2`
- Docker Compose：`5.4.0`
- 资源 envelope：4 vCPU、8 GiB；当前 WSL 可见内存约 7.76 GiB
- 平台数据库：`ml_platform`
- MLflow 数据库：`mlflow`，与平台数据库隔离
- 当前 SHA 业务镜像：已冷构建，需提交后按完整 SHA 重建并刷新 receipt
- Week 11 工具与合同测试：`104/104 OK`

## 4. 未完成任务

### W11-R1：固定资源真实性能

状态：`passed`

要求：

- 隔离栈在 4 vCPU / 8 GiB 下持续运行整个负载窗口。
- `core-read`、`warm-inference`、`enqueue` 各执行 iteration 1/2/3。
- `cold-model-load` 执行 iteration 1。
- `welding-e2e` 执行 iteration 1，10 个请求全部为 `completed`。
- 生成所有原始 JSON 和 `performance/summary.json`。
- summary 的 `status=passed` 且 `candidate_status=passed`，提交 SHA 与当前基线一致。

证据：`temp_test/week11-12-live/evidence/performance/summary.json`；上一轮 `2e53c1b` 已通过。当前提交需重建镜像并复跑，确保证据绑定最终 SHA。

### W11-R2/W11-R3：真实备份恢复与 N-1 升级

状态：`passed`

证据：`backup/restore-result.json`、`upgrade/result.json`、`upgrade/smoke.json`。结果均为 `status=passed`，恢复包含行计数、FK、15 个对象 SHA-256、RTO/RPO；N-1 包含双 head、seed、两次升级和 `alembic check`。

### W12-R1：最终 evidence manifest

状态：`open`

必须包含并通过：

- `environment.json`
- `performance/summary.json`
- `backup/restore-result.json`
- `upgrade/result.json`
- `security/summary.json`
- `playwright/result.json`
- `security/runtime-images.json`

运行 `evidence_manifest.py`，所有状态、哈希、提交绑定和安全门禁必须通过；任何 `skipped` 不得改写为 `passed`。

### W12-R3：最终状态和发布决策

状态：`open`

只有 W11-R1、W12-R1 及当前 source SHA 绑定全部通过后，才能：

- 更新 `PLATFORM_STATUS.md` 和本文件为完成。
- 生成最终验收报告和 manifest 链接。
- 确认工作区没有未纳入发布的 Week 12 修改。
- 执行发布、推送或合并操作。

## 5. 当前阻断与下一步

1. 推送 `2356388` 到 GitHub `main`，等待当前 SHA full run 完成。
2. 下载并校验新 SHA 的 security summary、Chromium result、四镜像扫描和 runtime provenance。
3. 按完整 SHA 重建隔离镜像；复跑 W11-R1/W11-R2/W11-R3，保留原始 JSON。
4. 运行 `evidence_manifest.py`；失败时修复真实证据或阻断原因，不手改结果。
5. manifest 通过后更新 `PLATFORM_STATUS.md`、本文件和最终验收报告，再确认远程 SHA 与本地一致。

## 6. 当前证据位置

- WP0 环境证据：`temp_test/week11-12-live/evidence/`
- W11-R2 实测结果：`temp_test/week11-12-live/evidence/backup/restore-result.json`
- W11-R3 实测结果：`temp_test/week11-12-live/evidence/upgrade/result.json`
- 验收执行计划：`ml-platform/docs/superpowers/plans/2026-08-22-week9-12-acceptance-closure.md`
- 历史远程全量门禁：Actions Run `32569941915`（旧 SHA，仅作历史参考）
- 当前性能结果：`performance/summary.json`（待最终 SHA 复跑）

## 7. 文档维护

每次执行后只更新本文件的当前状态、未完成任务、阻断和下一步；历史问题、已解决问题和旧状态保留在归档文件及共享经验文档中，不在当前计划中重复展开。
