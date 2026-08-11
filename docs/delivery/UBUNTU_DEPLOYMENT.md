# 智擎平台 Ubuntu 24.04 部署指南

本指南面向单机 Ubuntu 24.04 LTS 的生产部署。部署结果包含 PostgreSQL、Redis、Celery Worker/Beat、MinIO、MLflow、TensorBoard Gateway、推理运行时、FastAPI 后端、前端和 Nginx 网关。

## 1. 部署边界

- 对外入口：`http://<服务器地址>/`，由 Nginx 的 `80` 端口提供。
- 本机管理入口：后端 `127.0.0.1:8000`、前端 `127.0.0.1:5173`、MinIO `127.0.0.1:9000/9001`。当前 Compose 默认不会将这些端口直接暴露到局域网或互联网。
- 持久化：PostgreSQL 使用 `postgres-data` 卷，MinIO 使用 `minio-data` 卷。不要执行 `docker compose down -v`，否则会删除业务数据和制品。
- HTTPS：仓库当前 `nginx.conf` 只启用 HTTP。若对公网提供服务，应在企业反向代理、负载均衡器或定制 Nginx 配置中终止 TLS 后再开放 `443`。

建议使用独立虚拟机或物理机，至少预留 4 vCPU、8 GB 内存和 100 GB SSD；点焊报告复现、模型训练和大规模制品留存建议提升到 8 vCPU、16 GB 内存。

## 2. 系统准备

以具有 `sudo` 权限的普通用户登录 Ubuntu，不要用 root 长期运行应用。

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git openssl

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \"${UBUNTU_CODENAME:-$VERSION_CODENAME}\") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

重新登录 SSH 会话后确认 Docker 可用：

```bash
docker version
docker compose version
docker run --rm hello-world
```

防火墙只放行运维 SSH 和平台网关。首次登录修改管理员密码前，应只允许受信任的内网或 VPN 访问平台。

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
# 配置 TLS 后再执行：sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status verbose
```

## 3. 获取代码与创建部署目录

以下示例使用 `/srv/zhinqing`。部署时固定到已验证的 Git 提交或发布标签，不要直接把未检查的工作区上传到服务器。

```bash
sudo install -d -m 0750 -o "$USER" -g "$USER" /srv/zhinqing
git clone https://github.com/FaceGg/Al-Platform.git /srv/zhinqing
cd /srv/zhinqing
git checkout main
git pull --ff-only

mkdir -p backups
chmod 700 backups
```

部署前确认以下文件存在：

```bash
test -f docker-compose.yml
test -f nginx.conf
test -f docker/postgres/init-mlflow.sql
test -f docs/delivery/ubuntu24.production.env.example
```

## 4. 配置生产环境变量

复制模板并限制其权限：

```bash
cp docs/delivery/ubuntu24.production.env.example .env
chmod 600 .env
```

模板中的 `POSTGRES_PASSWORD`、`SECRET_KEY`、`MINIO_ROOT_PASSWORD`、`TENSORBOARD_SESSION_SECRET` 和 `INFERENCE_INTERNAL_SECRET` 都必须替换。建议只使用十六进制随机值，避免 PostgreSQL URL 中出现需要转义的特殊字符。

```bash
openssl rand -hex 32
```

将生成值填入 `.env` 后，必须保持以下两组值一致：

- `POSTGRES_PASSWORD` 与 `DATABASE_URL`、`MLFLOW_BACKEND_STORE_URI` 中的 PostgreSQL 密码。
- `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` 与 `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY`。

不要把 `.env`、数据库导出、MinIO 密钥、模型或真实点焊数据提交到 Git。可选的 LLM 变量默认留空，不影响数据标注、AutoML、工作流和点焊质量感知。

## 5. 部署与启动

先让 Compose 渲染配置，缺少必填变量时会在这里失败：

```bash
cd /srv/zhinqing
docker compose --env-file .env config > /tmp/zhinqing-compose.yaml
```

构建并启动全部服务：

```bash
docker compose --env-file .env up -d --build --remove-orphans
docker compose --env-file .env ps
```

首次启动需要拉取基础镜像、安装 Python 依赖并构建前端，耗时取决于服务器网络和 CPU。`migrate` 成功退出后，后端、Worker 和调度器才会进入可用状态。

查看启动日志：

```bash
docker compose --env-file .env logs --tail=200 migrate backend worker scheduler
docker compose --env-file .env logs -f backend worker
```

## 6. 验收与首次登录

从服务器本机执行健康检查：

```bash
curl -fsS http://127.0.0.1/api/health
curl -fsS http://127.0.0.1/api/ready
curl -fsS http://127.0.0.1/health
```

预期结果：

- `/api/health` 返回 `{"status":"ok"}`。
- `/api/ready` 返回全部依赖项 `ready: true`；它会验证数据库迁移、Redis、Celery Worker、MinIO、MLflow、TensorBoard Gateway 与推理运行时。
- `/health` 返回 Nginx 网关状态。

在浏览器打开 `http://<服务器地址>/`。初始管理员凭据不得写入部署文档或工单；由部署负责人通过受控渠道交接。首次登录后立即进入“用户管理”修改管理员密码，并创建实际使用者账号。

