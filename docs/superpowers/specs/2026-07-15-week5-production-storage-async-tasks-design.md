# 第五周生产存储与异步任务设计

> 日期：2026-07-15
> 状态：已完成方案确认和规范自审，等待用户审阅
> 范围：PostgreSQL、Alembic、Redis/Celery、MinIO、制品 URI、配置与密钥管理

## 1. 目标与边界

第五周采用双模式渐进迁移：本地开发继续支持 SQLite、本地文件和线程执行；生产模式使用 PostgreSQL、Alembic、Redis/Celery 和 MinIO。现有 API、DAG 执行器和前端协议尽量保持兼容，通过适配器替换基础设施实现。

本周迁移工作流运行，不迁移训练任务。生产集成验收在 GitHub Actions Ubuntu 服务容器中完成，本机不要求安装 Docker。训练任务后续复用本周建立的任务分发接口。

## 2. 总体架构

系统增加三个稳定边界：

1. `Settings`：集中加载、校验和脱敏数据库、队列、对象存储及应用密钥配置。
2. `ArtifactStorage`：屏蔽本地文件与 MinIO 的存储差异，业务层只处理制品 URI。
3. `TaskDispatcher`：屏蔽本地线程与 Celery 的投递、取消和状态查询差异。

本地模式的数据流为 FastAPI -> SQLite/Local Storage/Thread Dispatcher。生产模式的数据流为 FastAPI -> PostgreSQL、MinIO、Celery/Redis；Celery Worker 运行现有 DAGExecutor，通过 PostgreSQL持久化状态，并通过 Redis Pub/Sub 向 FastAPI 发布实时事件。

## 3. PostgreSQL 与 Alembic

### 3.1 数据库配置

`DATABASE_URL` 继续作为 SQLAlchemy 统一入口。SQLite 使用适合本地和测试的连接参数；PostgreSQL启用连接池、`pool_pre_ping` 和可配置的池大小、溢出数量及连接超时。

生产模式要求 URL 使用 PostgreSQL 驱动。配置和日志只显示脱敏 URL，不得输出用户名后的密码内容。

### 3.2 Schema 生命周期

Alembic 是生产 Schema 的唯一变更入口。建立覆盖当前全部 SQLAlchemy 模型的基线 revision，后续字段、索引和约束只能通过新 revision 修改。

生产模式启动时不执行 `Base.metadata.create_all()`，也不执行 `ensure_schema_compatibility()`。应用启动时检查数据库 revision 是否等于 Alembic head，不一致时返回 `DATABASE_SCHEMA_OUTDATED` 并拒绝进入就绪状态。

SQLite 本地模式暂时保留 `create_all + ensure_schema_compatibility`，用于兼容现有开发数据库。该兼容模块不再增加新的生产字段迁移。

### 3.3 数据迁移

提供显式 SQLite 到 PostgreSQL 迁移命令。迁移按外键依赖顺序复制表记录，保留 UUID、时间、JSON 和空值语义；目标表已有相同主键时校验内容而不是重复插入。完成后输出每张表的源记录数、目标记录数和差异，任何差异均使命令返回非零退出码。

迁移命令不删除、覆盖或重命名原 SQLite 文件。正式切换前由使用者单独备份并修改生产配置。

## 4. Local/MinIO 制品存储

### 4.1 存储接口

`ArtifactStorage` 提供 `put`、`open`、`materialize`、`exists`、`delete` 和完整性校验。Local Provider 生成 `file://` URI；MinIO Provider 生成 `s3://bucket/key` URI。

MinIO 对象键固定为 `projects/{project_id}/artifacts/{artifact_id}/{filename}`。文件名必须去除路径分隔符和父目录引用，服务端生成 artifact ID，调用方不能提供对象键。

### 4.2 模型兼容

`Artifact` 增加 `storage_uri`。原 `storage_path` 在第五周继续保留，读取时优先使用 `storage_uri`，为空时兼容旧路径。新代码不得把 MinIO URI 写入 `storage_path`。

需要真实文件路径的 Pandas、训练算子和历史实现通过 `materialize()` 将对象下载到 `temp_test` 隔离缓存。上下文结束后回收文件，不把 MinIO 下载缓存写入源码目录。

### 4.3 一致性与迁移

上传过程流式计算 SHA-256 和文件大小。对象写入成功但数据库提交失败时删除对应对象；补偿删除失败时记录结构化错误，保留可审计对象键。

历史制品迁移命令逐条上传本地文件，校验 SHA-256 和大小后更新 `storage_uri`。命令可重复执行，已验证的记录直接跳过；失败记录保持原 `storage_path`，不影响继续读取。

Dataset 上传、训练模型输出和 `OperatorResult.artifacts` 统一经过 `ArtifactService`。第五周不暴露 MinIO 预签名地址，下载仍由后端完成项目权限检查。

## 5. Celery 工作流执行

### 5.1 分发接口

`TaskDispatcher` 提供 `enqueue_workflow`、`cancel` 和 `get_status`。Local Dispatcher 封装当前线程行为；Celery Dispatcher 只负责队列操作，不直接执行业务逻辑。

API 创建并提交 `WorkflowRun` 后投递任务，Celery 参数只包含 `run_id`。Worker 使用独立数据库会话读取不可变工作流快照并调用现有 `DAGExecutor`。

### 5.2 状态与幂等

`WorkflowRun` 增加 `task_id`、`queue_name`、`worker_id` 和 `heartbeat_at`。Worker 通过 PostgreSQL 行锁领取运行：终态直接退出；具有新鲜心跳的 `running` 任务视为重复投递；无有效领取者或心跳过期的任务允许恢复执行。

