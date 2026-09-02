# 汽车焊接工业 AI 平台开发计划

> 文档状态：当前进度与未完成任务
> 文档更新日期：2026-08-31
> 验收工作最后更新：2026-08-24（冻结；后续验收仅作为续行记录追加）
> 其后条目：产品开发记录，不改变 Week 9–12 验收冻结状态
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
| Week 9 | 已完成 | 当前 SHA 的生产推理生命周期、Redis fail-closed、滚动发布、限流和运行时治理已通过远程 required jobs 及最终证据门禁。 |
| Week 10 | 已完成 | 当前 SHA 的角色矩阵、审计、模型卡、Outbox 与四通道通知已通过远程 required jobs 及最终证据门禁。 |
| Week 11 | 已完成 | 固定 4 vCPU/8 GiB 性能、PostgreSQL/MinIO 备份恢复和 N-1 升级均在当前 SHA 生成并通过真实证据。 |
| Week 12 | 已完成 | Chromium acceptance、security/runtime-images 和最终 evidence manifest 均在当前 SHA 通过。 |
| Week 9-12 总体 | 已完成 | Run `33363122355` 的六个 required jobs、同 SHA 全部必需制品和 `evidence_manifest.py` 均通过。 |

## 3. 当前冻结基线

- 验收证据代码 SHA：`3752794001c58b91d6a0e5f9c139f5635989a963`；随后仅提交状态文档收口提交 `e7d84d9`，未改变验收代码。
- 分支：`main`
- 远程 full run：`33363122355` 绑定 `3752794001c58b91d6a0e5f9c139f5635989a963`，总体 `success`；Quality Windows/Ubuntu、Production integration、Production experiment integration、Chromium acceptance 和 Week 11-12 verification 均为 `success`。
- WSL Docker Engine：`29.7.2`
- Docker Compose：`5.4.0`
- 资源 envelope：4 vCPU、8 GiB；当前 WSL 可见内存约 7.76 GiB
- 平台数据库：`ml_platform`
- MLflow 数据库：`mlflow`，与平台数据库隔离
- 当前业务镜像：当前 SHA 的 runtime image digest 为 `sha256:6269cf4e8f8a43f0a6a607ad94b14017f7dc5f27d728600341deed974e29c931`。
- Week 11 工具与合同测试：本地相关回归通过；当前 SHA 的远程 Week 11-12 verification 已完成并上传完整证据。

## 4. 验收任务状态

### W11-R1：固定资源真实性能

状态：`passed`

要求：

- 隔离栈在 4 vCPU / 8 GiB 下持续运行整个负载窗口。
- `core-read`、`warm-inference`、`enqueue` 各执行 iteration 1/2/3。
- `cold-model-load` 执行 iteration 1。
- `welding-e2e` 执行 iteration 1，10 个请求全部为 `completed`。
- 生成所有原始 JSON 和 `performance/summary.json`。
- summary 的 `status=passed` 且 `candidate_status=passed`，提交 SHA 与当前基线一致。

证据：`temp_test/remote-run-33363122355/performance/summary.json`，`status=passed`、`candidate_status=passed`，commit 绑定当前 SHA。

### W11-R2/W11-R3：真实备份恢复与 N-1 升级

状态：`passed`

证据：`temp_test/remote-run-33363122355/backup/restore-result.json`、`upgrade/result.json`、`upgrade/smoke.json`，均为 `status=passed`；备份恢复 RTO/RPO 和 N-1 双次迁移、smoke 均通过。

### W12-R1：最终 evidence manifest

状态：`passed`

必须包含并通过：

- `environment.json`
- `performance/summary.json`
- `backup/restore-result.json`
- `upgrade/result.json`
- `security/summary.json`
- `playwright/result.json`
- `security/runtime-images.json`

运行结果：`temp_test/remote-run-33363122355/final-evidence-manifest.json`，`status=passed`；所有状态、哈希、提交绑定和安全门禁均通过，未改写任何 `skipped` 状态。

### W12-R3：最终状态和发布决策

状态：`completed`

W11-R1、W11-R2/R3、W12-R1 及当前 source SHA 绑定均已通过，已完成：

- 更新 `PLATFORM_STATUS.md` 和本文件为完成。
- 生成最终验收报告和 manifest 链接。
- 确认工作区没有未纳入发布的 Week 12 修改。
- 已完成本次验收文档变更的提交与推送；不再重复触发 CI。

## 5. 当前阻断与下一步

1. Run `33363122355` 已核对：六个 required jobs 全部 `success`，绑定 SHA `3752794001c58b91d6a0e5f9c139f5635989a963`。
2. 已下载同一 SHA 的全部必需制品；性能、备份恢复、N-1、安全、Playwright 和最终 manifest 均为 `passed`。
3. `evidence_manifest.py` 输出 `status=passed`，包含 7 项必需证据、哈希、镜像 digest 和迁移 head。
4. Week 12 外部栈的四角色、四通道、rollout、部署和真实 `429` 浏览器验收已由 Chromium receipt 通过；生产默认限流值未改。
5. 旧 Run 的失败记录继续保留在历史续行中，不作为当前验收依据。

## 6. 当前证据位置

- WP0 环境证据：`temp_test/week11-12-live/evidence/`
- W11-R2 实测结果：`temp_test/week11-12-live/evidence/backup/restore-result.json`
- W11-R3 实测结果：`temp_test/week11-12-live/evidence/upgrade/result.json`
- 验收执行计划：`ml-platform/docs/superpowers/plans/2026-08-22-week9-12-acceptance-closure.md`
- 历史远程全量门禁：Actions Run `32569941915`（旧 SHA，仅作历史参考）
- 当前性能结果：上一 SHA 的 `performance/summary.json` 仅作历史参考；最终 SHA 必须复跑并覆盖当前证据。
- 当前 Run 下载目录：`temp_test/remote-run-33363122355/`（含 environment/security/performance、backup、upgrade、Playwright 和最终 manifest）。
- 当前最终 manifest：`temp_test/remote-run-33363122355/final-evidence-manifest.json`，`status=passed`。
- 针对 Chromium 冷 runner 依赖安装超时，`.github/workflows/ci.yml` 的 Chromium job timeout 已从 `40` 调整为 `60` 分钟；同时移除了自定义 pip index URL，改用 runner 默认源。两项修改需在新 SHA 的 full Run 中验证，不能复用 `33249241089`。

## 7. 文档维护

每次执行后只更新本文件的当前状态、未完成任务、阻断和下一步；历史问题、已解决问题和旧状态保留在归档文件及共享经验文档中，不在当前计划中重复展开。

## 7A. 最新执行记录（2026-08-31，通用自动标注旧模型输入兼容）

- 问题现象：通用数据标注启动自动标注时，注册模型要求 `current_ratio`、`voltage_ratio`、`power_wld1` 等 73 个点焊派生特征，原始数据没有这些列，任务失败并返回 `QUALITY_INPUT_COLUMNS_INVALID`。
- 根因：历史 `report_v1` 模型包保存的是派生特征 schema；通用自动标注执行层此前把内部派生特征名直接当作原始数据列名读取，未调用既有 `build_feature_frame()` 适配器。
- 修复：仅当注册模型 schema 与完整 `FEATURE_SCHEMA` 精确匹配时，自动标注现场从点焊报告原始字段生成派生特征；其他通用模型仍严格按原始输入列读取，不过滤缺失列、不引入目标列或模型特征列概念。新增回归测试覆盖 73 特征生成。
- 验证：`py -3.14 -m py_compile` 通过；`git diff --check` 通过。当前环境缺少 `joblib`，后端运行时 smoke/test 无法执行，记为 `skipped`，不宣称测试通过。
- 未完成：需在具备后端依赖的环境运行点焊质量服务和 API 回归测试，并用真实注册模型/数据集执行一次自动标注验收。

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

> 以上第 1–11 节为 Week 9–12 验收记录，最后更新日期固定为 2026-08-24。以下条目仅记录后续产品开发，不作为验收进度更新。

## 11A. 验收续行（2026-08-28）

- 当前发布 SHA `905d82cce113bb9493bc9c99b16d8b43337c0dec` 的普通 push Run `33131895648` 已完成 `success`；Quality Ubuntu/Windows、后端套件、前端测试和构建均通过，但 Production integration、Production experiment integration、Chromium acceptance、Week 11-12 verification 在该 push 模式下均为 `skipped`，不计入 Week 9-12 验收。
- 已触发当前 SHA 的完整门禁 Run `33135264039`（`workflow_dispatch`, `mode=full`）。截至 2026-08-28 记录，Production integration、Production experiment integration、Quality Ubuntu/Windows 均为 `success`，Chromium acceptance 仍为 `in_progress`；Week 11-12 verification 尚未开始。必须等待并逐项核对所有 required jobs，任何 `failed`、`cancelled` 或 `skipped` 均保持未完成。
- 本地 `run_suite.py` 已执行到 `test_week12_security_gates`；该模块在本机 300 秒超时，未取得完整 active suite 通过结论，记为 `failed/blocked`，不替代远端 full run。此前已通过的 `test_database_production`、`test_api_project_access`、`test_notification_models` 和 `test_week11_12_tools` 保持独立通过记录。
- 当前工作树存在用户未提交的前端修改（`AppLayout*`、`APIMarketplacePage*`），未纳入本次验收提交，必须保留。
- Run `33135264039` 已于 2026-08-28 完成，绑定 SHA `905d82cce113bb9493bc9c99b16d8b43337c0dec`，总体 `success`。六个 job 均为 `success`：Quality Ubuntu/Windows、Production integration、Production experiment integration、Chromium acceptance、Week 11-12 verification。
- 已下载并核对远端制品：Playwright `result.json` 为 `passed=1,total=1,failed=0`；安全 `summary.json` 为 `status=passed`，四个当前 SHA 镜像、pip-audit、Bandit、npm audit、Trivy、Gitleaks 和 frozen-stack web security gates 均为 `passed`，runtime-images 与 source commit 均绑定 `905d82c`。
- 该 Run 的 Week 11-12 verification 工作流实际执行的是工具/合同测试、安全扫描和 web security gate；上传制品未包含当前 SHA 的 `performance/summary.json`、`backup/restore-result.json` 或 `upgrade/result.json`。因此 W11-R1、W11-R2、W11-R3 仍为 `rerun_required`，不能仅凭 job 绿色关闭 Week 9-12 验收。
- 继续重跑时发现本地 `temp_test/week11-12-live` runbook 不是可复用的当前发布门禁：性能脚本会被旧证据目录拒绝，带 security image override 时要求 CI 专用 `WEEK12_*_IMAGE` 变量，去掉 override 后 backup 脚本在一次性 WSL 调用中又因 `/tmp/week9-12-secrets/env` 生命周期和 Compose DNS 不稳定而失败。上述结果归类为 `blocked`，不计为业务验收失败，也不计为通过。
- 当前 `HEAD` 已变为 `420a6c8848fc095dfa1e76e0f1c12cb91ec07592`，与 Run `33135264039` 绑定的 `905d82c` 不同；该 Run 的安全、浏览器和 Week 11-12 结果不能绑定到当前 SHA。必须先将 WP3/WP4/WP5 执行器纳入受版本控制的 CI/工具路径，再以 `420a6c8` 重新生成全部证据。

## 12. 最新执行记录（2026-08-24，手动标注详情修复）

- 问题现象：手动标注样本后队列进度始终少 1；只标注一个样本时退出再进入显示 `0`。人工标签编辑区在运行中任务轮询时自动退出，新增标签丢失；标签按钮宽度随内容和编辑按钮变化。
- 根因：SQLAlchemy 会话使用 `autoflush=False`，提交/删除接口修改 `current_label` 后未 flush 就执行计数查询，当前样本未进入聚合结果并把错误进度持久化。前端 effect 依赖 `target_schema` 对象引用，轮询每次返回的新对象都会重置编辑状态和本地标签列表。
- 修复：标签状态变更后先 `db.flush()` 再统计并持久化进度；前端改用目标 schema 内容签名触发初始化；标签网格按最长标签字符数计算统一固定宽度，并为编辑态删除按钮保持稳定布局。
- 验证：后端 API `37/37`、点焊质量服务 `30/30`、数据标注页面 `28/28`；Python `compileall`、TypeScript/Vite 生产构建和 `git diff --check` 通过。构建仅有既有大 chunk 警告；真实浏览器和远端 Actions 尚未执行。

## 13. 最新执行记录（2026-08-24，通用手动标注入口修复）

- 问题现象：通用数据集点击“开始手动标注”时报 `QUALITY_INPUT_COLUMNS_INVALID`，提示缺少 `wld1c`、`cvei` 等已屏蔽的点焊质量字段。
- 根因：手动任务创建、校验和执行共用点焊质量特征解析，任何数据集都被强制要求报告表字段和波形字段；前端虽然选择了通用列，后端仍按旧质量感知契约校验。
- 修复：增加通用手动标注配置解析和执行分支；仅当数据集包含完整点焊报告字段时保留原质量/AutoML 手动路径，不完整时按实际输入列和目标列生成样本、目标 schema 和人工标注队列。自动任务继续严格使用点焊质量字段校验。
- 验证：后端 API `38/38`、点焊质量服务 `30/30`、数据标注页面 `28/28`；新增普通 `record_id/temperature/Fault` CSV 手动任务回归，验证接口、创建接口和执行后样本队列均通过；前端构建、Python 编译和差异检查通过。真实浏览器和远端 Actions 尚未执行。

## 14. 最新执行记录（2026-08-24，手动任务状态和队列颜色修复）

- 问题现象：手动任务尚未完成全部样本标注时，任务列表可能显示 `completed`；样本队列中的手动标签使用自动质量告警级别渲染，出现红色或绿色。
- 根因：通用手动任务生成样本后直接写入 `completed`，没有区分“样本准备完成”和“人工标注完成”；任务序列化也直接返回持久化状态。前端队列无条件按 `warning_level` 映射颜色。
- 修复：手动任务在未全部标注时显示 `running`，只有 `annotated_count == total_count` 才显示 `completed`；提交/删除人工标签后同步更新任务状态。手动队列标签改用默认中性色，自动任务继续显示质量告警颜色。
- 验证：后端 API `38/38`、数据标注页面 `28/28`；新增断言覆盖未完成手动任务返回 `running` 和手动队列不使用红色告警标签。Python 编译、前端构建和差异检查通过。真实浏览器和远端 Actions 尚未执行。

