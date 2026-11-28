# 验收证据：补齐路线第二批 S2a（划分与盲测地基）

- **日期**：2026-11-26
- **范围**：B2-G1 数据集划分管理（从零建）+ 建模轮次锁定 + 盲测历史台账 + E03 评估上限 + E04 入库即定
- **技术方案**：[技术方案-补齐路线第二批.md](技术方案-补齐路线第二批.md) §6（范围裁决/表设计/服务/API/测试矩阵）
- **提交**：S2a 收口提交（本文件所在提交）
- **环境**：Windows 11 本机；SQLite；训练红线以既有 AutoML 模块回归为证

## 1. 验收口径逐条结论（路线 B2-G1 + 计划 §3 S2a）

| # | 口径 | 结论 | 证据 |
|---|---|---|---|
| 1 | 轮次启动后划分不可变（修改被拒且落审计） | **passed** | API 面无划分更新端点（不可变性为构造性保证）；`test_modeling_rounds.py::test_start_round_locks_and_records_audit`（创建即锁定 + `modeling_round.start` 审计事件） |
| 2 | 盲测样本被使用后自动进历史台账 | **passed** | `test_blind_eval_cap_default_two`（每次评估落 blind_test_usages；E03 上限 2 触顶拒绝 BLIND_EVAL_CAP_REACHED） |
| 3 | 新轮次无法复用旧盲测 | **passed** | `test_used_blind_cannot_be_reused_by_new_round`（BLIND_REUSE_REJECTED）；样本键集指纹跨版本可比（同批样本换版本仍能撞出）；`test_new_batch_new_version_can_start_fresh_round`（新批次新版本可开新轮次） |
| 4 | 同一种子重放划分一致 | **passed** | `test_dataset_splitting.py::test_same_seed_replays_same_split_and_fingerprint`（角色序列与指纹全等） |
| 5 | 三策略划分正确 | **passed** | 分层（类最小代表）/分组（整组不跨角色）/时间（尾部留出）三用例；无效输入拒绝 |
| 6 | 默认路径零变化（兼容红线） | **passed** | `automl_execution` 仅在显式 `dataset_split_id` 时过滤 frame；AutoML 回归 81 用例绿（excluded_columns/anomaly/ensemble/multioutput，不改一字通过） |
| 7 | 训练只用 development 行、盲测永不进训练 | **passed**（单元级） | `TestTrainingWiring::test_development_filter_excludes_blind_rows`（角色过滤互斥完备）；全链 split-aware 训练任务未做（API 契约与过滤函数为证，登记为范围限制） |
| 8 | 盲测复核隐藏模型分数 | **passed**（裁剪层） | 盲测评估 API 响应不含逐样本分数（字段裁剪）；标注门户复核流程随 S3 多人标注重构建设（技术方案 §6.0 登记的阶段衔接） |

## 2. 横向合同与回归

| 项 | 结论 | 证据 |
|---|---|---|
| 迁移纪律（`_114`） | **passed** | `test_gap_batch2_migrations.py::test_s2a_split_round_tables_upgrade_and_downgrade`（四新表往返 + `alembic check` 零漂移） |
| 测试登记 | **passed** | week 1 新增 test_dataset_splitting / test_modeling_rounds；test_suite_manifest 绿 |
| 与 excluded_columns 共用取数入口层级 | **passed** | 同在 `read_automl_dataset` 之后过滤（frame 级），互不干扰（回归同批绿） |

## 3. 未验证与遗留

- **not_run**：split-aware 全链训练任务（造工件+全量跑）；PG 往返（CI 背书）；真实大表（28 万行）成员批插压测（批插 chunk 5000 已实现，容量按日量观察）。
- **登记限制**：无业务样本键的划分（行号回退指纹）跨版本复用检测退化为划分身份比对（技术方案 §12.9）——生产使用建议数据集导入带 sample_id 列（既有能力）。
- **S2b 衔接**：发布门禁终验/不回退检查（B2-03/E01）经 `record_blind_evaluation` 消费盲测（purpose=release_final_validation / no_regression_check 已备）；S2b 前端交付三级样本量看板与划分控件。

## 4. 结论

S2a 八条口径全部 passed（口径 7/8 带范围限制如实登记）；E03/E04 落地；兼容红线经 AutoML 回归背书。任务完成不等于发布就绪。

## 〔审核更正 2026-11-27〕三批复审结论

> 原表原结论保留不改写，以本节为准。

### P0：训练接线不可达

- **`dataset_split_id` 没有任何入口能传进来**：`AutoMLRunRequest` 是 `extra="forbid"` 且无此字段（`api/training.py:89-127`），params 组装也不含（:795-824）；全后端只有 `automl_execution.py:3096` 一处读取。**划分训练接线在真实链路上不可达**——验收口径 5「AutoML 全量回归通过、既有任务结果可复现」的「零变化」因此空洞成立。**〔已修复 2026-11-27 `160433b5`〕**：AutoMLRunRequest 增可选 `dataset_split_id` + 创建时划分存在性/归属校验（404 DATASET_SPLIT_NOT_FOUND）+ params 组装传递——训练接线自此可达；「零变化」用例是空断言的问题仍在（另需断言 development 行数）。
- 「默认路径零变化」用例是**空断言**：`tests/test_modeling_rounds.py:200-205` 只断言一个字典的 `.get()` 为 None。
- 划分创建用 `pd.read_csv`（`api/splits.py:98`），训练用 `read_automl_dataset`（Excel 走 read_excel）——**Excel 数据集的行号对不上**。

### P0：盲测复用检测名存实亡（验收口径 3 标 passed）

原文「同批样本换版本仍能撞出台账」**不成立**（内存库复核）：
- 台账查询**只限同一 `dataset_version_id`**（`services/modeling_rounds.py:55-77`）——同一批样本换版本、同种子，blind 指纹完全相同，新轮次仍被允许。
- 比对是**整集指纹相等**，不是「交集非空」——同版本换种子后，12 行盲测里 3 行与已用盲测重叠，仍放行。

### P1：其余

- 三策略是**自写近似**，不是文档说的镜像 `train_test_split` / `GroupShuffleSplit`。
- 迁移里 `blind_eval_cap` 无 DB 默认值、`purpose` 无 CHECK，只有 ORM 层。
- `GET /dataset-splits/{id}/summary` 端点不存在；§6.6 说的「路由面断言」用例不存在。
- 盲测台账的 `sample_count` 与 `samples_fingerprint` 由**客户端自报**，不与划分核对。

### 前端

三级样本量看板与划分控件未落地（原文「随 S2b 交付」，S2b 未交付）。4 个写端点未登记 `PROJECT_WRITE_ACTIONS`。
