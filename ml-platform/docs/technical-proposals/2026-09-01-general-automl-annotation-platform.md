# 通用自动建模与数据标注平台技术方案

**日期：** 2026-09-01
**最近修订：** 2026-09-02
**状态：** 需求与关键决策已确认，评审通过（2026-09-02）
**范围：** 通用结构化数据的版本管理、自动建模、手动/自动标注、独立标注员门户、模型资产化与离线导出
**不包含：** 开发排期、任务拆分、代码实现步骤

## 1. 方案目标

平台面向通用结构化表格数据，形成从数据导入、建模、自动标注、人工协作、结果回传、验收、模型注册到离线推理导出的闭环。

本方案固定以下产品目标：

1. 自动建模支持单目标分类、多目标分类、单目标回归和多目标回归。
2. 标注支持多个独立的标签列，每列支持 int、float 或 string，并在任务内冻结 schema。
3. 自动标注支持按簇、按规则、按簇加规则三种互斥策略。
4. 标注员使用独立前端、独立后端、独立账号和独立登录态完成工作。
5. 主平台负责项目权限、任务发布、指派、验收、模型注册与导出；标注员主动回传结果。
6. 模型和任务使用版本化输入输出契约，确保训练、自动标注、回传和导出推理可追溯、可校验、可复现。

## 2. 产品边界与基本原则

### 2.1 数据边界

首期只处理扁平结构化表格数据。JSON/XML 文件先归一化为同一张表，再进入 schema、版本、建模和标注流程：

| 项目 | 约束 |
|---|---|
| 导入格式 | CSV、Excel、Parquet、JSON、XML |
| 支持列类型 | int、float、string |
| Excel | 每次导入选择一个工作表和表头行，读取公式计算结果 |
| CSV | 显示并允许确认编码、分隔符和表头识别结果 |
| Parquet | 只允许扁平标量列；struct、list、map 等嵌套值必须在导入前展开 |
| JSON | 支持顶层对象数组，或由管理员指定的记录数组路径；每条记录必须是对象，字段值必须为标量 |
| XML | 由管理员指定重复记录节点路径；记录节点的属性和直接子节点映射为列，字段值必须为标量 |
| JSON/XML 非标量值 | 首期不自动展开嵌套对象、数组或深层 XML 节点；发现非标量值时返回字段路径并拒绝导入，用户预处理后重试 |
| 不在首期范围 | 图像、音频、视频、PDF、专用文本标注、时间序列专用训练策略 |

### 2.2 设计原则

1. 通用优先：所有业务对象、接口、字段和界面使用通用命名，不依赖固定数据列或业务术语。
2. 版本优先：数据版本、任务快照、标签 schema、规则、聚类工件、模型版本和导出包均不可变。
3. 契约优先：输入、输出、预处理、映射、标签和权限均由显式合同定义，服务端为唯一裁决方。
4. 逻辑快照：任务记录数据版本和固定 sample_id 集合，不为每位标注员复制原始数据。
5. 完整审计：标签、回传、验收、导出、权限变化和受控清理均保留审计链。
6. 失败封闭：输入不合法、契约不兼容、工件不完整或后台执行失败时，不发布部分业务结果。
7. 项目隔离：数据、任务、模型、导出、统计和标注员授权默认严格按项目隔离。

## 3. 总体架构

~~~text
                         主平台用户
                              |
                    主平台 Web 前端
                              |
                       主平台 API 服务
       +----------------------+----------------------+
       |                      |                      |
  数据版本与标注域       AutoML 与模型资产域       项目权限与通知域
       |                      |                      |
       +----------------------+----------------------+
                              |
                    持久化异步任务层
          数据导入 | 预览 | 训练 | 聚类 | 导出 | 回传处理
                              |
       +---------------+------+----------------+
       |               |                       |
  PostgreSQL/SQLite   Redis/任务队列          对象存储

                         标注员
                              |
              独立标注员 Web 前端 :8443
                              |
                    独立标注员 API 服务
                              |
              受认证的内部服务 API 调用
                              |
                       主平台 API 服务
~~~

### 3.1 主平台服务

主平台服务拥有以下职责：

- 项目、项目成员和项目管理员权限。
- 数据导入、数据版本、schema、sample_id 和数据制品管理。
- 手动标注任务、自动标注任务、预览、任务状态、指派请求、回传验收和数据版本生成。
- AutoML 任务、候选模型、模型注册、默认模型、模型生命周期和模型导出。
- 全局算法目录、项目算法启用范围、审计、站内通知和受控数据清理。

### 3.2 独立标注员服务

标注员服务独立部署，默认从 `https://annotator.<平台域名>:8443` 访问。前端地址、API 地址和端口均通过 `ANNOTATOR_PUBLIC_ORIGIN`、`ANNOTATOR_API_ORIGIN` 等环境配置注入，不能写死到客户端代码；生产环境必须使用受信任的 HTTPS 域名或反向代理入口。

标注员服务拥有以下职责：

- 标注员注册、审核后登录、密码重置后的独立会话管理。
- 被指派任务的任务队列、样本分页、标签编辑、自动保存、批量标注、完成确认、批注和主动回传。
- 门户内站内通知和任务状态展示。
- 与主平台通过内部 API 接收任务交付、权限变更和状态变更，并发起回传。

主平台与标注员服务可以共用数据库实例，但必须使用独立逻辑 schema 或表前缀、独立数据库账号和最小权限。两个服务不得跨边界直接读写对方业务表，所有任务交付、指派变更、回传和会话撤销都通过受认证的内部 API 完成。

### 3.3 异步执行与制品存储

以下操作必须使用持久化异步任务：

- 文件导入、schema 推断、数据版本建立。
- AutoML 训练、候选搜索、独立测试评估、模型工件生成。
- 自动标注全量预览、聚类、规则计算和正式执行。
- 任务交付、回传、导出包生成、校验和计算和恢复扫描。

所有异步任务均持久化任务 ID、幂等键、状态、阶段、进度、错误码、脱敏错误详情、尝试次数和审计关联 ID。短暂基础设施错误可重试一次；成功结果只能在完整工件写入且校验完成后原子发布。

## 4. 核心领域模型

### 4.1 数据版本

| 实体 | 核心字段 | 责任 |
|---|---|---|
| dataset_versions | project_id、version、source_artifact_id、content_hash、schema_hash、row_count、status | 不可变数据版本 |
| dataset_schema_columns | dataset_version_id、column_key、display_name、ordinal、data_type、nullable | 冻结列顺序与类型 |
| dataset_samples | dataset_version_id、sample_id、source_row_index、row_locator | 稳定样本身份与行定位 |
| dataset_imports | source_format、parse_options、operator、result、error_summary | 导入过程和审计 |

导入创建数据版本前，系统推断每列的 int、float、string 建议。管理员可确认或修改推断类型。数值列出现无法解析的非空值时，导入必须失败并返回列名和行标识；真正缺失值保留为缺失。数据版本创建后，列类型、顺序和 sample_id 均不可变。

管理员可以选择一个非空且唯一的已有列作为 sample_id。未选择或校验失败时，系统生成不可变 UUID。sample_id 不作为模型输入、标签列或标注员默认可见字段。

### 4.2 标签 schema

| 实体 | 核心字段 | 责任 |
|---|---|---|
| label_schemas | project_id、version、purpose、status | 标签 schema 版本 |
| label_columns | schema_id、column_key、display_name、data_type、ordinal、constraint | 标签列定义 |
| label_value_constraints | label_column_id、min_value、max_value、min_length、max_length、allowed_values、free_text | 可选值范围与枚举约束 |

