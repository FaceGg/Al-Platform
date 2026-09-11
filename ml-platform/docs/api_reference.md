# API 接口文档 — ML算法平台

> Base URL: `http://localhost:8000`
> Swagger UI: `http://localhost:8000/docs`

## 认证方式

所有需要认证的接口需在请求头携带 JWT Token：
```
Authorization: Bearer <access_token>
```

---

## 1. 认证 (Auth)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/auth/login` | 用户登录，返回 access_token |
| POST | `/api/auth/register` | 用户注册 |

---

## 2. 用户管理 (Users)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/admin/users` | 获取所有用户（管理员） |
| GET | `/api/admin/users/{user_id}` | 获取指定用户 |
| PUT | `/api/admin/users/{user_id}/role` | 修改用户角色 |

---

## 3. 项目管理 (Projects)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/projects` | 获取项目列表 |
| POST | `/api/projects` | 创建项目 |
| GET | `/api/projects/{project_id}` | 获取项目详情 |
| PUT | `/api/projects/{project_id}` | 更新项目 |
| DELETE | `/api/projects/{project_id}` | 删除项目（204 No Content） |

---

## 4. 工作流 (Workflows)

### 4.1 工作流CRUD

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/projects/{project_id}/workflows` | 获取工作流列表 |
| POST | `/api/projects/{project_id}/workflows` | 创建工作流 |
| GET | `/api/projects/{project_id}/workflows/{workflow_id}` | 获取工作流详情 |
| PUT | `/api/projects/{project_id}/workflows/{workflow_id}` | 更新工作流 |
| DELETE | `/api/projects/{project_id}/workflows/{workflow_id}` | 删除工作流 |

### 4.2 工作流直接操作

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/workflows/{workflow_id}` | 直接获取工作流 |
| PUT | `/api/workflows/{workflow_id}` | 直接更新工作流 |

### 4.3 工作流执行

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/workflows/{workflow_id}/run` | 执行工作流，返回 run_id |

### 4.4 运行管理

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/runs/{run_id}` | 查询运行状态与结果 |

---

## 5. 算子 (Operators)

### 5.1 算子清单

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/operators` | 获取所有可用算子（含输入/输出/参数定义） |

### 5.2 算子分类

**数据IO类** (`io_operators.py`)：
- CSV导入、CSV导出、数据连接

**数据处理类** (`processing.py`)：
- 缺失值处理、类别编码、标准化、MinMax缩放、特征选择、数据分割

**机器学习类** (`ml_operators.py`)：
- 随机森林、XGBoost、逻辑回归、支持向量机、KNN、决策树

**模型评估类** (`evaluation.py`)：
- 分类评估、回归评估、混淆矩阵、交叉验证

**可视化类** (`visualization.py`)：
- 特征分布图、相关性热力图

**深度学习类** (`dl_operators.py`)：
- PyTorch训练器（条件导入，需安装torch）

---

## 6. 数据集 (Datasets)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/projects/{project_id}/datasets/upload` | 上传数据集文件 |
| POST | `/api/projects/{project_id}/datasets/batch` | 批量数据导入 |
| GET | `/api/projects/{project_id}/datasets/export` | 导出项目数据集 |
| GET | `/api/datasets/{dataset_id}/export` | 导出指定数据集 |
| GET | `/api/datasets/{dataset_id}/preview` | 预览数据集内容 |

---

## 7. 知识库 (Knowledge Base)

### 7.1 知识库CRUD

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/knowledge/bases` | 获取知识库列表 |
| POST | `/api/knowledge/bases` | 创建知识库 |
| GET | `/api/knowledge/bases/{kb_id}` | 获取知识库详情 |
| DELETE | `/api/knowledge/bases/{kb_id}` | 删除知识库 |

### 7.2 文档管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/knowledge/bases/{kb_id}/documents` | 上传文档（txt/md/csv） |
| GET | `/api/knowledge/bases/{kb_id}/documents` | 获取文档列表 |
| DELETE | `/api/knowledge/documents/{doc_id}` | 删除文档 |

### 7.3 向量化与检索

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/knowledge/bases/{kb_id}/vectorize` | 向量化未嵌入文档，同步写入VectorStore |
| POST | `/api/knowledge/bases/{kb_id}/search` | 向量相似度搜索（支持use_vector_store参数） |
| POST | `/api/knowledge/bases/{kb_id}/search/hybrid` | 混合检索：向量+元数据过滤+关键词 |
| POST | `/api/knowledge/bases/{kb_id}/rag` | RAG问答（检索+LLM生成） |

**混合检索请求体示例**：
```json
{
  "query": "焊接电流对质量的影响",
  "top_k": 5,
  "metadata_filter": {"kb_id": "xxx"},
  "keyword": "电流"
}
```

### 7.4 对话管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/knowledge/bases/{kb_id}/chat` | 发起RAG对话 |
| GET | `/api/knowledge/bases/{kb_id}/chats` | 获取会话列表 |
| POST | `/api/knowledge/bases/{kb_id}/chats` | 创建新会话 |
| GET | `/api/knowledge/bases/{kb_id}/chats/{session_id}` | 获取会话消息 |
| DELETE | `/api/knowledge/bases/{kb_id}/chats/{session_id}` | 删除会话 |