## 15. 最新执行记录（2026-08-24，标注详情页头收窄）

- 完成：仅收窄标注详情页顶部“QUALITY / LABELING / 数据标注”页头，降低上下内边距、底部间距、标题字号和项目选择框高度；任务列表与配置页的通用页头样式不变。
- 验证：DataAnnotationPage 聚焦测试 `29/29`，`git diff --check` 通过。
- 补充：详情页项目选择框最小高度由 `28px` 调整为 `15px`，并更新样式回归断言；聚焦测试仍为 `29/29`。
- 补充：针对带 `runId` 的 `view=tasks` 工作区 URL，顶部项目选择框实际位于普通 `.page-header`，已单独设置为 `15px` 高度；聚焦测试仍为 `29/29`。
- 补充：根据页面截图，详情页红框范围的页头整体收窄，移除详情页顶部 Project 选择框；创建任务配置页的项目选择仍保留。聚焦测试和差异检查需重新验证。
- 补充：左侧“数据标注”菜单现在显式导航到 `view=tasks` 任务列表，并清除当前详情页的 `runId`、样本和其他工作区参数；创建任务和详情页内部返回逻辑不变。
- 补充：侧边栏菜单改为由 Ant Design `Menu` 统一接收 `onClick`，避免已选中的“数据标注”菜单项未触发项目级点击处理；聚焦菜单测试 `6/6` 通过。
- 补充：修复详情页点击侧边“数据标注”后仅刷新不离开详情的问题；`view=tasks` 现在会清理组件内 `workspaceMode/runId/datasetId` 状态并阻止旧参数回写，同时打开任务工作区时使用跳过标记避免与任务列表清理逻辑竞态。前端聚焦测试 `35/35` 通过。
- 补充：自动标注配置页模型下拉为空的根因是训练完成模型状态为 `completed`，而质量模型接口仅筛选 `registered`；接口现同时返回 `completed/registered` 的点焊质量模型。弱监督策略改到模型选择下方，勾选后工艺规则默认清空，点击“点焊工艺规则模版”才填充默认规则。前端聚焦测试 `34/34` 通过；Python 后端测试命令在当前环境退出码为 `1` 且无输出，未计为通过。
- 补充：自动建模任务列表增加项目名称列；运行中普通 AutoML 任务现在可进入详情并显示“停止”操作，调用训练任务停止接口提交取消请求；任务删除仍遵循后端仅允许终态删除的约束。点焊模型选择接口改为返回项目内所有已完成/已注册模型库制品，因此 AutoML 注册模型可供新建自动标注任务选择。新增 AutoML 页面回归测试覆盖项目列与运行任务停止操作。
- 补充：自动建模任务列表中普通 AutoML 任务的类型标签由“普通建模”更正为“自动建模”；停止任务进入 `cancel_requested` 后，前端删除按钮启用，后端将该状态纳入训练任务可删除终态，避免停止后任务无法清理。新增回归覆盖停止、刷新状态和批量删除链路。
- 验证：`AutoMLPage` 与 `DataAnnotationPage` 前端测试 `34 passed / 19 skipped`，生产构建通过，`git diff --check` 通过；后端 `pytest tests/test_training.py -q` 在当前环境退出码 1 且无输出，未计为通过，需在具备 Python 测试依赖的环境复跑。
- 补充：任务 `d708d58f-d8b1-4873-8734-eb510dbad2b3` 实际已完成，但因 600 秒时间预算提前结束搜索，后端保留了 `13/35` 的试验预算进度，详情页显示为 37.14%，造成“卡住”假象。详情页现以任务 `status=completed` 作为总体完成依据显示 100%，同时将计数文案改为“已完成试验”，保留实际试验数。
- 验证：`AutoMLTaskPage` 测试 `7/7 passed`，前端生产构建通过，`git diff --check` 通过；通过本地 API 认证后核对该任务状态为 `completed`，`metrics.progress` 为 `completed=13,total=35,budget_exhausted=true`，确认根因不是 worker 卡死。
- 补充：修复普通数据集点击“开始自动标注”仍进入点焊质量特征校验的问题。非完整点焊报告的自动任务现在按选定输入列和项目内已完成/已注册模型制品执行通用推理，生成自动标签，不再要求 `wld1c`、`cvei` 等点焊字段；完整点焊报告继续保留原质量感知流程。
- 验证：后端 API/service 文件 `py_compile` 通过；数据标注与质量 API 前端测试 `34/34 passed`，前端生产构建和 `git diff --check` 通过。后端 pytest 尚未执行，需在具备项目测试依赖的环境补跑通用自动任务回归。

## 16. 最新执行记录（2026-08-25，注册模型一致性与自动标注两步配置）

- 问题现象：“模型库”的“注册模型”列表为空时，自动标注模型下拉仍展示大量仅训练完成的 `ModelLibrary` 制品；自动标注第一屏同时暴露目标列、弱监督和提交操作，配置层次不清晰。
- 根因：自动标注模型接口绕过 `RegisteredModel/ModelVersion` 注册表，直接按 `ModelLibrary.status in (completed, registered)` 返回制品；自动标注继续复用手动标注的目标列控件，没有使用注册版本持久化的输出 schema。
- 修复：自动标注模型接口改为联表返回项目内 `platform_joblib` 注册版本，并携带注册模型名称、版本、输入 schema 和输出列 schema；服务层直接加载时同样要求存在注册版本。自动标注按模型输出 schema 自动确定目标列与类型，第一步仅选择项目、数据和注册模型，点击“下一页”进入第二步配置弱监督并显示“开始自动标注”；手动标注目标列流程不变。
- 验证：相关前端页面/API 测试 `53/53 passed`，前端生产构建通过，后端三个相关文件使用捆绑 Python `py_compile` 通过，`git diff --check` 通过。真实浏览器确认自动标注默认显示步骤 1/2、第一步不显示目标列/弱监督/开始按钮，并确认同一项目的模型库“暂无注册模型”时自动标注下拉也为空。Windows 捆绑 Python 与 WSL Python 均未安装 `pytest`，后端 API 回归测试已补充但本机未执行，不计为通过。
- 剩余：在具备后端测试依赖的环境运行 `tests/test_api_spot_weld_quality.py`；使用含已注册模型版本的项目在真实浏览器复核“下一页”后的第二步提交链路。

## 17. 最新执行记录（2026-08-25，自动标注前置校验模型参数修复）

- 问题现象：自动标注第 2 步已选择模型，点击“开始自动标注”时 `/spot-weld/validate` 仍返回 `400 QUALITY_MODEL_REQUIRED`，运行创建请求未执行。
- 根因：两步配置改造后，`selected_model_id` 只写入 `/spot-weld/runs` 创建 payload，没有同步写入先执行的 `/spot-weld/validate` options；后端校验按自动标注契约拒绝缺少模型 ID 的请求。
- 修复：自动模式的校验请求与创建请求统一携带同一个 `selected_model_id`；手动模式仍不发送该字段。前端回归测试分别断言 validate 和 create 两个请求的模型 ID 与自动推导目标列一致。
- 验证：`DataAnnotationPage` 与 `spotWeldQuality` 测试 `34/34 passed`，前端生产构建和 `git diff --check` 通过。真实浏览器使用项目 `725b6ca9-d965-4349-9172-d8fb900c6500`、`weld_fault_features.csv` 和注册模型 `automl-job - LightGBM v1` 提交成功，创建运行 `3ae5f3cc-eba9-4838-b0ca-9c38ad709253`，316 条样本完成自动标注，未再出现 `QUALITY_MODEL_REQUIRED`。

## 18. 最新执行记录（2026-08-25，数据标注全面通用化）

- 问题现象：数据标注页面仍显示点焊缺陷标签、波形替换、工艺规则和弱监督聚类配置；包含完整点焊字段的普通数据集会被后端按列形状重新路由到点焊质量校验，导致通用注册模型输入列缺少 `cvei/cvev/cver/cvep` 时返回 `QUALITY_INPUT_COLUMNS_INVALID`。
- 根因：数据标注与点焊质量建模复用了 `/spot-weld` API 和运行表，但缺少显式工作流类型；校验、创建和 worker 通过数据集形状推断用途，前端也保留了点焊规则、固定标签和波形展示。
- 修复：数据标注请求显式携带 `workflow_kind=data_annotation`，校验、创建和 worker 对该类型始终使用通用目标 schema、输入列和注册模型推理，不再按数据列形状进入点焊路径；默认 `quality_modeling` 保留原点焊 AutoML 行为。前端移除点焊固定标签、规则模板、弱监督聚类和波形替换，第二步改为只读的“注册模型推理”通用策略，任务、上传、错误、页头和导航 URL 全部改为通用数据标注语义。
- 验证：后端 `tests.test_api_spot_weld_quality` 完整回归 `39/39 passed`，包含“完整点焊形状数据仍走通用自动标注”的新增测试；前端相关测试 `44/44 passed`，生产构建、Python `py_compile` 和 `git diff --check` 通过。真实浏览器检查任务列表、自动配置步骤 1/2 和样本工作区，未发现 `点焊/焊点/飞溅/虚焊/烧穿/波形/工艺规则` 可见文本，页面布局正常。
- 兼容边界：数据库模型、内部 CSS 类名和 `/spot-weld` 路径暂时保留，供既有点焊质量建模和历史运行兼容；数据标注行为由显式 `workflow_kind` 隔离，不再依赖这些内部命名。

## 19. 最新执行记录（2026-08-25，数据标注任务全状态删除）

- 问题现象：数据标注任务仅在 `completed/failed/cancelled` 状态显示可删除，运行中或排队中的任务无法删除；后端同样以 `QUALITY_RUN_ACTIVE` 拒绝非终态删除。
- 根因：前端按钮和后端接口都把“终态”错误地当作删除前置条件；如果只移除状态判断，异步 worker 仍可能在运行记录删除后写入样本或状态，造成外键错误或孤立数据。
- 修复：所有任务状态均可点击删除，沿用确认弹窗，取消确认时不发送请求；后端对活动任务先取消 Celery/本地调度，再显式删除依赖记录和运行记录。Local dispatcher 支持取消待执行任务，并向运行中的通用标注 worker 提供协作取消信号；worker 在样本落库和提交前检查取消信号及运行记录是否仍存在，删除后停止写回。
- 验证：后端完整 `tests.test_api_spot_weld_quality` 为 `39/39 passed`，删除接口与调度器聚焦测试 `9/9 passed`；前端数据标注、导航、数据管理和 API 测试 `45/45 passed`；前端生产构建和 `git diff --check` 通过。构建仅有既有大 chunk 警告；真实浏览器删除操作和远程 Actions 尚未执行。

## 20. 最新执行记录（2026-08-25，自动标注翻页按钮居中）

- 调整：自动标注第一步的“下一页”和第二步的“上一页 / 开始自动标注”操作组改为水平居中；“上一步”文案统一为“上一页”。手动标注提交按钮仍沿用原布局。
- 根因：自动和手动配置共用 `.data-annotation__setup-footer`，其 `justify-content: space-between` 会让单个翻页按钮靠左、多个按钮分散到两端。
- 验证：DataAnnotationPage 测试 `30/30 passed`，前端生产构建和 `git diff --check` 通过；构建仅有既有大 chunk 警告。

## 21. 最新执行记录（2026-08-25，通用自动标注弱监督聚类与规则配置）

- 需求：自动标注第二步提供可选“弱监督标注策略”；启用后按注册模型的实际特征 schema 和 `feature_importances_` 执行标准化、重要性加权 KMeans（K=2~8、轮廓系数选优），页面显示等待状态、聚类摘要和 PCA 散点图，并允许用户配置共享 dtype 的规则标签。
- 修复：增加通用注册模型聚类预览接口；规则 token 仅允许数据列、数字/逻辑运算符、数字和字符串，数据列严格来自所选数据文件；服务端使用结构化解析器和 dtype 校验，不使用 `eval`；弱监督规则命中时覆盖模型标签并持久化规则命中、cluster id 和聚类结果。未启用弱监督时保持纯注册模型推理路径。
- 额外修复：布尔规则解释器即使发生 `and/or` 短路也必须消费右侧 token，避免表达式解析游标残留；前端 API 类型改为结构化规则类型，避免 TypeScript 将嵌套 token 误判为普通 JSON 字典。
- 验证：前端 DataAnnotation/API 聚焦测试 `36/36 passed`；前端生产构建通过；后端相关文件 `py_compile` 通过；Miniconda 环境后端服务/API 回归 `71` 个用例中原有一条随机未注册模型 ID 断言与注册模型契约冲突，已改为断言 `QUALITY_MODEL_INVALID`，修正后的回归单测通过。当前未重复执行完整 71 用例，之前完整运行的唯一失败已被该测试修正。
- 未完成/风险：当前工作树仍包含本轮之前的多模块未提交用户修改；未执行提交、推送或远程门禁。完整后端回归应在下一次依赖稳定的环境复跑并保留最终结果；真实浏览器尚未使用启用弱监督且存在已注册模型的项目复核聚类预览和最终提交链路。

## 22. 最新执行记录（2026-08-25，聚类配色与规则条件折叠）

- 调整：聚类散点图按簇拆分为独立 series，使用稳定颜色表、图例和摘要色点，不同簇不再共用默认颜色。
- 调整：规则条件仍以“类型 + 值”结构编辑；选择下拉值后立即折叠为仅显示值，数字/字符串输入在失焦或回车后折叠；点击已完成值可重新编辑；每个条件对新增独立删除按钮，删除不影响同一规则的其他条件。
- 兼容：提交前将折叠态规则重新序列化为原有结构化 token 合同，服务端校验和规则解析接口不变。
- 验证：DataAnnotation/API 前端测试 `36/36 passed`，生产构建通过，Miniconda 环境后端 service/API 完整回归 `71/71 passed`，`git diff --check` 通过；真实浏览器使用项目 `725b6ca9-d965-4349-9172-d8fb900c6500` 和注册模型 `automl-job - LightGBM v1` 完成聚类，页面显示 4 个簇、不同色点和规则编辑区。
- 剩余：未执行提交、推送或远程门禁；当前工作树仍包含本任务之前的多模块未提交修改，均保持原样。

## 23. 最新执行记录（2026-08-25，弱监督开关与条件删除控件视觉优化）