每个标签列同时具有显示名称和不可变机器标识。机器标识在任务、回传数据、模型输出和导出包中保持稳定。标签列可使用已有数据列；此时必须继承原列类型和初始值，禁止隐式类型转换。

基础校验规则如下：

| 类型 | 合法值 |
|---|---|
| int | 十进制整数，存储范围为有符号 64 位整数；禁止小数、指数形式、溢出和隐式四舍五入 |
| float | `float64` 有限数；拒绝 NaN、`+Infinity`、`-Infinity`、溢出和无法保持有限性的转换 |
| string | UTF-8 文本，去除首尾空白后非空，默认最多 4,096 字节；枚举值按精确字符串匹配 |

标签列默认 `required=true` 且不可为空。任务过程中允许暂时未填，但完成确认和回传前，每个样本的每个标签列必须有合法值。不存在隐式跳过、空值完成或数组型多选值。业务需要未知、不确定或无数据时，必须由管理员配置为该列的合法值。`allowed_values`、`min_value`、`max_value`、字符串长度等约束均由列 schema 冻结；首期不支持自定义正则、层级标签、互斥组、数组标签或隐式类型转换。

### 4.3 标注任务与逻辑快照

| 实体 | 核心字段 | 责任 |
|---|---|---|
| annotation_tasks | project_id、mode、state、source_dataset_version_id、label_schema_id、task_revision | 任务主记录 |
| annotation_task_snapshots | task_id、dataset_version_id、sample_selection、visible_columns、instruction_version | 冻结任务范围 |
| annotation_task_labels | task_id、label_column_id、required、initialization_rule | 任务标签合同 |
| annotation_assignments | task_id、annotator_id、sample_scope、sample_scope_hash、state、due_at、assigned_by | 项目内标注员授权和固定样本范围 |
| annotation_sample_current | task_id、sample_id、final_values、revision_no、last_author | 当前完整标签集合 |
| annotation_revisions | task_id、sample_id、values、provenance、author、base_revision_no、action | 不可变写入历史 |
| annotation_comments | task_id、sample_id 可空、body、status、author、related_revision | 任务级和样本级批注 |
| annotation_confirmations | task_id、task_revision、confirmed_by、confirmed_at | 当前修订的完成确认 |
| annotation_return_batches | task_id、assignment_id、sample_scope_hash、source_revision、result_dataset_version_id、idempotency_key、state、triggered_by | 回传、验收和替代关系 |

任务快照由数据版本 ID、固定 sample_id 清单、可见字段、标签 schema、任务说明和配置版本组成。样本范围可为全量或由管理员配置筛选条件后解析出的固定 sample_id 清单。发布时所有指派范围都解析为固定 sample_id 集合并保存哈希，多个标注员允许拥有重叠范围，标注员共享同一个任务逻辑快照。指派范围只决定可编辑边界，不替代任务完成条件。

任务完成的默认条件是：任务快照中的每个 sample_id 的每个必填标签列都有合法值，且没有待处理的并发冲突、规则冲突或回传替代关系。某个标注员确认只代表其指派范围完成，不得单独把未完成的全局任务标记为完成；重叠指派不要求每位标注员重复提交同一样本。

### 4.4 自动标注策略与来源链

| 实体 | 核心字段 | 责任 |
|---|---|---|
| automatic_annotation_configs | task_id、model_version_id、strategy、output_contract、config_hash | 自动标注主配置 |
| cluster_artifacts | task_id、preprocessor、weight_vector、k_scores、centers、seed | 聚类工件 |
| cluster_label_mappings | task_id、cluster_id、label_values、is_fallback | 按簇标签 |
| rule_sets | task_id、version、rules、fallback_values | 按规则标签 |
| annotation_value_provenance | revision_id、label_column_key、model_value、strategy_value、final_value、source | 每列来源链 |

每个样本、每个标签列必须保留：

1. 初始模型输出。
2. 簇或规则策略输出。
3. 人工最终值。
4. 最后修改人、修订号、修改时间和来源说明。

人工编辑只更新最终值，不覆盖模型和策略来源。回传数据只包含最终标签，不包含内部来源链、簇编号、规则命中或模型中间输出。

### 4.5 AutoML、模型版本与导出

| 实体 | 核心字段 | 责任 |
|---|---|---|
| automl_tasks | project_id、task_type、target_columns、input_contract、search_config、status | AutoML 主任务 |
| automl_candidates | task_id、algorithm_version、metrics、params、runtime、state | 候选训练结果 |
| registered_models | project_id、model_name、model_version、source_candidate_id、state | 手动注册模型 |
| model_contracts | model_version_id、input_contract、output_contract、preprocessing、mappings | 预测合同 |
| model_exports | model_version_id、annotation_task_revision 可空、artifact_id、manifest_hash、state | 独立导出记录 |

模型注册由用户手动选择完整成功的候选触发。worker 只负责训练、保存候选工件和报告，不创建或启用模型库记录；任何自动创建模型库条目的实现都违反本方案。每次注册形成不可变模型版本，保存数据版本、训练配置、候选算法版本、参数、指标、预处理、映射表、输入输出契约、特征重要性和模型工件校验和。

## 5. 数据导入、版本与回传

### 5.1 数据导入流程

1. 管理员提交文件和解析选项；表格文件配置编码、分隔符、表头或工作表，JSON 配置记录数组路径，XML 配置重复记录节点路径。
2. 系统按格式解析文件，并将 JSON/XML 记录归一化为扁平表格；解析选项、记录路径和字段映射写入解析合同。
3. 系统推断列类型，管理员确认类型、`sample_id` 和数据版本元数据。
4. 系统校验数据行、唯一 `sample_id`、列名唯一性、列类型、非标量值和内容哈希；任一校验失败则整批拒绝，不产生可用的部分版本。
5. 异步任务同时保留原始文件制品和归一化表格制品，并写入 schema、解析合同、`sample_id` 索引和版本记录。
6. 创建成功后，数据版本可用于任务预览、AutoML 或已授权的数据管理操作；后续流程只依赖归一化表格和不可变解析合同。

#### 5.1.1 JSON/XML 解析合同

- JSON 记录路径使用受控字段路径，不执行任意代码或表达式；路径解析后必须得到对象数组，空数组允许导入但需产生明确的空数据提示。
- XML 记录路径使用受控元素路径；每个记录节点的属性和直接子节点生成稳定列名，重复列名或同一列出现不兼容标量类型时拒绝导入。
- JSON/XML 的编码、记录路径、列名映射、空值处理、类型推断结果和解析器版本都写入数据版本的 `parse_contract`，并参与版本内容校验。
- 原始文件制品不可变保存，归一化表格作为后续任务的唯一输入；重新解析必须创建新的数据版本，不能覆盖历史版本。
- 解析错误返回格式、字段/节点路径、行或记录标识、错误类别和脱敏值摘要，不能把部分解析结果标记为成功。
- 解析器必须禁用 XML DTD、外部实体、外部 schema、网络访问和文件系统实体解析；JSON/XML 路径只允许受控字段/元素路径，不能执行表达式、查询或脚本。
- 导入请求必须执行大小、解压后大小、记录数、列数、嵌套深度、单字段长度和总处理时间限制；默认上限为 1 GB 原文件、4 GB 解压后内容、100 万条记录、200 列、32 层深度和 64 KB 单字段，部署可下调但不能取消。
- JSON 重复键、XML 重复列名、非法编码、实体扩展、压缩炸弹和解析超时均拒绝导入；上传文件按实际内容识别格式，不信任扩展名或客户端 MIME。
- 必需列不存在与列存在但值为空必须区分：缺少列返回 `INPUT_REQUIRED_COLUMN_MISSING` 并拒绝整批；已存在列的空值按该列冻结的 `missing_policy` 处理并记录计数，禁止把缺列当作可填充缺失值。