### 7.5 知识图谱

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/knowledge/bases/{kb_id}/graph/entities` | 获取实体列表 |
| POST | `/api/knowledge/bases/{kb_id}/graph/entities` | 创建实体 |
| DELETE | `/api/knowledge/graph/entities/{entity_id}` | 删除实体 |
| GET | `/api/knowledge/bases/{kb_id}/graph/relations` | 获取关系列表 |
| POST | `/api/knowledge/bases/{kb_id}/graph/relations` | 创建关系 |
| DELETE | `/api/knowledge/graph/relations/{rel_id}` | 删除关系 |
| GET | `/api/knowledge/bases/{kb_id}/graph` | 获取完整图谱（nodes+edges） |

---

## 8. 模型训练 (Training)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/training/run` | 启动训练任务 |
| GET | `/api/training/jobs` | 获取训练任务列表 |
| GET | `/api/training/jobs/{job_id}` | 获取训练任务详情 |

### 8.1 AutoML

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/training/automl/run` | 启动自动化建模 |
| GET | `/api/training/automl/jobs` | 获取AutoML任务列表 |

---

## 9. 模型库 (Models)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/projects/{project_id}/models` | 获取项目下所有模型 |
| GET | `/api/models/{model_id}` | 获取模型详情 |
| DELETE | `/api/models/{model_id}` | 删除模型 |

---

## 10. 工艺模板 (Templates)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/templates` | 获取模板列表 |
| GET | `/api/templates/{template_id}` | 获取模板详情 |
| POST | `/api/templates/{template_id}/instantiate` | 从模板创建工作流 |

---

## 11. 系统监控 (Monitor)

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/monitor/current` | 获取当前资源使用（CPU/内存/磁盘/GPU） |
| GET | `/api/monitor/history` | 获取历史监控数据 |

---

## 12. 数据标注 (Labeling)

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/labeling/rules` | 基于规则的自动标注 |
| POST | `/api/labeling/similarity` | 基于相似度的标注推荐 |

---

## 13. 多智能体协同 (Orchestration)

### 13.1 智能体管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/orchestration/agents` | 注册智能体 |
| GET | `/api/orchestration/agents` | 获取智能体列表 |

### 13.2 任务管理

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/orchestration/tasks` | 创建协同任务 |
| GET | `/api/orchestration/tasks` | 获取任务列表 |
| GET | `/api/orchestration/tasks/{task_id}` | 获取任务详情 |

### 13.3 规划与审核

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/orchestration/plan` | LLM任务分解与规划 |
| GET | `/api/orchestration/reviews` | 获取审核任务列表 |
| POST | `/api/orchestration/reviews/{task_id}` | 提交审核结果 |

### 13.4 消息

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/orchestration/messages` | 发送智能体间消息 |

---

## 14. 系统

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |

## 15. API 管理

API 市场前端入口为 `/api-marketplace`，应通过前端开发/部署端口访问；后端页面地址 `/api-marketplace` 不存在。
所有接口需要登录后的 Bearer Token，前端 Axios 客户端会自动附加认证头。

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/platform/apis` | 获取当前用户拥有或公开可见的 API |
| GET | `/api/platform/apis/stats` | 获取权限范围内的 API 总数、发布/下线/失败数和调用总数 |
| POST | `/api/platform/apis` | 创建自定义 API；仅接受内部 `/api/...` 路径 |
| PUT | `/api/platform/apis/{api_id}` | 编辑自定义 API；来源绑定 API 由部署生命周期管理 |
| DELETE | `/api/platform/apis/{api_id}` | 删除自定义 API；来源绑定 API 不允许直接删除 |
| POST | `/api/platform/apis/publish/deployment/{deployment_id}` | 发布运行中的推理部署，幂等返回同一 API |
| POST | `/api/platform/apis/publish/deployment/{deployment_id}/offline` | 将部署 API 下线 |

模型 API 的真实执行地址为 `/api/inference-deployments/{deployment_id}/predict`。部署成功启动后自动发布，停止后自动下线；未达到 running/running 状态的部署不能发布。

---

## 16. 通用自动建模与数据标注平台

