# 第二周工作流可靠性设计

## 1. 目标

在不提前引入 Celery、Redis 或独立执行进程的前提下，为现有线程执行架构补齐可交付的工作流主链路：发布快照版本、运行前校验、协作式取消、节点超时、节点重试、结构化日志与错误详情，以及前端画布和进度状态同步。

本设计保持 API、状态机和执行控制边界稳定，使第 5 周可以把后台线程替换为持久任务队列，而无需重写前端调用协议和核心状态语义。

## 2. 已确认决策

- 取消采用协作式语义，不强制终止正在运行的 Python 算子。
- 工作流采用“可编辑草稿 + 不可变发布快照 + 恢复为草稿”。
- 节点可靠性采用平台默认值并允许节点覆盖。
- 默认 `timeout_seconds=300`、`max_retries=0`、`retry_delay_seconds=0`。
- 本周保留后台线程，只增加可替换的执行适配边界。

## 3. 架构边界

### 3.1 WorkflowVersion

新增不可变工作流版本模型，保存：

- 工作流 ID。
- 单调递增版本号。
- 发布时工作流名称和描述。
- 节点快照 JSON。
- 连线快照 JSON。
- 发布者和发布时间。

发布只读取当前草稿并创建新快照。历史版本不允许修改。恢复操作将指定版本内容覆盖到当前草稿，并保留全部历史版本；恢复本身不自动发布。

### 3.2 RunControl

新增与数据库无关的运行控制对象，向执行器提供：

- `is_cancel_requested()`：检查运行是否收到取消请求。
- 平台默认可靠性参数。
- 节点级参数解析与边界校验。
- 可中断的重试等待。

`DAGExecutor` 只依赖该控制接口，不直接查询 ORM 或 FastAPI 状态。

### 3.3 RunService

新增运行服务负责：

- 创建运行及运行快照。
- 执行前完整校验。
- 工作流与节点状态转换。
- 每次节点尝试记录。
- 结构化日志和错误信息。
- WebSocket 事件发布。
- 协调 `DAGExecutor` 与运行控制对象。

API 层只负责认证、参数解析、调用服务和返回响应。现有后台线程作为适配器调用运行服务，后续可替换为 Celery task。

## 4. 数据模型

### 4.1 WorkflowVersion

- `id: UUID`
- `workflow_id: UUID`
- `version: int`
- `name: str`
- `description: str`
- `nodes_snapshot: JSON`
- `edges_snapshot: JSON`
- `published_by: UUID | null`
- `published_at: datetime`

`(workflow_id, version)` 建立唯一约束。

### 4.2 WorkflowRun 扩展

- `status` 使用冻结状态值。
- `cancel_requested_at: datetime | null`
- `cancelled_at: datetime | null`
- `workflow_version: int | null`
- `workflow_snapshot: JSON`，确保运行不受后续草稿编辑影响。
- `error_code: str | null`
- `error_details: JSON | null`
- `logs: JSON`，本周保存结构化有限日志；生产日志系统留待后续阶段。

### 4.3 NodeRun 扩展

- `attempt: int`，从 1 开始。
- `status` 使用节点尝试状态。
- `error_code: str | null`
- `error_details: JSON | null`
- `duration_ms: int | null`
- `logs: JSON`

同一节点每次重试创建新的 NodeRun，不覆盖前一次失败。

## 5. 状态机

### 5.1 工作流运行

```text
pending -> running
pending -> cancel_requested -> cancelled
running -> completed
running -> failed
running -> cancel_requested -> cancelled
```

终态为 `completed`、`failed`、`cancelled`。终态不可再次变更。取消终态不是失败，不写通用执行失败错误。

### 5.2 节点尝试

```text
pending -> running -> completed
pending -> cancelled
pending -> skipped
running -> failed
running -> timed_out
running -> cancelled
```

当一次尝试为 `failed` 或 `timed_out` 且仍有重试额度时，等待 `retry_delay_seconds` 后创建下一次尝试。取消检查发生在节点开始前、重试等待期间和节点返回后。

## 6. 超时语义

节点执行放入受控工作线程，调用方最多等待 `timeout_seconds`。达到上限后：

1. 当前尝试标记为 `timed_out`。
2. 若有重试额度，按策略进入下一次尝试。
3. 无重试额度时，运行标记为 `failed`，停止调度后续节点。
4. 原 Python 调用无法被线程安全强制终止，可能继续自然运行；其迟到结果不得写入 DataBus 或覆盖终态。

该限制必须记录在运行日志和技术债中。需要真正强制终止时，在第 5 周改为独立任务进程或 Celery worker hard/soft time limit。

