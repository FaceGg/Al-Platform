# 通用平台验收矩阵

> 状态：`in_progress`。本矩阵只接受当前 Git SHA 的 `passed` 收据；`failed`、`cancelled`、`skipped`、缺失或旧 SHA 收据均阻止发布。

| ID | 合同 | 主要验证命令 | 证据责任 |
|---|---|---|---|
| DAT-01 | JSON/XML 正常导入：记录路径、映射、解析器/schema hash 冻结，重解析产生新版本 | `pytest tests/test_dataset_import_contract.py -q` | 后端与真实导入链路证据 |
| DAT-02 | JSON/XML 安全解析与限制 | `pytest tests/test_dataset_import_contract.py -q` | 后端测试收据 |
| DAT-03 | 缺列与空值：缺少必需列拒绝；已有列空值按 missing_policy 处理并计数 | `pytest tests/test_dataset_import_contract.py -q` | 输入合同证据 |
| LAB-01 | 多列标签 schema 与类型校验 | `pytest tests/test_label_schema.py tests/test_label_schema_api.py -q` | 后端测试收据 |
| LAB-02 | 三种自动策略互斥、其他兜底不可删除且必须配置、规则未命中回退 | `pytest tests/test_annotation_strategies.py -q` | 策略与真实页面证据 |
| LAB-03 | 逐列规则 > 簇 > 其他，同优先级冲突进入 needs_review | `pytest tests/test_annotation_strategies.py -q` | 策略优先级与冲突证据 |
| CLU-01 | 加权 KMeans 与确定性分配 | `pytest tests/test_annotation_strategies.py -q` | 后端测试收据 |
| CLU-02 | 10,000 样本聚类：全量赋簇、评估模式/样本数/hash、前端不加载全量 | 容量运行命令尚未建立，不得用小样本测试关闭 | 10,000 样本实测与浏览器分页证据 |
| CON-01 | 重叠指派与 revision 冲突 | `pytest tests/test_annotation_concurrency.py -q` | 后端测试收据 |
| CON-02 | 并发回传：幂等不重复建批次，过期批次不能静默覆盖 | `pytest tests/test_annotation_concurrency.py tests/test_annotation_return_acceptance.py -q` | 并发数据库与 API 证据 |
| RET-01 | 回传锁：只读、显式编辑并产生新修订后解除，旧批次 supersede | `pytest tests/test_annotation_concurrency.py -q` | 后端与真实门户证据 |
| AUTH-01 | 独立标注员身份和会话撤销 | `pytest tests/test_annotator_auth.py -q` | 后端测试收据 |
| AUTH-02 | Web 安全：CORS、CSRF、限流、密码哈希、服务 JWT/mTLS | `pytest tests/test_security_contract.py tests/test_annotator_auth.py -q`；门户后端套件 | 双服务真实安全证据 |
| API-01 | 通用任务 API、分页和状态错误合同 | `pytest tests/test_annotation_task_state_api.py -q` | 后端测试收据 |
| AUTO-01 | 四种 AutoML 任务与候选工件 | `pytest tests/test_automl_multioutput.py -q` | 后端测试收据 |
| AUTO-02 | 模型注册：worker 不自动注册、完整候选手动注册、重复注册幂等 | `pytest tests/test_automl_multioutput.py tests/test_model_registration_contract.py -q` | worker、注册 API 与真实浏览器证据 |
| EXP-01 | 模型导出包、签名、SBOM 与 checksum | `pytest tests/test_model_export_contract.py -q` | 导出收据 |
| INF-01 | 离线 predict/annotate 输入输出合同 | `pytest tests/test_offline_inference_contract.py -q` | 推理收据 |
| REL-01 | 重试与恢复：租约过期重领、幂等副作用、临时制品 TTL 清理保护已提交制品 | `pytest tests/test_async_operation_contract.py -q`；真实 worker 恢复演练 | broker/worker/存储恢复证据 |

## 2026-09-15 验收编号语义更正

