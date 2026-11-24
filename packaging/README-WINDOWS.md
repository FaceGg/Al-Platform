# Linkraft Windows 安装部署（Docker Desktop）

Windows 包（`linkraft-windows-*.zip`）与 Ubuntu 包来自同一棵源码树：同样的 compose
服务定义、同样的 legacy-cpu 镜像钉版、同样的迁移链。差异只在宿主机入口脚本
（PowerShell 取代 bash）与平台专有步骤（防火墙/文件权限/存储属主）。`compose-windows.ps1`
额外叠加 `docker-compose.windows.yml` 覆盖：把 legacy-cpu 硬编码的构建网络 `host` 回落为默认桥接（Docker Desktop 兼容），镜像源可达性不受影响。
服务定义、同样的 legacy-cpu 镜像钉版、同样的迁移链。差异只在宿主机入口脚本
（PowerShell 取代 bash）与平台专有步骤（防火墙/文件权限/存储属主）。

## 环境要求

- Windows 10 22H2 / Windows 11 / Windows Server 2019+，4 vCPU，8 GB 内存，至少 40 GB 可用磁盘。
- **Docker Desktop**（WSL2 后端），版本需自带 **Docker Compose v2.24.4+**（compose 覆盖文件使用 `!override` 语法）。安装时勾选 "Use WSL 2 based engine"；WSL2 未启用时按 Docker Desktop 提示执行 `wsl --install`。
- 主平台对外端口 TCP `5175`，审核员门户 TCP `8443`（防火墙放行；安装脚本在管理员会话下自动加规则）。
- 首次构建需访问 Docker Hub 与 pip/npm 镜像源（默认 aliyun/npmmirror，可用 `PIP_INDEX_URL` / `NPM_REGISTRY` 覆盖）。
- MinIO 同样钉在 CPUv1 镜像（老 CPU 兼容口径与 Ubuntu 版一致，见下「CPU 兼容性」）。

## 安装（新部署）

```powershell
Expand-Archive .\linkraft-windows-<VERSION>.zip -DestinationPath C:\linkraft
cd C:\linkraft\linkraft-windows-<VERSION>
pwsh -File packaging\install-windows.ps1 -PublicOrigin http://SERVER_IP:5175
```

（无 pwsh 时用自带 Windows PowerShell：`powershell -ExecutionPolicy Bypass -File packaging\install-windows.ps1 ...`）

脚本行为：预检 Docker Desktop 与 Compose 版本 → 生成 `.env`（全部秘钥用 .NET 随机数生成；`-AdminInitialPassword` 可统一初始口令）→ 生成 `secrets\notification_master_key` → 校验 compose 配置 → 构建镜像 → 启动全栈 → 轮询健康端点（最长 6 分钟）。管理员会话下自动放行 5175/8443 防火墙规则；非管理员只打印建议命令。

安装完成后浏览器打开 `http://SERVER_IP:5175/`，审核员门户 `http://SERVER_IP:8443/`。若 Windows 防火墙弹窗，选择「允许访问」。

**端口/源速记**：`-PublicOrigin` 是浏览器看到的完整源（默认 5175 端口），必须与浏览器地址栏完全一致；5173 直连前端属另一源，需 `-PublicOriginAliases` 显式加入。`-PublicPort` / `-AnnotatorPort` 可改对外端口。

