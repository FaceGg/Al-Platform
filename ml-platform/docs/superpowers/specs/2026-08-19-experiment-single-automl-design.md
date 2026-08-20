# 实验与 AutoML 任务一对一设计

## 目标

- 一个实验最多创建一个 AutoML 任务。
- 占用关系在 AutoML 任务成功、失败、取消或被删除后仍保留。
- 删除实验时删除占用关系；新建实验使用新 ID，可创建新的 AutoML 任务。
- 普通训练任务不占用实验。
- AutoML 建模任务列表以实验为第一列并显示实验名称。

## 数据模型

新增 `experiment_automl_bindings` 表：

- `experiment_id`：主键，外键指向 `experiments.id`，删除实验时级联删除。
- `job_id`：首次使用该实验创建的 AutoML 任务 ID，不设置到 `training_jobs` 的外键，确保任务物理删除后绑定仍保留。
- `created_at`：绑定创建时间。

`experiment_id` 的主键约束作为并发唯一性边界。迁移时为历史 `operator_id = 'automl'` 且仍有关联实验的任务回填绑定；同一实验存在多条历史任务时，按 `created_at`、`id` 排序选择最早任务。

## 后端行为

AutoML 创建接口在审计事务内同时插入 `TrainingJob` 和 `ExperimentAutoMLBinding`。若实验已有绑定，返回 HTTP 409 和稳定错误码 `EXPERIMENT_ALREADY_HAS_AUTOML_JOB`；数据库唯一约束冲突也归一化为同一响应，避免并发绕过。

实验列表和详情返回 `automl_used` 与 `automl_job_id`。AutoML 任务序列化返回 `experiment_name`，任务已因实验删除而失去关联时返回空值。

## 前端行为

- 实验选择器仅展示 `automl_used = false` 的实验。
- 项目切换后自动选中第一个未使用实验；没有可用实验时清空选择。
- 新建实验成功后加入可选列表并自动选中。
- 建模任务列表第一列标题为 `实验`，内容优先显示 `experiment_name`，旧数据缺少该字段时显示 `-`。

## 验证

- 后端 API 回归覆盖唯一占用、任务删除不释放、普通训练不占用、实验状态字段和实验名称序列化。
- 迁移测试覆盖单一 Alembic head 和历史数据回填。
- 前端回归覆盖筛选、默认选择、新建后选择以及任务列表列名和内容。
- 运行聚焦测试、前端构建、Python 编译和差异检查。
