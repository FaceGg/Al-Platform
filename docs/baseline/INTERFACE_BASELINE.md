# 接口基线

> 冻结日期：2026-07-12。本文记录现有可依赖契约；冲突项在修复前不得扩散为新调用方式。

## 工作流运行状态

| 对象 | 状态 | 说明 |
|---|---|---|
| WorkflowRun | `pending` | 已创建，尚未开始 |
| WorkflowRun | `running` | 执行器已开始 |
| WorkflowRun | `cancel_requested` | 已请求协作式取消，等待节点边界 |
| WorkflowRun | `completed` | 全部可执行节点完成 |
| WorkflowRun | `failed` | 校验或节点执行失败 |
| WorkflowRun | `cancelled` | 协作式取消完成 |
| NodeRun/前端节点 | `pending` | 尚未执行 |
| NodeRun/前端节点 | `running` | 节点执行中 |
| NodeRun/前端节点 | `completed` | 节点完成并保存输出 |
| NodeRun/前端节点 | `failed` | 节点校验或执行失败 |
| NodeRun/前端节点 | `timed_out` | 当前尝试超过节点超时 |
| NodeRun/前端节点 | `cancelled` | 节点因运行取消而结束 |
| NodeRun/前端节点 | `skipped` | 条件分支未选中或上游跳过 |

工作流终态为 `completed`、`failed`、`cancelled`。节点每次重试创建独立 attempt，不增加 `retrying` 状态；重试由下一条 `running` attempt 表达。

## API 错误契约

- FastAPI 标准错误响应：HTTP 4xx/5xx，JSON 为 `{ "detail": <string|object> }`。
- 资源不存在统一使用 404；参数/业务校验当前主要使用 400；认证失败使用 401；权限不足使用 403。
- 工作流异步失败写入 `WorkflowRun.error_message`，WebSocket 完成事件携带 `status: "failed"` 与 `error`。
- 工作流运行已提供 `WORKFLOW_EMPTY`、`WORKFLOW_INVALID`、`NODE_EXECUTION_FAILED` 和 `NODE_TIMED_OUT` 稳定错误码；其他 API 尚未统一。

后续目标结构仍为 `{ "code": "STABLE_CODE", "message": "localized message", "details": {}, "trace_id": "..." }`；本周仅冻结工作流主链路。

## 工作流版本

- 当前工作流为可编辑草稿。
- `POST /api/workflows/{id}/publish` 创建单调递增、不可变快照。
- 版本列表和详情分别由 `/versions` 与 `/versions/{version}` 提供。
- 恢复版本只覆盖当前草稿，不删除历史，也不自动发布。
- 运行保存草稿快照；草稿与已发布快照一致时记录 `workflow_version`。

## 算子契约

- 基类：`BaseOperator`。
- 元数据：`id`、`name`、`category`、`description`、`version`、`inputs`、`outputs`、`parameters`。
- 校验：`validate(inputs: dict) -> bool`。
- 执行：`execute(inputs: dict, params: dict) -> dict`，返回键必须对应输出端口名。
- 预览：`get_preview(outputs: dict) -> dict`，当前为可选覆盖。
- 端口：`PortSpec(name, type, label)`；参数：`ParamSpec(name, type, default, label, options, range_min, range_max)`。

算子注册必须通过显式模块导入触发 `@register_operator`。导入顺序仍是隐含依赖，Week 3 前不得新增第二套注册路径。

## DataBus 契约

| 输入类型 | 存储格式 | 加载结果 |
|---|---|---|
| `bytes` | `.bin` | `bytes` |
| `DataFrame` | `.jsonl` | `DataFrame` |
| 非空 `list[dict]` | `.jsonl` | `DataFrame` |
| 列表值组成的非空 `dict` | `.jsonl` | `DataFrame` |
| 其他 JSON 值、空列表、空字典 | `.json` | 原 JSON 值 |

DataBus 返回的是文件路径，执行器在下游节点加载。默认路径位于项目根目录 `temp_test/data`，可通过 `ML_PLATFORM_TEMP_DIR` 覆盖；该路径不是跨机器制品 URI。

## 执行器与 WebSocket 事件

- 回调签名：`status_callback(run_id, node_id, status, result=None, metadata=None)`；四参数回调继续兼容。
- 节点事件：`{ type: "node_status", run_id, node_id, status, attempt, result? }`。
- 工作流结束：`{ type: "run_completed", run_id, status, result? | error? }`。
- 工作流级开始事件暂借用 `node_id: "__wf__"`，属于兼容行为，不应在新模块复制。
- POST `/api/workflows/{workflow_id}/run` 返回 201 与 `{ run_id, status: "pending" }`。
- POST `/api/runs/{run_id}/cancel` 幂等请求协作式取消。
- GET `/api/runs/{run_id}` 返回节点尝试历史、结构化错误和有限日志。

## 前后端边界

- REST 客户端基地址为 `/api`，默认 JSON 内容类型，Token 使用 `Authorization: Bearer <token>`。
- WebSocket 路径为 `/ws/runs/{run_id}`。
- 前端每次运行前通过 `resetExecution()` 清空节点状态、结果和进度。
- ReactFlow 节点与边由 Zustand store 作为单一状态源；连线删除必须调用 `removeEdge`/`applyEdgeChanges`。

## 2026-07-13 Week 3 接口更正（覆盖旧算子契约）

- 运行时注册算子数量为 79；以 `OperatorRegistry.list_all()` 的自动化检查为准。
- 唯一执行签名为 `execute(context: OperatorContext, inputs: dict, params: dict) -> OperatorResult`，不提供旧协议运行时兼容。
- 执行器在调用前校验算子参数，并将 `timeout_seconds`、`max_retries`、`retry_delay_seconds` 作为执行策略字段分离。
- `OperatorResult` 包含 `outputs`、`metrics`、`artifacts`、`logs`；输出端口和指标有限性必须通过契约校验。
- 新训练请求 `POST /api/training/run` 必须提供 `dataset_artifact_id`；`dataset_path` 仅用于读取历史任务。
- 训练任务详情返回数据/模型制品 ID、模型库 ID、Schema、预处理、指标、日志和结构化错误。

## 2026-07-14 Week 4 接口补充

- 完整应用运行时注册算子为 80 个，新增 `anomaly_eval`；注册表统计必须先导入完整应用。
- 四个工业模板 ID：`weld_quality`、`fault_parameter_analysis`、`anomaly_detection`、`full_ml_comparison`。
- 工业模板实例化请求为 JSON：`project_id`、`dataset_artifact_id`、`parameters`；不接受服务器文件路径。
- `GET /api/projects/{project_id}/datasets` 返回当前用户项目内 dataset Artifact 列表，不暴露 `storage_path`。
- `GET /api/runs/{run_id}` 的节点记录包含 `result`，与 WebSocket 节点结果契约一致。
- SQLite 时间差计算将无时区值按 UTC 解释，避免节点终态持久化回滚。
- 执行进度容器提供 `data-testid="execution-progress"` 和稳定 `data-status`，仅用于无可访问状态角色的浏览器验收。
