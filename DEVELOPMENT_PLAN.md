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
| 第 11 周 | 进行中 | 系统联调与性能优化 | 已开始独立性能工具、固定环境基线、备份升级夹具和联调验收设计；最终测量等待第 9-10 周接口冻结 | 全链路版本、性能基线、问题清单 |
| 第 12 周 | 进行中 | MLOps 核心版验收 | 已开始安全、备份恢复、升级、E2E 和证据清单设计；最终验收等待第 9-11 周门禁通过 | 企业 MLOps 核心版、验收报告 |
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
- 第 9 至第 12 周已完成并行范围审计和设计确认，正式规格为 `docs/superpowers/specs/2026-07-20-week9-12-mlops-core-design.md`；实施计划和生产代码尚未开始。
- 第 11 周最终性能结论依赖第 9-10 周接口、Schema 和发布行为冻结；第 12 周最终验收依赖第 9-11 周门禁通过，不得因并行启动提前标记完成。

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

### 2026-07-22：产品壳层 UI 方向预览

- 当前周次：第 9 至第 12 周并行设计支持工作。
- 开发内容：为汽车焊接工业 AI 平台生成三个可比较的完整产品壳层预览，包含侧栏、顶栏、数据驾驶舱和项目列表。
- 问题现象：现有产品页面使用稳定的功能语义，但尚未有不影响生产路由的可视化方向比较入口。
- 根因：生产 React 组件、认证、API 和主题令牌直接耦合，不适合在未选定方向前直接替换。
- 解决方法：新增 `ml-platform/frontend/ui-previews/index.html` 作为自包含静态预览，以共享内容模型切换冷黑工业、纸张实验室和午夜电蓝三种视觉方向。
- 验证方式：通过本地静态服务器检查三种方向和窄屏预览；确认 `ml-platform/frontend/src/` 未被修改。
- 影响范围：仅新增预览和设计记录，不影响生产前端、路由、API 或部署配置。
- 预防措施：最终视觉方向必须由用户选择后再进入独立的生产改造任务，并保持 IA、路由和已有可访问性契约稳定。
- 遗留事项：等待用户选择方向或提出混合调整后，再设计生产实施范围。


### 2026-07-22：UI 方向预览迭代 - 圆润科技控制台

- 当前周次：第 9 至第 12 周并行设计支持工作。
- 开发内容：根据反馈将预览重构为更具科技感和圆润感的未来工业控制台。
- 解决方法：统一采用蓝青色状态语汇、20px 左右的模块圆角、半透明层叠面板、柔和边界和栅格背景；三套方案更新为智能光舱、白色未来和夜航脉冲。
- 验证方式：浏览器验证主题切换、窄屏 560px 重排、无水平溢出及零控制台错误。
- 影响范围：仅修改独立预览 HTML，不影响生产 React 代码、路由、API 或部署配置。
- 遗留事项：等待用户确认最终方向或提出组合调整。

### 2026-07-22：全项目测试覆盖缺口补全（只测不改）

