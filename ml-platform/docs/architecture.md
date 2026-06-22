# 汽车焊接制造工艺智能体编排软件 — 架构设计

## 1. 产品概述

面向汽车焊接制造工艺场景，提供自动化建模、模型训练、工作流编排、多智能体协同、向量数据库、RAG知识库6类核心能力的智能体编排平台。

### 应用场景
- **焊接质量预测**：基于工艺参数（电流、电压、压力、时间）预测焊点质量
- **工艺参数推荐**：根据材料属性和焊接要求推荐最优参数组合
- **缺陷检测与分类**：利用ML模型对焊接缺陷进行自动识别分类
- **产线知识管理**：构建焊接工艺知识库，支持智能问答与工艺溯源

## 2. 技术架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    前端 (React 18 + TypeScript)           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │Dashboard │ │Workspace │ │Knowledge │ │  Monitor    │ │
│  │  仪表盘   │ │ 工作流编辑 │ │  知识库  │ │   监控面板   │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
│          Ant Design + ReactFlow + ECharts               │
└──────────────────────┬──────────────────────────────────┘
                       │ REST / WebSocket
┌──────────────────────┴──────────────────────────────────┐
│                  后端 (FastAPI + SQLAlchemy)              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │  Auth    │ │ Workflow │ │Training  │ │ Knowledge   │ │
│  │  认证鉴权 │ │ DAG执行  │ │ 训练管理  │ │  RAG+Graph  │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │
│  │Operator  │ │ Monitor  │ │Orchestra │ │  Vector     │ │
│  │  算子注册 │ │ 资源监控  │ │多智能体  │ │  Store      │ │
│  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │
│              NetworkX DAG Engine + NumPy                │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────────┐
│                    数据层                                 │
│     SQLite (开发) / PostgreSQL (生产) + 文件存储          │
└─────────────────────────────────────────────────────────┘
```

### 2.2 技术选型

| 层次 | 技术 | 说明 |
|------|------|------|
| **前端** | React 18 + TypeScript | SPA框架 |
| **UI组件库** | Ant Design 5 | 企业级UI组件 |
| **流程可视化** | ReactFlow | 可视化流程编排 |
| **后端框架** | FastAPI | 高性能异步Web框架 |
| **ORM** | SQLAlchemy 2.0 | 数据库ORM |
| **DAG引擎** | NetworkX | 有向图执行引擎 |
| **ML框架** | scikit-learn + XGBoost + PyTorch | 传统ML/深度学习 |
| **向量存储** | NumPy (内存HNSW) | 高性能向量索引 |
| **数据库** | SQLite (开发) / PostgreSQL (生产) | 关系型数据库 |
| **部署** | Docker Compose | 容器化部署 |

### 2.3 目录结构

```
ml-platform/
├── backend/
│   └── app/
│       ├── main.py              # FastAPI入口
│       ├── config.py            # 配置管理
│       ├── database.py           # 数据库连接
│       ├── api/                  # API路由层
│       │   ├── auth.py          # 认证
│       │   ├── projects.py      # 项目管理
│       │   ├── workflows.py     # 工作流CRUD
│       │   ├── workflows_direct.py # 工作流直接操作
│       │   ├── runs.py          # 运行管理
│       │   ├── operators.py     # 算子列表
│       │   ├── datasets.py      # 数据集
│       │   ├── templates.py     # 工艺模板
│       │   ├── training.py      # 模型训练
│       │   ├── knowledge.py     # 知识库/RAG
│       │   ├── labeling.py      # 数据标注
│       │   ├── monitor.py       # 系统监控
│       │   ├── orchestration.py # 多智能体协同
│       │   ├── models.py        # 模型库管理
│       │   └── users.py         # 用户管理
│       ├── engine/              # 核心引擎
│       │   ├── base_operator.py # 算子基类
│       │   ├── dag_executor.py  # DAG执行器
│       │   ├── data_bus.py      # 数据总线
│       │   ├── registry.py      # 算子注册
│       │   └── vector_store.py  # 向量存储
│       ├── operators/           # 算子实现
│       │   ├── io_operators.py  # 数据IO
│       │   ├── processing.py    # 数据处理
│       │   ├── ml_operators.py  # 机器学习
│       │   ├── dl_operators.py  # 深度学习
│       │   ├── evaluation.py    # 模型评估
│       │   └── visualization.py # 可视化
│       ├── models/              # 数据模型
│       └── schemas/             # Pydantic模式
├── frontend/                    # React前端
└── docs/                        # 文档
```

## 3. 6类能力模块

### 3.1 自动化建模 (AutoML)

**目标**：低代码实现从数据到模型的全流程自动化

**核心能力**：
- **数据导入**：支持CSV/Excel/URL/批量上传，自动检测列类型
- **自动特征工程**：缺失值处理（均值/中位数/众数填充）、类别编码（One-Hot/Label）、数值标准化（Standard/MinMax）
- **多模型对比训练**：RandomForest / XGBoost / LogisticRegression / SVM 并行训练
- **5-fold交叉验证**：自动评分（Accuracy/F1/ROC-AUC）
- **模型选择**：基于验证集表现自动推荐最优模型
- **超参配置**：支持网格搜索与随机搜索

**API端点**：`POST /api/training/automl/run`, `GET /api/training/automl/jobs`

### 3.2 模型训练 (Training)

**目标**：统一训练框架，支持20+算子的灵活编排

**核心能力**：
- **统一训练框架**：算子化设计，拖拽式构建训练流水线
- **实时监控**：WebSocket推送训练状态（epoch/loss/accuracy）
- **早停策略**：验证集loss不再下降时自动停止
- **检查点管理**：训练中断可从最近检查点恢复
- **模型版本管理**：自动版本号递增（v1/v2/...）
- **增量训练**：支持在新数据上继续训练已有模型

**API端点**：`POST /api/training/run`, `GET /api/training/jobs`, `GET /api/training/jobs/{job_id}`

### 3.3 工作流编排 (Workflow)

**目标**：可视化拖拽式构建ML流水线，DAG引擎驱动执行

**核心能力**：
- **ReactFlow可视化编辑**：拖拽算子节点、连线构建数据流
- **DAG循环检测**：拓扑排序确保无环依赖
- **条件分支/循环/并行**（规划中）
- **工艺模板**：预置焊接场景模板（焊接质量预测/参数推荐/缺陷分类）
- **执行管理**：可监控、可中断、可回溯

**API端点**：工作流CRUD + WebSocket实时推送 + Run管理

### 3.4 多智能体协同 (Orchestration)

**目标**：LLM驱动的任务分解→分配→执行→聚合闭环

**核心能力**：
- **智能体注册**：支持类型：planner / executor / reviewer / llm
- **任务分解**：LLM将复杂任务拆解为子任务
- **路由分配**：根据智能体能力自动分配任务
- **大小模型协同**：轻量模型做特征提取，大模型做语义理解
- **人机协同**：关键节点人工审核接口
- **消息通信**：智能体间消息传递与状态同步

**API端点**：Agent CRUD、Task CRUD、Review、Message、Plan

### 3.5 向量数据库 (Vector Store)

**目标**：高性能内存向量索引，支持混合检索

**核心能力**：
- **HNSW-like索引**：基于图的近似最近邻搜索，支持M=16连接数配置
- **元数据过滤**：支持等值/列表过滤（如 `{"doc_id": "abc"}`、`{"type": ["A","B"]}`）
- **关键词混合检索**：向量相似度 + 关键词降权（0.3系数）
- **增量写入**：线程安全的批量添加
- **更新/删除**：支持单条更新和批量删除
- **余弦相似度**：默认L2归一化后点积计算

**技术指标**：
- 维度：768（可配置）
- 相似度度量：cosine
- 存储：内存（NumPy数组）
- 线程安全：threading.Lock保护

### 3.6 RAG知识库 (Knowledge Base)

**目标**：文档→向量化→语义检索→LLM生成的知识闭环

**核心能力**：
- **文档管理**：上传（txt/md/csv）、自动分段（Chunk）
- **向量化**：TF-IDF全量语料库嵌入
- **语义检索**：余弦/欧氏/点积多度量支持
- **LLM生成**：检索增强生成（RAG），上下文拼接
- **多轮对话**：ChatSession支持上下文连续对话
- **知识图谱**：实体-关系建模，可视化图谱
- **来源可溯**：每个答案标注引用来源文档

**API端点**：KB CRUD、Document CRUD、Search、Vectorize、RAG、Chat、Graph

## 4. 数据流

### 4.1 知识库RAG流程
```
[文档上传] → 段落切分(Chunk) → TF-IDF向量化 → 存入VectorStore + DB
                                                      ↓
