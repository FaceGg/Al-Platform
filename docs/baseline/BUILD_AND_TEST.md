# 构建与测试基线

## 环境

- Python 3.11+，依赖见 `ml-platform/backend/requirements.txt`。
- Node.js 20+ 与 npm，依赖以 `ml-platform/frontend/package-lock.json` 为准。
- Docker Compose 为可选部署验收依赖；当前开发机未安装。

## 后端

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform\backend
python -m pip install -r requirements.txt
python run_suite.py
```

`run_suite.py` 为每个模块创建独立临时 SQLite 数据库，2026-07-14 当前验收结果为 31/31 模块通过，最新约 199.1 秒。

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

当前验收结果为 9/9 测试文件、26/26 测试通过，TypeScript 与 Vite 生产构建通过。测试仍输出 React Router future flag、React `act` 和 jsdom `getComputedStyle` 告警；构建主包 2,621.11 kB。CI 应优先使用 `npm ci`。

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

Docker 命令当前未在本机验证，不能据 Compose 文件存在声明容器交付完成。

## 验收口径

- 后端标准套件退出码为 0。
- 前端测试与构建退出码为 0。
- Playwright 主流程退出码为 0。
- Windows 启动、健康、登录、停止和端口释放全部通过。
- Ubuntu CI 成功前，第四周只能保持进行中。
- 测试数据库、上传目录和临时制品不得复用生产数据。
