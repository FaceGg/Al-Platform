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

## 5. 〔审核更正 2026-11-27〕三批复审结论——§4「十四条口径全部 passed」不成立

> 取证：代码级逐项核对 + 运行验证。**原表原结论保留不改写，以本节为准。** 本阶段是第二批对标竞品的核心价值所在（堵「F1 0.999 浅验证集放行」漏洞），复审发现两条核心门禁名存实亡。

### 5.1 P0：核心门禁在真实链路上名存实亡（原标 passed）

| # | 原声明 | 实际 | 代码事实 |
|---|---|---|---|
| 1 | 「终验指标**只能取自 S2a 锁定盲测**」 | **不成立** | `_blind_final_metrics`（`services/release_governance.py:805-829`）直接取 `version.metrics`，与 metric_floor 同源同阈值；额外条件只是「项目里存在锁定轮次且 cap 未满」，轮次选取是「项目最近一个锁定轮次」（:430-440），与被发布版本无关联。**〔已修复 2026-11-27 `c14af2a1`〕**：有监督任务对锁定盲测段真实打分（`score_blind_split`：物化→blind 过滤→密封验签→打分→与 target 比对，`scored_from=blind_split`）；无监督保持 version.metrics 冠军资格口径并 detail 如实标注 |
| 2 | 「候选与现役冠军在**同一批盲测样本**上配对盲评」 | **不成立** | `evaluate_no_regression`（:553-616）比较两个版本各自的 `version.metrics`；指纹是 `{version, round}` 的哈希，**从未被比较**；`usages` 查询后未使用。**〔已修复 2026-11-27 `c14af2a1`〕**：候选与冠军对同一 blind 段分别打分，同批配对由「同一 frame」构造性保证，样本集指纹随 detail 落档（`same_blind_samples=True`） |
| 3 | 默认配置下发布可用 | **默认 cap=2 时归档门禁必 failed** | 探测评估（`approval_executors.py:205-232`）先消耗 2 次 cap，正式评估得到 `blind_final_validation=failed(no_blind_metrics)`、`no_regression=failed(blind_eval_cap_reached)`。**测试与 M2 演练都手工把 cap 设成 5 或 6 绕开了**。〔待复核 2026-11-28〕随 #1 修复终验改走盲测打分，cap 消耗语义变化需重估（探测评估的记账次数）|
| 4 | 「有效授权发布**免逐单审批**」（G2） | **不成立** | 预授权只在已批准的 model_release 单执行时才被检查，仍需另一人四眼批准；无免审路径 |
| 5 | 预授权发布执行 | **必 NameError** | `ReleaseExecutor.perform`（`approval_executors.py:256`）使用未导入的 `_uuid` **〔导入已修 2026-11-27 `8898aa6b`；原句「作用域内无 import」随修复作废〕**；免审路径与指纹推导仍开放；带 `preauthorization_id` 的发布从未可用。release-request 的 payload 也不含 `acceptance_gates_fingerprint`，必 `PREAUTH_GATES_CHANGED` |
| 6 | 「产物摘要不符的回执被拒绝」（G3） | **API 上不可达** | 回执端点不传 `expected_digest`（`api/release_governance.py:408-416`），请求体也无时间窗字段；服务层 digest_mismatch 逻辑正确但 API 永远产不出 mismatch |
| 7 | 豁免三约束（E01） | **约束在，效果无** | 三分支逻辑成立（`approval_executors.py:306-323`），但 `perform` 是空操作（:328-330），不创建灰度、不解除拦截；model_release 创建时只要有失败项就拒（:227-232），**豁免批准后仍无路可发**。且 `test_release_governance.py` 无任何 exemption 用例——验收 #13 无证据 |
| 8 | 「窗口超时可接管」 | **未实现** | `force_shadow_gate` 只被接收和存入 payload，无任何读取方；置 True 且无报告时仍 failed |

### 5.2 P1：测试缺口（原未登记）

- **E13 场景矩阵端到端用例 0 个**——技术方案 §7.5 第 6 条明文要求「回退豁免/影子回放/发布回滚」三场景端到端用例；tests 目录无任何引用。验收 14 条口径与遗留节均未提。
- **影子对照零测试**——技术方案 §7.4 测试矩阵明文要求 `test_shadow_compare.py`，**该文件不存在**；验收 #1、#2 无用例支撑。
- `traffic_mirror`（流量镜像）未实现——只是对整个 frame 打分，不关联 champion 行。
- 影子种子是时间派生，API 无 seed 参数；无样本池时抛 `GovernanceError` 但端点只接 `SplitError` → 500。
- 下游消费未过滤 `channel`：水位线计数与 `business_alert_ratio` 都会把影子行算进去。
- **〔复审后新发现并修复 2026-11-27/28〕**：①打分链路两处键错配（`_load_candidate_bundle` 曾用 `registered_model_id` 查 ModelLibrary、工件归属曾取 owner_id 当 project_id——影子/盲测打分恒失败，`c14af2a1` 修复；champion 对照调用点漏传随第二轮复审补 `6492de79`）；②**`SHADOW_SAMPLE_SOURCES` 常量自 40351d9f 被引用但从未定义**——`run_shadow_batch` 首次调用必 NameError，影子运行端点从未可用（M2 演练影子报告手工插行、无测试调用，两轮审核均漏，2026-11-28 新测试首次真实调用抓出，`6492de79` 补定义）；③影子端点 `SHADOW_NO_SAMPLE_POOL` 曾 500，已修（GovernanceError 映射，`c14af2a1`）。

### 5.3 P1：其余名义化