- 上表恢复技术方案 §16.4 的原始编号含义；旧表曾将 LAB-02/03、CLU-02、CON-02、RET-01、AUTH-02、AUTO-02 等替换为不同场景，不能由旧同名收据推导本表已通过。
- 命令仅列出现有相关测试入口，不表示这些测试已经穷尽该编号要求。缺少原条款断言、真实容量或跨服务证据时，该编号继续保持未完成。
- 本轮 19 项最终验收均未关闭。当前 working-tree 聚焦测试单独记录到全方案一致性实施台账，不能生成最终 SHA 的 passed 收据。
- 以下历史记录保留，不重写既有结果；其范围和 SHA 不自动转移到更正后的编号。

收据使用 `python -m tools.generic_acceptance_evidence` 写入 `temp_test/generic-platform-acceptance/receipts/`。最终门禁调用 `validate_acceptance_manifest`，并将所有收据绑定到同一个当前 SHA。

## 2026-09-25 CLU-02 容量范围调整

- 当前 Task 14/CLU-02 的必需容量由用户调整为 10,000 样本；当前矩阵行和后续验收按此容量执行。
- 历史记录中的“百万样本”表述保留，不追溯改写历史语义；它不再是当前必须实现的发布门槛。
- 本次仅更新验收范围，未生成 10,000 样本真实运行或浏览器分页证据。

## 2026-09-09 当前 SHA 检查记录

- SHA：`e94862af844ea95a31203423c24a8ececd7553d6`。
- 已验证：聚焦后端证据按各 Task 记录；`alembic check` 无新升级操作；fresh SQLite `upgrade head` 到 `20260909_40`；前端生产构建通过；`git diff --check` 退出码 0。
- 未通过：后端完整 active suite 退出码 1（旧数据库/通知检查失败，安全门禁模块超过 300 秒超时）；前端完整 Vitest 退出码 1（56 个文件通过、1 个文件失败、274 个测试通过、19 个历史 skipped），失败点为 `weekAcceptance.test.ts` 的测试文件归属台账缺五个新文件。
- 未执行或无证据：当前 SHA 的 Docker/Compose、真实 broker、Playwright、导出包/离线推理、恢复演练和远程 CI。
- 矩阵结论：保持 `in_progress`；任何上述失败、超时、缺失或未执行项都不能生成 `passed` 收据。

## 2026-09-09 当前 SHA 复核

- 前端台账回归：`npm test -- --run src/weekAcceptance.test.ts`，**7 passed**。
- 前端完整套件：`npm test -- --run`，**57 个文件通过、275 个测试通过、19 个历史 skipped，退出码 0**。因此上一条记录中的台账遗漏已修复；旧失败记录保留用于追溯，不再代表当前结果。
- 后端 worker 回归：`python -m unittest tests.test_celery_workflows -v`，**19/19 OK**。
- 发布结论不变：后端完整 active suite 仍有历史失败和安全模块超时；Docker/真实 broker/Playwright/导出离线/恢复/远程 CI 仍无当前 SHA 收据，矩阵继续保持 `in_progress`。
- 测试基础设施风险：`run_suite.py` 固定使用 `unittest` 执行模块，pytest 风格模块可能产生 `NO TESTS RAN`；在框架感知派发和 `tests/test_run_suite.py` 回归完成前，不把 Week 17 聚合结果作为发布门禁。

## 2026-09-09 进度整理更正

- 当前 `run_suite.py` 已具备基于 AST 的 pytest/unittest 框架派发，上一条“固定使用 unittest”是历史检查点，保留用于追溯；新的剩余风险是 `has_zero_tests` 读取嵌套历史摘要时可能误判外层模块为零测试。
- `tests/test_run_suite.py` 当前 **6 passed**，但 Week 17 聚合仍不能作为通过门禁，直到零测试误判回归修复并重跑聚合。
- `tests/test_label_schema_api.py` 当前 **3 passed、1 failed**；失败来自测试夹具使用了不属于项目的数据版本，属于夹具待修正，不应削弱服务端项目归属校验。
- 前端台账与完整 Vitest 的当前 SHA 复核已记录为 **7/7**、**57 个文件/275 个测试通过、19 个历史 skipped**；后端 worker 导入回归为 **19/19 OK**。
- 矩阵仍为 `in_progress`：后端完整套件、Docker/真实 broker、Playwright、导出/离线、恢复演练和远程 CI 均缺少当前 SHA 的完整通过收据。

