# 产品优化方案（去除大模型能力版本）

> 基于第 9-17 周规划（推理生产化 / 权限审计 / K8s / Notebook / 多集群 / 数据探索标注）
> 范围：传统 MLOps + 云原生基础设施，暂不包含第 18-20 周大模型能力
> 生成时间：2026-07-23

---

## 一、可借鉴功能清单（按周次规划）

### 第一梯队：第 9-12 周（推理 / 权限 / 性能 / 验收）

| # | 借鉴来源 | 功能 | 本产品现状 | 复用比 | 自研量 |
|---|---------|------|-----------|--------|--------|
| 1 | MLflow Tracking | autolog 自动日志 | 已用 MlflowClient，协议兼容 | 85% | ~30 行 |
| 2 | MLflow Model Registry | 模型阶段流转（Staging/Production） | 仅 approval_status，缺 stage | 10% | ~100 行 |
| 3 | Kubeflow Pipelines | 运行级缓存 | dag_executor 无缓存 | 0% | ~170 行 |
| 4 | n8n | 节点错误分支 + 可配置重试 | 有重试无错误分支 | 15% | ~120 行 |
| 5 | n8n | 触发器节点（webhook/event） | 有 schedules 无事件触发 | 15% | ~160 行 |

### 第二梯队：第 13-16 周（K8s / Notebook / 多集群）

| # | 借鉴来源 | 功能 | 本产品现状 | 复用比 | 自研量 |
|---|---------|------|-----------|--------|--------|
| 6 | Kubeflow Pipelines | K8s Job/Pod 提交与状态同步 | 无 K8s 执行器 | 40% | ~400 行 |
| 7 | JupyterHub | 在线 Notebook 开发环境 | 无 Notebook | 50% | ~300 行 |
| 8 | K8s Device Plugin | GPU 调度与资源配额 | 无 GPU 管理 | 70% | ~100 行 |
| 9 | Cube Studio | 多集群路由与资源治理 | 单机 Compose | 20% | ~500 行 |
| 10 | Cube Studio | 算子作业模板（job-template） | 80 算子无行业模板 | 5% | ~350 行 |

### 第三梯队：第 17 周（数据探索与标注）

| # | 借鉴来源 | 功能 | 本产品现状 | 复用比 | 自研量 |
|---|---------|------|-----------|--------|--------|
| 11 | Apache Superset | SQL Lab 数据探索 | 无 SQL 探索 | 60% | ~200 行 |
| 12 | Label Studio | 多模态数据标注 | 有标注基础页面 | 80% | ~100 行 |
| 13 | Apache Superset | 数据质量报告 | 无 | 40% | ~250 行 |

### 横向增强（贯穿各周）

| # | 借鉴来源 | 功能 | 本产品现状 | 复用比 | 自研量 |
|---|---------|------|-----------|--------|--------|
| 14 | Flyte | 类型化端口强校验 | PortSpec 有 type 不强制 | 30% | ~120 行 |
| 15 | Flyte | 动态工作流（运行时生成 DAG） | 静态 DAG | 5% | ~300 行 |
| 16 | Kubeflow SDK | 工作流代码定义（画布↔代码） | 仅画布定义 | 0% | ~400 行 |
| 17 | MLflow Projects | 可复现训练环境打包 | 无环境打包 | 35% | ~200 行 |

---

## 二、复用比例汇总

| 复用性质 | 功能数 | 综合复用比 | 说明 |
|---------|--------|-----------|------|
| SDK 直接复用 | 2 项 | 70-85% | autolog、GPU 调度（K8s 原生） |
| 独立组件集成 | 3 项 | 50-80% | JupyterHub、Label Studio、Superset |
| 协议/结构借鉴 | 5 项 | 10-40% | 模型阶段、K8s Job、SQL Lab、类型校验、环境打包 |
| 完全自研 | 7 项 | 0-20% | 缓存、触发器、多集群、模板、动态 DAG、代码生成、错误分支 |

**综合复用比：约 35% 可直接复用，65% 需自行开发**

> 相比含大模型方案（30%/70%），去除 LLM 后复用比略升，因为 K8s 生态和 Label Studio/Superset 等独立组件成熟度高、可独立集成。

---

## 三、重点功能复用详解

### 1. autolog 自动日志 — 复用 85%（最高 ROI）

```
现状：training_execution.py 已用 MlflowClient，experiment_tracking.py 已封装接口
```

| 部分 | 来源 | 工作量 |
|------|------|--------|
| mlflow.sklearn.autolog() | MLflow SDK 直接调用 | 1 行 |
| mlflow.xgboost.autolog() | MLflow SDK 直接调用 | 1 行 |
| mlflow.pytorch.autolog() | MLflow SDK 直接调用 | 1 行 |
| 注入集成 + 去重 | 自研 | ~30 行 |

**结论**：协议层已兼容，1 天可完成。

### 2. GPU 调度 — 复用 70%

```
现状：无 GPU 管理，第 15 周规划
```

| 部分 | 来源 | 工作量 |
|------|------|--------|
| K8s GPU Device Plugin | K8s 官方组件直接部署 | 0 行代码 |
| GPU 资源声明（limits: nvidia.com/gpu） | K8s 原生 | Pod spec 字段 |
| GPU 监控（DCGM exporter） | NVIDIA 官方 | 部署即可 |
| 本产品算子配置 GPU 参数 | 自研 | ~60 行 |
| GPU 规格展示 UI | 自研 | ~40 行 |

**结论**：K8s GPU 生态成熟，主要工作是 UI 适配，3 天可完成。

### 3. Label Studio 标注 — 复用 80%

```
现状：有 AnnotationPage.tsx 基础页面，但无成熟标注引擎
```