- 调整：弱监督标注策略的启用控件改为更大的滑动开关，使用“启用/已启用”状态文字和明显的选中态；规则每个条件改为独立圆角框，删除按钮移动到边框右上角并使用“×”符号。
- 兼容：仍保留原生 checkbox 的无障碍名称和规则 token 的 `kind/value` 序列化，未改变接口或提交行为。
- 验证：DataAnnotation/API 前端测试 `36/36 passed`，生产构建通过；构建仅有既有 ECharts 大 chunk 警告。
- 剩余：未执行提交、推送或远程门禁；当前工作树其他未提交修改保持原样。

## 24. 最新执行记录（2026-08-26，自动标注双模式提交入口）

- 调整：自动标注第二步的“开始自动标注”按钮不再因为弱监督尚未完成聚类而置灰；关闭弱监督时可直接提交并使用注册模型的原始预测标签，开启弱监督时仍在点击后校验聚类和规则配置，确保实际执行采用“聚类 + 规则”并以用户规则标签覆盖模型标签。
- 后端确认：通用数据标注 worker 在 `weak_supervision=false` 时保留模型标签；为 `true` 时执行加权 KMeans、规则解析和命中标签覆盖，原有 API 契约不变。
- 验证：DataAnnotation/API 前端测试 `36/36 passed`，生产构建通过，`git diff --check` 通过；后端通用 worker 分支沿用既有 `71/71 passed` 回归结果。未执行提交、推送或远程门禁。

## 25. 最新执行记录（2026-08-26，数据标注任务列表完整性与归属列）

- 问题现象：数据标注任务列表只按当前选中项目请求，导致列表有时显示全部、有时只显示部分任务，且缺少项目和创建者信息。
- 修复：任务列表视图并行加载所有可访问项目的任务，按任务 ID 去重并按创建时间倒序合并；工作区仍保持单项目请求。任务序列化新增 `project_name` 和 `created_by_name`，列表新增项目、创建者列，打开/删除任务使用任务自身的 `project_id`。
- 验证：DataAnnotation/API 前端测试 `37/37 passed`，生产构建通过，后端 API/service `py_compile` 通过，`git diff --check` 通过；未执行提交、推送或远程门禁。

## 26. 最新执行记录（2026-08-26，数据标注页面视觉与英文适配）

- 调整：新增 `dataAnnotation` 中英文文案命名空间，数据标注任务列表、自动标注两步配置、弱监督聚类与规则编辑、标注工作区的主要可见文案和状态映射均通过 `useI18n()` 渲染；保留项目名、模型名、列名和标签值等业务数据原样。
- 调整：任务删除、规则删除和人工标签删除统一采用 `Tooltip + ant-btn-icon-only + DeleteOutlined` 的危险色图标按钮；规则条件继续保留右上角 `×` 删除按钮，新增任务操作区统一间距与焦点/悬停样式。
- 兼容：中文无障碍名称保持既有测试和键盘操作契约；英文模式使用对应英文标签、状态、空状态和操作文案。
- 验证：DataAnnotation/API 前端测试 `37/37 passed`，生产构建通过（仅既有 ECharts 大 chunk warning），`git diff --check` 通过；未执行提交、推送或远程门禁。
- 范围说明：本轮覆盖数据标注新增/近期修改页面；AutoML、Monitor、ProjectDetail 等历史页面仍可能存在未迁移的中文硬编码，未在本轮扩大重构范围。

## 27. 最新执行记录（2026-08-26，工作台统计变更即时同步）

- 问题现象：工作台“模型总数”“API 总数”“模型状态”仅依赖 15 秒轮询，用户在模型库或 API 页面新增/删除后，工作台不能立即反映变化。
- 修复：增加统一的 `platform:dashboard-stats-changed` 前端事件；模型库成功创建/删除注册模型、API 页面成功删除 API 后广播事件；工作台监听同页事件并立即重新请求 `/dashboard/stats`，同时监听 `storage` 事件支持跨标签页同步，原有 15 秒轮询作为后台异步变化兜底。
- 验证：Dashboard/ModelLibrary/DataAnnotation 聚焦测试 `49/49 passed`，生产构建通过，`git diff --check` 通过；构建仅有既有 ECharts 大 chunk warning。未执行提交、推送或远程门禁。

## 28. 最新执行记录（2026-08-26，自动建模超时状态与训练进度）

- 问题现象：AutoML 搜索预算耗尽且计划试验未完成时仍持久化赢家并显示 `completed`；任务接口未返回 `error_details`，列表无法展示错误原因；训练任务进度只在首次加载时显示。
- 根因：`automl_execution._execute_optuna_job` 仅记录 `budget_exhausted`，未在持久化前阻断未完成搜索；训练任务页面缺少运行中任务轮询，并未优先读取 `metrics.progress`。
- 修复：预算耗尽且 `completed_trials < planned_trials` 时抛出超时错误，统一写入 `AUTOML_TIME_BUDGET_EXCEEDED`、错误消息和 `error_details.message`，状态为 `failed`；训练 API 返回 `error_details`，AutoML 列表显示错误消息；总时间上限输入调整为最大 `9999` 秒并显示单位；训练任务列表每 1.5 秒刷新运行中任务，优先使用后端进度指标。
- 验证：前端 AutoML/TrainingJobs 测试 `9 passed / 19 skipped`，生产构建通过，后端相关文件 `py_compile` 通过，`git diff --check` 通过；后端 pytest 未执行（当前环境缺少 pytest 依赖），未计为通过。

## 29. 最新执行记录（2026-08-26，所有任务列表默认全量与项目/创建人列）

- 需求：自动建模、模型训练、数据标注和智能编排任务列表默认显示当前用户有权限访问的全部项目任务，并新增项目、创建人列；选择项目后才进行筛选。
- 修复：训练任务序列化补充 `project_name`、`created_by_id`、`created_by_name`；数据标注新增 `/api/spot-weld/runs` 聚合列表接口，按项目权限返回全部可访问运行；智能编排任务新增可空 `project_id`、`created_by_id` 字段和 Alembic `20260826_13` 迁移，工作流历史任务支持关系回退；四个前端列表均增加“全部项目”默认选项和项目/创建人显示。
- 兼容：旧编排任务的项目和创建人可为空，无法回退时显示 `-`；新建编排任务要求选择项目；原有项目级标注接口和具体任务操作路径保留。
- 验证：前端聚焦测试 `54 passed / 19 skipped`，生产构建通过（仅既有 ECharts 大 chunk warning），后端相关文件 `py_compile` 通过，`git diff --check` 通过；后端 pytest 因当前环境缺少 `sqlalchemy/pytest` 依赖未执行，未计为通过。未执行提交、推送或远程门禁。

## 30. 最新执行记录（2026-08-26，模型训练实验列表补齐）

- 问题现象：模型训练页面的“实验”列表仍复用首个项目作为隐式筛选，导致跨项目实验显示不完整，且缺少项目和创建人列。
- 修复：实验列表接口的 `project_id` 改为可选；省略项目时按当前用户可访问项目返回全部实验，显式项目时继续执行项目权限校验。实验响应新增 `project_name`、`created_by_name`；前端将实验筛选状态与训练任务筛选状态分离，默认使用“全部项目”，并新增项目、创建人列。
- 验证：实验 API 与模型训练页面专项测试 `10/10 passed`；相关前端聚焦套件 `59 passed / 19 skipped`；生产构建通过（仅既有 ECharts 大 chunk warning）；实验后端文件 `py_compile` 与 `git diff --check` 通过。后端 pytest 因当前环境缺少项目测试依赖未执行，未计为通过。未执行提交、推送或远程门禁。

## 31. 最新执行记录（2026-08-26，监控与任务列表显示统一）

- 调整：资源监控移除“点焊质量预警”区域及其项目选择、预警请求和样本跳转逻辑，仅保留 CPU、内存、磁盘、GPU 资源指标。
- 调整：新增前端公共任务状态映射，自动建模、模型训练、数据标注和智能编排统一显示中文/英文状态文本与颜色；数据标注仅修正显示映射，不修改后端真实状态。
- 调整：任务列表删除操作统一采用危险色图标按钮、Tooltip 和无障碍名称；保留批量删除按钮的文字和数量信息。
- 验证：监控、数据标注、自动建模、模型训练、智能编排前端测试 `46 passed / 19 skipped`；生产构建通过（仅既有 ECharts 大 chunk warning），`git diff --check` 通过。未执行提交、推送或远程门禁。

## 32. 最新执行记录（2026-08-26，自动标注规则请求解析修复）

- 问题现象：自动标注点击“开始自动标注”前的 `/validate` 请求返回 422，Pydantic 报告 `process_rules[*].tokens` 无法转换为 `str/float/int/bool`。
- 根因：`DatasetQualityRequest.process_rules` 只允许标量字典值，但弱监督规则合同包含嵌套的 `tokens` 数组；请求在进入服务层规则校验前就被 FastAPI 拒绝。
- 修复：将请求模型字段改为允许嵌套 JSON 的 `list[dict[str, Any]]`；规则语义、token 类型、数据列和标签 dtype 仍由 `normalize_annotation_process_rules` 统一校验。
- 验证：后端 API 文件 `py_compile` 通过；数据标注/质量 API 前端测试 `38/38 passed`。后端 pytest 仍因环境缺少项目依赖未执行，未计为通过。

## 33. 最新执行记录（2026-08-26，规则请求模型运行时适配器修复）

- 问题现象：修复标量字段后，服务端 `/validate` 从 422 变为 500，Pydantic 报 `DatasetQualityRequest` 未完全定义。
- 根因：模块启用了延迟注解，但请求模型使用的 `Any` 未从 `typing` 导入；静态 `py_compile` 无法触发 FastAPI/Pydantic 运行时类型适配器构建错误。
- 修复：补充 `Any` 导入，使 `process_rules: list[dict[str, Any]]` 能被 FastAPI 正确解析。
- 验证：Miniconda Python 实例化嵌套 `process_rules` 请求模型通过；后端 `py_compile` 通过；数据标注/质量 API 前端测试 `38/38 passed`。

## 34. 最新执行记录（2026-08-26，自动标注目标列标签类型校验）

- 问题现象：运行 `cf1ee194-cf69-4ce1-8e44-e648604c7b91` 创建成功后由 worker 失败，错误码为 `QUALITY_LABEL_TYPE_INVALID`。
- 根因：已有目标列 `Fault` 的实际 dtype 为 `int64`，但前端弱监督标签类型默认是 `string`，提交了非数字标签；任务创建前没有按已有目标列 dtype 校验，因此错误延迟到异步执行阶段。
- 修复：前端选择已有目标列时自动同步其 dtype；自动标注使用模型输出目标 dtype；提交前按有效 dtype 校验规则标签，整数/浮点标签不合法时阻止创建任务；请求中的 `target_column_dtype` 与有效 dtype保持一致。
- 验证：数据标注/质量 API 前端测试 `38/38 passed`，前端生产构建通过，后端相关服务/API `py_compile` 通过，`git diff --check` 通过。未修改历史失败任务状态。

## 35. 最新执行记录（2026-08-26，自动标注不依赖目标列）

- 问题现象：自动标注沿用注册模型的 `target_column`，当数据存在同名列但弱监督规则标签类型不一致时，任务异步失败；数据没有该列时也无法稳定创建任务。
- 修复：自动标注请求不再发送目标列名称或将其视为输入排除项；关闭弱监督时使用注册模型输出 schema 的 dtype 和模型预测标签，启用弱监督时使用用户选择的标签 dtype、聚类结果和规则标签覆盖模型标签。后端自动配置允许 `target_column=None`，不要求数据存在目标列。
- 测试：新增无模型目标列的前端自动标注回归，并更新旧请求断言；DataAnnotation/API 前端测试 `39/39 passed`，生产构建通过，后端相关文件 `py_compile` 通过，`git diff --check` 通过。
- 剩余：需重启本地前后端服务并新建运行验证；此前 `cf1ee194-cf69-4ce1-8e44-e648604c7b91` 的失败状态是历史事实，不回写。

## 36. 最新执行记录（2026-08-26，弱监督人工标签仅保留用户规则标签）

- 问题现象：启用弱监督后，标注工作区的人工标签选项同时出现模型预测标签和用户规则标签。
- 根因：通用自动标注 worker 生成 `target_schema.classes` 时无条件合并模型预测结果与规则标签，前端按该字段渲染人工标签选项。
- 修复：弱监督模式下 `target_schema.classes` 只从用户添加的规则标签生成；未启用弱监督时仍使用模型输出标签作为 schema 类别。
- 验证：新增弱监督工作区回归，确认模型标签不显示、规则标签正常显示；DataAnnotation/API 前端测试 `40/40 passed`，后端服务 `py_compile` 和 `git diff --check` 通过。

## 37. 最新执行记录（2026-08-26，弱监督规则允许使用数据集非模型特征列）

- 问题现象：规则选择数据集中真实存在的 `Fault` 列后，`/spot-weld/validate` 返回 `QUALITY_ANNOTATION_RULE_COLUMN_INVALID`。
- 根因：前端允许规则选择数据集全部列，规则执行也读取完整原始行，但后端 validate、create 和 worker 只按模型特征 schema 校验规则列，三处契约不一致。
- 修复：聚类和模型推理继续只使用注册模型特征列；规则列校验统一改为数据集原始列，允许规则引用 `Fault` 等不参与模型推理的真实字段，并继续拒绝数据中不存在的列。
- 验证：新增后端 API 回归，覆盖模型仅使用 `wld1c`、规则使用 `Fault` 的 validate/create 链路，`unittest` 通过；规则解析专项 `2/2`、前端 DataAnnotation/API `40/40`、后端 `py_compile` 和 `git diff --check` 通过。当前 Miniconda 环境未安装 pytest，pytest 命令未计为通过。

## 38. 最新执行记录（2026-08-26，自动标注移除建模列契约）

- 需求澄清：自动标注是通用数据标注流程，用户没有也不应选择“目标列”或“模型特征列”；数据可能采用任意业务格式。
- 根因：前端从注册模型元数据读取 `feature_schema/target_column_dtype`，再构造自动标注的 `target_column*` 和 `input_columns` 请求字段，把自动建模概念泄漏到了标注契约。
- 修复：自动标注 validate/create 请求只提交数据制品、模型、`label_dtype` 和可选弱监督配置，不再提交 `target_column`、`target_column_created`、`target_column_dtype` 或 `input_columns`；聚类预览同样只提交数据和模型。后端自动分支忽略遗留列参数，按完整数据建立标注记录，模型适配器内部解析其推理输入；模型列表为标注流程提供独立 `label_dtype`。
- 兼容：手动标注仍保留目标列创建/选择能力；自动建模和质量建模原有目标列、输入列契约不变。
- 验证：前端回归显式断言自动请求不存在四个建模列字段，DataAnnotation/API `40/40 passed`；后端自动标注/API/模型列表专项 `3/3` 通过，生产构建、后端 `py_compile` 和 `git diff --check` 通过。

