# 通用平台验收矩阵

> 状态：`in_progress`。本矩阵只接受当前 Git SHA 的 `passed` 收据；`failed`、`cancelled`、`skipped`、缺失或旧 SHA 收据均阻止发布。

| ID | 合同 | 主要验证命令 | 证据责任 |
|---|---|---|---|
| DAT-01 | CSV、Excel、Parquet 导入与冻结版本 | `pytest tests/test_dataset_import_contract.py -q` | 后端测试收据 |
| DAT-02 | JSON/XML 安全解析与限制 | `pytest tests/test_dataset_import_contract.py -q` | 后端测试收据 |
| DAT-03 | 输入合同与不可变数据版本 | `pytest tests/test_dataset_import_contract.py tests/test_database_migrations.py -q` | 后端测试收据 |
| LAB-01 | 多列标签 schema 与类型校验 | `pytest tests/test_label_schema.py tests/test_label_schema_api.py -q` | 后端测试收据 |
| LAB-02 | 标签 revision 与并发写入 | `pytest tests/test_annotation_concurrency.py -q` | 后端测试收据 |
| LAB-03 | 标签前端编辑器 | `npm test -- --run src/components/LabelSchemaEditor.test.tsx` | 前端测试收据 |
| CLU-01 | 加权 KMeans 与确定性分配 | `pytest tests/test_annotation_strategies.py -q` | 后端测试收据 |
| CLU-02 | 自动策略预览与复核闭环 | `pytest tests/test_annotation_task_state.py tests/test_annotation_task_state_api.py -q` | 后端测试收据 |
| CON-01 | 重叠指派与 revision 冲突 | `pytest tests/test_annotation_concurrency.py -q` | 后端测试收据 |
| CON-02 | 回传锁与显式重新编辑 | `pytest tests/test_annotation_concurrency.py -q` | 后端测试收据 |
| RET-01 | 回传列表、差异、验收和退回通知 | `pytest tests/test_annotation_return_acceptance.py -q` | 后端测试收据 |
| AUTH-01 | 独立标注员身份和会话撤销 | `pytest tests/test_annotator_auth.py -q` | 后端测试收据 |
| AUTH-02 | 门户 API 与服务身份边界 | `pytest -q`（`ml-platform/annotator/backend`） | 门户测试收据 |
| API-01 | 通用任务 API、分页和状态错误合同 | `pytest tests/test_annotation_task_state_api.py -q` | 后端测试收据 |
| AUTO-01 | 四种 AutoML 任务与候选工件 | `pytest tests/test_automl_multioutput.py -q` | 后端测试收据 |
| AUTO-02 | AutoML 浏览器流程 | `npm run test:e2e -- e2e/automl-multioutput.spec.ts` | 浏览器收据 |
| EXP-01 | 模型导出包、签名、SBOM 与 checksum | `pytest tests/test_model_export_contract.py -q` | 导出收据 |
| INF-01 | 离线 predict/annotate 输入输出合同 | `pytest tests/test_offline_inference_contract.py -q` | 推理收据 |
| REL-01 | 迁移、恢复、清理与安全门禁 | `pytest tests/test_async_operation_contract.py tests/test_security_contract.py -q` | 恢复与安全收据 |

收据使用 `python -m tools.generic_acceptance_evidence` 写入 `temp_test/generic-platform-acceptance/receipts/`。最终门禁调用 `validate_acceptance_manifest`，并将所有收据绑定到同一个当前 SHA。

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
