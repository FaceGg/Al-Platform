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
| Week 9 | 进行中 | 生命周期、Redis fail-closed 已通过；当前候选 SHA 的远程安全和 Chromium 证据待全量重跑。 |
| Week 10 | 进行中 | 角色矩阵、四通道通知已通过；当前候选 SHA 的远程证据待全量重跑。 |
| Week 11 | 进行中 | 固定资源性能、备份恢复、N-1 已在上一 SHA 通过；当前浏览器/CI 修复会产生新 SHA，三项证据必须重新绑定。 |
| Week 12 | 进行中 | 外部隔离栈 `1/1` 已验证 scheduler 并发与真实 `429`；Run `32630148806` 的 Chromium 因测试 skipped 被 fail-closed receipt 正确拒绝，CI 修复待发布。 |
| Week 9-12 总体 | 进行中 | 不得因远程 CI 全绿或合同测试通过提前关闭。 |

## 3. 当前冻结基线

- 源代码 SHA：当前工作区含待发布的 Week 12 浏览器/CI 修复；提交后冻结为新的验收 SHA。最终验收要求 `HEAD == origin/main`。
- 分支：`main`
- 远程 full run：`32630148806` 绑定 `4af516a`，Quality 和生产集成通过；Chromium 因 Week 12 测试 skipped 而 receipt 失败，Week 11-12 verification 因依赖被 skipped。该 Run 不能用于验收。
- WSL Docker Engine：`29.7.2`
- Docker Compose：`5.4.0`
- 资源 envelope：4 vCPU、8 GiB；当前 WSL 可见内存约 7.76 GiB
- 平台数据库：`ml_platform`
- MLflow 数据库：`mlflow`，与平台数据库隔离
- 当前业务镜像：旧 SHA 仅作历史参考；当前 SHA 必须重建四个镜像并刷新 receipt。
- Week 11 工具与合同测试：`104/104 OK`

## 4. 未完成任务

### W11-R1：固定资源真实性能

状态：`rerun_required`

要求：

- 隔离栈在 4 vCPU / 8 GiB 下持续运行整个负载窗口。
- `core-read`、`warm-inference`、`enqueue` 各执行 iteration 1/2/3。
- `cold-model-load` 执行 iteration 1。
- `welding-e2e` 执行 iteration 1，10 个请求全部为 `completed`。
- 生成所有原始 JSON 和 `performance/summary.json`。
- summary 的 `status=passed` 且 `candidate_status=passed`，提交 SHA 与当前基线一致。

证据：`temp_test/week11-12-live/evidence/performance/summary.json`；当前候选变更提交后必须重建镜像并复跑，不复用旧 SHA 结果。

### W11-R2/W11-R3：真实备份恢复与 N-1 升级

状态：`rerun_required`

证据：`backup/restore-result.json`、`upgrade/result.json`、`upgrade/smoke.json`；上一 SHA 均为 `status=passed`，当前候选变更提交后必须重新绑定并验证。

### W12-R1：最终 evidence manifest

状态：`blocked_by_ci_and_sha_refresh`

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

1. 提交并推送当前 CI、Playwright、scheduler 并发合同修复，触发新 SHA 的 `mode=full` workflow。
2. 下载并校验最终 SHA 的 security summary、Chromium result、四镜像扫描和 runtime provenance；不得把 Run `32630148806` 的 skipped Chromium 或后置任务计为通过。
3. 按最终完整 SHA 重建隔离镜像；复跑 W11-R1、W11-R2、W11-R3，保留上一 SHA 原始证据为历史参考。
4. 外部 Week 12 栈必须使用 `INFERENCE_RATE_LIMIT_CAPACITY=5`、`INFERENCE_RATE_LIMIT_REFILL_PER_SECOND=0.01`，并完成四角色、四通道、rollout、部署和真实 `429` 浏览器验收；生产默认限流值不改。
5. 运行 `evidence_manifest.py`；失败时修复真实证据或阻断原因，不手改结果。
6. manifest 通过后更新 `PLATFORM_STATUS.md`、本文件和最终验收报告，再确认远程 SHA 与本地一致。

## 6. 当前证据位置

- WP0 环境证据：`temp_test/week11-12-live/evidence/`
- W11-R2 实测结果：`temp_test/week11-12-live/evidence/backup/restore-result.json`
- W11-R3 实测结果：`temp_test/week11-12-live/evidence/upgrade/result.json`
- 验收执行计划：`ml-platform/docs/superpowers/plans/2026-08-22-week9-12-acceptance-closure.md`
- 历史远程全量门禁：Actions Run `32569941915`（旧 SHA，仅作历史参考）
- 当前性能结果：上一 SHA 的 `performance/summary.json` 仅作历史参考；最终 SHA 必须复跑并覆盖当前证据。

## 7. 文档维护

每次执行后只更新本文件的当前状态、未完成任务、阻断和下一步；历史问题、已解决问题和旧状态保留在归档文件及共享经验文档中，不在当前计划中重复展开。

## 8. 最新执行记录（2026-08-23）

- 外部 Week 12 Chromium 验收在低容量隔离栈完成 `1 passed`；覆盖四角色、项目权限、站内/企业微信/邮件/Webhook、模型注册、ONNX、rollout pause/explicit rollback、部署和真实 `429`。scheduler 每 60 秒会推进 rollout，浏览器合同已改为验证合法状态机、单调推进和最终 `completed@10000`，并对 `ROLLOUT_REVISION_CONFLICT` 读取持久化状态。
- Run `32630148806` 证明 fail-closed receipt 生效：默认浏览器任务运行了 4 个普通 E2E，Week 12 因缺少隔离环境 skipped，receipt 拒绝该结果，Week 11-12 verification 因依赖 skipped。当前 CI 修复会生成密钥、证书和 acceptance Compose 栈，启动 Vite 后设置完整 Week 12 环境再执行浏览器测试，失败时仍上传 JSON receipt。
- 当前未完成项仍为：新 SHA 远程 full workflow、四镜像重建、W11-R1/R2/R3、最终 security/Playwright 制品下载和 W12-R1 manifest。任何旧 SHA、failed、cancelled 或 skipped 证据均不计通过。