## 2026-09-09 聚合复核（最新）

- 当前 SHA 仍为 `e94862af844ea95a31203423c24a8ececd7553d6`。
- `run_suite.py --week 17` 已按模块原生框架执行，结果为 **21/21 模块通过、0 失败、退出码 0**；其中 `tests.test_run_suite` **7/7 OK**、标签 schema API **4 passed、1 warning**，说明本轮运行器摘要解析和项目归属测试夹具修复已生效。
- 该聚合结果只覆盖当前本地 Week 17 模块级测试，不等同于 19 项验收收据。后端完整 active suite、真实 broker、Docker/WSL、Playwright、导出/离线、恢复和远程 CI 仍无完整当前 SHA 通过证据。
- 矩阵结论保持 `in_progress`；不得将本次聚合绿灯外推为任务完成或发布就绪。

## 2026-09-09 当前工作树进度整理

- 当前 SHA 为 `e94862af844ea95a31203423c24a8ececd7553d6`，分支与远端 `0/0`；工作树有未提交变更，用户本地 `README.md` 不属于本次验收范围。
- 新增前端回归尚未通过：`npm test -- --run src/pages/DataAnnotationPage.test.tsx` 为 **39 项中 38 passed、1 failed**。失败用例为通用任务预览完成后执行按钮应启用的列表流程。
- 根因已定位为前端状态接线缺口：预览详情已返回 `preview_id/status`，但没有回写列表任务的 `task.preview`，因此执行操作仍被禁用。该问题尚未修复，不能生成 `API-01` 或相关页面通过收据。
- 此前前端全量 **57 文件/275 测试通过、19 个历史 skipped** 的结果早于本次新增回归，需修复后重新执行；Week 17 聚合、worker 导入和其他局部收据仍只对各自范围有效。
- 矩阵结论保持 `in_progress`。下一门禁顺序为页面状态回写修复、聚焦测试、台账/全量 Vitest，然后继续 Task 5 的 broker、恢复、分页和操作中心验证。

## 2026-09-09 当前工作树复核更正

- 预览完成状态已回写对应列表任务；`npm test -- --run src/pages/DataAnnotationPage.test.tsx` 为 **39/39 passed**，此前 38/39 的 RED 保留为历史记录。
- 前端验证已重新执行：台账 **7/7 passed**，完整 Vitest **57 个文件通过、276 个测试通过、19 个历史 skipped**，生产构建退出码 0。275 项测试的旧记录不再代表当前工作树结果。
- 后端聚合运行器复核：unittest **7/7 OK**、pytest **7 passed**、Week 17 **21/21 模块通过、0 失败**；`git diff --check` 通过。
- 这些结果来自含未提交变更的工作树，不能写为 Git SHA 绑定的 `passed` 收据。矩阵继续保持 `in_progress`；后端完整套件、Docker/真实 broker、Playwright、导出/离线、恢复和远程 CI 仍缺少可发布版本的完整证据。

## 2026-09-09 Task 5 刷新合同复核

- 任务列表在刷新后已返回当前修订可执行预览，不会将旧修订预览误作为当前动作目标。后端聚焦命令 `pytest tests/test_annotation_task_state.py tests/test_annotation_task_state_api.py tests/test_genericization_contract.py -q` 为 **52 passed、3 warnings**；共享状态服务和任务 API 编译通过。
- 该结果为 Task 5 的局部工作树证据，可支持后续 `CLU-02`、`API-01` 的实现复核，但不能替代当前 Git SHA 的收据。没有新增 `receipts/`，也没有生成任何 `passed` 验收结论。
- 矩阵继续为 `in_progress`：真实 broker、恢复、完整后端、Docker/WSL、Playwright、导出/离线和远程 CI 仍需在干净提交上生成同一 SHA 的完整证据。

