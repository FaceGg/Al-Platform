# Week 15 Notebook、镜像与 GPU 实施计划

> For agentic workers: execute the tasks in order, keep each checkbox independently reviewable. 本计划是 [2026-09-24 Week 13–17 计划](2026-09-24-week13-17-development.md) Task 3 的细化执行入口；设计合同见 [Week 15 技术方案](../../technical-proposals/2026-09-28-week15-notebooks-images-gpu.md)。前置：Week 13、Week 14 已通过退出门禁。

**Goal:** 交付 Notebook 会话（启动/访问/空闲回收/停止）、不可变镜像目录、GPU 资源类封闭映射；构建端点合同落地但受决策门约束（未获批 501）；kind smoke 中 GPU 用例如实 skipped。

**Architecture:** 会话 = Week 14 执行器上 `linkraft.io/role=notebook` 作业；浏览器经后端 API 反代（K8s service proxy + HMAC 短时令牌）访问 Jupyter；镜像资产以 digest 不可变登记并与 Trivy 扫描状态联动；GPU 请求必须解析到已验证容量的资源类。

**Tech Stack:** Week 13/14 全部既有设施、K8s service proxy、HMAC 令牌（复用平台 secret）、React/Vitest。

**Spec:** [Week 15 技术方案](../../technical-proposals/2026-09-28-week15-notebooks-images-gpu.md)、[Week 13–17 计划](2026-09-24-week13-17-development.md)、DEVELOPMENT_PLAN.md §4–§5。

## Global Constraints

- 状态 `planned`；Week 13/14 未收口不得开始本计划集群侧实现。
- 浏览器不接触集群凭据；代理令牌短时且随会话删除失效；镜像 digest 不可变；`scan_status=failed` 的镜像禁止引用。
- 无 Docker socket、无 DinD、无特权 builder；构建端点未获批一律 501 `IMAGE_BUILD_NOT_APPROVED`。
- GPU 无设备/无插件/无类 → 显式错误或 `skipped` 收据（带原因），永不折算 passed。
- 迁移计划名 `20260924_64_developer_resources.py`（以实现日空闲号为准）。

## File map

Create:

- `ml-platform/backend/app/models/developer_resources.py`
- `ml-platform/backend/app/schemas/developer_resources.py`
- `ml-platform/backend/app/services/notebook_service.py`
- `ml-platform/backend/app/services/image_build_service.py`（决策门 + 获批后 Kaniko 适配器）
- `ml-platform/backend/app/services/gpu_scheduler.py`
- `ml-platform/backend/app/api/notebooks.py`、`app/api/images.py`
- `ml-platform/backend/alembic/versions/20260924_64_developer_resources.py`
- `ml-platform/backend/tests/test_notebook_api.py`、`test_image_catalog_api.py`、`test_image_build_security.py`、`test_gpu_scheduling.py`
- `ml-platform/frontend/src/api/notebooks.ts`、`src/api/images.ts`、`src/pages/NotebookPage.tsx`、`src/pages/ImageCatalogPage.tsx`
- `ml-platform/frontend/src/pages/NotebookPage.test.tsx`、`src/pages/ImageCatalogPage.test.tsx`

Modify:

- `app/models/__init__.py`、`app/config.py`（`notebook_*`/`image_*`/`gpu_*` 设置）、`app/main.py`、`app/tasks/celery_app.py`（idle 扫描 beat）、Week 14 executor（新增 notebook 角色标签与代理就绪探测 helper）
- `frontend/src/App.tsx`（`/notebooks`、`/images` 路由）、`components/AppLayout.tsx`、`i18n/index.tsx`
- `tests/week_manifest.py`（新增 `15:` 键）、`frontend/src/weekAcceptance.test.ts`（第 15 周）

## Task 15.1 决策前置（Task 0 子集）

- [ ] 构建路径决策：与用户/运维确认"预构建目录基线 + Kaniko 获批增量"是否接受；未确认前按基线实现，构建端点保持 501。
- [ ] Notebook 基线镜像：smoke 时 `kind load` 一个固定 digest 的 jupyter 基础镜像并登记为平台可见。
- [ ] GPU 类清单：默认空表；有真实 NVIDIA 节点前所有 GPU 用例保持 skipped 口径。

## Task 15.2 模型与迁移（RED → 实现）

- [ ] RED：三表唯一键（session operation 唯一、image `(registry, repository, digest)` 唯一、gpu 类 `(cluster_id, name)` 唯一）；digest 形式校验；`scan_status` 枚举；空库 upgrade / downgrade / `alembic check`。
- [ ] 实现 `developer_resources.py` + 迁移 `20260924_64`。