- Wilson 门禁在真实链路永不评估：release-request 端点不传 options；所需的 `recall_minority_true_positive` / `total_positive` 键全后端无生产者。
- 无监督口径只看 `synthetic_auc ≥ 0.5`，`normal_fpr`、`stability` 未检查。
- drift 的「未消解」等于「未提案」——点一下提案即放行。
- 预授权比对的指纹是**客户端自报字符串**，没有服务端推导，「质量门变更拦截」是名义的。
- `GET .../release-preauthorizations` 端点不存在；`GET /dataset-splits/{id}/summary` 不存在。
- Challenger 退役不存退役计划，留下孤儿 draft revision。
- 验收 #5 引用的 `TestNoRegression` 类不存在（实为 `TestReleaseGates` 的三个方法）；#12「三态」只测了一态。

### 5.4 P2：前端

**S2b 前端完全未落地**——计划 §10 导航归属「影子推理归算法平台·模型运营」「发布门禁/别名在模型库详情承载」全部为空；对 challenger / release-governance / preauthorization / release-request / receipts 等关键词在前端源码（除测试）命中均为 0。原文登记「API 先行，UI 随 M2 补」，**但 M2 已收口而 UI 没补**（见 M2 更正）。

### 5.5 更正后的口径状态

十四条口径中 **10 条 failed、4 条 passed**（2026-11-27 复审时点；修复进度：#3/#4 已修 `c14af2a1`、#7 已修 `8898aa6b`、#5 部分修，见 §5.1 标注）。failed：#1（影子零测试）、#2（默认 cap 下归档必 failed）、#3（终验取 version.metrics）、#4（不回退非同批配对）、#6（免审不成立）、#7（执行器 NameError）、#10（回执 API 不可达）、#12（接管未实现）、#13（豁免无效果）、#14（E13 用例 0 个）。passed：#5（Challenger）、#8（预授权四失效，服务层）、#9（门禁四拦截 + Wilson，函数级）、#11（回执放量 opt-in）。结构化结论见 [验收-补齐路线-S2b.json](验收-补齐路线-S2b.json)。**7 个写端点未登记 `PROJECT_WRITE_ACTIONS`、API 级测试零越权断言**（实测鉴权本身正确）。

### 5.6 已证伪（留痕）

- 「跨项目越权（影子报告导出、回执）」：实测对无成员关系项目的端点返回 `404 PROJECT_NOT_FOUND`，**不成立**。

---

## 6. 〔第三轮复审 2026-11-28〕修复进度更新

> 本节为 2026-11-28 第三轮复审后的修复进度登记，原 §5 保留不改写。

- **#2 默认 cap 下归档必 failed——已修**（`6f1c5b3c`）：盲测台账幂等记账（同轮次同指纹同用途不重复消耗额度），探测+正式双跑不再双重记账，默认额度 2 恰好覆盖终验+不回退两门。
- **#13 豁免无效果——已修**（`6f1c5b3c`）：豁免执行器真实生效；被拒发布申请存档落档为豁免依据（曾即造即删，豁免永远无据）；门禁探测对已批准豁免仅放行 no_regression 失败，硬失败仍拦。豁免 HTTP 级端到端见 E13 场景 A。
- **#14 E13 用例 0 个——已补**（`6f1c5b3c`）：`tests/test_e13_scenarios.py` 三场景全链 HTTP（回退豁免/影子回放/发布回滚）。
- **#1 影子零测试——部分补**：`test_audit_fixes_20261127.py` champion 对照 + E13 场景 B 影子回放 HTTP；专项 `test_shadow_compare.py` 仍未建。
- **traffic_mirror（流量镜像）——已落地**（2026-11-28 第四波）：`traffic_mirror_keys` 镜像该部署近期真实生产推理流量（online/batch）的 sample_key（最近优先、去重保序），影子样本由真实流量驱动；无生产流量或样本池无命中 → 409 `SHADOW_NO_TRAFFIC` 诚实失败（曾按「全量 frame」静默兜底，来源语义名存实亡）；champion 对照两种来源均做（曾仅 random_sample）；HTTP 级 E13 场景 D 两用例（流量命中/无流量拒绝）。
- **仍开放（2026-11-28 第四波后）**：#6 预授权免审路径与指纹推导、#10 回执 API expected_digest/时间窗、#12 影子窗人工接管、#9 门禁四拦截 Wilson 真实链路（traffic_mirror 与前端治理面板已落地，见上）。
- **写端点豁免文档化——已登记**（2026-11-28 第四波）：回执端点（POST `/inference-deployments/{id}/rollouts/{id}/receipts`）不登记 `PROJECT_WRITE_ACTIONS` 的依据为「登录会话 + inference.operate 权限 + 服务层 `record_rollout_receipt` 内 `_audit` + 回执行 reported_by_id/status/digest_mismatch 落列即不可变台账，属服务层审计形态」（原注释「按 X-Api-Key 外部鉴权」表述失实，已更正）；豁免位置：`app/api/release_governance.py` PROJECT_WRITE_ACTIONS 注释 + 本节 + 技术方案第二批 §12.A。
- **S2b 前端治理面板——已落地**（2026-11-28 第四波，导航归属计划 §10.2「算法平台 · 模型运营」独立菜单）：`ReleaseGovernancePage`（`/algo/release-governance`）承载部署域治理——challenger 注册/退役、影子打分（随机抽样/流量镜像两来源）、影子报告列表 + CSV 导出、预授权授予/按 ID 吊销、发布申请（门禁 checks 展示）；无 challenger 读取端点故不显示候选现状（诚实设计，页面文案说明）；测试 `ReleaseGovernancePage.test.tsx`。
