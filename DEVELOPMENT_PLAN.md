# 汽车焊接工业 AI 平台开发计划

> 文档状态：当前进度与未完成任务
> 更新日期：2026-08-24
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
| Week 9 | 进行中 | 生命周期、Redis fail-closed 和生产集成已通过；当前 SHA 的最终安全、浏览器和证据绑定仍待远程验证。 |
| Week 10 | 进行中 | 角色矩阵、四通道通知已通过；当前 SHA 的最终远程证据仍待绑定。 |
| Week 11 | 进行中 | 固定资源性能、备份恢复、N-1 在上一 SHA 通过；当前 SHA 变更后必须重新绑定三项真实证据。 |
| Week 12 | 进行中 | WeCom allowlist 修复已通过创建/发送阶段；上一轮 Chromium 在模型注册阶段因 MinIO 配置不一致返回 `409 MODEL_REGISTRY_FAILED`，`430db19` 已修复并由 Run `32681461233` 验证中。 |
| Week 9-12 总体 | 进行中 | 不得因远程 CI 全绿或合同测试通过提前关闭。 |

## 3. 当前冻结基线

- 源代码 SHA：`430db194e5ecf0932c5ba2e6357c97ab0f2fe955`，当前 `HEAD == origin/main`。该 SHA 包含 WeCom allowlist 和浏览器 fixture MinIO 配置修复；最终验收仍需远程全量门禁和同 SHA 真实证据。
- 分支：`main`
- 远程 full run：当前 `32681461233` 绑定 `430db19`，状态 `in_progress`；上一 Run `32679688421` 的 Quality/生产集成均通过，但 Chromium 以 `MODEL_REGISTRY_FAILED` 失败，Week 11-12 verification 为 `skipped`，不能用于验收。
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

1. 等待并核对 Run `32681461233`：Quality、生产集成、Chromium 隔离 Week 12 和 Week 11-12 verification 必须全部成功；任何 `failed` 或 `skipped` 均保持未完成。
2. 下载并校验 `430db19` 的 security summary、Chromium result、四镜像扫描和 runtime provenance；不得复用旧 SHA 制品，也不得把任何 skipped 作业计为通过。
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
- Run `32632461877` 的 Quality、生产集成均通过，Chromium 失败且 Week 11-12 verification 被 skipped。已验证根因是浏览器 job 缺少 `WEEK12_INFERENCE_INTERNAL_SECRET`，同时把依赖本地 SQLite fixture 的普通 E2E 与外部 PostgreSQL 验收混跑。修复后普通 Chromium 回归在隔离 `5174` 端口 `4/4 passed`，CI 工作流合同 `43/43 OK`，前端测试 `207 passed / 19 skipped`，构建通过；新 SHA 的远程 full run 仍是必需门禁。
- Run `32637496040` 的 Quality、Production integration、Production experiment integration 均为 `success`；Chromium 在标准回归启动阶段失败，因为全新 runner 上 SQLite 与 artifact 路径的父目录尚未创建，隔离 Week 12 因前置 step 失败未执行，Week 11-12 verification 为 `skipped`。修复为在标准回归前显式创建两个隔离目录，并增加工作流合同断言；仍需新 SHA 的远程 full run。
- 当前未完成项仍为：新 SHA 远程 full workflow、四镜像重建、W11-R1/R2/R3、最终 security/Playwright 制品下载和 W12-R1 manifest。任何旧 SHA、failed、cancelled 或 skipped 证据均不计通过。

## 9. 最新执行记录（2026-08-24）

