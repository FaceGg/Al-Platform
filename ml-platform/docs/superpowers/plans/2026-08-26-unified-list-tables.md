# Unified List Tables Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the primary lists in seven platform modules share one compact table surface, one header typography contract, and one tooltip-enabled icon action system.

**Architecture:** Keep business column definitions in their current pages, introduce a focused `TableRowAction` component for icon actions, and centralize table geometry in `global.css`. Convert only the data annotation task list from its custom article grid to Ant Design `Table`; no backend contracts or task behavior change.

**Tech Stack:** React 18, TypeScript, Ant Design Table/Button/Tooltip, `@ant-design/icons`, Vitest, Testing Library, Vite.

---

## File Map

- Create `ml-platform/frontend/src/components/TableRowAction.tsx`: shared icon-only row action with Tooltip, accessible name, semantic tone, loading, and disabled states.
- Create `ml-platform/frontend/src/components/TableRowAction.test.tsx`: shared component interaction and accessibility contract.
- Modify `ml-platform/frontend/src/styles/global.css`: compact table surface, shared header/body typography, row height, hover state, operation alignment, and action focus/semantic colors.
- Modify `ml-platform/frontend/src/pages/ProjectListPage.tsx`: standard project row actions and toolbar icons.
- Modify `ml-platform/frontend/src/pages/ModelLibraryPage.tsx`: standard registered-model and deployment row actions and table surfaces.
- Modify `ml-platform/frontend/src/pages/DataManagePage.tsx`: replace local row-action button styling with the shared component.
- Modify `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`: migrate the task article grid to Ant Design Table and shared row actions.
- Modify `ml-platform/frontend/src/pages/AutoMLPage.tsx`: standard task list surface and actions.
- Modify `ml-platform/frontend/src/pages/TrainingJobsPage.tsx`: standard experiment/training task surfaces and actions.
- Modify `ml-platform/frontend/src/pages/OrchestrationPage.tsx`: standard task/agent surfaces and actions.
- Modify focused tests for each page to lock structure, tooltips, icons, and existing behavior.
- Modify `DEVELOPMENT_PLAN.md` and `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md` after verification.

## Task 1: Shared Row Action Contract

**Files:**
- Create: `ml-platform/frontend/src/components/TableRowAction.tsx`
- Create: `ml-platform/frontend/src/components/TableRowAction.test.tsx`

- [ ] **Step 1: Write the failing shared-component tests**

Cover a neutral view action and a danger delete action. Assert the icon-only button has the supplied `aria-label`, danger class, disabled/loading behavior, and a Tooltip that becomes visible after mouse hover.

```tsx
render(
  <AntApp>
    <TableRowAction label="删除项目 项目A" icon={<DeleteOutlined />} danger onClick={onClick} />
  </AntApp>,
);
const button = screen.getByRole("button", { name: "删除项目 项目A" });
expect(button).toHaveClass("table-row-action");
expect(button).toHaveClass("table-row-action--danger");
fireEvent.mouseEnter(button.closest("span")!);
expect(await screen.findByRole("tooltip")).toHaveTextContent("删除项目 项目A");
fireEvent.click(button);
expect(onClick).toHaveBeenCalledTimes(1);
```

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform\frontend
npm test -- --run src/components/TableRowAction.test.tsx
```

Expected: failure because `TableRowAction` does not exist.

- [ ] **Step 3: Implement the focused shared component**

Use this public contract:

```tsx
import type { MouseEventHandler, ReactNode } from "react";
import { Button, Tooltip } from "antd";

interface TableRowActionProps {
  label: string;
  icon: ReactNode;
  onClick?: MouseEventHandler<HTMLElement>;
  danger?: boolean;
  warning?: boolean;
  disabled?: boolean;
  loading?: boolean;
}