## 7. 校验与错误

运行创建前执行：

- 工作流存在且当前用户可访问。
- 至少存在一个节点。
- 节点 ID、算子 ID 和连线端点有效。
- 非控制流环路被拒绝。
- 必需输入端口连接完整。
- 节点可靠性参数为非负数并在平台上限内。

错误响应继续兼容 FastAPI `{detail: ...}`，同时运行详情提供稳定字段：

```json
{
  "error_code": "NODE_TIMED_OUT",
  "error_message": "Node execution exceeded timeout",
  "error_details": {
    "node_id": "...",
    "attempt": 1,
    "timeout_seconds": 300
  }
}
```

本周稳定错误码至少包括：`WORKFLOW_EMPTY`、`WORKFLOW_INVALID`、`RUN_CANCELLED`、`NODE_VALIDATION_FAILED`、`NODE_EXECUTION_FAILED`、`NODE_TIMED_OUT`。

## 8. API

- `POST /api/workflows/{workflow_id}/publish`
  - 创建下一不可变版本，返回版本摘要。
- `GET /api/workflows/{workflow_id}/versions`
  - 按版本倒序返回摘要。
- `GET /api/workflows/{workflow_id}/versions/{version}`
  - 返回完整快照。
- `POST /api/workflows/{workflow_id}/versions/{version}/restore`
  - 将快照恢复为当前草稿。
- `POST /api/workflows/{workflow_id}/run`
  - 运行当前草稿快照；若草稿等于已发布版本则记录该版本号，否则版本号为空。
- `POST /api/runs/{run_id}/cancel`
  - 非终态运行转为 `cancel_requested`；重复调用幂等。
- `GET /api/runs/{run_id}`
  - 返回运行、节点尝试、错误详情和日志摘要。

## 9. WebSocket 事件

保持现有路径 `/ws/runs/{run_id}`，事件统一为：

- `run_status`：运行状态变化。
- `node_status`：节点尝试状态变化，携带 `attempt`。
- `run_log`：结构化日志条目。
- `run_completed`：兼容现有前端的终态事件。

WebSocket 只用于实时体验，不作为状态事实来源。断线或晚连接后，前端必须调用运行详情接口恢复最终状态。

## 10. 前端设计

- 运行按钮每次启动前调用 `resetExecution()`。
- 停止按钮调用取消 API，不再仅关闭 WebSocket和本地重置状态。
- Store 支持工作流状态和节点状态：`skipped`、`timed_out`、`cancel_requested`、`cancelled`。
- 进度条将 `completed`、`failed`、`timed_out`、`cancelled`、`skipped` 计为已结束节点，但分别显示语义和颜色。
- 工作区增加发布按钮、版本历史抽屉、版本详情与恢复确认。
- 错误详情展示稳定错误码、消息、节点、尝试次数和日志摘要。
- WebSocket 关闭后查询运行详情，不直接把运行判定为失败或重置为待运行。

## 11. 测试策略

严格执行红绿重构：

- 模型和版本 API：发布递增、快照不可变、恢复草稿、版本不存在。
- 状态机：合法转换、终态保护、重复取消幂等。
- 执行控制：节点覆盖默认值、失败重试、超时、重试等待期间取消、迟到结果不落盘。
- 运行 API：空工作流在创建执行线程前拒绝、无效 DAG 返回结构化错误、详情返回尝试历史。
- 前端 Store：每次运行重置、完整状态集合、断线恢复。
- 前端组件：进度状态与取消按钮行为。
- 全量验证：后端标准套件、前端 Vitest、TypeScript/Vite 构建。
- 浏览器 E2E：若现有环境具备 Playwright，则验证发布、运行、取消、失败详情和恢复；依赖不可用时记录受阻原因与手工步骤，不伪报通过。

## 12. 非目标

- 不引入 Redis、Celery、PostgreSQL 或分布式锁。
- 不实现强制杀死正在运行的 Python 线程。
- 不实现断点续跑、暂停后恢复或跨服务重启恢复。
- 不实现协作编辑、分支版本或版本合并。
- 不实现无限日志保留和生产日志检索。

## 13. 验收标准

- 发布、版本列表、版本详情和恢复 API 有自动化回归测试。
- 取消、超时、重试和完整状态机有自动化回归测试。
- 运行详情可定位失败节点、尝试次数和稳定错误码。
- 前端真实调用取消 API，断线后可恢复最终状态。
- 前端完整显示新增状态，运行前可靠重置进度。
- 后端全量套件、前端测试和生产构建通过。
- 开发计划、问题记录和共享经验文档完成追加。