### 16.1 数据版本与标签 schema

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/projects/{project_id}/dataset-versions` | 查询项目授权的数据版本 |
| GET | `/api/projects/{project_id}/label-schemas` | 查询项目标签 schema |
| POST | `/api/projects/{project_id}/label-schemas` | 创建多列标签 schema |
| GET | `/api/dataset-versions/{version_id}` | 查询不可变数据版本及输入合同 |

支持 CSV、Excel、Parquet、JSON 和 XML。JSON/XML 会先归一化为扁平标量表；解析器拒绝重复键、非标量值、外部实体、路径穿越和超出大小/行数/列数限制的输入。数据版本一旦冻结不可修改。

### 16.2 通用标注任务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/annotation-tasks` | 按项目和所有者分页查询任务 |
| POST | `/api/annotation-tasks` | 创建手动通用标注任务 |
| POST | `/api/automl-tasks` | 创建自动标注/AutoML 任务 |
| POST | `/api/annotation-tasks/{task_id}/preview` | 创建或复用当前 revision 的预览 |
| GET | `/api/annotation-tasks/{task_id}/previews` | 查询预览历史 |
| GET | `/api/annotation-tasks/{task_id}/previews/{preview_id}` | 查询预览状态、快照和摘要 |
| GET | `/api/annotation-tasks/{task_id}/previews/{preview_id}/samples` | 游标分页查询预览样本 |
| POST | `/api/annotation-tasks/{task_id}/execute` | 执行当前 revision 的已完成预览 |
| POST | `/api/annotation-tasks/{task_id}/transition` | 按 revision 执行状态转移 |
| GET | `/api/annotation-tasks/{task_id}/executions/{operation_id}/results` | 游标分页查询执行结果 |
| GET | `/api/annotation-tasks/{task_id}/executions/{operation_id}/stats` | 查询样本、策略和最终标签统计 |
| GET | `/api/annotation-operations` | 查询统一操作中心 |

所有长任务返回 `202` 和 `operation_id`。预览和执行均绑定不可变任务快照、配置 revision 和配置 hash；旧 revision 预览不能解锁当前 revision 的执行。状态修改必须携带 `task_revision`。

### 16.3 AutoML 合同

持久化任务类型为 `classification`、`multioutput_classification`、`regression` 和 `multioutput_regression`。交叉验证支持 2 至 5 折；搜索方法支持 `grid`、`random`、`bayesian`、`evolutionary` 和 `multi_fidelity`；搜索强度使用 `light`、`medium`、`high` 和 `ultra` 档位。AutoML worker 只生成候选制品，不能自动创建或批准模型库版本。

自动标注策略支持 `model`、`cluster`、`rule` 和 `cluster_rule`。同一标签列的来源优先级固定为规则、簇、其他；冲突或无法满足类型约束时返回 `needs_review`，不伪造兜底值或特征重要性。

### 16.4 指派、门户和回传

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/annotation-tasks/{task_id}/assignments` | 指派一个或多个独立标注员 |
| GET | `/api/projects/{project_id}/annotation-return-batches` | 查询回传批次 |
| GET | `/api/annotation-return-batches/{return_batch_id}/diff` | 查询回传差异 |
| POST | `/api/annotation-return-batches/{return_batch_id}/accept` | 验收回传并生成新数据版本 |
| POST | `/api/annotation-return-batches/{return_batch_id}/return` | 退回回传并记录原因 |
| POST | `/portal/auth/register` | 标注员注册 |
| POST | `/portal/auth/login` | 标注员门户登录 |
| GET | `/portal/tasks` | 查询当前主体的指派任务 |
| PUT | `/portal/tasks/{task_id}/samples/{sample_id}/labels` | 保存样本标签 |
| POST | `/portal/tasks/{task_id}/confirm` | 确认标签集合 |
| POST | `/portal/tasks/{task_id}/edit-for-return` | 显式解除回传只读锁 |
| POST | `/portal/tasks/{task_id}/return` | 主动回传任务 |

门户使用独立账号、主体 ID、会话和前端入口，不共享主平台 Cookie 或项目选择器。标签写入携带基础 revision；冲突响应包含服务端完整标签集合，必须由标注员明确确认后才能重试。回传成功后范围只读，必须显式编辑并产生新 revision。

### 16.5 幂等、分页和安全

所有写请求要求 `Authorization`、`X-Request-ID` 和 `Idempotency-Key`。列表、样本、预览、结果、统计和差异使用 `cursor` 分页，默认 50、最大 200；游标耗尽后不得重新请求第一页。重复的幂等请求返回原始 operation/resource。

错误响应至少包含 `request_id`、稳定 `code`、`message` 和 `details`。Cookie 状态修改需要 CSRF 校验；CORS 使用明确来源白名单；认证、注册、密码重置和批量标注执行限流。错误详情、导出包和日志不得包含密码、令牌、密钥或真实数据。

### 16.6 模型导出与离线运行

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/model-exports` | 创建预测或标注导出 |
| GET | `/api/model-exports/{export_id}` | 查询导出状态 |
| POST | `/api/model-exports/{export_id}/validate` | 校验导出包 |
| GET | `/api/model-exports/{export_id}/download` | 导出完成后一次性下载 |

导出包必须包含模型、预处理、输入输出合同、映射、推理代码、依赖锁定、SBOM、签名和全量 SHA-256。只有 `ready` 且验证通过的导出可下载；无效输入只产生脱敏报告，不发布部分结果。

---

## 通用响应格式

成功：
```json
{
  "id": "uuid",
  "name": "string",
  ...
}
```

错误：
```json
{
  "detail": "错误描述信息"
}
```

HTTP状态码：
- `200`：成功
- `201`：创建成功
- `204`：删除成功（无响应体）
- `400`：请求参数错误
- `401`：未认证
- `403`：无权限
- `404`：资源不存在
- `500`：服务器内部错误
