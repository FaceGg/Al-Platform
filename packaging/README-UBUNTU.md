# Linkraft Ubuntu 安装部署

## 环境要求

- Ubuntu 22.04 或 24.04 LTS，4 vCPU，8 GB 内存，至少 40 GB 可用磁盘。
- Docker Engine 24+ 与 Docker Compose v2.24.4+（安装包的端口替换覆盖使用了 `!override` 语法）。部署用户必须能够直接运行 `docker`。
- 防火墙或云安全组需放行 TCP `5175`（主平台）和 `8443`（审核员门户）。首次构建需要能访问 Docker Hub、GHCR 以及配置的 Python 镜像源。
- 目标服务器的 Docker 守护进程必须能拉取以下精确版本的 CPUv1 MinIO 镜像，或提前以完全相同的镜像名导入。安装脚本绝不会用 `latest` 替代；若 Docker Hub 返回 `pull access denied`，请配置贵方批准的镜像仓库/加速器，或在安装前导入管理员提供的离线镜像 tar 文件。

## 安装

```bash
tar -xzf linkraft-ubuntu-20261020-r17.tar.gz
cd linkraft-ubuntu-20261020-r17
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

r8 及更早版本存在一个 PostgreSQL 专属缺陷：`generic_annotation_tasks.status` 列宽为 `VARCHAR(24)`，而回传冻结会写入 `returned_pending_acceptance`（27 字符），导致每次回传校验都失败并表现为 `409 RETURN_BATCH_NOT_READY`（操作 `error_code` 显示为乱码如 `9h9h`，这是 SQLAlchemy 内部错误码泄漏）。SQLite 不检查 VARCHAR 宽度，所以本地开发与测试环境从未暴露该问题。r9 通过 alembic 迁移 `20260926_61` 将 `status` 与 `paused_from_status` 加宽到 `VARCHAR(32)`；升级时 `migrate` 容器会自动执行。r10 起新增自愈：冻结操作失败的回传批次不再死锁，标注员可直接重新回传，旧批次会被自动标记为 `superseded`。

r11 及更早版本的审核员/标注员门户在**非 localhost 的 HTTP 访问**下无法保持登录：登录接口返回 200 但浏览器会丢弃带 `Secure` 标志的 cookie，表现为登录后立即被弹回登录页（`/portal/auth/me` 401）。r12 起 `.env` 中 `ANNOTATOR_COOKIE_SECURE=false`（安装脚本对新装和升级部署都会写入），门户会话 cookie 不再带 Secure 标志；若将来在门户前部署 HTTPS 反向代理，把该值改回 `true` 即可。

r13 起门户会话 cookie（`portal_session`/`admin_portal_session`）的 `path` 收紧为 `/portal`：cookie 按域不按端口隔离，旧版 `path=/` 的门户 cookie 会被同机主平台（5175/5173）登录请求一并带上，触发平台 cookie-CSRF 策略返回 `CSRF_TOKEN_REQUIRED`。从 r12 及更早版本升级后，既有浏览器需**一次性手动清除**旧的门户 cookie（删除该域名下 `portal_session` 与 `admin_portal_session`，或清除站点数据）；此后主平台与门户登录互不干扰。

从 r9 及更早版本升级前已 `failed` 的回传批次，若标注员门户提示无法重新回传（assignment 仍锁在 `returned_pending_acceptance`），可执行以下 SQL 解锁后再重新回传：

```bash
./packaging/compose-ubuntu.sh exec postgres psql -U ml_platform -d ml_platform \
  -c "UPDATE annotation_assignments SET state='pending' WHERE state='returned_pending_acceptance' AND id IN (SELECT assignment_id FROM annotation_return_batches WHERE state='pending');"
```

从 r4-r8 升级时，保留现有 `.env`、`secrets/` 和数据库，只覆盖源码并重建相关服务：

```bash
tar -xzf /path/to/linkraft-ubuntu-20261020-r17.tar.gz \
  --strip-components=1 -C ~/linkraft-ubuntu-20260924-r4
