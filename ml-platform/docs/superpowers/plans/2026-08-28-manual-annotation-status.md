# 手动标注任务状态展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将手动标注任务的用户可见状态限制为“运行中/已完成”，同时保持自动标注状态行为不变。

**Architecture:** 在 `DataAnnotationPage` 的展示层引入按标注模式归一化的状态函数，继续复用现有通用状态函数处理自动任务。通过页面测试锁定列表和工作区详情的行为，不修改后端持久化状态机。

**Tech Stack:** React, TypeScript, Vitest, Testing Library, Ant Design。

---

### Task 1: 锁定状态展示回归

**Files:**
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`
- Test: same file

- [x] **Step 1: 写失败测试**：增加手动任务列表测试，返回 `failed` 和 `cancelled` 的手动任务，断言状态标签只出现“运行中”；增加自动任务失败状态断言仍为“失败”。
- [x] **Step 2: 运行聚焦测试确认失败**：执行 `npm test -- --run src/pages/DataAnnotationPage.test.tsx`，新增断言按预期失败。

### Task 2: 实现展示层状态归一化

**Files:**
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`

- [x] **Step 1: 添加最小函数**：手动模式按完成与非完成归一化为 `completed`/`running`，自动模式沿用原始状态。
- [x] **Step 2: 替换列表和详情标签调用**：任务表状态列与工作区顶部状态标签使用归一化结果，保留原始状态用于按钮禁用和轮询条件。
- [x] **Step 3: 重跑聚焦测试确认通过**：`DataAnnotationPage.test.tsx` 38/38 通过。

### Task 3: 项目文档与验证

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [x] **Step 1: 运行前端生产构建**：`npm run build` 通过，仅有既有大 chunk warning。
- [x] **Step 2: 运行差异检查**：`git diff --check` 通过。
- [x] **Step 3: 追加计划和经验记录**：已记录本次需求、根因、修改、测试结果和剩余风险。
