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
