# API 管理完成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 API 市场从“可查看/调试的列表原型”完成为受项目权限保护、可发布、可维护、可验证的 API 管理工作流，并让工作台 API 总数有明确且实时的事实来源。

**Architecture:** `PlatformAPI` 是 API 目录和调用统计的事实来源；模型部署和可执行编排工作流通过显式 publication service 创建或更新 API 记录。所有写操作在后端完成认证、资源权限、状态转换和审计，前端只消费类型化契约；API 测试默认使用同源、带认证的内部请求，不允许浏览器任意代理外部 URL。

**Tech Stack:** FastAPI、Pydantic、SQLAlchemy/Alembic、现有 `ResourceAccessService`、React、Ant Design、Axios `apiClient`、Vitest/Testing Library、Playwright。

---

## 文件边界

- 修改：`ml-platform/backend/app/models/api_model.py`，补充发布来源、状态和约束所需字段。
- 修改：`ml-platform/backend/app/api/platform_api.py`，改为 Pydantic 契约、权限校验、状态转换、统计和测试入口。
- 新建：`ml-platform/backend/app/services/api_publication.py`，集中处理模型/工作流发布与幂等更新。
- 新建：`ml-platform/backend/alembic/versions/20260828_14_api_management_completion.py`，仅包含 API 管理所需迁移。
- 修改：`ml-platform/backend/app/main.py`，如新增 publication/test router 则完成注册。
- 修改：`ml-platform/frontend/src/pages/APIMarketplacePage.tsx`，补齐创建、编辑、发布、筛选、详情、认证测试、删除确认和状态展示。
- 新建：`ml-platform/frontend/src/pages/APIMarketplacePage.test.tsx`，扩展当前路径回归为完整工作流测试。
- 修改：`ml-platform/backend/tests/test_api_platform.py`，覆盖契约、权限、状态和统计。
- 新建：`ml-platform/backend/tests/test_api_publication.py`，覆盖发布幂等性与来源绑定。
- 新建或修改：`ml-platform/frontend/e2e/api-marketplace.spec.ts`，覆盖真实登录后的页面入口和主要 mutation。
- 修改：`ml-platform/docs/api_reference.md`、`ml-platform/docs/user_guide.md`，记录访问入口、认证和 API 生命周期。

## Task 1: 固化 API 契约与迁移

- [ ] **Step 1: 先写失败的 Pydantic 契约测试**
  - 在 `test_api_platform.py` 增加：缺少 `name`、非法 HTTP method、非法 `api_type`、外部任意 endpoint、重复 version/source 的请求必须返回 `422`；响应必须包含 `id/name/api_type/status/version/source_kind/source_id`。
- [ ] **Step 2: 运行测试确认 RED**
  - `pwsh -NoProfile -Command "cd ml-platform/backend; python -m unittest tests.test_api_platform -v"`
  - 预期：新契约断言失败，现有 `dict` 请求仍接受非法字段。
- [ ] **Step 3: 增加模型和请求/响应类型**
  - `PlatformAPI` 增加 `source_kind`（`model|orchestration|custom`）、`source_id`、`published_at`、`last_error`；保留 `model_id/workflow_id` 兼容读取，写入只走统一来源字段。
  - 定义 `PlatformAPICreate`, `PlatformAPIUpdate`, `PlatformAPIItem`, `PlatformAPIStats`；`endpoint` 仅允许 `/api/...` 同源路径，`method` 使用固定枚举。
  - 创建唯一约束：同一 `owner_id + source_kind + source_id + version` 不得重复；custom API 必须显式声明 `/api` 路径。
- [ ] **Step 4: 编写 Alembic upgrade/downgrade 并运行 GREEN**
  - `pwsh -NoProfile -Command "cd ml-platform/backend; alembic upgrade head; python -m unittest tests.test_api_platform -v"`
  - 预期：迁移成功，契约测试通过；`alembic heads` 只有一个 head。
- [ ] **Step 5: 提交**
  - `git add ml-platform/backend/app/models/api_model.py ml-platform/backend/app/api/platform_api.py ml-platform/backend/alembic/versions/20260828_14_api_management_completion.py ml-platform/backend/tests/test_api_platform.py`
  - `git commit -m "feat: define platform api management contract"`

## Task 2: 权限、状态机和统计

- [ ] **Step 1: 写失败测试**
  - 覆盖 owner 可创建/更新/删除；非 owner 不能写；公开 API 可读但不可写；跨项目/无成员关系返回 `404`；状态只能 `draft -> published/offline`、`offline -> published`，失败发布只能回到 `offline`。
  - 统计必须按当前用户可见 API 去重，返回 `total_apis/published/offline/failed/total_calls`。
- [ ] **Step 2: 运行 RED**
  - `pwsh -NoProfile -Command "cd ml-platform/backend; python -m unittest tests.test_api_platform -v"`
