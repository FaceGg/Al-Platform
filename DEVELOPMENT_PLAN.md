# 汽车焊接工业 AI 平台开发文档

> 文档状态：持续维护
> 最近更新：2026-07-20
> 适用项目：`E:\codex_workspace\agent_spot_welding`
> 总周期：20 周，共计 5 个月

## 1. 强制开发流程

每次开始开发前必须完成以下步骤：

1. 阅读本文件，确认当前周计划、已完成项、未完成项、已知问题和潜在风险。
2. 阅读共享经验文档：`C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`。
3. 检查工作区状态，保护用户已有修改，不覆盖、不回退无关改动。
4. 从当前周的未完成任务中选择工作，不跳过前置依赖。
5. 修改前先补充或确认验收条件；缺陷修复优先增加回归测试。
6. 开发完成后执行相关测试、构建和必要的页面验证。
7. 更新本文件中的任务状态、完成记录和未完成项。
8. 将本次出现的问题、潜在问题和处理结果追加到本文档末尾。
9. 将可复用的问题与解决方法追加到共享经验文档，并按项目分类。

禁止事项：

- 不得仅因页面、模型或 API 文件存在就将功能标记为完成。
- 不得绕过测试直接声明功能完成。
- 不得删除历史问题记录；修正信息必须追加说明。
- 不得在未确认影响范围时修改公共执行器、DataBus、认证和工作流状态机。
- 不得将本地绝对路径、密码、Token、密钥或测试账号写入正式代码。

## 2. 状态定义

| 状态 | 含义 | 完成要求 |
|---|---|---|
| 未开始 | 尚未进入开发 | 需求和验收条件可继续细化 |
| 进行中 | 已开始开发 | 存在负责人明确的当前任务和验证方式 |
| 已完成 | 已实现并验证 | 代码、测试、文档和验收结果均完成 |
| 受阻 | 因外部依赖无法推进 | 已记录阻塞条件、影响和解除方式 |
| 延后 | 当前版本不实施 | 已记录调整原因和目标版本 |

## 3. 当前项目基线

### 3.1 已完成功能

以下功能已具备可运行基础，但后续仍可能进入稳定性和生产化改造：

- React 18 + TypeScript + Vite 前端框架。
- FastAPI + SQLAlchemy 后端框架。
- JWT 登录、注册、管理员和基础用户管理。
- 项目、工作流、节点、连线和运行记录基础模型。
- ReactFlow 工作流画布、算子拖放、参数配置、保存和删除。
- NetworkX DAG 执行、基础拓扑检查、条件、循环和合并控制。
- WebSocket 工作流运行状态推送。
- DataBus 对 DataFrame、JSON 和二进制模型 Artifact（受平台管理的数据或模型文件）的基础传递。
- 80 个运行时注册且 ID 唯一的数据、处理、融合、机器学习、深度学习、评估、可视化、优化和焊接机理算子，全部使用严格执行协议。
- 数据集上传、预览、基础导出、SHA-256、Schema 推断和项目范围 Artifact 管理。
- 工作流发布快照、版本列表与恢复，节点重试、等待超时、协作取消、尝试历史、有限日志和结构化错误。
- 使用 `dataset_artifact_id` 的训练闭环，训练成功后登记模型 Artifact 和模型库血缘。
- 模型库、训练任务、知识库、知识图谱、标注、监控、API 市场、计算资源和智能体基础页面/API。
- 焊接质量预测、参数推荐、异常检测和全流程 ML 示例模板。
- 中英文切换、明暗主题和 Docker Compose 基础部署。
- 后端 API、DAG、向量存储、智能体和算子基础测试。

### 3.2 未完成功能

以下功能尚未达到稳定或生产可用状态：

- 工作流导入导出、多人协作编辑和节点级断点续跑；发布快照、版本恢复、Celery 持久任务、硬超时及失联恢复已完成。
- 数据集版本、完整生命周期和 ZIP 等历史入口统一；基础 Schema、哈希、训练血缘和对象存储 Artifact 已完成。
- 数据集版本、完整生命周期、ZIP 等历史入口统一；基础 Schema、哈希、训练血缘和对象存储 Artifact 已完成。
- 工作流导入导出、多人协作编辑、节点级断点续跑和调度优先级；发布快照、版本恢复、Celery 持久任务、硬超时、失联恢复及定时调度已完成。
- 推理服务生产化：多版本发布、滚动升级、灰度、限流、运行指标、回滚和模型卡；基础 ONNX 注册、审批、部署和在线推理已完成。
- SSO、企业消息通知及更细粒度资源权限；项目 owner/editor/operator/viewer、关键写操作审计已完成。
- Kubernetes 执行器、Notebook、镜像构建、多集群、GPU 调度和资源配额。
- SQL Lab、数据探索、多模态标注、审核和数据回流。
- 生产级 RAG、检索评估、权限过滤、LLM 网关和智能体可靠执行。
- AIHub、一键开发、一键微调和一键部署。
- 更广泛的前端 E2E、性能测试、安全测试、备份恢复和升级测试；焊接质量主流程 E2E 已完成。

## 4. 周度开发计划

> 每周均需交付：可部署代码、自动化测试结果、演示记录、遗留问题和风险更新。

| 周次 | 状态 | 工作主题 | 主要开发内容 | 周交付物 |
|---|---|---|---|---|
| 第 1 周 | 已完成 | 基线治理与范围冻结 | 已盘点页面、API、模型、算子和测试；修复前端构建与测试环境、Join 数据正确性；冻结状态、错误、数据和执行器接口 | `docs/baseline/` 功能台账、技术债清单、接口基线、构建测试基线；前后端可构建可测试 |
| 第 2 周 | 已完成 | 工作流与执行可靠性 | 已完成发布快照版本、前置运行校验、协作取消、节点超时/重试、尝试历史、有限日志、结构化错误、画布和进度状态同步 | 稳定工作流主链路、冻结状态机、后端 25 模块与前端 19 用例 |
| 第 3 周 | 已完成 | 数据、算子与训练闭环 | 已统一 79 个运行时算子协议；完成数据 Artifact、训练评估、模型保存、模型库登记和血缘展示 | 严格算子协议、数据训练闭环；后端 28/28 模块、前端 22/22 测试和生产构建通过 |
| 第 4 周 | 已完成 | 工业模板与首版交付 | 已完成真实数据准备、四套模板执行闭环、Artifact 向导、Playwright 主流程、Windows/Linux 脚本、跨平台 CI 和交付文档；GitHub Ubuntu 22.04 质量门禁与 Chromium 验收通过 | 稳定可交付版、首月验收报告 |
| 第 5 周 | 已完成 | 生产存储与异步任务 | 已完成 PostgreSQL/Alembic、Redis/Celery、MinIO、制品 URI、配置密钥、迁移工具、生产容器和真实服务验收 | 生产数据层、对象存储、异步任务框架；Actions Run 29548916619 全绿 |
| 第 6 周 | 已完成 | 实验与训练管理 | 已完成实验、Run、参数、指标、日志、制品、检查点、恢复、早停、AutoML Trial、隔离 TensorBoard、真实 Compose 集成与跨平台验收 | 企业基础版、实验训练追踪 |
| 第 7 周 | 已完成 | Pipeline 调度与权限 | 调度、角色审计、全量、WSL 生产验收与远程 CI 全部通过 | 调度器、实例管理、权限审计 |
| 第 8 周 | 已完成 | 模型注册与基础推理 | ONNX 注册中心、独立推理运行时、运维 UI、生产 Compose 与远程验收全部完成 | 模型注册中心、基础推理服务 |
| 第 9 周 | 进行中 | 推理服务生产化 | 已完成范围审计并确认多版本发布、滚动升级、回滚、API 密钥、限流、服务日志、运行指标和模型卡设计 | 生产级推理服务、版本发布回滚 |
| 第 10 周 | 进行中 | 权限、审计与通知 | 已确认复用第 7 周项目角色与审计，补齐资源越权防护、平台安全审计及站内、企业微信、邮件、通用 Webhook 通知 | 权限矩阵、审计日志、告警通知 |
| 第 11 周 | 进行中 | 系统联调与性能优化 | 工具/恢复回归、N-1 契约和隔离 WSL 生产栈已验证；固定 4 vCPU/8 GiB 性能基线和真实 N-1 升级仍待执行 | 全链路版本、性能基线、问题清单 |
| 第 12 周 | 进行中 | MLOps 核心版验收 | 安全/冻结契约/CI 清单与受控通知栈已验证；完整 Chromium、固定环境性能和最终证据清单仍待执行 | 企业 MLOps 核心版、验收报告 |
| 第 13 周 | 未开始 | Kubernetes 基础接入 | 集群、命名空间、资源组、节点发现、访问凭据和连通性检查 | 集群管理基础、资源发现 API |
| 第 14 周 | 未开始 | Kubernetes 执行器 | Job/Pod 提交、状态同步、日志、取消、超时和垃圾回收 | Kubernetes Executor 运行闭环 |
| 第 15 周 | 未开始 | Notebook、镜像与 GPU | JupyterLab、VS Code、镜像目录、在线构建、GPU 规格和节点调度 | 在线开发、镜像管理、GPU 调度 |
| 第 16 周 | 未开始 | 多集群与资源治理 | 多集群路由、存储挂载、资源配额、集群/节点/Pod/GPU 监控 | 云原生版、多集群资源管理 |
| 第 17 周 | 未开始 | 数据探索与标注 | SQL Lab、数据探索、质量报告、多模态标注、审核和数据回流 | 数据探索、标注与训练数据闭环 |
| 第 18 周 | 未开始 | RAG 与工业智能体 | 文档解析、Embedding、召回重排、引用、权限、工具调用和人工审核 | 生产级 RAG、工业智能体闭环 |
| 第 19 周 | 未开始 | LLM 网关与 AIHub | 模型路由、密钥、配额、限速、监控和统一资产目录 | LLM 网关、AIHub、一键开发部署 |
| 第 20 周 | 未开始 | 全量验收与交付 | 全链路 E2E、性能、安全、备份恢复、升级、培训和文档 | 全功能版、验收报告、交付资料 |

## 5. 当前开发队列

### 5.1 当前应优先处理

1. 按已确认设计并行推进第 9 周生产推理和第 10 周权限、审计、通知实现，Alembic 保持单一线性历史。
2. 第 11 周先行建设性能、备份恢复、升级和安全验收工具；第 12 周先行建设验收矩阵和证据清单，但最终结论等待上游接口冻结。
3. 优先修复公开注册角色提升、Compute、Annotation、API Marketplace 和成员探测顺序的现存授权缺口。
4. 持续执行跨平台 CI、生产栈和 Chromium 回归，控制已交付功能回归风险。

### 5.2 当前未完成

