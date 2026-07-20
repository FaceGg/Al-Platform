# 功能台账

> 基线日期：2026-07-15。状态依据源码、运行时注册表、自动化测试和构建结果，不以文件存在作为完成功能的依据。

## 规模快照

| 对象 | 数量 | 证据 |
|---|---:|---|
| 前端路由 | 23 | `frontend/src/App.tsx`：22 个页面路由和 1 个兜底路由 |
| 前端页面文件 | 26 | `frontend/src/pages/*` 文件统计，包含辅助/测试文件 |
| API 路由模块 | 25 | `backend/app/api/*.py` 文件统计 |
| FastAPI 路由 | 147 | 导入 `app.main` 后读取 `app.routes` |
| API 端点声明 | 143 | 路由装饰器静态统计，不含框架内建路由 |
| SQLAlchemy 持久化模型 | 30 | `backend/app/models/*.py` 中继承 `Base` 的类 |
| 注册算子 | 80 | 导入 `app.main` 后读取 `OperatorRegistry.list_all()`，80 个 ID 全部唯一 |
| 后端测试文件 | 46 | `backend/tests/test_*.py`；标准套件执行 46 个隔离模块 |
| 前端测试文件 | 14 | Vitest 共 35 个测试 |

算子数量以完整应用启动后的运行时注册表为准。2026-07-14 已验证 80 个算子且 ID 唯一；仅导入部分算子包不能作为平台总数口径。

## 状态定义

- **可交付**：核心路径有自动化验证，当前环境可构建。
- **功能可用**：已有前后端实现或 API 测试，但生产可靠性尚未完成。
- **原型**：可演示或内存实现，不具备持久化、隔离、扩展或安全保证。
- **受阻**：实现存在，但当前环境或外部依赖无法完成验收。
- **未实现**：仅在计划或 UI 入口中出现，没有完整运行闭环。

## 功能分类

| 领域 | 状态 | 已验证范围 | 主要缺口 |
|---|---|---|---|
| 登录、注册、基础用户管理 | 功能可用 | Auth/User API 模块测试通过 | 完整 RBAC、SSO、审计未实现 |
| 项目与工作流 CRUD | 功能可用 | CRUD、发布快照、版本恢复和运行测试通过 | 导入导出、多人协作编辑未实现 |
| ReactFlow 工作区 | 可交付 | Store 9 个测试和焊接主流程 Playwright 通过 | 并发编辑未验证 |
| DAG 执行与状态推送 | 功能可用 | Local/Celery 共用执行服务，领取锁、心跳、重复投递、取消恢复、Redis 事件及 WebSocket 测试通过 | 节点级断点续跑未实现 |
| DataBus | 功能可用 | DataFrame/JSON/二进制相关引擎和容器路径测试通过 | 大数据流式传输未实现 |
| 数据融合 Join | 功能可用 | DataFrame 空输入、复合键一次 merge 回归通过 | 大表性能、键类型校验待补 |
| 数据集上传、预览、导出 | 功能可用 | Dataset API、项目范围 Artifact、哈希和 Schema 推断测试通过 | 版本、ZIP 全入口统一、对象存储未实现 |
| 80 个注册算子 | 功能可用 | 签名、结果协议、扩展、异常评估和机理算子测试通过 | 未逐算子覆盖性能、安全和所有边界 |
| 四套焊接工业模板 | 可交付 | 真实 Fault 数据四模板后端 E2E、Artifact 向导、浏览器主流程及 Ubuntu Chromium CI 通过 | 更广泛的浏览器、性能和安全场景待后续覆盖 |
| Windows 本地部署脚本 | 可交付 | 启动、健康、登录、停止和端口释放通过 | 服务化、自动升级未实现 |
| Ubuntu 本地部署脚本 | 可交付 | Bash 语法、GitHub Ubuntu 22.04 服务冒烟、后端/前端质量门禁通过 | WSL2 本地完整启动需安装 Linux Node.js 18+ |
| 训练、AutoML、模型库 | 功能可用 | Artifact 输入、训练评估、模型保存、模型库登记和血缘 UI 测试通过 | 持久队列、检查点、实验追踪、原子完成事务和审批部署未实现 |
| 知识库、RAG、知识图谱 | 原型 | Knowledge API、向量存储测试通过 | 权限过滤、检索评估、生产向量库未实现 |
| 标注、监控、计算资源、API 市场 | 原型 | 对应 API 模块测试通过、页面可构建 | 多数为本地数据或基础 CRUD，无生产集成 |
| 智能体与应用编排 | 原型 | Orchestrator/Agent 测试通过 | 可靠队列、工具沙箱、人工审核持久化未实现 |
| Docker Compose 部署 | 可交付 | WSL2 完成生产镜像、迁移、bucket、API/Worker 和 readiness；远程 Actions 通过 | 备份恢复和升级演练在后续周次 |
| PostgreSQL/Redis/Celery/MinIO | 可交付 | Alembic、幂等数据迁移、对象往返、真实 Worker/事件/恢复和远程 4/4 生产集成通过 | 备份恢复演练在后续周次 |
| Kubernetes/Notebook/GPU 调度 | 未实现 | 计划中定义 | 无生产实现与验收用例 |

## 本次验证

- 后端：`python run_suite.py` 全量 46/46 模块通过；第五周 13/13 模块通过。
- 前端：`npm test`，14/14 文件、35/35 测试通过；测试清单和生产模块导入检查通过。
- 前端：`npm run build`，TypeScript 与 Vite 构建通过。
- 浏览器：`npx playwright test --project=chromium`，焊接主流程 1/1 通过并重复验证。
- 构建：页面已按路由拆包，首屏依赖块均低于 500 kB；ECharts 懒加载 chunk 约 1.13 MB，后续使用 `echarts/core` 继续裁剪。
- Docker：WSL2 Docker 29.6.2 / Compose 5.3.1 完成生产栈构建和 4/4 真实服务集成验证。
- 远程：[Actions Run 29548916619](https://github.com/FaceGg/Al-Platform/actions/runs/29548916619) 的 Windows/Ubuntu 质量、生产集成和 Chromium 全部成功。
- WSL2：前端 Linux 依赖安装、测试和构建已执行；后端 32/33 模块通过，本地虚拟环境缺少可选 PyTorch，深度学习算子模块待补依赖复测。