### 5.2 回传流程

1. 标注员对当前任务修订完成确认后，主动发起回传。
2. 标注员服务使用幂等内部 API 调用主平台。
3. 主平台重新读取源数据版本，按 sample_id 对齐最终标签。
4. 同机器标识且类型一致的标签列覆盖到新版本；新标签列追加到新版本。
5. 生成只含原始数据列和最终标签列的新数据版本，状态为待验收。
6. 项目管理员在回传结果列表预览、批注、对比差异并决定验收或退回。

回传结果通过验收后才能作为新任务或 AutoML 的输入。验收不改变历史数据版本，也不改变已经训练、注册或导出的模型血缘。

回传按指派范围产生独立批次，批次携带 `assignment_id`、范围哈希、提交时的 `task_revision` 和幂等键。主平台以 sample_id 对齐并在事务中串行验收：

- 同一批次重复请求返回原批次，不生成重复数据版本；不同标注员同时回传时，先成功提交的批次保留，基于过期任务修订的批次返回冲突并要求刷新后重新回传。
- 验收不做隐式的逐列拼接、自动多数投票或静默覆盖。重叠样本必须以当前样本完整标签集合为准，管理员退回后由标注员显式编辑生成新修订再提交。
- 接受部分范围的回传不会把全局任务标记为完成；只有所有样本必填标签完整且所有待处理冲突清空后，任务才可进入待回传/已完成路径。

## 6. 手动标注方案

### 6.1 任务创建

管理员创建手动任务时配置：

- 项目、数据版本和固定样本范围。
- 任务名称、Markdown 说明、完成标准和列级填写指引。
- 标签 schema、可见字段、截止时间和任务状态。
- 项目内已授权标注员的多选指派。

可见字段只允许来自源数据原始列。sample_id、内部处理字段、模型中间结果和未授权列默认不展示。

### 6.2 标注员编辑

标注员门户支持：

- 被指派任务列表、搜索、筛选、排序和分页。
- 按授权字段、标签完成状态、本人最近修改时间和批注状态筛选。
- 列类型和约束匹配的标签控件。
- 一行或多行的批量赋值；默认不覆盖已有合法标签，覆盖需要显式确认。
- 修改后自动保存，并展示保存中、已保存和保存失败状态。
- 网络失败时保留未提交内容并允许重试。
- 仅能读取和写入自己被指派的固定 sample_id 范围；范围之外的样本即使知道 sample_id 也必须返回未授权。

每次服务端提交都包含该样本完整标签集合、当前 `revision_no` 和幂等键。服务端执行乐观并发检查：

1. 修订未过期时，原子写入完整集合并生成修订。
2. 修订过期时，停止自动保存并返回当前值、当前修订和差异摘要。
3. 标注员必须显式确认以自己的完整标签集合覆盖最新版本后，才可成为最后成功写入者。

这保留最后成功写入语义，同时避免自动保存无感覆盖其他标注员工作。系统不使用持有式样本锁；多个标注员可以同时编辑同一样本，但过期修订必须先解决冲突，不能静默覆盖。

### 6.3 完成确认与状态

完成确认分为两层：标注员确认自己的指派范围，项目管理员确认任务整体。标注员确认只记录其范围、任务修订和时间；系统只有在任务快照全部样本的必填标签完整、无未解决冲突且不存在待处理回传替代时，才把任务推进到 `awaiting_return`。任一有效指派标注员不能跳过未完成样本单独完成全局任务。

任意最终标签修改会撤销全部旧确认，并将任务恢复为进行中。批注变化不影响完成确认或回传锁。

## 7. 自动标注方案

### 7.1 公共流程

自动标注采用以下固定流程：

1. 选择数据版本和已启用注册模型。
2. 选择是否启用聚类。
3. 若启用聚类，对全部符合条件的样本生成最终簇分配；K 的轮廓系数评估按 7.1 的精确/近似规则执行。
4. 在按簇、按规则、簇加规则三种策略中选择一种。
5. 配置多列标签、规则、簇映射和全部兜底值。
6. 生成全量预览并冻结预览版本。
7. 明确确认执行，形成自动标签任务。
8. 在任务列表或预览页完成多选指派，不自动跳转标注详情页。

自动任务的最终预测、簇分配、规则命中和标签覆盖必须针对全量样本计算。界面显示全量统计和分页样本；只有 K 选择的 Silhouette Score 允许在大数据上使用确定性近似评估：样本数不超过 100,000 时使用全量评分，超过时按 `hash(sample_id, task_revision, seed)` 稳定抽取最多 50,000 条评估样本，并记录 `evaluation_mode`、`evaluation_sample_count`、总体样本数和样本哈希。抽样只用于比较 K，不用于替代最终全量聚类或标签生成。模型、聚类、规则、标签或数据范围任一变化都会使预览失效并要求重新计算。

### 7.2 不启用聚类

不启用聚类时，最终标签严格使用模型 output_contract 的标签列、机器标识、显示名称和类型。管理员不能改写 schema。模型输出作为初始最终标签，标注员可合法修改并完成确认。

### 7.3 启用聚类

启用聚类时，模型输出作为内部来源保留，自动策略生成最终标签。标注员门户只显示最终可编辑标签，不显示簇编号、特征权重、规则命中和模型内部输出。

聚类仅在满足以下条件时执行：

- 当前任务范围至少有 3 条可完成训练期预处理的样本。
- 加权特征空间至少存在 2 个不同向量。
- 能获得有限且总和大于零的原始输入特征权重。

任一条件不满足时，聚类预览失败并返回明确原因，不降级为单簇、随机簇或等权聚类。

### 7.4 特征重要性加权 KMeans

1. 按目标列获取所选模型的重要性，来源优先级为模型原生 `feature_importances_`、线性模型 `coef_` 的绝对值、置换重要性、经批准的 SHAP 重要性；每个目标列只选一种来源并记录方法、版本和随机种子。
2. 将编码后特征索引映射回原始输入列：同一原始字符串列的 one-hot 维度按绝对重要性求和，数值列保持一维，无法映射的交互维度必须单独记录并阻断聚类。
3. 对每个目标列的重要性取非负有限值并做 L1 归一化，多目标任务按目标列等权平均得到总权重，同时保留逐目标向量；若所有来源均不可用、含 NaN/Infinity 或总和为零，返回 `FEATURE_IMPORTANCE_UNAVAILABLE`，不得静默退化为等权聚类。
4. 对聚合后的权重再次归一化：`weights = importances / sum(importances)`。
5. 在训练期标准化和编码后的空间计算：`X_weighted = X_standardized × sqrt(weights)`；标准化器和映射表只能使用训练数据拟合。
6. 搜索 `K = 2..min(8, n_eligible_samples - 1)`，以 Silhouette Score 选择最优 K；大数据评估样本规则见 7.1。
7. 分数并列时选择较小 K；K 不满足 `2 <= K < n_eligible_samples` 时不执行。
8. 保存编码映射、标准化器、逐目标/聚合权重、重要性来源、所有 K 分数、评估样本哈希、随机种子、最终中心和预览 hash。

重试、回看、回传关联导出包和 annotate 命令只能使用已保存工件进行 predict，不得重新拟合或重新搜索 K。管理员需要重新聚类时必须创建新任务版本。

### 7.5 三种自动策略

#### 按簇

