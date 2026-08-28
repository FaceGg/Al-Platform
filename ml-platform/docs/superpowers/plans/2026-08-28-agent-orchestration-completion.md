# 应用编排完成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将应用编排从“任务列表 + 硬编码规划 + 内存审核”完成为可持久化、可执行、可恢复、可审核的多智能体 DAG 工作流。

**Architecture:** `AgentTask` 作为工作流节点，新增不可变的 plan/version、dependency edge、execution attempt、review 和 message 持久化记录。计划生成只产生版本化 DAG；调度器依据依赖和状态投递现有 Celery/local dispatcher，worker 负责幂等领取与状态写回；人工审核是持久化 gate，重启后仍可恢复。项目权限仍由 owner/member 解析，global admin 不隐式绕过项目成员权限。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy/Alembic、现有 Celery/Redis 与 `TaskDispatcher`、React/Ant Design、Vitest、Python unittest、Playwright。

---

## 文件边界

- 修改：`ml-platform/backend/app/models/agent.py`，增加 plan/node/edge/attempt/review 状态模型。
- 新建：`ml-platform/backend/alembic/versions/20260828_15_agent_orchestration_execution.py`。
- 修改：`ml-platform/backend/app/api/orchestration.py`，类型化请求、项目权限、状态转换和执行命令。
- 修改：`ml-platform/backend/app/engine/orchestrator.py`，真实 LLM adapter、确定性 fallback 标记、DAG 计划和调度接口。
- 新建：`ml-platform/backend/app/services/orchestration_execution.py`，依赖调度、幂等领取、重试、取消和恢复。
- 新建：`ml-platform/backend/app/tasks/orchestration_tasks.py`，Celery worker 入口。
- 修改：`ml-platform/backend/app/main.py`，注册新增 router/task import。
- 修改：`ml-platform/frontend/src/pages/OrchestrationPage.tsx`，补齐创建、计划、执行、取消、重试、详情、消息和审核。
- 修改：`ml-platform/frontend/src/pages/OrchestrationPage.test.tsx`，从列表测试扩展为工作流测试。
- 新建：`ml-platform/backend/tests/test_orchestration_execution.py`、`test_orchestration_restart_recovery.py`。
- 修改：`ml-platform/backend/tests/test_orchestration_api.py`（若现有文件名不同，以实际测试文件为准）。
- 新建：`ml-platform/frontend/e2e/orchestration.spec.ts`。
- 修改：`ml-platform/docs/api_reference.md`、`ml-platform/docs/user_guide.md`、`DEVELOPMENT_PLAN.md`。

## Task 1: 持久化计划和执行状态

- [ ] **Step 1: 写 RED 测试**
  - 创建任务后 `requires_review` 必须持久化；计划生成后重读任务仍有 plan version 和节点；重启新 Session 后 review/message/attempt 仍存在。
  - 非法状态跳转（`completed -> running`、`cancelled -> queued`）必须返回稳定错误码。
- [ ] **Step 2: 增加模型与迁移**
  - `AgentPlan(id, task_id, version, source_kind, source_text, status, created_by_id)`；`AgentTaskNode(plan_id, task_id, node_key, name, description, agent_type, status, input_data, output_data, assigned_agent_id)`；`AgentTaskEdge(plan_id, from_node_id, to_node_id)`；`AgentExecutionAttempt(node_id, attempt_no, status, celery_task_id, error_message, started_at, finished_at)`；`AgentReview(task_id, node_id, status, decision, comment, reviewer_id, decided_at)`。
  - 对 `(plan_id,node_key)`、`(node_id,attempt_no)` 建唯一约束；外键删除策略必须避免孤儿消息和审核记录。
- [ ] **Step 3: 运行迁移与 RED/GREEN**
  - `pwsh -NoProfile -Command "cd ml-platform/backend; alembic upgrade head; python -m unittest tests.test_orchestration_execution -v"`
  - 预期：先因模型/API 尚未接入失败，再在最小实现后通过；`alembic heads` 单 head。

## Task 2: 类型化 API 和项目权限

- [ ] **Step 1: 写权限/契约测试**
  - owner/member viewer/editor/outsider 表驱动覆盖任务、计划、节点、消息、审核；global admin outsider 不能因全局 role 访问无项目关系资源。
  - 创建任务缺 `project_id`、无权限 agent、非法 priority/status 返回 `422/403/404`。
- [ ] **Step 2: 替换 `dict` body**
  - 定义 `AgentTaskCreate/Update`, `PlanRequest`, `ReviewRequest`, `MessageCreate`, `TaskCommandResponse`；所有响应显式返回 `project_id/project_name/created_by_name/plan_id`。
  - `_task_for_user` 统一调用项目访问服务；列表省略 `project_id` 返回全部可访问项目任务，传入时只做权限过滤。
- [ ] **Step 3: GREEN**
  - `pwsh -NoProfile -Command "cd ml-platform/backend; python -m unittest tests.test_orchestration_api -v"`

## Task 3: 真正的规划与 DAG 校验

- [ ] **Step 1: 写规划 RED 测试**
  - mock LLM 返回合法 JSON 时保存 `source_kind=llm`；超时/非法 JSON 时保存 `source_kind=deterministic_fallback` 和错误原因；节点 key、依赖、环、重复节点必须被拒绝。