## 2026-09-09 Task 5 审计补充

- 本次只读审计确认：状态机、冻结快照、预览 DurableOperation/worker、owner-scoped cursor 列表和当前 revision 预览刷新合同已有局部实现；对应 Task 5 回归为 **52 passed、3 warnings**，前端页面 **39/39**，台账 **7/7**，完整 Vitest **57 文件/276 passed/19 skipped**，Week 17 聚合 **21/21**。这些结果均来自脏工作树，不产生 `passed` 收据。
- `API-01`/`CLU-02` 仍不能关闭：执行链路没有 durable execution operation/worker/result/recovery；本地派发和真实 broker/restart 未验证；统计结果的 sample/cluster/rule/final-label cursor 合同缺失；页面操作中心仍未统一且只有 Preview/Assign/Execute；配置 revision/invalidation 端点缺失。
- 全量后端门禁另有环境阻塞：项目 `.venv` 缺少 requirements 声明的 `catboost==1.2.*`，完整收集在 `tests/test_onnx_conversion.py` 失败；在依赖补齐并重跑前，不将该失败归因于实现，也不生成全量通过收据。
- 矩阵继续保持 `in_progress`。下一门禁顺序为补齐依赖并重跑后端全量，随后实现 Task 5 执行/恢复、结果分页和统一操作中心，再收集 Task 6–13 运行态证据，最后在干净 SHA 上重跑 Task 14 全部收据。

## 2026-09-10 Task 5 执行链路检查点

- 当前工作树出现执行结果表/迁移、幂等执行请求服务和执行 worker/派发测试的进行中改动，但代理尚未完成 GREEN 验证；因此 `API-01`、`CLU-02` 和 `REL-01` 不新增 `passed` 收据。
- 既有局部证据仍只按原范围有效：Task 5 回归 **52 passed、3 warnings**，前端页面 **39/39**，台账 **7/7**，完整 Vitest **57 文件/276 passed/19 skipped**，Week 17 **21/21**，worker 导入 **19/19**，生产构建和 `git diff --check` 通过。所有结果来自脏工作树，不能满足当前 SHA 收据合同。
- 环境复核更正：项目 `.venv` 可导入 `catboost 1.2.10`；`onnx`、`onnxmltools`、`skl2onnx` 缺失。后端完整套件收集须先补齐声明依赖并重新执行，不能将该环境阻断记为代码失败或通过。
- 矩阵继续为 `in_progress`。仍缺执行结果完整 GREEN、local/Celery 派发、真实 broker/重启恢复、结果与统计分页、完整任务操作矩阵、Docker/WSL、Playwright、导出/离线及远程 CI 的当前 SHA 证据。

## 2026-09-10 发布前进度整理

- 当前分支 HEAD 为 `e94862af844ea95a31203423c24a8ececd7553d6`，本次发布前仍为脏工作树；下列结果均为工作树证据，不是 SHA 绑定收据。
- Task 5 执行链路代理报告 **59 passed、4 warnings**，后续审查复核报告 **61 passed、4 warnings**；前端 `DataAnnotationPage.test.tsx` 当前 **41 passed**，`weekAcceptance.test.ts` **7 passed**。
- 后端重新执行未启动：项目 `.venv` 的 `python.exe` 目标解释器已不存在，`pyvenv.cfg` 指向 `C:\Users\17723\AppData\Local\Programs\Python\Python314\python.exe`。该项标记为环境阻断，不能写成后端通过或失败。
- `API-01`、`CLU-02`、`REL-01` 及 Task 5 相关矩阵项仍不能关闭。缺口包括真实 broker/Celery、重启恢复、原子 recovery claim、完整操作矩阵、配置 revision/旧预览失效、前端结果/统计消费与 cursor 加载，以及当前 SHA 的 Docker/Playwright/导出/离线/远程 CI 收据。
- 本次文档整理不生成 `passed` 收据；推送分支只保存当前实现和审计状态，后续必须修复 Python 环境、形成干净 SHA 后重新执行 required gates。

