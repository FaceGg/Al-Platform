# 多模态标注平台集成（Label Studio）实施计划（决策门控）

> For agentic workers: **本轨道已暂缓（`deferred`，2026-09-28 决策评审）**——D1 未立项，Task 1+ 不执行；D2–D8 结论已归档（[技术方案 §10](../../technical-proposals/2026-09-28-label-studio-integration.md)），重新立项需用户明确指示。本计划是独立立项的执行入口，不属于 Week 13–17 计划。

**Goal:** 以深度集成模式交付多模态标注：平台侧绑定/导出/回流三套合同 + 网关跳转，标注员单点登录 LS 完成标注，结果经现有回传/验收状态机回流；表格标注门户零改动。

**Architecture:** 平台新增 `annotation-sync` 域（绑定/导出批/回流记录 + Celery 同步任务）；LS 部署为内网有状态服务（复用 PostgreSQL/Redis/MinIO），浏览器经门户网关访问；schema 翻译按 `LabelSchema.version` 生成并归档不可变 config。

**Tech Stack:** 既有门户网关模式、Celery/Redis、ArtifactService/MinIO、Label Studio（Apache-2.0，digest 锁定）、React/Vitest；部署形态随 Task 0 D3 决策（K8s 或 compose）。

**Spec:** [Label Studio 集成技术方案](../../technical-proposals/2026-09-28-label-studio-integration.md)、DEVELOPMENT_PLAN.md §4–§5。

## Global Constraints

- 状态 `deferred`（2026-09-28 用户暂缓）：不得自行启动；D2–D8 结论见技术方案 §10，重新立项时直接生效。
- 平台是唯一业务真相源：LS 完成 ≠ 回传；回流唯一入口 = 现有回传状态机；不做自动验收。
- 凭据（LS API token）只以 `env:`/`file:` 引用；LS 仅内网可达；不做 iframe。
- 表格标注门户零行为变更；新增测试模块登记唯一周次（`week_manifest.py` 新增独立键 `20:`，不占用 Week 13–17 键）。
- 迁移以实现日空闲修订号为准；不改 `labeling.py` 既有表。

## File map（获批后生效）

Create:

- `ml-platform/backend/app/models/annotation_sync.py`
- `ml-platform/backend/app/schemas/annotation_sync.py`
- `ml-platform/backend/app/services/label_studio_client.py`（含 Fake 适配器，模式同 `kubernetes_client.py`）
- `ml-platform/backend/app/services/annotation_sync.py`（导出/回流/schema 翻译）
- `ml-platform/backend/app/api/annotation_sync.py`
- `ml-platform/backend/alembic/versions/<空闲号>_annotation_sync.py`
- `ml-platform/backend/tests/test_annotation_sync_api.py`、`test_annotation_sync_contracts.py`
- `ml-platform/frontend/src/api/annotationSync.ts`、`src/pages/AnnotationSyncPage.tsx`、`src/pages/AnnotationSyncPage.test.tsx`
- 网关侧：`ml-platform/annotator/backend/app/api/label_studio.py`（LS 跳转/代理路由）

Modify:

- `app/models/__init__.py`、`app/config.py`（`label_studio_*` 设置）、`app/main.py`、`app/tasks/celery_app.py`（同步轮询 beat）
- 标注员门户前端任务卡（模态路由入口）、主平台任务列表（模态徽标）、`i18n`
- `tests/week_manifest.py`（新增 `20:` 键）、`frontend/src/weekAcceptance.test.ts`
- `docker-compose.yml` / K8s manifests（D3 决策后）：LS + 独立 database

## Task 0 决策清单——已收口（2026-09-28：D1 暂缓）

- [x] D1 立项与首期模态：**暂缓，不立项**（用户决定）→ 轨道转 `deferred`，Task 1+ 不执行。
- [x] D2 集成模式：B 深度集成（证据收口，条件生效）。
- [x] D3 部署形态：先 compose 落地，后续随 Week 13–15 迁移（用户确认，条件生效）。
- [x] D4 表格标注不迁移（证据收口，条件生效）。
- [x] D5 身份模式：provisioning + 网关单点登录（证据收口，条件生效）。
- [x] D6 回流策略：LS 完成不自动回传（证据收口，条件生效）。
- [x] D7 存储访问：StorageBinding 优先、就绪前 presigned（证据收口，条件生效）。
- [x] D8 运维承诺：完整接受（用户确认，条件生效）。
- [x] 记录归档：DEVELOPMENT_PLAN.md §4.3 + 技术方案 §10；结论 `deferred`，重新立项需用户明确指示。

