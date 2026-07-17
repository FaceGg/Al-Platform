# 汽车焊接工业 AI 平台开发文档

> 文档状态：持续维护
> 最近更新：2026-07-17
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
- 实验跟踪、训练检查点、指标对比、AutoML Trial 和 TensorBoard。
- Pipeline 定时、补录、依赖、并发、优先级、暂停和恢复。
- 模型注册、模型版本、审批、部署关联和模型卡。
- 推理服务、在线测试、滚动升级、灰度、限流、监控和回滚。
- 完整 RBAC、项目角色、SSO、操作审计和企业消息通知。
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
| 第 6 周 | 未开始 | 实验与训练管理 | 实验、Run、参数、指标、日志、制品、检查点、恢复、早停和 TensorBoard | 企业基础版、实验训练追踪 |
| 第 7 周 | 未开始 | Pipeline 调度与权限 | Cron、补录、依赖、并发、超时、重试、暂停恢复、项目角色和审计 | 调度器、实例管理、权限审计 |
| 第 8 周 | 未开始 | 模型注册与基础推理 | 模型版本、指标、审批、基础推理、在线测试、健康检查和服务启停 | 模型注册中心、基础推理服务 |
| 第 9 周 | 未开始 | 推理服务生产化 | 多版本发布、滚动升级、回滚、密钥、限流、服务日志和运行指标 | 生产级推理服务、版本发布回滚 |
| 第 10 周 | 未开始 | 权限、审计与通知 | 项目角色、资源权限、关键操作审计和企业消息通知 | 权限矩阵、审计日志、告警通知 |
| 第 11 周 | 未开始 | 系统联调与性能优化 | 联调数据、Pipeline、实验、模型和服务；完成核心性能优化 | 全链路版本、性能基线、问题清单 |
| 第 12 周 | 未开始 | MLOps 核心版验收 | 功能、E2E、权限、性能、安全、备份恢复和升级验证 | 企业 MLOps 核心版、验收报告 |
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

1. 建立真实功能台账，区分生产可用、功能可用、原型和未实现。
2. 修复前端构建、国际化和工作流运行的残留问题。
3. 固化工作流运行状态机和节点输入输出协议。
4. 规范数据库、上传目录、测试数据库和临时数据目录。
5. 建立可重复执行的前端、后端和 E2E 测试命令。

### 5.2 当前未完成

- 第 1 周代码、测试和文档已验收；Docker 因当前机器未安装 Docker，保留为补充环境验收项。
- 2026-07-14 已完成临时文件分类清理；正式源码和测试仍有大量未提交修改，需在发布前按范围审查并提交。
- 当前开发文档与共享经验文档已建立，后续开发必须持续维护。
- 第 2 周核心代码和自动化测试已完成；第四周已补充 Playwright 焊接质量主流程。
- 第 5 周已完成：本地后端 46/46、第五周 13/13、前端 35/35、构建、Chromium 1/1、WSL 生产栈 4/4 均通过；远程交付证据为 [Actions Run 29548916619](https://github.com/FaceGg/Al-Platform/actions/runs/29548916619)。
- 第 4 周已完成：后端当前 33/33、前端当前 35/35、构建、Playwright、Windows 脚本以及 GitHub Ubuntu 22.04 质量门禁和 Chromium 验收全部通过；远程交付证据为 [Actions Run 29381233328](https://github.com/FaceGg/Al-Platform/actions/runs/29381233328)。

## 6. 每周验收检查表

- [ ] 本周范围与验收条件已冻结。
- [ ] 代码已完成审查并合并。
- [ ] 单元测试、API 集成测试和相关 E2E 已通过。
- [ ] 数据库、配置和接口变化已更新迁移与文档。
- [ ] 测试环境能够独立部署和演示。
- [ ] 日志、指标和错误信息能够支持问题定位。
- [ ] 未完成项已转入下一周并记录原因。
- [ ] 本周问题已追加到本文档末尾。
- [ ] 可复用经验已追加到共享经验文档。

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