## 2026-09-11 当前 SHA 复核

- 当前发布 SHA：`801f2a44e3802d6ccd3317026e63d730cf0c3869`，已与远端分支一致；工作树仅有用户本地 `README.md` 未暂存修改。
- 当前 SHA 的可复核结果：Task 5/6/7/8/13 聚焦后端 **88 passed、10 warnings**；安全/用户认证 **22 passed、8 warnings**；Week 17 聚合 **21 passed、0 failed**；前端全量 **57 files passed、279 passed、19 skipped**；生产构建、Python 编译、迁移 upgrade/check 和 `git diff --check` 通过。
- 本轮补齐了 local preview dispatch：local 模式复用 durable preview worker，独立 SQLite 回归确认 `preview_ready` 和 100% progress；Celery 路径未改变。
- 未形成以下当前 SHA 收据：真实 Redis/Celery broker、进程重启恢复、Docker/WSL、Playwright、导出包/离线真实运行、完整后端 active suite 和远程 CI。Docker 命令在当前 Windows 宿主不可用，因此这些项目保持 `unexecuted` 或 `in_progress`，矩阵总体保持 `in_progress`。

## 2026-09-11 AutoML 搜索强度控制修复

- 新建 AutoML 页面已移除“最大试验次数”；前端请求只发送 `search_strength`，后端在新合同中按强度派生执行预算。前端 `AutoMLPage` 聚焦 **10 passed**，后端 AutoML 跟踪/API **64 passed、10 subtests**。
- 该修复不关闭 `AUTO-01`：完整后端、浏览器 AutoML E2E、真实 worker/broker 和远程 CI 仍需当前 SHA 收据。

## 2026-09-11 通用任务状态动作矩阵

- 任务列表已补齐回传、验收、完成、归档、恢复和重开动作，均通过统一 transition API 提交 `task_revision`，新增返回任务验收动作的前端回归。
- `DataAnnotationPage` 聚焦测试 **42 passed**，生产构建和源码门禁通过；该结果不替代真实标注员门户、broker/recovery、浏览器 E2E 和远程 CI 收据。

## 2026-09-11 发布后前端全量复核

- 发布 SHA `3ecea9a61a4ae344322189feee001019c2f072e2` 的前端全量：**57 个文件通过、280 passed、19 skipped**。
- 前端全量绿灯不关闭 `AUTO-02` 或 `REL-01`；浏览器 E2E、真实 broker/recovery、完整后端和远程 CI 仍需独立收据。

## 2026-09-11 AutoML 浏览器证据

- 执行 `npm run test:e2e -- e2e/automl-multioutput.spec.ts`，Chromium **1 passed**；验证登录、项目/数据集选择、多目标配置、输入列过滤和 AutoML 请求合同。
- AUTO-02 仍保持 `in_progress`，因为当前结果尚未写入统一 SHA 收据目录，且真实远程验收栈与完整发布门禁仍未执行。

## 2026-09-11 导出与离线推理聚焦复核

- 执行 `pytest tests/test_model_export_contract.py tests/test_model_exports_api.py tests/test_offline_inference_contract.py -q`，结果 **9 passed、2 warnings**。
- EXP-01/INF-01 仍不生成 `passed` 收据：当前命令结果尚未写入统一 receipts，且未完成真实部署环境的导出包下载、checksum/SBOM 和离线 CLI 运行验收。

## 2026-09-11 19 项合同收据复核

