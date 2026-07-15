# 项目文件结构与清理规则

> 更新日期：2026-07-14

## 正式目录

| 路径 | 用途 |
|---|---|
| `ml-platform/backend/app` | FastAPI、模型、执行器、算子、服务和工业模板源码 |
| `ml-platform/backend/tests` | 后端 unittest 模块；由 `backend/run_suite.py` 统一执行 |
| `ml-platform/backend/tools` | 可重复使用的数据准备和维护工具 |
| `ml-platform/frontend/src` | React/TypeScript 正式源码和 Vitest 测试 |
| `ml-platform/frontend/e2e` | Playwright 浏览器验收与固定夹具 |
| `ml-platform/scripts` | Windows/Ubuntu 启停和健康检查 |
| `ml-platform/data/demo` | 可重复演示数据，不存放生产客户数据 |
| `docs/baseline` | 功能、接口、测试、技术债和文件结构基线 |
| `docs/delivery` | 部署、用户、演示和验收文档 |
| `docs/superpowers` | 已批准设计与实施计划 |
| `docs2` | 用户维护的 Word 文档资料，清理任务不自动修改 |
| `temp_test` | 项目开发、测试、构建和本地运行产生的临时文件；默认不提交 |

## 运行数据与生成物

以下路径不属于源码，不应提交 Git：

- `__pycache__`、`*.pyc`、`*.tsbuildinfo`
- `temp_test/*`（保留 `.gitkeep`）
- 历史位置 `temp_data`、`.runtime`、`.playwright-artifacts`、`dist`、`test-results`、`playwright-report`、`coverage`
- `*.db`、`*.log`、`*.err`、`*.pid`
- `artifact_store`、`uploads`、`exports`

数据库、上传文件、Artifact 和导出文件可能包含用户数据。常规清理只忽略，不直接删除；Artifact 仅在确认未被任何现存数据库引用后删除。

## 2026-07-14 清理结果

- 删除项目根目录和后端根目录中的一次性 `_fix`、`_write`、`append`、临时验证及旧集成脚本。
- 删除已被 `backend/tests`、`frontend/src/**/*.test.*` 和 `frontend/e2e` 替代的 `ml-platform/tests` 旧目录。
- 删除缓存、DataBus 临时目录、Playwright 生成物、测试数据库、旧日志、前端构建目录和 `tsbuildinfo`。
- 对三个现存 SQLite 数据库做只读 Artifact 引用检查，删除 59 个无引用测试 Artifact 目录，保留全部有引用目录。
- 保留生产 `ml_platform.db`、上传、导出、演示数据、DOCX 和所有正式开发文档。
- 清理后回归结果：后端 31/31 模块、前端 26/26 用例、生产构建和 Playwright Chromium 主流程 1/1 均通过；三个 Linux Shell 脚本通过 Git Bash 语法检查。

## 新文件准入

- 自动化测试放入现有测试目录，不在源码根目录创建 `test_*.py`。
- 一次性迁移脚本完成后删除；可重复工具放入 `backend/tools` 并写明输入、输出和验证方式。
- 调试日志、数据库和临时样本不得作为源码提交。
- 删除用户数据前必须确认所有权、数据库引用和可恢复备份。
- 新增临时文件默认写入项目根目录 `temp_test`；仅操作系统级短生命周期 `tempfile` 可使用系统临时目录。
