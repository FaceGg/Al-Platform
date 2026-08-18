# Dashboard and Navigation UI Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development before production edits.

**Goal:** 修复工作台真实数据展示、明亮模式顶部栏、右上角用户信息和数据标注导航入口。

**Architecture:** 保持现有 React/Ant Design 结构，不改后端 API。Dashboard 使用现有聚合接口并区分加载、错误和空数据；AppLayout 统一使用主题 CSS 变量，用户身份统一从 `/api/auth/me` 回填，导航新增独立 `/data-annotation` 菜单项。

**Tech Stack:** React 18、TypeScript、Ant Design、React Router、Vitest、Testing Library、Vite。

---

### Task 1: Dashboard data states

**Files:**
- Modify: `ml-platform/frontend/src/pages/DashboardPage.tsx`
- Test: `ml-platform/frontend/src/pages/DashboardPage.test.tsx`

- [ ] Write failing tests for populated backend stats, failed stats request, and project list rendering from API response.
- [ ] Run the focused Dashboard test and confirm the new assertions fail against the current silent-fallback behavior.
- [ ] Add explicit loading/error/empty states while preserving the existing `core_assets`, `model_status`, `algorithm_coverage`, and `items` response contracts.
- [ ] Run the focused Dashboard test and confirm it passes.

### Task 2: Theme-aware header and navigation

**Files:**
- Modify: `ml-platform/frontend/src/components/AppLayout.tsx`
- Modify: `ml-platform/frontend/src/stores/themeContext.tsx` if synchronization coverage requires it
- Test: `ml-platform/frontend/src/components/AppLayout.test.tsx`
- Test: `ml-platform/frontend/src/stores/themeContext.test.tsx`

- [ ] Write failing tests that assert the header uses theme-aware classes/styles and the theme toggle exposes the correct accessible label/state.
- [ ] Run the focused layout/theme tests and confirm failure.
- [ ] Replace hard-coded dark header styling with existing CSS variables and add stable accessible labels for theme switching.
- [ ] Run the focused layout/theme tests and confirm both light and dark states pass.

### Task 3: Username and role presentation

**Files:**
- Modify: `ml-platform/frontend/src/components/AppLayout.tsx`
- Modify: `ml-platform/frontend/src/components/AppLayoutUsername.test.tsx`

- [ ] Write failing tests for `/api/auth/me` username recovery, UUID fallback suppression, and compact username/role layout.
- [ ] Run the focused username tests and confirm failure because the current request uses `/me` and falls back to `userId`.
- [ ] Fetch `/auth/me`, keep username and role in one normalized display state, suppress UUID as visible identity, and remove excess spacing between name and role tag.
- [ ] Run the focused username tests and confirm pass.

### Task 4: Data annotation navigation

**Files:**
- Modify: `ml-platform/frontend/src/components/AppLayout.tsx`
- Modify: `ml-platform/frontend/src/components/AppLayout.test.tsx`
- Modify: `ml-platform/frontend/src/weekAcceptance.test.ts`

- [ ] Write a failing navigation test asserting a visible `数据标注` item points to `/data-annotation` and is selected on that route.
- [ ] Run the focused layout test and confirm failure because the item is absent.
- [ ] Add the standalone item immediately below `数据管理`, wire navigation and selected-key matching.
- [ ] Run the focused navigation test and confirm pass.

### Task 5: Verification and documentation

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [ ] Run focused frontend tests for Dashboard, AppLayout, username, and theme.
- [ ] Run the complete frontend Vitest suite and `npm run build`.
- [ ] Verify desktop light/dark screenshots and navigation in the local browser.
- [ ] Record implementation, verification, and any remaining backend/runtime limitation in the development documents.
