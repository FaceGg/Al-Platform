# Unified Task Delete Confirmation Design

## Goal

All task-list delete actions use the same confirmation interaction before any delete request is sent. This covers single-row icon actions and toolbar batch-delete actions.

## Scope

- Data annotation task list.
- AutoML modeling task list.
- Model training experiment and training-job lists.
- Application orchestration task and agent lists.
- Existing task-list batch-delete controls in these workflows.
- Other task-style tables that already use the shared row-action pattern when they expose a delete command.

Non-task content deletion, such as annotation-rule tokens, label options, knowledge documents, and notification items, is outside this change.

## Interaction Contract

- Delete remains a red trash icon for row actions.
- Clicking an enabled delete control opens an Ant Design `Popconfirm`.
- Placement is `topRight`.
- Title is the localized equivalent of `Confirm deletion?`.
- Single-row description identifies the target and states that deletion cannot be undone.
- Batch description includes the selected count and states that deletion cannot be undone.
- Confirm text is the localized delete label and uses a danger button.
- Cancel text is the localized cancel label.
- Disabled controls do not open a confirmation popup.
- Delete handlers run only from `onConfirm`, never from the initial button click.

## Component Design

Create a shared confirmation wrapper that owns the common `Popconfirm` configuration. Compose it with `TableRowAction` for icon-only row actions and allow a supplied child button for batch actions.

The wrapper accepts:

- accessible delete label;
- target name or batch count;
- confirmation callback;
- disabled/loading state;
- optional custom description for domain-specific consequences;
- child control when the caller is a toolbar action.

The shared component must not own API calls or page state.

## Migration Rules

- Replace direct row-delete handlers with the shared confirmation component.
- Replace `window.confirm`, page-specific `Modal.confirm`, and page-local `Popconfirm` delete configurations in task lists.
- Preserve existing eligibility rules, API endpoints, loading behavior, and success/error messages.
- Preserve non-delete confirmations such as stop or revoke actions.
- Preserve current localized object names in accessible labels.

## Error Handling

- Closing or cancelling the popup performs no request.
- API failures continue to use each page's existing error message path.
- The confirmation popup closes after confirmation; page loading state prevents duplicate submissions where already supported.

## Verification

- Shared component tests cover open, cancel, confirm, danger styling, disabled state, and batch child controls.
- Page tests assert that clicking delete alone does not call the API.
- Page tests assert that confirming calls the existing endpoint once.
- Data annotation tests no longer mock `window.confirm`.
- Focused tests cover AutoML, training jobs, data annotation, orchestration, and other migrated task-list pages.
- Run frontend production build and `git diff --check`.

## Compatibility

- Keep Ant Design and the existing `TableRowAction` visual language.
- Use existing i18n labels where available, with Chinese and English fallbacks in the shared component.
- No backend API or persistence changes are required for this UI consistency change.
