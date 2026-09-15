# API 管理与应用编排统一实施计划

> 当前版本：2026-09-15  
> 执行顺序：先完成 API 管理，再完成应用编排。  
> 状态口径：`planned`、`in_progress`、`passed`、`failed`、`blocked`、`skipped`、`not_run` 分开记录，未执行不算完成。

## 1. 目标与边界

本计划将 API 管理和应用编排合并为一份唯一实施计划，避免两个独立文档产生冲突。

- **API 管理**负责 API 目录、生命周期、权限、调用测试、统计和发布来源管理。
- **应用编排**负责 DAG 规划、执行、审核、重试、取消、恢复和运行记录。
- 应用编排只有在 API 管理完成门槛通过后才开始。
- 编排完成后，才接入“已完成编排发布为 API”的集成。
- API 市场不是 DAG 编辑器；应用编排不是 API 目录。

## 2. 总体阶段

| 阶段 | 内容 | 状态 | 前置条件 |
|---|---|---|---|
| Phase A | API 管理契约、迁移、后端、前端和发布同步 | `in_progress` | 无 |
| Phase B | API 管理完整验收和发布门槛 | `planned` | Phase A |
| Phase C | 应用编排持久化和类型化 API | `planned` | Phase B |
| Phase D | 应用编排规划、DAG 校验和执行器 | `planned` | Phase C |
| Phase E | 审核、消息、恢复、前端和 API 集成 | `planned` | Phase D |
| Phase F | 两个模块联合验收和发布 | `planned` | Phase E |

当前不得把历史局部实现、文档计划或旧测试结果直接标记为本计划完成。

## 3. Phase A：API 管理实现

### A1. 契约、模型和迁移

- 固化 `PlatformAPICreate`、`PlatformAPIUpdate`、`PlatformAPIItem`、`PlatformAPIStats`。
- 支持 `source_kind=model|orchestration|custom` 和 `source_id`。
- 限制 HTTP method、API 类型和内部 `/api/...` endpoint。
- 同一 owner、来源和版本建立唯一约束。
- 完成 Alembic migration。
- 旧 SQLite 数据库通过启动兼容层补齐字段，不重建历史数据。

### A2. 后端 CRUD、权限和状态机

- 实现列表、详情、创建、编辑和删除。
- owner/editor 可写，viewer 只读，公开 API 可读不可写。
- 无项目关系资源返回隐藏式 `404`。
- 删除前检查部署或工作流引用。
- 状态只允许：
  - `draft -> published`
  - `published -> offline`
  - `offline -> published`
- 发布/下线使用显式 action，不允许普通更新绕过状态机。
- 所有失败返回稳定错误码并写审计记录。

### A3. 模型来源发布同步

- 已完成且运行中的模型部署自动创建或更新 API。
- 同一模型来源重复发布必须幂等。
- 部署停止时 API 自动下线。
- 发布失败只记录 `last_error`，不得生成虚假已发布记录。
- 应用编排来源在 Phase E 完成后接入，Phase A 不提前实现编排发布。

### A4. 前端 API 市场

- 入口固定为 `/api-marketplace`，不能访问后端根路径 `/api-marketplace`。
- 首次请求使用认证的 `apiGet("/platform/apis")`。
- 支持创建、编辑、发布、下线、删除确认、详情和筛选。
- 展示来源、schema、可见性、更新时间、调用统计和错误信息。
- 完整处理 loading、error、empty、permission 状态。
- API 测试器只调用同源内部 endpoint，自动携带 Bearer Token。
- 不支持浏览器直接代理任意外部 URL。

### A5. 工作台统计

- `PlatformAPI` 是 API 数量唯一事实来源。
- 统计按当前用户可见范围过滤。
- 删除、发布、下线后重新请求立即反映。
- 不从前端页面数组推算 API 总数。

## 4. Phase B：API 管理完成门槛

以下项目全部通过后，才能启动应用编排：

- 后端契约、CRUD、权限和状态机测试通过。
- 发布幂等、部署下线同步和错误回执测试通过。
- 工作台统计与 API 市场统计一致。
- 旧 SQLite 和 Alembic 迁移验证通过。
- 前端 API 市场组件测试和生产构建通过。
- 真实登录浏览器完成创建、发布、测试、下线、删除流程。
- API 文档和用户指南已同步。
- 当前提交 SHA 的必要证据完整。
- 任意 `failed`、`skipped`、`cancelled`、`blocked` 或 `not_run` 均保持未完成。

## 5. Phase C：应用编排基础

### C1. 持久化模型和迁移

- 增加 plan/version、node、edge、execution attempt、review、message 模型。
- 保存不可变计划快照和节点配置。
- 对 `(plan_id,node_key)`、`(node_id,attempt_no)` 建唯一约束。
- 外键删除策略不得产生孤儿节点、审核或消息。
- 重启新 Session 后计划、执行、审核和消息仍可读取。

