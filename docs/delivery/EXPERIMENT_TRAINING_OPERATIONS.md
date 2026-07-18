# 实验与训练运维

## 服务配置

生产 Compose 使用 PostgreSQL 16、Redis 7、MinIO、MLflow 3.2.0、Celery Worker 和隔离 TensorBoard Gateway。平台业务库与 MLflow tracking backend 使用不同数据库；模型 Artifact 仍由平台 ArtifactService 登记，MLflow 保存 Run、指标、checkpoint 和 event artifact。

必须通过环境变量或 secret file 注入 `DATABASE_URL`、`SECRET_KEY`、`CELERY_BROKER_URL`、`REDIS_EVENTS_URL`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MLFLOW_BACKEND_STORE_URI` 和 `TENSORBOARD_SESSION_SECRET`。常用地址为 `MLFLOW_TRACKING_URI=http://mlflow:5000`、`MLFLOW_ARTIFACT_ROOT=s3://ml-platform/mlflow`、`MLFLOW_S3_ENDPOINT_URL=http://minio:9000`、`TENSORBOARD_GATEWAY_URL=http://tensorboard-gateway:6006`。

所有 Python 镜像和 CI 安装步骤固定使用 `https://mirrors.aliyun.com/pypi/simple/`；Backend/Worker 额外安装 `boto3`，MLflow 官方镜像启动时安装 `psycopg[binary]`。

## Experiment 生命周期

在 `/training` 页面选择项目后创建 Experiment。平台 PostgreSQL 保存项目归属和 MLflow Experiment ID；用户可打开 Runs，选择 2 至 10 个 Run 查看参数、最终指标和指标历史。前端只调用平台 API，不直接访问 MLflow。

训练任务必须绑定 Experiment 和 Dataset Artifact。Celery Worker 每个 epoch 写入 MLflow 指标、平台心跳和受控 TensorBoard event；完成后平台登记模型 Artifact/ModelLibrary 血缘。AutoML 使用 parent Run，每个候选使用 child Run；单个候选失败不会终止其他候选。

## 检查点与恢复

检查点保存在 Run 的 `checkpoints/epoch-*.joblib`、`latest.joblib` 和 `best.joblib`。页面的恢复操作只提交逻辑 `checkpoint_path`，后端绑定到已授权 source Run 后创建新的 TrainingJob/Run。恢复任务从 checkpoint 下一 epoch 继续，原 Run 不被修改。停止先进入 `cancel_requested`，Worker 在 epoch 边界保存状态并以 `KILLED` 结束 Run。

## TensorBoard 会话

平台先验证 TrainingJob 所属项目和 MLflow Run，再签发短期 HMAC token。Gateway 只接受受控相对目录 `project_id/run_id`，子进程监听内部 localhost，日志卷不暴露 Docker socket。会话过期或空闲超时会清理进程；跨 Run、遍历路径、篡改 token 和未授权资源返回 403/404。

## Readiness、回滚与备份

`GET /api/ready` 必须同时报告 `database`、`redis`、`celery`、`storage`、`mlflow` 和 `tensorboard`。稳定错误码包括 `MLFLOW_UNAVAILABLE`、`TENSORBOARD_UNAVAILABLE`、`TRACKING_UNAVAILABLE`、`TRAINING_FAILED` 和 `TENSORBOARD_SESSION_INVALID`。排障使用 `docker compose ps`、`docker compose logs --no-color backend worker mlflow tensorboard-gateway` 和 `curl --fail http://127.0.0.1:8000/api/ready`。

升级前备份平台 PostgreSQL、独立 MLflow PostgreSQL 和 MinIO bucket。停止 API/Worker 写入后保留 `mlflow` 与 `tensorboard-events` 数据，再回退应用镜像和依赖版本。若必须临时关闭追踪，使用 local 模式和 local artifact backend，不把生产数据库切换到未迁移 SQLite。

WSL2 Docker Engine 29.6.2 / Compose 5.3.1 已通过 `docker compose config`、目标镜像构建、Alembic 双次 upgrade/check、`/api/ready` 六项 OK，以及真实 Experiment/Run、指标、checkpoint、恢复、比较和 TensorBoard session 集成测试 1/1。