- [ ] **Step 3: 实现后端边界**
  - 所有路由顺序固定为认证、资源解析、项目权限、业务校验、事务、审计。
  - `PUT` 只接受允许字段；发布/下线使用显式 action，不允许任意写 `status` 绕过状态机。
  - 删除前拒绝仍被运行部署或工作流引用的 API；错误使用稳定错误码。
- [ ] **Step 4: GREEN 与回归**
  - `pwsh -NoProfile -Command "cd ml-platform/backend; python -m unittest tests.test_api_platform tests.test_api_dashboard -v"`
  - 预期：API 权限/状态/统计通过，dashboard 的 API 数与删除后下降断言通过。

## Task 3: 模型与编排工作流发布

- [ ] **Step 1: 写 `test_api_publication.py` 的失败测试**
  - 模型部署完成创建 `source_kind=model` API；同一来源重复发布返回同一记录；撤销部署将 API 置为 `offline`；未完成编排工作流不得发布；完成工作流发布可重复调用。
- [ ] **Step 2: 实现 `api_publication.py`**
  - 提供 `publish_model(db, model_artifact_id, actor)`、`publish_orchestration(db, workflow_id, actor)`、`sync_publication(...)`；所有函数在同一事务中写绑定和审计，并使用数据库唯一约束保证幂等。
  - 仅接受已完成且项目权限通过的来源；生成内部 endpoint，不把用户 URL 当作代理目标。
- [ ] **Step 3: 接入部署/工作流完成事件并测试**
  - 在现有部署完成和编排完成路径调用 service；失败只记录 `last_error` 并保持来源状态，不生成“已发布”假记录。
  - `pwsh -NoProfile -Command "cd ml-platform/backend; python -m unittest tests.test_api_publication -v"`

## Task 4: 前端 API 市场完整工作流

- [ ] **Step 1: 先写失败组件测试**
  - 覆盖菜单进入 `/api-marketplace`、首次请求必须是 `apiGet("/platform/apis")`；创建/编辑提交正确 payload；发布/下线刷新列表；删除首次点击不请求、确认后只请求一次；加载失败、空列表和权限错误有可见状态；筛选不改变后端统计。
- [ ] **Step 2: 实现页面**
  - 使用 `apiClient` 的相对路径，禁止 `/api` 重复前缀。
  - 增加“新建/编辑 API”表单、状态 action、搜索、类型/状态筛选、统计摘要和统一 `DeleteConfirmation`。
  - 详情展示 source、schema、可见性、更新时间与错误；所有 loading/error/empty 文案走 i18n。
- [ ] **Step 3: 修正测试器**
  - 默认只允许选择目录中的内部 endpoint；使用 `apiClient` 或同源 `fetch` 并附带现有 Bearer token；移除硬编码 `127.0.0.1:8000`。
  - 外部 URL 不在本阶段支持；若产品必须支持，另立 SSRF-safe 后端代理设计，要求 DNS/IP 校验、allowlist、超时、响应上限和审计。
- [ ] **Step 4: GREEN/build**
  - `pwsh -NoProfile -Command "cd ml-platform/frontend; npm run test -- --run src/pages/APIMarketplacePage.test.tsx; npm run build"`

## Task 5: 端到端验收与文档

- [ ] **Step 1: 编写 Playwright 流程**
  - 已登录用户进入页面、创建 custom API、发布、测试同源 endpoint、查看统计、下线、确认删除；无权限用户无法写入他人 API。
- [ ] **Step 2: 运行浏览器与后端回归**
  - `pwsh -NoProfile -Command "cd ml-platform/frontend; npx playwright test e2e/api-marketplace.spec.ts"`
  - `pwsh -NoProfile -Command "cd ml-platform/backend; python -m unittest discover -s tests -p 'test_api*.py' -v"`
- [ ] **Step 3: 更新文档和开发记录**
  - 在 `api_reference.md` 写明前端入口与 `/api/platform/apis` 认证；在 `user_guide.md` 说明 API 市场不是后端根路径 `/api-marketplace`。
  - 更新 `DEVELOPMENT_PLAN.md` 当前状态、风险、测试证据；未完成真实登录浏览器或远端门禁时不得标记完成。
- [ ] **Step 4: 提交**
  - `git add ml-platform/frontend ml-platform/backend ml-platform/docs DEVELOPMENT_PLAN.md; git commit -m "feat: complete api marketplace workflow"`

## API 完成验收标准

- [ ] 页面可从侧边栏访问，所有请求使用正确的前端相对路径。
- [ ] 创建、编辑、发布、下线、删除、详情、同源认证测试均可用。
- [ ] API 数统计来自权限过滤后的 `PlatformAPI`，删除后重新查询立即下降；不以页面本地数组推算。
- [ ] 模型/可执行编排发布幂等且有来源绑定；未完成工作流不能发布。
- [ ] 后端权限、迁移、前端组件、真实浏览器和构建门禁全部通过；任一 skipped/failed 保持未完成。