- 已为矩阵 19 个 ID 生成本地 receipts，最近一次调用 `validate_acceptance_manifest` 返回 **19 receipts valid**；文档提交完成后必须按最终发布 SHA 重新绑定。
- 收据验证证明每个合同均有发布 SHA、命令和相对证据路径；收据位于本地 `temp_test/generic-platform-acceptance/receipts/`，未将临时运行目录混入产品代码提交。任何新提交都会使旧 SHA 收据失效。
- 矩阵仍不等于平台整体发布完成：完整后端 active suite、Docker/WSL、真实 Redis/Celery、进程重启恢复、真实部署导出/离线运行和远程 CI 仍需独立门禁。

## 2026-09-11 Task 8/9 当前分支 API 复核

- 当前分支 `4def21a` 的 Python 3.11.9 聚焦回归：`test_annotation_concurrency.py`、`test_annotation_return_acceptance.py`、`test_annotator_auth.py`、`test_portal_internal_api.py` 共 **22 passed、2 warnings**。
- 该结果仅证明本地 API/服务合同；Docker、Redis/Celery、进程重启恢复、门户浏览器验收和远程 CI 未执行，因此 Task 8/9 与整体矩阵继续保持 `in_progress`。

## 2026-09-11 目标分支 Task 5/异步组合复核

- 当前分支 `general-automl-annotation-20260902`、HEAD `ac56fd7` 工作区干净；使用 Python 3.11 环境执行 Task 5/异步组合：**66 passed、4 warnings**。
- 覆盖 `test_annotation_task_state.py`、`test_annotation_task_state_api.py` 和 `test_async_operation_contract.py`，包括执行 DurableOperation、结果 cursor 分页、local/Celery 派发合同及恢复回归。
- 该结果是当前分支聚焦证据，不生成或更新 19 项 `passed` 收据；真实 Redis/Celery、进程重启恢复、Docker/WSL、完整后端 active suite、浏览器和远程 CI 仍未形成当前 SHA 的完整证据，矩阵继续 `in_progress`。

## 2026-09-11 Task 5 收口证据

- 后端 Task 5 组合：**74 passed、4 warnings**；前端 `DataAnnotationPage`、`PreviewDrawer` 和周台账：**59 passed**；生产构建通过。
- 当前分支 Chromium 通用平台验收：`e2e/generic-platform-acceptance.spec.ts` **1 passed**，覆盖任务列表、预览完成后的执行条件和 `execute -> return -> accept` 状态链。
- 真实 Redis/Celery 演练收据：`temp_test/task5-runtime-20260911-r3/receipt.json`，状态 `passed`；覆盖真实 broker 预览、执行 worker 终止/重启 recovery、同一 operation identity 和 5000 条结果无重复。
- Task 5 状态：`passed`。矩阵总体仍为 `in_progress`，因为 Task 6–14、当前最终 SHA 的 19 项收据、完整后端 active suite、Docker/WSL 全栈持续运行和远程 CI 仍未闭环。`r5` 重跑因 Docker 到 Windows 的 `127.0.0.1:6395` 端口映射被拒绝，记录为 `environment-blocked`，不改写 `r3` 的通过收据。

## 2026-09-11 Task 6 自动策略证据

- `CLU-01` / `CLU-02` 当前工作树聚焦验证：Task 6 后端组合 **65 passed、10 warnings**。
- 覆盖：model、cluster、rule、cluster_rule 策略，fallback 和规则冲突，类型化规则 DSL，特征重要性聚合，加权 KMeans 及预览策略 artifact/逐样本 provenance；自动任务 API 非法配置返回结构化 `422` 且不落库。
- 前端自动策略配置回归与周台账 **57 passed**；生产构建和 `git diff --check` 通过。
- 状态边界：以上是当前未提交工作树的 Task 6 聚焦证据，不是最终 Git SHA 收据。矩阵总体仍为 `in_progress`，Task 7–14、真实 Docker/Redis/Celery recovery、完整 active suite、门户完整浏览器链路和远程 CI 仍未闭环。

## 2026-09-11 Task 7 独立标注员认证证据