export default function TableRowAction({
  label, icon, onClick, danger = false, warning = false, disabled = false, loading = false,
}: TableRowActionProps) {
  const className = [
    "table-row-action",
    danger ? "table-row-action--danger" : "",
    warning ? "table-row-action--warning" : "",
  ].filter(Boolean).join(" ");
  return (
    <Tooltip title={label}>
      <span className="table-row-action__tooltip-target">
        <Button
          type="text"
          size="small"
          className={className}
          danger={danger}
          icon={icon}
          aria-label={label}
          onClick={onClick}
          disabled={disabled}
          loading={loading}
        />
      </span>
    </Tooltip>
  );
}
```

- [ ] **Step 4: Run the component test and verify GREEN**

Expected: all `TableRowAction` tests pass without `act` or accessibility warnings.

## Task 2: Shared Compact Table Styling

**Files:**
- Modify: `ml-platform/frontend/src/styles/global.css`
- Test: `ml-platform/frontend/src/components/TableRowAction.test.tsx`

- [ ] **Step 1: Add CSS contract assertions**

Read `global.css` in the component test and assert the shared selectors exist for `.table-surface`, `.table-surface .ant-table-thead > tr > th`, `.table-surface .ant-table-tbody > tr > td`, `.table-row-actions`, and `.table-row-action`.

- [ ] **Step 2: Run the test and verify it fails on the old 18px surface contract**

Expected: assertion fails because the current surface radius is `18px` and shared action selectors are absent.

- [ ] **Step 3: Implement the selected A visual tokens**

Set the shared contract to:

```css
.table-surface {
  overflow: hidden;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--bg-surface);
  box-shadow: none;
}

.table-surface .ant-table-thead > tr > th {
  min-height: 40px;
  padding: 10px 14px !important;
  color: var(--text-secondary) !important;
  background: var(--bg-elevated) !important;
  border-bottom: 1px solid var(--border-default) !important;
  font-size: 12px;
  font-weight: 600;
}

.table-surface .ant-table-tbody > tr > td {
  min-height: 46px;
  padding: 8px 14px !important;
  color: var(--text-primary) !important;
  border-bottom: 1px solid var(--border-subtle) !important;
  font-size: 13px;
}

.table-row-actions {
  display: inline-flex;
  justify-content: flex-end;
  align-items: center;
  gap: 4px;
  width: 100%;
}

.table-row-action__tooltip-target,
.table-row-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.table-row-action {
  width: 30px !important;
  min-width: 30px !important;
  height: 30px;
  padding: 0 !important;
  color: var(--text-secondary);
}

.table-row-action--danger { color: var(--status-danger) !important; }
.table-row-action--warning { color: var(--status-warning) !important; }
.table-row-action:focus-visible { outline: 2px solid var(--accent-primary); outline-offset: 2px; }
```

Use existing variables if their exact names differ; do not introduce duplicate hard-coded theme colors.

- [ ] **Step 4: Remove data-annotation task-card-only list styling**

Delete `.data-annotation__tasks`, `.data-annotation__task`, header-row, grid-track, and task-card responsive selectors only after Task 4 migrates the JSX. Preserve setup and workspace styles.

- [ ] **Step 5: Run the shared tests**

Expected: component and CSS contract tests pass.

## Task 3: Project, Model, And Data Lists

**Files:**
- Modify: `ml-platform/frontend/src/pages/ProjectListPage.tsx`
- Modify: `ml-platform/frontend/src/pages/ModelLibraryPage.tsx`
- Modify: `ml-platform/frontend/src/pages/DataManagePage.tsx`
- Modify: corresponding page tests.

- [ ] **Step 1: Add failing tests for uniform delete controls**

For each page, locate the row delete control by its localized accessible name and assert:

```tsx
expect(deleteButton).toHaveClass("table-row-action--danger");
expect(deleteButton).toHaveAttribute("aria-label", expect.stringMatching(/^删除/));
expect(deleteButton).not.toHaveTextContent("删除");
fireEvent.mouseEnter(deleteButton.closest("span")!);
expect(await screen.findByRole("tooltip")).toHaveTextContent(/删除/);
```

Also assert each primary list is inside `.table-surface`.

- [ ] **Step 2: Verify RED against current mixed implementations**

Expected failures:

- Project list uses red text links.
- Model library uses red icon plus text buttons.
- Data management uses a page-local icon button rather than the shared component.

- [ ] **Step 3: Migrate ProjectListPage actions**

Import `EyeOutlined`, `DeleteOutlined`, and `TableRowAction`. Replace `进入` and `删除` links with:

```tsx
<div className="table-row-actions">
  <TableRowAction label={`进入项目 ${record.name}`} icon={<EyeOutlined />} onClick={() => navigate(`/projects/${record.id}`)} />
  <TableRowAction label={`删除项目 ${record.name}`} icon={<DeleteOutlined />} danger onClick={() => deleteProject(record.id, record.name)} />
