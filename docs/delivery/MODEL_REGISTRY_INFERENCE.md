# 模型注册与基础推理运维指南

第八周提供项目级不可变 ONNX 模型版本、审批、独立推理 runtime 和 named-record 在线测试。`ModelLibrary` 仍是训练结果目录；`RegisteredModel`、`ModelVersion` 与 `InferenceDeployment` 是部署控制面。

## 权限

| 角色 | 查看 | 注册版本 | 审批/创建部署 | 启停/推理 |
|---|---:|---:|---:|---:|
| owner | 是 | 是 | 是 | 是 |
| editor | 是 | 是 | 是 | 是 |
| operator | 是 | 否 | 否 | 是 |
| viewer | 是 | 否 | 否 | 否 |

无项目关系的用户获得隐藏 404；已有成员权限不足获得 403。注册、审批、部署命令写入脱敏审计；预测 records 和结果不持久化。

## 模型来源与版本

- 平台来源只接受同项目、completed TrainingJob/ModelLibrary、受信任 training/automl provenance 和 joblib 格式。
- 转换子进程只允许 Logistic/Linear Regression、Random Forest、Gradient Boosting 及可选 StandardScaler，120 秒默认 timeout，输出必须通过 ONNX checker、CPU session 与 synthetic inference。
- 直接 ONNX 上传最大 256 MiB，使用流式临时文件、SHA-256、项目归属和显式 feature/output schema。
- 每个逻辑模型版本号单调递增。版本 snapshot 不可变；状态为 pending、approved、rejected、archived。拒绝必须填写意见。
- 转换、验证或数据库提交失败会补偿生成的对象存储内容；稳定错误码不包含路径或异常文本。

## 部署和推理

1. 在“模型库”选择项目，创建注册模型并注册平台或 ONNX 版本。
2. 在版本 Drawer 批准 pending 版本。
3. 在“推理部署”选择 approved 版本创建部署，再启动。
4. 在线测试提交 JSON 对象数组；字段必须与冻结 feature schema 完全一致。
5. 响应包含 predictions、可选 probabilities、精确 model version 和 duration_ms。
6. 停止后推理返回 `DEPLOYMENT_NOT_READY`。

推理边界限制 1-100 条 records、1 MiB body、有限 numeric 值，Backend 默认 30 秒 deadline。未知/缺失字段、bool 冒充数值、NaN/Infinity 均拒绝。

## Runtime 配置

生产必须配置 `INFERENCE_RUNTIME_URL` 与 32+ 字符 `INFERENCE_INTERNAL_SECRET` 或 `_FILE`。Compose 的 `inference-runtime` 只 `expose: 7000`，无宿主端口，UID/GID 1000 运行单 Uvicorn worker。`/health` 不鉴权；所有 `/internal` 路由使用 constant-time token 比较。

`/api/ready` 包含 `inference_runtime`。本地未配置返回 `LOCAL_MODE`；生产不可达返回 `INFERENCE_RUNTIME_UNAVAILABLE`。Celery Beat 每 60 秒按数据库 desired state reconciliation，可在 runtime session 丢失后重载，在 stopped 状态卸载多余 session。

## 生产验证与排障

- `docker compose config --quiet` 验证必填 secret 与内部依赖。
- `docker compose build inference-runtime` 必须显示阿里云 PyPI 源并以非 root 用户运行。
- `RUN_INFERENCE_INTEGRATION=1 python -m unittest tests.test_inference_production_stack -v` 只在隔离 PostgreSQL/MinIO 项目执行。
- 失败证据可收集 backend、scheduler、inference-runtime 日志；先替换 secret，再扫描原值，禁止上传未脱敏日志。
- `MODEL_CONVERSION_*` 检查来源、模型 allowlist、timeout 和资源限制；`MODEL_ARTIFACT_INTEGRITY_FAILED` 检查 MinIO 对象 size/SHA-256；`MODEL_LOAD_FAILED` 检查 ONNX Runtime 兼容性。

第九周再实现 rolling upgrade、public key、资源配额、生产 telemetry、灰度/回滚和多副本 session 分发。本周不承诺这些能力。
