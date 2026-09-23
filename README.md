# 灵工 Linkraft

灵工（Linkraft）是一个面向数据、模型和工作流协同开发的 Web 平台。仓库同时保留已经交付的平台基础能力，以及正在规划的通用 AutoML 与数据标注平台；两者的状态和验收边界由当前开发计划统一管理。

## 当前状态

- Week 1-12 的平台基础能力和历史验收已归档为 `passed` / `completed`，不属于当前实施范围。
- 通用自动建模与数据标注平台的 Task 1-14 均为 `planned`，尚未开始代码、迁移、测试或运行时验收。技术方案和实施计划是实现合同，不代表功能已经交付。
- Week 13-16（Kubernetes、Job/Pod、Notebook/GPU、多集群）为 `planned`；Week 17 为 `pending_decision`；Week 18-20 为 `deferred`。
- 仓库仍包含部分行业化历史实现。通用平台开发必须先完成 Task 1 的去行业化盘点和迁移边界，不能把现有页面、路由或历史文档当作通用功能已完成的证据。

完整的当前待办、依赖、风险和历史归档边界见 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)。

## 技术栈

| 层次 | 当前实现 |
| --- | --- |
| 前端 | React 18、TypeScript、Vite、Ant Design、React Flow、Zustand |
| 后端 | FastAPI、Pydantic Settings、SQLAlchemy、Alembic |
| 本地开发 | SQLite、本地制品存储、本地任务执行 |
| 生产运行 | PostgreSQL、Redis/Celery、MinIO、MLflow、TensorBoard Gateway、独立推理运行时、Nginx |
| 建模运行时 | scikit-learn、XGBoost、LightGBM、CatBoost、ONNX Runtime 等，具体依赖以后端 `requirements.txt` 为准 |

## 目录说明

```text
.
|- ml-platform/
|  |- backend/                 # FastAPI、数据模型、迁移、worker、后端测试
|  |- frontend/                # React 应用、Vitest、Playwright 测试
|  |- docs/                    # 架构、接口、技术方案、实施计划和验收资料
|  `- scripts/                 # 本地启动、健康检查和停止脚本
|- docker/                     # PostgreSQL 等容器初始化资源
|- docker-compose.yml          # 生产拓扑 Compose 定义
|- DEVELOPMENT_PLAN.md         # 当前权威开发计划
`- PLATFORM_STATUS.md          # 历史平台状态与验收摘要
```

## 本地开发

### 前置条件

- Windows 主机命令默认使用 PowerShell 7（`pwsh`）。
- Python 3.10 或更高版本。
- Node.js 18 或更高版本及 npm。
- Docker 场景使用 WSL2 中的 Docker Engine 与 Docker Compose；不要将 Docker 命令作为 Windows 宿主机流程的一部分执行。

### 安装并启动

从仓库根目录执行以下命令。后端配置文件只在不存在时从模板创建，避免覆盖本地配置。

```powershell
Set-Location .\ml-platform\backend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m pip install -r requirements.txt

Set-Location ..\frontend
npm ci

Set-Location ..
.\scripts\start.ps1
```

启动脚本会检查端口和依赖、创建 `temp_test/runtime` 日志目录，并启动以下本地地址：

- 前端：`http://127.0.0.1:5173`
- 后端健康检查：`http://127.0.0.1:8000/api/health`
- FastAPI OpenAPI 文档：`http://127.0.0.1:8000/docs`

本地模式使用 SQLite 和本地制品存储。应用启动时会初始化本地 schema 并执行兼容性补齐；生产环境则必须先通过 Alembic 迁移。

在 `ml-platform` 目录中检查或停止本地进程：

```powershell
.\scripts\health-check.ps1
.\scripts\stop.ps1
```

## 测试与构建

以下命令分别在对应目录执行。测试或构建是否通过应以本次实际输出为准，不能用历史 Run 或文档状态替代。

```powershell
# 后端隔离测试
Set-Location .\ml-platform\backend
python run_suite.py

# 前端单元测试和生产构建
Set-Location ..\frontend
npm test
npm run build

# 浏览器 E2E：配置会创建独立的 SQLite / 本地制品测试环境
npx playwright install chromium
npm run test:e2e
```

