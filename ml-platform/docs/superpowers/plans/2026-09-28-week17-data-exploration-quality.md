# Week 17 数据探索与质量报告实施计划（决策门控）

> For agentic workers: **Task 17.0 决策门未全批前，本计划不得越过 17.0 执行任何一步**。本计划是 [2026-09-24 Week 13–17 计划](2026-09-24-week13-17-development.md) Task 5 的细化执行入口；设计合同见 [Week 17 技术方案](../../technical-proposals/2026-09-28-week17-data-exploration-quality.md)。Week 13–15 收口是查询作业化（可选）的前置，但 API 进程内查询/报告不依赖 Week 14。

**Goal:** 获批后交付项目内只读 SQL 探索（三重上限、封闭执行）、确定性质量 profile 与可追溯报告 Artifact，全部叠加在既有项目权限/制品合同上。

**Architecture:** `ArtifactService.resolve`（项目隔离）→ `materialize` 临时副本 → sqlglot 语句校验 → per-request DuckDB 只读临时库（固定视图 + 收紧资源参数）→ 有界序列化；质量 profile 用固定 SQL 模板产出确定性报告，经 `create_from_file` 落 Artifact。

**Tech Stack:** DuckDB（新增）、sqlglot（新增）、既有 ArtifactService/权限/审计/通知、React/Vitest。

**Spec:** [Week 17 技术方案](../../technical-proposals/2026-09-28-week17-data-exploration-quality.md)、[Week 13–17 计划](2026-09-24-week13-17-development.md)、DEVELOPMENT_PLAN.md §4–§5。

## Global Constraints

- **决策门硬约束**：技术方案 §8 七项决策未全部记录获批前，Week 17 保持 `pending_decision`，本计划只允许 17.0；不创建迁移/API/前端路由/实现测试。
- 只读、项目隔离、上限、审计、追溯五条红线任一无法满足即停（回到决策门）。
- 查询审计不落语句原文；报告幂等复用；`generator_version` 变化生成新报告。
- 迁移计划名 `20260924_66_data_exploration_quality.py`（获批后按实现日空闲号创建）。

## File map（获批后生效）

Create:

- `ml-platform/backend/app/models/data_exploration.py`、`app/models/quality_report.py`
- `ml-platform/backend/app/schemas/data_exploration.py`、`app/schemas/quality_report.py`
- `ml-platform/backend/app/services/query_service.py`、`app/services/quality_profile.py`
- `ml-platform/backend/app/api/data_exploration.py`、`app/api/quality_reports.py`
- `ml-platform/backend/alembic/versions/20260924_66_data_exploration_quality.py`
- `ml-platform/backend/tests/test_data_exploration_api.py`、`test_query_limits.py`、`test_quality_reports.py`
- `ml-platform/frontend/src/api/dataExploration.ts`、`src/api/qualityReports.ts`、`src/pages/DataExplorationPage.tsx`、`src/pages/QualityReportPage.tsx`
- `ml-platform/frontend/src/pages/DataExplorationPage.test.tsx`、`src/pages/QualityReportPage.test.tsx`

Modify:

- `app/models/__init__.py`、`app/config.py`（`query_*`/`report_*` 上限设置）、`app/main.py`、`requirements.txt`（`duckdb`、`sqlglot`）
- `frontend/src/App.tsx`（`/data-exploration`、`/quality-reports` 路由）、`components/AppLayout.tsx`、`i18n/index.tsx`（`QUERY_*` 错误码）
- `tests/week_manifest.py`（**追加进既有 `17:` 键**——该键历史上混有通用标注模块与弃用点焊模块，弃用项由 `DEPRECATED_TEST_MODULES` 过滤；新模块为通用 active 成员）、`frontend/src/weekAcceptance.test.ts`（第 17 周）

## Task 17.0 决策门（唯一当前可执行任务）

