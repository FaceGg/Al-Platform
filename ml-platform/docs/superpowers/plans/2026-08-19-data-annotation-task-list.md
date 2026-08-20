# 数据标注任务列表入口调整 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 点击左侧“数据标注”后直接显示任务列表，且任务列表不再显示“点焊标注任务”等页头说明文字。

**Architecture:** 保持现有 `/data-annotation` 路由和 `isTaskList` 判断不变，只调整 `tasksView` 的展示结构：移除页头文字节点，将创建按钮放入任务列表区域顶部。现有任务数据、权限、创建流程和其他配置/工作区视图保持不变。

**Tech Stack:** React 18、TypeScript、React Router、Vitest、Testing Library、Vite。

---

### Task 1: 更新任务列表页头结构

**Files:**
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx:663-696`

- [ ] **Step 1: 删除任务列表页头的说明文字**

在 `tasksView` 中移除 `page-kicker`、`page-title`、`page-subtitle` 三个元素及其包裹的 `page-header-copy`，保留两个新建任务按钮。

- [ ] **Step 2: 将创建按钮放在任务列表区域顶部**

把现有 `data-annotation__task-actions` 放入 `data-annotation__tasks` 的第一个子节点，任务卡片和空状态逻辑保持不变；不要修改按钮文本、点击处理函数或权限逻辑。

- [ ] **Step 3: 保持旧链接行为不变**

确认 `isTaskList`、`isSetup`、`isWorkspace` 和 `returnToTaskList` 不改动，确保默认 `/data-annotation` 仍进入任务列表，带 `datasetId`/`runId` 的链接仍进入原视图。

### Task 2: 更新页面回归测试

**Files:**
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx:79-100,234-245`

- [ ] **Step 1: 替换旧标题断言**

在“直接打开任务列表”和“返回任务列表”测试中，将查找“点焊标注任务”的断言改为查找任务列表区域、任务进度和新建按钮。

- [ ] **Step 2: 增加页头文字不存在断言**

断言 `SPOT WELD / TASKS`、`点焊标注任务` 和 `查看任务状态、标注方式和当前进度` 均不在文档中；保留原有任务字段和创建操作断言。

### Task 3: 同步开发记录并验证

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: 运行聚焦测试**

在 `ml-platform/frontend` 执行 `npm test -- --run src/pages/DataAnnotationPage.test.tsx`，确认数据标注页面回归通过。

- [ ] **Step 2: 运行构建和差异检查**

执行 `npm run build` 与仓库根目录 `git diff --check`，确认 TypeScript、Vite 构建和补丁格式通过。

- [ ] **Step 3: 更新项目记录**

在 `DEVELOPMENT_PLAN.md` 末尾追加本次日期、实现内容、验证结果和剩余风险；在共享开发经验的 agent_spot_welding 分类追加现象、根因、解决方法、验证方式和预防措施。保留现有未提交修改，不覆盖无关文件。
