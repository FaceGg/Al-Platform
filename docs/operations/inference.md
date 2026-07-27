# 第九周生产推理运维

## 范围

第九周把 `InferenceDeployment` 扩展为稳定的项目级推理服务：不可变 revision/target、持久 rollout、加权路由、暂停/恢复/回滚、部署 API Key、Redis 失败关闭限流、脱敏 telemetry、模型卡和安全 DomainEvent。Week 10 的 Outbox 与通知通道消费 DomainEvent，不在本服务内发送通知。

## 发布模型

- 每个部署保留稳定 revision；target 使用 0-10000 基点权重。
- rollout 状态为 `pending`、`preloading`、`progressing`、`paused`、`completed`、`failed`、`rolled_back`。
- 流量步骤由持久 `step_schedule` 和 `lock_version` CAS 驱动，候选 runtime alias 在推进前必须已恢复。
- runtime 同时保留 legacy deployment key 和 `revision_id:model_version_id` target key；回滚先提交 durable stable 状态，再 best-effort 清理候选 alias，失败由 reconciliation 重试。

## 访问与限流

生产预测使用 `X-Inference-Api-Key: mli_...` 调用 `/api/v1/inference/{deployment_id}/predict`。明文只在创建或轮换响应中出现一次；数据库仅保存 PBKDF2 hash。Key 绑定部署、scope、过期时间和撤销状态。

Redis token bucket 使用单 Lua 脚本完成时间读取、补充、扣减和 TTL。Redis 连接、脚本或响应异常统一返回 `RATE_LIMIT_BACKEND_UNAVAILABLE`（HTTP 503），不使用进程内 fallback；超额返回 `INFERENCE_RATE_LIMITED`（HTTP 429）和 `Retry-After`。

## 可观测性与模型卡

请求日志只保存稳定状态、错误码、批大小、耗时、版本和时间，不保存 records、predictions、凭据、storage URI 或 traceback。指标按部署/分钟聚合，查询边界和 retention 受配置限制。模型卡由系统字段生成，人工 operational guidance 通过 revision 更新；导出仍执行敏感字段扫描。

## 运行配置

生产必须设置 `INFERENCE_RUNTIME_URL`、`INFERENCE_INTERNAL_SECRET`（或 `_FILE`）以及限流和 rollout 观测参数：

```text
INFERENCE_RATE_LIMIT_CAPACITY
INFERENCE_RATE_LIMIT_REFILL_PER_SECOND
INFERENCE_ROLLOUT_OBSERVATION_SECONDS
```

Compose 中 inference runtime 只暴露容器端口 7000，不发布宿主端口；backend、worker、scheduler、runtime 使用同一 runtime URL/secret 和限流配置。Beat 分离执行 deployment recovery、rollout reconciliation 与 telemetry retention。

## 排障与验收

1. 先检查 `/api/ready` 的 `inference_runtime` 状态和 runtime `/health`。
2. `MODEL_LOAD_FAILED`、`INFERENCE_RUNTIME_UNAVAILABLE` 只记录稳定错误码；不要把路径或异常原文写入响应或日志。
3. 检查 rollout 的 `lock_version`、stable revision 和 runtime key 清单；candidate alias 缺失时先运行 reconciliation，再推进流量。
4. 检查 Redis 连通性和 `Retry-After`，不要通过降低限流或启用内存计数绕过故障。

本地验收命令：

```powershell
C:\Users\17723\miniconda3\python.exe run_suite.py --week 8
C:\Users\17723\miniconda3\python.exe run_suite.py --week 9
npm test -- --run
npm run build
$env:PATH = "C:\Users\17723\miniconda3;$env:PATH"
npm run test:e2e -- --project=chromium
```

真实 PostgreSQL、Redis、MinIO、Celery 和 runtime 生命周期必须在隔离 Compose/GitHub Actions 中执行，不能用 SQLite 单测替代。完整证据见 [`docs/week9-production-inference-acceptance.md`](../week9-production-inference-acceptance.md)。
