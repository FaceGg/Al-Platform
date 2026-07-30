# 智擎平台名称变更 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将前端所有用户可见的平台品牌名称统一为“智擎”，同时保持技术标识不变。

**Architecture:** 使用一个源码品牌合同测试锁定各入口的展示名称，再对现有字面量做精准替换。不会新增品牌常量或修改后端、API、任务队列、存储及目录标识。

**Tech Stack:** React 18、TypeScript、Vite、Vitest、Playwright

---

### Task 1: 建立品牌展示合同

**Files:**
- Create: `ml-platform/frontend/src/branding.test.ts`

- [x] **Step 1: 写入失败测试**

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const read = (path: string) => readFileSync(resolve(process.cwd(), path), "utf8");

describe("platform branding", () => {
  it.each([
    "index.html",
    "src/i18n/index.tsx",
    "src/components/AppLayout.tsx",
    "src/pages/LoginPage.tsx",
    "src/pages/RegisterPage.tsx",
    "src/pages/DashboardPage.tsx",
  ])("uses 智擎 in %s", (path) => {
    expect(read(path)).toContain("智擎");
  });

  it("keeps the authenticated navigation assertion on the new brand", () => {
    expect(read("e2e/core-navigation.spec.ts")).toContain('toContainText("智擎")');
  });
});
```

- [x] **Step 2: 运行测试并确认预期失败**

Run: `npm test -- --run src/branding.test.ts`

Expected: FAIL，失败原因是上述生产入口仍未包含“智擎”。

### Task 2: 精准替换用户可见品牌

**Files:**
- Modify: `ml-platform/frontend/index.html`
- Modify: `ml-platform/frontend/src/i18n/index.tsx`
- Modify: `ml-platform/frontend/src/components/AppLayout.tsx`
- Modify: `ml-platform/frontend/src/pages/LoginPage.tsx`
- Modify: `ml-platform/frontend/src/pages/RegisterPage.tsx`
- Modify: `ml-platform/frontend/src/pages/DashboardPage.tsx`
- Modify: `ml-platform/frontend/e2e/core-navigation.spec.ts`
- Modify: `ml-platform/frontend/src/weekAcceptance.test.ts`

- [x] **Step 1: 修改浏览器、国际化和页面品牌文案**

将以下用户可见文案替换为“智擎”，需要副标题语境时使用“智擎 · 总览面板”或“智擎 · 工业智能平台”：

```text
ML 算法平台
AI模型训练编排平台
AI 模型训练编排平台
AI Model Training Platform
AI Training Platform
AI Model Training and Orchestration
Precision Forge
```

不要替换 `ml-platform`、`platform_joblib`、API 路径、Celery 任务名、存储桶或代码符号中的 `platform`。

- [x] **Step 2: 运行品牌合同测试并确认通过**

Run: `npm test -- --run src/branding.test.ts`

Expected: `7` 个品牌合同用例全部 PASS。

- [x] **Step 3: 搜索遗留品牌文案**

Run: `rg -n 'AI模型训练编排平台|AI Model Training Platform|AI Training Platform|Precision Forge|工业智能平台|ML 算法平台|AI 模型训练编排平台|AI Model Training and Orchestration' src e2e index.html`

Expected: 无匹配；CSS 中描述既有设计风格的注释如仍含 `Precision Forge`，也一并改为中性的 `Platform Design System`，避免旧品牌残留。

### Task 3: 完成回归和项目记录

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:/Users/17723/.codex/DEVELOPMENT_EXPERIENCE.md`

- [x] **Step 1: 运行前端全量测试**

Run: `npm test -- --run`

Expected: 全部 Vitest 用例 PASS。

- [x] **Step 2: 运行生产构建**

Run: `npm run build`

Expected: TypeScript 检查和 Vite 构建成功；只允许记录项目既有且与本次无关的 chunk-size 告警。

- [x] **Step 3: 更新项目记录**

在 `DEVELOPMENT_PLAN.md` 末尾追加本次任务状态、变更范围、验证结果、影响范围和遗留事项；在共享经验文件的本项目分类末尾追加品牌变更应区分用户文案与技术标识的可复用经验。

- [x] **Step 4: 检查最终差异**

Run: `git diff --check && git status --short && git diff --stat`

Expected: 无空白错误；`platform-preview.html` 仍保持用户原有修改且未被本任务覆盖。