- [ ] 逐项过技术方案 §8 七项决策，将产品确认结果记录到 DEVELOPMENT_PLAN.md（新 §4.2 或日期条目），含每项的批准人/日期/选定值。
- [ ] 任一项未确认 → 在台账记录开放项，Week 17 保持 `pending_decision`，本计划到此为止。
- [ ] 全部确认 → 在台账记录"Week 17 获批 + 决策值"，状态更新为 `in_progress`，方可继续 17.1。

## Task 17.1 依赖与模型（RED → 实现）

- [ ] `requirements.txt` 增 `duckdb`、`sqlglot`；确认导入隔离（不破坏既有套件）。
- [ ] RED：QualityReport 唯一键（dataset_version + schema_hash + params hash + generator_version）；SavedQuery（若获批）owner/project 校验；空库 upgrade / downgrade / `alembic check`。
- [ ] 实现模型 + 迁移。

## Task 17.2 查询服务（RED → 实现）

- [ ] RED（`test_query_limits.py`）：拒绝矩阵逐项断言——CREATE/INSERT/UPDATE/DELETE/ATTACH/DETACH/COPY/INSTALL/LOAD/EXPORT/PRAGMA/`read_csv*`/`read_parquet`/`glob`/`parquet_scan`/多语句/注释混淆；行上限、字节上限、超时中断（工作线程 cancel）、并发上限；连接与临时文件清理；审计无语句原文。
- [ ] RED（`test_data_exploration_api.py`）：跨项目版本 404（`ArtifactService.resolve` 隔离）、权限矩阵、cursor 分页、X-Request-ID。
- [ ] 实现 `query_service.py`：sqlglot 校验器 + DuckDB 只读临时库（固定视图、`memory_limit`/`threads` 收紧、无扩展加载）+ 有界序列化；`data_exploration.py` API。

## Task 17.3 质量 profile 与报告（RED → 实现）

- [ ] RED（`test_quality_reports.py`）：固定模板列输出（null/distinct/range/top/outlier）；幂等复用（同四元组返回既有报告）；绑定头逐字段断言（含 `schema_hash`、`content_hash`、`generator_version`）；确定性（同输入两跑逐字节一致）；生成走 `resource.create` 权限 + 审计；下载经 Artifact 授权（他人项目 404）。
- [ ] 实现 `quality_profile.py`（固定 SQL 模板）+ `quality_report.py` 服务（`create_from_file` 落库）+ `quality_reports.py` API。

## Task 17.4 前端两页（RED → 实现）

- [ ] RED：`DataExplorationPage.test.tsx`（数据集/版本选择、SQL 编辑、上限与预算显示、分页预览、`QUERY_*` 错误本地化）；`QualityReportPage.test.tsx`（生成按钮状态、绑定头展示、下载入口）。
- [ ] 实现两页 + API client + 路由 + 导航 + i18n。

## Task 17.5 清单登记与聚焦门禁

- [ ] `week_manifest.py`：新模块追加进既有 `17:` 键（记录键的历史构成）；`weekAcceptance.test.ts` 第 17 周。
- [ ] 聚焦门禁（模式同前几周，替换 `--week 17` 与新文件名）：pytest 三模块 → `run_suite.py --week 17`（确认弃用模块仍被过滤）→ compileall → alembic → 前端三件套 → `git diff --check`。

## Task 17.6 验收与台账收口

- [ ] 浏览器验收：真实数据版本上查询（含触发各上限的负例）、报告生成与下载、错误本地化。
- [ ] 收据：报告 Artifact 三键绑定 + 当前 SHA + 只读强制证明（拒绝矩阵输出）写入 `temp_test/week17-local/`。
- [ ] 先更新 DEVELOPMENT_PLAN.md，再归档详细记录；上限默认值与决策值一并记录。

## Exit gate

- 只读强制有完整拒绝矩阵证据；项目隔离/权限矩阵回归通过；上限逐项生效且可中断；报告绑定三键 + 当前 SHA 且确定性成立；浏览器验收通过；聚焦测试/迁移/前端门禁全绿。

## Explicit exclusions

- 未获批前不执行 17.1–17.6 的任何一步；不部署 Superset/Label Studio；不代理任意数据库；不新增跨项目访问；不以本计划或技术方案文档宣称完成。
