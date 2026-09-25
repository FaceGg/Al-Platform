# Linkraft Ubuntu 安装部署

## 环境要求

- Ubuntu 22.04 或 24.04 LTS，4 vCPU，8 GB 内存，至少 40 GB 可用磁盘。
- Docker Engine 24+ 与 Docker Compose v2.24.4+（安装包的端口替换覆盖使用了 `!override` 语法）。部署用户必须能够直接运行 `docker`。
- 防火墙或云安全组需放行 TCP `5175`（主平台）和 `8443`（审核员门户）。首次构建需要能访问 Docker Hub、GHCR 以及配置的 Python 镜像源。
- 目标服务器的 Docker 守护进程必须能拉取以下精确版本的 CPUv1 MinIO 镜像，或提前以完全相同的镜像名导入。安装脚本绝不会用 `latest` 替代；若 Docker Hub 返回 `pull access denied`，请配置贵方批准的镜像仓库/加速器，或在安装前导入管理员提供的离线镜像 tar 文件。

## 安装

```bash
tar -xzf linkraft-ubuntu-20260926-r9.tar.gz
cd linkraft-ubuntu-20260926-r9
chmod +x packaging/*.sh ml-platform/scripts/prepare-production-secrets.sh
PUBLIC_ORIGIN=http://SERVER_PUBLIC_IP:5175 ./packaging/install-ubuntu.sh
```

安装脚本通过 `packaging/compose-ubuntu.sh` 使用 `packaging/docker-compose.legacy-cpu.yml` 完成部署。`PUBLIC_ORIGIN` 必须与浏览器打开平台时使用的完整源（origin）完全一致，不含尾部路径；该值会写入 `FRONTEND_ORIGIN` 并传入后端容器。如需放行更多精确源，请传入逗号分隔的 `PUBLIC_ORIGIN_ALIASES`，例如 `PUBLIC_ORIGIN_ALIASES=http://SERVER_PUBLIC_IP:5173,http://127.0.0.1:5173`。如果 `.env` 已存在，其中的密钥保持不变；显式传入的 `PUBLIC_ORIGIN` 只更新 CORS 源配置。

脚本会把主平台绑定到 `0.0.0.0:5175`，审核员门户暴露在 `0.0.0.0:8443`，在 `secrets/notification_master_key` 不存在时自动创建，修复绑定挂载的 `data/` 与 `uploads/` 目录属主为 UID/GID 1000，然后启动完整 Compose 栈。CPUv1 MinIO 服务器的健康检查通过 `curl` 访问其 HTTP 就绪端点；独立的 `minio-init` CPUv1 mc 容器等待 `service_healthy` 后配置别名并创建存储桶。审核员前端在镜像构建时从仓库内的 Node/Vite 源码构建，不需要宿主机预置 `dist/` 目录。生成的 `.env` 与 `secrets/` 目录包含凭据，务必妥善备份，绝不能提交到代码仓库。

安装后通过 `http://SERVER_PUBLIC_IP:5175/` 访问主平台，`http://SERVER_PUBLIC_IP:8443/` 访问审核员门户。如果启用了 UFW，请执行 `sudo ufw allow 5175/tcp` 和 `sudo ufw allow 8443/tcp`。后端端口 8000、前端端口 5173、审核员 API 端口 8444 以及 MinIO 端口 9000/9001 默认仅本机可访问。`ANNOTATOR_BIND_ADDRESS` 默认为 `0.0.0.0`；若门户只应本机访问，请在 `.env` 中改为 `127.0.0.1`。

如果部署版本早于 `FRONTEND_ORIGIN` 支持，请用精确的公网源修复现有部署并重建后端容器：

```bash
PUBLIC_ORIGIN=http://SERVER_PUBLIC_IP:5175 ./packaging/install-ubuntu.sh
./packaging/compose-ubuntu.sh up -d --force-recreate backend
./packaging/compose-ubuntu.sh up -d --force-recreate annotator annotator-frontend
./packaging/compose-ubuntu.sh restart annotator-frontend
./packaging/prepare-production-storage.sh
./packaging/compose-ubuntu.sh restart backend
```

若直接在本地 `5173` 访问前端，浏览器源必须精确为 `http://localhost:5173` 或显式配置的别名（如 `http://127.0.0.1:5173`）；`http://SERVER_PUBLIC_IP:5173` 是另一个不同的源，必须加入 `PUBLIC_ORIGIN_ALIASES`。

如需将 TCP `5173` 作为第二个公网入口，请显式绑定前端并放行端口。除非有明确理由直接暴露前端，否则请保持 `5175` 为主入口：

```bash
FRONTEND_BIND_ADDRESS=0.0.0.0 \
PUBLIC_ORIGIN=http://SERVER_PUBLIC_IP:5175 \
PUBLIC_ORIGIN_ALIASES=http://SERVER_PUBLIC_IP:5173 \
./packaging/install-ubuntu.sh
sudo ufw allow 5173/tcp
```

若想让 `5173` 成为主浏览器源，设置 `PUBLIC_ORIGIN=http://SERVER_PUBLIC_IP:5173` 并保持 `FRONTEND_BIND_ADDRESS=0.0.0.0`；未显式提供别名列表时，安装脚本会自动补上对应的 `5175` 主机别名。

## 回传验收就绪