- 第 1 至第 8 周代码均已合并到 `main`：第 4 周 PR #1、第 5 周 PR #2、第 6 至第 8 周 PR #3。
- 第 5 周生产基础设施远程证据为 [Actions Run 29548916619](https://github.com/FaceGg/Al-Platform/actions/runs/29548916619)。
- 第 7 周远程验收证据为 [Actions Run 29667952189](https://github.com/FaceGg/Al-Platform/actions/runs/29667952189)。
- 第 8 周最终远程验收为 [Actions Run 29714469437](https://github.com/FaceGg/Al-Platform/actions/runs/29714469437)，Ubuntu、Windows、生产集成、实验集成和 Chromium acceptance 全部通过；合并提交为 `ba3ca98`。
- 第 9 至第 12 周已完成并行范围审计和设计确认，正式规格为 `docs/superpowers/specs/2026-07-20-week9-12-mlops-core-design.md`。第 9 周 Task 1-10 已完成本地实现、测试、Chromium 和验收文档；Task 11 的本地 WSL 生产栈已通过，远程 CI 和最终全量证据仍未完成。第 10 周安全/通知代码与第 11-12 周最终工具继续按依赖推进。
- 第 11 周最终性能结论依赖第 9-10 周接口、Schema 和发布行为冻结；第 12 周最终验收依赖第 9-11 周门禁通过，不得因并行启动提前标记完成。

### 2026-07-27：第 9 周 Task 10 生产栈门禁与 Chromium 验收完成

- 开发内容：补齐隔离 Compose 项目、生产推理环境变量、迁移/生产生命周期测试、Redis outage 门禁、runtime 重启/回滚测试、脱敏失败证据扫描和模型推理 Chromium 发布流程；模型注册服务在 `autoflush=False` 下显式 flush 版本后再生成 ModelCard。
- 问题现象：模型版本尚未 flush 时，模型卡服务在 SQLAlchemy `autoflush=False` 会拿不到版本 ID；前端全量测试在与 Vite build 并行执行时曾有一个 15 秒测试超时；默认 Windows `python` 别名使 Playwright webServer 以 9009 退出。
- 根因：注册服务依赖隐式 autoflush；并行构建造成本机资源竞争；WindowsApps 占位解释器不是真实 Python。
- 解决结果：两个注册路径均在 ModelCard 创建前显式 `db.flush()` 并加入回归；拆开复跑后前端恢复全绿；E2E 使用 Miniconda Python，Playwright 配置、fixture 与 CI 保留真实 interpreter 调用，不增加测试绕过。
- 验证方式：Week 8 `7/7`、Week 9 `7/7`、Task 10 focused backend `29` 项、前端 `19` 文件 `64` 项、生产构建、`compileall`、`git diff --check`、Chromium `3/3` 通过。Docker 未安装，生产 Compose integration 仍显式 skip，待远程 CI。
- 未完成：Week 9 Task 11 的远程生产栈、远程 CI、完整证据归档及最终周状态；Week 10-12 继续按冻结依赖推进。
- 预防措施：ORM 生成依赖实体主键时显式 flush；CPU 密集构建与测试分开执行；Windows E2E 文档和 CI 固定可用 Python 解释器；本地 skip 与远程生产通过必须分开记录。

### 2026-07-27：第 9 周 Task 11 本地 WSL 生产推理验收

- 开发内容：在 WSL Docker Server `29.6.2` / Compose `v5.3.1` 中以独立项目启动 PostgreSQL、Redis、MinIO、Celery、MLflow、TensorBoard gateway、inference runtime 和 backend；执行 migration head/current/check、实验集成、发布/恢复/回滚/限流生命周期、Redis outage 和 readiness。
- 问题现象：宿主 `8000` 已被现有 Week 6 栈使用；本桌面环境中分离的 WSL Compose 命令结束后会停止隔离服务，后续命令在 backend 内解析不到 `postgres`。
- 根因：端口是已有独立 Compose 项目占用；WSL/Docker 命令生命周期会终止本次隔离项目，不能把启动与真实服务验证拆成多个 shell 调用。
- 解决结果：临时将本次 backend 映射隔离到 `18000`，并在同一 WSL shell 内完成启动、迁移、所有真实服务测试、Redis/runtime 停止验证和 `down --volumes --remove-orphans`；临时 override 已删除，未影响现有 Week 6 栈。
- 验证方式：Alembic current/head 为 `20260720_09_production_inference` 且 check 无新操作；实验集成 `1/1`、推理 rollout/restart/rollback/rate-limit `1/1`、Redis fail-closed `1/1` 通过；`/api/ready` 的 database、redis、celery、storage、mlflow、tensorboard、inference_runtime 全部 ready。
- 未完成：CI 原始失败证据扫描已修复并通过 `tests.test_ci_workflow`，但远程 GitHub Actions、最终全量本地 gate、提交和合并仍未完成；第 9 周保持“进行中”。
- 预防措施：共享 Docker 主机上始终使用唯一项目名和非冲突宿主端口；在此 WSL 环境验证 Compose 生命周期时，把启动、验证和 teardown 放在同一个 shell，并仅销毁本项目 volumes；失败证据必须先扫描 raw copy，再只上传 redacted copy。

## 6. 每周验收检查表

- [x] 本周范围与验收条件已冻结。
- [x] 代码已完成审查并合并。
- [x] 单元测试、API 集成测试和相关 E2E 已通过。
- [x] 数据库、配置和接口变化已更新迁移与文档。
- [x] 测试环境能够独立部署和演示。
- [x] 日志、指标和错误信息能够支持问题定位。
- [x] 未完成项已转入下一周并记录原因。
- [x] 本周问题已追加到本文档末尾。
- [x] 可复用经验已追加到共享经验文档。

## 7. 已知风险与开发注意事项

### 7.1 已发现问题

- Pandas DataFrame 不能直接参与 `if data` 或 `if not data` 判断。
- DataBus 输入类型可能在 DataFrame、list、dict 和 bytes 之间变化。
- SQLite 和本地目录曾出现只读或权限问题，测试不得复用生产数据库。
- 导入顺序会影响算子注册表，测试必须显式完成算子注册。
- FastAPI TestClient 未使用上下文时可能不执行 lifespan，不能依赖启动钩子创建测试数据。
- ReactFlow 连线删除、节点状态和 Zustand 状态需要保持单一数据源。
- 新增 store 方法后必须同步所有调用方解构和类型定义。
- Join 多键关联必须使用左右键列表一次性 merge；复合主键回归已覆盖空输入、行数和左右键映射语义。
- i18n 对象批量编辑容易产生孤立逗号、括号错误和重复键。
- 前端页面存在硬编码英文和中文乱码风险；工作流参数标签、分类和端口预览已完成双语修复，其他原型页面仍需持续扫描。
- DOCX 自动生成必须同时检查正文、项目符号、编号、表格和分页结果。

### 7.2 可能出现的问题

- SQLite 文件持续增长、锁竞争或不同运行目录连接不同数据库。
- 本地文件绝对路径进入数据库，导致容器、测试和生产环境不可迁移。
- 进程内工作流执行在服务重启后丢失状态。
- WebSocket 建连晚于后台任务启动，导致客户端遗漏早期事件。
- 大 DataFrame 在节点间完整加载，造成内存峰值和磁盘膨胀。
- pickle/joblib 模型反序列化存在不可信制品执行风险。
- `execute_python`、表达式 `eval` 和自定义算子存在任意代码执行风险。
- 文件上传存在路径穿越、超大文件、类型伪造和恶意内容风险。
- JWT 密钥、LLM 密钥、数据库密码和镜像仓库凭据可能泄露。
- 多线程、Celery 和 WebSocket 同时更新运行状态时可能发生竞态。
- PostgreSQL、Redis、MinIO 和 Kubernetes 接入后会出现分布式一致性和补偿问题。
- GPU 驱动、CUDA、PyTorch 和容器镜像版本不匹配。
- 前端依赖缺失、缓存污染或构建工具版本差异导致本地可用但 CI 失败。

## 8. 开发问题追加记录

> 规则：只在本节末尾追加，不删除历史条目。问题解决后补充“解决结果”和“验证方式”。可复用经验还要同步到共享经验文档。

### 2026-07-12：建立持续开发文档

- 开发内容：建立项目开发计划、状态跟踪、风险和问题追加机制。
- 出现问题：此前开发计划主要存在于阶段性文档中，缺少每次开发前强制读取和持续追加入口。
- 解决结果：建立本文件，并通过项目 `AGENTS.md` 要求开发前读取。
- 验证方式：确认项目根目录存在本文件，且 `AGENTS.md` 包含读取和维护规则。
- 遗留事项：从下一次开发开始更新具体周次状态和完成记录。

## 9. 问题记录模板

### YYYY-MM-DD：问题标题

- 当前周次：第 X 周。
- 开发内容：本次计划完成的功能。
- 问题现象：可观察到的错误、日志或行为。
- 根因：经过验证的技术原因；未确认时明确写“待确认”。
- 解决方法：实施的代码、配置或流程调整。
- 验证方式：测试命令、测试用例、构建结果或页面验证。
- 影响范围：涉及的模块、数据、接口和部署环境。
- 预防措施：后续如何避免重复发生。
- 遗留事项：仍未解决或需要继续观察的内容。

### 2026-07-12：第一周基线治理与构建恢复

- 当前周次：第 1 周。
- 开发内容：完成页面、API、模型、算子和测试盘点；冻结运行状态、API 错误、DataBus、算子与执行器接口；恢复前端测试和生产构建；修复 Join 数据正确性。
- 问题现象：前端找不到 Vitest 和 Testing Library；TypeScript 报 i18n 键及 `useI18n` 缺失；Ant Design 测试依赖浏览器 `matchMedia`；Join 对空 DataFrame 抛布尔歧义异常并错误地逐键重复 merge。
- 根因：前端依赖目录安装不完整；中英文翻译对象结构不对称且页面缺少导入；jsdom 不提供 `matchMedia`；Join 混用了容器隐式布尔判断并误解复合键语义。
- 解决方法：按 lockfile 安装依赖；补齐同构翻译键和导入；在测试环境提供 `matchMedia`；增加两个失败回归测试后改为显式判空和一次性数组键 merge。
- 验证方式：后端 `python run_suite.py` 23/23 模块通过；Join 2/2 回归通过；前端 `npm test` 13/13 通过；`npm run build` 通过。
- 影响范围：前端构建与组件测试、API 客户端、国际化类型、数据融合 Join、第一周交付文档。
- 预防措施：CI 使用锁文件确定性安装；翻译键保持语言对象同构；组件测试集中维护浏览器 API mock；关系运算必须用代表标准语义的数据集回归。
- 遗留事项：当前机器没有 Docker，Compose 配置和镜像构建未执行；React 测试仍有 `act` 告警；前端产物存在 2.6 MB 大包告警；24 个后端测试文件中标准 runner 固定执行 23 个，需继续统一入口。

### 2026-07-12：功能数量口径纠正

- 当前周次：第 1 周。
- 开发内容：建立可重复统计的功能规模基线。
- 问题现象：历史计划写有 79 个算子，当前源码仅统计到 76 个 `@register_operator`。
- 根因：历史功能清单未与注册源码建立自动校验，增删算子后文档发生漂移。
- 解决方法：功能台账以当前源码静态统计 76 个为基线，并保留历史差异说明。
- 后续更正（2026-07-13）：静态装饰器计数遗漏了运行时注册入口；以 `OperatorRegistry.list_all()` 复核后确认 79 个算子且 ID 全部唯一。当前功能台账和周计划均采用 79 个运行时算子口径。
- 验证方式：使用 ripgrep 统计 `backend/app/operators/*.py` 的注册装饰器数量。
- 影响范围：算子目录、验收口径和后续测试覆盖率。
- 预防措施：将算子数量与唯一 ID 检查纳入注册表测试，文档引用测试生成的数量。
- 遗留事项：需在第 3 周逐一核对历史缺失的 3 个算子是删除、重命名还是遗漏注册。

### 2026-07-12：第二周工作流可靠性

- 当前周次：第 2 周。
- 开发内容：实现工作流发布快照、版本列表/详情/恢复、运行前置校验、协作取消、节点超时和重试、attempt 历史、结构化错误与日志、前端完整状态和断线恢复。
- 问题现象：原停止按钮仅关闭 WebSocket 并重置本地状态，后台仍继续执行；`create_all` 无法升级旧 SQLite 表；无事件循环时广播会创建未等待协程；复合重试完成事件丢失实际 attempt。
- 根因：运行控制和 UI 状态未通过持久 API 连接；SQLAlchemy `create_all` 只建缺失表不补列；广播在验证 loop 前构造协程；执行策略只返回 outputs 未返回成功尝试号。
- 解决方法：新增 RunControl 和冻结状态机；增加取消 API 与数据库检查；实现 SQLite 幂等兼容迁移；广播前检查 loop；策略返回 outputs 与 attempt；前端停止改为调用取消 API并在断线后查询详情。
- 验证方式：后端标准 runner 25/25 模块通过；前端 Vitest 5/5 文件、19/19 测试通过；TypeScript/Vite 构建通过。
- 影响范围：工作流模型、版本、运行 API、DAGExecutor、WebSocket、SQLite 升级、工作区 store、进度和节点状态。
- 预防措施：状态转换集中定义；每次重试独立持久化；协程只在有效 loop 下创建；数据库字段变化必须有迁移测试；WebSocket 不作为状态事实来源。
- 遗留事项：线程超时无法强制终止底层 Python 调用；固定 0.5 秒 WebSocket 等待尚未移除；Playwright 浏览器 E2E 未配置；React `act` 和前端大包告警仍存在。

### 2026-07-13：默认管理员登录返回 422

- 当前周次：第 2 周缺陷回归。
- 开发内容：修复默认管理员账号无法从登录页面提交的问题。
- 问题现象：页面输入 `admin` 和正确密码仍提示用户名或密码错误；后端日志显示登录请求返回 422，而相同凭据通过标准表单请求可返回 200。
- 根因：Axios 客户端全局声明 `Content-Type: application/json`，登录页传入 `URLSearchParams` 时该默认头未被覆盖，FastAPI `OAuth2PasswordRequestForm` 无法解析请求体。
- 解决方法：新增认证 API 适配层，登录请求显式使用 `application/x-www-form-urlencoded`；登录页不再自行拼装请求。
- 验证方式：认证适配层测试验证 URL、URLSearchParams 和 Content-Type；前端生产构建通过；通过 Vite 代理向后端提交标准表单返回 200。
- 影响范围：登录页面、Axios 请求头和 OAuth2 表单接口。
- 预防措施：全局默认请求头不能覆盖端点特定媒体类型；文件上传、表单和 JSON 请求必须各自提供契约测试。
- 遗留事项：登录页目前仍将所有异常统一显示为“用户名或密码错误”，后续可区分网络、422 和 401 错误。

## 2026-07-13 第三周开发追加记录

### 状态

第三周“数据、算子与训练闭环”计划已完成，周度计划表与本详细记录状态一致。

### 已完成

- 79 个运行时注册算子统一采用 `execute(context, inputs, params) -> OperatorResult`，并加入签名、裸字典返回和执行器旧调用扫描测试。
- DAG 在每次尝试中创建上下文，统一参数、结果、指标和日志校验；循环及循环体迁移到相同入口。
- 建立项目隔离的 `ArtifactService`，数据集上传返回 Artifact ID、SHA-256、Schema 和行列统计。
- 训练请求强制使用 `dataset_artifact_id`，成功后生成模型 Artifact 及模型库记录，并在任务详情展示完整血缘。
- 训练页面支持选择项目、数据 Artifact、目标列和算法，并查看 Artifact、模型库、Schema、指标、日志和错误。
- 验证：后端 `python run_suite.py` 为 28/28 模块通过；前端 `npm test` 为 22/22 通过；`npm run build` 成功。

### 未完成及后续安排

- 数据集 ZIP/部分历史批量入口统一迁移到 `ArtifactService`，安排到 Week 5 生产存储改造。
- 模型制品、模型库和训练任务完成状态的真正原子事务，安排到 Week 5 数据层改造。
- DAG 自动持久化 `OperatorResult.artifacts`，作为 Week 5 对象存储接口的一部分实现。
- 浏览器 E2E 焊接数据训练演示、测试环境告警清理和前端路由拆包纳入 Week 4 验收工作。

### 本次问题与风险追加

- 问题：循环执行路径仍保留两参数旧协议调用。根因是主 DAG 迁移时遗漏私有循环分支；已通过 AST 回归测试和统一策略入口修复。
- 问题：`BaseOperator` 非 dataclass 却使用 `dataclasses.field`，导致无参数算子校验报 `Field object is not iterable`；已修正并由可靠性测试覆盖。
- 风险：训练闭环当前依赖本地线程和本地制品目录，进程重启、跨实例运行和硬取消能力仍不足，Week 5 必须迁移到持久任务与对象存储。

## 2026-07-13 项目完成状态审计记录

- 已核对：前端路由/页面、FastAPI 路由、SQLAlchemy 模型、运行时算子、后端测试模块和前端测试文件。
- 已修正：第三周周表状态、79 个算子口径、工作流可靠性完成范围、Artifact 训练闭环和最新测试数量。
- 验证结果：后端 28/28 隔离模块通过；前端 7/7 文件、22/22 测试通过；生产构建通过。
- 发现问题：`FEATURE_INVENTORY.md`、`BUILD_AND_TEST.md` 和 `PLATFORM_STATUS.md` 长期保留旧数量及旧能力结论。
- 处理结果：功能台账和构建基线已更新；平台总览新增当前审计章节，历史内容保留供追溯。
- 潜在风险：统计仍依赖人工执行命令，后续应在 CI 中生成机器可读状态快照并由文档引用。

## 2026-07-14 第四周开发暂停记录

### 当前状态

- 第四周状态：进行中，已保存当前工作区，未提交 Git。
- 暂停原因：用户要求保存当前开发进度并暂停开发。
- 恢复入口：先重新读取本文件和共享经验文档，然后从“完整回归与交付文档”继续。

### 已完成

- 真实焊接数据准备：校验四个源 CSV，提取电流、电压、压力统计特征，生成 1,976 行、43 列的 `weld_fault_features.csv`，分类目标为 `Fault`。
- 工业模板契约：建立四套声明式模板 `weld_quality`、`fault_parameter_analysis`、`anomaly_detection`、`full_ml_comparison`，完成算子、参数、端口、输入和输出校验。
- 分类与异常能力：支持分层划分、类别权重、`scale_pos_weight`、异常列排除和 `anomaly_eval`。
- Artifact 实例化：四套工业模板使用 `project_id`、`dataset_artifact_id` 和语义参数 JSON，一次事务创建工作流、节点和边。
- 后端真实闭环：四套模板 E2E 连续两次通过；修复 SQLite 时间字段时区不一致导致 `NodeRun` 终态回滚的问题。
- 前端模板向导：新增强类型模板 API，支持已有/新建项目、项目内数据集 Artifact、模板元数据和语义参数，不再暴露服务器路径。
- 浏览器主流程：Playwright Chromium 已真实通过登录、创建项目、上传 316 行固定焊接数据、实例化模板、运行六个节点、确认终态和读取 metrics，单次结果 1/1 通过。
- 双平台交付基础：新增 Windows/Linux start、health-check、stop 脚本；Windows 已验证启动、健康检查、默认管理员登录和端口释放；Git Bash 位于 `D:\software\Git`，三个 Bash 脚本已通过 `bash -n`。
- CI 配置：替换未配置的 pytest、ESLint、Codecov 和强制 Docker，改为 Windows/Ubuntu 后端 runner、前端测试、构建、健康检查及 Ubuntu Playwright；YAML 本地解析通过。

### 本轮验证证据

- `python -m unittest tests.test_api_runs.TestRunsAPI -v`：3/3 通过。
- `python -m unittest tests.test_industrial_template_e2e -v`：四模板真实执行测试连续两次通过。
- `python -m unittest tests.test_api_datasets -v`：9/9 通过。
- `npm test -- --run src/api/templates.test.ts src/pages/TemplateWizardPage.test.tsx`：4/4 通过。
- `npm run build`：成功，存在约 2.62 MB 主包告警。
- `npx playwright test e2e/weld-quality.spec.ts --project=chromium`：1/1 通过，约 9.4 秒。
- Windows 脚本：健康接口 `ok`、前端 HTTP 200、默认管理员登录成功、停止后 8000/5173 端口释放。
- `D:\software\Git\bin\bash.exe -n`：三个 Bash 脚本语法通过。

### 本次问题、根因与解决结果

- 节点终态未持久化：SQLite 返回无时区 `started_at`，与带 UTC 的 `finished_at` 相减抛异常且回调回滚；统一按 UTC 计算耗时后修复。
- 运行详情缺少 metrics：数据库有 `NodeRun.result`，但响应 schema 未声明，Pydantic 静默过滤；补充 `result` 后查询与 WebSocket 契约一致。
- 项目内数据集无法列出：前端依赖的 GET 接口不存在；新增所有权校验的数据集 Artifact 列表接口且不暴露 `storage_path`。
- Windows 健康检查误判：接口实际返回 `status=ok`，脚本只接受 `healthy`；现兼容两种值。
- Windows 停止遗留 Vite：停止 `npm.cmd` 父进程不会自动清理 `node/esbuild`；改为递归终止进程树并处理子进程自然退出竞态。
- PowerShell 调用提前结束：被调用的健康脚本使用 `exit 0` 终止整个宿主；改为 `return`。
- Playwright 可访问定位失败：项目名称使用无 `href` 的视觉链接；改为 React Router `Link`。

### 未完成与恢复顺序

1. 重新执行完整后端 `python run_suite.py`，本轮命令因用户要求暂停而主动终止。
2. 执行全部前端 `npm test`、`npm run build`，并再次运行 Playwright 证明重复稳定性。
3. 再次执行最新 Windows start-health-login-stop 连续验收；当前各阶段已分别通过。
4. 将分支推送后运行 Windows/Ubuntu GitHub Actions；真实 Ubuntu CI 成功前不得标记第四周完成。
5. 创建 Windows/Ubuntu 部署、用户、演示和第四周验收文档，并同步功能台账、构建基线、平台状态和使用说明。
6. 清理本轮生成的 Playwright 数据库、Artifact、测试结果和运行日志前，先确认不覆盖用户历史文件。

## 2026-07-14 第四周本地验收完成记录

### 已完成

- 创建 Windows、Ubuntu 部署说明、用户手册、焊接演示指南和第四周验收记录。
- 同步更新使用说明、功能台账、构建测试基线、接口基线、技术债和平台状态总览。
- 完整应用运行时算子重新统计为 80 个，ID 全部唯一；新增算子为 `anomaly_eval`。
- 后端标准 runner 扩展到 31 个隔离模块，并纳入数据准备、工业模板契约和四模板真实 E2E。
- GitHub Actions 配置为 Windows/Ubuntu 质量矩阵及 Ubuntu Chromium 验收，不依赖项目密钥。

### 最新验证

- 后端 `python run_suite.py`：31/31 模块通过，最新约 199.1 秒。
- 前端 `npm test`：9/9 文件、26/26 测试通过，约 10.2 秒。
- 前端 `npm run build`：成功，JS 2,621.11 kB、gzip 846.97 kB。
- Playwright `npx playwright test --project=chromium`：1/1 通过，用例约 7.7 秒；主流程已重复验证。
- Windows：启动、健康检查、默认管理员登录、停止、PID 清理和 8000/5173 端口释放通过。
- Git Bash：`start.sh`、`health-check.sh`、`stop.sh` 语法通过。
- CI YAML：本地解析成功，包含 `quality` 和 `browser-acceptance`。

### 当前结论

- 本地第四周功能、测试、Windows 部署和文档已达到验收条件。
- 工作区尚未提交或推送，无法取得真实 Ubuntu GitHub Actions 证据。
- 根据既定验收规则，第四周仍标记为“进行中”；真实 Ubuntu `quality` 和 `browser-acceptance` 成功后方可改为“已完成”。

## 2026-07-14 项目文件清理记录

- 开发内容：重新梳理项目目录，删除一次性修复脚本、旧测试旁路和可再生生成物，建立文件准入规则。
- 问题现象：项目根目录、后端根目录和旧 `ml-platform/tests` 中混有 `_fix`、`_write`、`append`、手工验证脚本、测试数据库、日志和重复测试入口；运行数据目录持续出现在 Git 状态中。
- 根因：前四周开发过程中多次使用一次性脚本直接修复文件，旧测试未随标准 runner 建立而退出，Artifact 测试使用临时数据库但共享本地存储目录。
- 解决方法：依据引用搜索和正式入口清单删除 47 个已审计旧目标；清理 21 个生成目录和 20 个生成文件；只读查询三个 SQLite 数据库后删除 59 个无引用 Artifact 目录；完善 `.gitignore` 和 `FILE_STRUCTURE.md`。
- 保留范围：所有 DOCX、正式文档、演示数据、三个 `ml_platform.db`、上传、导出和数据库仍引用的 Artifact。
- 验证方式：后端 `python run_suite.py` 31/31 模块通过；前端 `npm test` 9/9 文件、26/26 用例通过；`npm run build` 成功；Playwright Chromium 主流程 1/1 通过；Git Bash 对 `start.sh`、`health-check.sh`、`stop.sh` 的语法检查通过；验证后再次删除构建和浏览器测试生成物。
- 预防措施：后端测试只放 `backend/tests`，浏览器测试只放 `frontend/e2e`；可复用脚本放 `backend/tools`；用户数据清理前必须检查数据库引用。
- 遗留事项：工作区正式源码和文档尚未提交；`docs2` 为用户 Word 资料目录，未自动移动或删除。

### 2026-07-14：统一项目临时文件目录

- 当前周次：第 4 周。
- 开发内容：创建项目根目录 `temp_test`，统一开发、测试、构建和本地运行产生的临时文件位置。
- 问题现象：DataBus、启动脚本、测试 runner、Playwright 和前端构建分别在工作目录、系统临时目录及模块目录生成临时文件，清理和定位困难。
- 根因：各工具使用自身默认输出目录，项目没有统一临时目录环境变量和准入规则。
- 解决方法：新增 `temp_test`；DataBus 使用 `temp_test/data`；测试 runner 使用 `temp_test/test-suite`；启动日志使用 `temp_test/runtime`；Playwright 数据和报告、前端构建输出均写入 `temp_test`；更新 `.gitignore`、CI 和目录文档。
- 验证方式：后端 31/31 模块通过且数据库路径位于 `temp_test/test-suite`；前端 9/9 文件、26/26 用例通过；生产构建输出位于 `temp_test/frontend-dist`；Playwright Chromium 1/1 通过；Windows/Linux 脚本语法检查通过；旧临时路径核对为空。
- 预防措施：新增项目临时输出必须优先使用 `ML_PLATFORM_TEMP_DIR` 或 `temp_test` 子目录；不得在源码目录新增临时数据库、日志、报告和构建目录。
- 遗留事项：系统库内部创建并自动回收的短生命周期临时文件仍由操作系统管理，不作为项目持久临时文件保留。

### 2026-07-15：第四周 Ubuntu 验收完成

- 当前周次：第 4 周。
- 开发内容：完成第四周剩余的真实 Ubuntu CI 验收，并使用 WSL2 补充本地 Linux 环境检查。
- 问题现象：此前只有 Git Bash 语法检查，缺少真实 Ubuntu 后端、前端、服务启停和浏览器验收证据，因此第四周不能标记完成。
- 根因：交付分支尚未推送运行 CI；早期 CI 还遇到 `requests` 依赖缺失、失败 traceback 截断、可选 PyTorch 未安装和浏览器运行目录不存在。
- 解决方法：完善依赖与 CI 诊断，安装 CPU PyTorch，准备浏览器运行目录；在 PR #1 上运行 Windows/Ubuntu 质量矩阵和 Ubuntu Chromium 验收。WSL2 Ubuntu 额外完成 Bash 语法与项目文件检查。
- 验证方式：[GitHub Actions Run 29381233328](https://github.com/FaceGg/Al-Platform/actions/runs/29381233328) 中 `Quality (windows-latest)`、`Quality (ubuntu-22.04)`、`Chromium acceptance (Ubuntu)` 三项全部成功；PR #1 检查全绿且可合并。WSL2 内核为 `6.18.33.2-microsoft-standard-WSL2`，三个 Shell 脚本通过 `bash -n`。
- 影响范围：第四周验收状态、Windows/Linux 交付路径、CI、功能台账和交付文档。
- 预防措施：跨平台交付必须记录真实 Actions Run URL 和 job 结果；本地 WSL 只能作为补充，不替代干净 Ubuntu CI。
- 遗留事项：PR #1 仍为 Draft 且尚未合并；WSL2 已安装 Node.js 22/npm，但系统 Python 为 3.14，与 CI 的 Python 3.11 不一致，完整本地启动需使用 Python 3.11 虚拟环境；GitHub action 已在本地升级到支持 Node.js 24 的版本，待推送后取得新一轮远程证据。
- 2026-07-15 CI 记录：Windows/Ubuntu Actions 中 26 个导入 app.main 的测试在收集阶段失败，5 个独立模块通过。run_suite.py 原先只输出 stderr 前 5 行，隐藏了 unittest traceback；已改为输出完整 stderr。当前根因仍待 CI 新日志确认，不据此猜测业务修复。
- 2026-07-15 CI 修复：完整 traceback 确认 `app/engine/orchestrator.py` 导入 `requests`，但后端 requirements 未声明，导致两平台导入阶段失败。已补充 `requests==2.32.*`，需通过本地完整回归和远程 Windows/Ubuntu/Chromium 检查后再关闭该问题。
- 2026-07-15 CI 后续问题：补充 `requests` 后，远程 CI 已从 26 个导入失败收敛为 1 个模块失败；Ubuntu 中 `test_operators_extended` 的 4 个断言失败，原因是未安装可选 PyTorch 时 `dl_operators.py` 不注册 `mlp_classifier`、`mlp_regressor` 和 `cnn1d_classifier`。尝试增加 scikit-learn CPU 回退注册，但代码插入位置与原 PyTorch 类定义边界冲突，当前本地修复草稿出现重复类/注册和抽象类未实现 `validate` 问题，尚未完成，已按要求暂停。恢复时应先清理 `dl_operators.py` 的重复定义，明确 `TORCH_AVAILABLE` 分支，并为回退类实现完整 `validate` 与测试。
- 2026-07-15 CI 修复更新：已清理并恢复 `dl_operators.py` 到提交基线，放弃未充分验证的源码回退实现；改为在 Windows/Ubuntu 质量任务和 Chromium 验收任务中显式安装 CPU 版 PyTorch。生产 `requirements.txt` 保持轻量，应用源码仍使用原始 PyTorch 算子实现。待本地回归及远程 CI 全部通过后关闭该问题。
- 2026-07-15 Chromium CI 问题：Windows/Ubuntu 质量任务通过后，Chromium webServer 启动失败，FastAPI lifespan 报 SQLite `unable to open database file`。根因是 Playwright 配置只给后端进程设置了数据库环境变量，而 CI 浏览器任务未为测试命令设置对应运行目录变量，应用启动时仍读取默认数据库路径。已在 Chromium 步骤显式设置 `DATABASE_URL`、`ARTIFACT_STORAGE_DIR` 和 `ML_PLATFORM_TEMP_DIR` 到 `temp_test`，待远程 Chromium 重跑验证。

### 2026-07-15：已知前端缺陷与维护项清理

- 当前周次：第四周完成后的缺陷清理。
- 开发内容：修复工作流算子配置和端口预览未汉化、测试环境告警、首屏单包过大及 GitHub action 运行时弃用告警；补充 WSL2 本地依赖检查。
- 问题现象：Join/Pivot/Aggregate/Sort 参数标签和端口预览显示英文；`blending`、`utility` 分类显示内部 ID；Vitest 输出 Router future、React `act` 和 jsdom `getComputedStyle` 告警；所有页面同步导入导致入口包约 2.62 MB；GitHub action 使用旧 Node.js 20 运行时。
- 根因：参数标签和预览文本未接入语言状态；测试环境缺少浏览器 API 兼容层及 Router future 配置；`App.tsx` 同步导入全部页面；CI action 主版本未升级。
- 解决方法：增加双语参数标签和端口预览格式、补齐算子分类；增加 4 个回归测试；统一测试环境 `getComputedStyle` 行为并启用 Router future flags；22 个页面改为 `React.lazy` 路由加载；升级 `checkout@v5`、`setup-node@v5`、`setup-python@v6`。
- 验证方式：参数标签和预览测试先失败后通过；前端 11/11 文件、30/30 用例通过且不再输出三类测试告警；生产构建成功，首屏依赖块均低于 500 kB；Playwright Chromium 1/1 通过；CI YAML 解析通过且旧 action 版本搜索为空。
- 影响范围：工作流编辑器、国际化、前端测试环境、路由加载、生产构建和 GitHub Actions。
- 预防措施：新增工作流可见文本必须提供中英文；测试环境 API mock 集中维护；新页面默认路由懒加载；每季度检查 action 运行时弃用公告。
- 遗留事项：ECharts 懒加载 chunk 约 1.13 MB，虽不进入首屏仍需后续改用 `echarts/core` 按图表类型注册；WSL2 Python 3.14 安装科学计算依赖耗时异常，建议使用与 CI 一致的 Python 3.11。
- 后续安全修复：`npm audit` 确认旧 Vite 5、Vitest 2 和 ECharts 5 存在 6 个公开漏洞；已升级到 Vite 8.1.4、Vitest 4.1.10、ECharts 6.1.0 和 plugin-react 6.0.3，使用 npm 官方 registry 复查为 0 漏洞。升级后的 30/30 测试、构建和 Playwright 1/1 通过。
- WSL2 验收更新：用户已安装 Node.js/npm 和 `/home/jingms/venv` 后端依赖；为避免复用 Windows 原生依赖，`start.sh` 新增 `ML_PLATFORM_FRONTEND_DIR`，指向 `temp_test/wsl-frontend` 的 Linux npm 依赖。WSL2 启动、两次健康检查、默认管理员登录、停止及 8000/5173 端口释放全部通过。
- 浏览器兼容更新：真实 BrowserRouter 已启用 future flags，主流程页面改用 Ant Design `App.useApp()` 消息上下文，Card `bodyStyle` 已迁移为 `styles.body`。最新 Playwright 主流程通过；仍观察到一次无功能影响的 ResizeObserver 通知循环，后续若可稳定复现再增加针对性处理。
- XGBoost 告警修复：回归测试先确认 `XGBoostTrainer` 仍传入已移除的 `use_label_encoder` 参数，再删除该参数；聚焦测试通过。该参数不再出现在后端源码中。

### 2026-07-15：第一至第四周全模块测试体系

- 当前周次：第四周完成后的全量回归与测试治理。
- 开发内容：按第一至第四周重组后端和前端测试清单，增加全应用模块导入检查、测试归属自检、工作区端口映射回归，并提供后端 `--week` 分组入口。
- 问题现象：原标准入口只有扁平模块列表，无法证明四周任务分别被覆盖；新增前端清单测试首次运行时，Vite glob 不包含当前清单测试文件自身。
- 根因：测试与周计划缺少机器可校验的映射；`import.meta.glob` 在当前测试模块中不会返回该模块自身。
- 解决方法：新增后端 `WEEK_TEST_MODULES` 和前端周次映射，自动比较磁盘发现结果；前端清单显式补入自身路径；每个后端模块继续使用独立数据库、Artifact 和临时目录。
- 验证方式：Windows 后端第一至第四周分别 16/16、7/7、7/7、3/3，通过统一入口复核为 33/33；前端 14/14 文件、35/35 测试、生产构建、npm audit 0 漏洞和 Playwright Chromium 1/1 通过。
- 跨平台结果：WSL2 前端独立 Linux 依赖已安装，单元测试后进入并完成生产构建；后端 32/33 模块通过，`test_operators_extended` 因 `/home/jingms/venv` 未安装可选 PyTorch 而缺少三个深度学习算子注册。该问题与既有 CI 前置依赖结论一致，不修改业务代码或跳过断言。
- 预防措施：新增测试必须在周次清单中唯一归属；新增生产模块必须通过全模块导入；完整算子验收环境必须显式安装 PyTorch CPU；Linux 前端依赖不得复用 Windows `node_modules`。
- 未完成：在 WSL2 执行 `/home/jingms/venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu` 后，重跑第三周或全量后端测试，取得本地 33/33 证据。

### 2026-07-15：第五周生产存储与异步任务设计确认

- 当前周次：第 5 周，状态调整为进行中。
- 已确认方案：保留 SQLite、本地文件和线程执行作为本地回退；生产模式使用 PostgreSQL/Alembic、Redis/Celery 和 MinIO，并以适配器隔离业务代码。
- 已确认验收：生产集成使用 GitHub Actions Ubuntu 服务容器；Celery 本周只迁移工作流运行；MinIO 对新制品使用 URI 并提供历史迁移命令；密钥使用环境变量或 Secret 文件。
- 设计文档：`docs/superpowers/specs/2026-07-15-week5-production-storage-async-tasks-design.md`。
- 实施计划：`docs/superpowers/plans/2026-07-15-week5-production-storage-async-tasks.md`，共 13 个任务，按配置、数据库、存储、队列、事件、集成测试和交付验收顺序执行。
- 风险控制：生产 Schema 只允许 Alembic 修改；Worker 事件通过 Redis 转发；数据库和对象存储迁移必须可重复执行并完成数量、大小与哈希校验；不得通过降低断言规避真实基础设施测试。
- 未完成：书面规范审阅、详细实施计划、代码实现、自动化测试、生产集成 CI 和交付文档。

### 2026-07-15：第五周开发暂停记录

- 暂停原因：用户要求保存当前开发进度并暂停开发。
- 已完成：第五周设计规范和 13 项实施计划已经用户确认并完成自审；实施任务 1 已完成配置模型、Secret 文件读取、生产模式校验、第五周测试清单和 `.env.example` 的代码修改。
- 任务 1 安全修复：JWT 密钥保持 `SecretStr`，只在认证签发/解析边界读取明文；生产 PostgreSQL URL 使用 SQLAlchemy 解析并校验 host/database；空 MinIO bucket 被拒绝；配置摘要移除 URL userinfo、query 和 fragment；敏感字段从标准序列化排除。
- 当前验证证据：开始实现前后端标准 runner 为 33/33；任务 1 实现代理最后报告 `tests.test_config tests.test_suite_manifest tests.test_app tests.test_api_users` 共 34/34 通过，`git diff --check` 通过。用户暂停后未由主流程再次独立运行测试。
- 审查状态：任务 1 初次规范审查已通过；初次代码质量审查发现五项安全问题，修复已写入工作区，但修复后的最终代码质量复审尚未执行，因此任务 1 仍保持进行中，不标记完成。
- 未开始：实施计划任务 2 至任务 13，包括 Alembic/PostgreSQL、SQLite 数据迁移、Local/MinIO 存储、Artifact 调用点迁移、Celery、Redis 事件桥接、readiness、真实生产集成 CI、容器与交付文档。
- 恢复顺序：先运行任务 1 的 34 项聚焦测试并执行代码质量复审；复审通过后更新任务状态，再从任务 2 的失败测试开始实施。
- 工作区状态：所有修改只保存在当前工作区，未创建提交、未推送；所有子代理和测试进程均已停止。
- 保护事项：根目录删除项、Word 文档、`docs2` 和 `docs/build_project_brief.py` 属于用户原有修改，恢复开发时不得回退或覆盖。

### 2026-07-16：第五周任务 1 完成

- 开发内容：完成双模式 Settings、Secret 文件解析、生产配置校验、配置脱敏、第五周测试清单和 `.env.example`。
- 安全修复：Pydantic 默认 `ValidationError.errors()/json()` 的输入统一替换为 `[redacted]`；JWT 维持纯 `SecretStr` 并只在认证边界取值；原始数据库、MinIO 和 LLM URL 不进入 repr/model_dump，安全摘要移除 userinfo、query 和 fragment。
- 验证方式：主流程执行配置、清单、应用和用户 API 聚焦测试 34/34 通过；安全补充后实现代理与独立质量复审执行 35/35 通过；`git diff --check` 通过。
- 审查结论：规范审查和最终代码质量审查均通过，未发现剩余中高风险问题。
- 当前状态：实施计划任务 1 已完成，开始任务 2 PostgreSQL/Alembic 基线。

### 2026-07-16：第五周任务 2 PostgreSQL 与 Alembic 基线完成

- 开发内容：数据库 Engine 按方言配置，SQLite 保留跨线程兼容参数，PostgreSQL 使用连接预检查和 Task1 的连接池参数；新增只读 Alembic revision 检查，生产启动只校验 schema head，本地启动继续执行 `create_all` 和兼容迁移。
- Alembic 基线：revision `20260715_01` 使用静态 `op.create_table`、`op.create_index` 和外键操作覆盖当前 30 张业务表、59 条外键与 2 个显式索引，不调用 `Base.metadata.create_all/drop_all`，不自动执行 upgrade。
- 问题现象：初次 autogenerate 检测到 `model_library.training_job_id` 与 `training_jobs.model_library_id` 形成双向外键环，默认顺序会让 PostgreSQL 引用尚未创建的表；升级后的 SQLite 执行 `alembic check` 时又将 UUID 反射成 NUMERIC，产生全量伪类型差异。
- 根因：环形外键不能全部以内联约束参与拓扑建表；SQLite 不保留 PostgreSQL/SQLAlchemy UUID 的原始类型信息，Alembic 类型比较无法从反射结果恢复 UUID 语义。
- 解决方法：迁移环境只为环中一条命名外键设置 `use_alter`，baseline 在所有表创建后显式补建该约束，SQLite 使用 batch alter、PostgreSQL 使用 `create_foreign_key`；在线 Alembic 环境仅对 SQLite 关闭类型比较，PostgreSQL 继续检查类型漂移。
- TDD 与验证：聚焦测试先因缺少 `engine_options` 明确 RED；实现后 10/10 GREEN。补充 `alembic check` 断言再次因 UUID 反射 RED，方言修正后 GREEN 并输出 `No new upgrade operations detected`。组合回归 35/35 通过，第五周 runner 2/2 模块通过。
- 预防措施：生产 schema 只能通过 Alembic 变更；新增模型后必须运行空库双次 `upgrade head`、`alembic check`、表/索引/revision 检查；出现外键环时必须命名并后置约束，不能依赖 autogenerate 的警告顺序；SQLite 类型反射结果不能替代 PostgreSQL 类型验收。
- 当前状态：实施计划任务 2 完成；任务 3 SQLite 到 PostgreSQL 数据复制尚未开始，本任务未实现任何数据复制逻辑。

### 2026-07-16：第五周任务 2 质量复审修复

- 审查问题：内存 SQLite 使用默认连接池时，主线程建表写入后子线程会获得独立连接并报 `no such table`；`initialize_database` 默认参数及 lifespan 的 session/dispose 绑定模块级对象，导致测试或嵌入应用注入数据库后仍可能访问全局数据库。
- 根因：SQLite 内存数据库状态属于单个 DBAPI 连接；Python 默认参数在函数定义时求值，且 lifespan 内部硬编码导入 `SessionLocal`、关闭全局 `engine`，绕过了运行时应用状态。
- 解决方法：仅对 `sqlite://`、`:memory:`、`file::memory:` 和 `mode=memory` URL 增加 `StaticPool`，文件 SQLite 保持默认池；`initialize_database` 改为 `None` 默认并在调用时解析，新增 `configure_runtime_dependencies` 将 settings、engine、session factory 注入 `app.state`，lifespan 按注入优先、模块级回退执行初始化、admin seed 和 shutdown dispose。
- TDD 验证：真实跨线程测试先 RED，子线程报 `sqlite3.OperationalError: no such table: shared_data`，加入 `StaticPool` 后 GREEN；真实 lifespan 测试先 RED 于缺少运行时注入 helper，实现后在独立 `temp_test` SQLite 中完成 schema 和 admin seed，并确认全局 `SessionLocal/engine` 未调用。
- 回归结果：`tests.test_database_production` 13/13，通过关联测试 48/48，第五周 runner 2/2 模块通过。
- 预防措施：内存 SQLite 测试必须验证跨线程真实读写而非只检查 options；生命周期依赖必须从应用状态解析，默认参数不得捕获可替换运行时对象；seed 与 shutdown 必须使用同一组解析后的数据库依赖。

### 2026-07-16：完成任务 2 后暂停

- 暂停要求：用户要求完成 Task 2 后保存开发进度并暂停。
- 已完成范围：第五周 Task 1 配置与密钥管理、Task 2 PostgreSQL/Alembic 基线均已完成实现、TDD、规范审查、质量审查和主流程复验。
- 最新验证：Task 2 关联测试 48/48 通过；第五周 runner 当前 2/2 模块通过；Alembic 空库双次升级、revision、30 张业务表和关键索引检查通过。
- 未开始范围：Task 3 SQLite 到 PostgreSQL 数据迁移工具及 Task 4-13 均未开始，本次未创建任何 Task 3 源码或测试。
- 恢复顺序：从实施计划 Task 3 的失败测试开始，不重复或回退 Task 1/2；真实 PostgreSQL 连接验收仍保留到 production-integration 任务。
- 工作区状态：所有进度保存在当前工作区，未提交、未推送；用户原有删除项、Word 文档、`docs2` 和 `docs/build_project_brief.py` 保持不动。

### 2026-07-16：第五周任务 3 SQLite 到 PostgreSQL 数据迁移工具完成

- 开发内容：新增 `tools/migrate_database.py`，提供 `TableTransferResult`、`copy_database` 和安全 CLI；新增 `tests/test_database_transfer.py` 并加入第五周测试清单。
- 迁移行为：按外键依赖顺序复制默认 Schema 业务表；保留主键、UUID、datetime、JSON 和空值；相同主键且内容相同则跳过，相同主键内容不同则记录 mismatch 且不覆盖；目标额外记录通过计数差异使 CLI 失败；重复执行新增数为 0。
- 循环外键：`model_library.training_job_id` 与 `training_jobs.model_library_id` 以及自引用可空外键采用首阶段置空、第二阶段回填；真实 ORM UUID 主键和双方外键均经过回归验证。
- 安全边界：跳过 `alembic_version`，不覆盖目标 revision；CLI 固定使用 `--source-url` 和 `--target-url`，输出移除凭据、query 和 fragment；源目标相同、记录冲突或计数差异均返回退出码 1。
- 问题与根因：SQLite 将 PostgreSQL UUID 列反射为 NUMERIC，直接使用反射类型读取会报 `TypeError: must be real number, not str`；循环外键回填若在 UUID 主键条件中继续使用原始字符串，会报 `str has no attribute hex`。
- 解决方法：源端使用经过标识符引用的原始 DBAPI 行读取，写入、比较和回填条件统一按应用或目标列类型规范化；表和列标识符通过 SQLAlchemy dialect preparer 引用，默认 PostgreSQL `public` Schema 契约保持不变。
- TDD 与审查：先因缺少迁移模块形成 RED；随后真实 ORM UUID 读取和双向循环回填分别形成 RED 并修复。规范审查补充真实 ORM JSON、datetime、null 覆盖后通过；代码质量审查修复 schema-qualified 原始读取后通过。
- 验证结果：`tests.test_database_transfer` 9/9 通过；迁移、生产数据库与清单组合测试 23/23 通过；`python run_suite.py --week 5` 为 3/3 模块通过；`git diff --check` 通过。
- 遗留风险：本任务使用两个隔离 SQLite 和真实 ORM Schema 验证通用逻辑；真实 SQLite 到 PostgreSQL 连接迁移仍按计划在 Task 11 production-integration 中验收，未提前标记完成。

### 2026-07-16：完成任务 3 后暂停

- 暂停要求：用户要求完成 Task 3 后保存开发进度并暂停。
- 已完成范围：第五周 Task 1 配置与密钥管理、Task 2 PostgreSQL/Alembic 基线、Task 3 SQLite 到 PostgreSQL 数据迁移工具均已完成实现、TDD、规范审查、代码质量审查和主流程复验。
- 未开始范围：Task 4 至 Task 13 尚未开始，本次未实现 Local/MinIO、Artifact 调用点迁移、Celery、Redis 事件桥接、readiness、生产集成 CI、容器或交付文档。
- 恢复顺序：从实施计划 Task 4 的失败测试开始；不得重复或回退 Task 1-3；真实 PostgreSQL 数据迁移验收保留到 Task 11。
- 工作区状态：所有开发进度保存在当前工作区，未提交、未推送；用户原有删除项、Word 文档、`docs2` 和 `docs/build_project_brief.py` 保持不动。

### 2026-07-16：第五周任务 4 Local/MinIO 存储适配器完成

- 当前周次：第 5 周。
- 开发内容：新增统一 `ArtifactStorage` 协议、`LocalStorage`、`MinioStorage` 和配置 factory；增加 MinIO 7.2 客户端依赖，并将存储测试唯一归属第五周。
- 问题现象：当前环境首次运行新测试时缺少 `minio` 包；调用链审查还发现工业模板不能把 MinIO 物化后的短期路径持久化到工作流节点。
- 根因：新增生产依赖尚未安装到本地 Python 环境；物化路径只在上下文内有效，无法跨进程或跨任务重用。
- 解决方法：安装与 `requirements.txt` 一致的 `minio==7.2.*`；本地存储使用根目录约束、同卷临时文件和原子替换，MinIO 使用固定 `projects/{project_id}/artifacts/{artifact_id}/{filename}` key、已知长度流上传、完整性校验、失败补偿删除和自动回收缓存。Task 5 将模板节点改为持久化 Artifact ID，并在算子执行时物化。
- 验证方式：`python -m unittest tests.test_storage -v` 6/6 通过；`python run_suite.py --week 5` 4/4 模块通过；`python -m unittest tests.test_module_imports -v` 2/2 通过；实际检查 MinIO 7.2.20 `put_object` 签名与适配器调用一致。
- 影响范围：后端依赖、制品存储协议、本地制品目录、MinIO 对象键和第五周测试清单；尚未迁移现有 Artifact 业务调用点。
- 预防措施：所有对象键片段必须由服务端校验和组装；外部对象写入成功而后续失败时必须补偿删除；临时物化路径不得写入数据库或工作流快照。
- 遗留事项：Task 5 至 Task 13 尚未完成；真实 MinIO 网络和生产组合验收保留到 Task 11。

### 2026-07-16：第五周任务 5 制品 URI 与业务调用点迁移完成

- 当前周次：第 5 周。
- 开发内容：Artifact 增加 `storage_uri` 和 Alembic revision `20260715_02`；ArtifactService 统一通过 Local/MinIO 存储、支持数据库失败补偿删除和旧 `storage_path` 读取；Dataset、Model、Template、Training 和后台 DAG 执行改用 Artifact ID/URI。
- 问题现象：第一次真实后台工作流回归中，CSVImport 按 Artifact ID 查询 SQLite UUID 列时报 `str has no attribute hex`，运行状态被错误收敛为失败。
- 根因：工作流节点参数来自 JSON 字符串，而 SQLAlchemy UUID 类型绑定要求 `uuid.UUID` 实例；单元测试只验证了服务内部 UUID，没有覆盖跨线程 JSON 到 ORM 查询的边界。
- 解决方法：ArtifactService 在查询边界统一将字符串 ID 转换为 UUID；CSVImport 在执行时通过 `materialize()` 读取，模板节点只持久化 `source=artifact` 和 `dataset_artifact_id`，不保存临时文件路径。
- 验证方式：Task 5 关联测试 58/58 通过；完整后端 runner 38/38 模块通过；Alembic 空库双次升级、`alembic check` 和 `20260715_02` 字段/索引检查通过；真实后台工作流 `test_api_runs` 3/3 通过；`git diff --check` 通过。
- 影响范围：制品模型、数据库迁移、本地/MinIO 业务适配、数据集 API、模型 API、训练闭环、工业模板和工作流运行。
- 预防措施：所有外部 JSON ID 在 ORM 查询边界显式规范化；稳定 Artifact ID/URI 与短期物化路径分离；新增跨进程调用必须包含真实后台执行回归。
- 遗留事项：Task 6 至 Task 13 尚未开始；旧批量训练接口仍保留历史 `dataset_path` 参数，需在后续调度/训练治理任务中继续收口；真实 PostgreSQL/Redis/MinIO/Celery 集成保留到 Task 11。

### 2026-07-16：第五周任务 6 算子制品持久化与历史迁移完成

- 当前周次：第 5 周。
- 开发内容：DAGExecutor 统一消费 `OperatorResult.artifacts`；ArtifactService 新增 `create_from_draft`；新增 `app/services/artifact_migration.py` 和 `tools/migrate_artifacts.py`，支持项目筛选、dry-run、SHA-256/大小校验、单条事务更新和幂等跳过。
- 问题现象：初始实现中 Draft bytes 被执行器完全丢弃；历史迁移入口若只实现 CLI 会导致测试和应用无法复用核心逻辑；重复迁移统计未计入已迁移记录。
- 根因：执行器只处理 `OperatorResult.outputs`；工具层和业务层没有稳定服务边界；迁移查询只筛选 `storage_uri IS NULL`，无法统计已存在 URI 的跳过记录。
- 解决方法：节点完成前持久化每个 Draft，返回 Artifact ID、URI 和大小引用，持久化失败则节点失败；迁移核心逻辑放入服务模块，CLI 仅做参数解析；迁移结果显式统计 candidates/migrated/skipped/failed，失败保留旧 `storage_path`。
- 验证方式：Task 6 聚焦测试 3/3 通过；第五周 runner 7/7 模块通过；第一周单独重跑 16/16 通过；`git diff --check` 通过。一次并行启动完整 runner 出现 `test_api_users` SQLite `unable to open database file`，单独重跑证明业务代码通过，记录为测试环境并行资源冲突，未据此修改数据库逻辑。
- 影响范围：DAGExecutor、ArtifactService、历史 Artifact 文件、第五周测试清单和迁移 CLI；未开始 Task 7 Celery/Local Dispatcher。
- 预防措施：执行器只允许稳定 Artifact 引用进入节点结果，不允许原始 bytes 穿透；迁移命令必须提供可复用函数并验证重复执行；涉及共享临时根目录的完整 runner 不应并行启动多个实例。
- 遗留事项：Task 7 至 Task 13 尚未开始；真实 PostgreSQL/Redis/MinIO/Celery 集成仍保留到 Task 11。

### 2026-07-16：第五周任务 7 至 10 基础设施代码完成

- 当前周次：第 5 周。
- 开发内容：新增 LocalTaskDispatcher、Celery app/任务领取逻辑、WorkflowRun 任务元数据迁移 `20260715_03`、Redis JSON 事件 publisher、readiness 服务与 `/api/ready` 路由；新增 production integration skip 测试、Ubuntu 服务容器 CI job、生产 Compose、Worker 镜像和迁移运维文档。
- 验证方式：第五周 runner 12/12 通过；基础设施聚焦测试 17/17 通过；生产集成测试本地明确 skip；Alembic head `20260715_03` 双次升级和 `alembic check` 通过；`git diff --check` 通过。
- 当前状态：Task 7–10 已完成本地实现和测试；Task 11 已建立 CI 验收 job，但尚未取得真实 GitHub Actions production-integration 成功证据，因此第五周整体仍为“进行中”。
- 已知限制：Celery 任务当前使用独立执行服务占位回调，真实 Worker 与 Redis 事件订阅的端到端执行必须在 CI 服务栈中继续验收；readiness 本地模式通过，生产依赖检查需真实服务验证。
- 遗留事项：Task 11 远程生产集成、Task 13 全量前后端/浏览器验收和最终文档收尾尚未完成。

### 2026-07-16：第五周任务 11-13 状态审计

- 当前周次：第 5 周，状态仍为进行中。
- 已完成：Task 1-10 的本地实现、迁移链、存储适配、制品迁移、Local Dispatcher、Celery claim 基础、Redis publisher、readiness、Compose/Worker 镜像和运维文档；第五周本地 runner 12/12 通过。
- 未完成：Task 11 真实 PostgreSQL/Redis/MinIO/Celery 集成测试尚未取得 GitHub Actions 证据；Task 13 全量后端、前端、Playwright、npm audit 和远程 production-integration 尚未完成。
- 阻塞与原因：当前机器未提供 Docker 服务栈，且 production integration 测试仍需补齐真实 Celery Worker 执行、Redis 订阅恢复、MinIO round-trip 和取消/超时断言；不能用本地 skip 代替生产验收。
- 当前验证：第五周 `python run_suite.py --week 5` 为 12/12；基础设施聚焦测试 30 个用例通过、生产集成 1 个用例明确 skip；Alembic `20260715_03` 双次升级和 `alembic check` 通过；`git diff --check` 通过。
- 恢复顺序：先完善 `tests/test_production_stack.py` 的真实服务断言和 Worker 启动步骤，运行 GitHub Actions `production-integration`；成功后执行 Task 13 全量验收并决定是否将第五周改为已完成。

### 2026-07-16：第五周剩余本地任务补齐

- 开发内容：完成 Task 8 恢复扫描、硬超时收敛和 Celery revoke；完成 Task 9 Redis 订阅器，对非法 JSON 丢弃、合法事件转发 WebSocket manager；补齐 Task 11 本地 skip 门禁和 CI 入口。
- 验证方式：Task 8/9 聚焦测试 7/7 通过；第五周 runner 12/12 通过；生产集成测试本地明确 skip；模块清单、Alembic 和 diff 检查通过。
- 当前状态：第五周所有可在当前环境完成的代码任务已完成；Task 11 远程 production-integration 和 Task 13 最终全量验收仍待 GitHub Actions 服务容器证据。
- 补充验证：Task 8 恢复扫描/硬超时和取消、Task 9 Redis 订阅器已补齐，新增聚焦测试 7/7 通过；第五周 runner 仍为 12/12。完整 runner 并行执行时唯一失败为 `test_api_users` SQLite `unable to open database file`，单独运行该模块已通过，属于共享临时目录资源冲突。

### 2026-07-16：第五周生产集成 job 收尾补充

- 开发内容：生产集成测试增加真实 PostgreSQL `SELECT 1` 和 MinIO round-trip；CI job 增加 Celery worker 启动、失败日志脱敏扫描和证据上传。
- 当前验证：本地 `RUN_PRODUCTION_INTEGRATION` 未启用时测试明确 skip；第五周本地 runner 仍为 12/12。真实 PostgreSQL/Redis/MinIO/Celery 结果仍需远程 Actions 运行确认。
- 遗留事项：Task 11 Step 5、Task 12 Step 4 和 Task 13 Step 5-7 依赖远程 job 与最终全量验收，未提前标记完成。

### 2026-07-16：第五周本地最终验收完成

- 验证结果：后端完整 runner 45/45 模块通过；前端 Vitest 14/14 文件、35/35 用例通过；前端生产构建成功；Chromium Playwright 1/1 通过；`npm audit` 报告 0 vulnerabilities；隔离数据库 Alembic 双次升级、`alembic current`/`alembic check` 测试通过；`git diff --check` 通过。
- 问题现象：直接在当前默认开发 SQLite 上执行 `alembic upgrade head` 报 `table algorithms already exists`，随后 `Target database is not up to date`。
- 根因：该开发库由本地模式 `create_all + ensure_schema_compatibility` 创建，没有 `alembic_version`；生产 Alembic baseline 只适用于新库或已有 revision 的数据库，不能覆盖未标记的旧开发库。
- 解决结果：不覆盖或重置用户开发库；使用隔离临时数据库完成 Alembic 真实升级验证，并保留现有本地兼容迁移路径。
- 当前状态：本地 Task 13 Step 1-4、6-7 已完成；Task 11 Step 5、Task 13 Step 5 仍依赖 GitHub Actions `production-integration` 远程成功证据。第五周暂不标记为最终完成。

### 2026-07-17：第五周真实生产栈与异步执行缺口修复

- 当前周次：第 5 周，状态仍为进行中。
- 开发内容：将工作流完整执行逻辑从 API 移入 `workflow_execution`，Local/Celery 共用服务；生产 dispatcher 使用真实 Celery task，Worker 显式注册完整算子；增加 PostgreSQL 行锁领取、心跳、绑定 Celery app 的 revoke、取消/失联恢复和 Redis client 回收；FastAPI lifespan 启停 Redis subscriber；readiness 增加 Alembic head 与真实 Redis/Celery/MinIO 依赖。
- 问题现象：原 Worker 领取后调用空 lambda 并错误返回完成；独立 Worker 未加载算子；Redis subscriber 未启动；真实 SQLite→PostgreSQL 第二次迁移因 UUID 32 位/连字符表示不同而重复插入；容器 DataBus 固定访问 `parents[4]` 报 `IndexError`；双 Uvicorn worker 并发种子触发管理员唯一键冲突；Docker 构建上下文包含 1.66 GB 开发数据库；Compose 5 将 MinIO 初始化字符串拆参导致裸 `mc` 执行。
- 根因：本地线程路径未真正抽取；应用初始化副作用只存在于 FastAPI main；跨方言主键未先规范化；运行路径和构建上下文隐含本地目录结构；种子流程是先查后插且没有处理并发唯一冲突；Compose shell 命令未固定为单一 `sh -c` 参数。
- 解决方法：建立共享执行服务和集中算子注册入口；任务 publisher/heartbeat 使用明确生命周期；主键构造调用方言规范化；DataBus 默认使用系统临时目录且生产显式设置 `ML_PLATFORM_TEMP_DIR`；增加 `.dockerignore`、非 root 命名用户、自动迁移服务、可移植 MinIO entrypoint 和并发安全种子；生产 CI 等待 Worker ready 并只上传脱敏日志。
- WSL 验证：Docker 29.6.2、Compose 5.3.1、PostgreSQL 16、Redis 7、Celery 5.4、MinIO 真实组合启动；`/api/ready` 的 database/redis/celery/storage 全部 `OK`；`tests.test_production_stack` 4/4 通过，覆盖数据库幂等迁移、MinIO、真实工作流、重复投递、Redis 事件、节点超时、失联和取消恢复。
- 完整验证：第五周 12/12、后端 45/45、前端 14 文件 35/35、生产构建、Chromium 1/1、npm audit 0 漏洞、隔离 Alembic 双次 upgrade/current/check、compileall、凭据扫描和 `git diff --check` 通过。
- 遗留事项：Task 11 Step 5 与 Task 13 Step 5 仍需 GitHub Actions `production-integration` 成功 URL；远程成功和最终文档提交前第五周不标记为完成。

### 2026-07-17：GitHub Actions 生产服务声明修复

- 当前周次：第 5 周，远程验收修复中。
- 问题现象：首次推送 Run `29547284623` 在创建任何 job 前失败，`jobs=[]` 且没有步骤日志。
- 根因：GitHub Actions 的 `services` schema 不支持 `command` 字段，本地通用 YAML 解析只能验证语法，无法发现 Actions 语义错误；MinIO 官方镜像又必须接收 `server /data` 参数。
- 解决方法：从 service containers 移除 MinIO，改在 job 步骤中使用 `docker run ... minio/minio:latest server /data`，轮询 live health；失败证据收集 MinIO 日志，`always()` 清理容器；`runner.temp` 只在 Worker/测试步骤环境中解析。
- 验证方式：本地 YAML 解析和 `git diff --check` 通过；等待修复提交后的 GitHub Actions 实际 job 创建和运行结果。
- 预防措施：Actions 配置变更除 YAML parser 外必须以真实 Run 验证；第三方 service 需要自定义命令时使用显式 `docker run` 步骤，不写未受支持的 schema 字段。
- 后续更正：修复 schema 后 Run `29547439929` 已创建并运行全部 jobs；production-integration 的 Worker 日志确认任务注册、Redis 连接和 ready，失败根因是 Celery CLI 将 `inspect` 的 `--timeout` 错放在子命令 `ping` 之后。命令已改为 `inspect --timeout=2 ping`，等待下一 Run 验证。

### 2026-07-17：GitHub Actions Worker 启动门禁二次修复

- 当前周次：第 5 周，远程验收修复中。
- 问题现象：Run `29547692020` 的 Worker 在 4 秒内完成 Redis 连接、任务注册并输出 `ready.`，但 `celery inspect --timeout=2 ping` 前两次返回 `No nodes replied`，第三次异常挂住，导致等待循环在约 104 秒后超时，生产集成测试未执行。
- 根因：将 Celery remote-control CLI 用作进程启动门禁会引入独立的 pidbox 响应与 CLI 阻塞路径，无法保证循环按时推进；失败证据扫描还调用了 Ubuntu 22.04 runner 未预装的 `rg`，扫描实际没有执行。
- 解决方法：启动门禁改为轮询 Worker 自身 `celery.log` 的 `ready.` 信号，并保留 PID 存活和超时日志；真实生产测试继续通过任务消费、结果读取及 `ReadinessService` 的 `inspect().ping()` 验证 Celery；敏感信息扫描改用 runner 自带的 `grep -E`。
- 测试与验证：新增 `test_ci_workflow`，先确认旧配置 2/2 断言失败，再修改 workflow 后 2/2 通过；YAML 解析和 `git diff --check` 通过；第五周 runner 更新为 13/13 模块通过。
- 遗留事项：修复提交仍需取得新的 GitHub Actions `production-integration` 4/4 成功证据；成功前第五周继续保持“进行中”。
- 预防措施：进程启动门禁优先使用进程自身可观测状态，远程控制能力由后续功能测试验证；CI shell 脚本只能依赖 runner 基线命令或显式安装工具，并为关键脚本增加静态契约测试。

### 2026-07-17：循环外键迁移保持更新时间修复

- 当前周次：第 5 周，远程质量门禁修复中。
- 问题现象：Run `29548417472` 的 production-integration 4/4 通过，但 Ubuntu 全量质量 job 在循环外键迁移回归中发现目标 `updated_at` 比源值晚 1 秒；本地执行常因两次操作落在同一秒而通过。
- 根因：循环外键采用第二阶段 UPDATE 修复，语句使用带 `onupdate=func.now()` 的 ORM Table；只显式更新外键时 SQLAlchemy 自动注入当前时间，破坏源数据时间戳。
- 解决方法：第二阶段仍使用 ORM 列类型保证 SQLite/PostgreSQL UUID 转换，但同时把所有声明 `onupdate` 的字段按源行原值显式写入，阻止隐式刷新。
- TDD 与验证：先把源 `updated_at` 固定为历史时间，确认旧实现稳定覆盖为当前时间；首次尝试使用反射表因 SQLite UUID 被反射为数值型而失败，依据类型处理证据调整为显式保留 onupdate 字段；最终聚焦用例、迁移模块 9/9 和第五周 13/13 通过。
- 遗留事项：需推送修复并取得新的 Windows/Ubuntu/production-integration/Chromium 全绿 Run 后再完成第五周状态更新。
- 预防措施：数据迁移 UPDATE 必须审计 Python-side default/onupdate；时间戳保真测试应使用固定历史值，不依赖同秒执行碰巧相等；反射表与 ORM Table 切换前必须验证自定义 UUID/JSON 类型处理器。

### 2026-07-17：第五周最终验收完成

- 当前周次：第 5 周，状态更新为已完成。
- 远程证据：[GitHub Actions Run 29548916619](https://github.com/FaceGg/Al-Platform/actions/runs/29548916619) 全绿；`Quality (windows-latest)`、`Quality (ubuntu-22.04)`、`Production integration (Ubuntu)` 和 `Chromium acceptance (Ubuntu)` 均成功。
- 生产版本与计数：PostgreSQL 16.14、Redis 7.4.9、Celery 5.4.0、MinIO `RELEASE.2025-09-07T16-13-09Z`；远程生产集成 4/4，Chromium 1/1。
- 本地验证：后端全量 46/46、第五周 13/13；WSL Docker 生产栈 4/4；前端 14 文件 35/35、生产构建、Chromium 1/1、npm audit 0 漏洞和 Alembic check 均通过。
- 完成范围：生产配置与密钥、PostgreSQL/Alembic、幂等 SQLite 迁移、Local/MinIO 存储、制品 URI/历史迁移、Local/Celery 分发、Redis 事件桥接、任务领取/心跳/取消/失联恢复、readiness、Compose 镜像、运维文档和跨平台 CI 已闭环。
- 后续工作：训练任务 Celery 化、实验追踪/检查点、周期性恢复调度、节点级断点续跑、备份恢复和性能压测按第 6 周及后续计划推进，不属于第五周遗留未完成项。

### 2026-07-17：第六周实验与训练管理设计确认

- 当前周次：第 6 周，状态调整为进行中。
- 设计结论：允许新增 MLflow；平台 PostgreSQL 保留权限、TrainingJob 状态和 MLflow ID，MLflow 作为 Experiment/Run/参数/指标/实验制品的事实来源；最终模型继续登记平台 Artifact 和模型库。
- 训练范围：普通训练与 AutoML 统一迁移到 Celery；新增 scikit-learn 迭代训练器，支持真实 epoch 指标、早停、checkpoint、恢复、取消和失联恢复；PyTorch checkpoint 延后。
- TensorBoard：采用受平台鉴权的隔离网关，每个会话只访问目标 Run，不暴露可浏览全部日志的公共实例。
- 规范文档：`docs/superpowers/specs/2026-07-17-week6-experiment-training-management-design.md`。
- 验收门禁：本地/远程全量回归、真实 MLflow/PostgreSQL/MinIO/Celery/TensorBoard 集成、前端比较与恢复流程、Chromium 和安全扫描全部通过后方可标记第六周完成。
- 遗留事项：详细实施计划、TDD 代码实现、迁移、容器、前端和生产验收尚未开始。

### 2026-07-17：第六周任务 1 生产配置完成

- 开发内容：新增 MLflow tracking/backend/artifact、TensorBoard gateway/会话 Secret、会话超时、checkpoint 间隔和训练失联阈值配置；补充 MLflow/TensorBoard 依赖与 `.env.example`。
- TDD 证据：新增配置测试先因字段不存在和生产校验缺失 RED；实现后新测试 7/7、配置组合 24/24 GREEN，第五周 runner 13/13 无回归。
- 安全边界：TensorBoard 会话 Secret 支持文件读取，MLflow backend URI 与会话 Secret 不进入标准 dump、repr 或安全摘要；摘要只暴露是否配置及清洗后的服务地址。
- 影响范围：配置模型、生产启动门禁、依赖、环境变量示例和第六周测试清单。
- 遗留事项：Experiment/TrainingJob Schema、MLflow adapter、训练执行、TensorBoard gateway 和生产服务尚未实现。
- 预防措施：生产 fixture 必须与新增强制配置同步；所有跨服务凭据使用 `SecretStr`/Secret 文件并加入泄露回归。

### 2026-07-17：第六周任务 2 实验与训练持久化完成

- 开发内容：新增项目级 `Experiment` 模型与 MLflow Experiment 唯一绑定；扩展 `TrainingJob` 的 Run、Celery、心跳、恢复血缘、checkpoint、epoch、监控和早停字段。
- TDD 证据：模型测试先因 `app.models.experiment` 缺失 RED，Alembic 测试先因 head 仍为 `20260715_03` 且业务表仅 30 张 RED；完整 downgrade 测试先确认空回滚会残留表和列；Week 6 归属测试先确认新模块未登记。
- 迁移策略：Alembic `20260717_04` 创建 `experiments`、训练列/索引/外键和完整 downgrade；本地 SQLite 兼容层只为旧表幂等补充 nullable 列和索引，不重建旧表或伪造外键。
- 验证结果：模型与生产迁移 19/19、数据库迁移回归 9/9、降级聚焦 1/1 通过；双次 upgrade、`alembic check`、降级到 `20260715_03` 均有自动化覆盖。
- 遗留事项：MLflow adapter、项目鉴权 Experiment API、训练执行与后续生产集成尚未实现；第六周保持进行中。
- 预防措施：新增 Alembic revision 必须同时验证空库双次升级、autogenerate check 和真实 downgrade；开发 SQLite 兼容迁移与生产外键迁移分层实现。

### 2026-07-17：第六周任务 3 MLflow Tracking Adapter 完成

- 开发内容：新增无导入副作用的 `ExperimentTracking` 协议与 `MlflowExperimentTracking`；支持 Experiment 复用、parent/child Run、参数/指标/标签、搜索/比较、指标历史、制品上传/列出/下载和 Run 终态。
- 数据契约：`TrackedRun`、`TrackedMetric`、`TrackedArtifact` 使用 frozen DTO；Run 的 params/metrics/tags 复制为只读映射，参数统一字符串化，指标拒绝 bool、非数值和 NaN/Infinity，step 保持整数。
- TDD 证据：测试先因 adapter 模块不存在 RED；补充 `set_tags` 契约时先撤掉具体实现并确认 AttributeError RED；测试清单先确认新模块未归属 Week 6。
- 测试边界：有状态内存 fake 返回 MLflow 3.1.4 官方 `Experiment/Run/RunData/Metric/FileInfo` 实体，验证可见状态而非调用次数；MLflow not-found 与基础设施异常分别映射为稳定领域错误。
- 当前验证：adapter 6/6 通过，不需要网络 MLflow 服务；真实 MLflow/PostgreSQL/MinIO 组合留到 Task 12 验收。
- 遗留事项：项目权限 API、训练执行、AutoML、TensorBoard、前端和生产集成仍未实现；第六周保持进行中。

### 2026-07-17：第六周任务 4 项目鉴权 Experiment API 完成

- 开发内容：新增 Experiment 创建/列表/详情、Run 分页和 2–10 Run 比较 API；创建使用 `project/<project_uuid>/<experiment_uuid>` 稳定 MLflow namespace，展示名称只保存在平台模型。
- 权限边界：所有资源查询先通过平台 Project owner 过滤，再解析或访问 tracking 服务；跨用户 Experiment、未配置 tracking 下的跨项目请求以及跨 Experiment Run 统一隐藏为 404。
- 一致性策略：重名在调用 MLflow 前返回 409；MLflow 失败回滚平台 session 且不留平台记录；MLflow 已创建后数据库失败返回 `EXPERIMENT_PERSISTENCE_FAILED`，保留远端历史且不尝试不可逆删除。
- 比较契约：保持请求 Run 顺序，参数/指标键排序；每个 Run 返回 params、latest metrics、metric history、状态、时间戳、显式 null 和 missing 列表。
- TDD 与验证：路由缺失时 6/6 以 404 RED；补充安全/数据库一致性用例时分别以错误 503 和通用 500 RED；最终 API 8/8 GREEN，Week 6 清单先确认新模块未登记。
- 遗留事项：训练提交仍是旧线程路径，将在 Task 6 迁移 Celery；checkpoint/恢复、AutoML、TensorBoard、前端与真实 MLflow 集成尚未完成。

### 2026-07-17：第六周任务 5 可恢复增量训练核心完成

- 开发内容：新增纯 `IterativeTrainer`，分类使用 `SGDClassifier(loss="log_loss")`，回归使用 `SGDRegressor`；固定划分与 StandardScaler，每 epoch 只执行一次 `partial_fit`。
- 指标与早停：分类记录 train/val loss 与 val accuracy；回归记录 train/val loss、val r2 和 val rmse；所有指标强制有限浮点，支持 min/max、patience、min_delta 和 restore_best。
- checkpoint：joblib bytes 保存当前/最佳模型、Scaler、完成 epoch、best epoch/metric、无改善计数、类别、feature/target schema、配置、Dataset/Job/Run 来源和格式版本 1；恢复允许增加 total epochs，但不重置 patience。
- 边界：核心模块不导入 SQLAlchemy、Celery、ArtifactService 或 MLflow；指标、checkpoint、取消均通过回调交给外层编排。
- TDD 与验证：模块缺失时测试 RED；最终分类、回归、早停、restore-best、取消、间隔 checkpoint、序列化版本和恢复 patience 共 8/8 GREEN；Week 6 清单先确认新模块未登记。
- 遗留事项：checkpoint 尚未上传 MLflow/MinIO，最终模型尚未登记 Artifact/ModelLibrary；这些由 Task 6 执行服务完成。

### 2026-07-17：第六周任务 6 Celery 训练执行完成

- 开发内容：新增 `execute_training_job` 与 `ml_platform.execute_training`；SQLite 使用状态条件 UPDATE 原子领取，PostgreSQL 路径使用 `FOR UPDATE SKIP LOCKED`，重复投递返回 skipped。
- 执行闭环：绑定 MLflow Run 并记录最终生效训练配置；逐 epoch 写指标、current epoch 和 heartbeat；上传 epoch/latest/best checkpoint；完成后登记模型 Artifact 和 ModelLibrary 血缘，最后结束 Run 并提交 completed。
- 失败与取消：tracking/训练异常写入稳定 error code、exception type 和日志，Run 标记 FAILED；cancel_requested 在 epoch 边界协作停止，保留 latest checkpoint，Run 标记 KILLED，且不登记最终模型。
- 事务边界：指标与 checkpoint 回调使用独立短 session，避免长训练事务持锁；completed 只在模型 Artifact、ModelLibrary、tracking tags/终态均成功后提交。
- TDD 与验证：服务缺失时模块导入 RED；补充完整训练配置审计时先因 MLflow params 缺少 total_epochs RED；最终训练执行 5/5、既有 Celery/dispatcher 10/10、任务注册 smoke 通过。
- 遗留事项：恢复 checkpoint 下载与新 Job 创建、stop/stale recovery API 留到 Task 7；旧 `/api/training/run` 线程入口尚待 Task 7 严格替换。

### 2026-07-17：第六周任务 7 checkpoint 恢复、停止与失联恢复完成

- API 替换：`/api/training/run` 现在必须绑定 owned Experiment 和 Dataset Artifact，创建 queued Job 并投递 Celery，不再启动 API 进程内线程；jobs/detail 返回追踪、epoch、checkpoint 和恢复血缘。
- checkpoint/恢复：列表改为 owned Job + MLflow artifacts；resume 在 API 层下载并验证格式、Dataset/Job 血缘和总 epoch，创建新 Job/Run 血缘后投递；Worker 执行时再次从源 Run 下载持久 checkpoint 并从下一 epoch 继续。
- 停止与恢复扫描：stop 只允许 pending/queued/running，写 cancel_requested 后 revoke；stale scan 对 checkpoint、无 checkpoint、cancel_requested 分别执行 pending+attempt、`TRAINING_WORKER_LOST`、cancelled。
- readiness：Celery ping 之外还必须确认 `ml_platform.execute_training` 已注册，防止“Worker 在线但不能训练”误判 ready。
- TDD 与验证：旧接口下 checkpoint/resume/stop 404、start 走旧 Artifact 路径及 recovery 模块缺失均 RED；Worker resume 暂时移除后明确从 `[1,2,3,4,5]` 错误重启，恢复后只记录 `[4,5]`；聚焦 17/17 GREEN。
- 遗留事项：AutoML 暂返回稳定 `AUTOML_MIGRATION_PENDING`，将在 Task 8 实现；TensorBoard、前端和真实生产服务验收尚未完成。

### 2026-07-17：第六周任务 8 Artifact AutoML 与 child Run 完成

- API/调度：AutoML 只接受 owned Experiment + Dataset Artifact，Pydantic `extra=forbid` 明确拒绝历史 `dataset_path`；创建 operator=`automl` Job 并投递 `ml_platform.execute_automl`。
- 候选执行：分类固定 RandomForest/GradientBoosting/LogisticRegression，回归固定 RandomForest/GradientBoosting/LinearRegression；使用 random_state=42 的 5-fold scoring。
- Tracking：一个 parent Run、每候选一个 child Run；记录候选参数、有限 cv score、duration 和失败类型/消息；单个失败继续，全部失败才写 `AUTOML_ALL_CANDIDATES_FAILED`。
- 选择与血缘：最高有限分获胜，同分按原候选顺序稳定选择；winner 全量拟合后登记模型 Artifact、ModelLibrary、Dataset/Job/parent Run 血缘，并在 parent tags 记录 best child/artifact。
- TDD 与验证：服务缺失时 RED；首次 API 测试因普通内存 SQLite 跨线程丢表暴露测试环境问题，改为 StaticPool 后 AutoML 与既有训练血缘 7/7 GREEN；新测试清单归属先 RED。
- 遗留事项：候选集合为第六周确定性有限版本，不含分布式/贝叶斯搜索；TensorBoard、前端和生产服务验收尚未完成。

### 2026-07-17：第六周任务 9 隔离 TensorBoard Gateway 完成

- Token：URL-safe base64 JSON + HMAC-SHA256，使用 constant-time compare；claims 仅含 session/run/受控相对 logdir/expiry，覆盖篡改、过期和字段校验。
- 进程隔离：固定 root 下 resolve，拒绝绝对路径、反斜杠和 `..`；TensorBoard 只监听 127.0.0.1，使用 argv 启动并固定 `--logdir/--path_prefix`，不接受 shell 字符串。
- 生命周期：相同 session 仅在 Run/logdir 匹配时复用，Run mismatch 拒绝；按 token expiry 或 idle timeout terminate/kill 清理。
- 平台授权：owned TrainingJob 且存在 MLflow Run 才签发短期 token；返回平台 backend proxy URL。平台代理与 gateway 都重新验签，篡改 token 在内部服务访问前返回 403。
- TDD 与验证：gateway 包缺失 RED；返回 URL 初次访问 404 后补充真实 proxy 契约；最终 token、遍历、复用、Run 隔离、清理、owner 授权和 proxy 6/6 GREEN，gateway import smoke 成功。
- 遗留事项：gateway 容器、共享日志卷、真实 TensorBoard 子进程/HTTP 由 Task 12 WSL Docker 验收；前端打开操作在 Task 11 完成。

### 2026-07-17：第六周任务 10 前端 Experiment/Training API 完成

- 新增 `api/experiments.ts`：Experiment 创建/列表/详情、Run 分页和 2–10 Run 比较，提供 ExperimentRun、MetricPoint、RunComparison 等类型。
- 扩展 `api/training.ts`：严格 TrainingJobCreate、checkpoint 列表、stop、resume 和 TensorBoard session 类型/方法；列表只兼容 array 或 `{items}` 两种既有响应。
- 契约修正：前端按实施计划发送 `checkpoint_path`；后端在 owned source Run 的 artifact 列表内解析相对 path，并生成持久 checkpoint URI，不接受任意本地路径。
- TDD 与验证：Experiment 模块缺失、Training 控制函数缺失先 RED；typed client 5/5 GREEN；前端 manifest 先因新测试未归属 RED，随后登记 Week 6 且不重复归属历史 training 测试。
- 遗留事项：TrainingJobsPage 仍是旧单表布局，Task 11 将改为 Experiment/Training 双 Tab、比较、停止、恢复和 TensorBoard 操作。

### 2026-07-17：第六周任务 11 实验与训练运维界面完成

- 运维工作区：按项目筛选 Experiment 与 Training Job，使用紧凑双 Tab 表格、状态色和 epoch 进度轨展示高频操作信息，详情使用 Drawer，避免页面区块卡片嵌套。
- Experiment 操作：支持创建、查看 Run、选择 2–10 个 Run、对比指标表和 ECharts 指标历史；Run checkbox 使用稳定可访问名称。
- Training 操作：新建任务使用 Experiment/Dataset/target/task/epoch 契约；运行任务可确认停止，终态任务可从 owned Run checkpoint 恢复，TensorBoard 仅打开平台 API 返回 URL。
- 可访问性修正：Ant Design 图标会进入按钮 accessible name，关键图标按钮显式设置业务 `aria-label`；停止确认文案放在真正的确认按钮上。
- TDD 与验证：旧页面缺少双 Tab 时 2/2 RED；实现后定向 2/2、完整前端 15 文件 39/39 和 TypeScript/Vite 生产构建通过。构建仍报告既有 ECharts 大 chunk 警告，不影响本任务验收。
- 遗留事项：真实 MLflow/TensorBoard 页面数据与浏览器主流程将在 Task 12 生产栈和 Task 13 E2E 中验收。

### 2026-07-18：第六周任务 12 Compose、Readiness 与真实生产集成完成

- 部署：Compose 新增 PostgreSQL MLflow 数据库初始化、MLflow 3.2.0 服务、非 root TensorBoard Gateway、受控 TensorBoard event volume；Backend/Worker 依赖 MLflow/Gateway 健康后启动。
- 训练事件：Worker 在 `project_id/run_id` 受控目录写入每个 epoch 的 TensorBoard scalar event，Gateway 使用同一卷启动隔离会话。
- Readiness：`/api/ready` 新增 `mlflow` 与 `tensorboard` 探针，未配置时返回 `LOCAL_MODE`，失败时使用 `MLFLOW_UNAVAILABLE`/`TENSORBOARD_UNAVAILABLE` 且不回显凭据。
- 依赖与配置：后端镜像和 CI 使用 `pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/`；增加 `boto3` 以支持 MLflow S3/MinIO artifact；MLflow 官方镜像启动时同样使用该源安装 psycopg。
- TDD 与验证：Readiness 初始 2 条新断言 RED；训练 TensorBoard event 初始因参数缺失 RED；修复后后端相关回归 13/13、WSL `docker compose config`、三个目标镜像构建、全栈健康和真实生产集成 1/1 GREEN。
- 问题记录：MLflow 3.1.4 PostgreSQL adapter 将字符串 Experiment ID 绑定为 VARCHAR，升级 3.2.x 后由服务端 `int(experiment_id)` 修复；官方镜像缺少 psycopg、平台 requirements 缺少 boto3、Worker 缺少 MinIO AWS 环境变量均已按真实日志补齐。
- 遗留事项：CI GitHub Actions 尚未远程运行；Task 13 需执行全量后端/前端/浏览器/迁移/安全验收并记录运行证据。

### 2026-07-18：第六周任务 13 本地验收完成，远程推送受网络阻塞

- 本地验收：后端全量 56/56、Week 6 10/10、前端 15/15 文件 39/39、生产构建、Chromium 1/1、npm audit 0 vulnerabilities、Alembic 双次 upgrade/current/check、WSL `/api/ready` 六项 OK、真实实验集成 1/1。
- 文档交付：新增 `docs/delivery/EXPERIMENT_TRAINING_OPERATIONS.md`，并更新使用说明、生产基础设施、功能台账、构建基线和平台状态。
- 外部阻塞：`git push -u origin codex/week-6-experiment-training` 因当前机器经代理连接 `github.com:443` 失败，尚未获得 GitHub Actions 远程 Run URL；不是代码或测试失败。
- 解除方式：恢复可用的 GitHub 网络/代理后，在本分支执行 push，等待 experiment integration、Chromium、quality 和 audit job 完成，再将 Run URL 追加到本记录并把第六周状态改为已完成。
- 遗留事项：远程 CI 证据和远程分支推送仍待外部网络恢复。

### 2026-07-18：第六周远程 CI 首轮失败修复

- 现象：Actions Run `29630372947` 的生产迁移 job 在导入配置时因缺少 `MLFLOW_TRACKING_URI` 被拒绝；实验 Compose job 中 backend 因非 root 用户无法创建 `/app/app/uploads` 而反复重启。
- 根因：生产 integration job 的环境变量未随生产配置新增项更新；Compose 将宿主上传目录挂载到 `/app/uploads`，而数据集 API 使用 `/app/app/uploads`。
- 处理：为两个 CI job 显式设置 MLflow tracking URI，并为旧生产 integration 补齐 MLflow backend/artifact 与 TensorBoard 全套生产必填配置；将 Compose 上传卷改挂到 `/app/app/uploads`，并在 backend 镜像构建阶段创建并授权该目录。
- 验证：`git diff --check` 和后端实验集成测试入口通过；等待新 Actions Run 完成生产迁移、Compose readiness 和真实实验生命周期验收。
- 遗留风险：本机无 Docker CLI，无法复现 Ubuntu runner 的容器权限环境；远程 CI 仍是本次修复的强制验收门禁。
- 补充：第三次 Run `29631098923` 已通过迁移、Celery、Redis 和 MinIO，旧 Week 5 readiness 用例因未启动第六周新增的两个 HTTP 服务而失败；该用例现对非本任务范围的 MLflow/TensorBoard 探针注入健康响应，真实服务仍由 `Production experiment integration` 独立验收。
- 补充：第四次 Run `29631294252` 的 Compose backend 继续因 `app.api.operators` 使用旧 `/app/uploads` 路径而不健康；已补充路径一致性回归测试并统一到 `/app/app/uploads`，等待下一次完整实验栈验收。
- 补充：第五次 Run `29631567092` 的 Linux 质量门禁发现新增 `test_upload_paths` 未登记周归属；已将其登记到 Week 6 manifest，功能测试本身通过。

### 2026-07-18：第六周全部远程验收完成

- Actions Run：`29631795297`，URL 已记录在 `PLATFORM_STATUS.md`。
- 结果：Quality Ubuntu、Quality Windows、Production integration、Production experiment integration、Chromium acceptance 全部成功；真实实验生命周期、MLflow/MinIO artifact round-trip、TensorBoard session、迁移双次 upgrade/current/check 和浏览器主流程均通过。
- 状态：第六周 Task 1-13 全部完成，之前记录的远程阻塞已解除；后续工作转入第七周 Pipeline 调度与权限。

### 2026-07-18：第七周 Pipeline 调度子系统本地验收完成

- 当前周次：第 7 周，整体状态仍为进行中。
- 开发内容：新增五字段 Cron/IANA 时区、持久 schedule/occurrence、唯一 occurrence 幂等、工作流快照绑定、依赖/并发 skip、暂停恢复、限量补录、持久指数退避、单任务硬超时、终态同步、Celery Beat 和独立 Compose scheduler。
- 问题现象：初版退避在同一 tick 内立即重试，`timeout_seconds` 未进入 WorkflowRun/Celery metadata，occurrence 不随 WorkflowRun 终态更新；全量回归还发现 Celery 循环导入、Alembic head/表数断言和历史 SQLite 兼容列未同步。
- 根因：调度策略只落配置未形成下一次尝试时间；执行元数据、恢复任务和两条数据库升级路径未同时扩展；scheduler task 在模块加载时反向导入 workflow task。
- 解决方法：新增 `next_attempt_at` 与 `WorkflowRun.timeout_seconds`、Alembic `20260718_06`、到期重投查询和 occurrence reconciliation；Celery 按稳定任务名 `send_task` 解耦；本地 SQLite 兼容层、生产 head 检查和迁移结构断言同步更新。
- 验证方式：调度/API/CI/manifest 聚焦 25/25，相关回归 54/54，Week 7 runner 3/3，全量后端 59/59；干净 SQLite 双次 upgrade/current/check 通过；WSL scheduler 镜像从阿里云 PyPI 源构建；真实 PostgreSQL/Redis/Worker/Beat 集成 1/1，两个 WorkflowRun 均完成并同步 occurrence。
- 生产证据：Beat 日志在 60 秒周期发送 `ml_platform.scheduler_tick` 与 `ml_platform.recover_pipeline_schedules`；Worker 注册全部调度/执行任务并完成定时与补录两次真实工作流。
- 已知问题：`macro` 算子会返回未声明输出端口，在严格执行协议下失败；生产集成已改用已验证的 `mechanism_thermal`，该算子问题保留为独立技术债。
- 遗留事项：GitHub 远程 CI 尚未运行；第七周第二阶段项目角色与审计尚未设计和实现；两项完成前不得把第七周标记为已完成。

### 2026-07-18：第七周项目角色与审计设计确认

- 范围：采用 `owner/editor/operator/viewer` 四角色；owner 固定为项目创建者，成员通过现有用户名加入，不实现邮件邀请、所有权转移或多 owner。
- 权限：owner 管理项目和成员；editor 管理项目资源和调度定义；operator 执行运行、训练与调度操作；viewer 只读；审计日志仅 owner 可读。
- 审计：覆盖项目资源所有写操作，记录 success/denied/failed、请求关联 ID、资源与脱敏变更摘要；禁止持久化密码、Token、Secret、凭据、原始文件和训练数据。
- 设计文档：`docs/superpowers/specs/2026-07-18-week7-project-roles-audit-design.md`。
- 当前状态：设计已确认，等待书面规格审阅；实施计划、迁移、代码、测试和生产验收尚未开始。

### 2026-07-18：第七周项目角色与审计实施计划完成

- 计划文档：`docs/superpowers/plans/2026-07-18-week7-project-roles-audit.md`。
- 执行顺序：请求关联/脱敏、持久模型与迁移、权限矩阵、审计事务、成员与审计 API、核心资源路由迁移、完整写路由盘点、生产与远程验收。
- TDD 门禁：每个行为先观察 RED，再实现最小 GREEN；新增测试模块只归属 Week 7 一次。
- 当前状态：实施计划已完成，尚未开始角色/审计生产代码。

### 2026-07-18：第七周角色审计 Task 1 请求关联与脱敏完成

- 开发内容：新增 UUID `X-Request-ID` middleware、请求上下文提取和 allowlist + 递归敏感键脱敏；主 FastAPI 应用已注册 middleware。
- TDD 证据：目标模块缺失时请求关联/脱敏 4/4 RED；实现后 4/4 GREEN，既有 `test_app` 7/7 通过。
- 安全边界：无效调用方 request ID 被替换；来源 IP 只读取直接连接地址，不信任未配置的转发头；password/token/secret/credential/authorization/cookie/content/data/path 键递归脱敏。
- 遗留事项：审计 ORM、权限矩阵、事务与 API 尚未实现，将按 Task 2-8 顺序推进。

### 2026-07-18：第七周角色审计 Task 2 持久模型与迁移完成

- 开发内容：新增 `ProjectMember` 与 append-only `AuditEvent`，成员角色/审计结果检查约束、成员唯一约束、查询索引和历史保留外键；Alembic head 更新为 `20260718_07`。
- 数据边界：owner 仍只来自 `Project.owner_id`；成员 project/user 删除级联，创建者和审计 project/actor 删除使用 `SET NULL` 保留业务/审计历史。
- TDD 证据：模型缺失和 33/35 表差异先 RED；实现后模型/完整迁移/降级 5/5 GREEN。
- 验证方式：独立临时 SQLite 双次 upgrade、current=`20260718_07`、`alembic check` 无待生成操作，`git diff --check` 通过。
- 遗留事项：权限矩阵、审计事务和 API 尚未实现。

### 2026-07-18：第七周角色审计 Task 3 集中权限矩阵完成

- 开发内容：新增 `ProjectRole`、冻结权限集合、owner-first `ProjectAccessService`、隐藏/可见领域错误和 owned/joined 项目去重查询。
- 权限结果：owner 全权限；editor 可读、资源 CRUD、执行和调度管理/操作；operator 只读、执行和调度操作；viewer 只读。
- TDD 证据：服务缺失时矩阵 3/3 RED；实现后矩阵/owner 优先/admin 不绕过/查询去重和模型回归 5/5 GREEN。
- 安全边界：全局 `User.role=admin` 不自动获得项目访问；无成员关系保持隐藏 404 语义，已有成员权限不足使用显式 403 领域码。
- 遗留事项：HTTP 映射、审计事务和成员 API 尚待后续任务。

### 2026-07-18：第七周角色审计 Task 4 审计事务边界完成

- 开发内容：新增冻结 `AuditIntent` 和 `AuditService.project_action` 上下文，集中处理权限检查、脱敏、success/denied/failed 事件和事务。
- 一致性：成功业务行与 success 事件一次提交；visible denial 单独提交 denied；异常回滚业务后由注入的短 session 写 failed；hidden outsider 不产生项目可见审计。
- 安全：失败仅记录稳定 error code，不记录异常文本；进入上下文前冻结 actor/request 信息，避免 rollback 后 ORM 过期读取。
- TDD 与验证：AuditService 缺失时 3/3 RED；实现后事务/脱敏/矩阵 7/7，补充审计提交失败回滚业务后事务用例 4/4 通过。
- 遗留事项：成员与审计查询 API、现有项目写路由接入尚未完成。

### 2026-07-18：第七周角色审计 Task 5 成员与审计 API 完成

- 开发内容：新增严格成员 schema、owner 合成成员列表、按现有用户名添加、改角、移除；新增 owner-only 审计筛选/分页 API；项目列表返回 owned/joined 去重结果和 `project_role`。
- 权限语义：成员管理/audit.read 仅 owner；visible member 返回 `PROJECT_PERMISSION_DENIED` 403，outsider 保持隐藏 404；owner 不允许作为普通成员。
- 审计动作：成员 add/role_change/remove 使用统一事务边界，查询接口只读且无写路由。
- TDD 证据：路由 404 与 joined project 缺失先 RED；实现后新 API、既有项目 CRUD 与领域服务 29/29 GREEN，`git diff --check` 通过。
- 遗留事项：项目 CRUD、工作流、数据、训练和调度写路由仍需接入集中权限/审计。

### 2026-07-18：第七周角色审计 Task 6 项目、工作流与运行迁移完成

- 开发内容：项目 CRUD/批量删除、嵌套与直接工作流、发布/恢复、自由/工业模板实例化、运行创建/读取/取消均接入集中项目权限；新增共享 HTTP 适配器和全局 `ProjectAccessError` 404/403 转换。
- 权限语义：owner 管理项目元数据；editor 可管理工作流定义、版本与模板；operator 可启动/取消运行；viewer 只读；间接 workflow/run 探测先解析所属项目，outsider 始终返回隐藏 404。
- 审计一致性：目标路由移除内部 `db.commit()`，项目/工作流/版本/模板/运行写入与 success 审计一次提交；visible denial 记录 denied，动作使用冻结的 `project.*`、`workflow.*` 和 `workflow_run.*` 名称。
- TDD 证据：成员读取 404、工作流越权读取、编辑者创建失败、操作员模板越权和审计缺失均先 RED；角色 API 6/6、Task 6 相关模块 40/40、工业模板契约/E2E 11/11 GREEN。
- 问题与修正：工业模板 ID 同时存在于新旧模板字典，非互斥分支把 JSON 工业请求错误地再次校验为查询参数请求；真实工业 API/E2E 回归稳定复现 400 后，改为互斥 `if/elif/else` 并恢复 11/11。
- 验证方式：`python -m compileall -q app`、`git diff --check` 通过；六个目标路由文件不再包含直接提交。
- 遗留事项：Task 7 数据集、实验、训练、调度路由，Task 8 其余项目级写路由盘点，以及 Task 9 全量/迁移/WSL/远程验收仍待完成。

### 2026-07-18：第七周角色审计 Task 7 数据、实验、训练与调度迁移完成

- 开发内容：数据集上传/批量/ZIP 与读取、Experiment 创建与查询、训练/恢复/停止/AutoML/删除、Schedule 创建/更新/暂停/恢复/补录及历史均使用项目角色解析和稳定隐藏语义。
- 权限结果：editor 可创建数据/实验并管理 schedule；operator 可训练、停止、恢复及操作 schedule；viewer 可读取数据、实验、训练和调度；outsider 的间接资源探测保持 404。
- 事务边界：ArtifactService 增加默认兼容的外层事务模式，使用 savepoint 隔离单文件失败，并在审计提交失败时按 URI 补偿对象存储；训练 job 创建与 broker dispatch 状态分成两个均有审计的持久步骤；pause/resume 由外层审计统一提交。
- 编排边界：schedule backfill 是跨 occurrence/broker 的多事务命令，先以 `schedule.backfill` 记录“已授权并接受”，审计持久化成功后才执行补录副作用。
- TDD 证据：editor/operator 原先被 owner-only 404、viewer 无法读取、操作员可越权上传等行为先 RED；Task 7 计划套件 41/41 GREEN，ArtifactService 相关回归随数据集模块额外通过。
- 验证方式：四个目标 API 文件无直接 `db.commit()`，`python -m compileall -q app`、`git diff --check` 通过。
- 遗留事项：Task 8 全项目写路由分类与剩余 project-bound 路由迁移、Task 9 全量/迁移/生产/远程验收尚待完成。

### 2026-07-18：第七周角色审计 Task 8 项目写路由完整性完成

- 盘点结果：全量扫描 `app/api` 写路由；14 个 project-write 模块声明 `PROJECT_WRITE_ACTIONS`，测试校验动作集合且每个动作同时出现在真实审计调用。PlatformAPI、Agent 本体、compute/knowledge/annotation 等保留全局或用户私有授权域。
- 新增迁移：模型 Artifact 读删、带 `project_id` 的 ModelLibrary CRUD/批删、绑定 workflow 的 AgentTask review/message/update/delete/create/批删接入集中权限与审计；间接读取同步使用 hidden 404。
- 权限语义：viewer 可读项目模型与任务；editor 管理模型资源；operator 操作 workflow-bound AgentTask；outsider 不能按 model/task ID 或 workflow 过滤探测项目资源。
- 外部存储：模型 Artifact 先原子提交 DB 删除与 `model.delete` 审计，再做幂等对象清理，审计失败不会先丢模型内容。
- TDD 证据：14 个模块清单缺失、viewer 模型 404、operator 越权更新 ModelLibrary、字符串 workflow UUID 写入失败、outsider 任务列表泄露均先 RED；实现后角色/清单/导入/旧 ModelLibrary/PlatformAPI 34/34 GREEN。
- 验证方式：`python -m compileall -q app`、`git diff --check` 通过。
- 遗留事项：仅剩 Task 9 manifest、全量、迁移、WSL 生产集成、远程 CI 和最终文档状态。

### 2026-07-18：第七周 Task 9 本地最终验收完成

- Manifest：`test_project_access` 与 `test_api_project_access` 仅归属 Week 7 一次；manifest RED 明确显示两模块缺失，登记后 GREEN。
- 测试：角色/调度/manifest 聚焦 55 项通过（生产门禁本地按环境跳过 1 项）；Week 7 runner 5/5；全后端 61/61 模块通过。
- 迁移：干净 SQLite 双 upgrade、current=`20260718_07`、`alembic check` 无差异。
- WSL 生产：独立 Docker network + PostgreSQL 16 + production backend image；空库迁移到 `20260718_07`，真实四角色解析、outsider 隐藏、success/denied 审计和业务原子更新 1/1 通过；trap 仅清理隔离容器/网络，默认 Compose 未修改。
- CI：production integration job 已增加 `RUN_PROJECT_ACCESS_INTEGRATION=1` 门禁；本地 `test_ci_workflow` 4/4 通过。
- 当前状态：本地开发与生产验收全部完成；提交推送并取得远程 GitHub Actions 全绿后，更新 Run URL 并把第七周改为“已完成”。

### 2026-07-19：第七周远程 CI 首轮稳定性修复

- 现象：Actions Run `29667386137` 的 production experiment image build 从阿里云 PyPI 下载依赖时发生 `ReadTimeoutError`；Windows quality 的 Experiment/Run 页面集成测试耗时 5710ms，超过 Vitest 默认 5000ms。
- 根因：Dockerfile 内 pip 已配置 10 次重试和 120 秒超时，但单次 BuildKit 构建仍会因镜像下载中断失败；页面测试包含多轮 Ant Design 异步交互，Windows runner 性能波动超出通用单测默认时限，业务断言本身未失败。
- 修复：production experiment job 最多重试三次完整 `docker compose build`，保留 BuildKit/pip 缓存；只将该页面集成测试的超时设为 10 秒，不放宽全局测试门禁。
- 验证：CI workflow 新契约先 RED 后 5/5 GREEN；目标前端测试连续三轮 6/6、完整前端 39/39、生产构建、Week 7 runner 5/5 和 `git diff --check` 通过。
- 遗留事项：等待新 Actions Run 全部成功；成功后记录 Run URL、完成第七周状态收口，再开始第八周。

### 2026-07-19：第七周全部远程验收完成

- Actions Run：`29667952189`，五个 job 全部成功。
- 远程证据：Windows/Ubuntu quality、PostgreSQL/Redis/MinIO/Celery production integration、MLflow/TensorBoard production experiment integration 与 Chromium acceptance 全绿。
- 状态：第七周 Pipeline 调度、项目角色/审计、迁移、本地全量、WSL 生产集成和远程 CI 全部完成；开发队列转入第八周模型注册与基础推理。

### 2026-07-18：第八周模型注册与基础推理设计确认

- 架构：平台 PostgreSQL 保存逻辑模型、不可变版本、审批与部署状态；独立 `inference-runtime` 使用 ONNX Runtime 执行数据面推理。
- 注册：受信任平台 joblib 在注册时隔离转换为 ONNX；已转换 ONNX 可携带显式 Schema 注册；验证或提交失败执行 Artifact 补偿。
- 权限：owner/editor 注册、批准和创建部署；operator 启停与调用；viewer 只读；所有项目写操作接入第七周审计边界。
- 推理：严格命名 JSON records，1 MiB/100 records 上限，返回预测、可选概率、版本和耗时；运行时仅开放内部鉴权接口。
- 规格：`docs/superpowers/specs/2026-07-18-week8-model-registry-basic-inference-design.md`。
- 当前状态：设计已确认并写入规格，等待书面规格审阅；实施计划、迁移、代码和测试尚未开始。

### 2026-07-18：第八周实施计划完成

- 计划：`docs/superpowers/plans/2026-07-18-week8-model-registry-basic-inference.md`。
- 顺序：安全 ONNX 转换、注册持久化、版本服务、独立运行时、部署编排、审计 API、生产 Compose、前端运维、Chromium、全量验收。
- 门禁：每项生产行为先观察 RED；依赖安装先配置阿里云 PyPI；默认 WSL Compose 不得被测试改动；远程 CI 全绿前保持第八周“进行中”。
- 当前状态：书面规格与实施计划已完成；生产代码尚未开始。

### 2026-07-18：第八周 Task 1 安全 ONNX 转换边界完成

- TDD：`app.services.onnx_conversion` 缺失时目标模块 RED；实现后转换、unsupported、畸形包、timeout、无效 ONNX、Schema 宽度与无效 worker 结果 7/7 GREEN。
- 实现：固定 sklearn allowlist；受信任 joblib 仅在受控子进程反序列化；父进程使用私有临时目录、固定参数与 120 秒超时；ONNX checker、CPU session 和 synthetic inference 全部通过后才返回制品元数据。
- 依赖：按要求先配置 `https://mirrors.aliyun.com/pypi/simple/`，锁定 `onnx 1.18.*`、`onnxruntime 1.22.*`、`skl2onnx 1.19.*`；本机使用仓库固定 `scikit-learn 1.7.2` 验证。
- 验证：ONNX 与 iterative training 回归 15/15、compileall、`git diff --check` 通过。
- 环境说明：全局 Python 同时安装非项目依赖 `sktime` 与 `mlxtend`，两者对 sklearn 的版本要求互斥，因此全局 `pip check` 不能作为仓库依赖结论；干净 GitHub Actions/容器环境继续作为强制依赖门禁。
- 遗留事项：Task 2 注册模型、不可变版本与部署持久化尚未开始。

### 2026-07-18：第八周 Task 2 注册中心持久化完成

- 模型：新增 `RegisteredModel`、不可变 `ModelVersion` 与 `InferenceDeployment`，覆盖项目/name、模型/version、状态、来源引用、查询索引和历史 actor `SET NULL` 约束。
- 迁移：Alembic head 更新为 `20260718_08`，生产业务表从 35 增至 38；三表完整 downgrade 到 `20260718_07`。
- 删除语义：Artifact/ModelLibrary/ModelVersion 引用使用 `DEFERRABLE INITIALLY DEFERRED`；单独删除受引用制品在 commit 时失败，删除整个 project 时交叉级联可在事务末统一通过。
- TDD：模型模块缺失与 35/38 表差异先 RED；实现后 ORM 9/9、完整生产数据库与迁移 25/25 GREEN。
- 验证：干净 SQLite 双 upgrade、current=`20260718_08`、`alembic check`、downgrade、compileall 和 `git diff --check` 通过。
- 遗留事项：Task 3 流式上传、版本注册、并发分配、审批与补偿服务尚未开始。

### 2026-07-18：第八周 Task 3 注册与审批服务完成

- 流式制品：`ArtifactService.create_from_stream` 使用 1 MiB 分块、调用方上限、私有临时文件、SHA-256 和既有存储补偿；文件名拒绝路径片段。
- 注册：平台源必须同项目、completed TrainingJob/ModelLibrary、关联同一 Artifact 且 metadata source 为 training/automl；生成独立 ONNX Artifact并冻结 Schema、指标、转换信息。直接 ONNX 注册要求同项目 model Artifact 和 format=onnx。
- 生命周期：版本按锁定逻辑模型行后取 max+1；pending 可批准/拒绝/归档，同状态幂等，冲突终态返回稳定错误码，拒绝必须有评论。
- 事务修正：`ArtifactService(commit=False)` 改为只 flush，不再内部开启 SAVEPOINT；批量数据 API 在单文件容错边界显式 `begin_nested()`，确保审计/注册外层 rollback 真正回滚 Artifact 元数据。
- TDD：服务模块缺失先 RED；补偿用例暴露 SQLite SAVEPOINT 成为实际外层事务的持久化问题；修复后服务/Artifact/Storage/Dataset 回归 30/30 GREEN。
- 遗留事项：Task 4 独立 ONNX Runtime 服务尚未开始；PostgreSQL 并发版本分配将在生产集成重复验证。

### 2026-07-18：第八周 Task 4 独立 ONNX Runtime 完成

- 运行时：新增内部 FastAPI 服务与锁保护的 process-local session cache；加载前验证 Artifact SHA-256/size，使用 CPUExecutionProvider，精确匹配冻结 input/output names。
- 安全：所有 `/internal` 路由使用 `X-Inference-Internal-Token` 和 `hmac.compare_digest`；稳定错误响应不含 token、URI、样本或异常文本；`/health` 单独用于容器探针。
- 推理：严格按冻结特征名排序，拒绝缺失/额外字段、bool 冒充数字、非有限值；限制 1-100 records 与 1 MiB body；返回 exact deployment/version、prediction、可选 probabilities 和 duration。
- 并发：predict 在锁内取得不可变 loaded reference 后释放锁，unload 不破坏已开始的 inference；重复 load/unload 幂等，冲突规格返回 `DEPLOYMENT_SPEC_CONFLICT`。
- TDD：runtime 包缺失先 RED；非有限值测试首次被 httpx 严格 JSON serializer 提前拒绝，改用原始非标准 JSON body 验证服务防御；runtime + conversion 14/14 GREEN。
- 遗留事项：Task 5 Backend runtime client、部署 saga、周期 reconciliation、配置与 readiness 尚未开始。

### 2026-07-18：第八周 Task 5 部署控制面完成

- 配置：production 强制 `INFERENCE_RUNTIME_URL` 与 32+ 字符 direct/file internal secret；新增转换/加载/推理 timeout，repr/dump/summary 不泄漏密钥或 URL 凭据。
- 权限：冻结矩阵新增 model.register/model.approve/deployment.create/inference.operate；owner/editor 全部，operator 仅 inference.operate，viewer 只读。
- Saga：approved-only 创建；start/stop 先持久 desired + transitional observed，再调用 runtime，最后持久 running/stopped 或 failed + 稳定码；重复操作幂等且失败可重试。
- 恢复：Celery Beat 每 60 秒运行 `ml_platform.reconcile_inference_deployments`，按数据库 desired state reload runtime 重启后缺失 session、卸载多余 session，不擅自改变 desired state。
- Readiness：新增 inference_runtime 探针；未配置 local 返回 LOCAL_MODE，失败返回 INFERENCE_RUNTIME_UNAVAILABLE。
- TDD/验证：缺失服务、extra config、unknown permission、readiness key 均先 RED；实现后配置/权限/部署/readiness/Celery 51 通过、1 生产门禁 skip，compileall 与 diff check 通过。
- 遗留事项：Task 6 严格 Pydantic schemas、项目权限、审计与完整公共 API 尚未开始。

### 2026-07-18：第八周 Task 6 严格审计 API 完成

- API：实现逻辑模型/版本/部署列表详情、ONNX 流式上传、平台或 ONNX 注册、批准/拒绝/归档、部署创建/启停和预测；所有写 schema `extra=forbid`，列表统一 `{items,total}`。
- 权限：owner/editor 注册、审批和创建部署；operator 启停/预测；viewer 只读；间接 ID 先解析所属项目，outsider 隐藏 404，visible denial 403。
- 审计：15 个 project-write 模块机器清单新增 9 个 model registry actions；注册、上传、审批、部署命令 success/denied/failed 均经统一事务边界，预测样本不入审计。
- Saga：start/stop 审计定义为“命令已授权并接受”，持久审计后再调用 runtime；远程结果由 desired/observed 状态记录。平台转换生成外部 ONNX 对象在审计 commit 异常时显式补偿。
- TDD：路由缺失先 RED；动态 action 拼接使完整性门禁 RED，改为显式字面 action 后通过；API/历史项目权限/旧 ModelLibrary/import 回归 34/34 GREEN。
- 遗留事项：Task 7 runtime 镜像、Compose/CI 和真实 PostgreSQL+MinIO lifecycle 尚未开始。

### 2026-07-18：第八周 Task 7 生产推理服务完成

- 部署：新增 UID/GID 1000 非 root `Dockerfile.inference`，使用阿里云 PyPI、单 Uvicorn worker、内部 `expose: 7000`、健康探针和独立 cache volume；Backend/Worker/Scheduler 获得统一 runtime URL/secret，Backend 等待 runtime 健康。
- CI：experiment integration 三次缓存构建包含 `inference-runtime`，生产栈启动并执行 `RUN_INFERENCE_INTEGRATION=1`；失败证据收集 runtime 日志，对 internal secret 脱敏并扫描泄漏。
- 真实生命周期：隔离 WSL Compose 项目使用 PostgreSQL 16、MinIO、真实 joblib-to-ONNX 转换、公共 API 注册/批准/创建/启停/预测；清空 runtime session 后 reconciliation 重载，预测一致，停止后返回 `DEPLOYMENT_NOT_READY`，审计存在且不含 records、S3 URI、secret 或 traceback。
- 生产问题 1：Linux 进程导入科学计算库后虚拟地址空间已超过固定 2 GiB，worker 再设置 `RLIMIT_AS=2 GiB` 导致 skl2onnx `MemoryError: std::bad_alloc`；改为 `max(4 GiB, current virtual memory + 2 GiB)`，保留 CPU 110 秒上限，并新增 Linux 回归。
- 生产问题 2：MinIO generator context manager 的宽泛异常捕获跨越 `yield`，把转换领域错误误包装成 Artifact 不可用；只包装下载和落盘阶段，消费者异常原样传播，并新增回归。
- 验证：Windows 聚焦 46 项通过、2 项按生产/Linux 门禁跳过；Linux ONNX/Storage 15/15；隔离生产生命周期 1/1；Alembic head=`20260718_08` 且 check 无差异；runtime 健康；隔离资源全清理，默认 Compose 容器未变。
- 遗留事项：Task 8 前端模型运维页、Task 9 Chromium 验收、Task 10 全量/文档/远程 CI 尚未完成。

### 2026-07-18：第八周 Task 8 模型运维前端完成

- Typed client：新增注册模型、版本、ONNX multipart、审批、部署启停与 named-record 推理的严格 TypeScript 类型和 URL/payload 契约；列表只归一数组或 `{items}`。
- 页面：`/models` 替换旧 Artifact 下载/批删页面，改为项目角色感知的注册模型/部署双 tab；提供逻辑模型、平台 joblib/直接 ONNX 版本注册、版本审批/拒绝、部署创建/启停、schema 生成 records、直接 JSON 推理和结果/概率/版本/耗时展示。
- 状态：表格支持 loading/empty/error；starting/stopping 显示 progress；failed 展示稳定 error code；viewer 只读，owner/editor 管理版本与部署，operator 操作推理。
- 可访问性与响应式：图标命令使用明确 `aria-label`，项目选择有可访问名称；表格使用稳定横向 scroll，Drawer/Modal 承载细节与命令，无嵌套卡片。
- 国际化：新增完全对称中英 `modelRegistry` 树，页面无硬编码可见中英文命令。
- 验证：新客户端/页面 5/5；全前端 17 文件、44/44；TypeScript/Vite production build；官方 npm registry audit 0 漏洞。开发镜像 npm mirror 不支持 audit endpoint，审计显式使用官方只读 endpoint。
- 遗留事项：Task 9 真实 Chromium 登录与完整 UI lifecycle，Task 10 后端/迁移/生产/远程 CI 和交付文档。

### 2026-07-18：第八周 Task 9 Chromium 模型推理验收完成

- Fixture：新增独立 Python fixture 脚本，直接使用生产 ORM/ArtifactService 在浏览器创建的项目内写入真实 TrainingJob、joblib Artifact 与 ModelLibrary provenance；未增加生产测试路由或授权绕过。
- 运行环境：Playwright Backend、fixture 与单 worker inference runtime 共享隔离 SQLite URL、local Artifact 目录和 32+ 字符 internal token。
- E2E：管理员真实登录，公共 API 创建项目，UI 新建逻辑模型、注册平台版本、批准 v1、创建/启动部署、提交 named records、验证概率与实际 v1、停止并验证 desired/observed 双状态。
- 可访问性修正：Ant Design 中文 Modal/Drawer 按钮因视觉字距产生 `创 建`/`推 理` accessible name；关键确认按钮显式设置业务 `aria-label`，自动化与屏幕阅读器不再依赖样式化文本拆分。
- TDD：fixture 缺失 RED；随后逐次通过 DOM snapshot 收窄 modal/drawer/row locator，无固定 sleep。
- 验证：目标 Chromium 1/1（17.8 秒）；完整 Chromium 2/2，新模型推理与既有焊接模板均通过。
- 遗留事项：Task 10 Week 8 最终 manifest 核对、全后端、迁移、隔离 WSL 生产、交付文档、推送和远程 CI。

### 2026-07-20：第八周 Task 10 最终验收完成

- 本地验证：Week 8 7/7 模块通过；配置回归 7/7；前端 17 个测试文件、44/44 用例、TypeScript/Vite 构建和官方 npm audit 通过；Chromium 2/2 通过。
- 隔离 WSL Compose：PostgreSQL 16、Redis/Celery、MinIO、MLflow、TensorBoard、inference-runtime、migrate、backend、worker、scheduler 全部健康；Alembic `20260718_08` upgrade/current/check 通过；实验恢复/TensorBoard 1/1、模型注册/推理运行时重启协调/停止 1/1；`/api/ready` 的 database、redis、celery、storage、mlflow、tensorboard、inference_runtime 均为 `OK`。
- 验收修正：首次手工 Compose 命令遗漏 `CELERY_RESULT_BACKEND`，造成 Celery `No result backend is configured`；按 CI 同等生产配置补齐后重跑通过。隔离项目及卷已由 trap 清理，默认 Compose 未修改。
- 当前状态：第八周代码、测试、文档和本地生产验收完成；待提交推送并取得远程 Actions 全绿证据后关闭发布流程。

### 2026-07-20：第八周远程 CI 合并前门禁修复

- 问题现象：PR #3 的实验生产集成在 Compose 插值阶段失败，生产集成在 Alembic 启动阶段失败。
- 已验证根因：实验任务未声明 Compose `migrate` 服务要求的 `INFERENCE_INTERNAL_SECRET`；生产迁移任务使用 `APP_MODE=production`，但未声明配置校验要求的 `INFERENCE_RUNTIME_URL`。
- 修复内容：在对应 GitHub Actions job 环境中补齐两个变量；新增 CI workflow 契约测试，防止必需运行时配置遗漏。
- 验证方式：CI 契约测试 9/9 通过；本地 `git diff --check` 通过；本机未安装 Docker，Compose 真实运行验证保留给远程 Actions。
- 当前状态：修复待推送并取得 PR #3 新一轮 Ubuntu、Windows、生产实验集成和生产集成全绿证据；取得证据后再合并 PR #3。

### 2026-07-20：第八周生产 readiness 回归修正

- 问题现象：补齐生产任务的 `INFERENCE_RUNTIME_URL` 后，生产栈测试的 HTTP 探针次数从 2 增至 3。
- 已验证根因：ReadinessService 已包含 inference runtime 检查；旧测试依赖 URL 缺失时该检查被跳过，未显式验证第三个探针。
- 修复内容：将测试改为验证 MLflow、TensorBoard 和 inference runtime 三个明确 URL，不再只依赖旧调用次数。
- 验证方式：readiness 和 CI workflow 相关测试 14/14、`compileall`、`git diff --check` 通过。
- 当前状态：修复待推送并以远程 production-integration 重新验收。

### 2026-07-20：第 1 至第 8 周合并与最终远程验收

- 当前周次：第 8 周收尾。
- 开发内容：完成第 5 周 PR #2 与第 6 至第 8 周 PR #3 的合并前门禁、合并和文档状态同步。
- 问题现象：首次 PR #3 远程 CI 因缺失生产运行时环境变量失败；补齐配置后，旧生产测试对 readiness 的固定调用次数断言失败。
- 根因：CI job 没有显式覆盖生产配置契约；旧测试隐式依赖缺失配置跳过推理运行时探针。
- 解决方法：补齐 workflow 环境变量与契约测试；将生产栈测试改为断言三个明确健康探针。
- 验证方式：Actions Run `29714469437` 的 Ubuntu、Windows、生产集成、实验集成和 Chromium acceptance 全部通过；PR #2 合并提交 `3c808f6`，PR #3 合并提交 `ba3ca98`。
- 影响范围：第 5 至第 8 周代码已进入 `main`，当前开发队列转入第 9 周。
- 预防措施：生产配置变更必须同步更新 CI 环境契约与 readiness 集成断言；合并前必须取得远程完整门禁通过证据。
- 遗留事项：第 9 周推理服务生产化功能尚未开始。
### 2026-07-20：Bug 清单第一轮修复与验证

- 完成事项：数据管理默认加载当前用户全部数据制品，预览、下载、删除和项目导出全部切换到制品 API；AutoML 改为使用数据制品 ID、数据列选择和训练任务轮询；知识库文档上传/删除改用实际路由；工作流版本支持删除；项目列表默认按创建时间倒序并可按名称或时间排序。
- 交互与可观测性：资源监控移除 Windows `wmic` 依赖并在前端请求失败时结束加载；驾驶舱每 15 秒刷新；工作流支持 Ctrl+C/Ctrl+V 单节点复制、Join 多键选择、算子名随语言动态切换；智能对话增加系统提示词和随机度配置。
- 验证方式：后端相关 API 51 项测试通过；前端 3 个 Vitest 文件 15 项测试通过；`npm run build` 成功；`git diff --check` 成功。
- 已知风险与遗留：本地 `LocalTaskDispatcher` 运行在 Python 线程，不能安全强制终止；生产 Celery 模式已使用 `revoke(terminate=True)`。若要在本地模式实现真正 kill，必须迁移到独立子进程并补充跨进程执行、资源回收和取消回归测试。全页面硬编码文本清理和真实浏览器工作流交互验收仍需继续。

### 2026-07-20：第 1-8 周与全局测试审计

- 测试用例：新增 `docs/week1-8-test-cases.md`，包含第 1-8 周 24 条验收用例和 9 条全局质量用例，覆盖业务链路、数据一致性、权限安全、工作流可靠性、前端质量、部署就绪性和性能边界。
- 自动化结果：后端隔离回归 `python run_suite.py` 46/46 模块通过；前端 Vitest 16 文件、41 用例通过；TypeScript/Vite 生产构建通过；Playwright 2/2 通过，覆盖焊接质量模板完整运行与 11 个核心认证路由加载。
- 缺陷修复：全局浏览器测试发现计算资源页面将 Axios 的 `/api` 基础路径重复拼接为 `/api/api/compute/*`，导致未处理 404；已改为 `/compute/*` 并在 E2E 中添加重复前缀失败断言，复测通过。
- 安全与部署：`npm audit --audit-level=high --registry=https://registry.npmjs.org` 为 0 vulnerabilities；Python `compileall` 通过。生产栈 `test_production_stack` 4 项因 `RUN_PRODUCTION_INTEGRATION` 未启用而跳过；当前机器未安装 Docker，未执行 PostgreSQL/Redis/MinIO/Celery 实测。
- 重要审计结论：当前源码与 `week_manifest.py` 只纳入第 1-5 周。未发现第 6 周实验/MLflow/TensorBoard、第 7 周 Pipeline/RBAC/审计、或第 8 周模型注册/部署/推理服务的实现与自动化模块；这些验收用例保留为待实现，不能计为已通过。待代码进入工作区后须将测试模块登记到第 6-8 周清单再运行完整验收。

### 2026-07-20：WSL Docker 生产集成复测

- 环境：WSL2 Docker Engine `29.6.2`、Docker Compose `5.3.1`。使用独立 Docker network、专用 PostgreSQL 端口 `55432`、Redis 端口 `56379`、MinIO 端口 `59000` 和独立数据库/桶，测试结束后已清理全部容器和网络。
- 环境修复：宿主 Python 缺少项目声明的 PostgreSQL 驱动 `psycopg[binary]`，安装 `3.2.13` 后完成真实 PostgreSQL 双次 Alembic 升级和 schema check。
- 结果：宿主源码生产用例中，数据库迁移幂等、MinIO round-trip、Celery 单次执行/Redis 事件共 3 项在 Linux Worker + 真实依赖组合下通过；宿主 readiness 因源码期望 Alembic `20260715_03` 而数据库/Worker 使用 `20260718_08` 返回 `DATABASE_UNAVAILABLE`，失败 1 项。
- 镜像复测：使用 `codexweek8final-worker:latest` 将专用库升级到 `20260718_08` 并运行镜像内测试，前 3 项通过；最后一项失败，原因是 readiness 外部依赖 HTTP 探测实际调用 3 次，而镜像内测试仍固定断言 2 次。
- 重要风险：当前宿主源码仅含 `20260715_03` 迁移和第 1-5 周测试清单，而本机第 8 周 Worker 镜像已包含 `20260718_08` 的实验、调度、权限、模型注册和推理代码。源码、镜像、迁移和测试版本不一致，不能将第 6-8 周标记为当前工作树已验收。需将第 6-8 周源码和测试同步回工作树，并将 readiness 探测断言改为与实际服务清单一致后复测。

### 2026-07-20：第 6-8 周版本一致性修复验证

- 根因确认：第 6-8 周实现位于 Git `main`（`20260718_08`），根工作树仍在其祖先分支；旧 `codexweek8final-worker` 镜像也早于 `main` 的 readiness 断言修复。
- 修复验证：从 `main` 创建隔离 worktree，后端第 6 周 `11/11`、第 7 周 `5/5`、第 8 周 `7/7` 模块均通过；前端 Vitest `17` 文件、`44` 用例通过，生产构建通过。
- WSL 生产验证：从同一 `main` 源码构建 `codex-week8-verified-worker`，使用独立 PostgreSQL、Redis、MinIO、网络、端口和测试桶；数据库升级至 `20260718_08`，真实生产栈 `test_production_stack` `4/4` 通过。测试资源已全部清理。
- 当前行动项：根工作树保留用户未提交代码、文档和制品，未强行切换或覆盖。需在保护这些修改的前提下，将根分支安全快进到 `main`，使日常运行源码、迁移、镜像和测试清单一致。

### 2026-07-20：主线同步与本地修改恢复完成

- 同步策略：先创建保护分支并将跟踪与未跟踪修改保存至 `codex-pre-main-sync-20260720`，再将根工作树更新至包含第 6 至第 8 周代码的 `main`，随后以 `git stash apply` 恢复用户修改。
- 冲突处理：项目排序合并到角色可见项目查询；训练接口与测试保留当前队列、实验追踪、审计和权限实现，未回退到旧线程式训练实现；其余数据制品、资源监控、工作流版本和前端交互修改均已恢复。
- 验证结果：后端聚焦接口回归 `40/40` 通过，前端 Vitest `19` 文件、`50` 用例通过，生产构建通过，Playwright `3/3` 通过（核心路由、模型推理、焊接模板）。
- 限制与后续：`run_suite.py --week 1` 受外层命令 120 秒限制中断，不能将该次完整套件计为通过；第 6 至第 8 周主线及隔离 WSL Docker 生产验收已在同步前完成。保留 stash 作为恢复备份，待人工确认工作树内容后再清理。

### 2026-07-20：Bug 清单第二轮修复

- AutoML：页面按所选项目加载实验并提交 `experiment_id`，与训练 API 的严格请求模型一致，消除因遗漏字段导致的提交失败。
- 工作流：节点运行状态、面板、工具栏、版本抽屉和删除确认弹窗随中英文设置切换；工作流启动后持久化 `task_id`，使生产 Celery 的 `revoke(terminate=True)` 能定位实际任务。
- 验证：后端 `test_api_runs`、`test_task_dispatcher`、`test_training` 共 14 项通过；前端工作流状态与版本 API 14 项通过，TypeScript/Vite 生产构建通过。
- 未完成：本地 `LocalTaskDispatcher` 仍采用线程，不能安全强杀当前算子；需要独立子进程和跨进程事件转发设计后再关闭该项。GPU 指标仍依赖宿主 `nvidia-smi`。

### 2026-07-20：第 9 至第 12 周并行开发设计确认

- 当前周次：第 9 至第 12 周同时启动，状态均为进行中。
- 审计结论：第 9 周现有部署仍固定单一模型版本，缺少发布修订、流量权重、滚动升级、回滚、生产 API Key、细粒度限流、调用日志、聚合指标和模型卡；第 10 周项目四角色与关键写操作审计已在第 7 周完成，后续不得重复建设。
- 已发现问题：公开注册允许客户端提交平台角色；Compute、Annotation 和 API Marketplace 存在按资源 ID 查询但未先验证归属的路径；成员管理在权限检查前查询目标，可能泄露用户名或成员状态。以上列为第 10 周首批安全回归范围。
- 确认设计：采用依赖感知三轨并行；第 9 周负责生产推理和领域事件，第 10 周负责资源授权、平台安全审计及站内、企业微信、邮件、通用 Webhook 通知，第 11-12 周先行建设性能、安全、备份恢复、升级和验收工具。
- 数据与迁移：推理发布使用不可变 revision、target 和持久 rollout；通知使用事务 Outbox、订阅、投递尝试和 dead-letter；Alembic 保持单一线性 revision，第 10 周迁移基于第 9 周迁移。
- 验收边界：第 11 周最终性能结论等待第 9-10 周接口冻结；第 12 周最终验收等待第 9-11 周全部门禁通过。并行启动不代表可提前标记完成。
- 验证方式：第 7 周后端清单 `5/5`、第 8 周后端清单 `7/7`、模型注册前端聚焦用例 `5/5` 通过；设计规格已完成占位符、矛盾、依赖和验收映射自审。真实 Compose 本次设计阶段未启动。
- 未完成：等待用户审阅正式设计规格；之后编写逐任务实施计划，并按 TDD 开始生产代码、迁移、前端、集成和验收实现。

### 2026-07-20：第 9 至第 12 周实施计划完成

- 规格状态：用户已审阅并确认 `docs/superpowers/specs/2026-07-20-week9-12-mlops-core-design.md`，设计提交为 `03c4a09`。
- 第 9 周计划：`docs/superpowers/plans/2026-07-20-week9-production-inference.md`，共 11 个任务、63 个 TDD 微步骤；迁移固定为 `20260720_09_production_inference`，线性继承 `20260718_08`。
- 第 10 周计划：`docs/superpowers/plans/2026-07-20-week10-security-notifications.md`，共 12 个任务、72 个 TDD 微步骤；迁移固定为 `20260720_10_security_notifications`，线性继承第 9 周 revision。
- 第 11-12 周计划：`docs/superpowers/plans/2026-07-20-week11-12-integration-acceptance.md`，共 14 个任务、60 个微步骤；Task 1-6 可立即执行，依赖冻结和最终验收任务保留明确门禁。
- 跨轨契约：第 9 周在 `app/events/domain.py` 定义冻结的 `DomainEvent` 和 `DomainEventRecorder.record(db, event)`；第 10 周 Outbox 实现只 add/flush，不拥有提交；第 11-12 周只消费冻结路由和迁移版本。
- 自审修正：统一第 10 周任务标题格式；将验收计划中的临时推理和通知测试路径修正为第 9/10 周精确 API；确认 37 个任务编号连续、195 个步骤、代码围栏成对、无实现省略号或禁用占位内容。
- 验证方式：三份计划 `git diff --check`、迁移链、事件签名、四通知通道、模型卡、性能/备份/升级/安全/E2E 规格映射检查通过。计划阶段未修改生产代码，未运行真实 Compose。
- 未完成：按选定执行模式进入 TDD 实现；第 9/10 周功能轨和第 11-12 周独立工具轨可并行，公共 CI、Compose、manifest、Alembic 链和状态文档由主线串行集成。

### 2026-07-21：第 9 周 Task 3 安全领域事件契约完成

- 完成：`DomainEvent` 冻结协议、空记录器、事件类型/载荷 allowlist、递归深冻结及存储序列化边界；默认记录器不提交事务。
- 修复：事件载荷拒绝 UUID、自定义对象、集合、非字符串键及 `NaN`/`+Inf`/`-Inf`，避免异步存储阶段序列化失败或产生非标准 JSON。
- 验证：domain smoke、模型/数据库 `32/32`、compileall、diff check 通过；完整 rollout 测试待 Task 6 服务落地后复跑。
- 后续：Task 4 实现 API Key 生命周期与 Redis 失败关闭限流。

### 2026-07-21：第 9 周 Task 4 API Key 与失败关闭限流完成

- 完成：PBKDF2 单次展示 API Key、部署/范围/过期/撤销校验、同事务轮换及安全列表 DTO；Redis 单 Lua 令牌桶使用 Redis 时间、原子 refill/consume/TTL 和 retry-after。
- 安全：Redis 连接、超时及脚本异常统一为 `RATE_LIMIT_BACKEND_UNAVAILABLE`，无内存降级或默认放行；公开列表不含密钥哈希或明文。
- 验证：`test_inference_api_keys`、`test_inference_rate_limit`、`test_config` `27/27` 通过；扩展聚焦集 `40/40`、compileall、diff check 通过，规格与质量双审通过。
- 后续：Task 5 建设请求脱敏日志、分钟指标、留存与模型卡。

### 2026-07-25：第 9 周 Task 5 可观测性与模型卡完成

- 完成：请求日志 allowlist 脱敏、分钟指标桶、固定延迟直方图/百分位、查询边界、留存清理，以及模型卡生成、系统字段保护、指导版本化和安全导出。
- 修复：分钟桶首次写入采用保存点冲突恢复，避免并发请求在唯一键上失败；模型卡 lineage 仅接受稳定标量，拒绝嵌套数据、URI、凭据和未知来源值。
- 验证：`test_inference_observability`、`test_model_cards`、`test_model_registry_service` `24/24` 通过；compileall、diff check 通过；规格复核缺陷已修复。
- 当前状态：Task 5 完成；Task 6 开始实现加权路由和持久 rollout CAS。

### 2026-07-21：第 9 周 Task 1 RED 合同边界完成

- 开发环境：在 `.worktrees/week9-12-mlops-core` 的 `codex/week9-12-mlops-core` 隔离分支执行；基线后端 `68/68` 模块、前端 `19/19` 文件 `50/50` 用例和生产构建通过。本机 Python 3.13/Node 24 与 CI Python 3.11/Node 20 的差异保留为后续远程门禁。
- 完成内容：新增第 9 周七个生产推理合同测试模块并登记 `week_manifest.py`，覆盖发布模型、滚动状态、API Key、Redis 限流、脱敏日志与指标、模型卡和生产推理 API。
- TDD 证据：七个新模块均按预期 RED，失败原因仅为第 9 周生产实体、服务和路由尚未实现；`test_suite_manifest` `1/1`、`compileall` 和 `git diff --check` 通过。
- 审查修正：统一 API Key 稳定错误码和请求头；补齐错误密钥、作用域、过期、撤销、轮换和安全 DTO；可观测状态固定为 `success/error/limited`；日志与 API Key 持久字段、公开序列化改用精确 allowlist；模型卡补齐血缘、制品、发布状态和安全导出合同。
- 审查结论：规格审查通过；代码质量复审无 Critical、Important 或 Minor 问题，最终提交为 `63b7e3c`。
- 未完成：Task 2 根据 RED 合同实现七张生产推理表和线性 Alembic `20260720_09_production_inference`；当前第 9 周整体保持进行中。

### 2026-07-21：第 9 周 Task 2 生产推理持久化完成

- 完成内容：新增 `DeploymentRevision`、`DeploymentTarget`、`DeploymentRollout`、`InferenceApiKey`、`InferenceRequestLog`、`InferenceMetricBucket` 和 `ModelCard` 七张表及 ORM 导出；迁移 `20260720_09_production_inference` 线性继承 `20260718_08`。
- 数据迁移：确定性回填每个旧部署的稳定 revision/10000 基点 target 和每个模型版本的 model card；空库、 populated DB、双次 upgrade、`alembic check`、完整 downgrade 均通过，Week 8 行未被破坏。
- 安全边界：API Key 只保留 PBKDF2 hash 和生命周期元数据；日志列为精确 allowlist；ModelCard lineage 只保留安全 ID/Schema/指标/审批字段，不复制 credentials 或 storage URI；`InferenceRequestLog.status` 不设置默认值，必须显式写入 `success/error/limited`。
- 验证方式：模型/迁移聚焦回归 `32/32`、compileall、API model-registry/project-access 回归通过；独立规格审查和质量审查均通过。`tests.test_model_cards` 暂因 Task 1 的 `app.services.model_cards` 尚未实现而无法导入，这是已知下游依赖，不计为 Task 2 失败。
- 提交：实现 `d60dc19`，ModelCard/default 修复 `c922980`，显式状态修复 `6f4b57e`；当前第 9 周整体保持进行中。
### 2026-07-21：第九周 Task 2 模型卡持久化复审修正

- 发现：模型卡缺少批准设计要求的 `intended_use` 与 `limitations`，且 Week 9 迁移中多个 ORM 默认值未落到数据库服务器默认。
- 修复：新增非空 4000 字符字段并以空字符串回填；为发布状态、rollout 状态/版本、API Key scopes、请求日志状态、指标计数/JSON 和模型卡 JSON/文本字段补齐服务器默认；回填路径显式写入模型卡字段。
- 验证：生产推理模型测试 12/12、数据库生产测试 18/18、迁移升级/降级/幂等和 legacy backfill 通过；`compileall`、`git diff --check` 通过。模型卡服务合同仍依赖 Task 1 后续实现。
- 未完成：Task 2 代码需由主线合并后与模型卡服务和完整 Week 9 测试联调。

### 2026-07-21：第 9 周 Task 3 领域事件 payload 深冻结修正

- 问题现象：`DomainEvent` 仅冻结顶层 `MappingProxyType`；调用方保留的 `model_version_ids` 列表或嵌套字典仍可变，可能在事件创建后改变已记录 payload。
- 根因：payload 过滤只复制顶层字典，没有递归复制和冻结嵌套容器。
- 解决结果：增加递归 `_deep_freeze`；嵌套 Mapping 转不可变 mapping、list/tuple 转 tuple，标量保持原值；新增列表来源变更和事件嵌套写入回归测试。
- 验证方式：独立 domain deep-freeze contract 通过；模型/数据库聚焦回归 32/32；`compileall` 和 `git diff --check` 通过。`test_inference_rollout` 仍因 Task 4 `app.services.inference_rollout` 尚未实现而无法收集，属于已知下游依赖。
- 影响范围：第 9 周领域事件安全 payload，不改变事件类型白名单或安全键过滤。
- 预防措施：不可变事件必须递归复制所有嵌套 Mapping 和序列；新增 payload 字段同时覆盖来源对象和事件对象两侧 mutation 测试。
- 遗留事项：待 Task 4 rollout 服务完成后运行完整 `test_inference_rollout` 和 Week 9 套件。

### 2026-07-21：第 9 周 Task 3 事件存储序列化补充

- 问题现象：递归冻结后 `MappingProxyType` 和 tuple 不能直接由 `json.dumps` 或 SQLAlchemy JSON 绑定，Outbox/持久化消费者缺少明确转换入口。
- 根因：事件 payload 的内存不可变表示与 JSON/数据库所需的可变纯容器表示不同，不能直接复用冻结对象。
- 解决结果：新增 `to_storage_payload` 公共递归序列化器；Mapping 转新 dict，list/tuple 转新 list，标量保持原值；输出不共享事件内部引用。
- 验证方式：新增 serializer contract，检查 plain dict/list、`json.dumps`、修改 serializer 结果不影响事件；domain contract、模型/数据库 `32/32`、compileall 和 diff check 通过。
- 影响范围：第 9 周事件 Outbox/存储边界；不会放松 DomainEvent 的深不可变约束。
- 遗留事项：Task 4 完成后需在真实事件记录器测试中使用 `to_storage_payload`，禁止直接将 `event.payload` 交给 JSON/SQLAlchemy。

### 2026-07-21：第 9 周 Task 3 payload JSON 类型校验

- 问题现象：冻结事件虽可安全存储，但 UUID、set、自定义对象等非 JSON 值仍可能进入 payload，直到 Outbox 序列化阶段才失败。
- 根因：深冻结只处理容器可变性，没有冻结 payload 的值域和 Mapping key 类型。
- 解决结果：增加递归 JSON-native 校验；允许 None/bool/int/float/str、字符串键 Mapping、list/tuple，其他值统一抛出 `DOMAIN_EVENT_PAYLOAD_INVALID`；保留安全键过滤。
- 验证方式：新增有效字符串 ID/int step 和 UUID/set/非字符串键/自定义对象拒绝回归；domain smoke、模型/数据库 `32/32`、compileall、diff check 通过。
- 影响范围：第 9 周事件构造和第 10 周 Outbox 输入契约；不改变事件类型白名单或存储 thaw API。
- 遗留事项：Task 4 完成后运行完整 rollout 和 Week 9 套件，确认所有生产事件使用 JSON-native payload。

### 2026-07-21：第 9 周 Task 3 非有限浮点 payload 修正

- 问题现象：Python `float` 值域包含 NaN、正无穷和负无穷；这些值会通过基本 float 类型校验，但不是严格 JSON 值。
- 根因：JSON-native 类型校验没有同时约束 float 的有限性。
- 解决结果：使用 `math.isfinite` 在冻结前拒绝 NaN、正无穷和负无穷，统一返回 `DOMAIN_EVENT_PAYLOAD_INVALID`；有限 float 继续允许。
- 验证方式：三种非有限值及有限 `2.5` 回归，domain smoke、模型/数据库 `32/32`、compileall 和 diff check 通过。
- 遗留事项：Task 4 完成后运行完整 rollout 和 Week 9 套件。

### 2026-07-25：第 9 周 Task 6 加权路由与持久 Rollout 完成

- 当前周次：第 9 至第 12 周并行开发；Task 6 已完成，第 9 周整体仍进行中。
- 开发内容：完成 `WeightedTargetRouter` 稳定基点哈希和两阶段 revision/target 路由；完成 candidate 创建、预加载、健康阈值、0/10/50/100 流量步骤、暂停/恢复、CAS 推进、回滚和重启 reconcile；runtime 以 `runtime_key` 支持同一部署多 revision 共存，并保留 Week 8 legacy 兼容。
- 问题现象：completed rollback 先恢复 legacy stable 后，candidate alias 清理失败会使事务回滚到 candidate stable；数据库路由、legacy runtime 和 candidate alias 可能不一致。远端已删除但客户端超时也会触发同一风险。
- 根因：不可逆的 runtime alias drain 与 rollback 状态提交位于同一异常边界，清理失败被错误当作 rollback 失败处理。
- 解决方法：先提交旧 stable revision、rollout `rolled_back` 和部署运行状态，再逐个 best-effort unload candidate alias；单个 drain 失败不回滚已提交的 stable 路由，后续由 reconcile 清理残留 alias。补充 drain 删除前失败和删除后超时回归。
- 验证方式：`test_inference_rollout`、`test_inference_runtime`、`test_inference_deployment` 独立回归 `50/50`；扩展 Task 6 相关五模块（含生产模型和 Celery 兼容）`74/74`；`C:\Users\17723\miniconda3\python.exe -m compileall -q app` 通过；`git diff --check` 通过。Week 9 清单前 6 个模块通过，`test_api_inference_production` 因 Task 7 路由尚未实施而导入失败，属于已知下游门禁，不计为 Task 6 失败。规格复审无新增 P0-P2，代码质量复审无 Critical/Important/Minor。
- 影响范围：`inference_rollout.py`、部署服务/runtime compatibility、rollout/runtime/deployment 测试，以及第 9 周实施计划和状态记录；未启动 Task 7 API、Task 8 Celery rollout、Task 9 UI、Task 10 生产/Chromium 或 Task 11 最终验收。
- 预防措施：跨数据库与 runtime 的不可逆操作必须拆成可提交状态边界；候选 alias 清理只能是可重试补偿，不得决定已完成 rollback 的数据库状态；每个 runtime key 的删除前/删除后异常都要有回归，状态机命令继续使用单一 `lock_version` CAS。
- 遗留事项：Task 7 严格控制面/生产预测 API 尚未开始，因此完整 Week 9、真实 PostgreSQL/Redis/MinIO/runtime、Chromium 和远程 CI 证据仍未完成；Task 7 完成前不标记第 9 周整体完成。

### 2026-07-26：第 9 周 Task 7 严格控制面与生产预测 API 完成

- 当前周次：第 9 至第 12 周并行开发；Task 7 已完成，第 9 周整体仍进行中。
- 开发内容：完成 canonical `/rollouts` 控制面、严格请求/查询模型、API Key 生命周期管理、生产预测 API 的 1 MiB 实际字节上限、稳定错误映射、项目角色边界和机器可检验审计动作清单。
- 问题现象：completed rollback 在 runtime 已切回旧 revision 并 drain candidate alias 后，若审计事务提交失败，数据库回滚会保留 candidate 为 stable，但补偿只恢复 legacy runtime key，生产加权路由会指向缺失的 durable candidate alias。
- 根因：审计提交回滚属于数据库与 runtime 的跨边界失败；legacy compatibility key 和 revision-target aliases 被当作同一 runtime 状态，但原补偿只恢复了前者。
- 解决结果：回滚命令使用 caller-owned transaction，运行时变更后的审计提交失败触发 durable-state reconciliation；该补偿先预加载数据库 stable revision 的全部 target aliases，再恢复 legacy key。API Key 仅 owner/editor 管理；owner/editor 创建 rollout，operator 可暂停、恢复和回滚，符合已冻结的 Week 9 权限矩阵。
- 验证方式：新增真实 HTTP 审计提交失败回归，先 RED 于 candidate alias 缺失，再 GREEN；`test_inference_rollout`、`test_api_model_registry`、`test_api_project_access`、`test_api_inference_production` 组合 `69/69` 通过；`python run_suite.py --week 9` 为 `7/7` 模块通过；生产模块导入 `2/2`、`compileall`、`git diff --check` 通过。已提交 `1c04d4f`。
- 影响范围：production inference API、model registry rollout/key routes、rollout runtime reconciliation，以及对应 API/角色/服务回归；不修改第 10 周 Outbox、通知或迁移链。
- 预防措施：任何审计拥有提交权而 runtime 已发生外部变更的命令，必须从持久数据库状态恢复 legacy key 与全部可路由 aliases；回归应同时覆盖审计提交失败、runtime compatibility key 和 revision target routing。
- 遗留事项：Task 8 Celery rollout/retention、Task 9 前端、Task 10 真实生产/Chromium、Task 11 文档和远程 CI 未开始；第 9 周不得提前标记完成。

### 2026-07-26：第 9 周 Task 8 Celery Rollout 与 Telemetry Retention 完成

- 当前周次：第 9 至第 12 周并行开发；Task 8 已完成，第 9 周整体仍进行中。
- 开发内容：新增稳定 Celery 任务 `ml_platform.advance_inference_rollout`、`ml_platform.rollback_inference_rollout`、`ml_platform.reconcile_inference_rollouts` 和 `ml_platform.prune_inference_telemetry`；新增 60 秒 rollout reconciliation 与每日 telemetry retention Beat。
- 问题现象：原 `reconcile_inference_deployments` 同时执行 deployment 和 rollout reconciliation；新增独立 rollout Beat 后会在同一周期重复预加载或推进 rollout。telemetry 清理任务也会忽略部署环境覆盖的日志留存配置。
- 根因：deployment recovery 与 release lifecycle 使用同一个周期任务，且 retention service 的默认值没有在异步任务边界显式接收 Settings。
- 解决结果：deployment Beat 只恢复 deployment runtime；rollout Beat 仅对 pending/preloading 状态执行恢复，再对 progressing 状态按持久 `lock_version` CAS 推进 0/10/50/100，冲突投递返回数据库持久状态且不吞未知异常。清理任务以 `settings.inference_log_retention_days` 初始化 `InferenceObservability` 并在删除后提交。
- 验证方式：稳定任务/Beat RED 后 GREEN；新增配置留存 RED 后 GREEN。`tests.test_celery_workflows tests.test_inference_deployment tests.test_inference_observability` 为 34/34；`python run_suite.py --week 9` 为 7/7 模块；生产模块导入 2/2、`compileall`、`git diff --check` 通过。实现提交为 `ba65509`，配置一致性修复待本任务文档提交一并保存。
- 影响范围：Celery Worker/Beat 注册、生产推理 rollout 生命周期和日志/指标定期删除；不修改 rollout 数据模型、公共 API、Week 10 Outbox 或 Alembic 链。
- 预防措施：不同事实源的 reconciliation 必须拆成独立周期任务；任何会触发 runtime 副作用的 rollout 命令必须携带数据库 CAS 版本；后台留存任务必须显式传入与 API 相同的 Settings 值。
- 遗留事项：Task 9 前端生产运维、Task 10 隔离生产栈/Chromium、Task 11 最终文档和远程 CI 未开始；第 9 周不能提前标记完成。

### 2026-07-26：第 9 周 Task 8 复审纠正：Rollout alias 恢复所有权

- 问题现象：Task 8 初版虽然拆出 deployment 与 rollout Beat，但 deployment service 仍会加载 active rollout candidate alias；progressing rollout 在 candidate alias 丢失时也可能直接进入下一流量步骤，导致 runtime key 不存在。
- 根因：两个状态机共享 deployment service 的 runtime 加载副作用；rollout Beat 只在 pending/preloading 行存在时调用 reconcile，未把 progressing 行的 alias 清单恢复作为 advance 前置条件。
- 解决结果：`InferenceDeploymentService.reconcile(..., include_rollout_aliases=False)` 默认只恢复 legacy/stable deployment runtime，candidate alias 保留在 expected 集合但不加载；`InferenceRolloutService.reconcile` 读取 runtime `list()`，仅加载缺失 target alias，并在恢复失败时将 rollout 置为 failed；rollout Beat 每 tick 先 reconcile，再查询并推进仍为 progressing 的记录。
- TDD 与验证：deployment Beat 参数、Beat 调用顺序、candidate alias 所有权和 progressing alias 恢复回归均先 RED；随后 `tests.test_celery_workflows tests.test_inference_deployment tests.test_inference_rollout tests.test_inference_observability` 为 `69/69`，`compileall`、`git diff --check` 通过。
- 影响范围：`ml-platform/backend/app/tasks/inference_tasks.py`、`app/services/inference_deployment.py`、`app/services/inference_rollout.py` 及三组后端回归；不修改 Week 10 通知、迁移、公共 API 或前端 Task 9 文件。
- 预防措施：周期任务必须按状态机明确 runtime 副作用所有者；任何会影响 weighted routing 的 progressing rollout，在 advance 前必须以 runtime 清单恢复全部可路由 alias；已存在 alias 的 reconciliation 必须验证零重复 load。
- 遗留事项：Task 9 前端生产运维、Task 10 隔离生产栈/Chromium、Task 11 最终文档和远程 CI 未开始；第 9 周整体仍不能提前标记完成。

### 2026-07-27：第 9 周 Task 9 前端生产运维本地完成

- 当前周次：第 9 至第 12 周并行开发；Task 9 已完成本地实现与验证，第 9 周整体仍进行中。
- 开发内容：模型运维页新增发布操作抽屉、加权目标和进度、暂停/恢复/回滚确认、一次性 API Key 创建与轮换展示、24 小时指标汇总、脱敏请求日志分页及模型卡查看、导出和指导更新；typed client 覆盖 rollout、API Key、metrics、logs 和 model card 合同。
- 问题现象：异步切换两个 deployment 时，较慢的旧请求可覆盖新抽屉数据；省略 CAS 版本时 FastAPI command body 为空会返回 422；指标只读取首个 100 分钟页；API Key 轮换的旧记录和新 ID 容易错误替换；创建 key 的迟到响应可在新抽屉显示旧明文；已过期 key 被显示为有效；发布 `pending` 复用模型审批的中文状态词。
- 根因：操作抽屉缺少所有异步命令的请求世代保护，客户端把可选 command payload 省略为无 body，遥测和轮换 UI 误把分页或生命周期视为单条本地状态，key 状态只判断撤销而未判断 expiry，通用和生产状态词由同一 renderer 选择。
- 解决方法：以 deployment/request generation 拒绝过期异步结果；无 lock version 时发送 `{}`；24 小时窗口汇总所有 metric pages；轮换后保留一次性明文并刷新服务端 key metadata；创建 key 仅在当前 generation 写入 UI；空日志探测页保持前页；过期 key 标记并禁用轮换；rollout/log 专用 renderer 使用 production statusLabels，模型审批和部署继续使用通用状态词，并补齐中英文 pending/failed/expired 词条。viewer 只读，operator 可操作现有发布，owner/editor 仍独占发布创建和 API Key 管理。
- 验证方式：新增竞态、空 command body、metrics 全分页、key distinct ID、过期 key、日志分页边界、角色显示、状态翻译、rollback、一次性密钥和模型卡回归；聚焦 Vitest `18/18`，前端全量 Vitest `19/19` 文件、`63/63` 用例，TypeScript/Vite production build，`git diff --check` 均通过。构建仍有既有 ECharts chunk 大小警告。
- 影响范围：`frontend/src/api/modelRegistry.ts`、ModelLibraryPage、对应 Vitest 与 i18n；未修改 Week 10 Outbox、Alembic、Compose 或 CI。
- 预防措施：跨 deployment 异步视图必须携带请求世代；可选 JSON command body 仍发送空对象；分页时间窗口的聚合不得使用单页 summary；同名状态在不同领域必须由对应 renderer 选择专属 i18n namespace；一次性密钥永不写入日志或持久状态，过期 key 不得被呈现为可轮换。
- 遗留事项：Task 10 真实 PostgreSQL/Redis/MinIO/runtime 生命周期和 Chromium 验收、Task 11 交付文档及远程 CI 仍未开始；本地前端验证不能代替真实生产栈或远程门禁。

### 2026-07-27：第 9 周 Task 9 复审纠正：关闭运维抽屉的密钥竞态

- 当前周次：第 9 至第 12 周并行开发；Task 9 仍仅完成本地前端实现与验证。
- 问题现象：点击创建 API Key 后关闭发布运维抽屉，若创建响应在关闭后才返回，一次性明文仍会在抽屉外弹出。
- 根因：抽屉关闭没有使 `operationsRequestRef` 失效，创建命令持有的 generation 仍被视为当前；`createdKey` 也没有在该资源边界清除。
- 解决方法：抽屉 `onClose` 递增请求 generation 并清除 `createdKey`，使加载、创建和轮换的迟到响应不能写入已关闭的资源视图。
- 验证方式：新增 deferred API Key 创建回归，旧实现稳定显示 `closed-once-only` 而 RED；修复后 `ModelLibraryPage.test.tsx` 13/13 通过。
- 影响范围：仅 `ModelLibraryPage` 短生命周期运维状态；不改变 API Key 后端生命周期或服务端密钥记录。
- 预防措施：资源抽屉关闭与资源切换都必须取消或失效所有异步世代，并删除与该资源绑定的一次性凭据状态。
- 遗留事项：仍需完成 Task 10 真实栈/Chromium，以及 Task 11 文档和远程 CI 门禁。

### 2026-07-27：第 9 周 Task 11 前端依赖审计受限例外

- 当前周次：第 9 周，整体仍为进行中。
- 问题现象：官方 registry 的 `npm audit --audit-level=high` 在 `react-router-dom@7.18.1` 下报告 2 个 React Router RSC Mode CSRF high；audit 建议强制降级至 `7.11.0`。
- 根因：React Router advisories 的受影响范围互相跨版本；实际安装 `7.11.0` 后 audit 报告 14 个更早 high，不能把降级当成安全修复。当前前端是 Vite `BrowserRouter` SPA，源码不包含 React Router server/RSC/SSR 导入或 Action/Server Action 路径。
- 解决方法：保留 7.18.1，记录严格受限例外；任何 RSC、SSR、prerender、server handler 或 Action/Server Action 引入必须先重新评估依赖。出现不含这些 advisories 的兼容版本后，恢复 audit 零 high 门禁。
- 验证方式：`npm ls react-router react-router-dom` 确认均为 `7.18.1`；源码扫描仅命中 `BrowserRouter` 和普通客户端导航 API；全量 Vitest、production build 和 Chromium 仍作为依赖变更后的强制回归。
- 影响范围：仅前端依赖审计状态；不改变 FastAPI 服务端、推理 API 或生产运行时安全边界。
- 遗留事项：本地 audit 不计为通过；远程 CI、完整回归、提交和合并仍是第 9 周完成门禁。

### 2026-07-27：第 9 周 Task 11 失败证据异常路径复审修正

- 当前周次：第 9 周，整体仍为进行中。
- 问题现象：CI 原始日志已在复制前完成敏感扫描，但 `cp` 或 `sed` 失败时 EXIT trap 只删除 raw 目录；redacted 目录可能保留未脱敏副本并被后续 `if: failure()` artifact 上传。
- 根因：失败清理只覆盖原始目录，没有把“复制已发生、脱敏未完成”的中间目录视为敏感边界。
- 解决方法：`cleanup_experiment_evidence` 在异常退出时同时删除 raw 和 redacted 目录；成功路径仅在 raw 删除后解除 trap，保留已经完成脱敏的 artifact。
- 验证方式：先增加 trap 清理契约，旧 workflow 稳定 RED；修复后 `tests.test_ci_workflow` 12/12 GREEN，YAML/Bash 静态检查和 `git diff --check` 待本次提交前复验。
- 预防措施：任何“copy then redact”工作流都必须把目标目录在 redaction 成功前视为敏感临时数据；上传条件不能只依赖 job failure，必须保证失败清理覆盖所有可上传目录。
- 遗留事项：远程 GitHub Actions 仍需以真实失败证据路径验证。

### 2026-07-27：第 10 周 Task 1 安全回归合同冻结（RED）

- 当前周次：第 10 周，整体仍为进行中；本项只冻结后续硬化必须满足的回归边界。
- 开发内容：新增隔离 SQLite 的 `test_security_hardening`，覆盖公开注册 role 注入、默认 engineer、Compute/Annotation/Platform API 的 owner/outsider 访问矩阵、Annotation sample/auto-label 隐藏语义，以及 Platform API 列表认证与私有行隔离；现有 Week 1 用户、计算和 API Marketplace fixture 改为直接数据库 bootstrap admin，不再依赖公开注册创建管理员。
- 问题现象：公开注册仍接受 `role=admin`；Compute、Annotation 和 Platform API 的外部资源路径未统一在业务访问前按 owner 过滤；Platform API 列表可匿名读取私有记录。
- 根因：注册路由以独立 Body 参数暴露 platform role，用户私有资源路由各自查询目标行，缺少集中 fail-closed resolver；遗留测试 fixture 将公开注册误作管理员初始化入口。
- 解决方法：本 Task 先以测试合同固定行为，生产修复留给 Task 2 的严格注册/平台审计和 Task 3 的 `ResourceAccessService`，避免在 RED 阶段混入实现。
- 验证方式：`C:\Users\17723\miniconda3\python.exe -m unittest tests.test_security_hardening tests.test_api_users tests.test_api_compute tests.test_api_platform -v` 独立复跑为 36 项，其中 10 个预期 RED（role 注入、未认证列表、私有泄露、外部资源越权及缺少 detail 路由），26 项既有兼容测试通过；`git diff --check` 通过。
- 影响范围：仅四个后端测试文件；无生产代码、迁移、通知、Compose 或 CI 变更。
- 预防措施：公开注册与平台 bootstrap 必须分离；每个用户私有资源新增或修改路由时，先以 owner/outsider 表驱动合同冻结 200/404 语义，再实现访问控制。
- 遗留事项：Task 2-3 必须使本合同 GREEN，并补齐平台 audit 模型、线性 migration 和集中资源解析；Week 10 不能在此之前标记完成。

### 2026-07-27：第 10 周 Task 5 通知设置、持久化模型与线性迁移完成

- 当前周次：第 10 周，整体仍为进行中；Task 5 已完成，后续进入 Task 6 加密、SSRF 防护和通道适配器。
- 开发内容：增加生产必需的 Fernet 通知主密钥及文件解析、SMTP/投递/安全 Webhook 配置；新增 `NotificationEndpoint`、`NotificationSubscription`、`NotificationOutbox`、`NotificationDelivery` 和 `InAppNotification` 模型；线性 Alembic `20260720_10_security_notifications` 同时持久化平台安全审计和五张通知表。
- 安全边界：通知主密钥、SMTP 用户名和密码均为排除序列化的 `SecretStr`；生产模式验证 Fernet 密钥；公开环境样例不含真实密钥、邮箱、企业微信 Token 或回调地址；端点种类、严重级别、状态、尝试次数、唯一事件/投递键及删除语义均由模型和迁移约束。
- 问题现象：既有生产配置脱敏测试把通用字符串 `password` 当作凭据值；新增安全摘要合法包含字段名 `smtp_password_configured` 后产生假失败。
- 根因：测试用过于通用的子串验证“不泄漏”，无法区分真实值与安全元数据的字段名。
- 解决方法：使用唯一测试凭据标记，并显式覆盖 SMTP 用户名/密码在 `repr`、`model_dump` 和安全摘要中不泄漏；未弱化任何生产脱敏字段。
- 验证方式：Task 5 初始 RED 为 3 个预期失败和 3 个 skip；GREEN 后 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_notification_models tests.test_config tests.test_experiment_config tests.test_database_production -v` 为 51/51，通过空库 upgrade/check/downgrade/re-upgrade，`alembic check` 输出 `No new upgrade operations detected`。
- 遗留事项：Task 6 必须实现加密配置、WeCom/邮件/Webhook SSRF 边界和适配器；Task 7 负责将冻结 Week 9 事件写入 Outbox，且记录器只 add/flush，不拥有提交。

### 2026-07-27：第 10 周 Task 6 加密、SSRF 防护与四通道适配器完成

- 当前周次：第 10 周，整体仍为进行中；Task 6 已完成，后续进入 Task 7 领域事件与事务 Outbox。
- 开发内容：新增 Fernet endpoint 配置加密/解密边界、严格 HTTPS DNS/IP Webhook 策略、官方 WeCom 目标校验、确定性 JSON/HMAC 签名、TLS SMTP 邮件和站内通知适配器；通道路由只接受冻结 `DomainEvent` 的安全信封。
- 安全边界：拒绝 loopback、私网、link-local、metadata、userinfo、fragment、非 443 端口和重定向；私网 relay 只能由精确平台 allowlist 放行；请求体限制 64 KiB；Webhook 自定义 header 不能覆盖 Content-Type、Idempotency-Key 或签名；端点密文、SMTP 凭据、签名密钥、provider body 和原始异常均不记录。
- 问题现象：初版允许自定义 header 覆盖路由保留的幂等键，也把抄送地址并入 `To` 而没有保留 RFC `Cc` 语义；缺少通知主密钥也与损坏密文共用同一错误码。
- 根因：自定义 header 未区分协议保留字段；邮件模型只汇总最终收件人；路由解密边界未区分环境缺失和数据损坏。
- 解决方法：冻结保留 header 集并以失败结果阻止发送；保留独立 To/Cc header 而仍向两者投递；主密钥缺失返回 `NOTIFICATION_CREDENTIAL_UNAVAILABLE`，损坏密文保留 `NOTIFICATION_CREDENTIAL_INVALID`。
- 验证方式：初始 RED 为 1 个模块可用性失败、11 个 skip；随后追加 header、Cc 和错误码 RED 后分别 GREEN。`C:\Users\17723\miniconda3\python.exe -m unittest tests.test_notification_channels -v` 为 14/14，通知/配置/实验配置/生产迁移组合为 65/65，`compileall` 与 `git diff --check` 通过。
- 遗留事项：Task 7 将 `DomainEvent` 安全载荷写入同一业务事务的 Outbox；记录器只 add/flush，不能 commit 或直接投递 Celery。

### 2026-07-27：第 10 周 Task 7 Week 9 事件记录器与事务 Outbox 完成

- 当前周次：第 10 周，整体仍为进行中；Task 7 已完成本地实现与验证，Task 8 的领取、投递、重试和死信处理尚未开始。
- 开发内容：新增 `OutboxDomainEventRecorder`，将冻结 `DomainEvent` 的存储副本以同一调用方事务写入 `NotificationOutbox`；API rollout 工厂从应用状态注入记录器，Celery rollout 工厂使用具体记录器，生产应用默认配置具体记录器。
- 问题现象：Week 9 rollout 失败事件使用 `severity="error"`，而已冻结的通知表只允许 `info`、`warning`、`critical`；同时 Outbox 的重复检查不能触发调用方尚未决定提交的业务状态 autoflush。
- 根因：Week 9 事件协议未限制 severity 枚举，通知持久化模型采用了更严格的订阅严重度集合；普通 ORM 查询默认 autoflush，会越过可组合服务的调用方事务边界。
- 解决方法：记录器在 `no_autoflush` 边界内仅查询完全相同的 `event_id + idempotency_key`，只抑制该精确重复；其他唯一约束错误继续抛出。随后只 `add`/`flush` 安全 thaw payload，不 commit、不创建 savepoint、不投递 Celery；仅在持久化边界将遗留 `error` 规范化为 `critical`，不改 Week 9 payload 或 rollout 状态机。
- 验证方式：先新增 Outbox 合同，模块缺失时 7/7 预期 RED；GREEN 后 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_notification_outbox tests.test_notification_models tests.test_inference_rollout tests.test_celery_workflows tests.test_api_inference_production -v` 为 78/78；`python -m compileall -q app`、具体应用记录器断言和 `git diff --check` 通过。
- 影响范围：`notification_outbox`、rollout API/任务构造器、应用记录器装配和 Outbox 回归；不修改通知通道、rollout 状态转换、运行时调用或 Celery 投递策略。
- 预防措施：跨领域事件先在 immutable DomainEvent 边界做 allowlist、JSON 值域与深冻结，再经显式 storage thaw 写入 JSON 列；可组合 Outbox 记录器不得 commit、dispatch 或创建持久 savepoint，重复抑制必须同时匹配全部幂等身份字段。
- 遗留事项：并发的完全重复插入仍可由数据库唯一约束报错，不能为吞掉该竞态而破坏调用方事务；Task 8 将在独立领取事务中处理 worker 幂等、重试和死信。

### 2026-07-27：第 10 周 Task 1-4 安全硬化与平台审计验证完成

- 当前周次：第 10 周，整体仍进行中；Task 1-7 已完成本地实现与针对性验证，下一项为 Task 8 通知领取、投递、重试和死信。
- 开发内容：公开注册采用严格 schema 且固定创建 engineer；平台管理员角色操作写入独立安全审计流；`ResourceAccessService` 为 Compute、Annotation 和 Platform API 提供 owner/间接 owner 的 fail-closed 解析；平台审计模型、线性迁移和管理员筛选查询接口已接入。
- 安全边界：跨用户私有资源在读取 payload、调用 provider 或执行写操作前隐藏为 404；平台 API 列表必须认证且仅返回自己的私有项或公共项；项目成员权限先于目标用户/成员查询；平台安全审计只允许管理员读取，且不暴露原始敏感数据。
- 问题现象：共享 SQLite fixture 中的 actor 删除回归先插入一条 `platform.user.role_change`，后续管理员角色变更回归只按 action 查询，错误假设该 action 全库唯一而导致 `MultipleResultsFound`。
- 根因：该测试类在 `setUpClass` 中复用数据库；审计流按 action 本来允许多行，测试没有以资源身份和结果限定预期事件。
- 解决方法：管理员角色变更断言同时匹配 action、目标 `resource_id` 和 `success` 结果，不改变生产审计写入语义。
- 验证方式：先复现 actor 删除后角色变更的确定性失败；修复后该配对 2/2 通过，`tests.test_security_hardening tests.test_platform_audit tests.test_api_users tests.test_api_compute tests.test_api_platform` 为 48/48 通过，`git diff --check` 通过。
- 遗留事项：Task 8 仍必须以独立领取事务实现单赢家、投递幂等、可重试退避与单次死信告警；Week 10 不得在 API、前端、浏览器和生产栈门禁完成前标记完成。

### 2026-07-28：第 10 周 Task 8 通知领取、投递、重试与死信完成

- 当前周次：第 10 周整体仍为进行中；Task 1-8 已完成本地实现、回归和规格复审，下一项为 Task 9 通知 API。
- 开发内容：新增稳定 Celery 任务 `ml_platform.deliver_notifications` 与 `ml_platform.enqueue_due_notifications`；Outbox 采用 PostgreSQL `SKIP LOCKED`/SQLite 条件更新领取，按订阅扇出确定性 delivery key，并持久化重试退避、终态和错误码。
- 并发修复：`NotificationDelivery` 追加 `claim_token`、`claimed_at`；worker 每次领取生成新的 token，结果写入必须同时匹配 `id + processing + claim_token`。超时回收后的旧 worker 只能读取持久状态，不能覆盖新 worker 的 `sent`、`retry` 或 `failed` 终态。
- 死信修复：`InAppNotification.deduplication_key` 为可空唯一键；死信告警使用 `notification.dead_letter:<event_id>`，SQLite/PostgreSQL 均以 `ON CONFLICT DO NOTHING` 原子去重，不影响正常多收件人站内通知。
- TDD 与复审：新增 lease、stale-finalizer、回收和死信唯一键合同，初始 4 项均按预期 RED；规格复审确认两项并发缺陷关闭，未发现其他 P0-P2 Task 8 缺口。代码静态复核未发现额外问题。
- 验证方式：`tests.test_notification_models tests.test_notification_outbox tests.test_notification_channels tests.test_inference_rollout tests.test_celery_workflows tests.test_api_inference_production` 为 `108/108`；`tests.test_security_hardening tests.test_platform_audit tests.test_api_users tests.test_api_compute tests.test_api_platform` 为 `48/48`；`C:\\Users\\17723\\miniconda3\\python.exe -m compileall -q app` 与 `git diff --check` 通过。
- 未完成与边界：真实 PostgreSQL `SKIP LOCKED`、Redis/Celery/Beat、四通道受控接收器和 `test_notification_production_stack.py` 尚未实现或验证，严格保留给 Task 11；不得把 SQLite/局部回归描述为生产栈验收。

### 2026-07-28：第 10 周 Task 8 代码质量复审更正

- 复审发现：初版每次 `execute_notification_delivery` 只在入口捕获一个时间戳，多个 delivery 排队处理时后续 lease 已接近超时，retry 时间也可能过期；fan-out 以查询后插入创建 delivery，两个恢复 worker 可同时观察空行而使其中一个因唯一键冲突中止。
- 根因：领取/完成时间被错误视为一次 task 级输入，而非 delivery 生命周期边界；唯一约束存在但没有作为 fan-out 的原子同步原语使用。
- 修复：新增可注入 `clock`，生产路径在每个 delivery 的领取前和 adapter 返回后分别采样，已有 `now` 参数继续提供冻结测试时间；fan-out 改为 PostgreSQL/SQLite `INSERT ... ON CONFLICT DO NOTHING`，随后查询同一 Outbox 的实际 delivery。
- TDD 与验证：两项新合同先分别以缺少 `clock` 与文件 SQLite 双 session 唯一键 `IntegrityError` RED；修复后两项 GREEN。最终组合 `tests.test_security_hardening tests.test_platform_audit tests.test_api_users tests.test_api_compute tests.test_api_platform tests.test_notification_models tests.test_notification_channels tests.test_notification_outbox tests.test_celery_workflows tests.test_inference_rollout tests.test_api_inference_production` 为 `158/158`；`compileall`、`git diff --check` 通过。
- 当前状态：Task 8 仅以本地 SQLite/单元和服务组合验证完成；质量复审 P1 已关闭。真实 PostgreSQL `SKIP LOCKED`、Redis/Celery/Beat、受控 WeCom/邮件/Webhook 接收器仍属于 Task 11，Week 10 继续保持进行中。

### 2026-07-28：第 10 周 Task 8 Outbox 聚合重算复审更正

- 复审发现：两个不同 delivery 近同时完成时，二者各自的终态更新虽受 claim token 围栏保护，但若不串行化同一 Outbox 的聚合重算，较晚提交的旧快照可把仍有 retry 的 Outbox 写回 `processing` 且清除 `next_attempt_at`；retry 已提交后另一个 sent 终态还可能清空聚合错误码。
- 根因：delivery 行围栏只保护单行所有权，不能保护多个 delivery 汇总到一个 Outbox 行的状态派生；聚合状态未从持久化 delivery 集合重新派生错误码。
- 修复：PostgreSQL 在 delivery 终态更新后以 `FOR UPDATE` 锁定 Outbox，再读取当前 delivery 集合并重算状态、最早 retry 时间及未解决 retry/dead-letter/failed 的稳定错误码；SQLite 保留原有串行写入语义。fan-out 并发合同同步点移至实际 `INSERT INTO notification_deliveries` 前并断言两个 worker 都到达原子插入边界。
- 验证方式：新增 PostgreSQL 锁调用合同、双 session `retry` 后 `sent` 的聚合回归和真实插入 barrier；`C:\\Users\\17723\\miniconda3\\python.exe -m unittest tests.test_security_hardening tests.test_platform_audit tests.test_api_users tests.test_api_compute tests.test_api_platform tests.test_notification_models tests.test_notification_channels tests.test_notification_outbox tests.test_celery_workflows tests.test_inference_rollout tests.test_api_inference_production -v` 为 `160/160`，`compileall -q app` 与 `git diff --check` 通过。
- 当前状态与边界：Task 8 本地实现、回归和复审完成，下一项为 Task 9 通知 API；此结果不替代 Task 11 的真实 PostgreSQL、Redis/Celery/Beat 或受控四通道接收器验证。

### 2026-07-28：第 10 周 Task 9 通知 API 复审缺陷修正

- 当前周次：第 10 周整体仍为进行中；Task 9 API 已完成本地实现、回归与复审修正，未提前替代 Task 11 生产栈门禁。
- 问题现象：同项目同名 notification endpoint 的创建或重命名将数据库唯一键冲突暴露为 500；重复站内 endpoint `/test` 会为同一收件人写入多条通知；已删除 ProjectMember 被 role/explicit selector 过滤为空后，adapter 又回退到 endpoint 中的旧加密收件人；endpoint `/test` 未在发送前复验该加密收件人的当前成员资格。
- 根因：API 未将精确 `(project_id, name)` 唯一约束映射为稳定领域冲突；`recipient_user_ids or configured_recipients` 把“未传 selector”和“worker 已解析为空”混为同一 falsey 状态；普通站内通知没有 per-recipient 的持久去重键，测试路由也未在解密后重新执行成员校验。
- 解决方法：仅将 `None` 解释为 endpoint 测试的配置回退，显式空 tuple/list 直接失败；用 `sha256(delivery_key + recipient UUID)` 生成 64 字符去重键，并在 SQLite/PostgreSQL 通过 `ON CONFLICT DO NOTHING` 原子写入；endpoint `/test` 经同一加密 router 解密后复验 in-app 成员；精确 endpoint 名称约束统一返回 409 `NOTIFICATION_ENDPOINT_NAME_CONFLICT`。Webhook 测试继续经过相同解密、SSRF、签名和 provider-body redaction 边界。
- TDD 证据：先观察 create/rename 500、重复 `/test` 生成两条记录、已删除收件人 endpoint `/test` 返回 200、worker fan-out 返回 sent 的 RED；修正 selector 回归后临时恢复旧 fallback 表达式，确认同一 worker 用例稳定 RED，再恢复实现 GREEN。Webhook 安全回归在修复前已 GREEN，证明既有安全边界未被绕过；管理员 retry 两项既有合同保持 GREEN。
- 验证方式：`tests.test_api_notifications tests.test_notification_channels tests.test_notification_outbox` 为 55/55；原 104 项 notification/access 组合因新增 6 项 API 回归扩展为 110/110，`RUN_PROJECT_ACCESS_INTEGRATION` 未启用的 PostgreSQL 用例按预期 skip 1 项；`C:\Users\17723\miniconda3\python.exe -m compileall -q app` 通过。
- 影响范围：`app/api/notifications.py`、`app/services/notification_channels.py` 与 `tests/test_api_notifications.py`；未修改 retry 状态机、迁移、Celery 调度或 Webhook provider 协议。
- 遗留事项：真实 PostgreSQL conflict/upsert、Redis/Celery/Beat 和受控 WeCom/邮件/Webhook 接收器尚未验证；仍属于 Task 11，不能将本地 SQLite 回归描述为生产栈验收。

### 2026-07-28：第 10 周 Task 9 站内通知成员撤销插入边界复审修正

- 当前周次：第 10 周，整体仍为进行中；本项仅修复 Task 9 的站内通知收件人授权竞态，不替代 Task 11 生产栈门禁。
- 问题现象：worker 先按项目角色解析收件人，随后 `InAppNotificationAdapter` 使用无条件 `INSERT ... VALUES` 写入。成员在解析后、写入前被移除时，仍可能收到新的站内通知。
- 已验证根因：成员资格只在 selector 层检查，没有作为站内通知持久化语句的条件；确定性去重键只能避免重复，不能授权收件人。
- 解决方法：SQLite/PostgreSQL 均改为 `INSERT ... SELECT ... WHERE EXISTS`，在同一写入语句中要求目标用户是事件项目 owner 或当前 `ProjectMember`，并保留每个 delivery/recipient 的 SHA-256 去重键与 `ON CONFLICT DO NOTHING`。owner 不要求存在 `ProjectMember`。
- TDD 与验证：新回归在 `before_cursor_execute` 中恰好于 `in_app_notifications` 插入前撤销成员，旧无条件写入稳定返回 `sent` 并写入一行（RED）；修复后返回 `NOTIFICATION_RECIPIENT_INVALID` 且写入 0 行（GREEN）。`tests.test_notification_channels` 15/15、`tests.test_notification_outbox` 26/26、`tests.test_api_notifications` 15/15、`tests.test_notification_models` 8/8、`python -m compileall -q app` 和 `git diff --check` 均通过。
- 影响范围：仅通知通道适配器与其回归；未修改成员 selector、Outbox 状态机、迁移、Celery 调度或外部 provider 协议。
- 预防措施：任何可在异步解析后被撤销的项目授权，必须成为最终持久化 statement 的 predicate；冲突安全去重不能代替授权。SQLite 的插入边界合同不替代 Task 11 的真实 PostgreSQL/Celery/受控接收器验收。
- 遗留事项：真实 PostgreSQL `INSERT ... SELECT` 并发时序、Redis/Celery/Beat 和四通道受控接收器仍按 Task 11 验收，Week 10 不提前标记完成。

### 2026-07-28：第 10 周 Task 10 前端治理收尾暂停

- 当前状态：按用户要求保存并暂停。Task 10 未完成，Week 10 整体仍为进行中；不得启动 Task 11 或 Task 12，也不得将当前本地进度描述为完整验收。
- 已保存范围：前端已具备通知中心、项目治理页、端点/订阅基础管理、收件人安全目录、审计与管理员投递分页、项目详情调用者角色传递，以及相关后端授权回归。
- 已验证问题：`npm test -- --run src/pages/ProjectGovernanceTabs.test.tsx` 运行 11 项，9 项通过、2 项 RED。端点编辑尚不能安全替换 Webhook/邮件/企业微信/站内配置；订阅表尚不向 `notification.manage` 用户显示已配置的角色或安全成员名称。
- 暂停原因：补齐上述两个闭环后仍需运行前端全量、构建、后端回归和文档验收，无法在本次快速收尾中诚实标记 Task 10 完成。
- 恢复顺序：先使两条 RED 合同 GREEN，禁止回显存储密钥或历史端点配置；再运行 Task 10 聚焦/全量验证、更新共享经验并提交完成记录。`ModelLibraryPage.test.tsx` 的既有分页 mock 修改不属于本任务，继续保留未提交。

### 2026-07-29：第 10 周 Task 10 前端治理与通知体验完成

- 当前状态：Task 10 已完成本地实现与自动化验证；Week 10 整体仍为进行中，Task 11 的 Chromium 与真实生产栈验收尚未开始。
- 开发内容：端点编辑支持安全重配开关；仅在管理员主动开启后显示空白的同通道配置表单，并以 `{ name, config }` 更新。订阅表为 owner/editor 显示收件角色和授权收件人目录中的用户名；只读角色不获取该列或目录。
- 问题现象：原有端点编辑只能重命名，无法更新通道配置；订阅虽保存 `recipient_roles` 和 `recipient_user_ids`，管理员表格无法确认目标收件人。
- 已验证根因：编辑弹窗没有保存 endpoint `kind`、重配状态或配置提交路径；订阅表没有消费已授权目录映射。直接拼接角色与用户名还会使可访问文本查询和扫描不稳定。
- 解决方法：编辑启动时重置所有表单字段，仅保留端点名称、种类和非敏感默认值；`replace_config` 开关未开启时只提交名称，开启后才根据安全空表单构建 config。订阅收件人按独立 Tag 渲染角色和目录用户名，找不到目录项时不泄露原始用户 ID。
- 验证方式：先复现 `ProjectGovernanceTabs` 11 项中的 2 项 RED；修复后该模块 `11/11`、Task 10 前端聚焦 `22/22`、前端全量 `82/82`、`npm run build`、后端 `tests.test_api_notifications tests.test_api_project_access` `32/32`、`compileall -q app` 与 `git diff --check` 全部通过。
- 遗留事项：Task 11 仍需实现并执行 Chromium 项目治理流、受控四通道接收器、PostgreSQL/Redis/Celery/Beat 生产栈测试和 Week 10 manifest 注册；不得以本地单元/API 验证替代这些门禁。
- 预防措施：安全端点的修改 UI 必须把“重命名”和“重录凭据”分为显式操作，且任何编辑会话先清空非公开字段；目录受限的收件人展示必须只使用已授权映射，并保持每个可扫描身份为独立可访问节点。

### 2026-07-29：第 10 周 Task 10 复核修正与本地门禁完成

- 当前状态：Task 10 已完成本地实现、复核、文档和自动化门禁；第 10 周整体仍为进行中，Task 11 的 Chromium、真实生产栈和 Week 10 manifest 尚未完成。
- 复核修正：编辑端点从 `editingEndpoint.kind` 派生真实通道，避免 `in_app`、`email`、`wecom` 重配时回退为 `webhook`；只读订阅 API 对 operator/viewer 返回空 `recipient_user_ids`，owner/editor 才能读取管理范围内的 selector。
- 测试修正：共享 SQLite fixture 的订阅回归按本次创建的 subscription ID 断言，避免历史记录改变 `items[0]`；Ant Design `Select` 的透明 search input 不再使用错误的 `toBeVisible()` 断言，改由无 URL 字段、下拉选项和最终 API payload 验证 in-app 分支。
- 验证方式：`ProjectGovernanceTabs` 14/14；Task 10 前端组合 6 文件、25/25；前端全量 23 文件、85/85；`npm run build` 成功；通知/项目访问后端 33/33；`compileall -q app` 和 `git diff --check` 通过。
- 影响范围：`ProjectGovernanceTabs` 编辑/订阅 UI、通知订阅列表 DTO、对应回归和本地开发记录；未泄露历史密钥或只读用户原始收件人 ID。
- 未完成与边界：Task 11 仍需注册 Week 10 模块、执行 Chromium 治理流、PostgreSQL/Redis/Celery/Beat 生产测试和四通道受控接收器；Task 12 及第 11-12 周最终工具依赖这些门禁，不能提前标记完成。
- 预防措施：敏感编辑回归必须覆盖每种通道的 `kind` 保真；API 脱敏必须在服务端执行而非依赖前端隐藏列；共享 append-only fixture 断言必须按完整资源身份定位；Ant Design 测试断言可见业务行为，不断言内部透明输入。

### 2026-07-29：第 11-12 周恢复加固与隔离生产栈中间验证

- 当前状态：第 11、12 周继续保持进行中；已完成备份恢复状态机加固、工具/契约/安全/CI 清单回归和隔离 WSL 生产栈验证，但未取得固定性能、完整 Chromium 或远程 CI 结论。
- 问题现象：备份清单写入后、最终回执尚未全部写入时可以恢复；但已有最终回执签名无效，或最终回执路径被目录/断链占用时，原恢复入口可能将其误判为缺失并在失败前改写 `manifest.json`。
- 根因与解决：恢复入口只以 `Path.is_file()` 判断最终状态，混淆“真正缺失”和“已存在但不可读/无效”；现在任何已存在或 symlink 的最终回执路径都会先进入失败关闭验证，只有路径真实缺失时才允许由已签名 pending 记录重建。新增签名篡改与目录占用回归均断言 manifest/pending 不变。
- 验证方式：新增目录占用合同先 RED 为 `PermissionError`，最小修复后 GREEN；`tests.test_week11_12_tools` 为 87/87，`UpgradeFixtureTests` 为 11/11，冻结 API 契约为 5/5，安全门禁为 26/26，环境清单为 1/1，manifest/CI 合同为 26/26；`compileall -q tools tests` 与 `git diff --check` 通过（仅现有 CRLF 提示）。
- WSL 证据：Docker 29.6.2 / Compose 5.3.1 的独立项目完成迁移 head/check、实验 1/1、推理 1/1、站内/企业微信/邮件/Webhook 通知 6/6，以及 Redis 失效关闭 1/1；退出后确认对应容器、volume 和 network 均已清理。
- 未完成与风险：当前 Docker 主机为 22 vCPU / 16.5 GiB，不符合固定 4 vCPU / 8 GiB 三轮性能基线，不能输出 Week 11 性能结论；真实 N-1 数据库升级、完整 Chromium 四角色验收、最终证据 manifest 和远程 GitHub Actions 仍是未完成门禁。

### 2026-07-29：第 12 周备份回执来源约束待修复

- 当前状态：暂停前审计发现新的安全门禁；未修改实现，不能将备份恢复验收标记为完整。
- 风险：`manifest.json`、pending/final 回执和证据枚举仍以 `Path.is_file()`/直接路径写入处理；有效符号链接、Windows reparse point 或同卷硬链接可使签名证据读取或写入落在回执根目录外。
- 恢复顺序：集中以 `lstat()` 拒绝链接/reparse 证据，采用根目录内临时文件加原子替换写入，并补充外部 sentinel、有效链接回执和同卷硬链接回归；完成后重新执行 `tests.test_week11_12_tools` 及相关安全门禁。

### 2026-08-01：第 12 周备份证据来源约束修复

- 当前状态：本地备份证据来源加固已完成并通过回归；第 11、12 周仍为“进行中”，本项不替代真实备份恢复 RTO/RPO、固定资源性能、完整 Chromium、N-1 升级、扫描汇总或远程 CI 门禁。
- 问题现象：已有 manifest 硬链接外部 sentinel 时，控制文件枚举先将其当作备份 payload 拒绝，阻断本应安全的原子替换；`mirror_minio` 只用 `Path.is_file()` 收集对象，会把同卷硬链接对象签入 MinIO pending 回执；目录占用 pending 路径会被误作缺失；回执写入在拒绝链接 manifest 前已计算其哈希。
- 已确认根因：原子写入目标和已接收的签名证据没有区分处理；普通文件判断没有统一应用到 pending 证据条目和 pending 路径状态，且 manifest 信任校验位于哈希读取之后。
- 解决方法：控制 manifest/receipt 名称在 payload 枚举前排除，并继续由 in-root 临时文件和 `os.replace()` 原子替换；`_backup_evidence_entry` 统一要求路径在 receipt root 内、`lstat()` 为普通非链接文件且 link count 为 1；已占用 pending 路径必须全部为可信普通证据文件；`_write_operation_receipt` 在哈希前验证 manifest。
- 验证方式：新增 MinIO 硬链接对象、非法 pending 目录占位、链接 manifest 不能在哈希前读取三条回归，均先 RED 后 GREEN；`C:\\Users\\17723\\miniconda3\\python.exe -m unittest tests.test_week11_12_tools tests.test_week12_security_gates tests.test_week11_contracts -v` 为 125/125，通过 `python -m compileall -q tools tests` 和 `git diff --check`（仅 CRLF 工作树提示）。外部 sentinel 在硬链接写入/拒绝回归中保持字节不变。
- 影响范围：仅 `backend/tools/backup_restore.py` 与 Week 11-12 工具回归；不修改生产数据库、MinIO bucket、Compose、CI 或用户的前端测试修改。
- 预防措施：文件系统安全控制必须将“新建原子写入目标”和“已存在、将被读取的证据”分为不同状态；所有 pending/manifest/final receipt 接受路径统一使用 `lstat()`、重解析点和 link-count 检查，任何已占用但无效的控制路径均失败关闭。
- 遗留事项：仍需在隔离 PostgreSQL/MinIO 环境执行真实备份恢复和 RTO/RPO；当前 22 vCPU/16.5 GiB Docker 主机不满足 4 vCPU/8 GiB 三轮性能基线，不能生成 Week 11 性能结论。

### 2026-08-02：第 10 周 Task 11 浏览器、清单与生产栈验收完成

- 当前状态：Task 11 已完成本地实现、回归、隔离 WSL 生产栈和目标 Chromium 验收；第 10 周整体仍为“进行中”，Task 12 的共享生产文件、完整本地收口与远程 GitHub Actions 尚未完成。
- 开发内容：修复外部 Chromium 次级角色上下文固定回 `127.0.0.1:5173` 的问题；通知受控接收器恢复镜像默认非 root `app` 用户；前端镜像健康检查改用显式 IPv4 loopback；为三项部署/浏览器边界增加静态回归。
- 问题现象与根因：接收器以 `user: "0:0"` 运行并同时 `cap_drop: ALL` 时，root 不再拥有 DAC override，不能读取 Compose 以 UID 1000、0600 挂载的 TLS 私钥，`load_cert_chain` 抛出 `PermissionError`。前端镜像自定义 Nginx 配置仅监听 IPv4，Alpine `localhost` 解析到 `::1`，健康检查连接被拒绝，导致完整栈无法等待 frontend healthy。外部 E2E 的 Windows `cmd.exe` 链中 `/s` 加带引号路径会产生无效目录语法，且 `set VAR=value &&` 会把分隔符前空格写入变量，令严格的 `RUN_WEEK12_BROWSER_ACCEPTANCE === "1"` 判断失败。
- 解决方法：删除接收器的 root 覆写，保留 `cap_drop: ALL` 与 `NET_BIND_SERVICE`；将前端健康检查改为 `127.0.0.1`；E2E 从主页面 origin 派生 viewer/outsider `baseURL`，并在保持 WSL Compose shell 存活时以无 `/s`、无分隔空格的 Windows Node Playwright CLI 执行外部用例。
- TDD 与验证：接收器非 root 契约和 IPv4 健康检查契约均先 RED 后 GREEN；`tests.test_ci_workflow` 23/23、`src/weekAcceptance.test.ts` 7/7、`run_suite.py --week 10` 7/7 模块通过，`git diff --check` 通过。WSL Docker 29.6.2 / Compose 5.3.1 的唯一项目完成迁移 `20260720_10_security_notifications` current/check、PostgreSQL/Redis/Celery/Mailpit/受控 Webhook-WeCom 接收器全健康、`test_notification_production_stack` 6/6 和外部 Chromium `security-notifications.spec.ts` 1/1；项目容器、网络和卷均已按精确标签清理。
- 影响范围：`docker-compose.acceptance.yml`、前端 Dockerfile、通知浏览器验收和 CI/Compose 静态契约；不改变通知协议、业务数据或用户的 `ModelLibraryPage.test.tsx` 修改。
- 遗留事项：Task 12 仍需收口共享 Compose/CI/交付状态、完整本地质量/依赖/扫描门禁与远程 CI；Week 11-12 的固定 4 vCPU/8 GiB 三轮性能、真实备份恢复 RTO/RPO、N-1 升级、完整外部 Chromium、最终证据清单和远程门禁继续保持未完成。

### 2026-08-02：第 10 周 Task 11 外部角色 Context 回归与双审闭环

- 当前状态：Task 11 的本地验收、静态回归、规格审查和代码质量审查均已闭环；第 10 周仍为“进行中”，不把本地 WSL 证据升级为远程 CI 结论。
- 问题现象：初始静态回归只检查通用 context 片段和固定登录 URL，viewer 或 outsider 任一角色退回裸 `browser.newContext()` 时可能漏检。
- 解决方法：分别锁定 viewer/outsider 使用 `baseURL: acceptanceBaseUrl`，禁止完整固定 `http://127.0.0.1:5173` origin；验收 origin 继续从主页面 `page.url()` 派生。
- 验证方式：`src/weekAcceptance.test.ts` 先在 viewer 回退裸 context 时按预期 1 项失败、其余 6 项通过；恢复后 7/7 通过。规格审查和代码质量审查均无 P0-P2；`git diff --check` 通过。共享经验已追加外部 Chromium context 的根因、修复、WSL 验证与远程 CI 边界。
- 遗留事项：Task 12 的共享生产配置、CI、交付文档和完整本地门禁继续按计划执行；第 11-12 周固定资源性能、真实备份恢复、N-1、完整浏览器、证据清单和远程 CI 仍未完成。

### 2026-08-02：第 12 周 Task 13 安全扫描门禁暂停检查点

- 当前状态：用户要求立即保存并停止；第 12 周和 Task 13 保持“进行中”，不得将安全扫描或 Week 11-12 最终验收标记为完成。
- 已保存范围：安全扫描封装器、CI 静态契约、受限 React Router 审计例外、原始报告相对路径绑定及对应回归均保留在未提交工作树；`ModelLibraryPage.test.tsx` 的用户既有修改未触碰。
- 已验证证据：暂停前主流程独立运行 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_week12_security_gates tests.test_ci_workflow -v` 为 76/76；`python -m compileall -q app tools tests` 与 `git diff --check` 退出码为 0，后者仅输出既有 CRLF 工作树提示。
- 未关闭缺口：规格复审确认路由 action 的成员表达式和对象 shorthand 仍可绕过；提供静态 gate 的 `security.json` 尚未在解析前完成普通文件、单链接、非 reparse 和根目录约束校验；不安全证据错误码仍需统一为 `SECURITY_EVIDENCE_INVALID`。实现代理在这些修复及复验完成前被停止。
- 恢复顺序：先检查 `security_scans.py` 与 `test_week12_security_gates.py` 的保存差异，按 RED→GREEN 补齐上述三项回归；随后重跑目标测试、编译和 diff 检查，再完成规格复审与独立代码质量复审。仅在真实扫描、冻结 Web 栈及远程 CI 取得独立证据后，才可关闭 Task 13 或 Week 12。

### 2026-08-08：第 12 周 Task 13 安全证据解析缺口修复

- 当前状态：Task 13 的静态安全证据解析缺口已完成 RED→GREEN；第 11-12 周仍为“进行中”，真实扫描、固定资源性能、备份恢复 RTO/RPO、N-1、完整 Chromium、最终证据清单和远程 GitHub Actions 仍未完成。
- 问题现象：React Router 例外扫描会误报 TypeScript `action: string` 类型字段，并漏检成员表达式与带类型注解的对象 shorthand；汇总器可能在校验 `security.json`/`web.json` 来源前读取状态，且不安全证据错误码不稳定。
- 根因：静态正则没有区分类型声明与运行时 route action；汇总流程先依赖候选计数再验证文件来源；web 缺失/非法分支复用了非证据错误码。
- 解决方法：增加类型声明局部屏蔽并覆盖成员表达式、类型注解 shorthand；所有影响汇总状态的 JSON 在解析前执行根目录 containment、`lstat()`、普通文件、非 reparse、单硬链接校验；统一不安全证据错误码为 `SECURITY_EVIDENCE_INVALID`。
- 验证方式：新增回归先 RED 后 GREEN；独立运行 `C:\\Users\\17723\\miniconda3\\python.exe -m unittest tests.test_week12_security_gates tests.test_ci_workflow -v` 为 83/83，`C:\\Users\\17723\\miniconda3\\python.exe -m compileall -q app tools tests` 通过，`git diff --check` 通过（仅既有 CRLF 提示）。
- 影响范围：`ml-platform/backend/tools/security_scans.py`、`ml-platform/backend/tests/test_week12_security_gates.py`；未修改用户既有 `ModelLibraryPage.test.tsx`。
- 预防措施：安全证据必须先验证来源再解析任何状态；静态扫描回归同时覆盖运行时语法、类型声明和 fail-closed 错误码；复杂 TypeScript 语法保持保守拒绝，后续若引入 AST 扫描需追加等价安全合同。
- 遗留事项：必须在独立 WSL/Compose 栈完成真实 scanner、固定 4 vCPU/8 GiB 性能、备份恢复、N-1 与完整浏览器验收，并取得远程 CI 证据后才能关闭 Task 13/Week 12。

### 2026-08-08：第 12 周 React Router 审计例外语法闭合修正

- 当前状态：React Router 受限 npm-audit 例外的新增静态语法缺口已按 RED→GREEN 修复；Task 13 和第 11-12 周继续保持“进行中”，不得将本地静态回归替代真实 scanner、生产栈或远程 CI。
- 问题现象：独立安全复审发现注释分隔 import、Route 的括号/嵌套括号别名、可选 factory call 与 `.bind()` factory alias 可使 Action route 绕过例外扫描并错误返回 `passed`；第二轮复审补充发现 alias/factory 中的注释和嵌套括号同样可绕过。
- 根因：命名 import、alias assignment 与 factory call 的正则只接受部分空白语法，未将 JavaScript/TypeScript 的 comment trivia、括号包装和 bound factory reference 归一到同一识别边界。
- 解决方法：import/re-export/local binding 扫描统一接受 comment trivia；Route/factory alias 归一化移除 comment、空白和任意外层括号，并识别 `.bind` 基础 factory；factory call 支持 comment trivia、optional call 与 parenthesized reference。
- TDD 与验证：新增 6 个回归先稳定 RED，覆盖 comment-separated import、单层/嵌套 Route alias、optional call、bound factory 与 comment/nested factory；实现后 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_week12_security_gates tests.test_ci_workflow -v` 为 123/123，`C:\Users\17723\miniconda3\python.exe -m compileall -q app tools tests` 与 `git diff --check` 通过（仅既有 CRLF 提示）。
- 影响范围：仅 `ml-platform/backend/tools/security_scans.py`、`ml-platform/backend/tests/test_week12_security_gates.py`；用户的 `ModelLibraryPage.test.tsx` 仍未触碰。
- 预防措施：受限依赖例外的静态 gate 需将注释、括号、local alias、re-export、optional/bound call 视为同类语法边界并分别保留 RED 回归；无法安全证明客户端-only 语义时保持失败关闭，复杂语法应迁移至 AST 检查。
- 遗留事项：需继续执行真实 scanner、冻结 Web 栈、固定资源性能、备份恢复、N-1 升级、完整 Chromium、最终 evidence manifest 与远程 GitHub Actions，才可关闭 Task 13/Week 12。

### 2026-08-08：第 12 周 React Router 例外语义绑定复审升级

- 当前状态：前两轮语法回归已通过且当前安全/CI 静态套件为 123/123；第三轮独立复审仍确认条件表达式和 `import * as Router` 后的 destructuring 可构造 Action/factory alias 并错误放行，因此本项继续受阻，不能把前一条局部语法修正表述为完整闭合。
- 已验证问题：`const R = true ? Route : Route`、`const { Route: R } = Router`、等价的 factory 条件/解构绑定均可在现有正则模型外建立可用 Action route 或 router factory。
- 根因：基于局部正则的 alias 传播只能覆盖有限语法，无法证明任意 JavaScript/TypeScript binding expression 与 React Router runtime export 的等价关系；继续逐例扩展会保留新的 fail-open 表面。
- 处理边界：停止第四轮正则补丁。待确认后采用其一：A. 对任何未建模的 React Router `Route`/router-factory/namespace binding 直接拒绝 npm-audit 例外（推荐，当前真实 BrowserRouter 前端不受影响）；B. 引入 TypeScript AST/符号绑定扫描并为新依赖与跨版本 parser 行为建立完整合同。
- 已保留证据：新增 six RED→GREEN 语法回归和 123/123 静态通过记录有效，但仅证明已覆盖形式；未解决的条件/namespace binding 仍为阻断合并的 P1。
- 遗留事项：取得上述架构决策并完成对应 RED→GREEN、独立复审后，才可进入真实 scanner、生产栈、固定资源性能、备份恢复、N-1、完整 Chromium、evidence manifest 和远程 CI 门禁。

### 2026-08-10：第 12 周 Task 13 保守绑定收敛与全量回归检查点

- 当前状态：已采用原方案 A：任何未被扫描器证明为安全的 React Router `Route`、router-factory、namespace、动态加载或别名传播，一律拒绝 npm-audit 例外；第 11、12 周仍为“进行中”，不将本地回归或局部扫描结果表述为最终验收。
- 已验证根因与处理：局部正则无法可靠证明条件表达式、解构、动态模块加载及跨运行时别名与 React Router 导出的等价关系。扫描器现只接受受限的命名导入和已建模的直接绑定，遇到条件绑定、namespace 解构、默认/混合导入、动态 `import`/`require`、对象或调用传播时失败关闭。真实客户端 BrowserRouter 前端仍被允许。
- 验证方式：`C:\\Users\\17723\\miniconda3\\python.exe -m unittest tests.test_week12_security_gates tests.test_ci_workflow -v` 为 138/138；`C:\\Users\\17723\\miniconda3\\python.exe run_suite.py` 为 89/89 模块；前端 `npm test -- --run` 为 23 个文件、90/90；`npm run build` 通过，仍有 ECharts 约 1.13 MB chunk 警告；`compileall -q app tools tests` 与 `git diff --check` 通过（后者仅有既有 CRLF 提示）。本地 Chromium 的四项可运行用例通过，外部 Week 12 栈用例按设计跳过；Windows Playwright 完成后未自动退出的本轮测试进程已按 PID 精确终止。
- 安全扫描证据：官方 npm registry audit 重新生成且为 0 vulnerabilities；Bandit HIGH 门槛为 0。pip-audit 的同日原始报告仍发现 `cryptography 49.0.0` 的 `PYSEC-2026-3552` / `CVE-2026-69247`，修复版为 50.0.0；该升级需要连同锁定的 MLflow 3.15 依赖链重新解析和全量兼容验证，当前不能宣称 Python 依赖门禁通过。
- 外部环境阻塞：Windows 与 WSL 均无 Trivy/Gitleaks；WSL Docker 29.6.2、Compose 5.3.1 可用，但主机为 22 vCPU / 15.4 GiB，未满足固定 4 vCPU / 8 GiB 三轮性能基线。重新拉取 `ghcr.io/mlflow/mlflow:v3.15.0` 在首层长期无进度后中止，未以旧 3.2.0 镜像替代或伪造真实生产栈结果。
- 后续顺序：取得冻结 MLflow 镜像和 Trivy/Gitleaks 后，在隔离 WSL Compose 栈执行真实备份恢复、N-1、完整外部 Chromium、web/security 汇总和固定资源性能；随后生成 evidence manifest、最终验收报告及远程 GitHub Actions 证据，再决定 Week 11-12 完成状态。

### 2026-08-10：第 12 周 CI 安全密钥注释导致 YAML 缩进回归

- 当前周次：第 12 周 Task 13 安全扫描门禁。
- 问题现象：为让 Gitleaks 忽略受控 CI 测试密钥而追加行尾注释时，两处 `INFERENCE_INTERNAL_SECRET` 行多出一个空格，GitHub Actions 工作流无法被 PyYAML 解析；目标套件出现 15 个连锁解析错误。
- 根因：手工编辑 YAML 映射项时没有保持同一 `env` 缩进层级；行尾注释本身不是问题，缩进漂移才是语法错误。
- 解决方法：将两处变量恢复到与相邻 `env` 键相同的缩进，仅保留 `# gitleaks:allow` 注释。
- 验证方式：修复前 `tests.test_ci_workflow` 29 项中 15 项错误；修复后 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_ci_workflow -v` 为 29/29，`git diff --check` 通过（仅 CRLF 工作树提示）。
- 影响范围：`.github/workflows/ci.yml` 受控测试环境变量；不改变运行时密钥、业务协议或用户既有前端测试修改。
- 预防措施：修改 GitHub Actions YAML 后必须先用 PyYAML/工作流合同解析，再运行行为断言；密钥扫描注释应与原始缩进一起做最小差异审查。
- 遗留事项：Trivy 漏洞数据库、冻结 MLflow 镜像、固定资源性能、真实备份恢复、N-1、完整外部 Chromium 和远程 CI 仍需独立证据。

### 2026-08-10：第 12 周真实 Trivy/Gitleaks 扫描证据

- 当前周次：第 12 周 Task 13 安全扫描门禁。
- Trivy 环境：WSL Docker 29.6.2 已有 `aquasec/trivy:0.67.2`；`trivy-cache` 中已有约 1.2 GB 漏洞数据库，可用 `--skip-db-update` 离线复用。
- 文件系统扫描：对当前工作树执行 HIGH/CRITICAL 漏洞、密钥和错误配置扫描，结果 `trivy-fs.json` 为 0 vulnerabilities、0 secrets、0 misconfigurations，扫描命令返回 0。
- 镜像扫描：当前 `codex-week12-20260810-a1-backend:latest`（MLflow 3.15.1、cryptography 49.0.0）发现 26 项 HIGH/CRITICAL，其中 22 HIGH、4 CRITICAL；4 项 CRITICAL 来自 Debian `perl-base`，另有 `cryptography 49.0.0` 的 `CVE-2026-69247` 受控兼容例外。镜像门禁仍为失败，不得以旧 `week9-12-mlops-core-backend` 结果替代当前栈。
- Gitleaks：worktree 根目录的 no-git 扫描曾命中 18 项，根因是 `tmp/` 缓存、临时私钥/脚本和 Trivy 报告生成物；在不含运行时临时目录的 `ml-platform` 应用源码和 `.github` CI 目录分别执行 no-git 脱敏扫描，均为 0 leaks。历史仓库扫描此前已验证无泄漏；临时报告不纳入提交。
- 验证方式：后端 `run_suite.py` 89/89；安全与 CI 目标套件 146/146；前端 23 文件、90/90；`npm run build`、Python `compileall`、`git diff --check` 通过。Trivy/Gitleaks 原始 JSON 仅保存在 `tmp/security-20260810/`。
- 遗留事项：镜像基础层待升级到无 HIGH/CRITICAL 的可发布版本；`cryptography` 50.0.0 与 MLflow 3.15 兼容性仍需独立解析验证；远程 CI、固定资源性能、真实备份恢复、N-1、完整外部 Chromium 和最终证据清单未闭合。

### 2026-08-10：第 12 周 Trivy 基础镜像重建复核

- 当前周次：第 12 周 Task 13 安全扫描门禁。
- 问题现象：当前后端镜像 Trivy 仍报告 Debian 13.6 基础包（含 `perl-base`）的 HIGH/CRITICAL CVE，不能仅用 MLflow/cryptography 例外解释。
- 处理结果：使用当前 Dockerfile 和 `docker build --pull` 重建 `codex-week12-20260810-a2-backend:latest`；Docker 解析到相同 `python:3.11-slim` digest，Trivy 结果仍为 26 项（22 HIGH、4 CRITICAL），无 secrets/misconfigurations。
- 验证方式：重建成功；同一 `trivy-cache`、同一 HIGH/CRITICAL 参数复扫并取得 `trivy-image-a2.json`。未修改业务依赖或将基础层 CVE 写入例外。
- 预防措施：发布前固定基础镜像 digest 并由镜像维护者提供已修复层；只有有明确补丁版本和兼容验证时才升级基础镜像或 Python 包。
- 遗留事项：等待可用的无阻断基础镜像/上游修复；远程 CI 与 Week 11-12 其他最终门禁仍未闭合。

### 2026-08-10：第 12 周 Trivy 基础镜像重建复核

- 当前周次：第 12 周 Task 13 安全扫描门禁。
- 问题现象：当前后端镜像 Trivy 仍报告 Debian 13.6 基础包（含 `perl-base`）的 HIGH/CRITICAL CVE，不能仅用 MLflow/cryptography 例外解释。
- 处理结果：使用当前 Dockerfile 和 `docker build --pull` 重建 `codex-week12-20260810-a2-backend:latest`；Docker 解析到相同 `python:3.11-slim` digest，Trivy 结果仍为 26 项（22 HIGH、4 CRITICAL），无 secrets/misconfigurations。
- 验证方式：重建成功；同一 `trivy-cache`、同一 HIGH/CRITICAL 参数复扫并取得 `trivy-image-a2.json`。未修改业务依赖或将基础层 CVE 写入例外。
- 预防措施：发布前固定基础镜像 digest 并由镜像维护者提供已修复层；只有有明确补丁版本和兼容验证时才升级基础镜像或 Python 包。
- 遗留事项：等待可用的无阻断基础镜像/上游修复；远程 CI 与 Week 11-12 其他最终门禁仍未闭合。

### 2026-08-10：第 12 周真实 Trivy/Gitleaks 扫描证据

- 当前周次：第 12 周 Task 13 安全扫描门禁。
- Trivy 环境：WSL Docker 29.6.2 已有 `aquasec/trivy:0.67.2`；`trivy-cache` 中已有约 1.2 GB 漏洞数据库，可用 `--skip-db-update` 离线复用。
- 文件系统扫描：对当前工作树执行 HIGH/CRITICAL 漏洞、密钥和错误配置扫描，结果 `trivy-fs.json` 为 0 vulnerabilities、0 secrets、0 misconfigurations，扫描命令返回 0。
- 镜像扫描：当前 `codex-week12-20260810-a1-backend:latest`（MLflow 3.15.1、cryptography 49.0.0）发现 26 项 HIGH/CRITICAL，其中 22 HIGH、4 CRITICAL；4 项 CRITICAL 来自 Debian `perl-base`，另有 `cryptography 49.0.0` 的 `CVE-2026-69247` 受控兼容例外。镜像门禁仍为失败，不得以旧 `week9-12-mlops-core-backend` 结果替代当前栈。
- Gitleaks：worktree 根目录的 no-git 扫描曾命中 18 项，根因是 `tmp/` 缓存、临时私钥/脚本和 Trivy 报告生成物；在不含运行时临时目录的 `ml-platform` 应用源码和 `.github` CI 目录分别执行 no-git 脱敏扫描，均为 0 leaks。历史仓库扫描此前已验证无泄漏；临时报告不纳入提交。
- 验证方式：后端 `run_suite.py` 89/89；安全与 CI 目标套件 146/146；前端 23 文件、90/90；`npm run build`、Python `compileall`、`git diff --check` 通过。Trivy/Gitleaks 原始 JSON 仅保存在 `tmp/security-20260810/`。
- 遗留事项：镜像基础层待升级到无 HIGH/CRITICAL 的可发布版本；`cryptography` 50.0.0 与 MLflow 3.15 兼容性仍需独立解析验证；远程 CI、固定资源性能、真实备份恢复、N-1、完整外部 Chromium 和最终证据清单未闭合。

### 2026-08-10：第 12 周 CI 安全密钥注释导致 YAML 缩进回归

- 当前周次：第 12 周 Task 13 安全扫描门禁。
- 问题现象：为让 Gitleaks 忽略受控 CI 测试密钥而追加行尾注释时，两处 `INFERENCE_INTERNAL_SECRET` 行多出一个空格，GitHub Actions 工作流无法被 PyYAML 解析；目标套件出现 15 个连锁解析错误。
- 根因：手工编辑 YAML 映射项时没有保持同一 `env` 缩进层级；行尾注释本身不是问题，缩进漂移才是语法错误。
- 解决方法：将两处变量恢复到与相邻 `env` 键相同的缩进，仅保留 `# gitleaks:allow` 注释。
- 验证方式：修复前 `tests.test_ci_workflow` 29 项中 15 项错误；修复后 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_ci_workflow -v` 为 29/29，`git diff --check` 通过（仅 CRLF 工作树提示）。
- 影响范围：`.github/workflows/ci.yml` 受控测试环境变量；不改变运行时密钥、业务协议或用户既有前端测试修改。
- 预防措施：修改 GitHub Actions YAML 后必须先用 PyYAML/工作流合同解析，再运行行为断言；密钥扫描注释应与原始缩进一起做最小差异审查。
- 遗留事项：Trivy 漏洞数据库、冻结 MLflow 镜像、固定资源性能、真实备份恢复、N-1、完整外部 Chromium 和远程 CI 仍需独立证据。

### 2026-08-11：第 12 周镜像与 Python 依赖修复阻塞复核

- 当前状态：Task 13 与第 11-12 周继续保持“进行中”；安全合同仍为 RED，未关闭镜像、Python 依赖或 Week 12 最终门禁。
- 问题现象：四个生产 Dockerfile 仍使用可变的 `python:3.11-slim`；正式 PyPI 最新 MLflow 为 `3.15.1`，其元数据要求 `cryptography<50`；`cryptography 50.0.0` 是 `CVE-2026-69247`/`PYSEC-2026-3552` 的修复版本，故把直接 pin 提升到 50 会使解析失败。当前 `python:3.11-slim-trixie` digest `sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff` 的基础层仍报告 4 项 CRITICAL、21 项 HIGH；`apt-get dist-upgrade` 无可用修复版本。
- 已确认根因：应用依赖冲突来自已发布 MLflow 的上游版本约束，不是本仓库 resolver 或代码问题；镜像风险来自 Debian 基础包尚未发布可用修复层，重建或仅改标签不会改变 digest。Alpine 虽然 OS 漏洞为 0，但当前 `scikit-learn==1.7.*` 没有可用 musllinux wheel，不能宣称科学计算栈兼容；未发布 MLflow 开发提交也不能作为稳定生产依赖。
- 处理结果：复核 PyPI 元数据、候选 digest、Trivy 基础层报告和干净 resolver 结果；保留 RED 合同、原始扫描与解析证据，不删除 cryptography 例外、不强制安装 50、不强制移除 Debian 包、不修改生产配置。
- 验证方式：PowerShell 7 `Invoke-RestMethod` 查询 PyPI；同一 Trivy 数据库和 HIGH/CRITICAL 参数复核 Trixie digest；既有完整镜像扫描保持 22 HIGH、4 CRITICAL；MLflow 3.15.1 + cryptography 50 的解析失败与当前 requirements 约束一致。
- 预防措施：依赖修复必须同时满足正式发行元数据、干净 resolver、运行时回归和无例外 pip-audit；基础镜像必须以实际 digest 和同参数 Trivy 结果选定，重建成功或 mutable tag 变化不能替代漏洞修复证据。
- 遗留事项：需由项目负责人在“等待正式 MLflow/基础镜像修复”和“批准维护经过测试的内部 MLflow backport/镜像方案”之间作出长期决策；决策前不得继续生产依赖改动、四镜像最终扫描、Week 12 安全门禁关闭、推送或合并。

### 2026-08-11：第 12 周独立 Python 依赖 pin 的局部修复

- 当前状态：`jaraco.context` 与 `wheel` 的直接 pin 已完成；Task 13 仍未完成，cryptography 例外、基础镜像风险和最终安全门禁继续保持未关闭。
- 问题现象：当前镜像中的 `jaraco.context 5.3.0` 与 `wheel 0.45.1` 分别对应 Trivy 报告的 `CVE-2026-23949` 和 `CVE-2026-24049`。
- 已确认根因：两个漏洞包没有被应用的顶层 requirements 固定，解析结果可落到旧版本；它们不受 MLflow 的 cryptography 上限约束。
- 解决方法：在 `ml-platform/backend/requirements.txt` 增加 `jaraco.context==6.1.0` 和 `wheel==0.46.2`；不改变 `cryptography==49.0.*`、`mlflow==3.15.*` 或安全例外。
- 验证方式：使用 PowerShell 7、阿里云 PyPI 镜像执行 `pip install --dry-run --report ... -r requirements.txt jaraco.context==6.1.0 wheel==0.46.2`，解析退出码为 0；随后原始 `pip-audit -r requirements.txt` 因 `pypi.org` TLS `UNEXPECTED_EOF_WHILE_READING` 中断，未产生可作为通过证据的报告。
- 预防措施：独立 pin 只有在干净 resolver 和原始 pip-audit 都成功后才能标记为已修复；网络或漏洞数据库不可用时记录为 blocked，不用 dry-run 或旧 JSON 冒充扫描通过。
- 遗留事项：需在可访问 PyPI advisory 服务的环境复跑无例外 pip-audit，并等待正式 MLflow/基础镜像修复或获得内部 backport 方案批准后再处理 cryptography 和四个生产镜像。

### 2026-08-11：第 12 周无例外 pip-audit 真实报告名称规范化修复

- 当前状态：Task 13 与第 11-12 周继续保持“进行中”。依赖审计已取得当前候选镜像内的零漏洞原始报告，但四个最终生产镜像的无缓存重建与 Trivy 扫描尚未完成，不能关闭安全或最终验收门禁。
- 问题现象：真实 `pip-audit` JSON 把 requirements 中的 `jaraco.context==6.1.0` 记录为规范化分发名 `jaraco-context`。安全扫描器仅以 `casefold()` 比较名称，会把该干净报告错误标记为 `PIP_AUDIT_REQUIRED_PACKAGE_MISSING`。
- 已确认根因：PyPI 分发名遵循 PEP 503，将连续的 `.`, `_` 和 `-` 归一化为 `-`；扫描器的受控包集合和报告名称没有在同一规范化边界比较。此前测试夹具使用了非真实的点号名称，未覆盖该输出。
- 解决方法：在 `tools/security_scans.py` 增加 PEP 503 等价的名称规范化，并将受控包集合与报告依赖名称都归一化后比较；回归夹具改为真实的 `jaraco-context` 输出。未增加例外、忽略规则或放宽漏洞判断。
- 验证方式：真实名称夹具先稳定 RED 为 `PIP_AUDIT_REQUIRED_PACKAGE_MISSING`，修复后 GREEN；`C:\Users\17723\miniconda3\python.exe -m unittest tests.test_image_security_contracts tests.test_week12_security_gates tests.test_ci_workflow -v` 为 148/148，`python -m compileall -q app tools tests` 通过。候选镜像 `codex-week12-ps7-backend:candidate` 内执行无例外 `pip-audit -r /app/requirements.txt` 退出码为 0，原始报告显示 `cryptography 50.0.0`、`jaraco-context 6.1.0`、`wheel 0.46.2` 均无漏洞。
- 影响范围：仅 Week 12 依赖审计报告解析与安全回归；不改变 React Router 受限 npm 例外、通知协议、用户的 `ModelLibraryPage.test.tsx` 或临时缓存保护范围。
- 预防措施：扫描器比较 Python 分发名称时必须采用 PEP 503 规范化；回归夹具应使用真实工具输出的名称格式，依赖门禁继续对任意漏洞和受控包缺失失败关闭。
- 遗留事项：`docker build --pull --no-cache` 重建 `codex-week12-final-backend:latest` 在 904 秒上限内未完成，未生成可扫描的最终镜像。需在 Docker 构建网络可完成时按同一固定 digest 重建 backend、worker、inference、TensorBoard，并运行四个 Trivy HIGH/CRITICAL 扫描、`tools.security_scans all`、全量回归和远程 CI 后再决定提交、推送或合并。

### 2026-08-12：第 11-12 周验收 Task 1 基线与证据工作区完成

- 当前状态：在 `codex/week9-12-mlops-core`、提交 `82afc9cd6011cbb23fdfeca68dc99c6f2ad1514d` 上创建隔离的 `temp_test/acceptance-20260810/` 工作区和 README 合同；Docker 29.6.2、Compose 5.3.1、WSL Ubuntu 26.04 已记录。
- 证据与保护：原 `%USERPROFILE%/.wslconfig` 已逐字节复制为 `baseline/wslconfig.original`，原文件和副本 SHA-256 均为 `A4AE25464FC82388F85AB6C9A3C8F1914DD24174EDC126EB465A77326BF7824B`；既有 `ModelLibraryPage.test.tsx`、`tmp/npm-cache/`、`tmp/pip-cache/`、`tmp/security-20260810/` 未暂存、未删除。
- 验证方式：PowerShell 7 记录分支、HEAD、remote、dirty paths；WSL `nproc`/`/proc/meminfo` 和 Docker `NCPU/MemTotal` 输出已保存，README 明确要求命令、时间、退出码、提交、工具版本、artifact 和脱敏状态。
- 遗留事项：Task 2-5 性能、备份恢复、N-1、Chromium 和 Web 安全尚未执行；Task 6-7 的 manifest、远程 CI、提交/推送/合并继续保持未完成。

### 2026-08-13：第 9-12 周高危修复与验收闭环计划冻结

- 当前状态：第 9 至第 12 周继续保持“进行中”。新增 `docs/superpowers/plans/2026-08-13-week9-12-high-risk-remediation-closure.md`，将高危修复、四生产镜像、固定资源性能、备份恢复、N-1、外部 Chromium、四通道通知、证据 manifest、远程 CI 与合并拆分为可验证任务；本记录不是任何门禁完成声明。
- 已复现阻断一：`C:\Users\17723\miniconda3\python.exe -m unittest tests.test_evidence_manifest.EvidenceManifestTests.test_generate_rejects_weakened_security_scan_commands -v` 产生 5 个 `KeyError`（`command` / `images`）。当前结论是 semantic evidence 测试夹具没有满足新版 scanner receipt 合同而被汇总器降级；必须先修正夹具使 baseline summary 真正为 `passed`，再验证弱化命令被 manifest 拒绝，不能放松生产合同。
- 已复现阻断二：固定 4 vCPU / 8 GiB 性能验收的限流场景第 6 次请求得到 `200` 而非预期 `429`。尚未确认是 Compose 镜像/环境变量绑定、Redis key 身份、Lua 令牌桶逻辑或测试工件漂移；下一步必须在单个隔离 WSL Compose 生命周期中记录环境、settings、容器 image ID、OCI revision、Redis `HGETALL` 与每次请求状态后再写最小回归和修复。
- 提交边界：用户要求所有变更提交。任务范围内的源码、配置、测试、文档和 `ModelLibraryPage.test.tsx` 将被显式暂存并提交；`tmp/npm-cache/`、`tmp/pip-cache/`、`tmp/security-20260810/` 是约 1.18 GiB 的生成缓存/raw scanner 产物，可能含 registry 元数据或未审核证据，不使用 `git add -A` 推送。安全、脱敏、相对路径的最终摘要另行纳入正式文档；共享 `DEVELOPMENT_EXPERIENCE.md` 位于仓库外，将更新但不能随 Git 提交。
- 验证方式：当前工作树为 `codex/week9-12-mlops-core`，相对 `origin/codex/week9-12-mlops-core` 领先 7 个提交；`git diff --check` 通过。第 9 至第 12 周只有在所有本地、WSL、扫描、manifest 和远程 CI 门禁通过后才可改为“已完成”。
- 遗留事项：按新计划先修复 evidence manifest 夹具，再诊断限流；任何扫描、构建、Compose、网络、迁移、浏览器或 CI 失败都阻断推送/合并结论并需保存可复现证据。

### 2026-08-13：第 12 周 evidence manifest scanner receipt 回归修复

- 当前状态：第 9 至第 12 周继续保持“进行中”；Task 2 已完成代码与聚焦验证，但不代表最终安全或发布门禁完成。
- 问题现象：新版安全汇总器要求 Bandit、Trivy、pip-audit、npm audit、Gitleaks 和四个容器镜像 receipt 使用精确命令/原始报告合同；旧测试夹具的容器 Trivy 命令缺少 `--output` 路径，导致 aggregate summary 被降级，弱化命令回归随后访问不到 `command`/`images` 并抛出 5 个 `KeyError`。完整安全测试还暴露两个旧夹具命令形状和两个 raw 报告缺失错误优先级问题。
- 已确认根因：测试夹具没有跟随生产合同同步；manifest 对“receipt 字段缺失”和“receipt 存在但命令/返回码非法”使用同一宽泛检查，掩盖了真实语义。
- 解决方法：补齐 `test_evidence_manifest.py` 与 `test_week12_security_gates.py` 的真实 Trivy `--output` receipt；保持生产 scanner fail-closed 规则不放宽；`tools/evidence_manifest.py` 先对缺失 `command` 报 `scanner receipt missing`，对非法命令/返回码报 `scanner receipt invalid`。
- 验证方式：PowerShell 7 使用 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_evidence_manifest tests.test_week12_security_gates tests.test_ci_workflow tests.test_image_security_contracts -v`，结果 `203/203` 通过；`python -m compileall -q app tools tests` 通过；`git diff --check` 通过。
- 影响范围：Week 12 证据 manifest 解析、测试夹具和安全回归；不改变业务 API、Redis 限流算法、通知通道或扫描例外。
- 预防措施：安全证据夹具必须由真实 scanner 命令形状和原始 JSON 生成；manifest 合同变更时同时更新合法 baseline、缺失字段和弱化命令回归，并分别验证错误码。
- 遗留事项：固定 4 vCPU/8 GiB 限流第 6 次请求仍待隔离 WSL 诊断；四镜像无缓存构建/Trivy、备份恢复、N-1、完整 Chromium、最终 manifest、远程 CI 和合并仍未闭合。

### 2026-08-13：第 11-12 周运行态镜像 provenance 暂停检查点

- 当前状态：用户要求保存进度并暂停修复。第 9 至第 12 周、Task 13 继续保持“进行中”；本条只保存已验证的本地合同与静态 Compose 结果，不将其表述为 frozen stack、最终安全门禁或远程 CI 通过。
- 开发内容：为 Week 12 frozen-stack 增加受控的 `runtime-images` 证据采集和 manifest 校验。证据固定覆盖 backend（`migrate`、`backend`）、worker（`worker`、`scheduler`）、inference（`inference-runtime`）和 tensorboard（`tensorboard-gateway`）的 image reference、image ID、OCI revision 与 source commit；CI 通过 `docker-compose.week12-security-images.yml` 使用已扫描镜像并禁止运行阶段重新 build。
- 已确认行为：同组件服务镜像 metadata 不一致、非法 image ID/revision、revision 与 source commit 不一致、缺少 runtime artifact、artifact 键/服务集合非法、artifact 与 Trivy receipt 映射不一致，以及绝对/敏感 runtime metadata，均由本地合同拒绝。`environment.json` 在容器内无 `.git` 时优先使用受控的 `ACCEPTANCE_SOURCE_COMMIT`。
- 验证方式：在 `ml-platform/backend` 目录以 `PYTHONPATH=.` 运行 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_acceptance_environment tests.test_evidence_manifest tests.test_ci_workflow tests.test_week12_security_gates tests.test_image_security_contracts -q`，结果 212 项通过；其中出现的 `--pip-audit-exception legacy-exception.json` usage 输出来自受控负向 CLI 测试。随后 `C:\Users\17723\miniconda3\python.exe -m compileall -q app tools tests` 退出码为 0。WSL Docker 29.6.2 / Compose v5.3.1 在完整 CI 等价占位环境变量下执行 `docker compose -f docker-compose.yml -f docker-compose.week12-security-images.yml config -q` 退出码为 0。
- 暂停边界：未执行真实 frozen-stack `up/inspect/runtime-images/summarize/down` 生命周期，未生成最终 evidence manifest，未运行 GitHub Actions。CI scanner bootstrap 的可变下载/直接执行高危项（Trivy、Gitleaks、MinIO `mc`）尚未开始修改；恢复时先完成 RED 合同、固定 release asset SHA-256 与版本检查，再继续 WSL 验收。
- 提交边界：本次提交纳入当前任务范围的 CI、Compose override、Python 工具、回归测试和本文件。`tmp/npm-cache/`、`tmp/pip-cache/`、`tmp/security-20260810/` 为缓存或原始扫描证据，不纳入 Git。

### 2026-08-13：CI 外部安全工具固定版本与摘要校验完成

- 当前状态：第 9 至第 12 周继续保持“进行中”；本条关闭 CI scanner bootstrap 的高危源代码问题，不代表四镜像扫描、最终验收或远程 CI 已完成。
- 问题现象：CI 从 `raw.githubusercontent.com` 的可变 `main/master` 安装脚本或未校验地址获取 Trivy、Gitleaks 与 MinIO `mc`，下载内容未在执行前绑定不可变版本和 SHA-256。
- 已确认根因：历史工作流只关注工具可用性，没有把发布资产来源、完整性校验顺序和精确运行版本纳入供应链安全合同。
- 解决方法：固定 Trivy `v0.73.0`、Gitleaks `v8.24.2`、MinIO `mc` `RELEASE.2025-08-13T08-35-41Z` 的官方 GitHub Release 资产；强制 HTTPS/TLS 1.2，先做 SHA-256 严格校验，再解压、移动、授权或执行；统一安装到 `$RUNNER_TEMP/bin` 并精确比较实际版本。活动验收计划中的 Trivy 版本同步更新为 `0.73.0`，历史记录保持不变。
- 验证方式：`tests.test_ci_workflow tests.test_week12_security_gates tests.test_image_security_contracts` 共 182 项通过；`compileall`、CI YAML 解析、禁止可变安装模式扫描与 `git diff --check` 通过。官方 checksum/API 与 WSL 真实工具版本交叉确认；Gitleaks release tag 为 `v8.24.2`，但官方二进制 `version` 输出为 `8.24.2`，工作流按真实输出精确比较。Windows 直接下载曾因外部网络超时留下零字节临时文件，该结果不作为成功证据。
- 影响范围：`.github/workflows/ci.yml`、CI 回归测试和当前执行计划；不改变业务 API、扫描失败关闭策略、通知协议或镜像内容。
- 预防措施：CI 下载的可执行文件必须固定版本化发布资产并校验官方摘要；校验必须早于任何执行步骤；版本检查使用精确比较，禁止子串匹配、`curl | sh` 和可变分支安装器。
- 遗留事项：四个生产镜像无缓存构建、非 root smoke、Trivy 全镜像扫描、真实冻结 Compose、固定资源性能、备份恢复、N-1、Chromium 四角色/四通道矩阵、最终 manifest、全量回归和远程 CI 仍待完成。

### 2026-08-13：生产镜像大依赖断点续传门禁修复

- 当前状态：第 9 至第 12 周继续保持“进行中”；本条仅修复 Docker 构建对网络中断的恢复配置，四个当前提交镜像尚未重建完成，不能标记镜像或安全门禁通过。
- 问题现象：在提交 `0f6e2c9aa9ce711d8ab542b35f8f9935cad3b31b` 的无缓存 backend 构建中，阿里云 PyPI 源下载 `nvidia-nccl-cu12 2.31.2`（342.1 MB）多次中断，pip 在第六次续传后以 `incomplete-download` 失败，已接收 332.4 MB。
- 已确认根因：镜像命令只设置 `--retries 10`，该参数只控制新的 HTTP 连接；Wolfi 内的 pip `26.2.1` 对断点续传使用独立的 `--resume-retries`，默认值为 5，因此大文件网络中断未能使用预期的十次重连预算。
- 解决方法：四个生产 Dockerfile 的 pip 安装命令统一使用 `--retries 10 --resume-retries 20 --timeout 120`；镜像合同测试锁定完整命令，防止日后删除续传配置。
- 验证方式：新增合同先在旧命令上稳定 RED，再在四个 Dockerfile 修改后 GREEN；`tests.test_image_security_contracts` 7/7、`compileall -q app tools tests` 和 `git diff --check` 通过。WSL 从旧镜像确认 pip `26.2.1` 支持 `--resume-retries`。
- 影响范围：仅生产镜像内 pip 下载恢复行为和镜像合同；不变更版本 pin、基础镜像 digest、运行用户、业务代码或安全阈值。
- 遗留事项：必须以本次修复后的提交重新执行四个 `--pull --no-cache` 构建，收集 image ID/OCI revision、非 root smoke 和 Trivy HIGH/CRITICAL 报告后，才能继续 frozen Compose 与最终验收。

### 2026-08-13：backend 镜像重建再次受外部大文件网络阻塞

- 当前状态：提交 `449249ad3f61ef32bcc77b12c9653702eb5bbdf1` 已包含断点续传修复；第 9 至第 12 周继续保持“进行中”，不把旧镜像当作当前提交证据。
- 验证过程：以 `--pull --no-cache` 从该提交重建 backend；基础 Wolfi 和 Python 层通过，pip 解析确认 `xgboost==3.2.*` 的 Linux 元数据声明 `nvidia-nccl-cu12`，随后阿里云源的 342 MB wheel 长时间传输停滞。旧镜像仍无 `449249a` revision，未被复用或重标记。
- 结论：当前阻塞是外部 PyPI 大文件传输/WSL Docker 网络状态，不是依赖解析错误；项目后续 GPU 计划不允许未经评估地移除 NCCL 依赖。构建进程已停止，未生成可验收的新镜像。
- 遗留事项：四个当前提交镜像的无缓存构建、非 root smoke、Trivy 扫描及其后的 frozen Compose/最终验收仍待在可稳定下载环境完成；本地代码与合同门禁可继续独立执行。

### 2026-08-13：暂停检查点——补齐 Week 12 测试台账归属

- 当前状态：用户要求保存进度并暂停修复；第 9 至第 12 周继续保持“进行中”。
- 问题现象：恢复后首次运行 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_suite_manifest -v`，`test_every_backend_test_module_has_one_week_owner` 失败，唯一未归属模块为 `test_image_security_contracts`。
- 已确认根因：新增 Week 12 镜像安全合同测试已提交到 `tests/`，但未同步登记到 `tests/week_manifest.py`；显式 Week 11/12 归属断言也未包含该模块。完整 runner 因此在首个 manifest 门禁停止。
- 已写入修复：将 `test_image_security_contracts` 唯一登记到 Week 12，并同步加入 `test_suite_manifest.py` 的 Week 12 归属断言；本次暂停前未重新运行该测试，故修复结果仍待验证。
- 验证状态：修复前失败证据已保存；暂停前仅执行 `git diff --check`，通过（仅存在 CRLF 工作树提示）。未执行完整后端 runner、前端、Compose、镜像重建、扫描、Chromium、远程 CI 或推送。
- 未完成与恢复顺序：恢复后先运行 `tests.test_suite_manifest` 确认 GREEN，再运行完整 `run_suite.py`；随后按既有计划执行完整环境 Compose、四镜像当前提交重建/扫描和其余 Week 11-12 门禁。不得把旧镜像或定向测试当作最终验收证据。

### 2026-08-13：Week 12 测试台账恢复验证

- 当前状态：Week 12 测试台账归属修复已完成本地验证；第 9 至第 12 周仍保持“进行中”，不将本地回归表述为 Compose、镜像、安全扫描或远程 CI 通过。
- 验证结果：`C:\Users\17723\miniconda3\python.exe -m unittest tests.test_suite_manifest -v` 为 4/4；随后 `C:\Users\17723\miniconda3\python.exe run_suite.py` 为 90/90 模块通过，耗时约 548 秒，包含 `test_image_security_contracts`。
- 交叉验证：`C:\Users\17723\miniconda3\python.exe -m compileall -q app tools tests` 通过；前端 `npm test` 为 23 文件、90 用例通过；`npm run build` 成功。构建仍报告既有 ECharts chunk 大于 500 kB 警告，未在本任务中改变 bundle 策略。
- 结论：唯一遗漏的 Week 12 测试归属已在完整 backend runner 中被覆盖。下一步是使用完整 CI 等价变量复验 Compose 配置，然后在稳定 WSL/Docker 网络中从当前提交重建四个生产镜像并收集 provenance 与 Trivy 证据。

### 2026-08-14：当前提交 Wolfi 镜像重建的 BuildKit/APK 下载诊断检查点

- 当前周次：第 12 周 Task 13 镜像安全门禁；第 9 至第 12 周继续保持“进行中”。
- 已证实现象：从提交 `d060fa6997d99cc3cc7e81456b2d811325abca55` 对 backend 执行两次 `docker build --pull --no-cache`，均在固定 Wolfi `apk add` 层失败。第一次为 `APKINDEX` 请求超时后包被误报不存在；第二次为 `libbz2-1` 下载 `operation timed out`，最终返回 `rpc error: code = Unavailable desc = error reading from server: EOF`。
- 已排除边界：固定 base digest 可拉取；`python-3.11=3.11.15-r9` 与 `py3.11-pip=26.2.1-r0` 仍可解析；WSL 直接读取 APK 索引返回 HTTP 200；同一 base 通过普通 `docker run` 执行相同 `apk add` 最终退出 0 并得到 Python 3.11.15 / pip 26.2.1。普通容器下载期间仍出现超时，说明链路并非稳定。
- 当前判断：尚未证明 Dockerfile、基础镜像 digest 或固定包版本存在产品缺陷；证据指向 BuildKit/APK 外部下载链路间歇性失败。不得删除 XGBoost/NCCL、放宽 pin、复用旧 `codex-week12-final-*` 镜像或将旧镜像重标记为当前提交证据。
- 后续顺序：先以最小固定 base/固定包 BuildKit 诊断只改变 build `--network` 模式，记录构建网络边界；仅在复现出确定性产品缺陷后按 RED→GREEN 修改实现。四个当前提交镜像全部重建、非 root smoke、Trivy、frozen Compose、性能、备份恢复、N-1、完整 Chromium 和远程 CI 仍为未完成门禁。

### 2026-08-14：第 12 周 setuptools vendor bundle 高危依赖最小修复

- 当前状态：第 9 至第 12 周与 Task 13 继续保持“进行中”。本条只记录 `requirements.txt` 的最小依赖修复及本地合同/解析证据，不表示镜像、安全或发布门禁完成。
- 问题现象：顶层 requirements 已固定 `jaraco.context==6.1.0` 和 `wheel==0.46.2`，但 `setuptools==80.9.0` 自带的 vendor bundle 仍含 `jaraco.context 5.3.0` 与 `wheel 0.45.1`，对应镜像安全报告中的 HIGH 风险。
- 已确认根因：顶层分发包 pin 不会替换 `setuptools` wheel 内部随包携带的 vendor 副本；同时 TensorBoard 2.19 仍通过 `pkg_resources` 依赖 setuptools，不能直接跨到移除该接口的 setuptools 81+。
- 解决方法：仅将 `setuptools` 固定版本从 `80.9.0` 升至 `80.10.2`，并同步镜像安全合同断言；保持现有 `jaraco.context`、`wheel`、TensorBoard、MLflow、cryptography、Dockerfile 与扫描例外不变。
- 验证方式：在 `ml-platform/backend` 以 `PYTHONPATH=.` 执行 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_image_security_contracts tests.test_week12_security_gates tests.test_ci_workflow -v`，182/182 通过（11.399 秒）；`C:\Users\17723\miniconda3\python.exe -m compileall -q app tools tests` 退出码为 0；使用阿里云 PyPI 镜像、`--ignore-installed --dry-run --no-cache-dir --report` 的干净解析生成 118 条安装记录，确认 `setuptools==80.10.2`、`jaraco.context==6.1.0`、`wheel==0.46.2`、`tensorboard==2.19.0`。Windows legacy GBK 控制台不能可靠承载 `pip --report -` 的 Unicode JSON，故 report 保存在系统临时目录而非 worktree。
- 遗留事项：未运行 Docker 构建；当前 BuildKit/Wolfi APK 外部下载超时仍为独立阻塞。四个当前提交镜像重建、非 root smoke、Trivy HIGH/CRITICAL、无例外 pip-audit、frozen Compose、最终 evidence manifest、性能、备份恢复、N-1、Chromium、远程 CI、推送和合并均仍未闭合，不能宣称最终安全门禁通过。

### 2026-08-14：WSL 链接 worktree 镜像 provenance 传递修复

- 当前状态：第 9 至第 12 周继续保持“进行中”；本条修正当前提交镜像重建命令的 provenance 传递，不表示镜像、安全扫描或发布门禁通过。
- 问题现象：初次按计划从提交 23c14e0a990bfa45f2069aae97b29f1fda221475 无缓存重建 backend、worker、inference、tensorboard 四个镜像均退出 0，但其 org.opencontainers.image.revision 全部为空，故四个标签均不可作为当前提交验收或 Trivy receipt 证据。
- 已确认根因：WSL 中链接 worktree 的 .git 文件包含 Windows E:/... gitdir 路径，git -C /mnt/e/... rev-parse HEAD 解析为错误的嵌套路径；普通 PowerShell 环境变量也不会自动继承到 wsl.exe。构建脚本因未对 source commit 或实际 OCI label 做 fail-closed 校验而继续完成。
- 解决方法：验收计划改为由 PowerShell 读取并验证 40 位 SHA，再使用 wsl.exe -e env ACCEPTANCE_SOURCE_COMMIT=<SHA> bash -lc 显式传递；Bash 在每次 build 前验证 SHA 格式，并在每个 image 后读取 OCI label，不匹配即退出。
- 验证方式：PowerShell 读取的 23c14e0a990bfa45f2069aae97b29f1fda221475 经 wsl.exe -e env 到达 Bash，40 位格式断言通过；四个现有标签均已被明确检查为 revision 空值并排除。镜像静态合同 7/7 与 compileall -q app tools tests 通过；最小固定 APK 的 default 与 host BuildKit 构建均成功；Trivy 新鲜 DB 的离线 Alpine 扫描退出 0。
- 预防措施：Windows/WSL 交界不得在 WSL 中假设链接 worktree 的 Git 元数据可解析；所有 provenance-sensitive 构建必须在 build 前验证 source SHA、在 build 后验证 OCI revision，空 label 与过期扫描一律失败关闭。
- 遗留事项：须在本条文档提交后的新 HEAD 重新无缓存构建四个镜像、执行非 root smoke 和新鲜 Trivy HIGH/CRITICAL 扫描；再继续完整安全链、frozen Compose、性能、备份恢复、N-1、Chromium、远程 CI 和合并。

### 2026-08-14：新 HEAD 四镜像 provenance、运行态与合同门禁完成

- 当前周次：第 12 周 Task 13 镜像安全门禁；第 9 至第 12 周继续保持“进行中”。本条只关闭四镜像构建与运行态门禁，不表示 Trivy、完整安全链、frozen Compose、最终验收或远程 CI 通过。
- 问题现象：首次执行四镜像非 root smoke 时，宿主 PowerShell 将嵌套 Bash 片段中的 `id`、`test`、`python3.11` 当作自身命令，出现 `The term 'id' is not recognized` 和 `syntax error: unexpected end of file`。
- 已确认根因：WSL Bash 外层脚本与 Docker `sh -lc` 内层脚本使用过度嵌套的单引号转义；失败发生在宿主命令构造边界，不在镜像运行时。单镜像直接 `wsl.exe -e docker run ... -lc '...'` 可稳定复现成功。
- 解决方法：不修改镜像或生产代码；逐镜像从 PowerShell 直接调用 `wsl.exe -e docker run`，把完整 smoke 命令作为单一参数交给容器 `sh -lc`。
- 验证方式：提交 `ae5c6c5d199a54ccf485ede105cef51bc1e0f688` 后，WSL Docker 29.6.2 / Compose v5.3.1 以 `--pull --no-cache` 重建四镜像；镜像 ID 分别为 `sha256:6cd1427f4c96ebc570ce0a6665b1ec077f9bf8a42424595786512540ba8362c4`、`sha256:537d894fbd9b80c862d05554e66c570cf0b209e893cf15cfe9fbf65965861ac`、`sha256:7f9fb0584865f078290776220d25edd5f0d686abf31a1bb2ed3bb485e93d0992`、`sha256:cb3900e966a768651b6f6325d018f29d0434e6ed916ce46087dd13628ac6c80a`，四个 `org.opencontainers.image.revision` 均精确匹配该 SHA；四镜像 smoke 均为 UID 1000、`HOME=/home/app`、Python 3.11.15；`tests.test_image_security_contracts` 为 7/7，`git diff --check` 通过。
- 预防措施：PowerShell、WSL、Docker、容器 shell 多边界命令优先使用单层脚本或直接参数传递；先用单镜像最小命令验证 quoting，再运行批量循环。宿主 quoting 失败不得改写为镜像失败。
- 遗留事项：Task 5 的四镜像 Trivy HIGH/CRITICAL receipts、完整 `tools.security_scans`、pip-audit/Bandit/Gitleaks/npm audit、frozen Compose、性能、备份恢复、N-1、Chromium、四通知通道、最终 manifest、远程 CI、推送和合并仍未闭合。

### 2026-08-14：第 12 周 Task 5 容器镜像回执完整性回归

- 当前状态：新增 fail-closed 回归已完成；第 9 至第 12 周、Task 13 继续保持“进行中”，不将该本地合同替代四镜像 Trivy、完整安全链或远程 CI。
- 问题现象：聚合 `security.json` 的 `container_image.images` 若缺少任一已要求的镜像回执，汇总器必须明确拒绝；仅覆盖单个 `ArtifactName`、`Metadata.ImageID`、OCI revision 或 failed record 不能证明该 cardinality 边界。
- 解决方法：在 `tests.test_week12_security_gates` 增加真实 `summarize` 路径回归：从有效 aggregate receipt 删除一项 image，断言退出码为 1、summary 状态为 `failed`、container image gate 错误码为 `SECURITY_EVIDENCE_INVALID`。未放宽生产扫描器或把必需镜像降级为可选。
- 验证方式：`C:\Users\17723\miniconda3\python.exe -m unittest tests.test_week12_security_gates.SecurityGateTests.test_summary_rejects_missing_required_container_image_receipt_as_invalid -v` 为 1/1 通过；代码差异只增加该回归。
- 预防措施：任何 required image set 的变更同时覆盖缺回执、错误 artifact、错误 image ID、错误 OCI revision 与 failed receipt；汇总器对不完整 aggregate evidence 必须失败关闭。
- 遗留事项：仍需对最终 HEAD 的 backend、worker、inference、tensorboard 重新构建并产生四份真实 Trivy receipt，再运行完整 `tools.security_scans` 与最终 manifest。

### 2026-08-14：Task 3 Compose MinIO bucket 传播修复

- 当前状态：已定位并修复限流诊断前的 Compose 配置缺陷；第 9 至第 12 周、Task 13 继续保持“进行中”，本条不代表最终生产栈或远程 CI 通过。
- 问题现象：唯一 `MINIO_BUCKET` 隔离 Compose 生命周期中，backend/worker 使用该 bucket，而 `minio-init` 未接收变量并回退创建 `ml-platform`，造成应用对象写入 `NoSuchBucket`；该存储缺口会在限流请求前阻断诊断。
- 已确认根因：`minio-init` 的 entrypoint 已使用 `$${MINIO_BUCKET:-ml-platform}`，但其 `environment` 仅传入 MinIO root 凭据，缺失对应变量；Docker Compose 因此无法把调用方的唯一 bucket 传入 initializer。
- 解决方法：仅在 `minio-init.environment` 增加 `MINIO_BUCKET: ${MINIO_BUCKET:-ml-platform}`，保持 entrypoint 与限流生产代码不变；`test_ci_workflow` 新增回归，要求键存在、值严格匹配 fallback expression 且与 backend 相同。
- 验证方式：修复前新合同因 `MINIO_BUCKET` 缺失稳定 RED；修复后主流程独立运行 `C:\Users\17723\miniconda3\python.exe -m unittest tests.test_ci_workflow -v` 为 33/33，`git diff --check` 通过。此前同一隔离生命周期已在 capacity=5、refill=0.001 下得到 `200,200,200,200,200,429`，因此不修改 `inference_rate_limit.py`。
- 预防措施：任何 Compose initializer 使用服务可覆盖的名称、bucket、schema 或 namespace 时，必须将同一变量显式传入 initializer，并以唯一资源值的静态合同和隔离 lifecycle 验证；配置阻断不得误归因于限流器或其他业务逻辑。
- 遗留事项：提交后必须从新 HEAD 重建四镜像、重新进行非 root/Trivy/security receipt 验证；随后才可运行 frozen Compose、性能、备份恢复、N-1、完整 Chromium、最终 manifest 与远程 CI。

### 2026-08-14：第 12 周 Trivy 容器输出目录挂载修复

- 当前状态：验收计划的 Trivy 命令已完成最小 RED/GREEN 纠正；四镜像、Trivy 和安全 receipt 继续保持未完成，因为本条提交会生成新的 source commit，不能使用此前 `8956585` 标签作为最终证据。
- 问题现象：按计划在 WSL 中创建 host `temp_test` 输出目录后，`aquasec/trivy:0.73.0` 仍对四个镜像返回 exit 1，错误均为无法打开 `/mnt/e/.../trivy-image-*.json`；输出文件未产生，故该 exit code 不能解释为漏洞发现。
- 已确认根因：Trivy 在独立容器中运行，只挂载 Docker socket 和 cache volume；host 的 `$out` 路径没有挂载到扫描容器，`--output` 指向了容器内不存在的目录。历史命令同样存在该路径边界缺口。
- 解决方法：验收计划只增加 `-v "$out":/out`，并将 Trivy output 改为容器内 `/out/trivy-image-${image}.json`；Docker socket、Trivy version、cache、severity、exit-code、target image 与原始报告位置保持不变。
- 验证方式：旧命令对 backend、worker、inference、tensorboard 均复现 output path 错误；仅增加 mount 的 backend 最小复验成功写入 JSON，schema 含 `ArtifactName`、`ArtifactType` 与 `Results`，Trivy scan exit 为 0。该单镜像结果仅验证路径修复，不构成最终四镜像安全结论。
- 预防措施：任何在工具容器内使用 host output path 的命令，必须先映射 host directory 并使用 container-visible output path；在把非零退出码归因为安全 finding 前，先验证 raw report 文件存在、可解析且与预期 image ID/reference 绑定。
- 遗留事项：提交后以新 HEAD 重新无缓存构建四镜像、非 root smoke、四份 Trivy HIGH/CRITICAL report 和完整 security chain；之后才可生成 receipt、frozen Compose 和最终 manifest。

### 2026-08-14：Wolfi Python 3.11 滚动 APK 包版本修复

- 当前状态：已完成镜像静态合同的最小 TDD 修复；本条不构成新 HEAD 的 Docker 构建、Trivy 或运行态验收。
- 问题现象：四个 Python 3.11 镜像在 `apk add` 固定 `python-3.11=3.11.15-r9` 与 `py3.11-pip=26.2.1-r0`，但当前 Wolfi rolling APKINDEX 已不能解析这两个版本，导致镜像构建失败。
- 已确认根因：不可变 wolfi-base digest 不会冻结滚动 APK repository 的 APKINDEX；当前可用精确值为 `python-3.11=3.11.14-r0` 和 `py3.11-pip=25.3-r3`。
- 解决方法：只同步 `docs/security/python-base-image.json` 的 runtime 两项与 backend、worker、inference、tensorboard 四个 Dockerfile 的单一 `apk add` 行；新增 JSON runtime 精确 pin 回归，不改 base digest、retry、requirements 或安全门禁。
- 验证方式：新增测试在旧 JSON 上以 `3.11.15-r9 != 3.11.14-r0` 预期 RED；修复后聚焦测试 1/1、`C:\Users\17723\miniconda3\python.exe -m unittest tests.test_image_security_contracts -v` 为 8/8、`C:\Users\17723\miniconda3\python.exe -m compileall -q app tools tests` 退出 0、`git diff --check` 通过。
- 预防措施：使用 rolling APK repository 的精确 package pin 必须在构建前用当前 APKINDEX 验证仍可解析，并将该值以 JSON 和所有生产 Dockerfile 的同一合同锁定；静态通过后仍须在新 HEAD 单独重建和重新生成安全证据。

### 2026-08-14：Wolfi APK 瞬断重试修复

- 当前状态：已完成静态合同和最小 Dockerfile 重试修复；此前 `204d0dc` 的 backend/worker 构建结果因本次提交将过期，不能用于最终 receipt、Trivy 或运行态验收。
- 问题现象：`204d0dc` 的 backend/worker 无缓存构建已成功，但 inference 在同一 `apk add` 的 `libexpat1-2.8.3-r0` 下载阶段返回 `operation timed out`；该命令已解析当前 Python/Pip pin，失败不再是版本不可用。
- 已确认根因：生产 Dockerfile 对 Chainguard APK 包下载只执行一次；rolling registry 的单个包下载瞬断会立即使单镜像构建失败，即使同一 source、base digest 和 package pin 的其他镜像已经成功。
- 解决方法：保留不可变 base digest、精确 Python/Pip pin 和失败关闭语义，在四个 Dockerfile 的同一 `apk add` 外加入三次递增 sleep 的重试循环；第三次失败仍退出 1。新增合同要求四个生产镜像都保留精确三次重试结构。
- 验证方式：新合同在未加循环时对 Dockerfile 稳定 RED；实现后聚焦 1/1、`C:\Users\17723\miniconda3\python.exe -m unittest tests.test_image_security_contracts -v` 为 9/9、`C:\Users\17723\miniconda3\python.exe -m compileall -q app tools tests` 和 `git diff --check` 通过。
- 预防措施：外部 APK 下载故障必须先与 package pin 不可用区分；确认是瞬断后，使用有限、可审计、失败关闭的重试，并在新提交无缓存重建全部镜像后才生成安全结论。
- 遗留事项：提交后从该新 HEAD 重新无缓存构建 backend、worker、inference、tensorboard，验证非 root/OCI provenance，之后重新运行 Trivy 和完整 security chain。

### 2026-08-15：第 12 周 Task 4 冻结提交四镜像重建与 provenance 验证

- 当前周次：第 12 周 Task 4/5 镜像安全门禁；第 9 至第 12 周继续保持“进行中”。本条只关闭 `1a861a4e536c9a2ee4e597abe15e272f965348f0` 的四镜像构建、provenance 与 non-root runtime 门禁，不表示 Trivy、完整安全链、frozen Compose、最终验收或远程 CI 通过。
- 问题现象：开始时四个 `codex-week12-final-*` 标签均存在，但 OCI revision 分别仍为旧提交 `204d0dc1960053d9bae432698c1df0a2195dd749` 或 `8956585d6ccdfe082b8328533ab0f5302fa45195`，不能用于当前冻结提交的 receipt 或发布证据。按原 Bash 脚本在 WSL 内执行 linked-worktree `git -C` 时又稳定报 Windows `gitdir` 路径被错误拼接。
- 已确认根因：Windows 链接 worktree 的 `.git` 指向 `E:/...`，WSL Git 无法可靠解析该元数据；旧镜像标签是此前提交的构建产物。一次 TensorBoard 构建还遇到 XGBoost/NCCL wheel 连接中断，但 Dockerfile 的固定 `--resume-retries 20` 成功续传，未引入依赖漂移。
- 解决方法：由 PowerShell 7 读取并验证 40 位 source SHA，以 `wsl.exe -e env ACCEPTANCE_SOURCE_COMMIT=<SHA>` 显式传入 WSL；Bash 仅校验传入 SHA 格式、以 `--pull --no-cache` 构建四个镜像，并在每次构建后立即用 `docker image inspect` 精确比较 OCI revision。non-root smoke 采用 PowerShell 逐镜像直接调用 `wsl.exe -e docker run`，避免 Bash/Docker shell 的多层 quoting。
- 验证方式：WSL Docker `29.6.2` / Compose `v5.3.1` 下四个最终镜像分别得到 `sha256:4e0a3e1961ad3c370869bc24c6c084af28d391009d260ddfb7e0b2e1fcc71501`、`sha256:3778d0378b94bdf11792227e1f71fe79449c49f751adbe13fde04e3c326d4378`、`sha256:69aeaf9cb61e0649a65af2a65c26a7cf11ff1fbfe9edf45449f0d27cb56b7aca`、`sha256:0af77bace5af874a21944bba7c17f209f7835bd9aa37f5cbebe99b9f62e32e82`；四个 OCI revision 均精确匹配 `1a861a4...`，四个 smoke 均输出 UID `1000`、`HOME=/home/app`、Python `3.11.14`。`C:\Users\17723\miniconda3\python.exe -m unittest tests.test_image_security_contracts -v` 为 `9/9` 通过，`git diff --check` 通过。
- 影响范围：仅当前 WSL Docker image tags、构建缓存和验收记录；未修改应用代码、Dockerfile、requirements、生产 Compose 配置或持久化数据。
- 预防措施：跨 Windows/WSL 的 linked-worktree build 不得在 WSL 内推导 Git SHA；每个构建必须独立验证 source commit、image ID 和 OCI revision。大 wheel 的瞬断只允许有限、可审计、失败关闭的续传，完成后仍需以新 image ID 重新扫描。
- 遗留事项：Task 5 仍须从该四个 image ID 生成四份 Trivy HIGH/CRITICAL receipt，运行完整 `tools.security_scans` 与 fail-closed manifest；frozen Compose、性能、备份恢复、N-1、Chromium、四通道通知、远程 CI、推送与合并均未闭合。

### 2026-08-15：第 12 周安全回执 P1 范围收口与进度整理

- 当前状态：第 9 至第 12 周继续保持“进行中”。本条仅收口 filesystem Trivy 与 Gitleaks 证据回执的本地 fail-closed P1；工作树中的 `.gitleaks.toml`、`tools/security_scans.py`、`tools/evidence_manifest.py` 和两份安全回归测试尚未提交，不能作为当前 HEAD 的镜像、扫描、Compose 或发布证据。
- 问题现象：独立规格复审证明旧 receipt 合同可接受子目录 filesystem Trivy target、仅绑定 repository 路径而不绑定 Gitleaks 实际源树、在 Gitleaks 读取配置前产生 TOCTOU 窗口，并允许 `security/summary.json` 生成后直接篡改 Gitleaks binding 仍写出 passed manifest；snapshot 临时目录创建或清理失败也必须不能产生通过回执。
- 已确认根因：命令/原始报告验证没有把执行根精确锁为 repository root；`execution_root_sha256` 没有覆盖被扫描的文件内容；配置的验证与 scanner 实际读取之间共享可变目录；manifest 只验证通用 receipt 形状而未复算 Gitleaks 专用 binding。
- 解决方法：filesystem Trivy 固定以 repository root 为 `cwd`、最终 target 与原始 `ArtifactName` 均严格为 `.`；Gitleaks receipt 新增受控 `source_tree_sha256` 和 `isolated_read_only_snapshot` 上下文，在私有只读 source/config snapshot 内执行；summary 与 manifest 共享 live binding validator；硬链接、reparse、snapshot 创建或清理失败一律以 `GITLEAKS_SOURCE_SNAPSHOT_INVALID` 失败关闭。
- 验证方式：主线程在 `ml-platform/backend` 以 `PYTHONPATH=.` 重新运行 9 项 P1 回归，覆盖 snapshot 执行、源/配置隔离、hard-link 拒绝、snapshot 创建失败、receipt/summary/manifest 篡改拒绝和 Trivy 子目录收窄，结果 `9/9` 通过（19.534 秒）；`C:\Users\17723\miniconda3\python.exe -m compileall -q tools tests` 与限定范围的 `git diff --check` 均退出 0。实现阶段另有 `tests.test_evidence_manifest tests.test_week12_security_gates -v` 的 `184/184` 本地回归记录（206.014 秒）；它是本地合同证据，不替代完整回归或真实 scanner 验收。
- 影响范围：仅 Week 12 安全证据生成、汇总与 manifest 校验及相应回归；不改变业务 API、模型发布、通知通道、Compose 运行配置、Dockerfile 或依赖 pin。
- 预防措施：scanner receipt 必须同时绑定命令、执行根、原始 artifact、实际 source/config 字节和执行上下文；所有影响 summary/manifest 的文件必须在读取前以安全文件规则验证，并在每个下游验证边界重算 binding，不能仅信任先前的 aggregate。
- 遗留事项：最新未提交 source 会使此前四镜像 provenance、Trivy receipt 与运行态证据过期。后续仍需对提交后的新 HEAD 重建四生产镜像、运行四份 Trivy HIGH/CRITICAL、完整 `tools.security_scans` 与最终 manifest、完整后端/前端/Chromium 回归、frozen Compose、固定 4 vCPU/8 GiB 三轮性能、PostgreSQL/MinIO 备份恢复、真实 N-1 升降级、四角色/四通知通道 Web 验收、远程 CI、推送及 main 合并；这些完成前不得将 Week 9–12 标记为完成。

### 2026-08-16：第 9-12 周高危合并回归本地收口

- 当前状态：高危项的代码修复和本地完整回归已完成；第 9 至第 12 周仍保持“进行中”，直到 PR #17 的最新提交通过全部远端 CI 并合并到 `main`。旧 run `31869871802` 的失败不能作为当前通过证据。
- 问题现象：主线合并后，完整 CI workflow 被缩减且 job-level `env` 使用了不允许的 `runner.temp` 上下文；生产与实验集成缺少通知加密密钥/证书。代码侧同时出现两个 Alembic head、点焊路由和恢复逻辑遗漏、平台用户审计与角色边界回退、管理员绕过项目成员隔离，以及 React Router 例外扫描对测试写法和 namespace import 的误报。
- 已确认根因：跨分支合并只处理了文本冲突，没有重新验证 workflow 表达式上下文、迁移 DAG、路由注册、权限矩阵和审计动作的组合合同；测试夹具及前端导入形状也没有同步到合并后的安全扫描规则。
- 解决方法：恢复生产、实验、通知、安全和 Week 11-12 完整 CI jobs，改用 `/tmp` 受控路径并在 job 内生成权限为 `0600` 的 Fernet key 与短期证书；新增 `20260815_11` merge revision 合并通知与点焊迁移 head；恢复点焊模型/路由、孤儿项目和本地质量任务修复、平台用户角色校验/自操作阻断/审计、通知权限，并保持平台管理员仅在全局 dashboard 拥有全局视图而不绕过项目成员隔离。前端测试改用真实 Router/JSX，抽离可视化节点判断并使用具名 import，保留 React Router 例外的 fail-closed 范围。
- 验证方式：`tests.test_week12_security_gates` 为 `153/153`；`run_suite.py` 最终为 `111/111` 模块；前端 Vitest 为 `43/43` 文件、`203/203` 用例，生产构建通过；`tests.test_ci_workflow` 为 `33/33`；`alembic heads` 仅返回 `20260815_11 (head)`；`git diff --check` 通过。首次完整后端回归暴露 5 个模块失败，修复后第二轮仅发现 stale Gitleaks binding 的错误测试期望，恢复 `SECURITY_EVIDENCE_INVALID` 后安全模块和第三轮完整后端回归均通过。
- 提交边界：只提交 Week 9-12 高危修复、对应回归和本记录；`tmp/npm-cache/`、`tmp/pip-cache/`、`tmp/security-20260810/` 保持未跟踪且不推送。
- 遗留事项：推送新提交到 `codex/week9-12-mlops-core`，等待 PR #17 的全部 GitHub Actions jobs 完成；任一 job 失败必须按精确日志继续修复。全部通过后方可合并到 `main` 并验证远端 main 包含合并提交。

### 2026-08-16：PR #17 首轮远端 CI 跨平台与诊断链修复

- 当前状态：Actions run `31917549971` 已确认 Ubuntu Quality、生产集成和实验集成失败；本轮修复已通过 Windows/Linux 聚焦回归及完整安全合同，但尚未推送，Week 9-12 与 PR #17 继续保持“进行中”。
- 问题现象：MinIO client 已下载且 SHA-256 校验通过，却因版本字段读取错误中止；两个集成 job 的失败证据步骤把 `sed -E` 写成文件参数，导致原始容器日志未能保留。Ubuntu Quality 还出现 `WindowsPath` 在 POSIX 实例化、测试绑定特权端口 443、以及 pip/npm 单元测试被真实 Gitleaks 工作树快照状态干扰。
- 已确认根因：`mc --version` 的 release 位于首行第 3 列；GNU sed 的扩展正则选项必须放在表达式前；命令解析与脱敏使用了会跟随被 mock 的 `os.name` 选择具体实现的 `Path`；通知验收未显式选择临时端口；依赖审计测试没有隔离不属于其断言目标的 Gitleaks 快照边界。Git checkout 的 `.git` 元数据也不属于 `--no-git` 产品源码范围，可能包含 checkout 管理的特殊文件。
- 解决方法：CI 改为读取 `mc` 第 3 列并使用 `sed -E -i -e ...`；命令 shim 与脱敏改用 `PurePath`；通知接收器测试使用 `https_port=0`、`events_port=0`；Gitleaks 源快照与配置契约排除根 `.git`，仍对产品源码 symlink/reparse/hard-link 失败关闭；pip/npm 测试 mock 独立 Gitleaks 快照边界。
- 验证方式：Windows 聚焦回归 `42/42`；Linux 后端镜像复现的原失败集合 `7/7`；`tests.test_week12_security_gates tests.test_ci_workflow tests.test_notification_receiver_acceptance` 完整回归 `190/190`。完整 runner 首轮为 `110/111`，唯一失败是 manifest 测试夹具仍计算旧 Gitleaks 范围；同步 `.git` 排除后 `tests.test_evidence_manifest` 为 `31/31`。UID 模拟未复现 migrate 读取密钥失败，Alembic 完整升级到 `20260815_11` 并退出 0，因此未引入无证据的权限放宽或 `chown`。
- 预防措施：外部 CLI 的版本输出要用真实 runner 输出建立合同；failure-evidence 脚本必须自身可执行且先保存 raw log；跨平台测试不得通过修改全局 `os.name` 后实例化具体 `Path`；网络测试显式使用临时端口；单一门禁测试隔离无关安全 gate，同时保留对应 gate 的独立失败关闭回归。
- 遗留事项：提交并推送本轮修复，等待新的 PR #17 Actions 全部结束；生产或实验集成若仍失败，使用已修复的 redacted evidence 读取精确容器日志后继续处理。全部远端门禁通过前不得合并或标记 Week 9-12 完成。

### 2026-08-16：PR #17 实验栈非 root 密钥挂载修复

- 当前状态：Actions run `31919525599` 的生产集成已通过；实验集成失败证据已成功上传并确认根因。本轮权限修复尚未推送，双平台 Quality 的该 run 不再作为最终门禁。
- 问题现象：实验 Compose 的 `migrate` 容器在导入配置时以 `NOTIFICATION_MASTER_KEY_FILE could not be read` 退出 1；证据中的 Pydantic traceback 已完成脱敏并保留。
- 已确认根因：GitHub runner 以 UID 1001 创建宿主 `/tmp/notification-master.key` 且模式为 `0600`，Compose 将该文件只读挂载给 UID 1000 的非 root Python 容器；本地此前未改变 owner 的模拟没有覆盖该真实 UID 边界。
- 解决方法：只对需要挂载进非 root 容器的实验 key 和 Week 11-12 frozen-stack key 执行 `sudo chown 1000:1000`、`sudo chmod 0400`；失败证据用 `sudo cat` 读取 key 进行泄漏扫描。宿主直接运行的 production key 保持 runner 所有，不修改 Compose 用户或放宽为 group/world readable。
- 验证方式：`tests.test_ci_workflow` 为 `35/35`，workflow YAML 可解析，`git diff --check` 通过；WSL 中 UID/GID `1000:1000`、mode `0400` 的宿主文件由 `--user 1000:1000` 容器以只读 mount 成功读取。
- 预防措施：CI 生成并 bind-mount 给非 root 容器的 secret 必须同时验证 owner、mode、容器 UID 和失败证据读取路径；本地权限模拟要断言实际 UID/GID，而不能只依赖 chmod。
- 遗留事项：推送后等待新 Actions run 的实验集成、双平台 Quality、Chromium 和 Week 11-12 verification 全部通过，再合并 PR #17。

补充：run `31919874046` 的实验栈已完成镜像构建、migrate、backend、worker 和 runtime 启动；失败仅来自 runner UID 1001 在 cleanup 阶段直接删除 UID 1000 所有的 key。已将实验和 frozen-stack cleanup 改为 `sudo rm -f`，并把该清理路径加入 CI 合同测试。

### 2026-08-16：PR #17 受控通知接收器证书权限修复

- 当前状态：Actions run `31920999493` 的生产集成已通过；实验集成失败证据已补充 `notification-receiver` 与 `notification-proxy` 日志并确认精确根因。本轮修复本地合同已通过，仍需推送后等待新的双平台 Quality、生产/实验集成、Chromium 与 Week 11-12 verification 全部通过，之后才能合并 `main`。
- 问题现象：实验栈的 migrate、backend、worker、scheduler、MLflow 与 inference runtime 均能启动，但 `notification-receiver` 在 `ssl.SSLContext.load_cert_chain()` 读取 `/run/secrets/notification_receiver_private_key` 时以 `PermissionError: [Errno 13] Permission denied` 退出，导致 `docker compose up --wait` 失败。
- 已确认根因：CI runner 创建接收器证书、私钥和 CA 后仅执行 `chmod 600`，文件仍属于 runner UID；Compose 将其挂载给默认 UID 1000 的非 root backend 镜像。此前只修复了 notification master key 的 owner，未把同一非 root secret 合同应用到 TLS 文件。
- 解决方法：证书生成后统一执行 `sudo chown 1000:1000` 与 `sudo chmod 0400`，保持 owner-only read；cleanup 统一用 `sudo rm -f`。失败证据服务列表永久包含 `notification-receiver` 和 `notification-proxy`，避免再次只得到 compose 退出码。
- 验证方式：`C:\\Users\\17723\\miniconda3\\python.exe -m unittest tests.test_ci_workflow -q` 为 `35/35`，新增断言覆盖 TLS 文件 owner/mode，失败证据合同覆盖两个受控通知服务，`git diff --check` 通过。远端 CI 尚未对本次提交完成验证，因此不标记 Week 9-12 完成。
- 预防措施：所有由 runner 生成并挂载给非 root 容器的 secret、证书和私钥必须共享 owner/mode/consumer UID/cleanup 合同；Compose 启动失败的 evidence 必须包含所有被 `depends_on` 或 healthcheck 阻断的服务日志。

补充：修复 TLS 文件 owner 后，run `31921375165` 已证明 `notification-receiver` 为 healthy，生产集成仍通过；实验栈随后因 `notification-proxy` 显式禁用 healthcheck 而被 `docker compose up --wait` 拒绝。已为 proxy 增加 UID 1000 容器内的 `127.0.0.1:3128` TCP listener healthcheck，聚焦 CI/receiver 合同 `37/37` 通过，等待新远端 run 验证。

补充：run `31921710113` 已证明 receiver 和 proxy 均通过 `docker compose up --wait`，实验验证进入真实 MLflow 生命周期后因 `Host: mlflow:5000` 未在 MLflow 3.15 allowlist 中而返回 403。生产 Compose 已显式传入可配置的 `MLFLOW_ALLOWED_HOSTS`，默认仅允许内部 `mlflow:5000` 与 localhost/127.0.0.1 健康检查；CI 合同 `36/36` 通过，等待新远端 run 验证。

补充：run `31921969798` 已证明 MLflow Host allowlist 生效，实验栈迁移完成到当前合并头 `20260815_11`；失败仅来自 `test_inference_production_stack` 仍断言旧的 `20260720_10_security_notifications`。已将运行态断言同步到当前单一 Alembic head，相关模块本地收集 `2` 项均跳过（缺少真实栈），等待新远端 run 验证。

补充：run `31922307340` 已通过实验训练、推理发布/回滚、迁移 head、receiver/proxy 和 Webhook/企业微信验证；唯一失败为 Mailpit 邮件 outcome 返回 `retry`。根因是生产 Compose 将未配置的 SMTP 用户名/密码传为两个空字符串，Pydantic 解析为非 `None` SecretStr，适配器错误尝试空凭据 AUTH；现已把双空值规范化为无认证，仍对只配置一侧失败关闭。通知/生产栈/CI 聚焦回归 `58` 项通过、`6` 项无真实栈跳过，等待新远端 run 验证。

补充：run `31922736096` 已通过生产集成、实验集成、Ubuntu Quality 与双平台后端 `111/111`；Windows 前端仅两个长交互测试分别以 5.437 秒超过默认 5 秒、16.972 秒超过局部 15 秒而超时，未出现功能断言失败。仅将这两个测试的局部超时调整为 15 秒和 30 秒，聚焦 Vitest `2/2` 文件、`31/31` 用例通过，不放宽全局超时；等待新远端 run 全绿后再合并。

补充：run `31923820309` 已再次通过两个集成 job、Ubuntu Quality 和双平台后端 `111/111`，前两个超时测试也已通过；Windows runner 仅暴露同一 AutoML 文件中另一个历史耗时 4.742 秒、当次 5.305 秒的质量报告交互测试超过默认 5 秒。该测试增加 15 秒局部 timeout 后，AutoMLPage 聚焦 `18/18` 通过；全局 timeout 保持不变，等待新远端 run。

补充：run `31925024068` 的生产集成、实验集成和双平台 Quality 全部通过；Chromium 验收的应用和 11 个核心路由均已正常渲染，唯一失败是 `core-navigation.spec.ts` 仍断言已移除的 `AI模型训练编排平台`。历史提交 `babf6a7` 已将该验收标识更新为 `智擎`，但后续分支整合保留了旧 E2E 文件；现已恢复批准过的 `智擎` 断言，本地精确 Playwright 用例 `1/1` 通过，待推送后重跑完整 CI 和 Week 11-12 verification；新 run 全绿前仍不合并。

### 2026-08-16：PR #17 新增 setuptools CVE 与 Gitleaks 快照清理修复

- 当前状态：run `31926635306` 的生产集成、实验集成、Ubuntu/Windows Quality 和 Chromium 验收均通过；`Week 11-12 verification` 在安全汇总阶段失败。本轮已完成最小修复与本地真实扫描，但尚未推送；新 Actions run 的全部 job 成功前，第 9 至第 12 周继续保持“进行中”，PR #17 不合并。
- 问题现象：真实 `pip-audit 2.10.1` 对 `setuptools==80.10.2` 报告 `CVE-2026-59890`，修复版本为 `83.0.0`；Gitleaks 原始报告在 Ubuntu 生产环境示例的三项应用密钥占位值上命中 `Generic API Key`，同时 aggregate receipt 被记录为 `GITLEAKS_SOURCE_SNAPSHOT_INVALID`，掩盖了真实 scanner return code。
- 已确认根因：TensorBoard 2.19 依赖已被 setuptools 82 移除的 `pkg_resources`，所以不能只升级 setuptools；TensorBoard 2.21 已移除该运行时导入并可与 setuptools 83 配合。Gitleaks 快照被设为只读后，POSIX 删除失败发生在父目录缺少写权限；原 `shutil.rmtree` 回调只修改当前失败路径，清理失败后按 fail-closed 设计覆盖了 scanner findings。示例中的长大写占位字符串又满足 Generic API Key 规则。
- 解决方法：将 TensorBoard 固定到 `2.21.*`、setuptools 固定到 `83.0.0`；生产环境示例的 `SECRET_KEY`、`TENSORBOARD_SESSION_SECRET`、`INFERENCE_INTERNAL_SECRET` 改为空值，继续由现有注释要求使用 `openssl rand -hex 32` 填充。快照删除回调仅在快照根内先恢复失败路径父目录的 owner `rwx`，再恢复当前路径并重试，不放宽 Gitleaks 规则、扫描范围或失败关闭语义。
- 验证方式：三条回归均先在旧实现 RED；修复后 Windows 聚焦合同 `232/232` 通过、POSIX-only 用例 `1/1` 在 Linux 容器通过。完整 requirements 干净解析为 126 个安装项，包含 TensorBoard `2.21.0`、setuptools `83.0.0`、protobuf `6.33.6`、grpcio `1.83.0`；真实 `pip-audit` 审计 125 个依赖、0 漏洞；Gitleaks `v8.24.2` 对当前 reviewed source scope 扫描 0 leaks；TensorBoard 2.21/setuptools 83 overlay 下训练与 gateway 回归 `12/12` 通过。
- 预防措施：只读安全快照的删除测试必须在 POSIX 上覆盖父目录权限；scanner 结果与快照 lifecycle 错误必须分别可诊断。打包工具安全升级若跨越移除 API 的版本，必须同步升级实际调用该 API 的上游依赖，并验证 resolver、真实 audit、导入路径和业务运行回归；部署示例中的应用密钥默认保持空值，生成方式写在注释中。
- 遗留事项：完成 compile/diff/范围审查后提交并推送 PR #17；等待新 run 的六个 job 全部成功，再通过 PR 合并到 `main` 并验证远端 `main`、merge commit 和工作树边界。不得提交 `tmp/npm-cache/`、`tmp/pip-cache/`、`tmp/security-20260810/` 或 `tmp/ci-31926635306-week11-12-2/`。

补充：run `31929782258` 已通过生产集成、实验集成和 Ubuntu Quality；Windows Quality 的后端 `111/111` 也通过，但 `AutoMLPage` 的“启动质量感知”测试在前端阶段断言 `createQualityRun` 调用次数为 0。根因是测试只等待 preview API 被调用，没有等待 preview Promise 完成并把输入列写入 React 状态；Windows runner 上按钮仍为 disabled，点击不会触发提交。用例现改为先等待“运行质量感知”按钮 enabled 再点击，不修改生产代码或 timeout；聚焦 `1/1`、完整 AutoMLPage `18/18` 通过，待新 run 全绿后再合并。

### 2026-08-16：PR #17 Week 11-12 安全摘要 stale Gitleaks 回执修复

- 当前状态：run `31931087538` 的五个 job 已通过，`Week 11-12 verification` 在 `Summarize security evidence` 失败；第 9 至第 12 周仍保持“进行中”，未合并。
- 问题现象：扫描回执中的 Gitleaks `source_tree_sha256` 在冻结栈启动后的汇总阶段失效，所有安全门被统一标记为 `SECURITY_EVIDENCE_INVALID`。
- 已确认根因：`run security scans` 在测试套件之后执行，工作树中已存在 `__pycache__`、SQLite `*.db*`、`artifact_store` 等被 `.gitignore` 忽略的运行时生成物；冻结栈迁移和服务启动会改变这些字节，而源树摘要原先仍把它们纳入绑定。
- 解决方法：将 Gitleaks reviewed source scope 与 `.gitleaks.toml` 同步扩展为排除 `__pycache__`、`artifact_store`/`uploads`/`exports` 和 SQLite `*.db`/`*.db-shm`/`*.db-wal`；新增回归验证扫描后修改这些生成物不会改变摘要。未放宽源码、配置、快照或 manifest 的 fail-closed 校验。
- 验证方式：新增 stale-runtime-output 回归 `1/1`；Week 12 security gates `157/157`、evidence manifest `31/31`、CI workflow `36/36` 通过，待提交后重新运行完整远端六门禁。
- 遗留事项：完成 diff/compile 检查后提交并推送；等待新的双平台 Quality、生产/实验集成、Chromium 和 Week 11-12 verification 全部成功，再合并 `main`。

### 2026-08-16：PR #17 frozen-stack data 挂载导致安全摘要漂移修复

- 当前状态：Actions run `31937388470` 的生产集成、实验集成、Ubuntu/Windows Quality 和 Chromium 验收均通过；`Week 11-12 verification` 仍在 `Summarize security evidence` 失败，因此第 9 至第 12 周继续保持“进行中”，PR #17 未合并。
- 问题现象：安全扫描阶段的 Gitleaks receipt 全部通过，但 frozen-stack 启动后汇总仍将六个 scanner gate 统一标记为 `SECURITY_EVIDENCE_INVALID`；上传证据确认 web security 独立通过。
- 已确认根因：`docker-compose.yml` 将宿主 `./ml-platform/backend/data` 绑定到 `/app/data`。扫描时该宿主目录不存在，随后 `docker compose up` 会创建它；源树摘要会记录目录路径，因此即使目录为空也会使 `source_tree_sha256` 失效。上一轮仅排除了目录内常见数据库和 artifact 字节，没有覆盖 Compose 创建目录本身。
- 解决方法：只将精确运行时挂载 `ml-platform/backend/data` 加入 Gitleaks reviewed source scope、TOML 配置合同和两套证据夹具；不排除其他名为 `data` 的目录。回归同时断言该挂载在扫描后创建或写入不会改变摘要，而 `services/data` 等普通源码路径仍会改变摘要。
- 验证方式：新增精确 digest 回归先 RED 后 GREEN，真实 `summarize` 生命周期回归通过；Week 12 security gates `158/158`、evidence manifest `31/31`、CI workflow `36/36` 通过。待完成 compile、diff 和提交范围审查后推送，并重新等待完整六门禁。
- 遗留事项：新 Actions run 全部成功前不得合并或标记 Week 9-12 完成；若安全摘要仍失败，必须继续使用上传 artifact 对比具体 binding，不能扩大为通用 `data` 排除。

### 2026-08-16：PR #17 scanner receipt 与 Trivy 0.73 报告合同修复

- 当前状态：Actions run `31940235443` 的生产集成、实验集成、Ubuntu/Windows Quality 和 Chromium 验收均通过；`Week 11-12 verification` 仍在 `Summarize security evidence` 失败。已用 artifact `9262316127` 将失败隔离到两个确定的格式合同，本地修复和回归已完成，但新提交尚未推送，因此第 9 至第 12 周继续保持“进行中”，PR #17 未合并。
- 问题现象：Gitleaks receipt 的 `source_tree_sha256=f166c64b...` 已与 merge commit `447d9f3` 的干净 checkout 精确匹配，但 summary 仍把六个 scanner gate 统一判为 `SECURITY_EVIDENCE_INVALID`。逐项绕过 Gitleaks binding 后，`frontend_dependencies` 的 passed receipt 命令校验失败；修正该格式重放后只剩 `filesystem_trivy` 失败。
- 已确认根因：`run_scan` 会把任何含 `://` 的命令参数脱敏为 `[redacted-url]`，因此固定的 `--registry=https://registry.npmjs.org` 在落盘后不再满足 `is_required_scan_command` 的精确合同。真实 Trivy `0.73.0` 对 Git checkout 执行根目录 filesystem scan 时返回 `ArtifactName: "."`、`ArtifactType: "repository"`，而汇总器只接受旧形态 `filesystem`。
- 解决方法：将固定 npm registry 参数提取为单一常量，并仅对这一公开、受审查参数保留原值；其他 URL 仍继续脱敏，命令校验仍要求精确官方 registry。filesystem Trivy 原始报告允许 `filesystem` 或 `repository` 两种合法类型，同时继续强制 repository-root 命令、literal `.` target、`ArtifactName == "."`、无 HIGH/CRITICAL 漏洞、无 misconfiguration/secret finding；container image 仍只接受 `container_image`。
- 验证方式：两条回归均先在旧实现 RED，修复后 `2/2` 通过；将真实 run `31940235443` artifact 的 npm receipt 按新输出格式重放并仅隔离机器相关的 Gitleaks live path binding 后，七个 security gates 全部 passed。`tests.test_week12_security_gates tests.test_evidence_manifest tests.test_ci_workflow -v` 为 `227/227` 通过，另有 1 项 Windows 上按预期跳过的 POSIX 权限测试。
- 预防措施：scanner receipt 的脱敏输出必须由同一生产 validator 接受，新增或修改命令参数时要覆盖“执行 -> 脱敏落盘 -> summarize”生命周期；外部 scanner 的 schema 合同必须用真实 pinned 版本 artifact 验证，不能只依赖手写旧格式 fixture。
- 遗留事项：完成 compile、diff、提交范围审查后提交并推送；等待新 run 的六个 GitHub Actions jobs 全部成功。只有全绿后才合并 PR #17 到 `main`，并核验 PR 状态、merge commit、远端 `main` 和保留的未跟踪目录。
