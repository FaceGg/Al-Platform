# 第六周实验与训练管理设计

> 日期：2026-07-17
> 状态：已确认
> 适用项目：汽车焊接工业 AI 平台

## 1. 目标

第六周在第五周 PostgreSQL、Redis/Celery 和 MinIO 生产基础设施之上，建立可审计的实验与训练管理闭环：实验、Run、参数、指标时间序列、日志、制品、检查点、恢复、早停、AutoML Trial 和受控 TensorBoard 访问。

完成后，用户可以在项目内创建实验，提交普通训练或 AutoML，比较 Run，查看训练曲线与血缘，从检查点恢复任务，并通过平台鉴权打开仅包含目标 Run 的 TensorBoard。

## 2. 架构决策

采用“平台编排 + MLflow 追踪”架构：

- 平台 PostgreSQL 是项目权限、训练任务状态和业务关联的事实来源。
- MLflow 是 Experiment、Run、参数、指标、标签和实验制品元数据的事实来源。
- MLflow Tracking Server 使用独立 PostgreSQL 数据库和现有 MinIO artifact store。
- API 通过 `ExperimentTrackingService` 使用 MLflow，不在路由或 ORM 模型中散布 MLflow SDK 调用。
- 普通训练与 AutoML 均由 Celery Worker 执行，不再启动 API 进程内线程。
- 最终模型仍由平台 `ArtifactService` 登记，并写入模型库；检查点和 TensorBoard event 由 MLflow/MinIO 管理。
- 不双写完整指标时间序列，避免平台数据库和 MLflow 之间的补偿与对账负担。

## 3. 组件边界

### 3.1 平台 Experiment 模型

新增 `Experiment`：

- `id`：平台 UUID。
- `project_id`：所属项目，删除项目时级联删除绑定记录。
- `created_by`：创建用户。
- `name`、`description`：项目内名称和说明。
- `mlflow_experiment_id`：MLflow Experiment ID，唯一且非空。
- `created_at`、`updated_at`。

平台只通过项目所有权授权 Experiment。MLflow Experiment 名称使用稳定命名空间 `project/<project_uuid>/<experiment_uuid>`，展示名称保留在平台模型中，避免跨项目重名。

### 3.2 TrainingJob 扩展

`TrainingJob` 增加：

- `experiment_id`、`mlflow_run_id`。
- `task_id`、`worker_id`、`heartbeat_at`、`attempt`。
- `resumed_from_job_id`、`resumed_from_run_id`、`resume_checkpoint_uri`。
- `latest_checkpoint_uri`、`best_checkpoint_uri`。
- `current_epoch`、`total_epochs`、`monitor_name`、`monitor_mode`。
- `early_stopping_patience`、`early_stopping_min_delta`、`restore_best`。

状态限定为 `pending`、`running`、`completed`、`failed`、`cancel_requested`、`cancelled`。状态转换由训练服务集中执行，API、Celery task 和恢复扫描不得各自定义不同语义。

### 3.3 MLflow adapter

`ExperimentTrackingService` 负责：

- 创建或读取 MLflow Experiment。
- 创建 parent/child Run，记录平台 ID、项目 ID、用户 ID 和恢复血缘标签。
- 批量记录参数、epoch 指标和结构化标签。
- 上传、列出和下载 checkpoint/TensorBoard artifacts。
- 结束或终止 Run。
- 查询实验 Run、指标历史和制品。

业务代码只依赖平台定义的协议和数据类；测试使用内存 fake，真实集成测试使用 MLflow Tracking Server。

## 4. 训练执行

### 4.1 普通迭代训练

第六周新增轻量可恢复训练器：

- 分类：`SGDClassifier(loss="log_loss")`，首次 `partial_fit` 提供完整类别集合。
- 回归：`SGDRegressor`。
- 数值特征使用训练集拟合的 `StandardScaler`；目标列和特征 Schema 固化到 checkpoint。
- 数据划分使用固定随机种子，恢复任务复用原训练配置和数据 Artifact。
- 每个 epoch 记录训练损失、验证损失和主指标；分类主指标为 accuracy，回归主指标为 r2，同时记录 rmse。

每个 epoch 后按顺序执行：记录指标、更新心跳与 epoch、检查取消、判断早停、按间隔保存 checkpoint。数据库更新和 MLflow 写入失败必须产生结构化错误，不得将部分完成任务标记为成功。

### 4.2 早停

配置字段为：

- `monitor`：允许的指标名称。
- `mode`：`min` 或 `max`。
- `patience`：无改善 epoch 数，必须大于等于 1。
- `min_delta`：最小改善幅度，必须大于等于 0。
- `restore_best`：完成或早停时是否恢复最佳 checkpoint。