回传批次创建后，worker 会先异步冻结并校验不可变快照。批次显示为 `pending` 不代表已经可以验收；在操作状态为 `queued` 或 `running` 时，后端会按安全契约返回 `409 RETURN_BATCH_NOT_READY`。r8 起的主平台和审核员门户会显示"回传校验中"，并在校验完成前禁用差异、验收、退回和批注操作。

回传后请在门户中点击"刷新"，确认回传操作状态为 `completed` 再验收。若持续停留在校验中，先检查 worker 和 scheduler：

```bash
./packaging/compose-ubuntu.sh ps backend worker scheduler
./packaging/compose-ubuntu.sh logs --tail=200 worker scheduler
```

r8 及更早版本存在一个 PostgreSQL 专属缺陷：`generic_annotation_tasks.status` 列宽为 `VARCHAR(24)`，而回传冻结会写入 `returned_pending_acceptance`（27 字符），导致每次回传校验都失败并表现为 `409 RETURN_BATCH_NOT_READY`（操作 `error_code` 显示为乱码如 `9h9h`，这是 SQLAlchemy 内部错误码泄漏）。SQLite 不检查 VARCHAR 宽度，所以本地开发与测试环境从未暴露该问题。r9 通过 alembic 迁移 `20260926_61` 将 `status` 与 `paused_from_status` 加宽到 `VARCHAR(32)`；升级时 `migrate` 容器会自动执行。升级前已 `failed` 的回传批次不会自动恢复，请让标注员重新执行一次回传。

从 r4-r8 升级时，保留现有 `.env`、`secrets/` 和数据库，只覆盖源码并重建相关服务：

```bash
tar -xzf /path/to/linkraft-ubuntu-20260926-r9.tar.gz \
  --strip-components=1 -C ~/linkraft-ubuntu-20260924-r4
cd ~/linkraft-ubuntu-20260924-r4
./packaging/compose-ubuntu.sh up -d --build --force-recreate backend worker scheduler frontend annotator annotator-frontend
./packaging/compose-ubuntu.sh ps
```

## CPU 兼容性

安装包将 MinIO 固定为 `minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1`，mc 固定为 `minio/mc:RELEASE.2025-07-21T05-28-08Z-cpuv1`。后端、worker、推理运行时、TensorBoard 网关、迁移和 MLflow 均使用基于 `python:3.11-slim-bookworm` 的专用 Dockerfile 而非 Wolfi，因此规避了此前的 `CPU does not support x86-64-v2` 报错。主平台前端与审核员前端构建使用基于 Debian Node 20 的专用 Dockerfile 并带 npm 重试；默认 registry 为 npmmirror。如需更换镜像源，请在安装前设置 `PIP_INDEX_URL` 和/或 `NPM_REGISTRY`。构建参数中刻意没有 `--resume-retries`，因为目标 pip 版本不接受该选项。

安装前请在目标服务器上核验精确镜像名：

```bash
docker image inspect minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1 \
  minio/mc:RELEASE.2025-07-21T05-28-08Z-cpuv1
```

如果镜像存放在批准的私有仓库，请从那里拉取并以以上两个名称打标签，或加载管理员提供的离线镜像归档。在这台旧 CPU 主机上，禁止改标签为 `latest` 或使用更新的 MinIO 版本。

## 运维操作

```bash
./packaging/compose-ubuntu.sh ps
./packaging/compose-ubuntu.sh logs -f backend worker
./packaging/compose-ubuntu.sh restart
./packaging/uninstall-ubuntu.sh
./packaging/compose-ubuntu.sh down -v  # 永久删除数据卷；仅在确认要清除数据时使用
```

重建 `annotator` 网关后需要重启 `annotator-frontend`，因为 nginx 在启动时解析上游容器地址：

```bash
./packaging/compose-ubuntu.sh restart annotator-frontend
```

修复因既有 root 属主绑定挂载导致的上传报错（无需重装）：

```bash
./packaging/prepare-production-storage.sh
./packaging/compose-ubuntu.sh restart backend
```

如果 r4、r5、r6 或 r7 部署在注册 XGBoost AutoML 结果时返回 `MODEL_CONVERSION_FAILED`，请在不替换 `.env`、`secrets/` 和数据库文件的前提下更新现有部署目录，然后重建 Python 服务：

```bash
tar -xzf /path/to/linkraft-ubuntu-20260926-r9.tar.gz \
  --strip-components=1 -C ~/linkraft-ubuntu-20260924-r4
cd ~/linkraft-ubuntu-20260924-r4
./packaging/compose-ubuntu.sh up -d --build --force-recreate backend worker scheduler
./packaging/compose-ubuntu.sh ps backend worker scheduler
```

r8 及之后版本的 worker 会在应用 Linux 地址空间限制之前导入 ONNX/XGBoost 二进制扩展。既有模型制品无需重新训练；重建后的 `backend` 容器健康后重试注册即可。

如果 r4、r5、r6 或 r7 部署出现 MinIO 健康检查问题，请部署 r8 或更新版本，或先复制 r9 的 `packaging/docker-compose.legacy-cpu.yml`。CPUv1 服务器镜像不提供 `mc` 健康检查命令；r8 改用服务器的 HTTP 就绪端点，并把存储桶创建保留在独立的 `minio-init` mc 容器中：

```bash
./packaging/compose-ubuntu.sh up -d --force-recreate minio minio-init
./packaging/compose-ubuntu.sh up -d --remove-orphans
```

如需从当前源码树重新构建安装包，运行 `./packaging/build-package.sh 20260926-r9`。