前端构建输出和 E2E 制品写入被 Git 忽略的 `temp_test` 目录。生产 Compose、备份恢复、升级、安全扫描和远程 CI 有独立的执行环境与证据要求，详见验收矩阵，不应由上述本地命令替代。

## Docker Compose

根目录的 `docker-compose.yml` 是完整生产拓扑：PostgreSQL、Redis、MinIO、MLflow、TensorBoard Gateway、推理运行时、迁移任务、后端、Worker、Scheduler、前端和 Nginx。

`ml-platform/backend/.env.example` 是本地开发模板，不能原样用于生产 Compose。运行 Compose 前，在本地且被忽略的 `.env` 中准备所有 `docker-compose.yml` 标记为必填的变量，并为 `NOTIFICATION_CRYPTO_SECRET_FILE` 提供包含通知加密密钥的本地文件。不要提交 `.env`、密钥文件或运行时制品。

在 WSL 终端切换到仓库挂载目录后执行：

```bash
./ml-platform/scripts/prepare-production-secrets.sh
docker compose config
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8001/api/ready
docker compose logs --tail=100 backend worker
docker compose down
```

`migrate` 必须成功退出，后端和 Worker 才会启动。`/api/health` 只说明 API 进程存活；生产依赖状态使用 `/api/ready` 检查。

本地可将 `MLFLOW_WHEEL_DIR` 指向 psycopg wheel 缓存目录；该目录没有 wheel 时，MLflow 服务会使用默认 PyPI 源安装依赖。

## 文档导航

| 文档 | 用途 | 状态或适用范围 |
| --- | --- | --- |
| [当前开发计划](DEVELOPMENT_PLAN.md) | 当前未完成任务、依赖、风险和阶段状态 | 当前权威资料 |
| [通用平台技术方案](ml-platform/docs/technical-proposals/2026-09-01-general-automl-annotation-platform.md) | 通用 AutoML 与数据标注的产品、数据、接口和安全合同 | 已评审；实现尚未开始 |
| [通用平台实施计划](ml-platform/docs/superpowers/plans/2026-09-02-general-automl-annotation-platform.md) | Task 1-14 的文件边界、测试和依赖 | `planned` |
| [通用平台验收矩阵](ml-platform/docs/acceptance/2026-09-02-general-platform-acceptance-matrix.md) | 验收编号、执行上下文和证据责任 | `planned` |
| [通用化迁移基线清单](ml-platform/docs/migrations/2026-09-02-genericization-inventory.md) | 去行业化范围和迁移门禁 | `planned` |
| [导出与离线运行时清单](ml-platform/docs/acceptance/2026-09-02-export-runtime-checklist.md) | 导出包与离线推理输入合同 | `planned` |
| [架构文档](ml-platform/docs/architecture.md) | 历史架构与技术选型参考 | 包含行业化历史描述 |
| [API 参考](ml-platform/docs/api_reference.md) | 既有 API 路由参考 | 以运行中的 OpenAPI 为准 |
| [用户说明](ml-platform/USAGE.md) | 历史操作与部署说明 | 包含过往版本和行业化内容 |
| [平台状态摘要](PLATFORM_STATUS.md) | 历史交付和验收记录 | 当前待办以开发计划为准 |
| [历史计划归档](DEVELOPMENT_PLAN.history-2026-09-03.md) | 本轮计划整理前的完整记录 | 仅供追溯，不作为当前待办 |

## 开发约定

- 修改代码、配置、测试或文档前，先阅读 [AGENTS.md](AGENTS.md)、[DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) 和共享开发经验文档。
- 保留未提交的用户改动；不要使用 `git reset --hard`、`git clean` 或破坏性 `git checkout`。
- 每项工作完成后更新当前计划、补充可复用经验，并保留历史记录；不要用计划评审、局部绿灯或旧 SHA 代替本次实现和验收。
- 所有新工作树应建立在项目目录的 `.worktrees` 下；Windows 侧命令使用 `pwsh`，Docker/Unix 命令在 WSL 中运行。