## 7. 日常运维

### 查看状态和日志

```bash
cd /srv/zhinqing
docker compose --env-file .env ps
docker compose --env-file .env logs --tail=200 backend worker scheduler
docker compose --env-file .env logs -f backend
```

### 停止与启动

```bash
docker compose --env-file .env stop
docker compose --env-file .env start
```

需要重建容器时使用：

```bash
docker compose --env-file .env up -d --build --remove-orphans
```

不要使用 `docker compose down -v`。如确需停止并移除容器，保留卷：

```bash
docker compose --env-file .env down
docker compose --env-file .env up -d
```

### 升级

升级前先完成备份。随后拉取已审核的代码版本，再由 `migrate` 服务执行 Alembic 迁移：

```bash
cd /srv/zhinqing
git fetch origin
git checkout main
git pull --ff-only
docker compose --env-file .env up -d --build --remove-orphans
curl -fsS http://127.0.0.1/api/ready
```

若 `/api/ready` 返回 503，先检查 `migrate`、`backend`、`worker` 日志，不要在未确认备份的情况下回退数据库目录。

## 8. 备份与恢复

至少备份 PostgreSQL 逻辑数据和 MinIO 制品。建议每天定时备份，并将备份复制到独立存储。

PostgreSQL 逻辑备份：

```bash
cd /srv/zhinqing
set -a
. ./.env
set +a
timestamp=$(date +%F-%H%M%S)
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  > "backups/postgres-${timestamp}.dump"
```

MinIO 制品备份可使用临时 `mc` 容器镜像进行 `mirror`；操作前读取当前项目对应的 MinIO 用户、桶和备份目标，确认源桶为 `MINIO_BUCKET`，不要误覆盖线上桶。恢复时先停止写入服务，恢复 PostgreSQL，再恢复同一时间点的 MinIO 制品，最后启动 Compose 并检查 `/api/ready`。

## 9. 常见故障

| 现象 | 首先检查 | 处理方向 |
|---|---|---|
| `docker compose config` 提示变量缺失 | `.env` | 补齐必填变量，不要在命令行中临时写入密钥。 |
| `/api/ready` 返回 `DATABASE_SCHEMA_OUTDATED` | `migrate` 日志 | 等待或重跑迁移；确认数据库 URL 指向 Compose 内 `postgres`。 |
| `/api/ready` 返回 `CELERY_UNAVAILABLE` | `worker`、Redis 日志 | 确认 Worker 正在运行且 `CELERY_BROKER_URL`、`REDIS_EVENTS_URL` 均为 `redis://redis:6379/...`。 |
| `/api/ready` 返回 `MINIO_UNAVAILABLE` | `minio`、`minio-init` 日志 | 检查 MinIO 密钥是否一致、桶是否创建、`minio-data` 卷是否存在。 |
| 浏览器能打开页面但 API 报错 | `backend`、Nginx 日志 | 检查 `docker compose ps` 和 `curl http://127.0.0.1/api/health`。 |
| 点焊自动标注一直进行中 | `worker` 日志、任务列表 | 生产模式应由 Celery 执行；检查 Worker 与 Redis，不要重启数据库卷。 |
| 端口被占用 | `ss -ltnp` | 调整冲突服务或在 `.env` 设置仅供本机诊断的绑定地址；外部访问只使用 Nginx 入口。 |

## 10. 运行边界

- 此部署为单机 Compose 方案，不包含 Kubernetes、高可用数据库、跨机对象存储或自动 TLS 证书续期。
- 生产数据通过 PostgreSQL 与 MinIO 持久化；不要回退到 SQLite 或容器内临时路径。
- 点焊自动标注和 AutoML 是异步任务。完成状态、进度、报告与制品以平台页面和 `/api/ready`、Worker 日志为准。
- 任何升级、恢复或密钥变更都应先在隔离环境演练。
