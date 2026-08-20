# AutoML 模型结果注册 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让自动建模任务的每个成功模型结果都能通过行内“注册”按钮，幂等地注册到任务所属项目的“注册模型”列表。

**Architecture:** AutoML 执行器为每个成功算法族保存独立可信 `joblib` 制品和内部 `ModelLibrary` 来源，并把来源 ID写入结果行。模型注册 API 新增项目/任务/算法范围的原子操作，在同一审计事务中创建 `RegisteredModel`、首个 `ModelVersion`、模型卡并回写任务结果；前端只提交任务 ID 和算法 ID，并维护行级 loading/已注册状态。

**Tech Stack:** FastAPI、SQLAlchemy、scikit-learn/joblib、现有 ArtifactService/ModelRegistryService、React 18、TypeScript、Ant Design、Vitest、Testing Library。

---

### Task 1: 为每个 AutoML 成功结果保存独立模型来源

**Files:**
- Modify: `ml-platform/backend/app/services/automl_execution.py`
- Test: `ml-platform/backend/tests/test_automl_tracking.py`

- [ ] **Step 1: 添加失败测试**

扩展 Optuna 执行测试，使两个成功算法族完成后断言：

```python
algorithm_results = job.metrics["algorithm_results"]
all_results = job.metrics["all_results"]
self.assertTrue(all(item.get("model_library_id") for item in algorithm_results if item["status"] == "completed"))
self.assertTrue(all(item.get("model_library_id") for item in all_results))
self.assertEqual(self.db.query(ModelLibrary).filter_by(training_job_id=job.id).count(), 2)
self.assertEqual(str(job.model_library_id), job.metrics["best_model"]["model_library_id"])
```

- [ ] **Step 2: 运行测试确认旧实现失败**

运行：

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_tracking -v
```

预期：新增断言失败，因为旧实现只保存最佳模型且结果行没有 `model_library_id`。

- [ ] **Step 3: 实现每个结果的制品和内部模型记录**

在全部算法族搜索结束后遍历成功结果，为每个 `best_estimator` 保存包含模型、特征 Schema 和目标 Schema 的独立 `joblib`；创建 `ModelLibrary` 时写入该算法的 framework、backbone、AUC/F1、最佳参数、训练任务、数据集和模型制品。使用 `algorithm_id` 建立映射，并将 `model_library_id` 合并进 `_family_summary`、`all_results` 与 `best_model`；最佳结果继续赋值给 `job.model_library_id`、`job.model_artifact_id` 和 `job.model_path`。

- [ ] **Step 4: 运行聚焦测试**

运行同一 unittest 命令，预期全部通过，并确认测试临时存储中产生两个不同模型制品。

### Task 2: 新增幂等的原子注册接口

**Files:**
- Modify: `ml-platform/backend/app/api/model_registry.py`
- Modify: `ml-platform/backend/app/services/model_registry.py`
- Test: `ml-platform/backend/tests/test_api_model_registry.py`
- Test: `ml-platform/backend/tests/test_model_registry_service.py`

- [ ] **Step 1: 添加 API 和服务失败测试**

构造已完成 AutoML `TrainingJob`、对应 `ModelLibrary`/Artifact 和含 `model_library_id` 的算法结果，覆盖：

```python
response = client.post(
    f"/api/projects/{project_id}/automl-jobs/{job_id}/results/random_forest/register"
)
self.assertEqual(response.status_code, 201)
self.assertTrue(response.json()["created"])
self.assertEqual(response.json()["registered_model"]["name"], "任务名称 - 随机森林")
```

再次调用断言 `200`、`created=false`、模型/版本数量不增加；另测 operator 403、outsider 404、跨项目 404、失败/缺失结果 409 或 422，以及转换失败后无空注册模型和无孤立 ONNX 制品。

- [ ] **Step 2: 运行测试确认接口不存在**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_model_registry_service tests.test_api_model_registry -v
```

预期：新接口测试返回 404 或服务方法不存在。

- [ ] **Step 3: 实现服务级幂等查询和结果状态回写**

在 `ModelRegistryService` 增加按 `source_model_library_id` 查询已有 `ModelVersion` 的方法，以及把 `registered_model_id`/`model_version_id` 合并到 `algorithm_results`、`all_results`、`best_model` 对应 `algorithm_id` 行的结构化更新方法。幂等键使用源模型库 ID，不使用名称。