cd ~/linkraft-ubuntu-20260924-r4
./packaging/compose-ubuntu.sh up -d --build --force-recreate backend worker scheduler frontend annotator annotator-frontend
./packaging/compose-ubuntu.sh ps
```

从 r9-r16 升级到 r17 使用同样的流程（覆盖源码后执行上面的重建命令）。r17 相比 r12 的主要变更：

- **新增平台功能**：Kubernetes 集群管理/作业运行/Notebook 会话/镜像目录/多集群治理（Week 14-16，集群在平台内登记与连通性检查，无需为本包额外配置环境变量）、闭环演示（推理→错误数据回流→阈值告警→自动重训换模型）、编排服务图工作台、资源监控页；主平台/门户时间显示统一按 UTC 解析修复（此前 UTC+8 环境统一慢 8 小时）。
- **数据库迁移**：alembic head 由 `20260926_61` 推进到 `20261019_72`（新增 `20260928_62`–`20261019_72`，含 demo_loop、compute 心跳、developer_resources、resource_governance、工作流全局模板、编排大屏计数、闭环复核收集、特征工程方式等表）；升级时 `migrate` 容器自动执行，完成后请在 `./packaging/compose-ubuntu.sh logs migrate` 确认无错再验收业务。
- **门户 cookie path 收紧**：见上一节，升级后需一次性清除旧门户 cookie。
- **r14 修复 r13 安装脚本缺陷**：r13 的 `install-ubuntu.sh` 在校验前会把 `PUBLIC_ORIGIN` 的第一个字符误删（`http://` 变 `ttp://`），导致所有合法 origin 都被 `[ERROR] PUBLIC_ORIGIN must be an origin ...` 拒绝。r14 已修复（前导空白修剪改用纯空白前缀剥离写法）。若已解压 r13，可在其目录执行 `sed -i '133s|.*|PUBLIC_ORIGIN="${PUBLIC_ORIGIN#"${PUBLIC_ORIGIN%%[![:space:]]*}"}"|' packaging/install-ubuntu.sh` 就地修复，或直接改用 r14 安装包。
- **r15 模型运维修复与体验改进**：①删除已注册模型不再报 500——护栏只拦"活"引用（部署主版本与 stable/candidate/draft 发布目标），自动换模残留的 superseded/failed 历史目标随删除自动清理；模型库直接删除同样安全（级联清理引用版本与变空注册模型）；②发布运维抽屉修复 `INFERENCE_QUERY_INVALID`（分页参数校验缺陷）；③注册版本「来源训练模型」改为下拉选择（本项目已完成条目），不再需要手填 ID；④推理部署行新增「部署信息」查看抽屉；⑤API 市场全类型上线/下线按钮、predict 调用计入统计、响应字段解释；⑥界面默认中文与明亮主题（手动切换过的浏览器沿用其选择）。
- **r16 大数据集与稳定性修复**：①工作流节点完成载荷截断至前 20 行（修复大 CSV 运行十几分钟的根因）、节点默认超时 300→1800 秒（大 CSV 导入不再被节点超时杀死）、CSV 导出流式化 + 数据集预览截断 500 行（修复大数据集预览/下载 OOM 崩溃）；②终止按钮落库终态 + 修复跨工作流运行状态泄漏，支持活动运行恢复；③数据集下载使用原始文件名（支持中文文件名）、CSV 导出前置 UTF-8 BOM（修复 Excel 打开中文乱码）；④拧紧特征工程兼容中文注释表头、python_script venv 卷引导与 pandas 版本漂移修复；⑤闭环复核标签全输出可选与保存修复、正确数据按比例收集。
- **r17 工作台与拧紧算子增强**：①评估结果可视化预览——刷新/恢复后可查看历史节点结果，评估节点可开结果抽屉，指标中文化；②拧紧特征工程默认剔除泄漏判定列 + 缺失填充策略（单轴行保留）。

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
tar -xzf /path/to/linkraft-ubuntu-20261020-r17.tar.gz \
  --strip-components=1 -C ~/linkraft-ubuntu-20260924-r4
cd ~/linkraft-ubuntu-20260924-r4
./packaging/compose-ubuntu.sh up -d --build --force-recreate backend worker scheduler
./packaging/compose-ubuntu.sh ps backend worker scheduler
```

r8 及之后版本的 worker 会在应用 Linux 地址空间限制之前导入 ONNX/XGBoost 二进制扩展。既有模型制品无需重新训练；重建后的 `backend` 容器健康后重试注册即可。

如果 r4、r5、r6 或 r7 部署出现 MinIO 健康检查问题，请部署 r8 或更新版本，或先复制 r17 的 `packaging/docker-compose.legacy-cpu.yml`。CPUv1 服务器镜像不提供 `mc` 健康检查命令；r8 改用服务器的 HTTP 就绪端点，并把存储桶创建保留在独立的 `minio-init` mc 容器中：

```bash
./packaging/compose-ubuntu.sh up -d --force-recreate minio minio-init
./packaging/compose-ubuntu.sh up -d --remove-orphans
```

如需从当前源码树重新构建安装包，运行 `./packaging/build-package.sh 20261020-r17`。