### C2. 类型化 API 和项目权限

- 实现任务、计划、节点、消息、审核和执行命令契约。
- 支持创建、编辑、计划、运行、取消、重试、恢复和详情查询。
- owner/member/editor/viewer/outsider 按项目权限校验。
- global admin 不得隐式绕过项目资源关系。
- 非法 priority、status、project、agent 参数返回稳定 `422/403/404`。

## 6. Phase D：规划、DAG 校验和执行

### D1. 规划和 DAG

- LLM 规划结果保存 `source_kind=llm`。
- LLM 超时、无 key 或非法 JSON 时使用明确标记的 deterministic fallback。
- 校验重复节点、缺失依赖、环、孤立节点、端口类型和必填参数。
- 计划生成只创建版本化 DAG，不直接伪造节点完成。

### D2. 调度和 worker

- 无依赖节点只投递一次。
- 依赖未完成不得投递。
- 事务内幂等领取节点并创建 attempt。
- 复用现有 local/Celery dispatcher。
- 节点完成只解锁直接后继；失败正确传播。
- worker 二次校验权限和状态。

### D3. 重试、取消、超时和恢复

- 支持节点级和工作流级重试。
- 超过 `max_retries` 后计划失败。
- 取消阻止未领取节点，并向运行节点发送取消信号。
- worker 重启后恢复 queued/running attempt。
- 孤儿运行扫描、心跳和租约必须可审计。

## 7. Phase E：审核、前端和 API 集成

### E1. 持久化审核和消息

- `requires_review=true` 的节点完成后创建唯一 pending review。
- 批准只允许一次并恢复后继节点。
- 拒绝使计划进入 failed/rejected。
- 审核和消息按项目权限查询。
- 删除进程内 `pending_reviews`，改为数据库持久化。

### E2. 应用编排前端

- 任务列表、项目筛选、DAG 画布、节点配置和运行详情。
- 计划和运行按钮分离。
- 展示节点依赖、attempt、日志、错误、审核和消息。
- 支持保存草稿、发布版本、执行、取消、重试和删除确认。
- 动作按状态禁用，所有 loading/error/empty 状态可见。

### E3. 编排发布 API

- 仅已完成、可执行且无 pending review 的工作流可发布。
- 使用 `source_kind=orchestration` 和工作流版本 `source_id`。
- 同一工作流版本发布幂等。
- 工作流下线时 API 同步下线。
- 计划中、失败、取消或待审核状态不得出现在 API 市场的 published 状态。

## 8. 测试和验收批次

### API 管理

```text
backend:
python -m unittest tests.test_api_platform tests.test_api_dashboard tests.test_api_publication -v

frontend:
npm run test -- --run src/pages/APIMarketplacePage.test.tsx
npm run build

browser:
npx playwright test e2e/api-marketplace.spec.ts
```

### 应用编排

```text
backend:
python -m unittest tests.test_orchestration_api tests.test_orchestration_execution tests.test_orchestration_restart_recovery -v

frontend:
npm run test -- --run src/pages/OrchestrationPage.test.tsx
npm run build

browser:
npx playwright test e2e/orchestration.spec.ts
```

### 联合验收

- API 管理和应用编排后端全量相关测试。
- 前端测试和构建。
- 真实登录浏览器流程。
- API 发布来源绑定和权限隔离。
- 迁移、备份、恢复、错误回执和审计检查。
- 证据必须绑定当前提交 SHA。

## 9. 文件边界

API 管理：

- `backend/app/models/api_model.py`
- `backend/app/api/platform_api.py`
- `backend/app/services/api_publication.py`
- `backend/app/database_migrations.py`
- `backend/alembic/versions/*api_management*.py`
- `frontend/src/pages/APIMarketplacePage.tsx`
- `backend/tests/test_api_platform.py`
- `backend/tests/test_api_publication.py`
- `frontend/e2e/api-marketplace.spec.ts`

应用编排：

- `backend/app/models/agent.py`
- `backend/app/api/orchestration.py`
- `backend/app/engine/orchestrator.py`
- `backend/app/services/orchestration_execution.py`
- `backend/app/tasks/orchestration_tasks.py`
- `backend/alembic/versions/*agent_orchestration*.py`
- `frontend/src/pages/OrchestrationPage.tsx`
- `backend/tests/test_orchestration_execution.py`
- `backend/tests/test_orchestration_restart_recovery.py`
- `frontend/e2e/orchestration.spec.ts`

## 10. 当前状态与执行规则

- API 管理：`in_progress`，先完成现有实现的逐项验收和缺口修复。
- 应用编排：`planned`，必须等待 API 管理完成门槛。
- 通用自动建模与数据标注 Task 1–14：继续由根计划单独管理。
- 每完成一个阶段，必须同步 `DEVELOPMENT_PLAN.md`、测试证据和共享经验。
- 不得因历史提交、局部绿灯或文档完成而提前关闭阶段。
