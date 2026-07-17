# 构建与测试基线

## 环境

- Python 3.11+，依赖见 `ml-platform/backend/requirements.txt`。
- 深度学习算子验收需额外安装 PyTorch CPU；CI 使用 `python -m pip install torch --index-url https://download.pytorch.org/whl/cpu`。
- Node.js 20+ 与 npm，依赖以 `ml-platform/frontend/package-lock.json` 为准。
- Docker Compose 为可选部署验收依赖；当前开发机未安装。

## 后端

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform\backend
python -m pip install -r requirements.txt
python run_suite.py
```

`run_suite.py` 为每个模块创建独立临时 SQLite 数据库、Artifact 目录和系统临时目录。2026-07-15 当前验收结果为 33/33 模块通过，最新约 182.4 秒。

按周验收：

```powershell
python run_suite.py --week 1
python run_suite.py --week 2
python run_suite.py --week 3
python run_suite.py --week 4
```

当前周次结果依次为 16/16、7/7、7/7、3/3。`tests/test_suite_manifest.py` 保证每个后端测试模块恰好归属一个周次，`tests/test_module_imports.py` 导入全部 `app.*` 模块并检查已移除的框架 API。

单模块和 Join 回归：

```powershell
python -m unittest tests.test_api_runs -v
python -m unittest tests.test_operators_extended.TestBlendingOperators -v
```

## 前端

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform\frontend
npm install
npm test
npm run build
```

当前验收结果为 14/14 测试文件、35/35 测试通过，TypeScript 与 Vite 生产构建通过。`src/weekAcceptance.test.ts` 校验全部前端测试文件的周次归属，`src/moduleImports.test.ts` 导入 API、组件、国际化、页面和 Store 生产模块。React Router future flag、React `act` 和 jsdom `getComputedStyle` 测试环境告警已清理。路由懒加载后首屏依赖块均低于 500 kB；ECharts 懒加载 chunk 约 1.13 MB。CI 应优先使用 `npm ci`。

## 浏览器验收

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform\frontend
npx playwright install chromium
npx playwright test --project=chromium
```

焊接质量主流程覆盖登录、项目创建、数据上传、Artifact 模板实例化、六节点执行终态和 metrics。2026-07-14 最新结果为 1/1 通过，用例约 7.7 秒；已重复执行验证。

## 本地服务验收

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform
.\scripts\start.ps1
.\scripts\health-check.ps1
.\scripts\stop.ps1
```

Windows 已验证健康、登录和端口释放。Ubuntu 使用对应 `.sh` 脚本，真实执行等待 GitHub Actions。

## Docker

```powershell
cd E:\codex_workspace\agent_spot_welding
docker compose config
docker compose build
docker compose up -d
```

启动后检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

2026-07-17 已在 WSL2 Docker 29.6.2 / Compose 5.3.1 验证生产镜像构建、Alembic 迁移、MinIO bucket 初始化、API/Worker 启动和四项 readiness。生产栈聚焦验收命令为：

```bash
RUN_PRODUCTION_INTEGRATION=1 python -m unittest tests.test_production_stack -v
```

该入口会清空目标数据库业务表，只能连接专用测试数据库。普通 `python run_suite.py --week 5` 会明确跳过真实服务测试。

## 验收口径

- 后端标准套件退出码为 0。
- 前端测试与构建退出码为 0。
- Playwright 主流程退出码为 0。
- Windows 启动、健康、登录、停止和端口释放全部通过。
- Ubuntu 验收以真实 GitHub Actions 为准；Run `29381233328` 的 Ubuntu 22.04 质量门禁和 Chromium 验收均成功，第四周已完成。
- WSL2 补充验证中，前端 Linux 依赖安装、35 个测试和生产构建已执行；后端 32/33 模块通过，唯一失败为本地虚拟环境未安装可选 PyTorch，安装上述 CPU 包后需重跑 `python run_suite.py --week 3` 或全量入口。
- 测试数据库、上传目录和临时制品不得复用生产数据。
- 当前第五周验证：后端 45/45、第五周 12/12、WSL 生产栈 4/4、前端 35/35、构建、Chromium 1/1、npm audit 0 漏洞。GitHub Actions `production-integration` 成功证据仍是周完成门禁。
