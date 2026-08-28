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

- [ ] **Step 1: 写失败测试**：增加手动任务列表测试，返回 `failed` 和 `cancelled` 的手动任务，断言状态标签只出现“运行中”；增加自动任务失败状态断言仍为“失败”。
- [ ] **Step 2: 运行聚焦测试确认失败**：执行 `npm test -- --run src/pages/DataAnnotationPage.test.tsx`，预期新增手动失败/取消断言失败。

### Task 2: 实现展示层状态归一化

**Files:**
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`

- [ ] **Step 1: 添加最小函数**：定义 `displayRunStatus(run, lang)`；手动模式返回 `completed` 或 `running`，自动模式调用现有 `runStatusText`；颜色同步使用同一归一化状态。
- [ ] **Step 2: 替换列表和详情标签调用**：任务表状态列与工作区顶部状态标签使用归一化结果，保留原始 `selectedRun.status` 用于按钮禁用和轮询条件。
- [ ] **Step 3: 重跑聚焦测试确认通过**：执行同一 Vitest 命令，预期全部通过。

### Task 3: 项目文档与验证

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: 运行前端生产构建**：执行项目既有构建命令，确认 TypeScript/Vite 构建通过。
- [ ] **Step 2: 运行差异检查**：执行 `git diff --check`。
- [ ] **Step 3: 追加计划和经验记录**：记录需求、根因、修改、测试结果和剩余风险，不覆盖并行修改。