- `AUTH-01` / `AUTH-02` 当前工作树聚焦验证：主平台认证、门户内部 API 和迁移 **16 passed、2 warnings**；独立门户后端 **3 passed、2 warnings**。
- 门户前端认证、任务队列和工作区测试 **5 passed**，生产构建通过。
- 覆盖：独立 annotator account、不可变 subject、portal session 与 session version 撤销、主体映射、项目授权、服务 token issuer/audience/scope/project 校验，以及门户不接受客户端自带 project/annotator identity。
- 环境边界：Docker CLI 不可用，Compose config 和容器运行态未执行；以上是当前工作树聚焦证据，不是最终 Git SHA 收据。矩阵总体继续 `in_progress`，Task 8–14、Compose/真实运行态和远程 CI 仍未闭环。

## 2026-09-11 Task 8 指派与并发证据

- `CON-01` / `CON-02` 当前工作树聚焦验证：`tests/test_annotation_concurrency.py tests/test_annotation_return_acceptance.py tests/test_annotator_auth.py tests/test_portal_internal_api.py` **22 passed、2 warnings**。
- 覆盖：重叠指派、样本级 revision 冲突、完整服务端标签集合、任务/项目/标注员授权、回传幂等、回传后只读锁、显式 edit-for-return、门户标签和评论 API。
- 状态边界：Task 8 在当前工作树聚焦范围内通过；矩阵总体继续 `in_progress`，Task 9–14、Docker/真实 broker/recovery、完整门户浏览器和远程 CI 仍未闭环。

## 2026-09-11 Task 9 回传验收证据

- `RET-01` 当前工作树聚焦验证：`tests/test_annotation_return_acceptance.py tests/test_api_datasets.py tests/test_notification_outbox.py` **45 passed、20 warnings**。
- 覆盖：回传批次列表、管理员验收和退回、验收幂等、从不可变源版本生成新数据版本、源版本不变、schema/sample 复制、退回原因和标注员站内通知。
- 状态边界：Task 9 在当前工作树聚焦范围内通过；矩阵总体继续 `in_progress`，Task 10–14、完整前端/容器/worker/远程 CI 和最终 SHA 收据仍未闭环。

## 2026-09-11 Task 10 模型注册证据

- 当前仓库实际存在的模型注册/模型库后端组合 **47 passed、13 warnings、2 subtests passed**；前端 AutoML/模型库组合 **24 passed**；主平台生产构建通过。
- 覆盖：完整 candidate 注册边界、artifact-only lineage、重复注册幂等、多目标合同元数据、模型生命周期和模型库 API。
- 计划差异：计划引用的 `tests/test_automl_result_registration.py` 当前不存在，未将其记为执行通过；使用实际存在的 `test_model_registration_contract.py`、`test_api_model_registry.py`、`test_model_registry_service.py` 和 `test_api_model_library.py`。
- 状态边界：Task 10 在当前工作树聚焦范围内通过；矩阵总体继续 `in_progress`，Task 11–14、导出/离线运行态、容器/recovery、完整浏览器和远程 CI 仍未闭环。

## 2026-09-11 Task 11 导出与离线证据

- `EXP-01` / `INF-01` 当前工作树聚焦验证：后端导出/离线合同 **9 passed、3 warnings**；导出 API 与模型库前端 **15 passed**；主平台生产构建通过。
- 新增 `e2e/model-export.spec.ts`，Chromium **1 passed**；覆盖真实登录、模型库项目选择、已批准版本、异步导出 queued/running/ready 状态轮询以及 ready 后一次性下载。
- 状态边界：Task 11 在当前工作树聚焦、前端和浏览器范围内通过；矩阵总体继续 `in_progress`，Docker/真实部署导出运行、完整后端 active suite、Task 12–14 和远程 CI 仍未闭环。

## 2026-09-11 Task 12 主平台与标注员门户聚焦证据

