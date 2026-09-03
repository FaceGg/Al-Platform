# 多标签自动建模、数据标注与标注员门户实施计划

> **历史归档：** 本计划已被 `2026-09-02-general-automl-annotation-platform.md` 取代，仅保留用于追溯，禁止作为当前实施依据。其“共享认证”和“可删除其他兜底”等边界已被 2026-09-02 评审通过的通用平台方案否定。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目整体收敛为通用自动建模和通用数据标注，并交付多标签/多输出建模、标签化标注策略、独立标注员门户、任务指派和可复现模型导出推理。

**Architecture:** 先将现有行业专用模型、字段、路由、服务和页面迁移为通用任务合同，再以任务类型、标签 schema、assignment、输入契约和导出 manifest 为稳定边界。长任务继续使用现有持久化 worker，主工作台与独立 annotator 入口共享认证和 API 类型。

**Tech Stack:** FastAPI/Pydantic/SQLAlchemy/Alembic、Artifact Storage、scikit-learn、joblib/ONNX、React/TypeScript/Ant Design、Vitest、Playwright。

**Spec:** `ml-platform/docs/superpowers/specs/2026-08-31-multilabel-annotation-annotator-portal-design.md`

## Global Constraints

- 旧 `target_column` 仅作为迁移输入，必须转换为单元素 `target_columns`；新代码不得继续扩展行业专用合同。
- 标签写入必须经过服务端 schema、任务状态和权限校验。
- 导出推理必须校验完整 `input_contract`，不能只校验列名存在。
- required 验收失败或跳过不得关闭任务。
- 数据库结构变更必须有 Alembic 幂等迁移。

## 文件边界

- Modify: `ml-platform/backend/app/models/training.py`, `model_library.py`, `user.py`；迁移并最终移除行业专用模型文件
- Create/Modify: `ml-platform/backend/app/models/labeling_v2.py`, `assignment.py`, `model_export.py`, `app/schemas/*`, `app/services/label_schema.py`, `annotation_strategies.py`, `model_export.py`, `input_contract.py`
- Modify: `ml-platform/backend/app/api/training.py`, `labeling.py`, `annotations.py`, `model_library.py`, `auth.py`
- Create: Alembic migrations under `ml-platform/backend/alembic/versions/20260831_*.py`
- Modify/Create: `ml-platform/frontend/src/pages/AutoMLPage.tsx`, `DataAnnotationPage.tsx`, `ModelLibraryPage.tsx`, `src/api/*`, `src/annotator/*`, `annotator.html` or equivalent Vite entry
- Test: existing related backend/frontend tests; new test modules must be added to the registered week manifest
- Update: `ml-platform/docs/api_reference.md`, `ml-platform/docs/user_guide.md`, `DEVELOPMENT_PLAN.md`

### Task 0: 全项目去行业化迁移

盘点并迁移以下现有行业专用边界：

- 后端 `ml-platform/backend/app/api/spot_weld_quality.py`、`app/services/spot_weld_quality.py`、`app/models/spot_weld_quality.py` 及其相关 API/模型测试。
- 前端 `src/pages/DataAnnotationPage.tsx`、`src/pages/AnnotationPage.tsx`、`src/components/AnnotationCanvas.tsx`、`src/api/spotWeldQuality.ts` 及对应测试、路由、菜单和国际化文案。
- 数据库表、Alembic 迁移、artifact 元数据、worker 分发逻辑、导出逻辑和用户文档中的行业专用字段、URL、错误码和固定列名。

先新增通用 `modeling`/`labeling` API、模型和服务边界，再将历史数据转换为通用任务合同；旧行业 URL 只保留明确的迁移期弃用/重定向响应，不能继续承载新业务。删除或隔离行业专用入口，确保新功能不依赖行业列名、固定特征、专用规则或行业报告。先写专用引用清单和路由/API 回归测试，再逐模块迁移，最后用 `rg` 扫描源码、迁移、测试和文档，确认没有新增行业依赖。

### Task 1: 合同与迁移基线

交付四种 `task_type`、`target_columns`、`label_schema`、`input_contract`、assignment 和 export manifest 的 Pydantic/SQLAlchemy/Alembic 合同。先写并运行 RED 测试，再实现模型、索引、审计时间和乐观版本字段；从旧 JSON/字段回填兼容数据；完成 upgrade/downgrade 与序列化回归。

### Task 2: AutoML 多标签与多输出

为目标列数组、multilabel matrix 编码、多输出回归、按目标指标和聚合指标编写 RED 测试。扩展 AutoML 表单和 API，增加 estimator capability 检查、目标编码/解码、指标持久化、输入契约保存；确保取消、重试、恢复不会注册未完成结果。通过后端 AutoML、前端页面、构建和迁移回归。

### Task 3: 统一标签模型

为标签 CRUD、单标签兼容、多标签增删、confidence/source、修订历史编写 RED 测试。新增项目/任务标签集和版本快照；更新手动标注 API、`AnnotationCanvas`、`DataAnnotationPage`、自动结果持久化和导出，使模型标签与最终标签分离保存。通过 API、页面和导出回归。

