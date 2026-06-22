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