- Run `32676127712` 绑定 `a497757e685838c992deb35f0fd55b74d6c5f95f`。Quality Windows/Ubuntu、Production integration、Production experiment integration 均为 `success`；标准 Chromium 回归日志明确为 `4 passed`。
- 隔离 Week 12 首次执行在创建 WeCom 通知端点时返回 `422`；重试因首次执行已写入持久化模型夹具而在模型版本创建处返回 `409`，后者是重试污染，不是首要根因。Playwright receipt 为 `failed`，Week 11-12 verification 为 `skipped`，因此该 run 仍不计通过。
- 已确认 WeCom 请求 payload、官方 host 和 path 均合法；`422` 来自容器运行时 DNS/SSRF 校验未使用 acceptance Compose 已声明的显式 allowlist。修复为让 WeCom 创建与发送路径使用同一 `notification_webhook_allowlist`，仅在 acceptance Compose 中加入 `qyapi.weixin.qq.com`；生产默认空 allowlist 和官方 host/path 限制保持不变。
- 浏览器断言现在包含响应 body，隔离 Week 12 场景禁用 Playwright retry，避免有持久化副作用的二次运行以 `409` 覆盖真实首错。
- 本地验证：通知/API/CI `79/79`，Week 12 安全门禁 `160 passed / 1 skipped`，evidence manifest `32/32`，前端 `207 passed / 19 skipped`，前端构建通过，Compose 合并配置通过，`git diff --check` 通过。仍需新 SHA 的远程 `mode=full` 证明真实 runner 修复。
- 新 SHA `d192a48` 的 WeCom 修复已通过真实 CI 创建/发送阶段；但隔离浏览器随后在模型版本注册阶段返回 `409 MODEL_REGISTRY_FAILED`。根因是浏览器 job 的宿主 fixture 进程未设置 MinIO artifact backend，向本地路径写入 artifact，而容器后端按 MinIO 读取。当前修复补齐 `ARTIFACT_STORAGE_BACKEND=minio`、`MINIO_ENDPOINT=127.0.0.1:9000`、`MINIO_SECURE=0` 并增加 CI 合同断言，需再次提交和全量重跑。

## 10. 最新执行记录（2026-08-24）

- `d192a48` 的 WeCom allowlist 已生效，但 Run `32679688421` 的隔离 Chromium 在注册模型版本时返回 `409 MODEL_REGISTRY_FAILED`；该 Run 的 Week 11-12 verification 为 `skipped`，不能计入验收。
- 根因是宿主 fixture 与容器后端的 artifact 存储后端不一致：fixture 使用本地路径写入，容器后端从 MinIO 读取。
- `430db19` 已补齐 MinIO backend、endpoint、insecure CI 模式和对应合同断言，并已推送到 `main`。
- Run `32681461233`（SHA `430db19`）当前为 `in_progress`；在该 Run 完成且 W11-R1/R2/R3、最终 manifest 重新绑定通过前，Week 9-12 总体保持 `进行中`。

## 11. 最新执行记录（2026-08-24，Run 32681461233 完成后）

- Run `32681461233` 绑定 `430db194e5ecf0932c5ba2e6357c97ab0f2fe955`，总体 `failure`。Quality（Windows/Ubuntu）、Production integration、Production experiment integration 均 `success`。
- Chromium acceptance 在“Run standard browser regression”失败；日志显示宿主 E2E 继承了隔离栈的 `ARTIFACT_STORAGE_BACKEND=minio` 与 `MINIO_ENDPOINT=127.0.0.1:9000`，但标准 SQLite 回归未启动 MinIO，fixture 上传 artifact 时连接被拒绝。隔离 Week 12 和 Week 11-12 verification 因前置失败均 `skipped`。
- 修复已在工作树完成：标准 Playwright webServer 与 model fixture 强制 `ARTIFACT_STORAGE_BACKEND=local`，CI 标准步骤显式声明 `local`，并加入 workflow 合同断言。外部 Week 12 模式仍使用 MinIO。
- 本地验证：前端 Week Acceptance Vitest `7/7 passed`；TypeScript/Python 语法检查通过；后端 pytest 未能执行，因为当前捆绑 Python 未安装 `pytest`/`PyYAML`，归类为 `skipped`，不计通过。下一步需提交新 SHA 并重新运行 full workflow。