## 39. 最新执行记录（2026-08-26，列表表格与行操作视觉合同统一）

- 问题现象：项目管理、模型库、数据管理、数据标注、自动建模、模型训练和应用编排的列表外壳、表头字号/颜色、行高与操作按钮不一致；数据标注仍使用自定义卡片行，单行删除混用文字、文字加图标及不同颜色图标。
- 根因：页面各自实现表格外观和操作列，缺少可复用的行操作组件及统一 CSS 合同；数据标注任务列表没有使用 Ant Design `Table`，无法继承共享表头和响应式滚动规则。
- 修复：新增 `TableRowAction`，统一使用 `Tooltip + 30px icon-only Button + aria-label`；普通、停止和删除操作分别使用中性、警告和危险色，删除统一为红色 `DeleteOutlined`。共享 `.table-surface` 调整为 6px 圆角、无阴影、12px/600 表头和 46px 数据行；七个模块的主列表迁移到共享外壳，数据标注任务卡片迁移为 Ant Design `Table`，保留项目、创建者、状态、进度、打开和删除行为。
- 验证：8 个聚焦前端测试文件 `69 passed / 19 skipped`；新增公共组件测试覆盖图标按钮、Tooltip、危险色和禁用状态；生产构建通过，仅有既有 ECharts 大 chunk warning。浏览器已启动 `http://127.0.0.1:5175/`，但当前会话被重定向到登录页，未使用未授权凭据进入业务页面，因此真实数据页面桌面/窄屏视觉复核未计为通过。
- 剩余：未执行提交、推送或远程门禁；需在已有登录会话中补充七个页面的真实数据 Tooltip、键盘焦点、窄屏横向滚动和长名称不重叠检查。

## 40. 最新执行记录（2026-08-27，任务表格对齐、标注返回历史与本地 TensorBoard）

- 问题现象：部分任务列表的“操作”表头居中或默认左对齐，而行内图标组右对齐；新建数据标注任务后浏览器返回会跳到进入标注前的自动建模页面；本地训练任务点击 TensorBoard 返回 `503 TENSORBOARD_UNAVAILABLE`。
- 根因：项目、数据、训练和编排页面没有统一声明操作列右对齐；标注创建成功时使用 `replace` 将配置页直接替换为工作区，历史栈缺少任务列表；TensorBoard session API 只读取生产 secret/gateway，本地模式没有进程内签名和代理回退，并且本机 TensorBoard `2.19.0` 与当前 Python 不兼容，启动时缺少已移除的 `imghdr`。
- 修复：所有主任务列表的操作表头与内容统一右对齐，普通数据列继续左对齐；标注创建成功时将当前配置历史替换为 `view=tasks`，再压入 `view=workspace`；本地模式生成进程级临时 session signer，按训练事件目录启动受限 TensorBoard 子进程并代理请求，localhost 请求禁用系统代理，首次启动支持有限就绪重试，应用退出时关闭子进程。Miniconda TensorBoard 按仓库 `requirements.txt` 升级为 `2.21.0`。
- 验证：前端 9 个聚焦测试文件 `74 passed / 19 skipped`；训练 API 与 TensorBoard 后端 `19/19 passed`；生产构建通过，仅有既有 ECharts 大 chunk warning。真实 TensorBoard 子进程 smoke 返回 HTTP `200`，在第 2 次探测就绪；当前后端以 `uvicorn --reload` 运行，修改可自动重载。
- 剩余：未提交、未推送、未执行远程门禁；生产模式仍要求显式 `TENSORBOARD_GATEWAY_URL` 和 `TENSORBOARD_SESSION_SECRET`，本地回退不会放宽生产校验。

## 41. 最新执行记录（2026-08-27，训练任务 AutoML 操作禁用与对齐）

- 需求：普通训练任务继续提供“恢复”和“TensorBoard”；AutoML 任务保留按钮但置灰不可点击。训练任务表“操作”表头左对齐，行内操作内容居中对齐。
- 修复：前端依据 `operator_id === "automl"` 判断 AutoML，为恢复/TensorBoard 行操作传入 `disabled`；训练任务操作列增加 `onHeaderCell` 左对齐、`onCell` 居中对齐，并以专属 CSS 覆盖 fixed/sticky 单元格默认样式。
- 验证：`TrainingJobsPage` 聚焦测试 `7/7 passed`；前端生产构建通过（仅既有 ECharts chunk warning）；全量 Vitest `6/7` 文件通过，`weekAcceptance.test.ts` 因现有测试清单未登记 `TableRowAction.test.tsx` 与 `OrchestrationPage.test.tsx` 失败；`git diff --check` 通过（仅 CRLF 提示）。
- 剩余：未提交、未推送、未执行远程门禁；全量 acceptance 清单缺失项需单独补登记后再复跑。

## 42. 最新执行记录（2026-08-27，实验操作列与训练操作提示文案）

- 需求：实验列表“操作”表头左对齐、行内容居中；训练任务恢复和 TensorBoard 的悬停提示统一显示为“恢复”和“TensorBoard”，不再附带任务名称。
- 修复：实验操作列增加 `onHeaderCell`/`onCell` 对齐约束及专属 CSS；训练任务恢复/TensorBoard 使用通用本地化标签作为 Tooltip 与 aria-label，详情、停止、删除仍保留任务名以便区分对象。
- 验证：`TrainingJobsPage` 聚焦测试 `7/7 passed`；生产构建和差异检查需在本轮最终变更后复跑。

## 43. 最新执行记录（2026-08-27，详情操作提示统一）

- 需求：AutoML 和普通训练任务的“详情”提示均只显示“详情”。
- 修复：训练任务详情操作使用通用本地化标签，不再拼接任务名称；测试同步覆盖普通任务和 AutoML 任务。
- 验证：`TrainingJobsPage` 聚焦测试 `7/7 passed`。

## 44. 最新执行记录（2026-08-27，实验与训练任务操作列样式统一）

- 需求：实验和训练任务表的“操作”列使用同一套样式。
- 修复：两张表的操作列统一使用 `training-operation-column`，保留表头左对齐、行内容居中和操作按钮组居中规则，避免页面分别维护样式。
- 验证：`TrainingJobsPage` 聚焦测试 `7/7 passed`；生产构建需在本轮最终变更后复跑。

## 45. 最新执行记录（2026-08-27，移除任务表操作列固定定位）

- 需求：训练任务和实验列表当前宽度足够，不再固定“操作”列，避免固定列带来的额外滚动体验。
- 修复：移除两张表操作列的 `fixed: "right"`，保留统一操作列 class 和窄屏横向滚动保护。
- 验证：`TrainingJobsPage` 聚焦测试 `7/7 passed`；生产构建通过；`git diff --check` 通过。

## 46. 最新执行记录（2026-08-27，实验与训练任务操作列右对齐）

- 需求：实验和训练任务列表中的“操作”列统一右对齐。
- 修复：两张表操作列的表头、单元格和按钮组统一采用右对齐/末端布局。
- 验证：`TrainingJobsPage` 聚焦测试 `7/7 passed`；生产构建通过；`git diff --check` 通过。

## 47. 最新执行记录（2026-08-27，自动建模允许选择已有实验）

- 问题现象：自动建模新建任务的实验下拉会过滤已经运行过 AutoML 的实验，用户无法复用已有实验。
- 根因：项目实验加载后按 `!item.automl_used` 过滤，只保留未使用实验；同时只兼容 `{items: []}` 响应结构。
- 修复：移除 `automl_used` 前端过滤，项目下所有可访问实验均可选择；兼容数组和分页对象两种响应结构，并默认选择接口返回的第一个实验。
- 验证：`AutoMLPage` 聚焦测试 `5 passed / 19 skipped`；生产构建和差异检查需在本轮最终变更后复跑。

## 48. 最新执行记录（2026-08-27，保留实验唯一 AutoML 约束并级联删除）

- 需求修正：继续保留“一个实验只能有一个 AutoML 任务”；自动建模删除普通 AutoML 任务时，同时删除模型训练中的对应训练任务和实验。
- 根因：实验列表序列化遗漏 `automl_used/automl_job_id`，前端无法识别已绑定实验；自动建模删除复用通用训练任务批量删除，只删除 `training_jobs`，永久实验绑定和实验记录仍保留。
- 修复：实验列表补齐 AutoML 绑定字段；已有但未绑定的实验可选，已绑定实验保留显示但禁用。新增 `DELETE /api/training/automl/jobs/{job_id}`，仅允许删除终态 AutoML 任务，并在同一审计事务中删除训练任务及对应实验；前端删除后刷新任务和实验列表。
- 验证：AutoML API `21/21 passed`；AutoMLPage + TrainingJobsPage `12 passed / 19 skipped`。实验 API 全组存在既有失败：`cancel_requested` 已被共享终态集合纳入可删除状态，但旧测试仍要求阻止实验删除，本轮未将其计为通过。

## 49. 最新执行记录（2026-08-27，任务列表删除确认统一）

- 问题现象：不同任务及资源列表的删除操作混用直接调用、`window.confirm`、页面内 `Popconfirm` 和 `Modal.confirm`；部分按钮初次点击立即请求删除，单行与批量确认的标题、位置、危险色和中英文说明不一致。
- 根因：页面只复用了行操作图标，没有共享删除确认合同；各模块分别维护确认文案和回调，旧标注任务列表还保留文字删除按钮。
- 修复：新增公共 `DeleteConfirmation`，统一使用 Ant Design `Popconfirm`、`placement="topRight"`、不可恢复说明、红色确认按钮和中英文回退；单行删除继续使用红色垃圾箱图标，批量删除保留工具栏危险按钮。项目、数据集、两套标注任务、AutoML、实验、训练任务、注册模型、推理部署、编排任务和智能体均改为只有 `onConfirm` 才调用原删除 API；禁用项不弹出，停止、回滚、审批和重新生成报告等非删除确认保持原逻辑。
- 验证：10 个聚焦测试文件 `80 passed / 19 skipped`，覆盖打开、取消、确认、禁用、单行和批量数量说明；TypeScript 与 Vite 生产构建通过，仅有既有 ECharts 大 chunk warning；`git diff --check` 通过。
- 剩余：未提交、未推送、未执行远程门禁；知识库、用户管理、工作流卡片等非本次任务列表范围的删除确认未迁移。

## 50. 最新执行记录（2026-08-27，工作台实时模型统计与窄删除确认框）

- 问题现象：工作台“模型总数”和“模型状态”继续读取旧 `ModelLibrary.status`，无法反映真实 AutoML/普通训练任务；任务删除后页面未广播统计变化，只能等待轮询。删除确认弹层也会随文案扩展得过宽。
- 根因：工作台将训练任务、注册模型和推理部署三个生命周期误合并到旧模型库状态；AutoML 和训练任务成功新增、停止、恢复、删除后没有统一触发工作台重新请求；公共 `DeleteConfirmation` 没有弹层尺寸合同。
- 修复：按用户确认的互斥口径聚合真实实体：`pending/queued/running/cancel_requested` 为训练中，`completed` 且未运行部署为已完成，已关联 `observed_state=running` 推理部署的完成任务为已发布，失败和取消任务不计入模型资产；模型总数等于三类之和，API 总数继续来自当前用户可访问的 `PlatformAPI`。发布关系同时支持 `model_library_id` 和 `model_artifact_id` 两条来源链路。AutoML、普通训练和部署成功 mutation 后广播统一事件，工作台新增 focus/visibility 即时刷新并保留 15 秒轮询。删除确认框统一为 280px，移动端最大宽度为视口减 32px。
- 验证：后端 dashboard 集成测试 `8/8 passed`，覆盖互斥状态、运行部署、失败/取消排除、权限范围以及直接删除任务/API 后重新请求数量下降；前端 5 个聚焦测试文件 `34 passed / 19 skipped`；TypeScript 与 Vite 生产构建通过，仅有既有 ECharts 大 chunk warning；Python 语法编译和 `git diff --check` 通过。
- 剩余：未提交、未推送、未执行远程门禁；worker 异步状态变化通过 15 秒轮询或页面重新聚焦同步，不是服务端推送。

## 51. 最新执行记录（2026-08-27，全部变更发布前门禁修复）

- 问题现象：准备将当前工作区全部变更发布到 `main` 时，完整前端测试因 4 个新增测试文件未登记开发周失败；后端综合测试发现实验删除允许 `cancel_requested` 任务关联实验被删除，以及质量建模创建任务引用未初始化的 `run_configuration`。
- 根因：验收清单没有随新增测试同步更新；共享训练终态集合为任务删除包含 `cancel_requested`，但实验生命周期仍需将其视为阻塞状态；数据标注分支重构后，质量建模分支错误复用了仅在另一分支赋值的局部变量。
- 修复：将新增公共操作组件、旧标注页和编排页测试登记到 Week 12；实验删除改用明确的 `pending/queued/running/cancel_requested` 阻塞集合；质量建模配置恢复直接读取请求中的目标列、数据类型和输入列。
- 验证：聚焦回归前端 `7/7 passed`、后端 `51 passed / 11 subtests passed`；完整前端 `239 passed / 19 skipped`；后端综合测试 `202 passed / 41 subtests passed`，仅保留既有依赖弃用警告。
- 剩余：等待生产构建、暂存差异检查、Git 提交和 GitHub `main` 推送验证。

## 52. 最新执行记录（2026-08-28，弱监督默认“其他”兜底规则）

