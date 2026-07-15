# Ubuntu 部署说明

## 环境要求

- Ubuntu 22.04 或 24.04
- Python 3.10+
- Node.js 18+、npm
- `curl`、`setsid`
- 默认端口 `8000`、`5173` 未被占用

## 安装

```bash
cd /opt/agent_spot_welding/ml-platform/backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

cd ../frontend
npm ci

cd ..
chmod +x scripts/*.sh
```

生产环境配置至少包括：

```bash
export DATABASE_URL='sqlite:////var/lib/ml-platform/ml_platform.db'
export ARTIFACT_STORAGE_DIR='/var/lib/ml-platform/artifacts'
export ML_PLATFORM_RUNTIME_DIR='/var/run/user/'"$UID"'/ml-platform'
export SECRET_KEY='<随机长密钥>'
```

相关目录必须由运行账号拥有，不能使用桌面数据源的 Windows 绝对路径。

## 启停与健康检查

```bash
cd /opt/agent_spot_welding/ml-platform
./scripts/start.sh
./scripts/health-check.sh
./scripts/stop.sh
```

自定义端口：

```bash
BACKEND_PORT=8010 FRONTEND_PORT=5180 ./scripts/start.sh
BACKEND_PORT=8010 FRONTEND_PORT=5180 ./scripts/health-check.sh
./scripts/stop.sh
```

脚本使用独立进程组和 PID 文件。服务日志位于 `ML_PLATFORM_RUNTIME_DIR`。

## 数据库与权限

- SQLite 数据库和 Artifact 目录应放在持久磁盘并定期整体备份。
- 重置前必须停止服务，同时备份数据库和 Artifact。
- 多实例或高并发部署不能继续使用 SQLite，应按后续计划迁移 PostgreSQL 和对象存储。

## 常见故障

- **Permission denied**：检查脚本执行位和数据目录所有权。
- **端口占用**：使用 `ss -ltnp | grep -E ':8000|:5173'` 定位。
- **健康检查失败**：读取 `backend.err.log`、`frontend.err.log`。
- **Node/Python 版本过低**：脚本会在启动前返回可操作错误。
- **停止后残留**：确认 PID 文件属于当前部署目录，再检查进程组。

## 验收状态

脚本已通过 Git Bash 和 WSL2 的 `bash -n` 语法检查。GitHub Actions Run `29381233328` 已在 Ubuntu 22.04 完成后端 31 模块、前端测试、生产构建、服务启停冒烟和 Chromium 主流程验收，Ubuntu 交付路径通过。当前 WSL2 已安装 Node.js 22/npm，并使用 `/home/jingms/venv` 的 Python 依赖完成启动、健康检查、默认管理员登录、停止和端口释放。Windows 与 WSL 的 `node_modules` 不可复用；本地通过 `ML_PLATFORM_FRONTEND_DIR` 指向 `temp_test/wsl-frontend` 的独立 Linux 依赖目录。