Verification: 台账 §4.3 与技术方案 §10 记录一致；重新激活时 D2–D8 结论直接生效，无需重做决策评审（除非届时条件变化）。

## Task 1 模型与迁移（RED → 实现）

- [ ] RED：`label_studio_bindings` 唯一键（project 1:1）、凭据引用格式校验；`annotation_sync_exports` 幂等键唯一；`annotation_sync_returns` completion ↔ 样本唯一；空库 upgrade / downgrade / `alembic check`。
- [ ] 实现模型 + 迁移；`week_manifest.py` 注册。

## Task 2 LS 客户端与 schema 翻译（RED → 实现）

- [ ] RED（`test_annotation_sync_contracts.py`）：Fake LS 客户端协议（projects/tasks/completions/健康检查）；token 引用解析、异常映射脱敏；schema 翻译器输出按 `LabelSchema.version` 归档不可变 config，同版本重生成逐字节一致；enum/number/text 映射覆盖 `LabelColumn` 全字段。
- [ ] 实现 `label_studio_client.py` + 翻译器。

## Task 3 导出与回流（RED → 实现）

- [ ] RED：导出批幂等（重放同任务集）、有界（超限拒绝）、project 隔离（跨项目 404）、样本经 presigned/StorageBinding 引用不复制数据；回流聚合按标注员主体 → 创建 `AnnotationReturnBatch`（幂等键 = export + completion 版本）、走现有验收状态机、部分完成策略、冲突标记；"LS 完成不自动回传"断言（回流只生成待确认批次）。
- [ ] 实现 `annotation_sync.py` 服务 + Celery 轮询/导出任务。

## Task 4 API 与网关（RED → 实现）

- [ ] RED（`test_annotation_sync_api.py`）：绑定 CRUD 权限矩阵（`resource.*`）、导出/对账端点幂等与审计、健康检查复用连通性合同、`SYNC_*` 错误码、X-Request-ID；网关 LS 跳转路由的会话校验与 404 隐藏语义。
- [ ] 实现 `annotation_sync.py` API + 网关 `label_studio.py` + `config.py` 设置。

## Task 5 前端（RED → 实现）

- [ ] RED：`AnnotationSyncPage.test.tsx`（绑定表、导出批状态、回流失败明细、手动对账）；门户任务卡模态路由（多模态任务经网关跳转、表格任务不受影响断言）。
- [ ] 实现页面 + API client + 主平台/门户入口 + i18n。

## Task 6 部署与 smoke（D3 决策后）

- [ ] compose（或 K8s）落 LS 服务：digest 锁定镜像、独立 database、Redis 复用、仅内网绑定；备份/恢复脚本覆盖 LS 库。
- [ ] 端到端 smoke：平台建项目/多模态任务 → 导出批 → 标注员网关跳转 LS 完成标注 → 平台回流生成待回传批次 → 标注员回传 → 管理员验收 → 导出数据版本；中途注入 LS 不可达（同步显式失败不阻塞平台）；重放导出与回流验证幂等。
- [ ] 证据写入 `temp_test/ls-integration-local/`，绑定当前 SHA；已认证 Playwright：跳转标注 → 回传 → 验收。

## Task 7 台账收口

- [ ] 先更新 DEVELOPMENT_PLAN.md（状态、SHA、测试数字、未验证范围），再归档详细记录；保持 `in_progress` 直至门禁全绿。

## Exit gate

- 导出/回流幂等且项目隔离；回流必经回传/验收状态机且"完成≠回传"；表格门户零回归；LS 凭据零落库、仅内网；smoke 与 Playwright 全绿；证据绑定当前 SHA。

## Explicit exclusions

- 不迁移表格标注；不做 iframe/自动回传/自动验收/训练数据自动回流；不引入 CVAT；未获批不执行 Task 1+；不以 mock 或本文档宣称完成。
