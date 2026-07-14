# Windows 部署说明

## 环境要求

- Windows 10/11 或 Windows Server 2019+
- Python 3.10+
- Node.js 18+、npm
- 可写的数据库、Artifact 和运行目录
- 默认端口 `8000`、`5173` 未被占用

## 安装

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform\backend
python -m pip install -r requirements.txt

cd ..\frontend
npm ci
```

复制项目根目录 `.env.example` 中需要的配置到实际环境。生产环境必须修改 `SECRET_KEY`，并按部署目录设置 `DATABASE_URL`、`ARTIFACT_STORAGE_DIR` 和 `ML_PLATFORM_RUNTIME_DIR`。

## 启停与健康检查

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform
.\scripts\start.ps1
.\scripts\health-check.ps1
.\scripts\stop.ps1
```

也可双击或执行 `start.bat`。启动成功后访问：

- 前端：`http://127.0.0.1:5173`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/api/health`

默认管理员仅用于首次本地验证：`admin / admin123`。正式部署后应创建受控账号并限制默认账号使用。

## 自定义端口和运行目录

```powershell
.\scripts\start.ps1 -BackendPort 8010 -FrontendPort 5180 -RuntimeDir D:\ml-platform-runtime
.\scripts\health-check.ps1 -BackendPort 8010 -FrontendPort 5180
.\scripts\stop.ps1 -RuntimeDir D:\ml-platform-runtime
```

运行目录保存 PID 和标准输出/错误日志。停止脚本会递归清理 npm、Vite 和 esbuild 进程树。

## 数据库重置

仅在确认不需要历史数据后执行：

1. 运行 `stop.ps1`。
2. 备份 `DATABASE_URL` 指向的 SQLite 文件和 Artifact 目录。
3. 删除或移动 SQLite 文件。
4. 重新启动，系统会创建表和默认管理员。

不要只删除数据库而保留需要追溯的 Artifact，也不要在服务运行时替换数据库文件。

## 常见故障

- **端口已占用**：运行 `Get-NetTCPConnection -State Listen -LocalPort 8000,5173`，停止确认过的进程或传入新端口。
- **前端依赖缺失**：进入 `frontend` 执行 `npm ci`。
- **后端导入失败**：确认使用安装了 `requirements.txt` 的 Python 环境。
- **健康检查失败**：查看运行目录下 `backend.err.log` 和 `frontend.err.log`。
- **停止后仍占端口**：先再次运行 `stop.ps1`，再核对 PID 对应命令行，禁止结束来源不明的系统进程。

## 已验证范围

2026-07-14 在 Windows 本机验证：启动、后端 `status=ok`、前端 HTTP 200、默认管理员登录、停止及端口释放全部成功。
