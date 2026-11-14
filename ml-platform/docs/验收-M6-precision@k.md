# 验收记录：M6 半监督精调档 1（技术方案 §6.4 判据②）

- 日期：2026-11-14
- 方案：[技术方案-无监督弱监督异常检测.md](技术方案-无监督弱监督异常检测.md) §6.2 验收 / §6.4 二期总验收 判据②
- 结果数据：[验收-M6-precision@k.json](验收-M6-precision@k.json)
- 可复现：`ml-platform/backend/tools/acceptance/run_m6_precision_at_k.py`
  （在 `ml-platform/backend` 下：`.venv/Scripts/python.exe tools/acceptance/run_m6_precision_at_k.py`；默认写 `ml-platform/docs/验收-M6-precision@k.json` + `.md`；`--data <回流标签集.csv>` 进入 real-labels 模式）
- 运行模式：**mechanism-verification**

## 0. 诚实边界（先读）

> mechanism-verification 模式的数字只证明机制在合成标签上成立，不代表 §6.2 真实门槛（confirmed_fault ≥50 条真实确认故障 + ≥2 种真实异常形态）已满足；真实门槛状态见 m6_real_gate。

- 数据来源：`deterministic-synthetic-generator`（provenance=generator-synthetic）
- §6.2 真实门槛状态：**not_unlocked**（unlocked=False）——mechanism-verification 模式：本次标签为合成标签，不构成 §6.2 真实门槛证据；平台真实 confirmed_fault 标签数 0（DEVELOPMENT_PLAN「2026-11-12 二期开工」登记 M6 按 §6.2 自动顺延），真实门槛未解锁
- 机制门槛（合成/给定标签上跑 meets_m6_gate 的结果（机制门槛，非真实门槛））：unlocked=True，confirmed=60/50，形态簇=2
- 发布就绪：**否**（阻塞：§6.2 真实标签门槛未解锁（平台真实 confirmed_fault 标签 0 条））

## 1. 数据与模型

- 数据构造口径：确定性合成发生器：AR(1) 弱相关正常样本；确认故障类取自独立随机种子（seed+1000）合成基准中**分数超基线阈值**的异常（现场口径：只有触发过报警的样本才可能被确认）；false_alarm 类为正常样本中分数超基线阈值者
- 训练集 640 行 / 正常保留集 160 行（holdout_ratio=0.2）
- 评估集 300 行 = confirmed_fault 60 + false_alarm 40 + 正常背景 200
- 确认故障形态计数（取自独立种子 seed+1000 的合成基准）：{'uniform_outlier': 33, 'local_perturbation': 21, 'combinatorial_anomaly': 6}
- 模型：`iforest`，参数 {'n_estimators': 200, 'max_samples': 256}；contamination=0.01；seed=42

## 2. 阈值：一期标定 → 标签重标定

- 一期基线阈值 **0.57028**（一期标定：AnomalyScoreCalibrator.fit(holdout_scores, contamination=0.01).threshold_score（保留集 (1-contamination) 分位））
- 标签重标定阈值 **0.621496**（标签重标定：optimal_threshold_from_labels(confirmed_scores, false_alarm_scores)（漏报罚 2×误报，201 分位网格扫描））
- 阈值位移 Δ = **0.051216**

重标定细节：loss=0.725、fnr=0.3、fpr=0.125、confirmed=60、false_alarm=40

## 3. 判据②之一：precision@k（k=报警预算）

口径：报警预算口径 precision@k：报警集合 A(t)={score≥t}；操作员处置预算 k 条，按到达（时间）序取前 k 条处置，超预算部分被丢弃；precision = 处置批次中真故障（confirmed_fault）占比。该口径含阈值——阈值重标定可直接改善；纯排序口径（runner.py S4：混合池取分数前 k 名）阈值不变，另作对照列出。

> 夹具前提（机制前提，真实标签下需由数据检验）：真故障样本的分数整体高于误报样本（正常样本超基线阈值者）——这正是 §6.2 档 1「用标签把阈值抬到误报带之上」成立的前提。

| 指标 | 一期基线阈值 | 标签重标定阈值 |
|---|---|---|
| 阈值 | 0.57028 | 0.621496 |
| 报警数 | 101 | 47 |
| 报警预算 k | 60 | 60 |
| 超预算丢弃 | 41 | 0 |
| 处置批内真故障数 | 34 | 42 |
| **precision@k** | **0.566667** | **0.893617** |