- 管理员可选择一个或多个簇。
- 每个选择簇必须为全部标签列填写合法值。
- 系统始终存在不可删除的“其他”兜底簇；管理员可以修改其显示名称和各列值，但不能删除或留空。
- 未选择的簇、已选择但未配置映射的簇全部进入“其他”；“其他”必须为全部标签列填写合法值后才能预览或执行。

#### 按规则

- 规则只使用原始数据列值，不使用模型编码或聚类内部特征。
- 规则支持可视化条件、AND/OR 分组、数值/字符串比较、空值判断和优先级。
- 不支持正则、SQL、Python 或自定义脚本。
- 优先级数值越小越高；不同优先级同时命中时使用最高优先级。
- 同一最高优先级有多条规则命中且对同一标签列给出不同值时进入 `needs_review`，不能任意选择；不同标签列可以分别取各自命中的值。
- 规则可只写入部分标签列；未写入的列继续按该列的兜底值处理。规则侧始终存在不可删除的“其他规则”，每个标签列必须填写合法兜底值，未命中规则时使用该值。

#### 簇加规则

簇加规则按“先聚类筛选、再规则覆盖”的顺序执行：管理员选择的目标簇先决定样本是否进入规则范围，规则可进一步配置簇过滤；未选择的簇直接使用“其他”兜底，选定簇按簇映射取值。对同一标签列的优先级固定为“命中规则 > 已配置簇值 > 其他兜底”，规则未命中时回退到簇值，簇无映射时回退到“其他”。规则冲突、簇映射冲突或兜底缺失均进入 `needs_review`，不能静默合并。簇侧和规则侧如需同时保留信息，必须定义为不同机器标识的独立标签列，不能用同一列隐式覆盖。

### 7.6 自动标注失败

模型推理、聚类、规则解析、标签校验、工件读取或输出契约校验任一失败时，预览或执行整体失败，不产生可使用的部分标签。规则同优先级冲突、簇映射冲突和兜底缺失进入 `needs_review`，不能被标记为成功。错误结果保留错误摘要、受影响样本数和可定位样本标识，管理员可以在不改配置的情况下重试；重试必须复用相同输入版本和配置 hash，改变配置必须创建新任务修订。

## 8. 标注员门户、指派和回传

### 8.1 账号与认证

标注员使用独立账号表、独立认证服务和独立浏览器会话：

- 用户名和密码必填，密码至少 8 位。
- 邮箱可选；未验证邮箱的账号只能由管理员重置密码。
- 注册后状态为待审核，审核通过后才能被项目授权和接收任务。
- 管理员停用账号、审核拒绝或重置密码后，标注员全部会话立即失效。
- 主平台 Cookie、账号和标注员门户 Cookie、账号、令牌互不共享。

标注员账号使用不可变 `annotator_subject_id`。主平台保存该 subject 与 `platform_principal_id` 的受控映射（没有主平台账号时创建影子主体），项目成员关系和任务指派引用 subject ID，不引用可变用户名；所有映射、授权和撤销都写入审计。门户请求不得从客户端接受 `project_id`、`annotator_id` 或任意 assignment 范围作为可信权限依据。

门户会话使用独立的短期、轮换 token 和会话版本号；浏览器 Cookie 仅使用 `Secure`、`HttpOnly`、受控 `SameSite` 属性。账号停用、密码重置、解除项目授权和服务间撤销都会递增会话版本并使现有会话立即失效。标注员服务调用主平台时使用服务身份 JWT 或 mTLS，校验 issuer、audience、过期时间、nonce、最小 scope 和项目范围，不能复用浏览器会话。

### 8.2 项目授权与任务指派

系统管理员负责标注员账号审核、启停和重置密码。项目管理员负责将已审核标注员授权到项目，并将任务多选指派给已授权标注员；指派请求同时携带固定 sample_id 集合或可审计的筛选条件，发布后筛选条件不得再次解释。

同一标注员可以分别加入多个项目，但门户只显示其被指派任务。新增指派后，标注员看到任务当前最新完整标签、当前说明、截止时间和授权字段；不展示其他标注员的完整修订历史。

管理员移除标注员、暂停任务、取消任务或停用账号后，门户的下一次请求必须立即拒绝保存和回传。已成功提交的修订保留，未保存的本地修改不得写入。

### 8.3 回传锁与重新编辑

回传成功后，相关指派范围进入待验收并默认只读，回传按钮锁定。标注员需要显式点击编辑并成功提交至少一个新修订，才会解除回传锁、创建新的活动修订并允许继续修改。新的回传替代此前同一范围的未验收回传；同一时刻只有最新未被替代的回传可待验收。

回传通过验收后，标注员任务保持只读。项目管理员需填写原因并重新打开任务，才会创建新的任务修订供标注员修改。旧已验收版本始终不可变。

### 8.4 批注与通知

批注支持任务级和样本级。项目管理员和当前有效指派标注员可以查看和回复；项目管理员可以标记已解决或发起退回修改。批注保留作者、时间、关联修订和处理状态，但不写入回传数据、不参与训练且不影响确认和回传锁。

通知仅使用站内通知，触发场景包括：

- 注册审核、项目授权、任务指派和指派变更。
- 截止前提醒、逾期提醒、暂停、恢复、取消和重新打开。
- 批注回复、退回修改、回传成功/失败和验收结果。
- 后台任务完成、失败和需处理状态。

## 9. 回传验收与任务状态机

### 9.1 任务状态

| 状态 | 含义 | 可进入状态 |
|---|---|---|
| draft | 草稿，可修改配置 | previewing、cancelled |
| previewing | 正在生成预览工件 | draft、preview_ready、failed、needs_review |
| preview_ready | 预览有效，配置已冻结，可发布或执行 | executing、awaiting_annotation、paused、cancelled |
| executing | 自动标注正在推理、聚类、规则计算或写入结果 | awaiting_annotation、failed、needs_review、paused、cancelled |
| awaiting_annotation | 任务已发布，等待指派范围内标注或继续编辑 | in_progress、awaiting_return、paused、cancelled |
| in_progress | 存在活动指派，允许标注和保存 | awaiting_return、paused、cancelled |
| awaiting_return | 全部样本必填标签完整且已确认，可发起回传 | returned_pending_acceptance、in_progress |
| returned_pending_acceptance | 已回传，等待验收，默认只读 | in_progress、accepted |
| accepted | 回传版本已验收，任务只读 | completed、archived |
| completed | 任务已完成并形成可用数据版本 | archived、in_progress |
| paused | 暂停写入与回传，保留恢复目标状态 | preview_ready、awaiting_annotation、in_progress、cancelled |
| cancelled | 终止，不可编辑或回传 | archived |
| archived | 可逆归档，只读 | preview_ready、completed |
| failed | 自动流程失败，可查看错误并重试 | draft、previewing、executing、cancelled |
| needs_review | 规则/簇冲突或高风险配置待管理员处理，禁止执行和回传 | draft、previewing、cancelled |

手动与自动任务在主平台任务列表中统一管理。创建、自动执行成功和保存配置后均保持在任务列表或预览上下文，不自动进入详情页。

状态守卫必须由服务端统一执行，前端按钮隐藏不能替代权限和状态校验：

