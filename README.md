# 灵工 Linkraft

灵工（Linkraft）是一个面向数据、模型和工作流协同开发的 Web 平台，当前核心形态是**通用 AutoML 与数据标注平台 + 大模型驱动的自动建模智能体**：用户上传数据集后，智能体可以自主完成数据画像、训练方案规划、真实训练执行、评审反思与经验沉淀，并把冠军模型一键部署为在线推理、闭环重训或应用编排服务。平台基础能力（数据、工作流、实验、推理、权限）与智能体扩展的状态和验收边界由当前开发计划统一管理。

## 当前状态

- Week 1-12 的平台基础能力（生产数据层、实验训练、调度、权限审计、推理服务化、通知、备份升级、性能与安全验收）已全部归档为 `passed` / `completed`，不属于当前实施范围。
- 通用自动建模与数据标注平台（Task 1-14）已收口：通用 AutoML、数据集版本、标注全流程（指派→回传→验收→归档）、模型导出与门户合同均按当前 SHA 验证，容量门按用户确认支持 10,000 样本。
- Week 13-16（Kubernetes 集群接入、Job/Pod 执行闭环、Notebook/镜像/GPU、多集群治理）已 `completed`；Week 17（数据探索与质量报告）已获批、保持 `planned` 待实现；Week 18-20 为 `deferred`。
- **AutoML 智能体（当前主线）**：六相位（P1-P6）实现全部完成并通过真实 DeepSeek 双域验证；S5 服务化 API 与五步向导功能面闭环；换模跟随（重训换模即生效、零重新发布）、双域服务化对照、经验受益 A/B 对照（判据①②③）均实测通过——经验注入臂 1 轮收敛 vs 对照臂多轮门禁拒绝，收敛效率约 6 倍压缩。
- **多模型加权投票集成学习**已全链落地：平台引擎终选层 soft-voting、ONNX 集成合成图可注册可上线、闭环与编排重训集成、智能体训练器与向导集成面板，真实数据全模块实测通过。
- **知识中心**（PDF/Word/Excel 解析入库、知识图谱、检索绑定、经验置信度反馈）与 **LLM 网关**（14 家供应商模板、三种 API 格式、Tokens 用量统计、重试与映射求值器）已上线；AI 对话支持多会话与上下文容量管理。
- 前端已完成 v2 全平台改版：五视图信息架构（门户 / 算法平台 / 智能体中心 / 基础设施 / 系统管理）、默认深色主题、发布级 UI 正式化；监控大屏支持智能体重训事件可视化。
- 首个正式发布：GitHub Release `20261013-r14`（安装包 + sha256 资产，全量 CI 六 job 全绿）；安装包经 r1-r15 十五轮现场迭代。
- 多模态标注集成（Label Studio 深度集成）于 2026-09-28 决策评审后**暂缓**（`deferred`，用户决定）；方案与 D2–D8 结论归档备查，表格标注保持自研门户不迁移。

完整的当前待办、依赖、风险和历史归档边界见 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)。

## 技术栈

| 层次 | 当前实现 |
| --- | --- |
| 前端 | React 18、TypeScript、Vite、Ant Design、React Flow、Zustand（v2 设计系统：双主题令牌 + 中英 i18n，字体自托管 SIL OFL 开源字体） |
| 后端 | FastAPI、Pydantic Settings、SQLAlchemy、Alembic |
| 智能体运行时 | DeepSeek / 智谱 / Kimi 等多供应商 LLM 网关接入，沙箱化脚本执行，经验库与知识库（RAG） |
| 本地开发 | SQLite、本地制品存储、本地任务执行 |
| 生产运行 | PostgreSQL、Redis/Celery、MinIO、MLflow、TensorBoard Gateway、独立推理运行时、Nginx、Kubernetes |
| 建模运行时 | scikit-learn、XGBoost、LightGBM、CatBoost、ONNX Runtime、Optuna 等，具体依赖以后端 `requirements.txt` 为准 |

## 目录说明

