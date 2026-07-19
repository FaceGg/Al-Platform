# AI模型训练编排平台 - 需求与开发进度总览

> 第六周远程验收：GitHub Actions [Run 29631795297](https://github.com/FaceGg/Al-Platform/actions/runs/29631795297) 全部通过（Linux/Windows quality、Production integration、Production experiment integration、Chromium）。

> 第七周：调度、项目角色/审计、迁移、全量与 WSL 生产集成已通过；仅待本次远程 CI。

> 最后更新: 2026-07-18 | 当前版本: 0.3.0

---

## 一、平台定位

面向**汽车焊接制造**场景的 Web 级 AI 模型训练编排平台，定位为专属 AI "智造工厂"。平台覆盖数据管理、模型训练、工作流编排、应用部署的全链路 AI 开发原子能力，支持**零代码拖拽操作**、**可视化工作流编排**、**多智能体协同**。

**目标用户**: 业务人员 / 产线工程师 / 算法工程师

---

## 二、技术架构

| 层次 | 技术栈 |
|------|--------|
| 前端框架 | React 18 + TypeScript + Vite |
| UI 组件库 | Ant Design 5.x |
| 工作流画布 | ReactFlow v11 |
| 状态管理 | Zustand |
| 国际化 | 自研 Context (zh/en) |
| 后端框架 | FastAPI (Python 3.12) |
| 数据库 | SQLite (SQLAlchemy ORM) |
| 机器学习 | scikit-learn / XGBoost |
| 深度学习 | PyTorch |
| 数据序列化 | JSON Lines (流式) + 二进制 (Bytes) |
| 通信 | RESTful API + WebSocket |
| 数据总线 | DataBus (临时文件系统) |
| DAG 引擎 | NetworkX + 自定义拓扑执行器 |

---

## 三、算子总览 (80个)

### 3.1 数据接入 (IO) — 10个
| ID | 名称 | 输入 | 输出 |
|----|------|------|------|
| csv_import | CSV/Excel Import | — | data |
| csv_export | CSV Export | data | data |
| json_import | JSON Import | — | data |
| read_excel | Read Excel | — | data |
| read_database | Read Database | — | data |
| read_url | Read URL | — | data |
| write_csv | Write CSV | data | data |
| retrieve | Retrieve | — | data |
| store | Store | data | data |
| image_import | Image Import | — | data |

### 3.2 数据清洗与预处理 (Processing) — 13个
| ID | 名称 | 功能 |
|----|------|------|
| missing_value_handler | Missing Value Handler | 缺失值处理（删除/均值/中位数/众数/常量） |
| impute_missing_advanced | Impute Missing (Advanced) | 高级缺失值填充（sklearn SimpleImputer） |
| label_encoder | Label Encoder | 分类编码（Label / OneHot） |
| scaler | Scaler | 特征缩放（Standard/MinMax/Robust），支持排除目标列 |
| normalize | Normalize | 数值标准化 |
| discretize | Discretize | 连续值离散化（等宽/等频） |
| detect_outliers | Detect Outliers | 异常值检测（Z-score / IQR） |
| select_attributes | Select Attributes | 列筛选 |
| set_role | Set Role | 列角色设置（label/id/weight/feature/ignore） |
| filter_examples | Filter Examples | 行筛选（表达式） |
| sample | Sample | 随机采样 |
| train_test_split | Train/Test Split | 数据集划分 |
| auto_feature_engineering | Auto Feature Engineering | 自动特征工程（交互/多项式） |

### 3.3 机器学习 (ML) — 15个
| ID | 名称 | 类型 |
|----|------|------|
| xgboost_train | XGBoost Trainer | 分类/回归 |
| random_forest_train | Random Forest Trainer | 分类/回归 |
| linear_model_train | Linear Model Trainer | 分类/回归 |
| decision_tree | Decision Tree | 分类 |
| naive_bayes | Naive Bayes | 分类 |
| knn | k-NN | 分类 |
| svm | SVM | 分类 |
| logistic_regression | Logistic Regression | 分类 |
| random_forest_regression | Random Forest Regression | 回归 |
| svm_regression | SVM Regression | 回归 |
| kmeans_clustering | k-Means | 聚类 |
| dbscan | DBSCAN | 聚类 |
| apriori | Apriori | 关联规则 |
| fp_growth | FP-Growth | 关联规则 |
| apply_model | Apply Model | 模型应用（支持 sklearn + PyTorch） |

### 3.4 深度学习 (DL) — 3个
| ID | 名称 | 类型 |
|----|------|------|
| mlp_classifier | MLP Classifier | 分类 |
| mlp_regressor | MLP Regressor | 回归 |
| cnn1d_classifier | CNN1D Classifier | 一维时序分类 |

### 3.5 模型评估 (Evaluation) — 6个
| ID | 名称 | 功能 |
|----|------|------|
| classification_eval | Classification Evaluation | 基本分类评估（准确率/精确率/召回率/F1 + 混淆矩阵） |
| classification_eval_detailed | Classification Evaluation (Detailed) | 详细评估（逐标签指标/错误分析/F1曲线） |
| regression_eval | Regression Evaluation | 回归评估（MSE/RMSE/MAE/R²） |
| model_comparison | Model Comparison | 多模型对比 |
| cross_validation | Cross Validation | K折交叉验证 |
| anomaly_eval | Anomaly Evaluation | 异常率、Fault 精确率/召回率/F1 和混淆矩阵 |

### 3.6 可视化 (Visualization) — 11个
| ID | 名称 | 图表类型 |
|----|------|----------|
| data_table | Data Table | 数据表格 |
| data_stats | Data Statistics | 统计摘要 |
| roc_curve | ROC Curve | ROC 曲线 |
| feature_importance | Feature Importance | 特征重要性 |
| distribution_plot | Distribution Plot | 分布图 |
| scatter_plot | Scatter Plot | 散点图 |
| histogram | Histogram | 直方图 |
| line_chart | Line Chart | 折线图 |
| confusion_matrix_plot | Confusion Matrix Plot | 混淆矩阵 |
| box_plot | Box Plot | 箱线图 |
| bar_chart | Bar Chart | 柱状图 |

### 3.7 数据融合 (Blending) — 7个
| ID | 名称 | 功能 |
|----|------|------|
| join | Join | 多表关联（inner/left/right/outer） |
| union | Union | 纵向合并 |
| aggregate | Aggregate | 分组聚合 |
| pivot | Pivot | 数据透视 |
| transpose | Transpose | 行列转置 |
| generate_attributes | Generate Attributes | 表达式生成新列 |
| sort | Sort | 排序 |

### 3.8 流程控制 (Control) — 3个
| ID | 名称 | 功能 |
|----|------|------|
| condition | Condition | 条件分支 |
| merge | Merge | 数据合并 |
| loop | Loop | 循环控制 |

### 3.9 实用工具 (Utility) — 4个
| ID | 名称 | 功能 |
|----|------|------|
| execute_python | ExecutePython | 嵌入 Python 脚本 |
| collect | Collect | 对象收集 |
| macro | Macro | 宏变量 |
| write_as_text | WriteAsText | 文本输出 |

### 3.10 参数优化 (Optimization) — 2个
| ID | 名称 | 功能 |
|----|------|------|
| optimize_grid | Grid Search Optimization | 网格搜索 |
| optimize_evolutionary | Evolutionary Optimization | 进化算法优化 |

### 3.11 焊接机理模型 (Mechanism) — 6个
| ID | 名称 | 功能 |
|----|------|------|
| mechanism_thermal | 热传导模型 | 峰值温度/熔化半径计算 |
| mechanism_nugget | 熔核生长模型 | 熔核直径/穿透率评估 |
| mechanism_lobe | 焊接窗口模型 | 合格焊接参数窗口 |
| mechanism_splash | 飞溅预测模型 | 飞溅风险评估 |
| mechanism_stress | 残余应力模型 | 残余应力分析 |
| mechanism_gate | 机理校验总控 | 多模型汇总校验 |

---

## 四、前端页面 (24个路由)

| 路由 | 页面 | 状态 |
|------|------|------|
| /login | 登录页 | ✅ |
| /register | 注册页 | ✅ |
| / | 数据驾驶舱 | ✅ |
| /projects | 项目管理 | ✅ |
| /projects/:projectId | 项目详情（含工作流列表） | ✅ |
| /workspace/:workflowId | **工作流编辑器**（画布+算子面板+配置面板） | ✅ |
| /template/:templateId | 模板向导 | ✅ |
| /models | 模型库 | ✅ |
| /data | 数据管理 | ✅ |
| /admin/users | 用户管理 | ✅ |
| /knowledge | 知识库 | ✅ |
| /knowledge/:kbId | 知识详情 | ✅ |
| /knowledge-graph | 知识图谱 | ✅ |
| /automl | 自动化建模 | ✅ |
| /training | 模型训练 | ✅ |
| /monitor | 资源监控 | ✅ |
| /algorithms | 算法目录 | ✅ |
| /api-marketplace | API 市场 | ✅ |
| /annotations | 数据标注 | ✅ |
| /orchestration | 应用编排 | ✅ |
| /compute | 计算资源管理 | ✅ |
| /chat | 智能对话 | ✅ |

---

## 五、后端 API 模块 (22个)

| 模块 | 路由前缀 | 功能 |
|------|----------|------|
| auth | /api/auth | 认证（登录/注册） |
| projects | /api/projects | 项目管理 CRUD |
| workflows | /api/workflows | 工作流 CRUD |
| workflows_direct | /api/workflows/direct | 工作流直接操作 |
| runs | /api/workflows/{id}/run | 工作流运行 + WebSocket |
| operators | /api/operators | 算子列表 |
| datasets | /api/datasets | 数据集管理 |
| templates | /api/templates | 预置模板 |
| users | /api/users | 用户管理 |
| models | /api/models | 训练模型管理 |
| model_library | /api/model-library | 模型库 |
| knowledge | /api/knowledge | 知识库 CRUD |
| monitor | /api/monitor | 资源监控 |
| labeling | /api/labeling | 数据标注 |
| training | /api/training | 训练任务 |
| orchestration | /api/orchestration | 应用编排 |
| algorithm | /api/algorithms | 算法目录 |
| platform_api | /api/platform | 平台 API |
| compute | /api/compute | 计算资源 |
| annotations | /api/annotations | 标注 API |
| chat | /api/chat | 智能对话 |
| dashboard | /api/dashboard | 仪表盘统计 |

---

## 六、预置工作流模板 (4个)

| ID | 名称 | 节点数 | 管道 |
|-----|------|--------|------|
| weld_quality | 焊接质量预测 | 7 | CSV→缺失值→编码→缩放→划分→XGBoost→评估 |
| param_recommend | 参数推荐 | 6 | CSV→缺失值→缩放→划分→随机森林回归→评估 |
| anomaly_detect | 异常检测 | 4 | CSV→缺失值→异常检测→统计 |
| full_ml | 全流程ML对比 | 9 | CSV→预处理→划分→RF/XGB双模型→评估→对比 |

---

## 七、核心特性

### 已完成
- [x] 80 个算子，11 个分类
- [x] 可视化拖拽 DAG 工作流编辑器 (ReactFlow)
- [x] 算子端口颜色状态（橙色=待运行/蓝色=运行中/绿色=完成/红色=失败）
- [x] 运行/终止切换按钮
- [x] WebSocket 实时运行状态推送
- [x] DataBus 流式数据总线（JSONL 防止内存溢出）
- [x] 模型序列化（bytes → .bin 二进制存储）
- [x] 端到端数据管道（算子间数据透明传递）
- [x] DAG 执行引擎（拓扑排序 + 条件分支 + 循环 + 并行）
- [x] 算子参数智能列推测（上游数据列名自动建议）
- [x] 端口数据预览（鼠标悬停显示数据摘要）
- [x] 算子端口动态分布
- [x] 连线悬停显示红色 X 删除按钮
- [x] 工作流保存/删除
- [x] 工作流名称编辑
- [x] 本地文件上传
- [x] 中英文界面切换 (i18n)
- [x] 明暗主题切换
- [x] 用户认证（JWT 令牌 + 角色权限）
- [x] 用户管理（管理员可删除用户）
- [x] 焊接机理模型 6 个
- [x] PyTorch 深度学习算子
- [x] 4 个预置工作流模板
- [x] 22 个前端页面
- [x] 22 个后端 API 模块

### 部分完成 / 需优化
- [~] 知识库页面（页面存在，功能需完善）
- [~] 知识图谱页面（页面存在，功能需完善）
- [~] RAG 集成（后端模块存在，前端待完善）
- [~] 资源监控实时数据（页面存在，后端需增强）
- [~] 自动化建模（算子存在，页面需完善）
- [~] 模型训练任务管理（页面存在，功能需完善）
- [~] 数据标注工具（页面存在，功能需完善）
- [~] 应用编排（页面存在，功能需完善）
- [~] API 市场（页面存在，功能需完善）
- [~] 向量数据库集成（后端 engine 存在）
- [~] 多智能体协同编排（模型存在）
- [~] 中文显示偶发乱码

### 未开始 / 待开发
- [ ] 边缘设备部署（盒子 IP 管理）
- [ ] CI/CD 自动化发布
- [ ] 模型 CICD 下发
- [ ] 详细单元测试覆盖
- [ ] E2E 集成测试
- [ ] 性能压力测试
- [ ] 用户操作文档

---

## 八、关键文件清单

### 后端核心
| 文件 | 说明 |
|------|------|
| backend/app/main.py | FastAPI 入口，路由注册 |
| backend/app/engine/data_bus.py | 数据总线（JSONL 流式 + bytes 二进制） |
| backend/app/engine/dag_executor.py | DAG 执行引擎 |
| backend/app/engine/registry.py | 算子注册表 |
| backend/app/engine/base_operator.py | 算子基类 |
| backend/app/operators/*.py | 12 个算子模块 |
| backend/app/api/templates.py | 工作流模板 |
| backend/app/api/runs.py | 运行管理 + WebSocket |

### 前端核心
| 文件 | 说明 |
|------|------|
| frontend/src/pages/WorkspacePage.tsx | 工作流编辑主页面 |
| frontend/src/components/workspace/CustomNode.tsx | 自定义算子节点（端口+状态+预览） |
| frontend/src/components/workspace/CustomEdge.tsx | 自定义连线（悬停删除） |
| frontend/src/components/workspace/WorkflowCanvas.tsx | ReactFlow 画布 |
| frontend/src/components/workspace/NodeConfigPanel.tsx | 节点配置面板 |
| frontend/src/components/workspace/OperatorPanel.tsx | 算子面板 |
| frontend/src/stores/workflowStore.ts | Zustand 工作流状态 |
| frontend/src/i18n/index.tsx | 中英文国际化 |
| frontend/src/stores/themeContext.tsx | 明暗主题 |

### 测试文件
| 文件 | 说明 |
|------|------|
| backend/run_suite.py | 33 个隔离后端测试模块的标准入口，支持第一至第四周分组执行 |
| backend/tests/test_industrial_template_e2e.py | 四套工业模板真实后端 E2E |
| frontend/src/**/*.test.ts(x) | 14 个 Vitest 文件、35 个测试 |
| frontend/e2e/weld-quality.spec.ts | Playwright 焊接质量浏览器主流程 |

---

## 九、最近修复记录

| 日期 | 问题 | 修复 |
|------|------|------|
| 06-29 | MemoryError 大数据集 | DataBus 改为 JSONL 流式写入 |
| 06-29 | templates.py 中文乱码 | 字节级修复 + BOM 移除 |
| 06-29 | 模型 bytes 传递失败 | DataBus 新增 .bin 二进制存储 |
| 06-29 | 算子 io 未导入 | ml_operators.py 添加 import io |
| 06-29 | 模板 scaler 无 target_column | 4 个模板全部补充 |
| 06-29 | 连线不显示 X 删除按钮 | CustomEdge.tsx 重写 |
| 06-29 | 端口预览数据缺失 | CustomNode.tsx 添加 store 数据接入 |
| 06-29 | NodeConfigPanel 结果预览 | 移除冗余预览区域 |

---

## 十、技术特色

1. **流式数据总线**: JSONL 格式逐行读写，避免大数据集内存溢出
2. **多类型数据传递**: DataFrame(JSONL) + Bytes(.bin) + Dict(JSON) 三种格式透明切换
3. **DAG 拓扑执行**: 基于 NetworkX 的拓扑排序引擎，支持条件分支/循环/并行
4. **智能参数推荐**: 算子参数根据上游数据列名自动生成下拉选项
5. **实战机理模型**: 6 个焊接领域专用物理模型（热传导/熔核/窗口/飞溅/应力/总控）
6. **零代码操作**: 拖拽式工作流编排，完全可视化操作

---

## 十一、2026-07-13 完成状态审计

### 规模与验证证据

| 项目 | 当前结果 |
|---|---|
| 前端路由 | 23 条（22 个页面路由、1 个兜底路由） |
| FastAPI 路由 | 145 条运行时路由；140 个业务端点声明 |
| 持久化模型 | 30 个 SQLAlchemy 模型类 |
| 算子 | 80 个完整应用运行时注册算子，ID 全部唯一 |
| 后端测试 | `python run_suite.py`：46/46 隔离模块通过 |
| 前端测试 | `npm test`：14/14 文件、35/35 测试通过 |
| 前端构建 | TypeScript 与 Vite 生产构建通过 |

### 已完成并有自动化验证

- 项目、工作流、用户、数据集、运行记录等基础 API。
- 工作流发布快照、版本列表和版本恢复。
- 节点重试、等待超时、协作取消、尝试历史、有限日志和结构化错误。
- 80 个算子的严格 `OperatorContext` / `OperatorResult` 执行协议。
- Artifact（受平台管理的数据或模型文件）创建、项目范围解析、哈希和基础 Schema 推断。
- 以 `dataset_artifact_id` 为输入的训练、评估、模型保存、模型库登记和血缘展示。
- ReactFlow 基础编辑、连线删除、运行进度重置及前端生产构建。

### 部分完成

- 数据管理：单文件和主要批量上传已接入 Artifact；ZIP 和部分历史入口尚未统一。
- 工作流可靠性：Local/Celery 共用执行服务，持久投递、心跳、取消、硬超时和失联恢复可用；节点级断点续跑和周期性恢复调度未完成。
- 训练管理：基础训练闭环可用；训练任务 Celery 化、检查点、实验追踪和原子完成事务未完成。
- 知识库、标注、监控、计算资源、API 市场和智能体已有页面/API，但仍以基础 CRUD 或本地实现为主。

### 未实现或未验收

- 模型部署、灰度发布、回滚、在线推理治理和完整模型注册审批。
- 完整 RBAC、SSO、审计、企业通知、Kubernetes、Notebook、GPU 和多集群治理。
- 更广泛的浏览器 E2E、性能、安全、备份恢复、升级和 Docker 镜像验收；焊接质量主流程 E2E 已通过。

## 十二、2026-07-14 第四周交付审计

- 真实数据准备生成 1,976 行、43 列焊接特征，Fault 分布为 1,897/79。
- 四套工业模板全部通过生产 DAG/API 路径执行，并有模板级预期输出断言。
- 模板向导使用项目范围 Dataset Artifact 和语义参数，不再输入服务器路径。
- Chromium 主流程覆盖登录、项目、上传、实例化、六节点运行和 metrics，并完成重复验证。
- Windows 启动、健康、登录、停止和端口释放通过；Ubuntu 脚本语法、服务冒烟和 CI 全部通过。
- 完整验证：后端 31/31 模块、前端当前 11/11 文件 30/30 测试、生产构建、Playwright 1/1 均通过。
- Ubuntu 证据：[GitHub Actions Run 29381233328](https://github.com/FaceGg/Al-Platform/actions/runs/29381233328) 的 Ubuntu 22.04 质量门禁和 Chromium 验收成功，第四周验收完成。

### 当前风险

- 第四周能力已形成可追溯提交和 PR #1，但 PR 仍为 Draft、尚未合并到 `main`。
- 前端测试环境告警已清理；工作流参数标签、分类和端口预览双语已补齐。
- 路由懒加载后首屏依赖块均低于 500 kB；ECharts 懒加载 chunk 约 1.13 MB，后续继续按图表能力裁剪。
- WSL2 已完成 Docker Compose 生产栈与真实服务验收；备份恢复和性能压测仍按后续周次执行。

## 十三、2026-07-15 第一至第四周全模块回归

- 后端建立周次清单和覆盖自检，第一至第四周分别为 16、7、7、3 个模块。
- Windows 分周测试全部通过，统一全量入口为 33/33 模块通过。
- 前端 14/14 文件、35/35 测试通过，并新增生产模块导入和工作区端口映射回归。
- TypeScript/Vite 生产构建、npm 安全审计（0 漏洞）和 Playwright Chromium 主流程 1/1 通过。
- WSL2 前端依赖安装、测试和构建已执行；后端 32/33 模块通过，唯一环境缺口为 `/home/jingms/venv` 未安装可选 PyTorch，深度学习算子复测仍待完成。

## 十四、2026-07-17 第五周生产基础设施验收完成

- PostgreSQL 16 与 Alembic `20260715_03`、SQLite 幂等迁移、MinIO URI、Celery Worker、Redis 事件桥接和生产配置已形成闭环。
- WSL2 Docker 29.6.2 / Compose 5.3.1 完成镜像构建、自动迁移、bucket 初始化、双进程 API、非 root Worker 和四项 readiness。
- 真实生产集成 4/4 通过，覆盖跨方言重复迁移、MinIO、真实工作流、重复投递、Redis 事件、节点超时、失联/取消恢复和 readiness。
- 本地全量后端 46/46、第五周 13/13、前端 35/35、构建、Chromium 1/1、npm audit 0 漏洞和 Alembic check 均通过。
- [GitHub Actions Run 29548916619](https://github.com/FaceGg/Al-Platform/actions/runs/29548916619) 的 Windows/Ubuntu 质量、生产集成 4/4 和 Chromium 1/1 全部成功，第五周状态为“已完成”。

### 十五、2026-07-18 第六周实验训练管理验收

- Experiment/Run、MLflow adapter、指标历史、checkpoint、早停恢复、AutoML child Run 和隔离 TensorBoard Gateway 已完成。
- `/training` 已改为 Experiment/Training 双 Tab，支持 Run 比较、停止、checkpoint 恢复和平台 TensorBoard 会话，中文/英文键结构一致。
- WSL2 真实生产栈使用 MLflow 3.2.0、独立 MLflow PostgreSQL database、MinIO S3 artifact、Celery Worker 和非 root Gateway；`/api/ready` 六项全部 OK。
- 本地证据：后端全量 56/56、Week 6 10/10、前端 15/15 文件 39/39、生产构建、Alembic 双 upgrade/check、真实实验集成 1/1。
- 待远程证据：GitHub Actions 第六周生产 integration、Chromium 实验页面主流程和 npm audit 需要在最终文档提交后运行。

### 十六、2026-07-18 第七周 Pipeline 调度本地验收

- 已实现五字段 Cron、IANA 时区、持久 schedule/occurrence、唯一 occurrence 幂等、依赖和并发策略、暂停恢复、限量补录、持久指数退避、单任务 timeout、终态同步与 stale recovery。
- Celery Beat 作为独立 scheduler 服务每 60 秒发送 tick/recovery，工作流继续复用快照绑定的 `WorkflowRun` 和既有 Worker 执行器。
- 数据库 head 为 `20260718_07`；干净 SQLite 双次 upgrade/current/check 与真实 PostgreSQL 空库迁移均通过。
- 本地验证：后端全量 61/61、Week 7 5/5；WSL scheduler 镜像构建通过，依赖从 `https://mirrors.aliyun.com/pypi/simple/` 安装。
- 真实集成：PostgreSQL + Redis + Worker + Beat 运行 1/1，通过双 tick 唯一 occurrence、真实定时执行、暂停/恢复、补录和两个 occurrence completed 同步。
- 项目协作：owner/editor/operator/viewer、成员管理、joined project、集中权限、项目写审计、请求关联和脱敏已覆盖 14 个 project-write 模块。
- 角色生产验收：独立 PostgreSQL 16 空库迁移后，四角色、outsider 隐藏、success/denied 审计和原子提交 1/1 通过。
- 状态限制：第七周仅待 GitHub Actions 远程验收；全绿后关闭本周。