| 操作 | 允许状态和前置条件 |
|---|---|
| 创建/编辑草稿 | `draft`、`failed`、`needs_review`；配置变更递增 `task_revision` 并使旧预览失效 |
| 生成预览 | `draft`、`failed`；同一配置 hash 的重复请求幂等返回原预览 |
| 发布手动任务 | `preview_ready`；转为 `awaiting_annotation` |
| 执行自动任务 | `preview_ready`；转为 `executing`，成功后转为 `awaiting_annotation` |
| 指派/变更指派 | `preview_ready`、`awaiting_annotation`、`in_progress`；不得越过项目和样本范围授权 |
| 保存标签/批量标签 | `awaiting_annotation`、`in_progress`，且指派有效、回传未锁定、revision 未过期 |
| 完成确认 | `awaiting_annotation`、`in_progress`；仅在本次确认范围完整时成功，全局状态由系统计算 |
| 发起回传 | `awaiting_return`；必须携带幂等键和当前任务修订 |
| 显式编辑回传 | `returned_pending_acceptance`；必须生成新修订后才能再次回传 |
| 验收/退回 | `returned_pending_acceptance`；验收先转 `accepted`，数据版本和审计落库后自动转 `completed`，退回转 `in_progress` |
| 重新打开 | `completed`；项目管理员填写原因并创建新任务修订 |
| 暂停/取消 | 仅允许未完成终态；取消后不得恢复写入 |

### 9.2 验收状态

回传批次采用 `pending`、`superseded`、`accepted`、`returned_for_changes`、`archived` 状态。只有 `accepted` 回传版本可作为训练或新任务输入。管理员验收、退回和归档均保留审计；同一任务和样本范围的验收按任务修订串行，过期批次不能覆盖较新批次。

### 9.3 差异和质量检查

回传前强制检查：

- 所有样本、所有标签列的完整性、类型和列级约束。
- 标签 schema 与源数据版本的冲突。
- 自动策略的簇映射、规则配置和全部兜底值。
- 输出行数、sample_id 集合和最终标签列。

系统还提供不阻断的风险提示：

- 标签分布、空值和异常值数量。
- 自动策略覆盖率、其他簇和其他规则命中率。
- 人工修改样本数和前后分布差异。

数据管理回传结果列表按 sample_id 比较源版本与回传版本，展示新增/覆盖标签列、变更样本数和逐样本前后值。

## 10. AutoML 方案

### 10.1 任务合同

AutoML 使用 `task_type` 与有序 `target_columns` 表达任务。下列四个值是持久化和接口的规范枚举；产品文案中的“多标签分类”统一指 `multioutput_classification`，不表示数组或集合型标签：

| task_type | target_columns | 说明 |
|---|---|---|
| classification | 恰好 1 列 | 单目标、单值分类；每个样本只能有一个类别 |
| multioutput_classification | 至少 2 列 | 多标签/多输出分类；每列是独立的单值分类目标，多个列不压缩为数组或 multi-hot |
| regression | 恰好 1 列 | 单目标回归；目标值为数值 |
| multioutput_regression | 至少 2 列 | 多输出回归；每列是独立的数值目标 |

历史或外部请求中的 `multilabel_classification`、`multiregression` 只能作为兼容别名读取，并在写入任务前归一化为 `multioutput_classification`、`multioutput_regression`；数据库、任务快照、模型合同和导出 manifest 不保存别名。分类目标可使用 int、float、string；回归目标只允许 int、float。目标列必须在数据版本中存在，且目标值为空、NaN、Infinity、溢出或不符合类型时拒绝启动，不得用输入特征缺失策略代填目标。

管理员显式选择输入特征，默认勾选全部非目标列。输入列名、顺序、类型、缺失策略、编码映射、标准化方式和预处理版本冻结到 input_contract。

### 10.2 训练前校验与预处理

| 内容 | 行为 |
|---|---|
| 必需目标列不存在 | 返回 `TARGET_COLUMN_MISSING`，拒绝启动 |
| 目标列存在但值为空/非法 | 返回带列名和 sample_id 的 `TARGET_VALUE_INVALID`，拒绝启动，不静默删行或插值 |
| 必需输入特征列不存在 | 返回 `INPUT_REQUIRED_COLUMN_MISSING`，拒绝启动；不能把缺列当作可填充缺失值 |
| 输入特征列存在但值为空 | 按训练期冻结的中位数、众数或未知类别策略处理，并记录缺失计数；若该列策略为 `error` 则拒绝 |
| 字符串输入特征 | 使用系统生成、可预览、训练后冻结的映射表和独热编码 |
| 字符串分类目标 | 使用冻结映射表，推理时还原原始值和类型 |
| 回归目标异常值 | 默认只提示风险；管理员可显式启用截断策略 |
| 回归预测超出训练范围 | 不截断、不拒绝，返回有限 float 并附风险标记 |

训练前需要提示目标缺失、类别过少、类别失衡、常量特征、高缺失特征、高基数字符串特征、重复样本和可能泄漏目标的字段。不能可靠训练的问题必须阻断；其余风险必须由管理员确认。所有输入列的 `required`、`nullable`、缺失策略、允许范围和类型均写入 `input_contract`，训练、自动标注和导出推理复用同一合同 hash。

### 10.3 交叉验证与独立测试

- 管理员可选 2 至 5 折，默认 5 折；不可用折数不展示，不静默降级。
- 单目标分类采用分层；多输出分类采用多标签迭代分层。若目标组合无法形成所选折数，界面只展示可用折数并要求用户重新选择，不静默降级为普通 KFold。
- 单目标和多输出回归采用随机打乱 KFold；随机种子必须冻结并写入任务快照。
- 预处理只能在训练折拟合，再应用到验证折。
- 可选独立测试集必须来自同项目、完整 schema、目标完整且 sample_id 无重叠的数据版本。
- 独立测试集不参与候选排序或超参数搜索，只在用户选择注册候选后评估最终重训模型。
- 独立测试没有全局硬阈值；若表现异常或与交叉验证差异明显，用户必须明确确认才可注册。

### 10.4 算法、搜索与资源

- 系统管理员维护全局算法注册表，算法、依赖和参数空间均版本化不可变。
- 项目管理员控制项目启用范围；创建任务时默认勾选全部兼容且已启用算法。
- 多输出训练按每个目标列独立构建兼容模型或使用明确声明支持多输出的包装器，保留逐目标模型、指标、预测输出和重要性；算法不支持当前 task_type 时从候选列表中剔除并说明原因。
- 支持网格、随机、贝叶斯、进化、多保真五种搜索；默认贝叶斯。
- 搜索强度为轻度 10 次、中 30 次、高 80 次、ultra 200 次；耐心值分别为 3、6、10、20，默认中。
- 时间预算为快速 30 分钟、标准 60 分钟、扩展 120 分钟、长时 240 分钟，默认标准。
- 单个 AutoML 任务最多并行 2 个候选算法；候选失败不阻断其他候选；短暂基础设施失败可重试一次。
- 用户可停止任务；已完整完成的候选保留且可注册；继续搜索必须新建任务。
- 分类类别权重由用户决定，默认启用；不自动做过采样、欠采样或合成样本。

### 10.5 指标、排行和报告

分类候选按照以下严格字典序排序：

1. 平均 AUC，越大越好。
2. 平均 Macro-F1，越大越好。
3. 平均 Accuracy，越大越好。
4. 候选实际训练、交叉验证和搜索总运行时间，越小越好。

多输出分类对每个目标列独立计算指标后等权平均。AUC 对二分类直接计算，对多分类使用 One-vs-Rest Macro AUC。优先使用 `predict_proba`，其次使用 `decision_function`；无法为任一目标列产生有效连续得分时标记 AUC 不可用，排在 AUC 完整可用候选之后。多标签 UI 不允许把不同目标列的类别拼成一个集合后再计算单一指标。

回归候选按照平均 R²、平均 RMSE、平均 MAE、运行时间排序，其中 R² 越大越好，其余越小越好。