- 开发内容：在不修改任何源代码的前提下，分析 `ml-platform/backend` 测试套件覆盖缺口，新增 12 个测试模块共 153 个测试用例，覆盖优化算子、工具算子、可视化算子执行、存储工厂、事件发布、推理任务、工作流执行服务、WebSocket 管理器、标注 API、工作流直接 API、Pydantic schemas 校验、ORM 模型自引用关系。
- 新增测试文件：
  - `tests/test_operators_optimization.py`（8 项，GridSearchCV/RandomizedSearchCV/Optuna 算子契约与超参输出）
  - `tests/test_operators_utility.py`（ExecutePython/Collect/Macro/WriteAsText 数据流转与文件落盘）
  - `tests/test_operators_visualization_execution.py`（ROC/特征重要性/分布/散点/直方/折线/混淆矩阵/数据表/统计算子执行并产出 base64 图表）
  - `tests/test_storage_factory.py`（5 项，StorageFactory 根据配置返回 LocalStorage/MinIOStorage 且单实例缓存）
  - `tests/test_events_local.py`（8 项，LocalRunEventPublisher 顺序回调、异常隔离、取消传播、NullRunEventPublisher 空实现）
  - `tests/test_inference_tasks.py`（5 项，InferenceTaskRepository CRUD 与按状态过滤）
  - `tests/test_workflow_execution_service.py`（8 项，WorkflowExecutionService 拓扑排序、参数合并、事件发布、循环/孤立节点容错）
  - `tests/test_websocket_manager.py`（连接/断开/广播/失败连接清理）
  - `tests/test_api_annotations.py`（标注任务 CRUD、样本列表、auto-label 流程、删除）
  - `tests/test_api_workflows_direct.py`（直接工作流 GET/PUT/DELETE 与 owner/editor/viewer/outsider 权限边界）
  - `tests/test_schemas_validation.py`（39 项，ProjectCreate/Update、WorkflowCreate/Save、UserCreate/Update 等 Pydantic 校验规则）
  - `tests/test_models_misc.py`（AgentTask 自引用关系、ProjectMember 唯一约束等 ORM 行为）
- 问题与解决：
  1. `ExecutePython` 算子将输入转为 DataFrame 注入脚本命名空间，`inp[0]` 是列访问而非行访问，KeyError: 0 → 改用 `inp.copy(); out['x'] = out['x'] + 5` 的 DataFrame 操作。
  2. `WriteAsText` 的 json 格式使用 `df.to_json(orient="records", indent=2)`，产出 `"a":1`（无空格）而非 `"a": 1` → 断言改为匹配实际输出格式。
  3. `ConnectionManager.broadcast` 中失败连接被清理但 good 连接保留，`run-1` key 不会删除 → 断言改为 good 保留、bad 被移除。
  4. `AgentTask.children = relationship("AgentTask", backref="parent", remote_side="AgentTask.id")` 中 `remote_side` 设为 PK，导致 `children` 实际是 many-to-one（返回父级），`parent` backref 是 one-to-many（返回子级集合）→ 断言方向修正。
  5. `AnnotationResult.task_id` 是 `UUID(as_uuid=True)` 列，传字符串触发 `'str' object has no attribute 'hex'` → 用 `uuid.UUID(self.task_id)` 转换并添加 `import uuid`。
  6. SQLite 不强制 `ON DELETE CASCADE` 且 ORM 关系无 `cascade="delete-orphan"`，删除 AnnotationTask 时 SQLAlchemy 尝试将子记录 `task_id` 设为 NULL 触发 NOT NULL 约束 → 在删除 task 前手动删除子 AnnotationResult 记录。
  7. `resolve_workflow_access` 对非项目成员返回 404 "hidden"（`ProjectAccessError(hidden=True)`），只有项目成员但权限不足才返回 403 → viewer 必须先通过 `ProjectMember(role="viewer")` 成为项目成员才能触发 403 权限拒绝路径。
  8. `ConfusionMatrixPlot` 算子从 `per_label[0]` 构建 2x2 矩阵，但 `labels` 从所有 `per_label` 条目派生；只有 1 个条目时 labels 有 1 项但矩阵有 2 列，matplotlib `set_xticklabels` 报 FixedLocator 数量不匹配 → 补充第二个 `per_label` 条目使 labels 数量匹配 2x2 矩阵维度。
- 潜在问题：
  - SQLite 与 PostgreSQL 在外键级联行为上存在差异（SQLite 默认不强制 ON DELETE CASCADE），测试中需手动清理子记录；生产 PostgreSQL 环境下行为可能不同，迁移时需关注。
  - `ConfusionMatrixPlot` 算子的 labels 派生逻辑与矩阵构建逻辑维度不一致是源代码层面的潜在缺陷，当前仅在测试侧通过补齐 per_label 条目规避；后续可考虑在源码侧修正 labels 派生或矩阵构建逻辑。
  - `AgentTask` 的 `children`/`parent` 命名与实际关系方向不符（`children` 返回父级，`parent` 返回子级集合），是源码命名层面的易混淆点，使用时需特别注意。