早停状态保存在 checkpoint 中。恢复后继续累计 patience，不从零开始。无效指标或 mode 在任务创建时返回稳定错误码。

### 4.3 Checkpoint 与恢复

checkpoint 使用 joblib 包，包含：

- 模型和预处理器。
- 已完成 epoch、最佳 epoch、最佳指标和无改善计数。
- 类别信息、特征 Schema、目标 Schema 和训练参数。
- 数据 Artifact ID、源 TrainingJob ID、源 MLflow Run ID 和格式版本。

checkpoint 路径为 `checkpoints/epoch-000001.joblib`，同时维护 `checkpoints/latest.joblib` 与 `checkpoints/best.joblib`。MLflow artifact URI 是持久引用，本地物化路径不得写入数据库。

恢复操作创建新的 TrainingJob 和 MLflow Run，不修改原 Run。新任务记录源 job/run/checkpoint，并从 checkpoint epoch 的下一轮继续。恢复前校验项目权限、checkpoint 格式版本、数据 Artifact 可访问性和训练参数兼容性。

### 4.4 取消与失联恢复

停止接口先将任务改为 `cancel_requested`，再 revoke Celery task。Worker 每个 epoch 检查数据库状态；收到取消时保存最后 checkpoint，结束 MLflow Run，并将状态改为 `cancelled`。

恢复扫描使用 `heartbeat_at` 判定失联：

- 有有效 latest checkpoint：增加 attempt 并重新投递同一 TrainingJob，从 latest checkpoint 继续。
- 无 checkpoint：标记 `failed`，错误码为 `TRAINING_WORKER_LOST`。
- 已请求取消：标记 `cancelled`，不得重新投递。

## 5. AutoML Trial

现有 AutoML 从 `dataset_path` 和 API 线程迁移到 Dataset Artifact 与 Celery。

- AutoML TrainingJob 对应 MLflow parent run。
- 每个候选模型对应 child run，记录候选参数、交叉验证指标、耗时和失败原因。
- child run 失败不终止其他候选；全部失败时 parent job 才失败。
- 最佳候选在完整训练集路径上完成训练，最终模型进入平台 Artifact 和模型库。
- parent run 记录最佳 child run ID、最佳指标和最终平台 Artifact ID。

第六周保留确定性的有限候选集合，不实现分布式超参搜索、贝叶斯优化或并行 Trial 调度。

## 6. API

### 6.1 Experiment

- `POST /api/experiments`：创建项目 Experiment。
- `GET /api/experiments?project_id=`：列出当前用户可访问的 Experiment。
- `GET /api/experiments/{experiment_id}`：返回平台元数据和 MLflow 汇总。
- `GET /api/experiments/{experiment_id}/runs`：分页列出 Run。
- `POST /api/experiments/{experiment_id}/compare`：比较 2 至 10 个 Run 的参数、最终指标和指标历史。

### 6.2 Training

- `POST /api/training/run`：要求 `experiment_id`、Dataset Artifact、训练器和参数，返回 TrainingJob ID。
- `GET /api/training/jobs`、`GET /api/training/jobs/{job_id}`：包含 experiment/run、epoch、checkpoint 和恢复血缘。
- `POST /api/training/jobs/{job_id}/stop`：请求取消。
- `GET /api/training/jobs/{job_id}/checkpoints`：列出 MLflow checkpoint artifacts。
- `POST /api/training/jobs/{job_id}/resume`：从指定或 latest checkpoint 创建恢复任务。
- `POST /api/training/jobs/{job_id}/tensorboard-session`：创建短期 TensorBoard 会话。

所有 UUID 在 API 边界解析；无权限资源统一返回 404，避免泄露跨项目 ID。错误响应包含稳定 `code` 和 `message`。

## 7. TensorBoard 隔离网关

不暴露共享 TensorBoard 公共端口。新增独立 `tensorboard-gateway` 服务：

- 平台后端校验 TrainingJob、Experiment 和项目权限后签发短期 HMAC token。
- token 包含会话 ID、Run ID、安全的相对日志目录和过期时间，不包含宿主机绝对路径。
- 网关验证签名和有效期，只能将日志目录解析到固定根目录内。
- 每个有效会话启动或复用仅指向目标 Run 的 TensorBoard 子进程，并通过随机会话路径代理 HTTP/WebSocket。
- 相同 Run 的有效会话可复用进程；过期会话和空闲进程自动清理。
- 网关容器以非 root 用户运行，不挂载 Docker socket，不接受任意命令或任意 logdir。

