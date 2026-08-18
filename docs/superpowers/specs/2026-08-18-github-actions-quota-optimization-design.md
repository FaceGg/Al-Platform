# GitHub Actions 配额优化与定时清理设计

**日期：** 2026-08-18
**状态：** 已确认，等待规格审阅
**范围：** `E:\\codex_workspace\\agent_spot_welding` 的 GitHub Actions 工作流与 CI YAML 契约测试。

## 目标

在不降低合并前基础质量门禁的前提下，降低重复 CI 和高成本 Docker 验证造成的 GitHub Actions 用量；同时自动回收不再需要的 Actions 数据。

成功标准如下：

- 新提交会取消同一 PR 或同一分支上已过时、仍在执行的 CI。
- PR 持续执行跨平台质量门禁和 Chromium 验收。
- Docker Compose、生产集成、实验集成和 Week 11-12 安全冻结栈只在 `main` 推送、每周定时验证或手动 `full` 模式执行。
- Artifact、cache 和已完成运行按明确阈值回收，且不会清理进行中的运行。
- CI 配置规则由自动化测试覆盖，防止未来改动重新扩大默认执行范围或删除保护条件。

## 现状与约束

当前 `ci.yml` 对 `main`/`develop` 推送和面向 `main` 的 PR 都运行跨平台质量、Chromium、生产集成、实验集成和 Week 11-12 验证。后面三项包含服务启动、Docker 镜像构建或安全扫描，是主要用量来源。

`actions/setup-python` 和 `actions/setup-node` 已启用依赖缓存；本设计不增加重复的缓存 action。仓库的 Artifact/日志默认保留期当前为 90 天，远端缓存和 Artifact 均可单独删除。

已确认保留策略：

| 数据 | 保留期 | 说明 |
| --- | ---: | --- |
| 失败证据 Artifact | 7 天 | Playwright、生产集成和实验集成失败证据。 |
| Week 11-12 验收与安全证据 Artifact | 14 天 | 每次完整验证产生的可审计证据。 |
| Actions cache | 7 天未访问 | 只删除最后访问时间早于阈值的 cache。 |
| 已完成 workflow run 及日志 | 30 天 | 仅删除 `completed` 的历史运行。 |

## 备选方案与决策

### 方案 A：PR 轻量门禁，主分支/定时任务运行重验证（采用）

- PR：质量矩阵与 Chromium 验收。
- `main` 推送：完整验证。
- 每周定时：完整验证。
- 手动触发：调用者显式选择 `light` 或 `full`。

该方案保留每个 PR 的跨平台测试和浏览器回归，同时将高成本 Docker 与安全验证移到可审计的合并后、定时和手动路径，最能降低常规开发迭代的额度消耗。

### 方案 B：保留所有 PR 全量验证，仅增加并发取消和清理（不采用）

覆盖面最高，但 Docker、镜像构建和安全扫描仍会随每次 PR 提交运行，无法有效控制配额。

### 方案 C：重验证仅手动或定时执行（不采用）

成本最低，但 `main` 合并后不会自动执行完整生产与安全验证，风险不可接受。

## 工作流设计

### 主 CI：`.github/workflows/ci.yml`

1. 保留 `push`（`main`、`develop`）和 `pull_request`（目标 `main`）触发器；增加每周一次的 cron，以及 `workflow_dispatch` 的 `mode` 输入，允许值为 `light` 和 `full`，默认 `light`。
2. 增加工作流级并发组。PR 使用 PR 编号，其他场景使用分支/引用；`cancel-in-progress: true`。这样同一 PR 或分支的新提交会取消旧运行，彼此独立的分支不会相互取消。
3. `quality` 在所有触发场景运行。
4. `browser-acceptance` 在所有触发场景运行，并继续依赖 `quality`。
5. `production-integration`、`experiment-integration` 和 `week11-12-verification` 仅在以下任一条件为真时运行：
   - `main` 分支的 `push`；
   - `schedule`；
   - `workflow_dispatch` 且 `mode == full`。
6. Week 11-12 job 的依赖关系继续保留；在轻量路径中，依赖项被跳过时该 job 也必须安全跳过，不得将跳过误报为成功的完整验收。
7. 为每个 `actions/upload-artifact@v4` 明确设置 `retention-days`：失败证据为 `7`，Week 11-12 验证证据为 `14`。

### 清理工作流：`.github/workflows/actions-cleanup.yml`

该工作流每周执行一次，提供手动触发入口用于验证和紧急回收。它使用仓库 API，并仅声明 `actions: write` 权限。

清理顺序和保护条件：

1. 查询 Artifact；删除创建时间早于其 Artifact 类别保留期的条目。名称匹配 `week11-12-verification-evidence` 使用 14 天阈值，其他 CI 失败证据使用 7 天阈值。
2. 查询 Actions cache；仅删除最后访问时间早于 7 天的条目。
3. 查询 workflow runs；仅删除创建时间早于 30 天且 `status == completed` 的运行。`queued`、`in_progress`、`waiting` 或其他非完成状态一律不删除。
4. 分页读取 API 返回值；单个资源删除失败时记录失败并使 job 失败，避免将部分回收误报为成功。
5. 仅访问当前仓库的 Actions API；不访问 release、源代码、issue、PR、仓库设置或业务数据。

删除已完成 workflow run 会一并删除其日志。Artifact 若先被 API 删除，后续运行删除不会误判为数据异常；删除端点返回不存在时应作为可说明的竞态跳过并继续处理。

## 测试与验证

扩展 `ml-platform/backend/tests/test_ci_workflow.py`，使用 YAML 解析测试以下契约：

- 触发器包含手动模式和每周 schedule，且 `mode` 的默认值与可选值明确。
- 并发组基于 PR 或分支隔离，并启用取消旧运行。
- PR 路径仍运行质量和 Chromium；重 job 条件只允许 `main` push、schedule 与手动 full。
- 所有 Artifact 上传点的 `retention-days` 与表中阈值一致。
- 清理工作流仅声明 `actions: write`，具有 schedule/手动入口、分页查询与对应 API 删除调用。
- 清理脚本对 Artifact、cache 和 workflow run 分别使用 7、7、30 天；run 删除前强制检查完成状态。

实施后执行该测试模块、YAML 解析检查、`git diff --check`，并使用 GitHub CLI 做只读工作流语法/远端确认。由于当前 Actions 配额或账单可能阻止 runner 启动，远端触发失败不能被解释为代码或 YAML 验证失败；本地验证和远端实际运行将分别记录。

## 非目标

- 不修改业务代码、Docker Compose、依赖版本、required checks 或分支保护规则。
- 不删除 Release、Git 标签、仓库源码、Issue、Pull Request 或业务 Artifact。
- 不改变现有 pip/npm 缓存键，也不增加重复缓存 action。
- 不把跳过的完整验证标记为完整 CI 通过。

## 风险与缓解

| 风险 | 缓解措施 |
| --- | --- |
| PR 中的 Docker/安全回归延后发现 | `main` 推送、周度定时任务和手动 full 仍执行完整验证。 |
| 错误删除审计证据 | 证据类别分开设定 7/14 天，删除前按创建时间和名称判定。 |
| 清理运行中任务 | workflow run 删除前只接受 `completed` 状态。 |
| 新提交造成无谓费用 | 同一 PR/分支使用并发取消，独立分支相互隔离。 |
| 远端 runner 无法启动 | 将 billing/quota 阻塞与代码验证分开记录，不循环重试消耗额度。 |