</div>
```

Add `DeleteOutlined` to the batch-delete toolbar button while retaining its text and selected count.

- [ ] **Step 4: Migrate ModelLibraryPage primary list actions**

Replace registered-model and deployment delete text buttons with `TableRowAction`. Convert other familiar row commands in those operation columns to icon actions with precise localized labels. Keep workflow commands that require explicit text, such as staged rollout approval, outside this row-action conversion when their icon would be ambiguous.

- [ ] **Step 5: Migrate DataManagePage actions**

Replace the local delete button with `TableRowAction`; also convert preview, download/export, and annotation-entry row commands to the shared action component using their existing icons and handlers. Keep the current `.dataset-table-actions` only if it is still needed for nowrap behavior; otherwise replace it with `.table-row-actions`.

- [ ] **Step 6: Run focused tests**

Run the ProjectList, ModelLibrary, and DataManage page test files. Expected: all existing behavior and new tooltip assertions pass.

## Task 4: Data Annotation Table Migration

**Files:**
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`
- Modify: `ml-platform/frontend/src/styles/global.css`

- [ ] **Step 1: Write failing structural tests**

Replace expectations for `region[name="数据标注任务列表"]` custom articles with an Ant table expectation. Assert the task list contains column headers for task, project, creator, mode/status, progress, and actions. Assert the delete control is a danger trash icon with Tooltip and the view control is a neutral icon with Tooltip.

- [ ] **Step 2: Verify RED against the custom article grid**

Expected: no Ant Design table exists in the task-list surface.

- [ ] **Step 3: Define `Table<QualityRun>` columns**

Use memoized columns or a stable local array with these renderers:

```tsx
const taskColumns = [
  {
    title: copy.task,
    key: "task",
    render: (_: unknown, run: QualityRun) => (
      <div className="table-primary-cell">
        <strong>{run.id.slice(0, 8)}</strong>
        <span>{runModeText(run, copy)}</span>
      </div>
    ),
  },
  { title: copy.project, key: "project", render: (_: unknown, run: QualityRun) => run.project_name || run.project_id || "-" },
  { title: copy.creator, key: "creator", render: (_: unknown, run: QualityRun) => run.created_by_name || run.created_by_id || "-" },
  { title: copy.modeStatus, key: "status", render: (_: unknown, run: QualityRun) => <Tag color={taskStatusColor(run.status)}>{runStatusText(run, lang)}</Tag> },
  { title: copy.progress, key: "progress", render: (_: unknown, run: QualityRun) => annotationProgressText(run) },
  {
    title: copy.actions,
    key: "actions",
    align: "right" as const,
    render: (_: unknown, run: QualityRun) => (
      <div className="table-row-actions">
        <TableRowAction label={`${run.label_mode === "manual" ? copy.viewManual : copy.view} ${run.id}`} icon={<EyeOutlined />} onClick={() => openRunWorkspace(run)} />
        <TableRowAction label={`${copy.deleteTask} ${run.id}`} icon={<DeleteOutlined />} danger loading={deletingRunId === run.id} onClick={() => void removeRun(run)} />
      </div>
    ),
  },
];
```

- [ ] **Step 4: Render the standard table**

Use:

```tsx
<div className="table-surface data-annotation__tasks-surface" role="region" aria-label={copy.taskListLabel}>
  <Table<QualityRun>
    rowKey="id"
    size="small"
    loading={loadingRuns}
    dataSource={runs}
    columns={taskColumns}
    pagination={false}
    scroll={{ x: 820 }}
    locale={{ emptyText: <Empty description={copy.noTasks} /> }}
  />
</div>
```

- [ ] **Step 5: Remove obsolete task-card CSS**

