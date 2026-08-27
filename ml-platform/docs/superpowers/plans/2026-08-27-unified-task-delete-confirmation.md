# Unified Task Delete Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every platform task-list row delete and batch delete use one localized Ant Design confirmation interaction before issuing a request.

**Architecture:** Add a small shared `DeleteConfirmation` wrapper that owns the `Popconfirm` contract and composes with existing row-action or toolbar buttons. Migrate task-list pages without changing their API calls, eligibility rules, loading states, or success/error handling.

**Tech Stack:** React, TypeScript, Ant Design, Vitest, Testing Library, existing i18n and `TableRowAction` components.

---

## File Map

- Create `ml-platform/frontend/src/components/DeleteConfirmation.tsx`: shared confirmation wrapper and row-action composition.
- Create `ml-platform/frontend/src/components/DeleteConfirmation.test.tsx`: component interaction contract.
- Modify `ml-platform/frontend/src/i18n/index.tsx`: localized confirmation title and irreversible-delete descriptions.
- Modify task-list pages and focused tests:
  - `pages/ProjectListPage.tsx` / `.test.tsx`
  - `pages/DataManagePage.tsx` / `.test.tsx`
  - `pages/DataAnnotationPage.tsx` / `.test.tsx`
  - `pages/AutoMLPage.tsx` / `.test.tsx`
  - `pages/TrainingJobsPage.tsx` / `.test.tsx`
  - `pages/ModelLibraryPage.tsx` and existing focused model-library tests
  - `pages/OrchestrationPage.tsx` / `.test.tsx`
- Modify `DEVELOPMENT_PLAN.md` and shared development experience after verification.

### Task 1: Shared Confirmation Component

**Files:**
- Create: `ml-platform/frontend/src/components/DeleteConfirmation.tsx`
- Create: `ml-platform/frontend/src/components/DeleteConfirmation.test.tsx`
- Modify: `ml-platform/frontend/src/i18n/index.tsx`

- [ ] **Step 1: Write failing component tests**

Cover these exact behaviors:

```tsx
render(<DeleteConfirmation label="删除任务 A" targetName="任务 A" onConfirm={onConfirm} />);
fireEvent.click(screen.getByRole("button", { name: "删除任务 A" }));
expect(screen.getByText("确认删除？")).toBeInTheDocument();
fireEvent.click(screen.getByRole("button", { name: "取消" }));
expect(onConfirm).not.toHaveBeenCalled();

fireEvent.click(screen.getByRole("button", { name: "删除任务 A" }));
fireEvent.click(screen.getByRole("button", { name: "删除" }));
expect(onConfirm).toHaveBeenCalledTimes(1);
```

Also assert `placement="topRight"` behavior through the rendered popup class/position contract, disabled controls do not open, and a supplied batch button child is preserved.

- [ ] **Step 2: Run the component test and verify failure**

Run:

```powershell
npm test -- --run src/components/DeleteConfirmation.test.tsx
```

Expected: failure because `DeleteConfirmation` does not exist.

- [ ] **Step 3: Add localized copy**

Extend `common` in both languages with:

```ts
confirm_delete_title: "确认删除？" / "Confirm deletion?"
delete_irreversible: "删除后无法恢复。" / "This action cannot be undone."
delete_target_prompt: "确定删除“{name}”吗？" / "Delete \"{name}\"?"
delete_selected_prompt: "确定删除选中的 {count} 项吗？" / "Delete the selected {count} items?"
```

- [ ] **Step 4: Implement the shared component**

Use this public contract:

```tsx
interface DeleteConfirmationProps {
  label: string;
  targetName?: string;
  selectedCount?: number;
  onConfirm: () => void | Promise<void>;
  disabled?: boolean;
  loading?: boolean;
  children?: ReactElement;
}
```

The component must render `Popconfirm` with `placement="topRight"`, localized title/description, `okButtonProps={{ danger: true }}`, and `TableRowAction` with `DeleteOutlined` when no child is supplied.

- [ ] **Step 5: Run component tests**

Expected: all `DeleteConfirmation` and `TableRowAction` tests pass.

### Task 2: Core Data and AutoML Task Lists

**Files:**
- Modify: `pages/DataAnnotationPage.tsx`
- Modify: `pages/DataAnnotationPage.test.tsx`
- Modify: `pages/AutoMLPage.tsx`
- Modify: `pages/AutoMLPage.test.tsx`

- [ ] **Step 1: Update tests to require confirmation**