[用户提问] → 查询向量化 → VectorStore检索(k-NN) → 拼接上下文 → LLM生成 → 返回答案
```

### 4.2 模型训练流程
```
[数据上传] → 预处理(缺失值/编码/标准化) → 特征工程 → 模型训练(RF/XGBoost/...) 
                                                         ↓
                                                    交叉验证评估 → 模型选择 → 保存部署
```

### 4.3 多智能体协同流程
```
[用户任务] → LLM Planner分解 → 子任务队列 → Router分配Agent 
                                                   ↓
                                            Executor执行 → Reviewer审核 → 结果聚合 → 返回
```

## 5. 部署

### 5.1 开发环境
```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev

# 访问
前端: http://localhost:5173
后端: http://localhost:8000
API文档: http://localhost:8000/docs
```

### 5.2 生产环境
```bash
docker-compose up -d
```

### 5.3 配置文件
- `.env`：环境变量（数据库URL、密钥等）
- `config.py`：应用配置（CORS、上传限制等）

## 6. 安全设计

- **JWT认证**：access token + refresh token
- **RBAC权限**：admin / user 角色分离
- **CORS白名单**：仅允许前端域名
- **密码加密**：SHA-256哈希存储

## 7. 扩展性设计

- **插件化算子**：通过装饰器注册新算子，零侵入扩展
- **多数据库**：SQLAlchemy抽象层，轻松切换SQLite/PostgreSQL
- **向量存储可替换**：VectorStore抽象接口，可替换为FAISS/Milvus
- **前端微服务化**：页面级懒加载，按需扩展功能模块
