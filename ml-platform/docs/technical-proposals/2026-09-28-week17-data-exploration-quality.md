# Week 17 数据探索与质量报告技术方案

**日期：** 2026-09-28
**状态：** 设计已获批（2026-09-28，§8 七项决策门全部通过）。Week 17 状态为 `planned`——实现按[实施计划](../superpowers/plans/2026-09-28-week17-data-exploration-quality.md)执行，完成周度门禁前不得宣称完成。
**范围（若获批）：** 基于 DuckDB 的项目内只读数据探索、数据质量 profile、可追溯质量报告 Artifact、查询与报告页面
**不包含（无论是否获批）：** Label Studio / 多模态标注与回流、Superset 部署（为独立选项，见 §9）、任意 SQL 代理、跨项目数据访问

## 1. 目标与方案定位

为已冻结的 `DatasetVersion` 提供两条安全的数据消费路径：

1. **探索查询**：项目成员对项目内数据版本执行只读 SQL，受行数/字节/时间三重上限约束。
2. **质量报告**：对数据版本生成确定性质量 profile（null/唯一/类型/范围/重复/离群），作为可下载、可追溯的 Artifact。

两者的共同红线：**只读、项目隔离、有上限、可审计、可追溯**。Week 13–16 若已完成，报告生成可（可选地）以 Week 14 作业形态运行；未完成也不阻塞本方案——查询与 profile 在 API 进程内即可执行。

## 2. 与既有合同的关系（已核实的直接复用点）

| 既有合同 | Week 17 用法 | 核实结论（2026-09-28） |
|---|---|---|
| `DatasetVersion` | 查询与报告的对象；`schema_hash`/`content_hash` 作为报告追溯键 | 模型原生含 `content_hash`、`schema_hash`、`row_count`、`parse_contract`，报告绑定无需新增字段 |
| `ArtifactService`（`resolve(artifact_id, project_id)` / `materialize` / `create_from_file`） | 输入物化到临时文件；报告落库与授权下载 | `resolve` 自带 project_id 参数即项目隔离裁决点；`create_from_file` 支持任意制品类型 |
| 项目权限 / 审计 | 查询与报告生成的访问控制与审计 | 复用 `execution.operate`（查询）与 `resource.create`（报告生成） |
| 通知 / X-Request-ID | 长耗时报告生成的完成通知与幂等 | 既有机制 |

依赖新增（获批后）：`duckdb`（查询与 profile 引擎）、`sqlglot`（SQL 语句校验）。已核实两者当前均不在 `requirements.txt`。**DuckDB 原生读取 CSV/Parquet，不依赖 pyarrow**——规避本机 pyarrow 环境问题的既有记录（HANDOVER §6.9）。

## 3. 总体架构

~~~text
DataExplorationPage / QualityReportPage
        |
        v
/api/data-exploration、/api/quality-reports
        |
        v
query_service.py                          quality_profile.py
  1) ArtifactService.resolve(project 隔离)    1) 同输入物化
  2) materialize → 临时只读副本                2) 固定 DuckDB SQL 模板聚合
  3) sqlglot 校验（§4）                        3) 结果写入报告 Artifact
  4) DuckDB 只读连接执行（线程 + 超时中断）
  5) 有界序列化返回
~~~

查询与 profile 都在 **per-request 临时 DuckDB 库**（内存或临时文件，请求结束即删）中执行，唯一的表是物化制品上的视图；平台数据库与文件系统不出现在可查询范围内。

## 4. SQL 安全合同

1. **语句校验（sqlglot）**：仅接受单条语句且语句类型为 SELECT；拒绝 DDL/DML（CREATE/INSERT/UPDATE/DELETE/ATTACH/DETACH/COPY/INSTALL/LOAD/EXPORT）、PRAGMA、表值函数 `read_*`/`glob`/`parquet_scan` 等文件访问入口、宏创建。校验不通过 → 422 `QUERY_FORBIDDEN`（带命中的规则名，不带原文上下文）。
2. **执行环境封闭**：DuckDB 以只读方式打开临时副本；不加载 httpfs 等扩展；`SET threads`/`memory_limit` 按上限收紧；只有预建视图可见（视图名 = 数据版本列名映射）。
3. **资源上限（Settings，默认值待决策门确认）**：`max_rows`（默认 1,000）、`max_result_bytes`（默认 10MB）、`max_runtime_seconds`（默认 30s，超时经工作线程中断返回 `QUERY_TIMEOUT`）、并发查询数/用户（默认 2）。
4. **审计**：每次查询记录 user/project/dataset_version/语句长度/行数/耗时/结果码（不记录语句原文，防敏感数据入日志）。

## 5. 核心领域模型

迁移计划名 `20260924_66_data_exploration_quality.py`（以实现日空闲号为准）。

- **SavedQuery**（可选，决策项）：project 内命名查询，owner 限定，仅存 SQL 文本与参数（无结果）。
- **QualityReport**（表 `quality_reports`）：`dataset_version_id`、`schema_hash`、`content_hash`、`params_json`（阈值等）、`generator_version`、`artifact_id`（FK artifacts）、`status`、`created_by`。同一 `(dataset_version_id, schema_hash, params_json hash, generator_version)` 幂等复用已有报告。
- **报告 Artifact**：经 `create_from_file` 落库（类型 `quality_report`，JSON + 摘要头），下载走既有 Artifact 授权路径。

## 6. 质量 profile 合同