Delete only selectors made unreachable by the table migration. Keep task header actions, setup workflow, rule editor, and workspace/detail styles intact.

- [ ] **Step 6: Run DataAnnotation tests**

Run `DataAnnotationPage.test.tsx` and `spotWeldQuality.test.ts`. Expected: task aggregation, project/creator rendering, opening, deletion, polling, automatic/manual setup, and all new table assertions pass.

## Task 5: AutoML, Training, And Orchestration Lists

**Files:**
- Modify: `ml-platform/frontend/src/pages/AutoMLPage.tsx`
- Modify: `ml-platform/frontend/src/pages/TrainingJobsPage.tsx`
- Modify: `ml-platform/frontend/src/pages/OrchestrationPage.tsx`
- Modify: corresponding tests.

- [ ] **Step 1: Add failing row-action and table-surface assertions**

For AutoML tasks, training experiments/tasks, orchestration tasks/agents, assert operation columns use shared icon actions and hover Tooltips. Assert their primary `Table` elements are wrapped in `.table-surface`.

- [ ] **Step 2: Verify RED on page-local button implementations**

Expected: AutoML and training delete buttons are Ant buttons without the shared component; orchestration mixes outlined and text buttons.

- [ ] **Step 3: Migrate AutoML task actions**

Use `EyeOutlined` for detail, `StopOutlined` for stop with warning tone, and `DeleteOutlined` for deletion with danger tone. Preserve the existing status-based disabled rule and handlers.

- [ ] **Step 4: Migrate TrainingJobsPage actions**

Apply the shared component to both experiment and training-task operation columns. Use explicit Tooltip labels that distinguish experiments from tasks. Preserve polling, progress rendering, stop/resume conditions, and project filters.

- [ ] **Step 5: Migrate OrchestrationPage actions**

Apply shared icon actions to task view/delete and agent view/delete controls. Preserve review commands whose meaning depends on approval context as text buttons when an icon alone would be ambiguous. Wrap both tab tables in the shared surface.

- [ ] **Step 6: Run focused tests**

Expected: existing filtering, project/creator columns, task state mapping, bulk deletion, task opening, and agent operations remain green alongside new tooltip assertions.

## Task 6: Cross-Page Verification And Documentation

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Run all focused frontend suites**

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform\frontend
npm test -- --run `
  src/components/TableRowAction.test.tsx `
  src/pages/ProjectListPage.test.tsx `
  src/pages/ModelLibraryPage.test.tsx `
  src/pages/DataManagePage.test.tsx `
  src/pages/DataAnnotationPage.test.tsx `
  src/pages/AutoMLPage.test.tsx `
  src/pages/TrainingJobsPage.test.tsx `
  src/pages/OrchestrationPage.test.tsx
```

If a listed historical test file does not exist, use the existing nearest page test and record the gap rather than inventing a passing result.

- [ ] **Step 2: Run production build**

```powershell
npm run build
```

Expected: TypeScript and Vite build pass; existing ECharts chunk warnings may remain but no new warnings are accepted.

- [ ] **Step 3: Run browser verification**

Start the existing frontend development server on an available port. Verify desktop and narrow viewport behavior for all seven list surfaces:

- Shared 6px table surface and header typography.
- No custom card rows in data annotation.
- No black trash icons or visible single-row `删除` text.
- Every row icon displays the correct Tooltip on hover.
- Keyboard focus is visible.
- Long names and operation groups do not overlap.
- Horizontal scrolling works where required.

- [ ] **Step 4: Run diff validation**

```powershell
cd E:\codex_workspace\agent_spot_welding
git diff --check
git status --short
```

Expected: no whitespace errors; unrelated dirty-worktree changes remain untouched.

- [ ] **Step 5: Update required development records**

Append the observed inconsistencies, root cause, shared-component solution, test/build/browser evidence, and prevention rule to both required development documents. Do not mark remote CI or unexecuted browser cases as passed.

## Execution Note

No commit steps are included because this workspace requires an explicit user request before committing. Keep every edit scoped, preserve all unrelated dirty-worktree changes, and report verification states separately.
