# 点焊标注实时进度、任务删除与规则编辑实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让点焊标注任务实时展示进度，支持删除终态任务，并允许自动、手动任务修改规则。

**Architecture:** 复用现有运行、样本和规则集表。后端新增规则更新 API 和服务方法；自动模式在现有样本上分批重算自动字段，手动模式只保存配置。前端用 1 秒轮询同步运行和样本，复用现有规则表单，并接入已有删除 API。

**Tech Stack:** FastAPI、SQLAlchemy、Pandas、React 18、TypeScript、Vitest、Testing Library。

---

### Task 1: 后端规则更新契约

**Files:**
- Modify: `ml-platform/backend/tests/test_spot_weld_quality_service.py`
- Modify: `ml-platform/backend/tests/test_api_spot_weld_quality.py`
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py`
- Modify: `ml-platform/backend/app/api/spot_weld_quality.py`

- [x] 写服务测试：自动任务修改规则后更新 `automatic_label`、`rule_hits`，保留 `current_label`。
- [x] 写服务测试：手动任务保存规则后样本标签不变。
- [x] 运行目标测试，确认因规则更新方法/API 不存在而失败。
- [x] 实现规则校验、保存、规则集更新和自动分批重算。
- [x] 新增 `PUT /runs/{run_id}/rules`，复用项目权限和审计。
- [x] 运行目标测试，确认通过。

### Task 2: 初次自动标注细粒度进度

**Files:**
- Modify: `ml-platform/backend/tests/test_spot_weld_quality_service.py`
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py`

- [x] 写测试记录提交时的 `annotation_progress`，要求中间进度可见。
- [x] 运行测试，确认当前 100 条批次行为失败。
- [x] 将样本创建提交批次缩小到最多 10 条。
- [x] 运行测试，确认通过。

### Task 3: 前端任务删除和规则编辑

**Files:**
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.ts`
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`

- [x] 写测试：终态任务显示删除按钮、确认后调用删除 API。
- [x] 写测试：自动和手动详情显示对应标题及可编辑规则，保存调用规则更新 API。
- [x] 运行目标测试，确认失败。
- [x] 增加 API 客户端规则更新方法。
- [x] 在任务列表接入删除按钮与确认。
- [x] 在详情页复用规则字段表单，按任务模式显示标题并保存。
- [x] 运行目标测试，确认通过。

### Task 4: 前端实时同步

**Files:**
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`

- [x] 写 fake timer 测试：活动任务每 1 秒刷新运行和样本，终态停止。
- [x] 运行测试，确认当前只刷新运行且周期为 1.5 秒而失败。
- [x] 实现统一轮询，合并最新运行、刷新样本并保留选中项。
- [x] 运行页面测试，确认通过。

### Task 5: 验证与文档

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [x] 运行后端点焊标注相关测试。
- [x] 运行前端数据标注页面测试。
- [x] 运行前端生产构建和 `git diff --check`。
- [x] 追加现象、根因、修复、验证和预防措施到两份开发文档。