候选如存在任一目标列指标无法计算、训练折失败或输出契约不完整，不能进入可注册排行榜。平台不设统一分数阈值，但注册时必须展示并确认逐目标风险。

分类报告按目标列展示类别分布、混淆矩阵、Precision、Recall、Macro-F1、Accuracy、AUC 和支持样本数。回归报告按目标列展示 R²、MAE、RMSE、真实值与预测值对比、残差分布和训练目标历史范围。

所有候选展示全局特征重要性。重要性来源、one-hot 还原、零值处理和多目标聚合规则与 7.4 一致：每个目标列先在后变换空间取非负有限值并 L1 归一化，再按目标列等权平均；同时展示逐目标向量、聚合向量、来源方法、映射表版本和是否存在不可用维度。重要性全部不可用时只能标记为不可用于聚类，不得虚构等权结果。

## 11. 模型库、状态与导出

### 11.1 模型状态

| 状态 | 允许操作 |
|---|---|
| pending_review | 查看、审核 |
| enabled | 自动标注、设为默认、导出 |
| disabled | 查看、审计；禁止新任务和导出 |
| revoked | 查看、审计；禁止新任务和导出 |
| archived | 只读查看和审计 |

项目管理员显式指定默认模型。默认模型必须与目标输入输出契约兼容。默认模型失效后默认项清空并通知管理员，系统不得自动选择最新版本或排行榜第一名。

### 11.2 导出包

每次导出固定到一个模型版本，可选关联一个自动标注任务修订。导出生成独立 ZIP，核心内容至少包含：

~~~text
model-export.zip
  model/
  preprocessing/
  mappings/
  contracts/input_contract.json
  contracts/output_contract.json
  runtime/inference.py
  runtime/cli.py
  runtime/requirements.lock
  runtime/README-runtime.md
  security/sbom.spdx.json
  security/manifest.sig
  manifest.json
  checksums.json
  README.md
~~~

用户可选择同时生成 `runtime/Dockerfile`。仅当导出请求关联了自动标注任务修订时，导出包还必须包含该修订冻结的 `annotation/strategy.json`、`annotation/cluster_method.json`、`annotation/cluster_artifacts.json`、`annotation/cluster_label_mappings.json` 和 `annotation/rules.json`；未关联任务修订时，不生成 annotation 目录。策略文件必须包含同列优先级、兜底值、规则版本、簇选择和配置 hash，不能只导出不可复现的文字描述。

`manifest.json` 至少记录：包格式版本、模型/候选/数据版本 ID、规范 `task_type`、输入输出合同 hash、预处理和算法库版本、Python/运行时版本、CPU/操作系统兼容性、模型/交叉验证/聚类随机种子、确定性开关、线程配置、所有制品 SHA-256、关联自动标注任务修订、策略和规则 hash、生成时间及导出工具版本。`checksums.json` 覆盖包内全部文件；`security/sbom.spdx.json` 记录直接和传递依赖，`security/manifest.sig` 对 manifest 与 checksums 签名（签名不可用时导出失败），公钥指纹通过受控配置分发。

导出包不包含真实数据、样本、标签、批注、账号信息、密钥或长期访问凭据。

### 11.3 predict 与 annotate

导出包始终提供 `predict`；关联自动标注任务修订时，额外提供 `annotate`：

- predict：只执行模型推理。
- annotate：在模型推理基础上，应用关联任务修订的聚类、簇标签、规则和来源信息。

命令支持 CSV、Excel、Parquet、JSON、XML 输入，以及 CSV、Parquet、JSON 输出；JSON/XML 只有在输入携带与训练一致的 `parse_contract` 时才允许，记录路径或字段映射不一致即拒绝。输入允许存在额外非特征列，但必需特征列、顺序语义、类型、缺失策略、枚举和数值范围必须与训练时的 `input_contract` hash 一致。缺少必需列、列类型不符、目标/特征值非法、预处理失败、sample_id 异常或输出契约不合法时，整批拒绝业务输出，并生成 `validation-report.json`；不得返回部分成功结果。

`validation-report.json` 至少包含错误类别、字段、行标识、期望类型、实际值摘要、合同 hash、解析器版本和可重试建议，不得包含完整原始值、密码或令牌。输出必须校验行数、sample_id 顺序/唯一性、列数、列类型、枚举约束和有限浮点值；校验失败时删除临时输出并以非零退出码结束。离线 `predict` 只输出模型结果，关联任务修订的 `annotate` 还输出最终标签、来源列和策略版本，但不暴露内部账号或权限信息。

## 12. 接口边界

### 12.0 通用接口合同

- 所有写接口要求 `Authorization`、`X-Request-ID` 和 `Idempotency-Key`；长任务返回 HTTP 202 与 `operation_id`，重复幂等键返回同一操作及最终结果。
- 所有列表、样本、预览、差异和批注查询使用游标分页：`cursor`、`limit`（默认 50，最大 200）和稳定排序键；禁止用不稳定的 offset 作为并发回传依据。
- 所有修改接口携带 `task_revision` 或 `If-Match`；过期时返回 HTTP 409 `REVISION_CONFLICT`，响应包含当前 revision、服务端完整标签集合、差异摘要和重新读取地址，客户端必须显式确认后才能覆盖。
- 错误统一返回 `{request_id, code, message, details}`；`details` 只包含字段、行/样本标识、期望类型、实际值摘要和可重试性，不返回完整原始记录或敏感凭据。
- 服务端从路径和会话解析项目、主体和 assignment，忽略客户端自报的项目归属；每个接口都执行项目范围、状态守卫和审计记录。

### 12.1 主平台公开 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/dataset-imports | 创建导入任务 |
| POST | /api/dataset-imports/{id}/confirm-schema | 确认 schema 和 sample_id |
| GET | /api/dataset-versions/{id} | 获取数据版本与合同 |
| POST | /api/annotation-tasks | 创建手动或自动任务草稿 |
| POST | /api/annotation-tasks/{id}/preview | 按配置 hash 创建预览操作，返回 `preview_id/operation_id` |
| GET | /api/annotation-tasks/{id}/previews/{preview_id} | 查询预览状态、全量统计和分页样本 |
| POST | /api/annotation-tasks/{id}/publish | 发布手动任务，转为 `awaiting_annotation` |
| POST | /api/annotation-tasks/{id}/execute | 执行自动标注，必须引用有效 `preview_id` |
| GET | /api/annotation-tasks/{id}/assignments | 分页查询指派和固定样本范围 |
| POST | /api/annotation-tasks/{id}/assignments | 多选指派，支持样本范围和截止时间 |
| PATCH | /api/annotation-tasks/{id}/assignments/{assignment_id} | 暂停、恢复或撤销指派 |
| POST | /api/annotation-tasks/{id}/pause | 暂停任务 |
| POST | /api/annotation-tasks/{id}/reopen | 重新打开已验收任务 |
| GET | /api/annotation-return-batches | 回传结果列表 |
| GET | /api/annotation-return-batches/{id} | 回传批次状态、范围和版本信息 |
| GET | /api/annotation-return-batches/{id}/diff | 分页查询源版本与回传版本差异 |
| POST | /api/annotation-return-batches/{id}/accept | 验收回传数据版本 |
| POST | /api/annotation-return-batches/{id}/return | 退回修改 |
| POST | /api/automl-tasks | 创建 AutoML 任务 |
| POST | /api/automl-tasks/{id}/register | 手动注册候选模型 |
| POST | /api/model-versions/{id}/exports | 创建模型导出任务 |
| GET | /api/model-exports/{id} | 查询导出状态、manifest hash 和错误 |
| GET | /api/model-exports/{id}/download | 下载已签名且校验通过的导出包 |