```text
.
|- ml-platform/
|  |- backend/                 # FastAPI、数据模型、迁移、worker、算子、后端测试
|  |- frontend/                # React 应用（v2 设计系统）、Vitest、Playwright 测试
|  |- annotator/               # 标注门户前端（自托管开源字体）
|  |- docs/                    # 架构、接口、技术方案、实施计划、操作手册和验收资料
|  |- scripts/                 # 本地启动、健康检查和停止脚本
|  `- skills/                  # 智能体技能定义
|- docker/                     # PostgreSQL 等容器初始化资源
|- docker-compose.yml          # 生产拓扑 Compose 定义
|- packaging/                  # Ubuntu 离线安装包构建与说明（r 系列）
|- DEVELOPMENT_PLAN.md         # 当前权威开发计划
|- DEVELOPMENT_PLAN_ARCHIVE.md # 历史计划归档
`- DEVELOPMENT_PLAN.history-*  # 三个时期的台账完整快照（与台账同步维护）
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

离线安装包（Ubuntu）的构建方法与现场部署说明见 `packaging/README-UBUNTU.md`。

## 文档导航

| 文档 | 用途 | 状态或适用范围 |
| --- | --- | --- |
| [当前开发计划](DEVELOPMENT_PLAN.md) | 当前未完成任务、依赖、风险和阶段状态 | 当前权威资料 |
| [历史计划归档](DEVELOPMENT_PLAN_ARCHIVE.md) | 本轮计划整理前的完整记录 | 仅供追溯，不作为当前待办 |
| [台账快照 2026-08-23](DEVELOPMENT_PLAN.history-2026-08-23.md) / [2026-09-03](DEVELOPMENT_PLAN.history-2026-09-03.md) / [2026-09-24](DEVELOPMENT_PLAN.history-2026-09-24.md) | 三个时期的台账完整快照 | 仅供追溯 |
| [大模型驱动自动建模流水线技术方案](ml-platform/docs/技术方案-大模型驱动自动建模流水线.md) | AutoML 智能体的总体设计与决策档案 | 当前主线 |
| [智能体实施计划](ml-platform/docs/superpowers/plans/2026-10-22-automl-agent.md) | 智能体六相位的进度、问题与后续 | P1-P6 已完成 |
| [智能体任务一键部署操作指南](ml-platform/docs/智能体任务一键部署操作指南.md) | 智能体任务的一键部署操作 | 操作手册 |
| [智能体任务全链 E2E 操作手册](ml-platform/docs/智能体任务全链E2E操作手册.md) | 从建模到服务化的全链演示路径 | 操作手册 |
| [闭环系统演示操作手册](ml-platform/docs/闭环系统演示操作手册.md) | 闭环自动化方案 A/B 演示 | 操作手册 |
| [通用平台技术方案](ml-platform/docs/technical-proposals/2026-09-01-general-automl-annotation-platform.md) | 通用 AutoML 与数据标注的产品、数据、接口和安全合同 | 已实现收口 |
| [Week 13-16 技术方案](ml-platform/docs/technical-proposals/2026-09-28-week13-kubernetes-foundation.md)（同目录 week14/15/16） | Kubernetes 接入、执行器、Notebook/GPU、多集群治理 | 已交付 |
| [Week 17 技术方案](ml-platform/docs/technical-proposals/2026-09-28-week17-data-exploration-quality.md) | 数据探索与质量报告的设计合同 | 已获批（planned） |
| [Label Studio 集成技术方案](ml-platform/docs/technical-proposals/2026-09-28-label-studio-integration.md) | 多模态标注引擎深度集成的设计合同与 D1–D8 决策记录 | 暂缓（deferred） |
| [通用平台验收矩阵](ml-platform/docs/acceptance/2026-09-02-general-platform-acceptance-matrix.md) | 验收编号、执行上下文和证据责任 | Task 14 收口时证据已归档 |
| [通用化迁移基线清单](ml-platform/docs/migrations/2026-09-02-genericization-inventory.md) | 去行业化范围和迁移门禁 | 已执行完毕 |
| [架构文档](ml-platform/docs/architecture.md) | 历史架构与技术选型参考 | 包含行业化历史描述 |
| [API 参考](ml-platform/docs/api_reference.md) | 既有 API 路由参考 | 以运行中的 OpenAPI 为准 |
| [用户说明](ml-platform/USAGE.md) | 历史操作与部署说明 | 包含过往版本和行业化内容 |

## 开发约定

- 修改代码、配置、测试或文档前，先阅读 [AGENTS.md](AGENTS.md)、[DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) 和共享开发经验文档。
- 保留未提交的用户改动；不要使用 `git reset --hard`、`git clean` 或破坏性 `git checkout`。
- 每项工作完成后更新当前计划、补充可复用经验，并保留历史记录；不要用计划评审、局部绿灯或旧 SHA 代替本次实现和验收。
- 所有新工作树应建立在项目目录的 `.worktrees` 下；Windows 侧命令使用 `pwsh`，Docker/Unix 命令在 WSL 中运行。