- 需求：数据标注的自动标注流程启用“弱监督标注策略”时，在“标注规则与标签”中默认增加“其他”规则，表达未命中用户普通规则的所有情况；该规则可以删除，仅允许编辑标签名称。
- 根因：原有 `process_rules` 只有条件 token，没有显式兜底语义；未命中规则时直接保留模型预测，前端也无法用稳定合同区分普通规则和“所有其他情况”。
- 修复：前后端规则合同增加兼容性的 `kind: condition | fallback`，历史缺省规则按 `condition` 处理。启用弱监督时前端仅在不存在兜底项时追加默认“其他 / Other”；兜底条件只读显示“除以上规则之外 / All other cases”，标签可编辑并可使用右上角删除按钮删除。序列化和标签类型校验识别兜底规则。后端限制最多一条兜底规则且要求空 tokens，先匹配全部普通规则，均未命中时才返回兜底标签；删除兜底规则后继续沿用模型预测。
- 验证：TDD 首次前端用例因找不到默认“其他”规则失败；实现后前端 `DataAnnotationPage + spotWeldQuality API` 测试 `43/43 passed`。后端服务与 API 聚焦测试 `4 passed / 3 subtests passed` 和 `1 passed`，相关完整测试 `74 passed / 25 subtests passed`；前端 TypeScript/Vite 生产构建通过，仅保留既有 ECharts 大 chunk warning；后端 `py_compile` 和 `git diff --check` 通过。
- 剩余：尚未在已登录真实浏览器会话中执行中文/英文视觉复核；当前工作区存在其他并行 CI、验收、迁移和编排修改，本功能未覆盖或回退这些变更。
## 53. 最新执行记录（2026-08-28，手动标注状态展示收敛）

- 需求：数据标注中的手动标注任务只展示“运行中”和“已完成”；自动标注任务状态保持不变。
- 根因：前端任务列表和工作区直接使用通用状态映射，手动任务的失败、取消状态会透出到用户界面。
- 修复：保留后端真实状态和控制逻辑不变；`DataAnnotationPage` 对手动任务将 `completed` 映射为“已完成”，其余状态映射为“运行中”，并同步状态颜色；自动任务继续使用通用状态映射。
- 验证：`DataAnnotationPage.test.tsx` `38/38 passed`；前端 `npm run build` 通过，仅有既有 ECharts 大 chunk warning；`git diff --check` 通过。
- 剩余：未执行真实登录浏览器视觉复核、提交或远程门禁；工作区其他并行修改未纳入本次验证。

## 54. 最新执行记录（2026-08-28，API 市场导航入口与接口路径修复）

- 问题现象：API 市场页面虽有路由，但侧边栏没有入口；页面请求使用了相对 `/api` 客户端下的重复 `/api` 前缀，且直接访问后端地址的 `/api-marketplace` 返回 404。
- 根因：导航菜单遗漏 `/api-marketplace`；`apiGet`/`apiDelete` 已配置 `baseURL=/api`，页面又传入 `/api/platform/apis`，导致接口路径重复。
- 修复：侧边栏加入 API 市场菜单项；API 页面改用 `/platform/apis` 和 `/platform/apis/{id}`，最终请求为 `/api/platform/apis`；前端路由保持 `/api-marketplace`，必须通过前端端口访问。
- 验证：AppLayout 与 API 页面聚焦测试 `8/8 passed`；前端生产构建通过；`git diff --check` 通过。
- 剩余：当前 `/api/platform/apis` 仍要求有效登录 Token；未执行真实登录浏览器复核、提交或远程门禁。

## 54. 最新执行记录（2026-08-28，全部本地变更发布到 main）

- 发布范围：将本地 `main` 相对 `origin/main` 的全部提交和工作树变更统一纳入发布，包括弱监督默认“其他”兜底规则、手动标注状态展示收敛、Agent 任务归属迁移与权限处理、Week 12 MinIO fixture 隔离、证据清单迁移头更新以及对应设计、计划和测试。
- 发布前审计：确认当前仓库是普通主工作区，分支为 `main`，工作树干净；受控重试 `git fetch origin main --prune` 成功，确认 `origin/main` 是本地 `HEAD` 的祖先，不需要冲突合并或强制推送。
- 验证：完整前端 Vitest `242 passed / 19 skipped`；前端 TypeScript/Vite 生产构建通过，仅有既有 ECharts 大 chunk warning；后端综合回归 `280 passed / 2 skipped / 164 subtests passed`；编排权限专项 `25 passed / 24 subtests passed`；Python `compileall`、`git diff --check origin/main..HEAD` 均通过。后端仅保留既有 `python_multipart` 弃用警告。
- 发布策略：全部本地提交和本记录通过普通非强制 `git push origin main` 发布；推送后必须重新获取远端引用并确认本地 `HEAD`、`origin/main` 和 GitHub `refs/heads/main` SHA 一致，工作树保持干净。

## 55. 最新执行记录（2026-08-28，API市场与应用编排完成计划）

- 用户确认需要为“API市场”和“应用编排”编写实现计划；本轮只写计划，不宣称功能已完成。
- 已将范围拆为两个可独立交付的计划：`ml-platform/docs/superpowers/plans/2026-08-28-api-management-completion.md` 与 `ml-platform/docs/superpowers/plans/2026-08-28-agent-orchestration-completion.md`。
- API市场计划先于应用编排执行，原因是其依赖面较小；计划覆盖 Pydantic 契约、Alembic 迁移、项目权限、发布幂等、同源认证测试、工作台统计、前端 CRUD、TDD、Playwright 和文档。
- 应用编排计划明确当前原型缺口：规划未调用 LLM、计划未持久化、无 DAG worker 执行、审核仅在进程内存；计划覆盖持久化 plan/node/edge/attempt/review/message、状态机、调度/重试/取消/恢复、前端命令和 API 发布前置条件。
- 状态：`planned`。尚未执行实现、迁移、测试、真实登录浏览器验收或远端门禁；现有工作树用户修改保持不变。

## 56. 最新执行记录（2026-08-29，按顺序开始 API 管理实现）

- 执行顺序确认：先完成 API 管理，再开始应用编排；本轮未修改应用编排代码。
- 已完成 API 第一阶段：`PlatformAPI` 增加来源/发布元数据字段；新增 `20260829_14_api_management_contract` Alembic 迁移；创建接口改为 Pydantic 契约和 `201` 响应；校验 API 类型、HTTP method、内部 `/api/` endpoint；更新接口增加状态转换校验；统计接口返回 published/offline/failed/total_calls；前端 API 市场增加新建、编辑、状态数据展示、统一删除确认和同源测试地址。
- 验证：全新 SQLite 数据库 Alembic 链升级至 `20260829_14` 成功；后端 API 平台测试 `8/8 passed`；前端 API 市场聚焦测试 `1/1 passed`；前端生产构建通过（仅既有大 chunk warning）；`git diff --check` 通过。
- 当前未完成：模型/编排发布幂等服务、完整 owner/member 权限矩阵、API 端到端浏览器验收、完整 i18n/error-state 回归和远端门禁。API 管理仍为 `in_progress`，应用编排保持 `pending`。

## 56. 最新执行记录（2026-08-28，修复当前 SHA 前端验收清单漏项）

- 问题现象：当前 SHA `420a6c8848fc095dfa1e76e0f1c12cb91ec07592` 的远端 Run `33138556778` 中，Windows/Ubuntu Quality 的后端 `113/113` 通过、前端实际测试 `243 passed / 19 skipped`，但 `weekAcceptance.test.ts` 失败，导致后续 Production、Chromium 和 Week 11-12 作业均为 `skipped`。
- 根因：新增的 `src/pages/APIMarketplacePage.test.tsx` 已被 Vitest 自动发现，但没有加入 Week 12 的 `weekTestFiles` 台账；这是清单契约错误，不是产品测试失败。
- 修复：将 `./pages/APIMarketplacePage.test.tsx` 登记到 Week 12，保留清单的“每个测试文件恰好归属一个开发周”断言。
- 验证：本地前端全量 `49 passed`、`244 passed | 19 skipped`；清单专项通过；远端旧 Run 的 `failed/skipped` 状态不回写为通过。
- 当前验收状态：Week 9-12 仍为 `in_progress`。当前 SHA 尚未获得新的 full run；Week 11 的固定资源性能、PostgreSQL/MinIO 备份恢复、N-1 升级三组真实证据及最终 `evidence_manifest.py` 仍未在当前 SHA 闭环。

## 57. 最新执行记录（2026-08-28，Run 33143998452 成功后的证据收口）

- 远端 Run `33143998452` 已完成 `success`，绑定 SHA `53ae360a7d050b48ca6b32d502e90958bcd327b9`；Quality 双平台、Production 双集成、Chromium 和 Week 11-12 job 均为 `success`。
- 制品核验：Week 11-12 artifact 仅包含 `environment.json`、security、runtime-images 和 web security；Chromium artifact 包含 `playwright/result.json`。未包含 `performance/summary.json`、`backup/restore-result.json` 或 `upgrade/result.json`。
- 当前 SHA 本地性能复跑已生成全部场景原始结果并绑定 `53ae360...`，但 `warm-inference` 超过阈值，`performance/summary.json` 为 `status=failed`；其余 core-read、enqueue、cold-model-load、welding-e2e 通过。
- 备份恢复复跑被本地 MinIO 客户端挂载阻断：`/tmp/mc.acceptance` 是目录而非可执行 `mc` 文件，工具返回 `mc: Permission denied`。未将该次尝试记为通过，也未伪造 `restore-result.json`。
- 当前验收状态仍为 `in_progress`。Week 11 三组真实证据尚未全部 `passed`，最终 `evidence_manifest.py` 不得运行通过或标记总体完成。

## 58. 最新执行记录（2026-08-28，修复推理运行时并发配置）

- 问题现象：当前 SHA 性能复跑中 warm-inference 2000 请求全部返回 200，但 P95 `929-1001ms`、P99 `1377-1469ms`，超过 `200/500ms` 门槛。
- 根因：`Dockerfile.inference` 将 Uvicorn worker 固定为 1，验收并发请求集中在单 worker 进程。
- 修复：推理镜像新增 `INFERENCE_RUNTIME_WORKERS` 环境变量，默认 4，Uvicorn 使用该值启动；生产可显式覆盖，未修改限流阈值。
- 验证：Dockerfile 变更已完成静态检查；需在新镜像上重新执行性能证据，并与新 SHA 的镜像 provenance 一致后才能判断是否达标。
- 当前状态：该修复会改变镜像与提交 SHA，最终仍需一次新的完整远端门禁和三组 Week 11 证据；未将旧性能失败结果改写为通过。

## 59. 最新执行记录（2026-08-28，验收提交边界更新）

- 推理并发修复已提交并推送，当前 `HEAD=6cceaa00b3b38db88a1a788df807dfeb0a03f775`；Run `33143998452` 仍只绑定上一 SHA `53ae360...`，不能作为当前 HEAD 的最终验收证据。
- 已完成本地 Dockerfile 构建验证和差异检查；当前性能失败结果、备份恢复阻断记录和历史证据均保留。
- Week 9-12 仍为 `in_progress`。在不重新执行当前 SHA 的远端门禁、重新生成镜像 provenance 及三组 Week 11 真实证据前，不得运行通过最终 manifest 或标记验收完成。

## 60. 最新执行记录（2026-08-28，推理并发修复后性能复核）

- 新镜像 `INFERENCE_RUNTIME_WORKERS=4` 已成功构建并启动；固定负载性能复核绑定 `6cceaa00b3b38db88a1a788df807dfeb0a03f775`。
- `core-read`、`enqueue`、`cold-model-load`、`welding-e2e` 场景完成；`warm-inference` 三轮仍失败，P95 `890-943ms`、P99 `1332-1476ms`，远高于 `200/500ms` 阈值。
- 结论：单纯增加 Uvicorn worker 未解决主要瓶颈，不能继续通过修改阈值或重复同一脚本宣称通过；需进一步 profiling/架构优化后再生成性能证据。
- 当前状态：Week 9-12 仍为 `in_progress`；备份恢复与 N-1 证据仍未生成，最终 manifest 仍被阻断。

## 61. 最新执行记录（2026-08-28，Week 11 证据再次核验）

- 备份恢复真实重跑已绕过错误的 `mc` 目录挂载并加入 Compose 网络；fixture seed 成功，但 `backup-postgres` 返回 `127`，后端运行镜像未提供 `pg_dump`，因此未生成可通过的 `restore-result.json`，W11-R2 仍为 `blocked`。
- N-1 runbook 已修正目标 revision 为 `20260826_13`（与 `upgrade_fixture.py` 的 `EXPECTED_HEAD` 一致）；实际容器执行还发现临时 backend 容器未挂载升级脚本，未产生当前 SHA 的升级证据，W11-R3 仍为 `missing/blocked`。
- 当前性能证据仍绑定 `6cceaa00b3b38db88a1a788df807dfeb0a03f775` 且 `warm-inference` 超阈值失败；未修改阈值或伪造结果。
- 当前结论：Week 9-12 不能关闭，最终 `evidence_manifest.py` 继续保持阻断。需要将备份/N-1 执行器纳入可复用的受版本控制运行路径，并提供 PostgreSQL 客户端工具后再做一次真实证据生成。

## 62. 最新执行记录（2026-08-28，受版本控制的 Week 11 执行器修复）

- 已将 WP3/WP4/WP5 执行器置于 `ml-platform/backend/tools/acceptance/`，CI 的 Week 11-12 verification 在安全扫描和 frozen-stack web gate 后同一 job 内执行真实性能、备份恢复和 N-1 流程，再下载 Playwright receipt 并生成 final evidence manifest。
- 性能运行器不再停掉 Compose backend 后用历史 `/tmp/week9-12-secrets` 手工重建容器；它保留 Compose 管理的 secret、证书、网络和运行时环境，在既有 backend 内生成原始结果，再复制到版本化 evidence 目录。新增回归合同拒绝旧临时路径和手工 `docker run`。
- 对第 58-60 节的并发尝试补充更正：推理运行时拥有进程内 `RuntimeRegistry`，多 Uvicorn worker 不能共享已部署模型状态，会产生非 owner worker 的 `DEPLOYMENT_NOT_READY`。运行时镜像已恢复固定单 worker；性能门槛未修改，必须使用该候选提交重新实测。
- 验证：Week 11/12 工具、镜像和 CI 合同 `158/158` 通过；所有 acceptance shell 的 `bash -n` 通过；尚未获得该候选提交的 WP3/WP4/WP5 实测结果、远程 full run 或 final manifest，因此 Week 9-12 保持 `in_progress`。

## 63. 最新执行记录（2026-08-29，唯一 full CI 与最终 manifest 结果）

