# 第四周验收记录

> 验收日期：2026-07-14
> 当前结论：本地功能与 Windows 交付路径通过；Ubuntu GitHub Actions 尚无真实运行证据，第四周状态保持“进行中”。

## 功能验收

| 验收项 | 结果 | 证据 |
|---|---|---|
| 真实焊接数据准备 | 通过 | 1,976 行、43 列，Fault 1,897/79，服务测试通过 |
| 四套工业模板契约 | 通过 | 未知算子、参数、端口、输入和输出校验测试 |
| 四模板真实执行 | 通过 | 后端 E2E 连续运行，四个 WorkflowRun 和预期 NodeRun 输出完成 |
| Artifact 模板向导 | 通过 | 适配器/页面 4 项聚焦测试；项目创建、数据集选择和语义参数提交 |
| 浏览器主流程 | 通过 | Chromium 登录、项目、上传、实例化、6 节点运行、metrics；重复运行通过 |
| Windows 本地部署 | 通过 | start、health、登录、stop、PID 清理和端口释放 |
| Ubuntu 本地部署 | 待外部验证 | Bash 语法通过，真实执行由 GitHub Actions Ubuntu 22.04 负责 |

## 最新完整验证

| 命令 | 结果 | 耗时/告警 |
|---|---|---|
| `backend/python run_suite.py` | 31/31 隔离模块通过 | 最新约 199.1 秒 |
| `frontend/npm test` | 9/9 文件、26/26 测试通过 | 约 10.2 秒；保留 Router future、React act、jsdom 告警 |
| `frontend/npm run build` | 成功 | 约 10.3 秒；JS 2,621.11 kB，gzip 846.97 kB |
| `frontend/npx playwright test --project=chromium` | 1/1 通过 | 用例约 7.7 秒，总耗时约 16.5 秒 |
| Windows 脚本验收 | 通过 | 后端 ok、前端 200、管理员登录成功、8000/5173 释放 |
| Bash `-n` | 通过 | 使用 `D:\software\Git\bin\bash.exe` |
| CI YAML 解析 | 通过 | `quality`、`browser-acceptance` 两个 job |

## 已知告警与风险

- 前端主包超过 500 kB，后续按路由拆包。
- jsdom 测试仍有 `act` 和 `getComputedStyle` 环境告警。
- 后端工作流仍是单进程后台线程，不支持服务重启恢复和硬终止。
- SQLite、本地 Artifact 目录和默认密钥不属于生产部署方案。
- XGBoost 输出 `use_label_encoder` 未使用告警，不影响本轮结果，后续清理无效参数。

## 外部验收缺口

`.github/workflows/ci.yml` 已配置 Windows/Ubuntu 质量矩阵和 Ubuntu Chromium 验收，但当前工作区未提交、未推送，因此没有可记录的 workflow URL。必须在真实 GitHub Actions 的 Ubuntu job 成功后，才能将第四周标记为“已完成”。