API 提交 Broker 失败时保留数据库中的待投递记录并返回 `TASK_ENQUEUE_FAILED`。应用启动恢复和 Celery 周期任务扫描没有有效 `task_id` 的待运行记录并重新投递。

### 5.3 超时、取消与恢复

Celery 任务启用 `acks_late` 和 `task_reject_on_worker_lost`。软超时由任务包装器捕获并写入结构化失败状态；硬超时用于终止失控 Worker 子进程。无法执行清理逻辑的硬终止由心跳恢复任务识别并收敛状态。

取消操作先将数据库状态改为 `cancel_requested`，再调用 Celery revoke。任务在协作取消宽限期内通过现有 `RunControl` 退出；超过宽限期后生产模式允许终止对应 Celery 子进程。重复取消和终态取消保持幂等。

API 服务重启不影响 Celery Worker。Worker 崩溃后任务重新入队，领取逻辑防止同一运行被两个有效 Worker 同时执行。

### 5.4 实时事件

Local Dispatcher 继续使用当前事件循环广播。Celery Worker 将节点和运行事件发布到 Redis Pub/Sub；FastAPI lifespan 启动订阅器并转发给 WebSocket Manager。

WebSocket 只用于实时体验，PostgreSQL 是状态真相来源。客户端重连后继续通过现有 Run REST API 恢复完整状态。

## 6. 配置与密钥

Pydantic `Settings` 统一管理 `APP_MODE`、数据库、Celery、Redis、MinIO、JWT 和临时目录。敏感字段使用 `SecretStr`。

每个敏感配置支持 `NAME` 和 `NAME_FILE` 两种来源。两者同时存在时拒绝启动；文件必须存在、可读且内容非空。日志、异常、健康检查和配置摘要统一脱敏。

本地模式允许开发默认值。生产模式必须满足以下条件：

- PostgreSQL 数据库 URL 已配置。
- Celery Broker 和 Redis Pub/Sub 已配置。
- MinIO endpoint、bucket、access key 和 secret key 已配置。
- JWT 密钥不是默认值且达到最低长度。

仓库只提供 `.env.example`，不得提交真实 `.env`、访问密钥、密码、Token 或 Secret 文件。

## 7. 健康检查与错误处理

`/api/health` 保持 `{"status": "ok"}` 兼容响应。新增 `/api/ready`，分别检查数据库、Alembic revision、Redis、Celery Worker 和 MinIO bucket。

就绪响应只包含组件名称、状态和稳定错误码，不包含 URL 凭据、对象存储密钥或内部 traceback。主要错误码包括：

- `DATABASE_UNAVAILABLE`
- `DATABASE_SCHEMA_OUTDATED`
- `STORAGE_UNAVAILABLE`
- `STORAGE_INTEGRITY_FAILED`
- `TASK_ENQUEUE_FAILED`
- `TASK_WORKER_UNAVAILABLE`
- `TASK_HARD_TIMEOUT`

基础设施异常记录完整服务端日志，API 返回可操作但不泄密的错误信息。

## 8. 测试与 CI

### 8.1 本地模式回归

保留现有 Windows/Linux SQLite、Local Storage 和 Local Dispatcher 测试。后端 33 个模块、前端 35 个用例、生产构建和 Playwright 主流程不得回归。

增加 Settings、Secret 文件、URL 脱敏、Local Storage、MinIO URI 解析、Dispatcher 选择和 Alembic版本检查单元测试。

### 8.2 生产集成测试

新增 Ubuntu `production-integration` GitHub Actions job，启动 PostgreSQL、Redis 和 MinIO 服务容器，并启动真实 Celery Worker。测试步骤包括：

1. 空 PostgreSQL 执行 `alembic upgrade head` 并验证重复升级。
2. 验证核心用户、项目、工作流、运行和制品 CRUD。
3. 上传、读取和迁移 MinIO 制品，校验 SHA-256 与对象键隔离。
4. 投递工作流并等待 Worker 完成。
5. 验证重复投递、取消、软超时、硬超时收敛和失败恢复。
6. 重启 API 后确认 Worker 继续执行，REST 与 WebSocket 状态可恢复。
7. 验证 `/api/ready` 和所有日志均不暴露密钥。

Windows/Ubuntu 原有质量矩阵继续运行本地模式，不依赖服务容器。

## 9. 交付物与完成标准

第五周交付物包括生产配置模型、Alembic 迁移链、SQLite 到 PostgreSQL 迁移命令、Local/MinIO存储适配器、历史制品迁移命令、Local/Celery 分发器、Redis 事件桥接、生产集成 CI，以及部署、迁移、回滚和故障排查文档。

只有同时满足以下条件才能将第五周标记为完成：

- 本地模式现有自动化测试和浏览器主流程全部通过。
- Ubuntu 生产集成 job 使用真实 PostgreSQL、Redis、MinIO 和 Celery 通过。
- 数据库与制品迁移可重复执行且有数量、大小和哈希校验。
- API 重启不终止已投递工作流，取消和超时状态最终一致。
- 正式代码、日志、测试输出和文档不包含真实凭据。

## 10. 明确不在本周范围

- 训练任务迁移到 Celery。
- 实验跟踪、检查点、TensorBoard 和 AutoML Trial。
- MinIO 预签名下载和外部直传。
- Vault、动态数据库凭据和自动密钥轮换。
- Celery 多队列优先级、Cron Pipeline 和项目级调度配额。
- Kubernetes、GPU Worker 和多集群调度。