- 验证方式：`C:\Users\17723\miniconda3\python.exe -m unittest tests.test_operators_optimization tests.test_operators_utility tests.test_operators_visualization_execution tests.test_storage_factory tests.test_events_local tests.test_inference_tasks tests.test_workflow_execution_service tests.test_websocket_manager tests.test_api_annotations tests.test_api_workflows_direct tests.test_schemas_validation tests.test_models_misc -v` → `Ran 153 tests in 49.860s OK`，全部通过。
- 影响范围：未修改任何源代码；测试覆盖扩展到 12 个新模块，源代码行为契约通过测试得到固化，为后续重构提供回归保障。
- 遗留事项：无；如需进一步提升覆盖，可考虑补充 ProjectAccessService 直接单元测试、AuditService 事务回滚路径测试、生产 PostgreSQL 级联行为集成测试。


### 2026-07-22：生产界面圆润科技视觉改造

- 当前周次：第 9 至第 12 周并行设计支持工作。
- 开发内容：在保留现有路由、认证、数据请求和 Ant Design 组件结构的前提下，升级全局主题、应用侧栏与顶栏为圆润科技控制台风格。
- 问题现象：原界面以直角卡片、橙色高亮和 GitHub 风格深色面板为主，跨页面视觉层级不够统一。
- 解决方法：更新 Ant Design 双主题令牌为电蓝主强调、绿色成功态和中性工业背景；将全局表面、菜单、卡片、按钮、标签、弹窗和空状态统一为 10 至 20px 圆角，并为顶栏引入克制的半透明层次。
- 验证方式：前端 npm run build 通过；npm test -- src/components/AppLayout.test.tsx 3/3 通过；Vite 本地服务的 /login 入口返回 HTTP 200。
- 影响范围：ml-platform/frontend/src/App.tsx、components/AppLayout.tsx 和 styles/global.css；不改动路由、API、认证、状态管理或业务页面数据逻辑。
- 遗留事项：全量视觉验收需要使用已授权真实账号遍历受保护业务页面；当前未在本次任务中改变身份数据或登录状态。


### 2026-07-22：核心页面圆润科技视觉扩展

- 当前周次：第 9 至第 12 周并行设计支持工作。
- 开发内容：继续将圆润科技视觉规范落到登录、注册和数据驾驶舱，并修复非 AppLayout 页面主题变量无法稳定继承的问题。
- 问题现象：入口页保留橙色或紫色渐变及装饰圆形；数据驾驶舱的统计卡、图表和项目标记仍直接使用旧橙紫色；ThemeProvider 未同步根 DOM 主题属性。
- 根因：共享视觉令牌未覆盖硬编码页面样式，主题状态仅存在于 React Context，缺少 CSS 变量所需的根属性。
- 解决方法：以电蓝为主强调、青绿和琥珀为状态色重构入口页和驾驶舱；ThemeProvider 将当前主题同步到 document.documentElement；新增主题同步回归测试。
- 验证方式：npm test 运行 themeContext 和 AppLayout 用例，共 4/4 通过；npm run build 通过；Playwright 分别截取加载完成的登录和注册页面并完成视觉检查。
- 影响范围：全局主题、入口页、数据驾驶舱和 ThemeProvider，不改动认证接口、路由、统计 API、轮询或项目跳转逻辑。
- 遗留事项：受保护业务页面的最终视觉遍历仍需在用户已授权的真实会话下执行。


### 2026-07-22：核心业务页圆润科技视觉扩展（第二批）

