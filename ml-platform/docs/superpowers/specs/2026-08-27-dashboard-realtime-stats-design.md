# 工作台实时模型统计设计

## 目标

工作台的模型总数、API 总数及模型状态必须来自当前业务实体，并在 AutoML、普通训练、模型发布和 API 资源发生变化后及时刷新。

## 统计口径

- `训练中`：当前用户可访问项目内，状态为 `pending`、`queued`、`running` 或 `cancel_requested` 的训练任务。
- `已发布`：当前用户可访问项目内，训练产出的模型已经关联到 `observed_state = running` 的推理部署。一个训练任务只计一次。
- `已完成`：状态为 `completed`，但不属于上述已发布集合的训练任务。
- `模型总数`：训练中、已完成、已发布三类互斥数量之和；失败和取消任务不计入模型资产。
- `API 总数`：当前用户可访问的 `PlatformAPI` 数量。

发布关系按两条现有来源链路识别：

1. `TrainingJob.model_library_id -> ModelVersion.source_model_library_id -> InferenceDeployment`。
2. `TrainingJob.model_artifact_id -> ModelVersion.source_artifact_id -> InferenceDeployment`。

## 实时同步

- 工作台保留 15 秒轮询，覆盖 worker 异步更新训练和部署状态的场景。
- 工作台监听同页事件、跨标签页 storage 事件、窗口 focus 和页面重新可见事件并立即刷新。
- AutoML、普通训练、模型注册/部署、Platform API 的成功新增、删除和状态操作发送统一统计变更事件。
- 后端 API 始终重新查询数据库，前端事件只负责触发刷新，不缓存或自行推算统计值。

## 删除确认框

公共 `DeleteConfirmation` 的弹层宽度统一为 280px，并设置 `max-width: calc(100vw - 32px)`，保证桌面端不过宽且移动端不溢出。

## 验证

- 后端集成测试覆盖三类互斥统计、发布关联、权限隔离以及删除后重新请求统计变化。
- 前端测试覆盖 mutation 后事件通知、focus/visibility 刷新和确认弹层宽度。
- 运行前端生产构建与 `git diff --check`。