对每个列输出固定结构：`dtype`、`null_count/null_ratio`、`distinct_count`、`min/max/mean/std`（数值列）、`top_values`（分类型列，≤20）、`duplicate_row_count`（表级）、`outlier_iqr_count`（数值列）。全部由固定 SQL 模板在 DuckDB 中计算，输出头部绑定：

~~~json
{ "dataset_version_id": "...", "schema_hash": "...", "content_hash": "...",
  "params": {...}, "generator_version": "w17q1", "generated_at": "...", "row_count": ... }
~~~

确定性要求：同输入 + 同参数 + 同 generator 版本 → 逐字节一致（测试固化）；`generator_version` 变化即生成新报告。

## 7. 接口边界（获批后实现）

前缀 `/api/data-exploration`、`/api/quality-reports`；权限：查询 = `execution.operate`，报告生成 = `resource.create`，查看/下载 = `project.read`：

| 方法 路径 | 语义 | 主要错误 |
|---|---|---|
| POST `/data-exploration/query` | 只读查询（dataset_version_id + SQL + 分页 cursor） | 422 `QUERY_FORBIDDEN`；408 `QUERY_TIMEOUT`；422 `QUERY_LIMIT_EXCEEDED`；404 版本不可见 |
| GET/POST/DELETE `/data-exploration/saved-queries` | 可选（决策项） | — |
| POST `/quality-reports/generate` | 生成报告（幂等键；重复请求复用既有报告） | 409 生成中；422 参数 |
| GET `/quality-reports`、GET `/{id}` | 列表/详情（含绑定头） | 404 隐藏式 |
| GET `/{id}/download` | 经 Artifact 授权下载 | 403/404 |

## 8. 决策记录（2026-09-28 全部获批）

第 1/3/4/5 项由用户于 2026-09-28 确认，第 2/6/7 项按仓库证据收口；台账记录见 DEVELOPMENT_PLAN.md §4.2。

| # | 决策项 | 决策 | 依据 |
|---|---|---|---|
| 1 | 功能范围 | **批准**：DuckDB 只读查询 + 质量 profile + 报告 Artifact；不部署 Superset | 用户确认；Superset 若未来需要另立集成计划 |
| 2 | 数据访问角色 | 查询 `execution.operate`（owner/editor/operator）、报告生成 `resource.create`、查看/下载 `project.read`（viewer 只读）；不新增 permission 字符串 | 与 Week 13 决策 4 同构；`PERMISSIONS` 为封闭 frozenset（Week 13 已核实） |
| 3 | 资源上限值 | 行 1,000 / 结果 10MB / 30 秒 / 并发 2（Settings 可配） | 用户确认默认组 |
| 4 | 审计与保留 | 查询审计保留 90 天（可配）；语句原文不入审计 | 用户确认；保留期仿既有 `inference_log_retention_days` 惯例（默认 30、可配 1–365） |
| 5 | SavedQuery | 首期不纳入，二期再议 | 用户确认；降低首期合同面 |
| 6 | 结构化审核扩展 | 维持现状：既有标注指派/回传/验收为基线，不新增重复 API | Week 13–17 计划 §8.1 强制项 |
| 7 | 成本预算 | API 进程内执行，零新增基础设施；作业化（依赖 Week 14）另批 | 无计费系统可对接；duckdb 为进程内引擎 |

结论：决策门全部通过，Week 17 状态由 `pending_decision` 转为 `planned`；实现按实施计划自 Task 17.1 起。

## 9. Superset 替代路径

若产品选择 Superset 而非 DuckDB：保持本方案的权限、隔离、审计与报告 Artifact 合同不变，另立集成计划（部署、账号映射、行级安全模型），**不静默替换查询边界**；DuckDB 方案保留为质量 profile 的内部引擎。

## 10. 测试与验收标准（获批后执行）

1. `test_data_exploration_api.py`：项目隔离（他项目版本 404）、权限矩阵、审计记录、cursor 分页。
2. `test_query_limits.py`：DDL/DML/attach/copy/read_* 全量拒绝矩阵；行/字节/超时上限逐项触发；并发上限；中断后连接清理。
3. `test_quality_reports.py`：幂等复用、绑定头完整性（dataset_version/schema_hash/params/generator_version/当前 SHA）、确定性（同输入两跑一致）、下载授权、报告 Artifact 走 ArtifactService。
4. 浏览器：查询页（上限提示、分页预览、错误本地化）、报告页（生成/下载）。
5. 清单：新增测试模块**追加进 `week_manifest.py` 既有 `17:` 键**——该键历史上混有通用标注模块与弃用点焊模块（后者由 `DEPRECATED_TEST_MODULES` 过滤，默认 `--week 17` 不运行），新模块为通用 active 成员；此特例已记录。
6. 证据绑定当前 SHA；报告 Artifact 必须可复核绑定三键（dataset_version、schema_hash、参数）。

## 11. 显式排除项

- 不实现 Label Studio/多模态/iframe/训练数据回流（维持 2026-08-18 延后决策）。
- 不部署 Superset、不代理任意数据库连接、不开放文件路径读取。
- 不以本方案文档宣称任何完成状态；实现完成周度门禁前不写发布结论。

## 12. 方案结论

本方案把"数据探索"压缩为一个可安全获批的最小合同：DuckDB 临时库 + sqlglot 校验 + 三重上限 + Artifact 追溯，全部叠加在既有项目权限与制品合同上。决策门已于 2026-09-28 全部收口，实施计划（Task 17.1 起）即可执行。
