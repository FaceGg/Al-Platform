# 通用平台验收矩阵

**状态：** planned，Task 14 交付物。以下编号与主技术方案第 16.4 节一致。

## 执行上下文

命令基准目录：后端命令从 `ml-platform/backend` 执行；前端命令从 `ml-platform/frontend` 执行。证据根目录固定为 `temp_test/generic-platform-acceptance/`，每个矩阵编号的回执固定写入 `receipts/<ID>.json`，由 `backend/tools/generic_acceptance_evidence.py` 生成。回执必须记录当前 Git SHA、实际命令、测试源文件 hash、生成制品的路径/hash、状态和脱敏检查结果。

恢复演练必须在与 CI 相同的 Compose/容器边界执行，不能把宿主机直接调用 `run_backup_restore.sh` 当作验收：

- WSL 仓库根目录由 PowerShell 7 先通过 `wsl.exe -e wslpath -a (Get-Location).Path` 转换；`ML_PLATFORM_EVIDENCE_DIR` 必须是该路径下的绝对 Linux 路径。
- 本地受控演练使用 `COMPOSE_FILE=docker-compose.yml:docker-compose.acceptance.yml`；CI 的权威上下文是 `.github/workflows/ci.yml` 的 `week11-12-verification` job，使用 `docker-compose.yml:docker-compose.week12-security-images.yml`，并先构建、校验绑定当前 SHA 的 backend、worker、inference 和 tensorboard 镜像。
- `run_week11_acceptance.sh` 使用 `docker compose ... up --no-build`，执行前必须通过 `docker compose --project-name "$COMPOSE_PROJECT_NAME" config -q`，并确保 `postgres`、`redis`、`minio`、`minio-init`、`mlflow`、`tensorboard-gateway`、`inference-runtime`、`migrate`、`backend`、`worker` 和 `scheduler` 已按 health/dependency contract 就绪。
- Compose 必须提供这些变量：`POSTGRES_DB`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`DATABASE_URL`、`SECRET_KEY`、`CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND`、`REDIS_EVENTS_URL`、`MINIO_ROOT_USER`、`MINIO_ROOT_PASSWORD`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MLFLOW_BACKEND_STORE_URI`、`MLFLOW_ARTIFACT_ROOT`、`MLFLOW_TRACKING_URI`、`TENSORBOARD_SESSION_SECRET` 和 `INFERENCE_INTERNAL_SECRET`；其中密码、URL 中的凭据、密钥和 token 只来自受控 CI/本地密钥配置，绝不写入回执。
- `NOTIFICATION_CRYPTO_SECRET_FILE` 必须存在并能被运行时 UID 1000 读取；使用 acceptance Compose overlay 时，还必须提供 `NOTIFICATION_ACCEPTANCE_CA_FILE`、`NOTIFICATION_RECEIVER_CERTIFICATE_FILE` 和 `NOTIFICATION_RECEIVER_PRIVATE_KEY_FILE`。
- `COMPOSE_PROJECT_NAME`、`ML_PLATFORM_EVIDENCE_DIR` 和 `ACCEPTANCE_SOURCE_COMMIT` 必须显式设置；`ACCEPTANCE_SOURCE_COMMIT` 必须等于当前 Git SHA。
- WSL 解析 runner 前必须确认 `run_*.sh` 使用 LF 行尾。当前 Windows 工作树受 `core.autocrlf=true` 影响可能物化为 CRLF；这种状态下直接 `bash` 运行或语法检查不属于通过，需使用 Linux/CI checkout 或不覆盖当前工作树的 LF 校验副本。
- 版本化 runner 只负责写入 `environment.json`、性能结果、`recovery/backup/*` 和 `recovery/upgrade/*`。`recovery/cleanup.json` 不由 Compose teardown 生成，必须由 Task 13 的 `cleanup_orphan_artifacts` 验收 harness 序列化；缺少该文件时 REL-01 保持 `in_progress`。

PowerShell 7 先转换路径，再以 `wsl.exe -e sh -lc` 在 WSL 仓库根目录设置 `COMPOSE_PROJECT_NAME` 和绝对 Linux 路径 `ML_PLATFORM_EVIDENCE_DIR=$repoWsl/temp_test/generic-platform-acceptance/recovery`，运行 `bash ml-platform/backend/tools/acceptance/run_week11_acceptance.sh`，由版本化 runner 调用后端容器内的 backup/upgrade 执行器。

Task 13 清理回执（在同一个 Compose 项目、backend 容器内、恢复 runner 完成后执行）的计划命令为：

```sh
docker compose --project-name "$COMPOSE_PROJECT_NAME" run --rm -T \
  --user "$(id -u):$(id -g)" \
  -v "$ML_PLATFORM_EVIDENCE_DIR:/evidence" \
  backend python -m tools.cleanup_acceptance \
  --older-than-seconds 3600 \
  --output /evidence/cleanup.json \
  --source-commit "$ACCEPTANCE_SOURCE_COMMIT"
```

该命令对应计划中的新建工具，当前工作树尚未提供该工具；在 Task 13 完成前不得执行或伪造其输出。

## 验收编号

| 编号 | 覆盖内容 | 精确验证命令 | 必须存在的回执或关联制品 |
|---|---|---|---|
| DAT-01 | JSON/XML 正常导入 | `py -3.14 -m pytest tests/test_dataset_import_contract.py -q` | `receipts/DAT-01.json` |
| DAT-02 | JSON/XML 安全输入 | `py -3.14 -m pytest tests/test_dataset_import_contract.py -q` | `receipts/DAT-02.json` |
| DAT-03 | 缺列与空值 | `py -3.14 -m pytest tests/test_dataset_import_contract.py -q` | `receipts/DAT-03.json` |
| LAB-01 | 标签类型与值校验 | `py -3.14 -m pytest tests/test_label_schema.py -q` | `receipts/LAB-01.json` |
| LAB-02 | 三种自动策略与不可删除兜底 | `py -3.14 -m pytest tests/test_annotation_strategies.py -q` | `receipts/LAB-02.json` |
| LAB-03 | 策略逐列优先级与冲突 | `py -3.14 -m pytest tests/test_annotation_strategies.py -q` | `receipts/LAB-03.json` |
| CLU-01 | 特征重要性加权 KMeans | `py -3.14 -m pytest tests/test_annotation_strategies.py -q` | `receipts/CLU-01.json` |
| CLU-02 | 百万样本最终全量赋簇 | `py -3.14 -m pytest tests/test_annotation_strategies.py -q` | `receipts/CLU-02.json` |
| CON-01 | 重叠样本乐观并发 | `py -3.14 -m pytest tests/test_annotation_concurrency.py -q` | `receipts/CON-01.json` |
| CON-02 | 并发回传与幂等 | `py -3.14 -m pytest tests/test_annotation_concurrency.py tests/test_annotation_return_acceptance.py -q` | `receipts/CON-02.json` |
| RET-01 | 回传后只读锁与新修订解锁 | `py -3.14 -m pytest tests/test_annotation_return_acceptance.py -q` | `receipts/RET-01.json` |
| AUTH-01 | 独立门户认证与会话撤销 | `py -3.14 -m pytest tests/test_annotator_auth.py -q` | `receipts/AUTH-01.json` |
| AUTH-02 | CORS、CSRF、限流、密码和服务间认证 | `py -3.14 -m pytest tests/test_security_contract.py -q` | `receipts/AUTH-02.json` |
| API-01 | 长任务、分页、幂等、revision、审计 | `py -3.14 -m pytest tests/test_annotation_task_state.py tests/test_async_operation_contract.py -q` | `receipts/API-01.json` |
| AUTO-01 | 四种规范 AutoML 任务类型 | `py -3.14 -m pytest tests/test_automl_multioutput.py -q` | `receipts/AUTO-01.json` |
| AUTO-02 | 用户手动注册候选模型 | `py -3.14 -m pytest tests/test_model_registration_contract.py -q` | `receipts/AUTO-02.json` |
| EXP-01 | 导出包、SBOM、签名和策略工件 | `py -3.14 -m pytest tests/test_model_export_contract.py -q` | `receipts/EXP-01.json`；回执记录导出包内 `manifest.json`、`checksums.json`、`security/sbom.spdx.json`、`security/manifest.sig` 的 hash |
| INF-01 | 离线 predict/annotate 输入拒绝 | `py -3.14 -m pytest tests/test_offline_inference_contract.py -q` | `receipts/INF-01.json`；回执记录脱敏 `validation-report.json` 的 hash |
| REL-01 | 租约、重试、恢复和清理 | `py -3.14 -m pytest tests/test_async_operation_contract.py tests/test_week11_12_tools.py -q`; isolated Compose: run `bash ml-platform/backend/tools/acceptance/run_week11_acceptance.sh` in the context above, then execute the Task 13 command block above | `receipts/REL-01.json`；runner 生成 `recovery/backup/restore-result.json`、`recovery/upgrade/result.json`；Task 13 cleanup harness 生成 `recovery/cleanup.json`。三者均须存在并绑定当前 SHA，不能用 Compose teardown 或空报告替代 |

## 通过条件

前端浏览器补充命令为 `npm run test:e2e -- e2e/generic-platform-acceptance.spec.ts`；新建隔离数据库执行 `py -3.14 -m alembic upgrade head`，旧 SQLite 兼容执行 `py -3.14 -m pytest tests/test_database_migrations.py -q`。最终 `final-evidence-manifest.json` 必须列出所有 19 个回执及其关联制品的 SHA-256。所有 required 测试、构建、迁移、浏览器、导出和恢复证据必须绑定当前 SHA 且为 `passed`。`failed`、`cancelled`、`skipped`、缺失或旧 SHA 证据均保持 `in_progress`。