- 当前提交 `aa70e1fbb60a2e3b859a961bd5826677b014a3e1` 已推送到 `origin/main`，本地 `HEAD`、远端分支和 GitHub `refs/heads/main` 一致。
- 本地顺序验收已全部通过并绑定当前提交：固定资源性能 `status=passed/candidate_status=passed`，三轮 warm-inference P95 约 `151/157/170ms`；PostgreSQL/MinIO 备份恢复 `status=passed`，行数、外键、3 个对象 SHA-256、RTO/RPO 均通过；N-1 从 `20260720_10_security_notifications` 到 `20260826_13` 两次升级、`alembic check`、API/ready/worker smoke 均通过。
- 唯一远程 full run `33179479206` 绑定当前提交。Quality Windows/Ubuntu 和 Chromium acceptance 均 `success`，Chromium receipt 为 `passed=1,total=1,failed=0`；Production integration 在 `30` 分钟 job 上限被取消，Production experiment integration 在 `35` 分钟 job 上限被取消，Week 11-12 verification 因依赖取消而为 `skipped`。
- 已下载该 run 的全部可用制品；只有 Playwright evidence，未生成 `security/summary.json`、`security/runtime-images.json` 或 Week 11-12 verification artifact。最终 `evidence_manifest.py` 已执行并按 fail-closed 规则失败，明确缺少上述两个安全证据文件。
- **唯一剩余根因：远程 full CI 的两个生产集成 job 在依赖安装/镜像构建仍运行时达到 30/35 分钟 job timeout，导致后续安全汇总与 Week 11-12 verification 被取消/跳过。** 本轮不再触发第二次 CI，不标记 Week 9-12 完成；当前总体保持 `in_progress`。

## 64. 最新执行记录（2026-08-29，修复冷缓存验收超时）

- 已核对 Run `33179479206` 的完整 job 日志：Production integration 在 backend `pip install` 阶段耗满 30 分钟；Production experiment integration 的四个镜像并行重复下载 `xgboost` 131.7 MB 和 `catboost` 97.2 MB，耗满 35 分钟，均未进入业务测试。
- 已将 `.github/workflows/ci.yml` 的 Production integration timeout 调整为 `60` 分钟，Production experiment integration timeout 调整为 `90` 分钟；实验作业增加 `COMPOSE_PARALLEL_LIMIT=1` 和 Buildx 初始化，使共享 requirements 层串行构建并复用缓存，避免冷 runner 上的带宽竞争。
- 已新增 CI 合同测试，锁定生产作业冷缓存预算、实验作业串行构建约束和 Buildx 初始化；本地 `tests.test_ci_workflow` 为 `45/45 OK`，`git diff --check` 通过。
- 该修复改变了 workflow source SHA；必须提交推送后重新触发唯一一次 full CI，重新取得当前 SHA 的 security、runtime-images、Playwright、Week 11 三组真实证据并运行最终 `evidence_manifest.py`。在此之前 Week 9-12 保持 `in_progress`。

## 65. 最新执行记录（2026-08-29，Week 11 运行器密钥权限阻断）

- Run `33229492059` 绑定当前提交 `3ecf2830f968d2372bb340784c78d61bf083858f`；Quality 双平台、Production 双集成和 Chromium acceptance 均为 `success`，Week 11-12 verification 在 `Run live Week 11 acceptance evidence` 失败。
- 真实日志显示 frozen-stack web security gate 成功；随后 `run_week11_acceptance.sh` 重新启动 security image Compose 栈时，`migrate` 服务退出 `1`，导致性能、备份恢复、N-1、汇总和最终 manifest 均未执行。根因是前一步 cleanup 删除了由 CI 设置为 UID `1000:1000` 的通知密钥，运行器重新生成密钥后只设置 `0600`，生产镜像以 UID 1000 读取失败。
- 修复：运行器生成或复用密钥后统一执行 `sudo chown 1000:1000` 和 `sudo chmod 0400`；Compose 启动失败时输出 `migrate` 日志。新增独立 stdlib 回归合同，先验证缺失权限合同时失败，再验证修复后通过；`bash -n` 和该回归测试均通过。
- 当前状态：Week 9-12 仍为 `in_progress`；Run `33229492059` 不计入验收。修复提交并推送后，只再触发一次 full CI，必须重新生成当前 SHA 的 security、Playwright、performance、backup/restore、upgrade 和最终 `evidence_manifest.py`，全部通过后才可关闭验收。

## 66. 最新执行记录（2026-08-29，修复 Week 11 回归测试台账阻断）

- 问题现象：权限修复提交 `90d14a147e49efd9216e73672f42752c79bdbae0` 的 Quality 作业在 `test_suite_manifest` 失败，业务测试未执行失败；自动发现的 `test_week11_runner_contract.py` 未登记到周测试归属清单。
- 根因：新增独立测试模块后未同步 `tests/week_manifest.py`，违反“每个测试模块恰好一个周归属”的合同。
- 修复：将通知密钥 UID/权限回归断言并入已登记的 `test_week11_12_tools.py`，删除独立未登记模块；不修改用户未提交的 API 市场变更。
- 本地验证：模块归属清单通过；仓库环境缺少 `fastapi`、`httpx` 等 `requirements.txt` 依赖，完整后端导入测试无法启动；待远端 Quality 环境验证。`bash -n`、`git diff --check` 和 Python 编译检查在提交前完成。
- 验收状态：保持 `in_progress`。提交推送后仅允许触发一次当前 SHA full CI；只有 Quality、Production、Chromium、Week 11-12 verification 以及最终证据清单全部成功，且制品绑定当前 SHA，才能关闭 Week 9-12。

## 67. 最新执行记录（2026-08-29，API 管理继续实现）

- 完成模型部署与 API 目录生命周期同步：部署 `start` 成功后自动创建或恢复唯一的 `source_kind=model` API；重复启动保持幂等；`stop` 成功后将同一 API 标记为 `offline`，从未发布的部署停止不会报 API 不存在错误。
- 完成后端边界：手工创建仅允许 `custom` API；来源绑定 API 禁止直接编辑或删除；公开 API 对非所有者只读；部署发布权限区分 viewer `403` 与项目外用户隐藏 `404`；数据库增加 `(source_kind, source_id, version)` 唯一约束并纳入 `20260829_14` 迁移。
- 完成前端 API 市场测试器修复：使用 Axios `apiClient.request` 自动携带认证，强制同源内部路径；新增/编辑 payload 测试、加载失败可见状态和自定义 API 表单约束。
- 验证证据：后端 `test_api_platform` 13/13、`test_api_model_registry` 11/11、独立迁移后 `test_api_dashboard` 8/8、前端 `APIMarketplacePage.test.tsx` 5/5、前端生产构建通过、`git diff --check` 通过；全新 SQLite 已升级至 `20260829_14 (head)`。
- 浏览器验收受环境阻断：本地前后端均已启动，但 Codex In-app Browser 访问 `http://127.0.0.1:5173/api-marketplace` 和 `http://localhost:5173/api-marketplace` 均报告 `ERR_BLOCKED_BY_CLIENT`，未将其误记为通过。API 管理仍保持 `in_progress`，应用编排继续 `pending`，待可用浏览器环境完成真实登录 CRUD/测试验收后再收口。

## 68. 最新执行记录（2026-08-29，API 市场实时统计摘要）

- API 市场页面新增实时统计摘要，初始化和每次 mutation 后并行重新读取 `/platform/apis` 与 `/platform/apis/stats`，展示 API 总数、已发布、已下线和调用总数；统计不由前端列表长度推算。
- 新增组件回归覆盖统计接口请求及数值展示；前端 API 市场测试 `6/6 passed`，生产构建通过。
- API 管理仍为 `in_progress`：真实登录浏览器验收仍受 `ERR_BLOCKED_BY_CLIENT` 阻断，未开始应用编排。

## 67. 最新执行记录（2026-08-29，修复高并发遥测跨表死锁）

- 问题现象：Run `33234445251` 的 Week 11 runner 在 live acceptance 内退出；性能制品显示 `warm-inference` 三轮 P95 为 `217.4–221.1 ms`，超过未修改的 `200 ms` 门槛。PostgreSQL 日志同时出现 `inference_api_keys.last_used_at` 与 `inference_metric_buckets ... FOR UPDATE` 的死锁。
- 根因：`_persist_observation` 在同一事务中先更新 API key，再锁定并更新分钟聚合桶。高并发遥测使不同事务以相反的跨表锁顺序等待，既造成死锁，也占用生产请求共享的数据库资源。
- 修复：遥测先提交 `InferenceRequestLog` 和分钟桶聚合，释放聚合锁；随后在同一 Session 的新事务中使用 60 秒条件更新 `last_used_at`，不再让两张表的锁重叠。新增回归测试锁定先提交指标、后触碰 API key 的顺序。
- 本地验证：相关 Python 文件编译通过；`tests.test_ci_workflow` `45/45` 通过；四个 acceptance shell `bash -n` 通过；`git diff --check` 通过。完整后端回归尚未在本机执行，因缺少 `requirements.txt` 中的 `fastapi`、`pydantic` 等依赖。
- 剩余：提交并推送该修复后，只触发一次最终 full CI；必须取得同一 SHA 的 security summary、runtime-images、Playwright、performance、backup/restore、upgrade 和 `evidence_manifest.py` 全部通过制品，之后才可关闭 Week 9–12。

## 69. 最新执行记录（2026-08-29，统一迁移 head 台账）

- Run `33241458084` 绑定提交 `d089ee9d0540693d007332d1f13bf223f77c8c7d`，Quality Windows/Ubuntu 均在 `test_upgrade_head_twice_creates_complete_schema` 失败；真实失败不是业务回归，而是 API 管理迁移已将 Alembic head 推进到 `20260829_14`，验收测试和工具仍固定旧值 `20260826_13`。
- 已将 `test_database_production.py`、`test_evidence_manifest.py`、`test_inference_production_stack.py`、`test_week11_12_tools.py`、`upgrade_fixture.py`、`evidence_manifest.py` 和 `run_upgrade_fixture.sh` 的发布 head 统一为 `20260829_14`，并保留 `20260826_13` 作为迁移链中的父 revision；未修改性能阈值或伪造历史证据。
- 本地验证：上述 Python 文件编译通过，四个 acceptance shell `bash -n` 通过，`tests.test_ci_workflow` `45/45` 通过，`git diff --check` 通过。当前工作树仍保留用户未提交的 `ml-platform/frontend/src/pages/APIMarketplacePage.test.tsx`，未纳入本次修复。
- 当前状态：Week 9–12 仍为 `in_progress`。提交并推送本次修复及已有 API 市场提交后，只允许触发一次最终 full CI；必须取得同一 SHA 的 Quality、Production integration、Production experiment integration、Chromium acceptance、Week 11–12 verification，以及 security/runtime-images、performance、backup/restore、upgrade 和最终 `evidence_manifest.py` 全部通过制品，才可关闭验收。

## 70. 最新执行记录（2026-08-29，修复分钟指标桶首次创建竞态）

- 问题现象：Run `33242546889` 的真实性能请求全部返回 `200`，但 PostgreSQL 日志在并发遥测写入时多次报告 `duplicate key value violates unique constraint uq_inference_metric_buckets_deployment_minute`，遥测执行器因此记录未处理持久化异常，性能证据按 fail-closed 规则为 `failed`。
- 根因：`InferenceObservability._bucket` 使用“缺失行 `SELECT ... FOR UPDATE` 后再 INSERT”的非原子创建流程；并发事务都能在首个事务提交前观察到缺失行，savepoint 回退不能可靠覆盖 PostgreSQL 的唯一键竞争窗口。
- 修复：PostgreSQL 方言改用 `INSERT ... ON CONFLICT (deployment_id, bucket_start) DO NOTHING`，随后重新 `SELECT ... FOR UPDATE` 锁定获胜桶；SQLite/其他方言继续保留 savepoint 回退路径。新增回归测试锁定原子冲突安全 SQL。
- 验证：`test_inference_observability`、`test_api_inference_production`、`test_inference_production_models` 共 `31/31` 通过；Week 11/12 工具与 CI 合同 `150/150` 通过；四个 acceptance shell 经 Bash `-n` 检查通过；相关 Python 编译和 `git diff --check` 通过。后端全量回归在安全扫描 CLI 子进程处出现既有参数兼容错误 `--pip-audit-exception legacy-exception.json`，随后停止，不能记为全量通过。
- 当前验收：本机无 Docker，未宣称真实 PostgreSQL 竞态已在容器中复跑；未重新触发远端 CI。旧 Run 和旧 SHA 制品继续失效，Week 9–12 保持 `in_progress`。若要关闭，必须在包含本修复的当前 SHA 上重新生成 performance、backup/restore、N-1、security/runtime-images、Playwright 和最终 `evidence_manifest.py` 全部通过制品。

## 71. 最新执行记录（2026-08-29，Run 33249241089 完成后的当前 SHA 验收）

- Run `33249241089` 绑定 `4dacd2e685db5b6fbed672def32166783e5d0fbc`，总体结论为 `cancelled`。
- Quality Windows/Ubuntu、Production integration、Production experiment integration 均为 `success`；Chromium acceptance 在 `Install backend dependencies` 阶段达到 40 分钟 job 上限并为 `cancelled`；Week 11-12 verification 因依赖取消为 `skipped`。
- 该 Run 的全部可用制品已下载到 `temp_test/remote-run-33249241089/`，仅包含 `playwright-evidence/result.json`，其 `status=failed`、`passed=0`、`total=0`。当前 SHA 没有可用的 `environment.json`、`performance/summary.json`、`backup/restore-result.json`、`upgrade/result.json`、`security/summary.json` 或 `security/runtime-images.json`。
- 已使用远程 Run URL 调用 `evidence_manifest.py`；工具按 fail-closed 规则报告上述 7 项必需证据缺失，未生成 manifest，未修改任何旧证据或状态为通过。
- 唯一当前阻断根因：Chromium acceptance 冷 runner 在安装后端依赖时超过 40 分钟 job timeout，导致浏览器和 Week 11-12 verification 没有执行，后续当前 SHA 证据无法生成。Week 9-12 总体保持 `in_progress`。

## 72. 最新执行记录（2026-08-29，Chromium CI 超时修复已合并）

- 远端在本地提交期间先后推送 `aeda410`（Chromium timeout 40→60 分钟）和 `c7af3b7`（移除自定义 pip index URL）；未覆盖任何用户修改。
- 本地已将上述远端提交与验收台账合并；`ci.yml` 当前 Chromium timeout 为 `60` 分钟，Quality/Production/Week 11-12 的其他 timeout 保持既定值，默认 pip 源不再被 workflow 覆盖。
- 本地 CI 合同测试 `tests.test_ci_workflow` 为 `45/45 OK`，`git diff --check` 通过。合并后的候选提交尚未取得新的远程 full Run；Week 9-12 继续保持 `in_progress`。

