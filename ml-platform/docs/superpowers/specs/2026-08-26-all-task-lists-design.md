# All Task Lists Design

## Goal

Make the AutoML, model training, data annotation, and orchestration task lists show every task the current user may access by default. Every list displays the task project and creator, while an optional project filter narrows the result without changing authorization.

## Shared List Contract

- Omitting `project_id` returns tasks from all projects where the current user has read access.
- Supplying `project_id` verifies project access and returns only that project's tasks.
- Task rows expose `project_id`, `project_name`, `created_by_id`, and `created_by_name`.
- Lists remain ordered newest first.
- Project selectors use an explicit `All projects` option as their default.
- Creation forms still require a concrete project.

## AutoML And Training

`TrainingJob` already stores `project_id` and `user_id`. Its serializer will expose the related project name and username. AutoML and training list endpoints already support an omitted project filter, so the frontend will stop selecting the first project as the implicit list scope. Both task tables will display project and creator columns.

## Data Annotation

The quality-run endpoint will change `project_id` from required to optional. Without it, the query is restricted to accessible project IDs. The task page will load all runs by default and use the existing project selector only as a filter. Opening, deleting, or editing a task continues to use the row's actual project ID.

## Orchestration

`AgentTask` will gain nullable `project_id` and `created_by_id` columns with relationships to `Project` and `User`. New standalone tasks require a project and persist the authenticated creator. Workflow-backed tasks use the workflow project and authenticated creator.

For historical rows, serialization falls back to the related workflow's project and workflow creator when direct task fields are null. Old standalone tasks that cannot be attributed display `-`; they remain visible only under the existing legacy ownership/access behavior. New project-scoped tasks use project authorization for list, detail, mutation, and deletion operations.

## Frontend Behavior

- Default list scope is all accessible projects.
- Selecting a project reloads only that project's tasks.
- The project and creator columns use names first and IDs as fallback.
- Empty, loading, refresh, delete, and detail behavior remain unchanged.
- Chinese and English labels are added through the existing i18n namespaces.

## Error And Permission Handling

- An inaccessible explicit project filter returns the existing authorization error.
- Cross-project default lists never expose inaccessible tasks.
- Missing legacy project or creator information renders `-` and does not cause the list request to fail.
- Task actions resolve authorization using the persisted project or workflow fallback.

## Verification

- Backend tests cover default cross-project results, explicit filtering, inaccessible-project exclusion, creator/project serialization, and legacy orchestration fallback.
- Frontend tests cover default unfiltered requests, project filtering, and project/creator columns for all four lists.
- Run focused backend and frontend tests, frontend production build, Python compilation, and `git diff --check`.
- Update `DEVELOPMENT_PLAN.md` and the shared development experience after implementation.
