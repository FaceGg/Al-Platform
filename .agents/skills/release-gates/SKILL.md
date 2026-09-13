---
name: release-gates
description: Run and interpret repository release, acceptance, CI, Docker, security, and evidence gates. Use only for release readiness, acceptance, publication, or remote-gate requests.
---

# Release Gates

## Required evidence

- Bind every result to the current commit SHA and record the actual branch and
  working-tree state.
- Record the command, environment, and structured result.
- Distinguish `passed`, `failed`, `skipped`, `cancelled`, `not_run`, and
  environment-blocked.
- Treat any required failure, cancellation, or skip as not release-ready.
- Do not use a previous SHA, an agent report, or a generated file's existence as a
  substitute for current verification.

## Execution

1. Inspect Git state and current workflow inputs.
2. Run focused gates first, then module, build, browser, runtime, security, and
   remote gates according to the requested scope.
3. Use `continue-on-error` only when preserving failure evidence is required.
   Recompute the final result from evidence files.
4. Clean only task-owned temporary resources. Do not delete user data or unrelated
   artifacts.
5. Report release readiness separately from task completion.