### Task 4: 簇/规则/簇+规则自动标注

为三种策略互斥校验、指定单簇/多簇选择、按簇标签映射、“其他”兜底簇、规则匹配、多列标签、组合策略优先级、不完整映射和类型错误编写服务测试。定义 typed rule DSL 并服务端编译校验，禁止执行客户端字符串；实现策略管线并返回 `cluster_id`、命中规则、最终多列标签和解释信息；提供只读预览接口。前端增加唯一策略选择器：

- `cluster`：聚类后选择一个或多个簇，为指定簇配置一列或多列标签，默认生成可删除/可编辑的“其他”兜底簇，覆盖未选择或未配置标签的簇。
- `rule`：复用现有规则编辑器，但每条规则可配置多列标签；规则未命中时沿用现有 fallback 语义。
- `cluster_rule`：同时配置簇选择/标签和规则标签，保存明确的优先级并在预览中展示最终来源。

开始自动标注前校验只能选择一种策略、指定簇必须有映射、标签列和值符合 schema。通过 worker 重启测试与 API/UI 聚焦测试。

### Task 5: 标注员认证、独立门户与指派

为 annotator 注册/登录、assignment 可见性、管理员操作拒绝、assignment 过期/撤销和并发提交编写 RED 测试。复用现有认证新增 `annotator` 角色和审计；提供管理员分配/取消分配/批量分配/截止时间/工作量 API，指派接口支持一次选择多个标注员。新增独立前端、独立后端和独立登录态，默认使用可配置的 `8443` 端口，包含登录注册、任务队列、样本工作区、进度和提交/跳过。并发写入采用乐观修订校验和显式最后成功写入，过期修订必须先冲突确认。手动或自动任务创建/执行完成后，前端不得自动跳转到标注详情页；任务列表和结果区域必须提供“预览”和“指派标注员”操作。Playwright 覆盖管理员多选指派后 annotator 登录及越权访问。

### Task 6: AutoML 结果注册与模型导出

为终态幂等注册、制品可读性、manifest 完整性和导出权限编写 RED 测试。AutoML 成功后创建/更新注册模型和版本，记录任务类型、标签 schema、簇/规则元数据与输入契约；导出确定性归档，包含模型文件、受控模板生成的 `inference.py`、manifest、schema、预处理、聚类方法和规则；模型库增加导出与下载 API，拒绝未审批、不完整或跨项目制品。

### Task 7: 推理输入一致性门禁

为列顺序、dtype、缺失/多余列、空值策略、schema hash 和旧模型兼容编写 RED 测试。实现共享 `validate_input_contract(frame, contract) -> ValidationReport`，同时用于 API 和导出脚本；错误返回 expected/actual 差异。完成 train -> register -> export -> infer 成功，以及输入不一致拒绝的端到端测试。

### Task 8: 文档、验收与发布

更新 API reference、用户指南、角色矩阵、annotator 地址、任务生命周期和导出包示例；建立需求到测试命令/证据的验收矩阵；核对当前 SHA、远程作业、浏览器产物、导出 checksum，任何 required `failed`/`skipped` 保持 `in_progress`；更新 `DEVELOPMENT_PLAN.md`，仅对已验证问题追加共享开发经验。

## 任务完成后的交互合同

- 手动标注任务完成：保留当前列表/结果上下文，显示“预览”和“指派标注员”，不自动打开标注详情页。
- 自动标注任务完成：保留当前列表/结果上下文，显示“预览”和“指派标注员”，不自动打开标注详情页。
- “预览”只读展示样本、最终标签、标签来源、簇/规则解释和进度，不改变任务状态。
- “指派标注员”支持单选或多选标注员，提交后显示 assignment 状态和已指派人员，可再次编辑。

## 依赖顺序

`Task 0 -> Task 1 -> Task 2/3 -> Task 4/5 -> Task 6 -> Task 7 -> Task 8`。Task 2 与 Task 3 可在合同完成后并行；Task 6 必须等待 Task 2 和 Task 3 的 schema 稳定；Task 7 必须等待导出 manifest 稳定。

## 需求覆盖自检

- 全项目去行业化：Task 0。
- 多标签分类/回归：Tasks 1-2。
- 手动/自动标签：Task 3。
- 簇、规则、簇+规则：Task 4。
- 独立标注员网页、注册登录、任务指派：Task 5。
- 模型库注册、导出和输入一致性校验：Tasks 6-7。
- 历史数据迁移、测试、文档和远程验收：Task 0、Global Constraints 与 Task 8。

## 已确认配置（2026-09-02）

- 标注员门户采用独立前后端、独立登录态和可配置 `8443` 端口。
- 多人同时标注采用乐观修订校验；冲突需显式确认完整标签集合后才允许最后成功写入。
- 多标签保留为多个独立列，类型为 `int`、`float` 或 `string`；首期不做层级标签或互斥组。
- 自动标注策略互斥为按簇、按规则、按簇加规则；按簇默认提供可编辑的“其他”兜底。
- 标注员主动回传后锁定回传操作，显式编辑生成新修订后解除；模型注册沿用用户手动选择候选的现有逻辑。