- 当前周次：第 9 至第 12 周并行设计支持工作。
- 开发内容：将项目列表、数据管理、模型库和工作流编辑器接入已确认的电蓝圆润工业控制台视觉系统。
- 问题现象：共享主题已升级，但高频业务页仍使用裸表格、直角工作流工具栏以及硬编码白色或灰色画布，导致与登录、驾驶舱和应用壳层的层次不一致。
- 根因：共享 Ant Design token 无法覆盖页面内联表面样式；业务页缺少统一的标题区、表格容器和工作台类名。
- 解决方法：新增页面壳、标题区、表格表面、数据预览表和工作流工作台 CSS 类；将工作流左右面板、浮层和操作区改为主题变量驱动的圆角半透明层级；保留所有路由、接口、表格列、权限、i18n、工作流端口槽位和按钮事件逻辑。
- 验证方式：前端 `npm test -- src/pages/DataManagePage.test.tsx src/pages/WorkspacePage.test.ts src/components/AppLayout.test.tsx` 共 3 个文件、7 项通过；`npm run build` 通过；Playwright 在公开登录页完成桌面及 iPhone 13 截图检查，未出现空白、重叠或横向溢出。
- 影响范围：`ml-platform/frontend/src/styles/global.css`、`pages/ProjectListPage.tsx`、`pages/DataManagePage.tsx`、`pages/ModelLibraryPage.tsx` 和 `pages/WorkspacePage.tsx` 的呈现层，不更改 API、状态、认证或工作流执行行为。
- 预防措施：后续业务页接入共享主题时先增加语义化容器类，再替换内联硬编码颜色；对已有并行逻辑文件只使用精确视觉锚点替换并在构建前复核 diff。
- 遗留事项：受保护业务页的最终人工视觉遍历需要用户已授权的真实会话；本次未读取、写入或伪造浏览器身份数据。

### 2026-07-23：工作流画布与算子圆润科技视觉重构

- 当前周次：第 9 至第 12 周并行设计支持工作。
- 任务状态：工作流视觉实现、聚焦回归和生产构建已完成；受保护工作流路由的真实会话视觉遍历仍待用户授权。
- 开发内容：重构画布网格、缩放控件、缩略图、连线、算子面板、节点外观、参数面板和执行进度浮层，使其接入已确认的电蓝圆润工业控制台视觉系统。
- 问题现象：工作区壳层已经使用圆润科技风格，但算子节点、端口、连线和侧栏仍保留较直角、浅色且层级割裂的旧外观。
- 根因：ReactFlow 节点、边和多个浮层各自使用局部样式，通用主题令牌无法覆盖节点状态、动态端口与画布控件。
- 解决方法：为节点提供分类图标、运行状态、算子 ID 与输入输出信号行；为动态端口保持原有 slot/port ID 和定位逻辑；统一画布、面板、边、缩放控件与进度层的主题变量、圆角、边界和状态色；增加节点视觉 DOM 合同与算子面板折叠默认态回归测试。
- 验证方式：`npm test -- src/components/workspace/CustomNode.test.tsx src/components/workspace/CustomNode.test.ts src/components/workspace/OperatorPanel.test.tsx src/components/workspace/NodeConfigPanel.test.tsx src/pages/WorkspacePage.test.ts` 为 5 个文件、10 项通过；`npm run build` 成功；相关文件 `git diff --check` 成功。构建仅保留既有 ECharts chunk 大小警告。
- 影响范围：`ml-platform/frontend/src/components/workspace/`、`styles/global.css` 和新增工作流组件测试；未改动工作流 API、Zustand 状态模型、端口 ID、连线水合、认证或执行语义。
- 预防措施：视觉改造涉及 ReactFlow 时，动态端口的 ID、handle 位置和边水合必须作为回归契约；共享样式只通过语义类承接，不以视觉替换改写执行逻辑。
- 遗留事项：`NodeConfigPanel.join.test.tsx` 是并行新增且与基线通用多选配置行为不匹配的 Join 键对 UI 测试，本次不扩展功能以使其通过；该需求需单独确认。受保护工作流的真实桌面/移动视觉验收需在用户授权的现有会话中完成。

### 2026-07-23：Bug 清单修复后的前端验收收口