- [ ] **Step 2: 实现 `orchestrator.py`**
  - 抽取 `LLMPlanner` adapter，使用配置的 URL/key/timeout；禁止无 key 时伪装成功。
  - `validate_dag(nodes)` 使用拓扑排序检测环和不存在依赖；fallback 仍可用但在 UI/API 明确标记为确定性规划。
  - 规划接口只创建 plan/version 和节点，不直接把节点标记 completed。
- [ ] **Step 3: GREEN**
  - `pwsh -NoProfile -Command "cd ml-platform/backend; python -m unittest tests.test_orchestration_execution -k plan -v"`

## Task 4: 调度、执行、重试、取消和恢复

- [ ] **Step 1: 先写 worker/service RED 测试**
  - 无依赖节点可投递一次；依赖未完成不投递；重复调用不重复创建 attempt；失败按 `max_retries` 重试，超过上限标记 plan failed；取消阻止未领取节点并向运行节点发取消信号；服务重启后可从 queued/running attempt 恢复。
- [ ] **Step 2: 实现 `orchestration_execution.py` 与 Celery task**
  - 事务内使用 `SELECT ... FOR UPDATE`（SQLite 用等价锁保护）领取节点，创建 attempt 后再投递 dispatcher；worker 二次校验权限和状态。
  - 节点完成后只解锁其直接后继；失败传播到依赖节点；取消和恢复写审计事件。
  - 复用现有 `LocalTaskDispatcher/CeleryTaskDispatcher`，不另造 broker 协议。
- [ ] **Step 3: 实现命令 API**
  - `POST /api/orchestration/tasks/{id}/plan`、`/run`、`/cancel`、`/retry`；命令返回 `accepted` 与 plan/node 状态，不谎称执行已完成。
- [ ] **Step 4: GREEN**
  - `pwsh -NoProfile -Command "cd ml-platform/backend; python -m unittest tests.test_orchestration_execution tests.test_orchestration_restart_recovery -v"`

## Task 5: 持久化人工审核和消息

- [ ] **Step 1: 写审核 RED 测试**
  - `requires_review=true` 的节点完成后创建唯一 pending review；批准只允许一次并恢复后继节点；拒绝使 plan failed/rejected；重启后待审核列表按项目权限返回；消息发送和查询只允许任务可见成员。
- [ ] **Step 2: 替换内存 `pending_reviews`**
  - `Orchestrator.request_human_review` 改为写 `AgentReview`；审核提交在事务中更新 review、node、plan 并触发调度；删除进程内 dict。
- [ ] **Step 3: GREEN**
  - `pwsh -NoProfile -Command "cd ml-platform/backend; python -m unittest tests.test_orchestration_execution -k review -v"`

## Task 6: 前端完整工作流与文案

- [ ] **Step 1: 写组件 RED 测试**
  - 创建任务保存项目和 `requires_review`；计划显示 source kind、版本、节点依赖；运行/取消/重试调用正确命令；审核通过/拒绝刷新；消息可发送；删除首次点击不请求；所有“取消/待审核?”误用标签改为正确中文/英文。
- [ ] **Step 2: 实现页面**
  - 任务列表保留全部项目筛选；详情使用节点 DAG、attempt、错误、审核和消息 tabs；动作按状态禁用并显示 tooltip；所有删除复用 `DeleteConfirmation`。
  - 计划按钮与运行按钮分离：计划只生成/预览，运行才投递；loading/error/empty 状态可见。
- [ ] **Step 3: GREEN/build**
  - `pwsh -NoProfile -Command "cd ml-platform/frontend; npm run test -- --run src/pages/OrchestrationPage.test.tsx; npm run build"`

## Task 7: 真实浏览器、发布集成和文档

- [ ] **Step 1: 编写 Playwright**
  - 登录用户创建项目任务、规划、查看 DAG、运行、审核、发送消息、取消/重试并刷新页面；验证服务重启后状态和审核仍可见；outsider 得到 404/403。
- [ ] **Step 2: 运行回归**
  - `pwsh -NoProfile -Command "cd ml-platform/frontend; npx playwright test e2e/orchestration.spec.ts"`
  - `pwsh -NoProfile -Command "cd ml-platform/backend; python -m unittest discover -s tests -p '*orchestration*.py' -v"`
- [ ] **Step 3: 仅在可执行稳定后发布 API**
  - 调用 API publication service 发布 completed plan；计划中、失败、取消或存在 pending review 的任务不得出现在 API 市场的 published 状态。
- [ ] **Step 4: 更新文档和开发记录**
  - 明确“应用编排”负责 DAG 规划/执行/审核；“API 市场”负责已发布能力的目录与调用，不是任务编排入口。
  - 更新 `DEVELOPMENT_PLAN.md` 和共享经验；任何未执行的浏览器/远端门禁保持 `open`。

## 编排完成验收标准

- [ ] 计划、节点、依赖、attempt、消息和审核均持久化，重启不丢失。
- [ ] LLM 规划和确定性 fallback 可区分；DAG 环检测和状态转换 fail closed。
- [ ] 真实 worker 能执行可运行节点，支持依赖、重试、取消、失败传播和恢复。
- [ ] 前端能创建、规划、运行、审核、发消息、查看详情、取消、重试和删除。
- [ ] 项目权限、审计、迁移、后端/worker/前端/E2E/build 全部通过；任何 skipped/failed 不算完成。