### 12.2 标注员门户公开 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /portal/auth/register | 注册标注员账号 |
| POST | /portal/auth/login | 标注员登录 |
| POST | /portal/auth/logout | 撤销当前门户会话 |
| GET | /portal/tasks | 获取本人被指派任务 |
| GET | /portal/tasks/{id} | 获取任务、指派范围和当前 revision |
| GET | /portal/tasks/{id}/samples | 按游标分页读取授权样本 |
| PUT | /portal/tasks/{id}/samples/{sample_id}/labels | 原子提交完整标签集合 |
| POST | /portal/tasks/{id}/bulk-labels | 批量写入标签 |
| POST | /portal/tasks/{id}/confirm | 确认当前任务修订 |
| POST | /portal/tasks/{id}/edit-for-return | 显式解除回传只读锁 |
| POST | /portal/tasks/{id}/return | 主动发起回传 |
| POST | /portal/comments | 创建任务级或样本级批注 |
| GET | /portal/comments | 分页读取本人可见批注 |

### 12.3 服务间内部 API

内部接口必须使用服务身份认证、最小作用域、项目范围校验、幂等键和审计关联 ID。主要用途包括：

- 标注员账号审核、启停、密码重置。
- 项目授权和任务交付。
- 指派名单、截止时间、任务状态和批注同步。
- 标注员主动回传、回传状态更新和验收结果通知。
- 模型导出状态、签名元数据和一次性下载授权。

内部 API 不能被浏览器直接调用，也不能通过跨服务数据库读写替代。

### 12.4 核心请求与响应字段

| 操作 | 请求必填字段 | 成功响应/异步结果 |
|---|---|---|
| 创建任务草稿 | `dataset_version_id`、`mode`、`label_schema_id`、`sample_scope`、`task_revision=0` | `201 {task_id,state=draft,task_revision}` |
| 生成预览 | `task_id`、`task_revision`、`config_hash` | `202 {operation_id,preview_id,state=previewing}`；查询接口返回统计、样本数、工件 hash 和分页数据 |
| 发布/执行 | `task_id`、`preview_id`、`task_revision` | `202 {operation_id,state=awaiting_annotation|executing}`；重复键返回原操作 |
| 指派 | `annotator_ids[]`、`sample_scope`、`due_at`、`task_revision` | `202 {assignment_ids[],sample_scope_hash,task_revision}`；每个标注员和样本范围单独审计 |
| 保存标签 | `assignment_id`、`sample_id`、`values{label_column_key:value}`、`base_revision` | `200 {sample_id,revision_no,values}`；过期返回 409 和当前完整集合/差异 |
| 完成确认 | `assignment_id`、`task_revision`、`scope_hash` | `200 {assignment_state,task_state,missing_samples[]}`；缺失标签不能确认 |
| 发起回传 | `assignment_id`、`task_revision`、`scope_hash`、`Idempotency-Key` | `202 {return_batch_id,operation_id,state=pending}`；返回批次只包含该固定范围 |
| 验收/退回 | `return_batch_id`、`decision`、`reason`、`task_revision` | `200 {batch_state,task_state,result_dataset_version_id?}` |
| 创建导出 | `model_version_id`、`annotation_task_revision?`、`include_runtime`、`Idempotency-Key` | `202 {export_id,operation_id,state=queued}`；下载只对 `completed` 且签名/校验通过的导出开放 |

`sample_scope` 只能是发布前解析出的 sample_id 集合或可审计筛选表达式；服务端保存解析后的集合和 hash。批量标签接口必须返回逐样本成功/冲突结果，不能把部分失败伪装成整体成功；客户端应按返回的 revision 重读后再重试。

## 13. 前端交互方案

### 13.1 主平台

数据标注页面采用任务列表作为操作中心：

- 创建任务、编辑草稿、预览、执行、指派、暂停、取消、归档和审计均从列表或显式预览进入。
- 手动任务预览展示说明、数据范围、可见字段、标签 schema 和分页样本。
- 自动任务预览额外展示模型、策略、全量分布、簇统计、规则命中和最终标签分页。
- 指派弹窗支持搜索、项目成员筛选、一次多选、截止时间和覆盖提醒。
- 回传结果列表独立展示来源任务、标注员、回传时间、验收状态、批注、差异和数据版本。

### 13.2 标注员门户

门户只展示被指派任务和执行所需信息：

- 任务队列支持状态、截止时间、逾期、完成进度和通知。
- 工作区使用分页表格和稳定控件，避免全量数据加载和布局抖动。
- 字符串枚举使用单值选择，自由文本使用文本输入，数值使用数值输入和范围提示。
- 批量操作先显示影响样本数和写入值；默认不覆盖已有合法值，覆盖需要确认。
- 门户不提供任意数据下载、标签 schema 管理、批注管理或模型导出；只展示被指派范围内的样本、标签输入和任务/样本批注，不展示模型、簇、规则的内部细节。

## 14. 权限、安全与审计

### 14.1 角色边界

| 角色 | 核心权限 |
|---|---|
| 系统管理员 | 标注员账号生命周期、全局算法目录、平台审计 |
| 项目管理员 | 数据版本、标签 schema、任务发布、指派、验收、模型注册/默认/导出 |
| 普通项目成员 | 创建草稿、配置、运行 AutoML；不能发布任务、验收回传或导出模型 |
| 标注员 | 独立门户内处理被指派任务、批注、确认和回传 |

### 14.2 数据访问保护

- 所有公开访问使用 HTTPS；服务间接口使用加密传输和服务身份认证。
- 数据库、对象存储和备份使用静态加密；密钥仅在受控配置中保存。
- 日志、通知和错误详情默认只保留任务 ID、sample_id、字段、错误类别和必要元数据，不记录完整行、标签值、密码或令牌。
- 项目隔离必须在查询、导出、统计、通知和内部 API 的每一层重复校验。

门户和主平台必须显式配置 CORS 允许来源，只允许登记的前端 origin，禁止 `*` 与携带凭据同时使用。Cookie 会话使用 `Secure`、`HttpOnly`、受控 `SameSite` 和短期过期；任何改变状态的 Cookie 请求同时校验 CSRF token、`Origin`/`Referer` 和请求方法，不能只依赖 SameSite。若采用 bearer token，令牌不得写入 localStorage，且必须校验 issuer、audience、scope、过期时间和会话版本。

登录、注册、密码重置和批量标签接口必须限流并审计。推荐默认值为同一 IP 登录 5 次/15 分钟、同一账号 10 次/15 分钟、注册 10 次/小时、密码重置 5 次/小时、单用户批量写入 120 次/分钟；超限返回统一错误，不泄露账号是否存在。密码长度 8 至 128 个字符，使用 Argon2id（或同等强度密码哈希）存储，禁止明文、可逆加密和日志记录，可选接入泄露密码黑名单。

JSON/XML 解析必须在隔离 worker 中执行，使用资源配额和超时；XML 禁止 DTD/外部实体/外部 schema/网络与文件系统访问，JSON 拒绝重复键，所有解析都执行文件大小、解压后大小、记录数、列数、深度和字段长度上限。上传内容按魔数/解析结果校验格式，拒绝路径穿越、压缩炸弹、实体扩展、解析超时和异常资源消耗。

### 14.3 审计与受控清理

默认不物理删除数据版本、任务快照、标签修订、回传批次、模型版本、导出记录或审计日志。归档为可逆状态。