- 任务状态：已完成本轮剩余自动化门禁修复；现有用户未提交修改均保留。
- 问题现象：前端全量测试最初有两项失败：新增测试文件未登记到周次 manifest；Join 配置测试找不到“添加键对”，页面仍以左右两个独立多选框表达键列，无法显式表达左右键配对。
- 根因：前端周次清单是显式维护的静态映射；Join 后端虽然使用 `left_keys/right_keys` 逗号列表，但前端控件没有提供成对编辑模型。
- 解决方法：为 Join 配置增加左右键列成对选择、添加和删除交互，按目标端口从上游运行结果提取左右数据列，并以一次状态更新同步写回 `left_keys/right_keys`；将新增页面、主题、工作流和 Join 测试分别登记到第 1、4、6 周清单。
- 验证方式：聚焦前端 3 个文件、5/5 用例通过；全量 `npm test -- --run` 为 27 个测试文件、64/64 用例通过；`npm run build`（TypeScript 检查和 Vite 生产构建）通过；`git diff --check` 通过。构建仅保留既有 ECharts 大 chunk 警告。
- 影响范围：`ml-platform/frontend/src/components/workspace/NodeConfigPanel.tsx`、`src/weekAcceptance.test.ts` 和前端测试说明；未改变 Join 后端参数协议、工作流端口 ID、连线水合或执行器语义。
- 纠正前条记录：此前记录的 Join 键对测试遗留已在本次实现并通过验证，不再作为未完成项。
- 当前未完成：本地线程调度器无法安全强制终止和 GPU 指标依赖宿主 `nvidia-smi` 的既有限制仍保留；受保护页面真实会话视觉验收仍需授权，不在本次自动化修复范围内。

### 2026-07-23：工作流算子文字与密度微调

- 当前周次：第 9 至第 12 周并行设计支持工作。
- 任务状态：已完成本次节点可读性与密度微调；工作流端口、边水合、执行状态和 API 未改动。
- 开发内容：提高画布算子标题、算子 ID、状态和输入输出信号的字号，并减少节点最小高度、内边距、信号区与错误/进度区的留白。
- 问题现象：前一轮圆润科技视觉重构后，节点标题为 13px，辅助信息和状态为 10px，而 142px 的最小高度和信号区间距使节点在常用缩放级别下显得文字偏小、内部偏松。
- 根因：初版节点设计优先保证状态信息和端口的视觉呼吸感，未将画布算子高频阅读场景的文字密度作为独立约束。
- 解决方法：标题调整为 14px，算子 ID、状态、信号和错误信息调整为 11px；节点最小高度调整为 128px，内边距、标题区图标尺寸和信号/错误/进度间距同步收紧；新增 CSS 密度回归契约，继续覆盖动态端口槽位。
- 验证方式：先新增视觉密度测试并确认旧 CSS 在 `142px` 和旧字号下失败，再更新样式；`npm test -- src/components/workspace/CustomNode.test.tsx src/components/workspace/CustomNode.test.ts src/components/workspace/OperatorPanel.test.tsx src/components/workspace/NodeConfigPanel.test.tsx src/pages/WorkspacePage.test.ts` 为 5 个文件、11 项通过；`npm run build` 成功。
- 影响范围：`ml-platform/frontend/src/styles/global.css` 与 `components/workspace/CustomNode.test.tsx`；不改动 JSX 结构、ReactFlow handle ID/位置、边水合或工作流执行语义。
- 预防措施：工作流节点视觉验收同时检查文字最小可读字号与容器空白比例；修改视觉密度时以 CSS 契约和动态端口测试共同防止将样式调整扩散到连接协议。
- 遗留事项：受保护工作流路由的真实桌面与移动视觉遍历仍需用户授权会话；本次不读取、写入或伪造身份状态。

### 2026-07-23：本地开发代理连接拒绝恢复