- [ ] **Step 4: 实现原子 API**

新增：

```text
POST /api/projects/{project_id}/automl-jobs/{job_id}/results/{algorithm_id}/register
```

接口在 `model.register` 审计事务中校验项目、任务、完成状态、结果状态和源模型归属；已有版本直接返回 `200 created=false`，否则创建默认名称的注册模型并调用 `register_platform_version(..., commit=False)`，回写任务结果后统一提交。捕获转换/制品错误时回滚并调用 `compensate_version_artifact`。

- [ ] **Step 5: 运行后端聚焦测试**

运行 Task 2 的 unittest 命令，预期全部通过。

### Task 3: 增加前端 API 与模型结果注册交互

**Files:**
- Modify: `ml-platform/frontend/src/api/modelRegistry.ts`
- Modify: `ml-platform/frontend/src/api/modelRegistry.test.ts`
- Modify: `ml-platform/frontend/src/pages/AutoMLTaskPage.tsx`
- Create: `ml-platform/frontend/src/pages/AutoMLTaskPage.test.tsx`
- Modify: `ml-platform/frontend/src/weekAcceptance.test.ts`

- [ ] **Step 1: 添加前端失败测试**

API 测试断言：

```typescript
await registerAutoMLResult("project-1", "job-1", "random_forest");
expect(post).toHaveBeenCalledWith(
  "/projects/project-1/automl-jobs/job-1/results/random_forest/register",
);
```

页面测试加载含两个 `model_library_id` 的成功结果，断言每行“详细”后有“注册”；点击随机森林注册后只该行进入 loading，成功后显示“已注册”；刷新数据中已有 `registered_model_id` 时初始即显示“已注册”；失败或无来源 ID 行按钮禁用。

- [ ] **Step 2: 运行测试确认旧页面失败**

```powershell
npm test -- --run src/api/modelRegistry.test.ts src/pages/AutoMLTaskPage.test.tsx
```

预期：API 函数和注册按钮不存在。

- [ ] **Step 3: 实现前端 API**

在 `modelRegistry.ts` 增加响应类型与 `registerAutoMLResult(projectId, jobId, algorithmId)`，调用新的项目范围 POST 接口。

- [ ] **Step 4: 实现行级注册状态**

在 `AutoMLTaskPage`：

- 从任务 `project_id`、结果 `algorithm_id`、`model_library_id` 和 `registered_model_id` 推导可注册/已注册状态。
- 使用 `registeringAlgorithmId` 只锁定当前行。
- 操作列使用 `<Space>`，顺序为“详细”“注册/已注册”。
- 首次创建提示“模型已注册到当前项目”，幂等返回提示“该模型已注册”，失败使用 `formatApiError`。
- 成功后同时更新当前 `job.metrics` 中对应结果行，确保无需重新请求即可显示“已注册”。

- [ ] **Step 5: 注册测试清单并运行聚焦测试**

将新测试文件只加入 `weekAcceptance.test.ts` 的一个周次，然后运行 Task 3 测试命令，预期全部通过。

### Task 4: 完整验证与项目记录

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: 运行后端验证**

```powershell
C:\Users\17723\miniconda3\python.exe -m unittest tests.test_automl_tracking tests.test_model_registry_service tests.test_api_model_registry -v
C:\Users\17723\miniconda3\python.exe -m compileall -q app tests
```

- [ ] **Step 2: 运行前端验证**

```powershell
npm test -- --run src/api/modelRegistry.test.ts src/pages/AutoMLTaskPage.test.tsx src/weekAcceptance.test.ts
npm run build
```

- [ ] **Step 3: 检查差异和真实页面**

在仓库根目录运行 `git diff --check`；启动前后端或复用当前开发服务，登录后检查任务结果按钮顺序、行级 loading、注册成功状态及模型库对应项目的注册模型列表。

- [ ] **Step 4: 同步历史记录**

在 `DEVELOPMENT_PLAN.md` 末尾记录实现、测试、未验证的真实 ONNX 转换/浏览器边界；在共享经验文档末尾追加多结果制品、幂等注册、事务补偿和前端行级状态的可复用经验。保留当前工作区所有无关修改。