| 部分 | 来源 | 工作量 |
|------|------|--------|
| 标注引擎（图像/视频/文本/音频） | Label Studio 独立部署 | Docker compose |
| 标注任务管理 API | Label Studio 原生 | 调用其 API |
| 前端嵌入 | Label Studio iframe | ~30 行 |
| 与本产品数据集打通 | 自研适配 | ~50 行 |
| 标注结果回流训练数据 | 自研 | ~50 行 |

**结论**：Label Studio 可独立服务直接集成，无需重写标注引擎，2-3 天完成对接。

### 4. K8s Job 提交 — 复用 40%

```
现状：无 K8s 执行器，第 14 周规划
```

| 部分 | 来源 | 工作量 |
|------|------|--------|
| K8s Python SDK（client-python） | 官方 SDK | 直接调用 |
| Job/Pod manifest 生成 | 借鉴 KFP，自研 | ~150 行 |
| 状态同步（watch 机制） | 借鉴 KFP，自研 | ~100 行 |
| 日志流式获取 | 自研 | ~80 行 |
| 超时/取消/垃圾回收 | 自研 | ~70 行 |

**结论**：K8s SDK 原生可用，但执行器逻辑需自研，约 400 行，5-7 天。

### 5. 运行级缓存 — 复用 0%，全自研

```
现状：dag_executor.py 无 cache/hash 逻辑
```

| 部分 | 来源 | 工作量 |
|------|------|--------|
| 输入哈希算法 | 自研 | ~30 行 |
| 缓存存储（文件/Redis） | 自研 | ~50 行 |
| 命中跳过执行 | 自研 | ~40 行 |
| 失效策略 + 清除 API | 自研 | ~50 行 |

**结论**：KFP 缓存强绑 Argo 无法搬运，但本产品 DAG 结构清晰，自研约 170 行，3-4 天。

---

## 四、落地优先级（按 复用比 × 价值 排序）

| 优先级 | 功能 | 周次 | 复用比 | 自研量 | 周期 |
|--------|------|------|--------|--------|------|
| P0 | autolog 自动日志 | 第 9 周 | 85% | ~30 行 | 1 天 |
| P0 | 模型阶段流转 | 第 9 周 | 10% | ~100 行 | 2 天 |
| P0 | Label Studio 标注 | 第 17 周 | 80% | ~130 行 | 3 天 |
| P1 | GPU 调度 | 第 15 周 | 70% | ~100 行 | 3 天 |
| P1 | 运行级缓存 | 第 11 周 | 0% | ~170 行 | 4 天 |
| P1 | 触发器节点 | 第 10 周 | 15% | ~160 行 | 3 天 |
| P2 | Superset SQL Lab | 第 17 周 | 60% | ~200 行 | 4 天 |
| P2 | K8s Job 提交 | 第 14 周 | 40% | ~400 行 | 6 天 |
| P2 | JupyterHub Notebook | 第 15 周 | 50% | ~300 行 | 5 天 |
| P3 | 算子作业模板 | 第 13 周 | 5% | ~350 行 | 5 天 |
| P3 | 类型化端口校验 | 第 11 周 | 30% | ~120 行 | 3 天 |
| P3 | 多集群路由 | 第 16 周 | 20% | ~500 行 | 7 天 |
| P4 | 动态工作流 | 第 14 周 | 5% | ~300 行 | 5 天 |
| P4 | 工作流代码生成 | 第 15 周 | 0% | ~400 行 | 6 天 |
| P4 | 训练环境打包 | 第 12 周 | 35% | ~200 行 | 4 天 |

---

## 五、核心结论

### 1. 复用结构变化
去除大模型后，复用来源从"Dify/LangFlow（LLM）"转向"K8s 生态 + 独立组件（Label Studio/Superset/JupyterHub）"，复用比略升至 35%。

### 2. 三类高复用功能优先做
- **autolog**（85%）— 第 9 周，1 天，零成本接入 MLflow 生态
- **Label Studio**（80%）— 第 17 周，3 天，标注能力一步到位
- **GPU 调度**（70%）— 第 15 周，3 天，K8s 原生支持

### 3. 完全自研但 ROI 高的
- **运行级缓存**（0% 复用，170 行）— 实验场景省 50% 算力，第 11 周必做
- **K8s Job 执行器**（40% 复用，400 行）— 第 14 周核心，K8s SDK 可用但执行逻辑自研

### 4. 建议跳过或延后的
- **动态工作流、工作流代码生成** — 复用 0-5%，自研 300-400 行，且非当前刚需，可延后
- **多集群路由** — 复用 20%，自研 500 行，单产线场景单集群足够，第 16 周再评估必要性

### 5. 总体工作量
保留的 15 项功能，总自研代码约 3200 行，按 2 人团队估算约 6-8 周可全部完成，与本产品第 9-17 周规划节奏吻合。

---

## 六、竞品参考来源

| 竞品 | 仓库 | 主要借鉴点 |
|------|------|-----------|
| MLflow | https://github.com/mlflow/mlflow | autolog、Model Registry 阶段流转、Projects 环境打包 |
| Kubeflow Pipelines | https://github.com/kubeflow/pipelines | K8s Job 提交、运行级缓存、SDK 代码定义 |
| Flyte | https://github.com/flyteorg/flyte | 类型化端口校验、动态工作流 |
| n8n | https://github.com/n8n-io/n8n | 错误分支、触发器节点 |
| Cube Studio | https://github.com/data-infra/cube-studio | 多集群路由、算子作业模板 |
| JupyterHub | https://github.com/jupyterhub/jupyterhub | 在线 Notebook |
| Label Studio | https://github.com/HumanSignalAI/label-studio | 多模态数据标注 |
| Apache Superset | https://github.com/apache/superset | SQL Lab 数据探索、数据质量报告 |