## Task 15.3 Notebook 服务（RED → 实现）

- [ ] RED（`test_notebook_api.py`）：启动幂等（重放同会话）；镜像必须在目录且 `scan_status` 非 failed；项目/用户隔离（他人会话 404）；stop/delete 幂等且终态一次；idle 扫描（fake 时钟）只回收 `running` 且超时会话并审计；`/access` 返回短时令牌，令牌过期与会话删除后 401/404；任何响应不含集群凭据。
- [ ] 实现 `notebook_service.py`（复用 Week 14 executor + `linkraft.io/role=notebook`）与 `notebooks.py`（含 `/access` 代理端点：K8s service proxy 转发、请求体/超时上限、WS 升级）。
- [ ] scheduler beat 注册 5 分钟 idle 扫描。

## Task 15.4 镜像目录与构建门（RED → 实现）

- [ ] RED（`test_image_catalog_api.py`）：登记（digest 唯一，冲突 409）；digest 不可变（PATCH 拒绝改 digest）；可见性隔离（他项目 404）；`scan_status=failed` 的镜像被会话/构建引用时 422。
- [ ] RED（`test_image_build_security.py`）：未获批 501 `IMAGE_BUILD_NOT_APPROVED`；以设置开关模拟"获批"后，fake builder 路径断言：builder 镜像非特权、无 socket 挂载、registry 凭据仅 `env:` 引用、日志脱敏、产物 digest 回写。
- [ ] 实现 `image_build_service.py`（决策门 + 适配器接口冻结）与 `images.py`。

## Task 15.5 GPU 调度（RED → 实现）

- [ ] RED（`test_gpu_scheduling.py`）：类解析（无类/非 active 显式错误）；容量复核（快照 stale 先刷新，allocatable=0 → `GPU_CAPACITY_EXCEEDED`）；selector/tolerations 仅接受受控值；`max_per_session` 上限；无 GPU 环境探测 → skipped 语义（返回可识别标记而非伪造成功）。
- [ ] 实现 `gpu_scheduler.py`（数据源：Week 13 节点快照 + 实时复核）。

## Task 15.6 前端两页（RED → 实现）

- [ ] RED：`NotebookPage.test.tsx`（列表/启动表单限目录内镜像/GPU 类下拉容量提示/停止按钮服务端状态驱动/idle 倒计时）；`ImageCatalogPage.test.tsx`（digest 短形式/扫描徽标/登记表单/构建入口未获批不渲染或 501 文案）。
- [ ] 实现两页 + API client + 路由 + 导航 + i18n（`NOTEBOOK_*`/`IMAGE_*`/`GPU_*`）。

## Task 15.7 清单登记与聚焦门禁

- [ ] `week_manifest.py` 新增 `15: ["test_notebook_api", "test_image_catalog_api", "test_image_build_security", "test_gpu_scheduling"]`；`weekAcceptance.test.ts` 第 15 周。
- [ ] 聚焦门禁（模式同 Week 13/14 计划，替换 `--week 15` 与新文件名）：pytest 四模块 → `run_suite.py --week 15` → compileall → alembic → 前端三件套 → `git diff --check`。

## Task 15.8 kind/WSL smoke 与证据

- [ ] 预载 jupyter 基线镜像（登记 digest）→ 启动会话 → 代理访问 200（含 WS 握手）→ 空闲扫描（缩短阈值实测）→ stop 回收（集群资源消失）。
- [ ] 镜像登记 → 会话引用成功；登记 `scan_status=failed` 镜像 → 引用被拒。
- [ ] GPU：确认集群无 NVIDIA 节点 → GPU 相关 smoke 记 **skipped（原因：无 NVIDIA 设备插件/节点）**，不折算 passed。
- [ ] 证据写入 `temp_test/week15-local/`，绑定当前 SHA；Playwright：启动 → 打开 → 停止、镜像登记。

## Task 15.9 台账收口

- [ ] 先更新 DEVELOPMENT_PLAN.md，再归档详细记录；构建决策门状态、GPU skipped 口径如实记录，Week 15 保持 `in_progress` 直至门禁全绿。

## Exit gate

- 会话与构建复用同一执行器；镜像与 registry 凭据永不回显；GPU 请求仅调度到已验证容量；构建端点决策门行为正确（未获批 501）；非 GPU 环境 skipped 收据；聚焦测试/迁移/前端门禁通过；证据绑定当前 SHA。

## Explicit exclusions

- 不做 JupyterHub 平台化、跨集群会话（Week 16）、数据探索（Week 17）；不引入 DinD/socket/特权构建；不在无 GPU 环境伪造通过；不以 mock 宣称构建闭环完成。
