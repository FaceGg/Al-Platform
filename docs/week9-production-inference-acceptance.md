# 第九周生产推理验收记录

## 结论

Week 9 代码、前端和本地 WSL 真实生产栈门禁已完成，周状态仍为“进行中”。GitHub Actions 远程 CI、最终全量证据和合并仍是必须的剩余门禁；本地 SQLite、mock runtime 或跳过的 integration test 不计作生产通过。

## 已取得证据

| 范围 | 结果 |
|---|---|
| Week 8 backend | `run_suite.py --week 8`: 7/7 modules |
| Week 9 backend | `run_suite.py --week 9`: 7/7 modules |
| Task 10 focused backend | 29 tests passed; production stack 2 tests explicitly skipped without opt-in |
| Frontend unit | 19 files, 64 tests passed |
| Frontend build | TypeScript check and Vite production build passed |
| Backend compile | `compileall -q app alembic` passed |
| Chromium | 3/3 passed: core routes, production model release lifecycle, welding quality |
| Migration contract | Week 9 head is `20260720_09_production_inference` in source and tests |
| Workspace hygiene | `git diff --check` passed |
| WSL production stack | Docker Server `29.6.2` / Compose `v5.3.1`; isolated PostgreSQL, Redis, MinIO, Celery and runtime lifecycle passed |
| WSL migration/readiness | `alembic upgrade/current/check` at `20260720_09_production_inference`; `/api/ready` returned every dependency as ready |
| WSL service acceptance | experiment integration `1/1`, rollout/restart/rollback/rate-limit integration `1/1`, Redis fail-closed integration `1/1` |

Chromium was run with the bundled Miniconda interpreter on `PATH`. The first default-shell attempt exited 9009 because Windows `python.exe` resolved to the Microsoft Store alias; this is an environment issue, not an application result.

## 前端依赖审计受限例外

`npm audit --audit-level=high --registry=https://registry.npmjs.org` 当前报告 React Router `7.12.0-8.2.0` 的 RSC Mode CSRF advisory（2 个 high）。本项目固定 `react-router-dom@7.18.1`，为 Vite 静态 SPA：入口只使用 `BrowserRouter`，源码未导入 `react-router-dom/server`、`react-router/server`、`react-server`、`createStatic*` 或 RSC/SSR 路径；HTTP 服务端实现由 FastAPI 提供，未启用 React Router Actions 或 Server Actions。

审计建议的强制降级 `7.11.0` 经实际安装和复查后会暴露 14 个更早的 React Router high advisories，因此不是可接受的修复。该结论不等同于 audit 通过：当前仅在上述 SPA 边界内接受受限例外。任何 React Router RSC、SSR、prerender、server handler、Action/Server Action 引入，或出现不含这些 advisories 的兼容版本时，必须先重新评估依赖并恢复 audit 零 high 门禁。

## Task 10 coverage

- Isolated CI Compose project name and unique teardown.
- Runtime URL, internal secret, rate-limit and rollout observation settings propagated to backend, worker, scheduler and inference runtime.
- Production migration upgrade/check and gated `TestInferenceProductionStack` lifecycle.
- Rollout to completion, API Key creation/redaction, Redis outage fail-closed check, runtime restart/reconcile and rollback.
- Failure evidence scans a transient raw copy for configured secrets and every `mli_...` token, copies only clean files for redaction, deletes raw evidence, and removes both evidence directories if copy/redaction fails before uploading only the redacted artifact.
- Chromium covers two model versions, 100% rollout, pause/resume, rollback, one-time key display, online inference version switch and viewer read-only controls.

## Remaining gates

1. Commit this verified delivery set, including both browser E2E fixtures, and run the CI production-integration job from that exact commit with PostgreSQL, Redis, MinIO, Celery and inference runtime.
2. Record the remote Actions URL, image digest and remote redaction-scan result; compare them with the local migration head and readiness evidence above.
3. Complete remaining Task 11 local frontend/security gates and remote CI evidence, then freeze the Week 9 contracts before Week 10 production verification.

No credentials, API-key plaintext, prediction records, object-storage URIs or raw tracebacks belong in this document or uploaded evidence.