- 主平台 Task 12 聚焦套件：`DataAnnotationPage`、`AutoMLTaskPage`、`ModelLibraryPage`、`AssignmentDialog`、`ReturnBatchList` 和周验收台账共 **83 passed**。
- 独立标注员门户前端全量测试：**5 passed**；门户生产构建和主平台生产构建均通过。
- Chromium 浏览器流程：**2 passed**，覆盖主平台通用任务列表/预览完成后执行及 `execute -> return -> accept` 状态链，以及门户独立身份、自动保存、冲突/回传锁和显式编辑流程。
- Task 12 在当前本地聚焦、前端构建和浏览器范围内标记为 `passed`。该证据来自当前工作树，不替代最终干净 SHA 收据；完整后端 active suite、Docker/WSL 持续运行、真实跨服务门户运行和远程 CI 仍由 Task 14 门禁负责。

## 2026-09-11 Task 13 异步恢复、清理与安全聚焦证据

- Task 13 聚焦套件：`tests/test_async_operation_contract.py tests/test_security_contract.py tests/test_suite_manifest.py` **32 passed、2 subtests passed**。
- 覆盖：过期 lease 单次回收、恢复派发去重、失败操作不发布部分制品、清理报告字段与 SHA 校验、幂等操作及请求安全合同；`celery_app.py`、`recovery.py`、`artifact_service.py`、`config.py`、`main.py` 和清理工具均通过 Python 编译。
- Task 13 在当前本地异步/安全/清理聚焦范围内标记为 `passed`。Docker/WSL Compose 配置与持续运行、真实跨服务 recovery、完整后端 active suite、最终 SHA 收据和远程 CI 仍未完成，继续由 Task 14 门禁负责。

## 2026-09-22 收据 CI 接入位置更正

- CI `week11-12-verification` job 的「Generate generic acceptance receipts」步骤已改为将 19 项收据写入 `ML_PLATFORM_EVIDENCE_DIR/generic-platform-acceptance/`（即 `temp_test/week11-12/generic-platform-acceptance/` 的运行时目录，具体以 job 环境变量为准），使最终 evidence manifest 的文件哈希清单收录收据并随 verification evidence 产物上传；此前收据生成于仓库根 `temp_test/generic-platform-acceptance/`、游离于最终 manifest 与上传产物之外，该历史记录保留不改写。
- 该步骤的嵌套 manifest 命名由 `final-evidence-manifest.json` 更正为 `acceptance-manifest.json`，避免与 `evidence_manifest` 生成的顶层最终 manifest 混淆。
- AUTH-02 的收据证据路径由不存在的 `ml-platform/annotator/backend/tests/test_portal_internal_api.py` 更正为实际门户后端套件 `ml-platform/annotator/backend/tests/test_portal_api.py`。
- 上述更正在当前工作树完成并以 `tests/test_ci_workflow.py`、`tests/test_acceptance_manifest.py`（**62 passed、138 subtests passed**）和本地 19 收据 + manifest 校验模拟锁定；远程 CI 尚未在最终干净 SHA 上执行，19 项 `passed` 收据仍以远程实际生成为准，本矩阵头部 fail-closed 规则不变。

## 2026-09-25 最终 SHA 远程门禁复核

- 代码 SHA `b185ead4f93068cf457a10fa5079d8be138ab88f` 的 [GitHub full CI Run 36112327185](https://github.com/FaceGg/Al-Platform/actions/runs/36112327185) 六个 required jobs 全部 `success`，没有 `skipped`；`week11-12-verification-evidence` 中的最终 manifest 为 `passed`，19 项 receipt 全部为 `passed` 并绑定该 SHA，manifest 文件哈希和大小逐项核对通过。
- 这只证明收据链和通用门禁已在当前 SHA 生成，不能覆盖原始矩阵的语义要求。CLU-02 仍缺 10,000 样本与分页实测；AUTH-02 仍缺主平台/门户双服务安全运行证据；AUTO-02 仍缺真实 worker 候选手动注册与重复注册幂等流程；REL-01 仍缺真实 broker/worker 恢复和 TTL 清理演练。四项保持 `in_progress`，矩阵总体不关闭。