系统提供极少数受审批的不可逆清理流程，用于合规、安全事件或重复大文件治理。清理流程必须包含双重权限、影响范围预览、不可逆确认、审计墓碑和备份处理记录。

## 15. 可靠性、容量和恢复

### 15.1 容量基线

| 项目 | 首期目标 |
|---|---|
| 单数据版本或标注任务 | 100 万样本 |
| 单数据版本原始字段 | 200 列 |
| 单任务标签列 | 20 列 |
| 标注员并发编辑 | 平台范围 100 人 |
| Silhouette 评估 | 不超过 100,000 样本使用全量；更大数据确定性抽样最多 50,000 条 |

所有列表、预览、差异和标注工作区必须使用服务端筛选、排序和分页。前端不得加载全量样本。聚类最终赋簇必须覆盖全部合格样本，K 评估样本数、抽样 hash 和耗时必须进入预览与审计；任务启动前先估算内存、CPU、对象存储和队列容量，超出部署配额时阻断而不是运行到中途失败。

### 15.2 任务可靠性

- 长耗时操作立即返回任务 ID；前端显示阶段、进度、错误和可重试状态。
- 用户离开页面后任务继续执行，完成、失败、需处理和逾期通过站内通知送达。
- 服务重启后通过持久化状态和幂等键恢复或重新领取未完成任务。
- 任务成功只在结果、工件、校验和和审计全部落库后发布。
- 任务失败、取消或缺少关键工件时，不暴露可被后续使用的部分结果。
- worker 领取任务使用租约（`lease_owner`、`lease_expires_at`、心跳）；租约过期可由单个新 worker 重新领取，已提交阶段通过唯一键和事务幂等。
- 预览、执行、回传和导出分别使用资源级唯一执行键；重复请求返回原操作，不启动第二个 worker。短暂基础设施错误按指数退避重试一次，超过上限进入失败并保留脱敏原因。
- 临时制品写入隔离前缀，只有数据库事务、校验和和审计记录全部成功后才标记为 committed；失败、取消或超时的孤立制品按 TTL 清理并保留清理审计，已发布制品不可被后台清理。

### 15.3 备份和恢复

按 RPO 不超过 1 小时、RTO 不超过 4 小时设计：

- 数据库和对象存储按同一恢复点备份。
- 至少每日全量、每小时增量或日志归档。
- 定期执行恢复演练。
- 恢复后校验数据版本、任务状态、模型工件和导出记录的一致性，再恢复写入。

## 16. 测试与验收标准

### 16.1 后端与合同测试

- 数据导入、类型冻结、schema 哈希、sample_id、数据版本和逻辑快照。
- 标签 schema、列级约束、批量写入、乐观并发、显式覆盖和来源链。
- 三种自动策略、全部兜底、规则优先级、待审核规则冲突、聚类边界和工件复用。
- 回传、验收、重新打开、回传替代、差异比较和训练血缘。
- 单目标/多目标分类与回归、交叉验证、算法兼容、搜索、排序、特征重要性和模型注册。
- 模型导出、predict/annotate、输入拒绝、输出契约和隔离运行。
- 项目隔离、服务身份、标注员越权、会话失效、指派变更和内部 API 幂等。

### 16.2 前端与浏览器验收

- 主平台：导入、任务创建、全量预览、指派、暂停、回传结果验收、差异与批注；预览状态、执行状态、需处理状态和错误重试入口可见。
- 标注员门户：注册、审核后登录、任务筛选、自动保存、冲突确认、批量标注、完成确认、显式重新编辑和回传。
- 权限：未授权项目、移除指派、停用账号、过期会话和下载限制。
- AutoML：分类/回归配置、候选报告、手动注册、状态切换和导出。
- 导出：ZIP 结构、校验和、manifest/SBOM/签名、离线 predict/annotate 及非法输入报告。

### 16.3 性能与恢复验收

- 按容量基线验证分页、预览、任务恢复、回传、差异查询和关键列表。
- 验证数据版本、标签修订、回传批次和模型导出在服务重启、重试和重复请求下保持幂等。
- 验证备份恢复后数据、制品和审计引用一致。

### 16.4 可执行验收矩阵

| 编号 | 场景 | 必须验证的结果 |
|---|---|---|
| DAT-01 | JSON/XML 正常导入 | 记录路径、字段映射、解析器版本和 schema hash 冻结，重新解析生成新版本 |
| DAT-02 | JSON/XML 安全输入 | XXE、DTD、重复键、非标量、超限文件、深度、超时和压缩炸弹均拒绝且无部分版本 |
| DAT-03 | 缺列与空值 | 缺少必需列返回 `INPUT_REQUIRED_COLUMN_MISSING`；列存在但值为空按 `missing_policy` 处理并记录计数 |
| LAB-01 | 标签类型 | int 溢出/小数、float NaN/Infinity、string 超长/空值/枚举不符均拒绝；合法值原样保留类型 |
| LAB-02 | 三种自动策略 | cluster/rule/cluster_rule 互斥；其他兜底不可删除且必须配置；规则未命中回退规则兜底 |
| LAB-03 | 策略优先级 | cluster_rule 按规则 > 簇 > 其他逐列决策，同优先级冲突进入 `needs_review` |
| CLU-01 | 加权 KMeans | 重要性来源、one-hot 聚合、多目标等权、零值阻断、K 2..8、seed 和工件可复现 |
| CLU-02 | 百万样本聚类 | 最终赋簇覆盖全量；Silhouette 评估模式/样本数/hash 正确记录，前端不加载全量 |
| CON-01 | 重叠样本并发编辑 | 过期 revision 返回 409 和差异；只有显式确认完整集合后才最后成功写入 |
| CON-02 | 并发回传 | 幂等键不重复建批次；过期批次不能静默覆盖，必须刷新/退回/重新修订 |
| RET-01 | 回传锁 | 回传后按钮和写入只读；显式编辑并产生新修订后才解除，同一范围旧批次被 supersede |
| AUTH-01 | 独立门户认证 | 独立 origin、Cookie、会话和账号；主体映射、项目授权、停用/重置后会话立即失效 |
| AUTH-02 | Web 安全 | CORS 白名单、CSRF、限流、密码哈希和服务间 JWT/mTLS 校验全部生效 |
| API-01 | API 合同 | 202 长任务、游标分页、状态守卫、统一错误、request/idempotency key 和审计关联完整 |
| AUTO-01 | 建模类型 | 四种规范 `task_type` 的列数、类型、指标和导出语义不混淆；兼容别名只在写入前归一化 |
| AUTO-02 | 模型注册 | worker 不自动注册；用户选择完整候选后手动注册，重复注册返回同一版本 |
| EXP-01 | 导出包 | manifest、合同 hash、运行时/库版本、seed、制品 SHA-256、SBOM、签名和策略工件齐全 |
| INF-01 | 离线推理 | 缺列、类型、解析合同、sample_id 或输出契约不符时整批拒绝并生成无敏感信息的 validation-report |
| REL-01 | 重试与恢复 | 租约过期可恢复、重复操作不产生副作用、临时制品按 TTL 清理且已提交制品不被删除 |

任何 required 测试、构建、迁移、浏览器验收、导出验证或恢复演练处于 failed、cancelled、skipped 或未执行状态时，均不得标记该功能完成。

## 17. 方案结论

本方案以通用数据版本、版本化标签 schema、逻辑任务快照、独立标注员服务、可复现 AutoML 和契约化模型导出为核心。它将数据、标签、任务、模型、人员权限和异步执行拆分为可独立验证的边界，并通过完整来源链、显式状态机、项目隔离和失败封闭原则保证可审计性与长期可维护性。