- 任务状态：已完成本地前后端开发服务恢复，不涉及业务代码或代理配置变更。
- 问题现象：Vite 对 `/api/dashboard/stats` 和 `/api/projects` 的代理请求连续报 `AggregateError [ECONNREFUSED]`。
- 根因：FastAPI 后端没有稳定监听 `127.0.0.1:8000`，Vite 无法建立代理连接；后续检查还发现前端开发服务器没有监听 `5173`。该错误发生在代理传输层，不是仪表盘或项目接口业务错误。
- 解决方法：在 `ml-platform/backend` 启动 `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`，在 `ml-platform/frontend` 启动 `npm run dev -- --host 127.0.0.1`，保持现有 Vite `/api` 与 `/ws` 代理配置不变。
- 验证方式：后端 `/api/health` 直连返回 `200`；经 `http://localhost:5173/api/health` 代理返回 `200`；`/api/dashboard/stats` 返回 `200`；`/api/projects` 返回预期的 `401 Not authenticated`，证明请求已到达鉴权层而非连接拒绝。
- 预防措施：本地联调前先检查 `127.0.0.1:8000/api/health`，再启动前端；若页面显示代理 `ECONNREFUSED`，先检查端口监听和后端启动日志，不应先修改页面接口代码。
- 遗留事项：无新增功能遗留；后台开发服务依赖当前本机进程，终端或系统重启后需按上述命令重新启动。

### 2026-07-23：Bug 清单四项复核与页面防回归

- 当前周次：第 9 至第 12 周并行设计支持工作。
- 任务状态：已完成清单复核、前端防回归实现和后端删除用户回归验证。
- 问题现象：清单记录自动建模路由空白、模型库缺少注册/部署删除按钮、数据管理删除按钮出界、管理员删除用户触发 `model_library.owner_id` 非空约束。当前基线已包含模型库操作按钮和用户资源转移修复，但 AutoML 缺少运行时异常兜底，数据表操作列在窄屏缺少固定布局约束。
- 根因：懒加载或渲染异常未被页面边界捕获时会让路由只剩空白；操作列使用固定总宽但未锁定右侧列和按钮不换行，窄屏下可视区域不稳定。用户删除问题的根因是删除关联资源时将非空用户外键更新为 `NULL`，现有实现已统一转移到管理员。
- 解决方法：新增可复用 `PageErrorBoundary` 并接入 `/automl`，提供错误提示和重新加载入口；数据管理操作列固定右侧、按钮禁止换行、表格改为 `max-content` 横向滚动；保留模型库已有注册模型/推理部署删除按钮和用户资源转移逻辑。
- 验证方式：先新增边界失败测试并确认模块缺失导致失败，再实现并通过；前端 `npm test -- --run src/components/PageErrorBoundary.test.tsx src/pages/AutoMLPage.test.tsx src/pages/ModelLibraryPage.test.tsx src/pages/DataManagePage.test.tsx` 为 4 个文件、7/7 通过；`npm run build` 通过；后端用户删除转移回归 1/1 通过；真实登录浏览器访问 `/automl` 可见完整页面而非空白。
- 影响范围：`ml-platform/frontend/src/App.tsx`、`src/components/PageErrorBoundary.*`、`src/pages/DataManagePage.tsx`、`src/styles/global.css`；后端 `users.py` 未新增行为变更，仅验证已有修复。
- 预防措施：所有高风险懒加载业务路由需有可恢复错误边界；数据表操作列必须设置稳定宽度、右侧固定和窄屏滚动；管理员删除用户必须覆盖所有非空用户外键的替换策略并保留集成回归。
- 遗留事项：Vite 构建仍报告既有 ECharts 大 chunk 警告；模型库和用户删除清单项已由现有基线实现并通过验证，无新增遗留。

### 2026-07-23：工作流端口与结果交互修复设计

- 当前周次：第 9 至第 12 周并行开发。
- 任务状态：设计已确认，待用户审阅规格后进入实现。
- 范围：端点唯一连接、处理与融合原始数据输出、端点预览、失败详情、评估算子执行、可视化结果独立面板。
- 设计文档：`docs/superpowers/specs/2026-07-23-workflow-port-and-results-design.md`。
- 已确认决策：输入和输出端点均强制单连接；融合算子按输入端口分别输出原始数据；可视化结果使用独立面板；失败状态标签打开错误详情。
- 遗留事项：实现前须完成规格审阅、测试计划和根因复现。
