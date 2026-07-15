# 第四周验收记录

> 验收日期：2026-07-15
> 当前结论：本地功能、Windows 交付路径、Ubuntu 22.04 质量门禁和 Ubuntu Chromium 验收全部通过，第四周状态为“已完成”。

## 功能验收

| 验收项 | 结果 | 证据 |
|---|---|---|
| 真实焊接数据准备 | 通过 | 1,976 行、43 列，Fault 1,897/79，服务测试通过 |
| 四套工业模板契约 | 通过 | 未知算子、参数、端口、输入和输出校验测试 |
| 四模板真实执行 | 通过 | 后端 E2E 连续运行，四个 WorkflowRun 和预期 NodeRun 输出完成 |
| Artifact 模板向导 | 通过 | 适配器/页面 4 项聚焦测试；项目创建、数据集选择和语义参数提交 |
| 浏览器主流程 | 通过 | Chromium 登录、项目、上传、实例化、6 节点运行、metrics；重复运行通过 |
| Windows 本地部署 | 通过 | start、health、登录、stop、PID 清理和端口释放 |
| Ubuntu 本地部署 | 通过 | Bash 语法通过；GitHub Ubuntu 22.04 完成后端、前端、构建和服务启停冒烟 |

## 最新完整验证

| 命令 | 结果 | 耗时/告警 |
|---|---|---|
| `backend/python run_suite.py` | 31/31 隔离模块通过 | 最新约 199.1 秒 |
| `frontend/npm test` | 当前 11/11 文件、30/30 测试通过 | Router future、React act、jsdom 告警已清理 |
| `frontend/npm run build` | 成功 | 页面按路由懒加载；ECharts 懒加载 chunk 约 1.13 MB |
| `frontend/npx playwright test --project=chromium` | 1/1 通过 | 用例约 7.7 秒，总耗时约 16.5 秒 |
| Windows 脚本验收 | 通过 | 后端 ok、前端 200、管理员登录成功、8000/5173 释放 |
| Bash `-n` | 通过 | 使用 `D:\software\Git\bin\bash.exe` |
| CI YAML 解析 | 通过 | `quality`、`browser-acceptance` 两个 job |
| GitHub Windows 质量门禁 | 通过 | Actions Run `29381233328`，后端、前端、构建和服务冒烟成功 |
| GitHub Ubuntu 22.04 质量门禁 | 通过 | Actions Run `29381233328`，后端、前端、构建和服务冒烟成功 |
| GitHub Ubuntu Chromium | 通过 | Actions Run `29381233328`，Playwright 焊接质量主流程成功 |

## 已知告警与风险

- 前端主包超过 500 kB，后续按路由拆包。
- 前端测试环境告警已清理；继续关注真实浏览器与 jsdom 行为差异。
- 后端工作流仍是单进程后台线程，不支持服务重启恢复和硬终止。
- SQLite、本地 Artifact 目录和默认密钥不属于生产部署方案。
- XGBoost 无效的 `use_label_encoder` 参数已删除，并由回归测试防止重新引入。
- GitHub action 已在本地升级到 `checkout@v5`、`setup-node@v5`、`setup-python@v6`，待推送后由新一轮远程 CI 确认。

## 交付状态

第四周交付分支已推送，[GitHub Actions Run 29381233328](https://github.com/FaceGg/Al-Platform/actions/runs/29381233328) 的三项检查全部成功，[PR #1](https://github.com/FaceGg/Al-Platform/pull/1) 检查全绿且可合并。PR 当前仍为 Draft，合并到 `main` 属于后续仓库集成操作，不再构成第四周功能与验收缺口。