## 73. 最新执行记录（2026-08-29，修复遥测 API key 高频写入）

- Run `33259324896` 绑定提交 `117e941ab504a8ba4ef64f794523a13250faf644`；Quality 双平台、Production 双集成和 Chromium acceptance 均为 `success`，但 Week 11-12 verification 在 `Run live Week 11 acceptance evidence` 失败，因此总 Run 为 `failure`。
- 该 Run 的环境、安全、runtime-images 和 Playwright 证据均绑定当前 SHA；真实性能原始结果也完整生成，但 `warm-inference` 三轮 2000 请求全部返回 200、错误率为 0，P95 分别为 `229.06/232.15/224.98 ms`，超过冻结的 `200 ms` 门槛；性能摘要为 `status=failed`，备份恢复、N-1 和最终 manifest 因前一步失败未生成。
- 根因：`_persist_observation` 在每个请求的后台任务中都执行一次条件 `UPDATE inference_api_keys` 和独立提交，即使 60 秒窗口内没有实际更新也会制造数据库事务；该额外写入与分钟聚合并发运行，增加生产请求的数据库争用。不是修改阈值或制品绑定问题。
- 修复：在 `app/api/inference_production.py` 增加线程安全的 60 秒进程内触碰节流；同一 API key 在窗口内只执行一次元数据更新，同时保留“先提交指标聚合、后更新 API key”的死锁修复。新增回归测试 `test_telemetry_does_not_touch_api_key_again_within_usage_interval`。
- 本地验证：推理、API key、观测、生产模型、Week 11/12 工具、Week 11 合同和 CI 合同共 `192` 项测试通过；`git diff --check` 通过。当前工作树修复提交尚未取得新的远程 full Run，Week 9-12 仍为 `in_progress`。
- 下一步：提交并推送该修复后，仅在最终 SHA 上触发一次 `workflow_dispatch mode=full`；必须取得六个 required jobs 全部 `success`，并下载同一 SHA 的性能、备份恢复、N-1、安全/runtime-images、Playwright 和最终 `evidence_manifest.py` 通过制品后，才能关闭验收。

## 74. 最新执行记录（2026-08-29，修复 Week 11 受保护密钥清理失败）

- Run `33264654621` 绑定提交 `4e6b6207ba7b13bbd6ac1f2e4c7da94906c0abfa`；Quality 双平台、Production 双集成和 Chromium acceptance 均 `success`。
- Week 11-12 verification 的性能、备份恢复、N-1、安全扫描、冻结栈 Web 安全门和 live acceptance 均已执行；live acceptance 本身完成后，runner 在 `Stop live Week 11 acceptance stack` 清理阶段失败。
- 唯一失败根因：CI 先以 `sudo chown 1000:1000`、`sudo chmod 0400` 保护 `/tmp/week12-security-notification-master.key`，但 `run_week11_acceptance.sh` 的 EXIT trap 与 workflow 的 `if: always()` 清理仍以普通用户执行 `rm -f`，日志报告 `Operation not permitted`，导致 job 失败并阻止最终 manifest 步骤完成。
- 修复：运行器 EXIT trap 和 workflow 清理统一改为 `sudo rm -f -- "$NOTIFICATION_CRYPTO_SECRET_FILE"`；新增 Week 11 runner 与 CI workflow 回归合同，防止权限回退。
- 本地验证：回归合同先在修复前按预期失败；修复后 `tests.test_week11_12_tools tests.test_ci_workflow` 共 `152/152` 通过，`bash -n tools/acceptance/run_week11_acceptance.sh` 和 `git diff --check` 通过。
- 当前状态：Week 9-12 仍为 `in_progress`。本次 Run 不计入关闭条件；修复提交推送后只触发一次新的 full CI，并必须重新获得当前 SHA 的六个 required jobs、security/runtime-images、performance、backup/restore、upgrade、Playwright 和最终 `evidence_manifest.py` 全部通过证据。

## 75. 最新执行记录（2026-08-29，修复推理 API-key 校验尾延迟）

- Run `33267537199` 绑定当前提交 `2f5df6b276ab377c6d9f5157f13dfadabd5df9be`；Quality 双平台、Production 双集成、Chromium acceptance 和安全扫描均成功，Week 11-12 verification 仅因真实性能摘要失败而失败。
- 当前 SHA 的真实性能原始证据完整生成，`cold-model-load`、`core-read`、`enqueue`、`welding-e2e` 均通过；`warm-inference` 三轮请求均为 HTTP `200` 且错误率 `0`，但 P95 为 `224.05/220.66/219.01 ms`，冻结门槛仍为 `200 ms`。
- 根因定位：生产推理路径每次请求都会从数据库重新读取 API-key 行并重复执行 PBKDF2 secret 校验；该校验结果不影响每次请求的撤销、过期、部署绑定或 scope 检查，却在固定并发下增加尾延迟。不是阈值、错误率、制品绑定或 CI skipped 问题。
- 修复：`InferenceApiKeyService` 增加进程内、TTL `300` 秒、最多 `1024` 项的 SHA-256 摘要缓存，仅复用已确认的 `(record_id, secret_hash)`；每次请求仍重新读取授权状态，secret hash 变化自动失效，缓存不保存 API-key 明文。新增跨实例回归测试，确认重复校验只执行一次且撤销后立即拒绝。
- 本地验证：API-key `6/6`、runtime `9/9`、推理/观测/Week 11/12/CI 合同 `184/184` 通过；`bash -n`、Python 编译和 `git diff --check` 必须在推送前再次执行。当前仍未取得修复 SHA 的远程性能、备份恢复、N-1、Playwright、安全汇总和最终 manifest，Week 9-12 保持 `in_progress`。
- 下一步：推送修复 SHA 后只触发一次 `workflow_dispatch mode=full`；仅当六个 required jobs、同 SHA 全部证据以及最终 `evidence_manifest.py` 均成功时，才允许关闭 W11-R1/R2/R3、W12-R1 和 Week 9-12 总体验收。

## 76. 最新执行记录（2026-08-29，API-key 修复提交前本地门禁）

- 已核对当前分支 `main` 与 `origin/main` 均指向 `2f5df6b276ab377c6d9f5157f13dfadabd5df9be`；用户此前修改的 `.github/workflows/ci.yml` 已包含在该提交中，工作树没有新的 CI 差异。
- 当前候选变更仅为 `InferenceApiKeyService` 的摘要校验缓存、跨实例/撤销回归测试和本条验收记录。缓存 TTL 为 `300` 秒、上限 `1024` 项，不保存明文；每次请求仍重新读取授权状态。
- 使用 Codex bundled Python 验证：API-key 测试退出码 `0`（6 项）；CI workflow 合同退出码 `0`（46 项）；Week 11/12 工具、合同和证据清单测试退出码 `0`；后端 `run_suite.py` 退出码 `0`。Python 编译、四个 acceptance shell 的 `bash -n` 和 `git diff --check` 均通过。
- 当前状态：Week 9-12 仍为 `in_progress`。尚未在修复后的新 SHA 上触发远程 full CI；不得复用 Run `33267537199` 的失败性能证据。
- 下一步：提交并推送当前候选 SHA；只触发一次 `gh workflow run ci.yml --ref main -f mode=full`，等待 Quality、Production、Chromium 和 Week 11-12 全部完成，下载同一 SHA 的全部制品并运行 `evidence_manifest.py`。只有 manifest 通过才可关闭验收。

## 77. 最新执行记录（2026-08-29，Run 33271973667 性能失败与并发 single-flight 修复）

- Run `33271973667` 绑定 SHA `815d712ad688b9ceb072af7ca1c32083a6f50f07`；Quality 双平台、Production 双集成和 Chromium acceptance 均为 `success`，Week 11-12 verification 在 live Week 11 runner 的性能摘要阶段失败。
- 真实性能证据显示五个场景均执行完成，HTTP 请求全部成功；唯一失败门禁为 `warm-inference-1` 的 P95 `203.112229599924 ms`，冻结门槛为 `200 ms`。`warm-inference-2/3` 分别为 `198.325159349838/182.731779350149 ms`。失败不是弃用警告、缺失制品或 skipped 作业。
- 根因：API-key 摘要缓存只解决串行重复校验；固定并发首批请求在同一缓存 miss 时仍同时执行 PBKDF2，造成首次 warm-inference 尾延迟抖动。新增 per-key single-flight 锁，并在锁内 double-check 缓存；继续每次从数据库读取撤销、过期、部署绑定和 scope 状态，缓存不保存明文。
- TDD 验证：先加入 `test_concurrent_verification_coalesces_a_cache_miss`，修复前确认 `8 != 1` 失败；实现后该回归和既有 API-key 回归通过。随后运行 `tests.test_inference_api_keys tests.test_api_inference_production tests.test_inference_observability tests.test_inference_production_models tests.test_week11_contracts tests.test_week11_12_tools tests.test_ci_workflow`，共 `196` 项通过。
- 当前状态：single-flight 修复尚未提交，Week 9-12 保持 `in_progress`。提交后只允许在新 SHA 触发一次 full CI；必须重新取得六个 required jobs、performance、backup/restore、N-1、security/runtime-images、Playwright 和最终 `evidence_manifest.py` 全部通过证据。

## 78. 最新执行记录（2026-08-29，Run 33276592294 证据目录权限修复）

- Run `33276592294` 绑定 SHA `ad7ad0f8cc630f7daab570c32c7b5ad9f13f9de5`；Quality 双平台、Production 双集成和 Chromium acceptance 均 `success`，Week 11-12 verification 在 live acceptance 阶段失败。
- 唯一失败根因：宿主 runner 创建的 `$ML_PLATFORM_EVIDENCE_DIR` 由 runner UID 拥有，而 Compose backend 镜像固定以 UID `1000` 运行；`run_week11_acceptance.sh` 通过 bind mount 将该目录挂载到 `/evidence` 后，`run_backup_restore.sh` 的 `mkdir -p /evidence/backup` 报 `Permission denied`，导致备份、N-1 和最终 manifest 未执行。不是业务、性能或安全扫描失败。
- 修复：两个一次性证据执行器的 `docker compose run` 均显式使用 `--user "$(id -u):$(id -g)"`，让容器使用宿主 runner UID 写入 bind mount，同时保持非 root；新增合同测试锁定两处参数。
- TDD/本地验证：修复前 `test_week11_evidence_executors_use_runner_uid_for_bind_mount_writes` 按预期失败；修复后 `AcceptanceRunnerContractTests 7/7`、`bash -n tools/acceptance/run_week11_acceptance.sh` 和 `git diff --check` 通过。
- 当前状态：Week 9-12 仍为 `in_progress`。本次 Run 的 Playwright、security、performance 等已生成但因 live runner 失败不能关闭；权限修复推送后只允许再触发一次当前 SHA 的 full CI，并重新绑定 backup/restore、N-1、summary、Playwright 和最终 manifest。

## 79. 最新执行记录（2026-08-30，临时容器密钥读取修复）

- Run `33282921412` 绑定提交 `568b20fb281a890a90290db26d10a2470556dad4`；Quality 双平台、Production 双集成和 Chromium acceptance 均 `success`，但 Week 11-12 verification 在 `Run live Week 11 acceptance evidence` 失败。
- 失败发生在 `run_backup_restore.sh` 调用 `seed_backup_fixture.py` 导入应用配置时：`NOTIFICATION_MASTER_KEY_FILE could not be read`。根因是前一轮权限修复让一次性容器使用宿主 runner UID 写入 evidence，但通知密钥仍为 `1000:1000`、`0400`，runner UID 无法读取该密钥。
- 修复：保留两个证据执行器的 `--user "$(id -u):$(id -g)"`，在运行器中使用 `sudo install` 创建仅供本次 runner UID 读取的 `0400` 临时密钥副本，并通过只读 bind mount 和 `NOTIFICATION_MASTER_KEY_FILE` 覆盖传入 backup/upgrade 临时容器；生产栈原始密钥权限不变。
- 本地验证：`AcceptanceRunnerContractTests` 及 Week 11/12 工具共 `108/108` 通过；验收 shell `bash -n`、Python 编译和 `git diff --check` 通过。Run `33282921412` 的失败证据不计入验收。
- 当前状态：Week 9-12 仍为 `in_progress`。提交本修复及本条记录后，只触发一次新的 `workflow_dispatch mode=full`；必须在同一新 SHA 上取得六个 required jobs、performance、backup/restore、N-1、security/runtime-images、Playwright 和最终 `evidence_manifest.py` 全部通过，之后才能关闭 W11-R1/R2/R3、W12-R1 和总体验收。

## 80. 最新执行记录（2026-08-30，临时 artifact cache 目录权限修复）

- Run `33285363236` 绑定 `ca84239c916813041a0eb5aceae6d95c371c2326`；五个前置 job 均 `success`，Week 11-12 verification 在 live acceptance 失败。
- 密钥读取修复已生效；新的唯一根因是 runner UID 的一次性容器在 readiness 检查构造 MinIOStorage 时无法创建 `/tmp/ml-platform/artifact-cache`。
- 修复：运行器创建 runner 拥有的 `0700` 临时目录，并将其挂载到两个一次性容器的 `/tmp/ml-platform`；生产服务仍使用原有容器临时目录。
- 本地需验证 runner 合同、shell 语法、Python 编译和差异检查；该 Run 未生成可关闭验收的完整 manifest，Week 9-12 保持 `in_progress`。

## 81. 最新执行记录（2026-08-30，Run 33287513144 性能失败与 ONNX 线程限制修复）

