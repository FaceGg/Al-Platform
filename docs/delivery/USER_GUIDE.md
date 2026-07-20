# 用户操作手册

## 基本概念

- **项目**：隔离数据、工作流、训练任务和模型的业务空间。
- **数据集制品（Dataset Artifact）**：平台管理的数据文件记录，包含不可变 ID、项目归属、存储位置、哈希、Schema 和行数。界面使用制品 ID，不要求用户填写服务器路径。
- **工作流**：由算子节点和有向连线组成的可执行 DAG。
- **运行记录**：保存工作流状态、节点每次尝试、耗时、错误和结果。

## 登录和项目

1. 打开 `http://127.0.0.1:5173`。
2. 本地首次验证可使用 `admin / admin123`。
3. 进入“项目管理”，创建项目并填写名称和描述。

## 上传焊接数据

1. 进入“数据管理”。
2. 选择项目。
3. 上传准备后的 `weld_fault_features.csv`。
4. 上传成功后平台生成数据集制品，并记录 43 列 Schema、行数和 SHA-256。

原始 `current.csv`、`voltage.csv`、`force.csv`、`labels.csv` 不能直接作为四模板输入，应先按演示指南生成特征表。

## 四套工业模板

| 模板 | 用途 | 主要输出 |
|---|---|---|
| 焊接质量预测 `weld_quality` | 以 `Fault` 为目标训练平衡随机森林分类器 | 分类指标、分类别指标、图表 |
| 故障风险参数分析 `fault_parameter_analysis` | 分类故障并识别关键电流、电压、压力特征 | 分类指标、特征重要性 |
| 焊接异常检测 `anomaly_detection` | 无监督标记异常焊点并与 `Fault` 对照 | 异常数据、统计、故障命中指标 |
| 全流程多模型对比 `full_ml_comparison` | 对比随机森林与 XGBoost 的故障分类表现 | 两组指标、模型对比结果 |

## 使用模板

1. 在项目详情点击“使用模板”，或打开 `/template/<模板ID>?project=<项目ID>`。
2. 确认场景、目标列 `Fault` 和必需列。
3. 选择项目内的数据集制品。
4. 调整模板公开的语义参数，例如树数量或异常比例。
5. 点击“创建工作流”，进入工作区。
6. 点击“运行”。每次运行会先清空旧进度，再显示各节点状态。

## 查看结果和错误

- 进度区显示完成节点数和 `running/completed/failed/cancelled` 终态。
- 点击节点可查看状态和结果预览。
- `GET /api/runs/{run_id}` 返回节点尝试、耗时、结构化错误和结果。
- 失败时先记录错误码、失败节点和 attempt，再检查后端运行日志。

## 使用限制

- 本地模式默认使用进程内线程；生产模式使用 PostgreSQL、Celery/Redis 和 MinIO，支持持久投递、硬超时、取消与失联恢复。节点级断点续跑和周期性恢复调度仍未实现。
- 本地模式默认使用 SQLite 和本地文件；多实例部署必须按生产基础设施文档切换到 PostgreSQL 和 MinIO。
- `execute_python` 和表达式算子只应运行可信输入。

## 注册模型与在线推理

1. 进入“模型库”，选择项目。项目名称旁显示当前 owner/editor/operator/viewer 角色。
2. owner/editor 创建逻辑注册模型，点击“注册版本”。平台来源填写已完成训练模型 ID；ONNX 来源选择文件并填写 feature/output Schema JSON。
3. 在“版本”中检查 framework、状态和版本号；owner/editor 批准 pending 版本，拒绝时必须填写意见。
4. 切换“推理部署”，选择 approved 版本创建部署。owner/editor/operator 可启动或停止。
5. 运行中点击“在线测试”。页面按冻结 Schema 生成 records 模板，也可直接粘贴 1-100 条 JSON records。
6. 查看 predictions、probabilities、精确版本和毫秒耗时。停止后不可继续推理。

viewer 只能查看。operator 不能注册或审批，但可启停和推理。records 必须字段完全匹配且数值有限；单请求最大 1 MiB。详细错误码和生产配置见 `MODEL_REGISTRY_INFERENCE.md`。