For each page, assert the delete API has zero calls after the initial trash-button click, then confirm through the shared popup and assert one API call. Cancel must leave the call count at zero. Remove `window.confirm` mocks from data annotation tests.

- [ ] **Step 2: Run focused tests and verify failure**

```powershell
npm test -- --run src/pages/DataAnnotationPage.test.tsx src/pages/AutoMLPage.test.tsx
```

- [ ] **Step 3: Migrate row deletes**

Replace direct handlers with:

```tsx
<DeleteConfirmation
  label={deleteLabel}
  targetName={taskName}
  disabled={!canDelete}
  loading={isDeleting}
  onConfirm={() => deleteTask(task)}
/>
```

Remove `window.confirm` from `deleteRun`; keep project checks and loading guards inside the handler.

- [ ] **Step 4: Run focused tests**

Expected: data annotation and AutoML focused tests pass; skipped tests remain reported as skipped.

### Task 3: Training and Model Task Lists

**Files:**
- Modify: `pages/TrainingJobsPage.tsx`
- Modify: `pages/TrainingJobsPage.test.tsx`
- Modify: `pages/ModelLibraryPage.tsx`
- Modify: `pages/ModelLibraryPage.test.tsx`

- [ ] **Step 1: Add confirmation regression tests**

Cover experiment deletion, terminal training-job deletion, registered-model deletion, and deployment deletion. The initial click opens the shared popup; only the danger confirmation executes the existing handler.

- [ ] **Step 2: Verify current tests fail**

Run:

```powershell
npm test -- --run src/pages/TrainingJobsPage.test.tsx src/pages/ModelLibraryPage.test.tsx
```

- [ ] **Step 3: Replace local confirmation implementations**

Remove delete-specific `Popconfirm` blocks in `TrainingJobsPage` and delete-specific `Modal.confirm` functions in `ModelLibraryPage`. Wrap existing delete callbacks with `DeleteConfirmation`. Do not modify stop, revoke, rollback, or other non-delete confirmations.

- [ ] **Step 4: Run focused tests**

Expected: all migrated training/model tests pass.

### Task 4: Project, Data, and Orchestration Lists

**Files:**
- Modify: `pages/ProjectListPage.tsx` / `.test.tsx`
- Modify: `pages/DataManagePage.tsx` / `.test.tsx`
- Modify: `pages/OrchestrationPage.tsx` / `.test.tsx`

- [ ] **Step 1: Add row and batch confirmation tests**

Test project row delete, dataset row delete, orchestration task/agent row delete, project batch delete, and orchestration task/agent batch delete. Batch descriptions must include the selected count.

- [ ] **Step 2: Verify tests fail against mixed current implementations**

Run the three focused page test files.

- [ ] **Step 3: Migrate row actions and batch buttons**

Use `DeleteConfirmation` without children for row trash icons. For batch actions, pass the existing danger button as `children` and move the previous `Modal.confirm` callback into `onConfirm`.

- [ ] **Step 4: Run focused tests**

Expected: all project/data/orchestration tests pass.

### Task 5: Cross-Page Verification and Documentation

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Append: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Search for remaining task-list delete bypasses**

Run:

```powershell
rg -n "window\.confirm|Modal\.confirm|TableRowAction.*DeleteOutlined|onClick=.*delete" ml-platform/frontend/src/pages
```

Review every remaining match and confirm it is either migrated or explicitly outside task-list scope.

- [ ] **Step 2: Run the focused suite**

```powershell
npm test -- --run src/components/DeleteConfirmation.test.tsx src/components/TableRowAction.test.tsx src/pages/ProjectListPage.test.tsx src/pages/DataManagePage.test.tsx src/pages/DataAnnotationPage.test.tsx src/pages/AutoMLPage.test.tsx src/pages/TrainingJobsPage.test.tsx src/pages/OrchestrationPage.test.tsx
```

- [ ] **Step 3: Run production build**

```powershell
npm run build
```

Expected: TypeScript and Vite build pass; existing chunk-size warnings remain warnings.

- [ ] **Step 4: Run diff validation**

```powershell
git diff --check
```

Expected: no whitespace errors; CRLF conversion notices may be reported separately.

- [ ] **Step 5: Update development records**

Record observed mixed confirmation behavior, shared-component solution, exact test counts, skipped tests, build result, and any remaining non-task delete controls. Preserve all existing history.

## Execution Constraint

The worktree contains unrelated user changes. Do not reset, checkout, stage, commit, or modify unrelated files. Use `apply_patch` for manual edits and report verification failures distinctly from skipped tests.
