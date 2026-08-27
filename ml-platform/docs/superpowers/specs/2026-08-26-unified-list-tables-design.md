# Unified List Tables Design

## Purpose

Unify list presentation and row actions across project management, model library, data management, data annotation, AutoML, model training, and application orchestration. The result must feel like one operational platform rather than seven unrelated page implementations.

## Scope

The change covers these list surfaces:

- Project management project list.
- Model library registered-model and deployment lists.
- Data management dataset list.
- Data annotation task list.
- AutoML task list.
- Model training experiment and training-task lists.
- Application orchestration task and agent lists.

Business-specific columns, filters, selection rules, pagination, permissions, and task behavior remain unchanged.

## Chosen Visual Direction

Use a quiet, compact operational table style:

- Table surface uses a neutral 1px border and 6px radius.
- Remove oversized 18px list radius and pronounced table shadow.
- Header uses a light neutral-gray background.
- Header labels use one shared 12px semibold style and one shared secondary text color.
- Body rows use a stable 46px minimum height, subtle separators, and a restrained hover background.
- Table text uses the existing application body font and primary text color.
- Operation columns are right aligned with a 4px gap between controls.
- Empty, loading, pagination, row-selection, and horizontal-scroll states use Ant Design Table behavior consistently.

## Structural Approach

Use shared table styling plus a shared row-action component instead of a full business-table abstraction.

1. Keep each page's existing Ant Design `Table` and column definitions.
2. Apply one shared list surface class and shared table sizing contract.
3. Add a reusable row-action icon button that owns tooltip, icon-button sizing, semantic color, loading state, disabled state, and accessible naming.
4. Replace the data annotation task card/grid implementation with Ant Design `Table` so its header, rows, empty state, and operation column match the other modules.

This avoids page-by-page CSS drift without forcing unrelated business tables into one oversized wrapper API.

## Row Actions

All familiar single-row actions use 30px icon-only buttons:

- View or enter: eye or open icon.
- Edit: edit icon.
- Download or export: download icon.
- Stop: stop icon with warning semantics where appropriate.
- Delete: `DeleteOutlined` trash-can icon with danger styling.

Delete must never appear as plain Chinese text, text plus icon, or a black icon. It always uses the same red trash-can treatment.

Every icon action must provide:

- A hover Tooltip with a specific action and object, such as `查看标注任务`, `下载数据`, `停止训练任务`, or `删除项目`.
- A matching localized `aria-label`.
- A visible keyboard focus state.
- A consistent disabled and loading state.

Only destructive actions use danger red. Ordinary actions use the shared neutral action color. Warning actions use the existing warning semantic color and must not visually compete with delete.

## Toolbar Actions

Page-level commands remain icon plus text because they initiate larger workflows:

- Create or add.
- Start.
- Import or upload.
- Batch delete.

Batch delete retains text and selected count, for example `批量删除（3）`. Its danger styling and confirmation behavior remain intact.

## Data Annotation Migration

Replace `.data-annotation__tasks` and `.data-annotation__task` article rows with an Ant Design `Table<QualityRun>`.

The table preserves these columns:

- Task identifier and annotation mode.
- Project.
- Creator.
- Status.
- Progress.
- Actions.

Opening a run, deleting a run, project ownership resolution, polling, status mapping, and bilingual copy must not change. The migration changes presentation, not task behavior.

## Shared Styling Contract

The shared CSS contract will define:

- Surface border, radius, background, and overflow.
- Header background, typography, padding, and separator.
- Body typography, row height, separator, and hover state.
- Operation-cell alignment and action spacing.
- Icon-button dimensions, focus ring, neutral color, danger color, disabled state, and hover state.

Page-specific selectors may adjust column widths or horizontal scrolling, but may not override shared header typography, delete styling, or row-action dimensions.

## Localization And Accessibility

- Tooltip and `aria-label` text must use the active Chinese or English locale where the page already supports localization.
- Existing untranslated pages may keep their current language for this scoped change, but newly added action text must not introduce a second language within the same page.
- Icon-only controls must remain keyboard reachable.
- Tooltips supplement accessible names; they do not replace them.
- Disabled controls retain sufficient contrast and expose their reason through the existing surrounding task state where applicable.

## Verification

Add or update focused tests to verify:

- All seven modules use the shared table surface contract.
- Data annotation renders an Ant Design table instead of custom task articles.
- Single-row delete controls use `DeleteOutlined`, danger styling, icon-only presentation, Tooltip, and an accessible name.
- Other familiar row actions use the shared icon-button component and Tooltip.
- Batch delete remains icon plus text and selected count.
- Existing navigation, deletion confirmation, permissions, selection, polling, and status behavior remain unchanged.
- Chinese and English action labels remain correct where localization exists.
- TypeScript checking, focused Vitest suites, production build, and `git diff --check` pass.

## Non-Goals

- No backend API or persistence changes.
- No changes to task state semantics.
- No redesign of detail pages, forms, modals, or dashboards.
- No replacement of Ant Design Table.
- No global typography or navigation redesign.
