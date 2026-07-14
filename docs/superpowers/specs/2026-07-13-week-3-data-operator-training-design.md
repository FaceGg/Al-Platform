# 第三周数据、算子与训练闭环设计

## 1. 目标

第三周交付稳定的数据训练闭环：数据上传形成可追踪制品，训练通过制品 ID 获取数据，训练完成后保存模型及元数据并自动登记模型库。同时一次性升级全部注册算子到统一强类型执行协议，消除裸字典返回、路径直传和算子间协议漂移。

## 2. 已确认决策

- 训练正式输入使用 `dataset_artifact_id`，不再以文件路径作为长期公共契约。
- 旧 `dataset_path` 仅在迁移期兼容，并通过响应或日志标记弃用。
- 训练成功后自动创建模型制品并登记模型库。
- 76 个现有算子在同一版本全部迁移到新签名，不保留运行时双协议。
- 迁移按算子分类分批实施和验证，但最终版本只允许新协议。
- 新签名固定为 `execute(context, inputs, params) -> OperatorResult`。

## 3. 模块边界

### 3.1 operator_contract

负责定义并校验：

- `OperatorContext`。
- `OperatorResult`。
- `ArtifactDraft`。
- 参数类型、选项和范围。
- 输入、输出端口名称和类型。
- 输出可序列化性及制品声明。

算子只处理领域逻辑，不自行操作 ORM、拼接全局目录或写入运行状态。

### 3.2 ArtifactService

负责：

- 按项目和用户权限解析制品。
- 创建数据集、模型、预处理器、指标等制品。
- 计算文件大小、摘要和格式。
- 保存数据 Schema、行数、来源和业务元数据。
- 提供受控本地路径给当前执行阶段。

服务接口后续可替换本地文件系统为 MinIO，而调用方继续使用制品 ID。

### 3.3 TrainingService

负责：

- 解析 `dataset_artifact_id`。
- 验证目标列、任务类型和特征集合。
- 执行数据清理、拆分、训练和评估。
- 保存模型、预处理和特征 Schema。
- 创建模型制品。
- 自动创建模型库记录。
- 更新 TrainingJob 的状态、指标和关联 ID。

API 只负责认证、请求校验、创建任务和查询结果。

### 3.4 DAGExecutor

负责为每个节点创建 OperatorContext，调用新算子签名，校验 OperatorResult，将普通输出交给 DataBus，将制品草稿交给 ArtifactService，并把 metrics/logs 写入节点尝试记录。

## 4. 算子协议

```python
@dataclass(frozen=True)
class OperatorContext:
    run_id: str
    node_id: str
    project_id: str | None
    artifact_service: ArtifactService
    cancel_requested: Callable[[], bool]
    logger: OperatorLogger

@dataclass(frozen=True)
class ArtifactDraft:
    name: str
    type: str
    data: bytes | str | Path
    format: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class OperatorResult:
    outputs: dict[str, Any]
    metrics: dict[str, float] = field(default_factory=dict)
    artifacts: list[ArtifactDraft] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
```

所有 BaseOperator 子类必须实现：

```python
def execute(
    self,
    context: OperatorContext,
    inputs: dict[str, Any],
    params: dict[str, Any],
) -> OperatorResult:
    ...
```

不再接受旧 `execute(inputs, params)`，不再允许直接返回裸字典。

## 5. 协议校验

### 5.1 执行前

- 必需输入端口必须存在。
- 不允许未知输入端口，控制流明确声明的动态端口除外。
- 参数按 ParamSpec 校验 `str`、`int`、`float`、`boolean`、`select`。
- select 参数必须在 options 中。
- 数值参数必须满足 range_min/range_max。
- 算子自定义 validate 只处理跨字段和领域规则。

### 5.2 执行后

- 返回值必须是 OperatorResult。
- outputs 键必须匹配声明输出端口。
- 必需输出不得缺失。
- metrics 值必须为有限数字。
- artifacts 必须包含合法类型、名称和可读取数据源。
- 普通输出必须可由 DataBus 处理。

协议错误使用稳定错误码：`OPERATOR_INPUT_INVALID`、`OPERATOR_PARAM_INVALID`、`OPERATOR_RESULT_INVALID`、`OPERATOR_ARTIFACT_INVALID`。

## 6. 数据制品

上传成功后创建 `Artifact(type="dataset")`，至少记录：

- 项目 ID、名称、格式、文件大小和本地受控存储位置。
- SHA-256 摘要。
- 行数、列数。
- 列名、推断类型、空值数。
- 创建时间和来源类型 `upload`。