- Run `33287513144` 绑定 `d7991ea62657165d47253e1971068bdc6e7de562`；Quality 双平台、Production 双集成和 Chromium acceptance 均 `success`，Week 11-12 verification 在 live 性能阶段失败。
- 真实性能请求全部返回 HTTP 200 且错误率为 0；唯一失败门禁为 `warm-inference` 三轮 P95 `224.792/211.557/205.079 ms`，冻结门槛为 `200 ms`。容器启动、密钥读取、artifact cache 和清理均已成功，后续备份、N-1、manifest 因该门禁 fail-closed 未执行。
- 根因：推理运行时为每个 ONNX 会话使用默认线程池；4 vCPU 固定资源下与 20 路并发叠加造成 CPU 过度争抢和尾延迟超标。
- 修复：`RuntimeRegistry.load` 创建 ONNX `SessionOptions`，将 `intra_op_num_threads` 与 `inter_op_num_threads` 均固定为 `1`，保持模型输出和安全校验不变。
- 本地验证：`tests.test_inference_runtime tests.test_inference_api_keys tests.test_inference_production_stack` 共 `18` 项（`2` 项按配置 skipped）通过；后续必须补充全套 Week 11/12 工具、合同、编译和差异检查。
- 当前状态：Week 9-12 仍为 `in_progress`。该修复提交后只允许再触发一次新 SHA 的 `workflow_dispatch mode=full`；必须重新取得性能、backup/restore、N-1、security/runtime-images、Playwright 和最终 evidence manifest 全部通过，才能关闭验收。

## 82. 最新执行记录（2026-08-30，Run 33291044965 manifest 误报修复）

- Run `33291044965` 已结束：Quality 双平台、Production 双集成和 Chromium acceptance 成功；性能、备份恢复、N-1、安全和 Playwright 证据均已生成并通过业务门禁。
- 唯一失败点为最终 `evidence_manifest.py`：`backup/restore-result.json` 中 `source_table_counts`/`restored_table_counts` 的真实表名 `inference_api_keys` 被泛化敏感字段规则误判为 API key。回执没有写入数据库 URL、凭据、token 或 secret。
- 修复：manifest 对四类数据库表计数字典执行严格结构校验（合法 SQL 标识符、非负整数），并将表名作为结构标识跳过敏感字段名匹配；普通 JSON 中真实 `api_key`/`token` 等敏感字段仍 fail-closed 拒绝。
- 回归：新增 manifest 测试覆盖 `inference_api_keys` 表名可接受和真实敏感字段仍拒绝；两项定向测试通过，`git diff --check` 通过。完整远程验收必须绑定修复后新 SHA，不能改写或复用 Run `33291044965` 的失败 manifest。
- 当前状态：Week 9-12 仍为 `in_progress`。下一步提交并推送本修复，只触发一次新 SHA `mode=full`，下载同 SHA 全部制品并再次运行最终 manifest；只有六个 required jobs 和 manifest 全部通过后才能关闭验收。

## 83. 验收续行（2026-08-31，Run 33294680627 Playwright 绝对路径修复）

- Run `33294680627` 绑定 `aa879e4ea4bd0f0594c2424e7e89aeeeeb277ea9`，Quality Windows/Ubuntu、Production integration、Production experiment integration、Chromium acceptance 和 live Week 11 业务步骤均为 `success`；最终 `evidence_manifest.py` 为唯一失败步骤，因此该 Run 总体为 `failure`，不得关闭 Week 9-12。
- 已下载并检查同 SHA 制品。`playwright/playwright-report.json` 的 `config.argv`、`config.rootDir`、`config.projects[].outputDir`、`reporter.outputFile` 和 trace attachment path 包含 GitHub runner 的 `/home/runner/...` 或 `/tmp/...` 绝对路径；manifest 按现有 fail-closed 规则拒绝该原始制品。不是性能、备份恢复、N-1、安全扫描或 Playwright 用例失败。
- 修复：`tools.playwright_evidence` 增加递归净化器，保留 JSON 的测试状态、项目和附件结构，同时脱敏文本凭据并替换 Windows/POSIX 绝对路径；浏览器 CI 在生成 summary 后以净化版覆盖待上传的 report。manifest 的绝对路径和敏感值门禁不放宽。
- 本地验证：新增 RED/GREEN 回归覆盖 runner 路径净化后 Chromium 结果仍为 passed；CI 合同先因缺少 `--sanitized-output` 失败，再在接线后通过。完整 `tests.test_evidence_manifest tests.test_ci_workflow` 共 `80` 项通过；使用 Run `33294680627` 的真实 report 重放，净化后通过 `_assert_safe_json` 且摘要为 `1/1` passed；Python 编译和 `git diff --check` 通过。
- 当前状态：Week 9-12 仍为 `in_progress`。本修复必须提交并在新 SHA 上重新触发一次 `mode=full`；仅当六个 required jobs、同 SHA 全部制品和最终 manifest 均通过后才能更新验收结果。

## 84. 验收续行（2026-08-31，Run 33363122355 最终关闭）

- Run `33363122355` 绑定验收证据代码 SHA `3752794001c58b91d6a0e5f9c139f5635989a963`，总体 `success`；Quality Windows/Ubuntu、Production integration、Production experiment integration、Chromium acceptance 和 Week 11-12 verification 六个 required job 全部成功。
- 同一 SHA 的 `environment.json`、`performance/summary.json`、`backup/restore-result.json`、`upgrade/result.json`、`security/summary.json`、`security/runtime-images.json` 和 `playwright/result.json` 均已下载；性能、备份恢复、N-1、安全和 Playwright 状态全部 `passed`。
- 最终 `evidence_manifest.py` 结果为 `temp_test/remote-run-33363122355/final-evidence-manifest.json`，`status=passed`，包含完整哈希、迁移 head `20260829_14` 和镜像 digest `sha256:6269cf4e8f8a43f0a6a607ad94b14017f7dc5f27d728600341deed974e29c931`。
- Week 9、Week 10、Week 11、Week 12 及 Week 9-12 总体现已关闭。随后提交的 `e7d84d9` 仅更新 `DEVELOPMENT_PLAN.md` 和 `PLATFORM_STATUS.md`，不改变已验证代码或制品绑定；本次不再重复触发 CI。
## 85. 最新执行记录（2026-08-31，数据标注导出恢复原始数据列）

- 问题现象：自动标注和手动标注的 CSV/XLSX 导出仅包含样本索引、自动/人工标签、审核状态等标注元数据，没有包含用户上传数据的原始列。
- 根因：`build_annotation_export` 直接从 `spot_weld_quality_samples` 构造主表；该表用于标注状态和追溯，不是原始数据制品的完整导出来源。
- 修复：导出时通过运行记录的 `dataset_artifact_id` 重新读取原始 DataFrame，按 `source_row_index` 将最终标签对齐到原始行。自动标注默认追加 `label`，手动标注沿用任务的目标列名；CSV 直接输出合并数据，XLSX 首表改为“标注数据”，并继续保留“标注样本 / 标签修订 / 标签快照”追溯工作表。
- 验证：自动 XLSX 与手动 CSV 导出聚焦测试 `4 passed`，确认原始列存在且标签与原始行对齐；Python 编译和 `git diff --check` 通过。完整 `test_api_spot_weld_quality.py` 回归仍需在最终差异上执行。
- 剩余工作：尚未通过真实登录浏览器下载文件并使用 Excel/文本编辑器人工检查；未执行提交、推送或远程门禁。

## 86. 最新执行记录（2026-08-31，产品品牌更名为灵工 / Linkraft）

- 需求：项目中文名称由“智擎”改为“灵工”，英文名称改为“Linkraft”。
- 修复：中文和英文国际化品牌分别改为“灵工”和“Linkraft”；同步更新登录、注册、工作台副标题、浏览器标题、核心导航 E2E 断言及设计系统注释。历史开发记录和独立旧视觉预览保留原文，不改写历史事实。
- 验证：品牌聚焦 Vitest 与验收清单测试 `25/25 passed`；前端生产构建通过，仅有既有 ECharts 大 chunk warning；核心导航 Playwright `1/1 passed`，验证浏览器标题为“灵工 Linkraft”且核心认证路由显示“灵工”。完整前端 Vitest 为 `248 passed / 19 skipped / 1 failed`，唯一失败是与本次品牌改名无关的既有 `ProjectListPage` 创建者夹具未渲染 `admin`。

## 87. 最新执行记录（2026-08-31，多标签建模、标注员门户与模型导出计划）

- 用户需求：自动建模支持多标签分类和回归；手动/自动标注支持标签；自动标注支持按簇、按规则、簇+规则；新增独立标注员登录注册页面；管理员可指派任务；完成模型注册模型库并导出模型文件、推理代码、聚类方法、标注规则，推理校验输入数据与训练输入一致。
- 本轮处理：仅整理需求并新增设计与实施计划，未修改业务代码、数据库或运行时行为。
- 设计文件：`ml-platform/docs/superpowers/specs/2026-08-31-multilabel-annotation-annotator-portal-design.md`。
- 实施计划：`ml-platform/docs/superpowers/plans/2026-08-31-multilabel-annotation-annotator-portal.md`。
- 计划拆分：合同/迁移、AutoML 多输出、统一标签、自动标注策略、标注员认证与指派、模型注册导出、推理一致性、文档与验收共 8 个任务；默认复用现有认证并新增 `annotator` 角色，兼容旧单标签任务。
- 待确认：独立网页部署形态（独立域名/端口或 `/annotator`）、多人并行标注冲突策略、多标签层级/互斥规则。上述决策确认前不进入实现阶段。
- 状态：`planned`。尚未执行测试、构建、迁移、浏览器验收、提交或远程门禁。
- 剩余：未执行提交、推送或远程门禁；完整前端测试仍需单独修复 `ProjectListPage.test.tsx` 的既有失败后复跑，不能将本轮聚焦通过折算为全量通过。

## 88. 需求边界再次纠正（2026-08-31）

- 用户明确：整个项目都必须是通用自动建模和通用数据标注，不是仅本次需求去除行业内容。
- 计划修正：新增“全项目去行业化迁移”作为 Task 0；现有行业专用模型、字段、路由、服务、页面和测试只作为待迁移遗留，不再作为新功能兼容目标。
- 后续门禁：实现前必须完成行业专用引用盘点、通用 API/模型迁移、旧数据转换和全量引用扫描；任何新代码不得继续依赖固定行业字段或专用工作流。
- 具体迁移清单：后端行业专用 API/service/model 及测试、前端数据标注页面/API/组件及测试、数据库迁移、worker 分发、artifact/export、路由/菜单/i18n 和用户文档均纳入 Task 0；旧 URL 仅允许迁移期弃用或重定向。

## 89. 需求细化记录（2026-08-31，自动标注策略与完成后交互）

- 自动标注策略互斥：用户只能选择 `cluster`、`rule`、`cluster_rule` 其中一种。
- 按簇标注：聚类后允许选择一个或多个簇；指定簇必须配置标签；默认增加可编辑/可删除的“其他”兜底簇，覆盖未选择或未配置标签的全部簇。
- 按规则标注：复用现有规则能力，但扩展为每条规则支持多列标签。
- 按簇+规则标注：整合簇选择/标签与规则标签，并持久化明确的优先级和标签来源。
- 完成后交互：手动和自动任务完成后均不自动跳转标注详情页；任务列表/结果区域增加只读“预览”和支持单选/多选标注员的“指派标注员”。
- 计划文件已同步更新：`ml-platform/docs/superpowers/specs/2026-08-31-multilabel-annotation-annotator-portal-design.md`、`ml-platform/docs/superpowers/plans/2026-08-31-multilabel-annotation-annotator-portal.md`。

## 90. 技术方案记录（2026-08-31，通用自动建模与数据标注平台）

- 新增技术方案：`ml-platform/docs/technical-proposals/2026-08-31-general-modeling-annotation-platform.md`。
- 方案内容：全项目通用化架构、四种 AutoML 任务类型、统一标签/修订模型、聚类/规则/簇加规则流程、预览与指派交互、标注员门户、模型导出包、输入契约校验、迁移阶段、API 草案、测试和发布门禁。
- 本轮仅新增技术文档，未修改业务代码、数据库或运行时行为；`git diff --check` 已执行。
- 待评审决策：标注员部署形态、多人标注冲突策略、多标签层级/互斥规则、簇加规则优先级。

## 91. 发布同步记录（2026-09-02）

- 发布基线：本地发布分支 `codex/publish-local-safe-20260902` 已基于 `origin/main` 的 `e307e1b9968f1e1fe215ccdfbe126d43905da722`；原工作树通过 `codex/local-pre-sync-20260902` 和两份 stash 保留。
- 纳入范围：标注导出恢复原始数据列、旧 SQLite API 字段兼容、历史模型输入适配、灵工/Linkraft 品牌同步、对应回归测试，以及通用自动建模/数据标注技术方案、设计、实施计划和本记录。
- 排除范围：`output/` QA 生成物、`packaging/` 未完成安装脚本、含行业标题的独立预览、旧版方案、编辑器锁文件和其他未完成内容继续保留在保护位置，不进入 `main`。
- 本地验证：前端完整 Vitest `254 passed / 19 skipped`，TypeScript 检查通过，生产构建通过（仅既有大 chunk warning）；后端定向回归 `77/77 OK`；Python 编译、DOCX 23 页渲染/逐页检查和 `git diff --check` 通过。
- 状态：提交、推送和快进合并仍待完成；远端如在写入前发生变化，必须重新同步，禁止强制推送。发布后需核对本地 `main`、`origin/main` 和 GitHub `refs/heads/main` 为同一 SHA，且工作树仅保留明确保护内容。

## 92. CI 失败修复记录（2026-09-02，Run 33584653041）

- Run `33584653041` 绑定提交 `04cbb71a85bb4836963dfbb91cfa47c11326becd`，Quality Ubuntu 和 Windows 均失败；其余 Production、Chromium 和 Week 11-12 job 因 Quality 失败而 `skipped`，不能按绿色子集计为通过。
- 首个真实失败为 `tests.test_suite_manifest.TestSuiteManifest.test_every_backend_test_module_has_one_week_owner`：自动发现新增模块 `test_database_migrations`，但 `tests/week_manifest.py` 未登记其周次归属；`112` 个其他模块通过。
- 根因是发布提交新增独立数据库迁移兼容回归时未同步测试周次台账，违反每个 `test_*.py` 恰好归属一个周次的 manifest 合同。
- 修复：将 `test_database_migrations` 登记到与数据库/存储兼容回归一致的 Week 5；未删除测试、未放宽 manifest 断言，也未修改通用技术方案 Markdown。
- 本地验证：修复前 `tests.test_suite_manifest` 稳定复现 `1` 项失败；修复后 `tests.test_database_migrations tests.test_suite_manifest` 共 `6/6 OK`；完整 `run_suite.py` 为 `114 passed, 0 failed`。
- 待远端验证：提交并推送本修复后重新检查 Quality Ubuntu/Windows；仅当后续 required jobs 不再因该门禁失败而跳过，才可记录新的 CI 结论。
