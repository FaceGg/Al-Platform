# 验收证据：补齐路线第二批 S2b（发布治理链）

- **日期**：2026-11-26
- **范围**：B2-09 Challenger 别名 + B2-02 影子对照 + B2-03 发布门禁（含 E01 不回退 / E02 Wilson）+ B2-G2 预授权 + B2-G3 影子窗口/回执/按量放量 + E11 签收单模板
- **技术方案**：[技术方案-补齐路线第二批.md](技术方案-补齐路线第二批.md) §7（代码事实基线/表设计/服务/API/测试矩阵）、§12.10–11
- **提交**：S2b 收口提交（本文件所在提交）
- **环境**：Windows 11 本机；SQLite；rollout 集成用既有 FakeRuntime 夹具

## 1. 验收口径逐条结论（路线 B2-02/03/09 + G2/G3 + 计划 §3 S2b）

| # | 口径 | 结论 | 证据 |
|---|---|---|---|
| 1 | 双模型同集打分一致率报告可导出 | **passed**（逻辑层） | `run_shadow_batch`（channel=shadow 落 InferenceResult，extra 带 champion 对照值与抽样种子）+ `build_shadow_report`（一致率+分组指标+缺失原因）；CSV 导出端点。真实模型包打分链路以密封验签加载为证；端到端真模型推理 not_run |
| 2 | 影子任务不写预警表 | **passed**（结构层） | 影子打分仅写 InferenceResult，不触达任何 alert 产生器（代码路径无预警调用） |
| 3 | 低 F1/漂移超阈/样本不足/无盲测四种情形均拦截 | **passed** | `test_release_governance.py::TestReleaseGates::test_four_intercepts`（metric_floor/blind_final_validation/blind_sample_floor 三拦截）+ `test_drift_severe_intercepts` |
| 4 | 无监督候选不因无 F1 误拦、也不无门槛放行 | **passed** | `test_unsupervised_candidate_not_blocked_by_f1`（synthetic_auc 冠军资格键；Wilson 对无监督不启用） |
| 5 | 不回退（E01）：同批盲测配对、容差比较；基线缺失=不适用 | **passed** | `TestNoRegression` 三用例（同轮次盲测记账、候选弱于冠军拦截、无冠军 deployment not_applicable）；样本集指纹一致校验在记账层 |
| 6 | Wilson 下界（E02）：30 检出 29 下界 83.3% < 90% 不通过 | **passed** | `TestWilson::test_roadmap_example_29_of_30_is_below_90`（wilson_lower_bound(29,30)=0.8333） |
| 7 | 通过单可追溯全部检查值 | **passed** | release_checks 表随 model_release 审批单归档（五项+Wilson 各自 threshold/observed/verdict）；release-request 端点响应逐项返回 |
| 8 | B2-09 Challenger 注册/退役留痕；别名切换沿用 stable 语义 | **passed** | `test_challenger_register_retire_with_audit`（注册/退役审计各 1 条）；「切换即时生效」= 既有 rollout 完成语义（stable 别名切换，rollout 回归 37 用例背书） |
| 9 | G2：授权人=申请人使用被拒；过期/超次/撤销/质量门变更不再命中；有效授权免审且留痕 | **passed** | `TestPreauthorization` 3 用例（SELF_GRANTED_DENIED + 四失效场景逐一 + 正常 use 计数） |
| 10 | G3：产物摘要不符的回执被拒绝 | **passed** | `test_receipt_digest_mismatch_is_marked`（digest_mismatch 不计入放量） |
| 11 | G3：无回执不放量 | **passed** | `test_inference_rollout.py::test_receipt_volume_gate_blocks_full_rollout_until_threshold_met`（ROLLOUT_RECEIPT_VOLUME_SHORT → 摘要不符回执不计入 → 达标后完成）；**opt-in 阈值**（thresholds.min_receipt_scored_count，缺省=既有行为零变化，§12.11 登记） |
| 12 | G3：影子观察窗前置（无报告不放行；超时可接管） | **passed**（逻辑层） | `shadow_window_gate`（no_shadow_report/not_comparable/达标三态）；接管=ReleaseExecutor 外 quality.manage 强制放行路径（force_shadow_gate 字段+审计，端到端 not_run） |
| 13 | 豁免三约束（E01）：终验未过不可发起 / 硬检查失败不可豁免 / 理由<10 字被拒 | **passed** | `ExemptionExecutor.validate_create` 三分支（EXEMPTION_FINAL_VALIDATION_NOT_PASSED / EXEMPTION_HARD_CHECKS_FAILED / EXEMPTION_REASON_TOO_SHORT）；四眼（豁免人≠发起人）由队列层强制 |
| 14 | 业务口径回退（E12） | **passed**（观测层） | `business_alert_ratio`（当前/基线窗口预警率倍数）；自动回退动作接线 not_run（观测值就绪，触发阈值挂 rollout.thresholds 由 M2 演练配置） |

## 2. 横向合同与回归

| 项 | 结论 | 证据 |
|---|---|---|
| 迁移纪律（`_115`） | **passed** | `test_gap_batch2_migrations.py::test_s2b_release_governance_tables_upgrade_and_downgrade`（四新表 + role CHECK 重建往返 + `alembic check` 零漂移；独立脚本 temp_test/m115_check.py 双向往返过） |
| 测试登记 | **passed** | week 1 新增 test_release_governance（18 用例）；rollout 模块补回执门集成用例（37 用例全绿） |
| 既有行为零变化 | **passed** | rollout 回归 37 用例（opt-in 阈值缺省关）；推理明细/开放接口回归 61 用例绿 |
| 模型包密封防线 | **passed** | 影子加载先验 `seal_is_valid` 再 joblib 反序列化（与 serving_deployment 算子同防线；扫描器中危提示的对齐处置） |
| 签收单模板（E11） | **passed** | `docs/现场准入签收单模板.md`（六类项目+五方交接+七项现场操作） |

## 3. 未验证与遗留

- **not_run**：真实模型包端到端影子打分（需真实工件与特征列）；影子窗强制接管端到端；业务回退自动触发接线（观测层就绪）；PG 往返（CI 背书）；前端发布治理 UI（Challenger/影子/门禁展示挂部署详情——API 先行，UI 随 M2 演练补，如实登记）。
- **范围登记（§12.10）**：E01 严格模式「禁新漏检」的逐样本口径需盲测复核门户产出逐样本真值——随 S3 标注质量链落地；S2b 交付同批指纹校验 + 点估计容差比较。
- **既有平行路径登记**：闭环即时换模（closed_loop_actions）无审批介入、保留原样（有自己的 hard_gates+熔断）；S2b 治理链覆盖 rollout 发布路径。

## 4. 结论

S2b 十四条口径全部 passed（口径 1/12/14 带范围限制如实登记）；E01/E02/E11/E12 增补落地；既有 rollout 行为零变化经回归背书。任务完成不等于发布就绪。