原始数据集制品不可覆盖。重新上传产生新的制品 ID。数据加工算子可在 OperatorResult.artifacts 中声明派生数据制品，并记录父制品 ID 和运行节点。

## 7. 训练任务模型

TrainingJob 新增：

- `dataset_artifact_id`：必需的正式数据输入。
- `model_artifact_id`：训练成功后的模型制品。
- `model_library_id`：自动登记的模型库记录。
- `feature_schema`：训练使用的特征、类型和顺序。
- `target_schema`：目标列和任务类型。
- `preprocessing`：缺失值、编码和缩放信息。
- `error_code`、`error_details` 和结构化日志。

旧 `dataset_path` 与 `model_path` 暂时保留用于数据库兼容和排障，不作为新增 API 的首选字段。

## 8. 训练闭环

1. API 校验项目与 dataset artifact 所有权。
2. 创建 pending TrainingJob，保存 dataset_artifact_id。
3. TrainingService 加载数据并生成 Schema。
4. 验证目标列、有效特征、样本量和任务类型。
5. 拆分训练/验证数据，训练模型并计算指标。
6. 将模型、预处理信息和 Schema 写入模型制品。
7. 创建 ModelLibrary 记录，关联训练任务、数据制品和指标。
8. 更新 TrainingJob 为 completed，并写入两个关联 ID。

任一步骤失败时，任务进入 failed，写入稳定错误码、详情和日志；不得创建可用模型库记录。若文件已写入但数据库事务失败，需清理孤立文件。

## 9. 模型制品元数据

模型制品至少记录：

- `training_job_id`。
- `dataset_artifact_id`。
- `operator_id` 或算法名称。
- `feature_schema` 和 `target_schema`。
- `preprocessing`。
- `metrics`。
- Python、scikit-learn 和模型库版本。
- 文件 SHA-256 和大小。

模型加载必须由可信项目制品 ID 发起，不能接受任意用户文件路径。

## 10. 算子迁移批次

迁移顺序：

1. IO 和 utility。
2. processing 和 blending。
3. ML、DL 和 optimization。
4. evaluation 和 visualization。
5. control 和 mechanism models。

每批必须完成签名检查、分类测试和最小执行测试后才进入下一批。全部迁移后删除旧调用路径，并运行注册表全量检查。

## 11. API 与前端

训练创建请求使用：

```json
{
  "project_id": "...",
  "dataset_artifact_id": "...",
  "target_column": "quality",
  "operator_id": "random_forest_train",
  "params": {}
}
```

训练详情返回数据制品摘要、feature/target schema、指标、模型制品和模型库 ID。前端训练页从项目数据制品列表选择数据集，不允许输入服务器文件路径；完成任务提供模型制品和模型库入口。

## 12. 测试策略

- OperatorContext、OperatorResult 和 ArtifactDraft 单元测试。
- 参数、输入、输出、metrics 和 artifacts 协议错误测试。
- 76 个注册算子签名与声明全量检查。
- 各算子分类最小执行回归。
- 数据上传创建制品、Schema、摘要和权限测试。
- dataset_artifact_id 不存在、跨项目和错误类型测试。
- 训练成功闭环：任务、指标、模型制品和模型库记录。
- 训练失败无可用模型记录及孤立文件清理测试。
- DAG 新协议下的数据传递、日志、指标、取消、超时和重试测试。
- 前端数据制品选择、训练详情和 API 适配层测试。
- 后端标准 runner、前端 Vitest 和生产构建全量验证。

## 13. 非目标

- 不引入 MinIO、PostgreSQL、Redis 或 Celery。
- 不实现实验追踪、超参数 Trial、TensorBoard 或检查点恢复。
- 不实现模型审批和在线部署。
- 不允许任意本地路径成为新的公共训练协议。
- 不保留运行时旧算子签名兼容层。

## 14. 验收标准

- 所有注册算子使用新签名并返回 OperatorResult。
- DAGExecutor 不再调用旧签名。
- 数据上传形成可追踪 dataset artifact。
- 训练 API 正式使用 dataset_artifact_id。
- 训练成功自动形成模型制品和模型库记录。
- 训练失败提供稳定错误且不产生可用模型记录。
- 一条焊接数据训练主链路可重复执行。
- 后端全量测试、前端测试和生产构建通过。
- 开发计划、问题记录、接口基线和共享经验完成更新。