`.env` 与 `secrets\` 含全部凭据：已用 icacls 收敛到当前用户，务必妥善备份，绝不能提交到代码仓库。

## 升级（保留 .env / secrets / 数据库）

```powershell
Expand-Archive .\linkraft-windows-<新版本>.zip -DestinationPath C:\linkraft-merge -Force
# 将新包内容覆盖到现有部署目录（保持 .env / secrets\ 不动）
Copy-Item C:\linkraft-merge\linkraft-windows-<新版本>\* C:\linkraft\linkraft-windows-<旧版本>\ -Recurse -Force
cd C:\linkraft\linkraft-windows-<旧版本>
pwsh -File packaging\install-windows.ps1 -PublicOrigin http://SERVER_IP:5175
```

安装脚本对既有 `.env` 只补缺失键（初始 admin 口令/门户签名密钥/CORS 源等），不覆盖既有秘钥；数据库迁移由 `migrate` 容器自动执行，完成后先看迁移日志再验收业务：

```powershell
pwsh -File packaging\compose-windows.ps1 logs migrate
pwsh -File packaging\compose-windows.ps1 ps
```

r19（重打版）起 compose 新增 `neo4j` 服务（知识图谱图存储投影，仅内网不暴露宿主端口，密码 `.env` 的 `NEO4J_PASSWORD`，默认 `kgdevpass123` 建议生产显式设置）。不启动 neo4j 也不影响平台——图存储投影自动降级 PostgreSQL。升级重建命令：

```powershell
pwsh -File packaging\compose-windows.ps1 up -d --build --force-recreate backend worker scheduler frontend annotator annotator-frontend neo4j
```

## 运维操作

```powershell
pwsh -File packaging\compose-windows.ps1 ps                       # 服务状态
pwsh -File packaging\compose-windows.ps1 logs --tail=200 worker   # 尾随日志
pwsh -File packaging\compose-windows.ps1 restart backend          # 重启单个服务
pwsh -File packaging\uninstall-windows.ps1                        # 停止并移除容器（保留数据卷/.env/secrets）
pwsh -File packaging\compose-windows.ps1 down -v                  # 彻底清除（含数据卷，不可恢复）
```

开机自启：Docker Desktop 设置勾选 "Start Docker Desktop when you log in"；容器均为 `restart: unless-stopped`，宿主机重启且 Docker Desktop 启动后全栈自动拉起。

## 常见问题

- **`docker` 命令找不到 / 守护进程不可用**：Docker Desktop 未安装或未启动；任务栏鲸鱼图标必须在运行状态。
- **`docker compose` 版本过旧**：升级 Docker Desktop 至自带 Compose ≥ 2.24.4 的版本（4.30+）。
- **浏览器打不开但本机 `curl http://127.0.0.1:5175/health` 正常**：防火墙未放行（管理员运行安装脚本，或手动加规则）；远程访问一律用服务器 IP 而非 `localhost`。
- **用 `localhost` 请求偶发超时**：Windows 对 `localhost` 可能解析到 IPv6，统一用 `127.0.0.1`。
- **构建/IO 慢**：Windows 路径经 WSL2 文件共享有开销；对 IO 敏感时可把部署目录放在 WSL 发行版文件系统内（`\\wsl$\` 下），或接受默认性能。
- **WSL2 内存不足**：全栈 + neo4j 建议 `.wslconfig` 至少 8GB；可用 `%UserProfile%\.wslconfig` 限制/上调并 `wsl --shutdown` 后重启 Docker Desktop。

## CPU 兼容性

与 Ubuntu 包同口径：MinIO 钉 `minio/minio:RELEASE.2025-07-23T15-54-02Z-cpuv1`、mc 钉 `RELEASE.2025-07-21T05-28-08Z-cpuv1`（老 CPU 无 x86-64-v2 指令也能跑）；Python 服务基于 `python:3.11-slim-bookworm`、前端构建基于 Debian Node 20 的 legacy Dockerfile。Docker Desktop 的引擎跑在 WSL2 虚拟机内，CPU 指令直通，老主机同样受此约束。如镜像拉取被拒（`pull access denied`），配置镜像加速器或提前导入同名镜像。

## 启用自编码器族（可选 torch，默认不装）

无监督异常检测的 AutoEncoder 族依赖 PyTorch，默认构建不安装（该族在算法目录自动缺席）。需要启用时在构建前设置环境变量 `WITH_TORCH=1`：

```powershell
$env:WITH_TORCH = "1"
pwsh -File packaging\install-windows.ps1 -PublicOrigin http://SERVER_IP:5175
```

torch 经 `--find-links` 从 PyTorch 官方 CPU wheel 目录（download.pytorch.org/whl/cpu/torch/）拉取——不要用默认 PyPI 源（会装 CUDA 版，带 GB 级 nvidia 依赖链）。