训练 Worker 将 event 写入共享临时卷，并在 Run 结束时作为 MLflow artifact 持久化。已完成 Run 首次打开 TensorBoard 时，网关先从 MLflow/MinIO 物化 event 到受控缓存。

## 8. 前端

训练页面改为“实验”和“训练任务”两个 Tab，沿用现有紧凑操作型布局：

- Experiment 列表展示名称、Run 数、最佳指标和最近运行时间。
- Run 表格支持选择 2 至 10 个 Run 进行参数和指标比较。
- Run 详情使用侧栏或 Modal 展示参数、指标曲线、结构化日志、制品、checkpoint 和血缘。
- TrainingJob 表格展示进度、当前 epoch、主指标、状态和来源。
- 任务操作包括停止、从 checkpoint 恢复和打开 TensorBoard。
- 所有新增文本保持中英文键同构；按钮使用现有图标库和工具提示。

前端不直接调用 MLflow 或 TensorBoard 地址，所有请求经过平台 API。

## 9. 配置与部署

新增配置：

- `MLFLOW_TRACKING_URI`、`MLFLOW_BACKEND_STORE_URI`、`MLFLOW_ARTIFACT_ROOT`。
- `MLFLOW_DATABASE_NAME`，默认 `mlflow`，与平台业务数据库分离。
- `TENSORBOARD_GATEWAY_URL`、`TENSORBOARD_SESSION_SECRET_FILE`。
- `TENSORBOARD_SESSION_TTL_SECONDS`、`TENSORBOARD_IDLE_TIMEOUT_SECONDS`。
- `TRAINING_CHECKPOINT_INTERVAL_EPOCHS`、`TRAINING_STALE_AFTER_SECONDS`。

Compose 增加 MLflow schema 初始化、MLflow server 和 TensorBoard gateway。Backend/Worker 仅在生产模式要求这些配置；本地测试可使用 fake tracking adapter，本地完整模式可启动 Compose 服务。

`/api/ready` 增加 MLflow 与 TensorBoard gateway 检查。生产 CI 在第五周服务组合上增加 MLflow 与 TensorBoard，并执行真实 Experiment/Run/checkpoint 会话冒烟。

## 10. 数据迁移与兼容

- Alembic 新 revision 创建 experiments 表并扩展 training_jobs。
- SQLite 兼容迁移同步新增列与索引，开发库不依赖 Alembic baseline。
- 既有 TrainingJob 的 `experiment_id` 和 `mlflow_run_id` 可为空，只读列表继续兼容。
- 新建任务必须提供 Experiment；旧 checkpoint_path API 被新的 job-scoped checkpoint API 取代。
- 删除 Experiment 只删除平台绑定，不自动删除 MLflow 历史；第六周不提供不可逆的 MLflow Experiment 删除。

## 11. 测试与验收

测试按第六周清单唯一归属，覆盖：

- Experiment 模型、权限、名称冲突和 MLflow 绑定。
- MLflow adapter 的创建、记录、查询、比较、制品和失败映射。
- 迭代训练指标、早停、best/latest checkpoint、取消和恢复血缘。
- 失联任务有/无 checkpoint 的恢复结果。
- AutoML parent/child Run、部分失败和最佳模型登记。
- TensorBoard token 签名、过期、路径穿越、Run 隔离、进程复用和清理。
- 前端 Experiment/Run 列表、比较、任务操作和 API 契约。
- PostgreSQL、Redis/Celery、MinIO、MLflow 和 TensorBoard 真实集成。
- Windows/Ubuntu 全量质量、前端构建、Chromium 主流程、npm audit 和 Alembic check。

只有以下条件同时满足，才能将第六周标记为完成：

- 普通训练和 AutoML 不再由 API 进程内线程执行。
- Experiment/Run/参数/指标/日志/制品可按项目权限查询。
- checkpoint、早停、恢复、取消和失联恢复有真实执行测试。
- TensorBoard 不能跨 Run 浏览日志，未授权和过期会话被拒绝。
- MLflow/PostgreSQL/MinIO/Celery/TensorBoard 生产集成通过。
- 本地与远程全量回归、文档和安全扫描通过。

## 12. 不在第六周范围

- PyTorch 深度学习 checkpoint 与分布式训练。
- 分布式 AutoML Trial 调度、贝叶斯优化和 GPU 搜索。
- 模型审批、模型卡、在线部署和灰度发布。
- Pipeline Cron、优先级、项目配额和 Kubernetes Executor。
- MLflow 历史硬删除、跨项目 Experiment 转移和外部用户直连 MLflow。