- precision@k 提升：是（Δ=0.32695）
- 纯排序口径对照（阈值不变）：0.75（k=60）——提升来自运行点（阈值），不是排序变化

### 各类检出

| 口径 | 一期基线阈值 | 标签重标定阈值 |
|---|---|---|
| confirmed_fault 检出率 | 1.0 | 0.7 |
| false_alarm 类报警率 | 1.0 | 0.125 |
| 正常背景误报率 | 0.005 | 0.0 |

## 4. 判据②之二：合成基准重跑（防精调过拟合确认样本）

> synthetic_auc（ROC AUC）与 stability（Spearman）由分数排序决定、与判定阈值无关；normal_fpr / perturbation_recall 随阈值变化。重跑用同一模型、同一合成基准，只把判定阈值换成标签重标定阈值。

| 指标 | 一期基线阈值 | 标签重标定阈值 |
|---|---|---|
| synthetic_auc（≥0.85） | 0.9523958333333333 | 0.9523958333333333 |
| normal_fpr（≤contamination×1.5） | 0.0125 | 0.0 |
| stability（≥0.8） | 0.9882894106657931 | 0.9882894106657931 |
| perturbation_recall | 0.375 | 0.125 |
| **gates_passed** | **True** | **True**（平台原样输出 True）|

重标定后门禁明细（按真实 normal_fpr 复算）：

| 门禁 | 值 | 阈值 | 结论 |
|---|---|---|---|
| synthetic_auc | 0.9523958333333333 | 0.85 | 通过 |
| normal_fpr | 0.0 | 0.025732132722552273 | 通过 |
| stability | 0.9882894106657931 | 0.8 | 通过 |

- 平台原样输出 gates_passed = **True**；按真实指标值复算 gates_passed = **True**

## 5. 判据②之三：false_alarm 分数分布下移

> 档 1 只动阈值不动检测器主体（§6.2 硬约束）→ 同一误报样本的**分数本身不变**，下移的是「分数相对阈值」的分布：阈值抬高 Δt 后全部误报样本的分数裕度（score − threshold）整体下移 Δt，且仍能触发报警的误报子集分数更低。

- 阈值位移 Δt = **0.051216**
- 误报类分数裕度中位数：0.010593 → -0.040623（位移 -0.051216）
- 仍能触发报警的误报子集：40 条（中位分 0.580872） → 5 条（中位分 0.634534）
- 正常背景误报：1/200 → 0/200 条
- 分布显著下移：**是**

## 6. 结论

- precision@k 提升：**是**
- 合成基准重跑仍全过门禁：**是**（门禁判定为平台 evaluate_anomaly_gates 原样输出）
- false_alarm 分数分布显著下移：**是**
- 判据②机制验证（mechanism-verification）：**通过**
- 判据②发布就绪：**否**

## 7. 附加产出：误报形态分析报表（§6.2）

```json
{
  "clusters": [
    {
      "cluster": 0,
      "sample_count": 8,
      "dense_features": [
        {
          "feature": "f5",
          "mean_z": -0.3067
        },
        {
          "feature": "f4",
          "mean_z": -0.9056
        },
        {
          "feature": "f2",
          "mean_z": -1.2561
        }
      ]
    },
    {
      "cluster": 1,
      "sample_count": 15,
      "dense_features": [
        {
          "feature": "f2",
          "mean_z": 2.0393
        },
        {
          "feature": "f3",
          "mean_z": 1.9332
        },
        {
          "feature": "f4",
          "mean_z": 1.7377
        }
      ]
    },
    {
      "cluster": 2,
      "sample_count": 9,
      "dense_features": [
        {
          "feature": "f0",
          "mean_z": 1.5804
        },
        {
          "feature": "f1",
          "mean_z": 1.4937
        },
        {
          "feature": "f2",
          "mean_z": 0.667
        }
      ]
    },
    {
      "cluster": 3,
      "sample_count": 8,
      "dense_features": [
        {
          "feature": "f5",
          "mean_z": 2.1776
        },
        {
          "feature": "f4",
          "mean_z": 2.1311
        },
        {
          "feature": "f3",
          "mean_z": 1.7217
        }
      ]
    }
  ],
  "sample_count": 40
}
```
