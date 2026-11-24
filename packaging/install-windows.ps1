#requires -Version 5.1
<#
.SYNOPSIS
  LinkrAFT Windows 宿主机安装器（Docker Desktop / WSL2 后端）。

.DESCRIPTION
  与 packaging/install-ubuntu.sh 同口径：生成 .env 与 secrets/、校验 Compose
  配置、构建镜像、启动全栈并等待健康端点。平台差异：
  - 秘钥用 .NET RandomNumberGenerator 生成（无 openssl 依赖）；
  - 跳过存储属主修复（prepare-production-storage.sh 的 chown 1000:1000 是
    Linux bind mount 语义，Docker Desktop 的 Windows bind mount 无 UID 检查）；
  - 防火墙用 New-NetFirewallRule（非管理员会话仅打印建议命令，不硬失败）；
  - 文件权限用 icacls 收敛到当前用户（尽力而为）。

.EXAMPLE
  pwsh -File packaging\install-windows.ps1 -PublicOrigin http://SERVER_IP:5175
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\install-windows.ps1 -PublicOrigin http://127.0.0.1:15175 -PublicPort 15175 -AnnotatorPort 18443
#>
[CmdletBinding()]
param(
  # 浏览器访问平台的完整源（origin），如 http://SERVER_IP:5175；留空回落 localhost
  [string]$PublicOrigin = $env:PUBLIC_ORIGIN,
  # 额外放行的精确 CORS 源，逗号分隔
  [string]$PublicOriginAliases = $env:PUBLIC_ORIGIN_ALIASES,
  # 主平台对外端口（写入 NGINX_PORT）
  [string]$PublicPort = "5175",
  # 审核员门户对外端口（写入 ANNOTATOR_PORT）
  [string]$AnnotatorPort = "8443",
  [string]$FrontendBindAddress = $env:FRONTEND_BIND_ADDRESS,
  [string]$AnnotatorBindAddress = $env:ANNOTATOR_BIND_ADDRESS,
  [string]$AnnotatorCookieSecure = $env:ANNOTATOR_COOKIE_SECURE,
  # 统一初始 admin 口令（仅全新数据库首启生效）；留空则随机生成进 .env
  [string]$AdminInitialPassword = $env:ADMIN_INITIAL_PASSWORD,
  # 跳过防火墙配置（例如已在组策略放行）
  [switch]$SkipFirewall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root ".env"
$ComposeWrapper = Join-Path $PSScriptRoot "compose-windows.ps1"

function Write-Info([string]$Message) { Write-Host "[INFO] $Message" }
function Die([string]$Message) {
  Write-Host "[ERROR] $Message" -ForegroundColor Red
  exit 1
}

function Get-RandomHex([int]$ByteCount) {
  $bytes = [byte[]]::new($ByteCount)
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  ($bytes | ForEach-Object { $_.ToString("x2") }) -join ""
}

function Get-RandomUrlSafeBase64 {
  $bytes = [byte[]]::new(32)
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
  [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
}

function Restrict-Acl([string]$Path) {
  # 尽力而为：收敛到当前用户；失败仅提示（现场若有域策略可忽略）
  try {
    icacls $Path /inheritance:r /grant:r "$($env:USERNAME):F" | Out-Null
  } catch {
    Write-Info "文件权限收敛失败（已忽略）：$Path"
  }
}

function Get-EnvValue([string]$Key) {
  foreach ($line in (Get-Content -LiteralPath $EnvFile)) {
    if ($line -match ("^\s*" + [regex]::Escape($Key) + "\s*=")) {
      return ($line -split "=", 2)[1]
    }
  }
  return $null
}

function Test-EnvKey([string]$Key) {
  foreach ($line in (Get-Content -LiteralPath $EnvFile)) {
    if ($line -match ("^\s*" + [regex]::Escape($Key) + "\s*=")) { return $true }
  }
  return $false
}

function Set-EnvValue([string]$Key, [string]$Value) {
  $lines = New-Object "System.Collections.Generic.List[string]"
  $lines.AddRange([string[]](Get-Content -LiteralPath $EnvFile))
  $found = $false
  for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match ("^\s*" + [regex]::Escape($Key) + "\s*=")) {
      $lines[$i] = "$Key=$Value"
      $found = $true
    }
  }
  if (-not $found) { $lines.Add("$Key=$Value") }
  [System.IO.File]::WriteAllLines($EnvFile, $lines)
  Restrict-Acl $EnvFile
}

function Get-DefaultFrontendOriginAliases([string]$Origin) {
  $aliases = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5175,http://127.0.0.1:5175"
  if ($Origin -match ":5175$") {
    $aliases += "," + ($Origin -replace ":\d+$", ":5173")
  } elseif ($Origin -match ":5173$") {
    $aliases += "," + ($Origin -replace ":\d+$", ":5175")
  }
  return $aliases
}

# ---------- 预检 ----------
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  Die "未找到 docker 命令：请先安装 Docker Desktop 并确认其正在运行。"
}
& docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Die "Docker 守护进程不可用：请启动 Docker Desktop（Settings > General > Start when you log in 可开机自启）。"
}
$composeOut = (& docker compose version) -join " "
if (-not ($composeOut -match "v?(\d+)\.(\d+)\.(\d+)")) {
  Die "无法解析 docker compose 版本输出：$composeOut（需要 Docker Compose v2）。"
}
$composeVersion = [version]("$($Matches[1]).$($Matches[2]).$($Matches[3])")
if ($composeVersion -lt [version]"2.24.4") {
  Die "Docker Compose v2.24.4+ 必需（compose 覆盖文件使用 !override 语法），当前：$composeOut。请升级 Docker Desktop。"
}
if (-not (Get-Command curl.exe -ErrorAction SilentlyContinue)) {
  Die "未找到 curl.exe（Windows 10+ 系统自带）：健康检查依赖它。"
}
if (-not (Test-Path -LiteralPath $ComposeWrapper)) {
  Die "缺少 Compose 包装器：$ComposeWrapper"
}

# ---------- PUBLIC_ORIGIN 清洗（对齐 r13 修复：剥纯空白前缀/CR/尾斜杠） ----------
$origin = ""
if ($PublicOrigin) { $origin = ([string]$PublicOrigin).Trim() }
while ($origin.EndsWith("/")) {
  $origin = $origin.Substring(0, $origin.Length - 1)
}
if ($origin -and ($origin -notmatch "^(https?://[^/\s]+)$")) {
  Die "PUBLIC_ORIGIN 必须是 http://SERVER_IP:5175 形式的源（不含路径）。"
}

# ---------- 防火墙（正式部署建议管理员运行） ----------
if (-not $SkipFirewall) {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
  $principal = New-Object Security.Principal.WindowsPrincipal($identity)
  $isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if ($isAdmin) {
    foreach ($pair in @(@("LinkrAFT 主平台 $PublicPort", $PublicPort), @("LinkrAFT 审核员门户 $AnnotatorPort", $AnnotatorPort))) {
      $existing = Get-NetFirewallRule -DisplayName $pair[0] -ErrorAction SilentlyContinue
      if (-not $existing) {
        New-NetFirewallRule -DisplayName $pair[0] -Direction Inbound -Action Allow `
          -Protocol TCP -LocalPort $pair[1] -Profile Any | Out-Null
        Write-Info "防火墙已放行 TCP $($pair[1])（$($pair[0])）。"
      }
    }
  } else {
    Write-Info "当前非管理员会话：跳过防火墙配置。放行命令（管理员 PowerShell 执行）："
    Write-Info "  New-NetFirewallRule -DisplayName 'LinkrAFT 主平台' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $PublicPort"
    Write-Info "  New-NetFirewallRule -DisplayName 'LinkrAFT 审核员门户' -Direction Inbound -Action Allow -Protocol TCP -LocalPort $AnnotatorPort"
  }
}

# ---------- .env ----------
if (-not (Test-Path -LiteralPath $EnvFile)) {
  Write-Info "生成 .env（新部署秘钥）。"
  $frontendOrigin = if ($origin) { $origin } else { "http://localhost:$PublicPort" }
  $frontendAliases = $PublicOriginAliases
  if (-not $frontendAliases) { $frontendAliases = Get-DefaultFrontendOriginAliases $origin }
  $frontendBind = "127.0.0.1"
  if ($FrontendBindAddress) { $frontendBind = $FrontendBindAddress }
  $annotatorBind = "0.0.0.0"
  if ($AnnotatorBindAddress) { $annotatorBind = $AnnotatorBindAddress }

  $postgresPassword = Get-RandomHex 32
  $minioPassword = Get-RandomHex 32
  $secretKey = Get-RandomHex 32
  $tensorboardSecret = Get-RandomHex 32
  $inferenceSecret = Get-RandomHex 32
  $adminPassword = $AdminInitialPassword
  if (-not $adminPassword) { $adminPassword = Get-RandomHex 12 }
  $annotatorServiceSecret = Get-RandomHex 32

  $lines = [string[]]@(
    "# Generated for this deployment. Keep this file and secrets/ outside version control.",
    "POSTGRES_DB=ml_platform",
    "POSTGRES_USER=ml_platform",
    "POSTGRES_PASSWORD=$postgresPassword",
    "DATABASE_URL=postgresql+psycopg://ml_platform:$postgresPassword@postgres:5432/ml_platform",
    "",
    "SECRET_KEY=$secretKey",
    "ML_PLATFORM_ADMIN_INITIAL_PASSWORD=$adminPassword",
    "ANNOTATOR_SERVICE_SECRET=$annotatorServiceSecret",
    "CELERY_BROKER_URL=redis://redis:6379/0",
    "CELERY_RESULT_BACKEND=redis://redis:6379/1",
    "REDIS_EVENTS_URL=redis://redis:6379/2",
    "",
    "MINIO_ROOT_USER=mlplatform",
    "MINIO_ROOT_PASSWORD=$minioPassword",
    "MINIO_ACCESS_KEY=mlplatform",
    "MINIO_SECRET_KEY=$minioPassword",
    "MINIO_ENDPOINT=minio:9000",
    "MINIO_BUCKET=ml-platform",
    "MINIO_SECURE=false",
    "MLFLOW_S3_ENDPOINT_URL=http://minio:9000",
    "MLFLOW_TRACKING_URI=http://mlflow:5000",
    "MLFLOW_BACKEND_STORE_URI=postgresql+psycopg://ml_platform:$postgresPassword@postgres:5432/mlflow",
    "MLFLOW_ARTIFACT_ROOT=s3://ml-platform/mlflow",
    "",
    "TENSORBOARD_GATEWAY_URL=http://tensorboard-gateway:6006",
    "TENSORBOARD_SESSION_SECRET=$tensorboardSecret",
    "TENSORBOARD_SESSION_TTL_SECONDS=300",
    "TENSORBOARD_IDLE_TIMEOUT_SECONDS=600",
    "INFERENCE_RUNTIME_URL=http://inference-runtime:7000",
    "INFERENCE_INTERNAL_SECRET=$inferenceSecret",
    "NOTIFICATION_CRYPTO_SECRET_FILE=./secrets/notification_master_key",
    "",
    "NGINX_BIND_ADDRESS=0.0.0.0",
    "NGINX_PORT=$PublicPort",
    "BACKEND_BIND_ADDRESS=127.0.0.1",
    "BACKEND_PORT=8000",
    "FRONTEND_BIND_ADDRESS=$frontendBind",
    "FRONTEND_PORT=5173",
    "ANNOTATOR_BIND_ADDRESS=$annotatorBind",
    "ANNOTATOR_PORT=$AnnotatorPort",
    "ANNOTATOR_COOKIE_SECURE=false",
    "MINIO_BIND_ADDRESS=127.0.0.1",
    "MINIO_API_PORT=9000",
    "MINIO_CONSOLE_PORT=9001",
    "FRONTEND_ORIGIN=$frontendOrigin",
    "FRONTEND_ORIGIN_ALIASES=$frontendAliases"
  )
  [System.IO.File]::WriteAllLines($EnvFile, $lines)
  Restrict-Acl $EnvFile
  Write-Info "初始 admin 口令已写入 .env（仅全新数据库首启生效；统一口令请用 -AdminInitialPassword 安装）。"
} else {
  Write-Info "检测到既有 .env：保留其秘钥与服务配置。"
}

# ---------- 升级补键（与 install-ubuntu.sh L162-206 对齐） ----------
if (-not (Test-EnvKey "ML_PLATFORM_ADMIN_INITIAL_PASSWORD")) {
  $admin = $AdminInitialPassword
  if (-not $admin) { $admin = Get-RandomHex 12 }
  Set-EnvValue "ML_PLATFORM_ADMIN_INITIAL_PASSWORD" $admin
} elseif ($AdminInitialPassword) {
  Set-EnvValue "ML_PLATFORM_ADMIN_INITIAL_PASSWORD" $AdminInitialPassword
}
if (-not (Test-EnvKey "ANNOTATOR_SERVICE_SECRET")) {
  Set-EnvValue "ANNOTATOR_SERVICE_SECRET" (Get-RandomHex 32)
}

if ($origin) {
  Set-EnvValue "FRONTEND_ORIGIN" $origin
} elseif (-not (Test-EnvKey "FRONTEND_ORIGIN")) {
  Set-EnvValue "FRONTEND_ORIGIN" "http://localhost:$PublicPort"
}
$aliasParam = $PublicOriginAliases
if ($aliasParam) {
  Set-EnvValue "FRONTEND_ORIGIN_ALIASES" $aliasParam
} else {
  $existingAliases = Get-EnvValue "FRONTEND_ORIGIN_ALIASES"
  if ($origin -and (-not $existingAliases)) {
    Set-EnvValue "FRONTEND_ORIGIN_ALIASES" (Get-DefaultFrontendOriginAliases $origin)
  } elseif (-not (Test-EnvKey "FRONTEND_ORIGIN_ALIASES")) {
    Set-EnvValue "FRONTEND_ORIGIN_ALIASES" (Get-DefaultFrontendOriginAliases $origin)
  }
}
if ($FrontendBindAddress) {
  Set-EnvValue "FRONTEND_BIND_ADDRESS" $FrontendBindAddress
} elseif (-not (Test-EnvKey "FRONTEND_BIND_ADDRESS")) {
  Set-EnvValue "FRONTEND_BIND_ADDRESS" "127.0.0.1"
}
if ($AnnotatorBindAddress) {
  Set-EnvValue "ANNOTATOR_BIND_ADDRESS" $AnnotatorBindAddress
} elseif (-not (Test-EnvKey "ANNOTATOR_BIND_ADDRESS")) {
  Set-EnvValue "ANNOTATOR_BIND_ADDRESS" "0.0.0.0"
}
if ($AnnotatorCookieSecure) {
  Set-EnvValue "ANNOTATOR_COOKIE_SECURE" $AnnotatorCookieSecure
} elseif (-not (Test-EnvKey "ANNOTATOR_COOKIE_SECURE")) {
  Set-EnvValue "ANNOTATOR_COOKIE_SECURE" "false"
}
Set-EnvValue "NGINX_PORT" $PublicPort
Set-EnvValue "NGINX_BIND_ADDRESS" "0.0.0.0"
Set-EnvValue "ANNOTATOR_PORT" $AnnotatorPort
Write-Info "后端 CORS frontend origin：$(Get-EnvValue 'FRONTEND_ORIGIN')"

# ---------- secrets/notification_master_key（对应 prepare-production-secrets.sh） ----------
$secretRelative = Get-EnvValue "NOTIFICATION_CRYPTO_SECRET_FILE"
if (-not $secretRelative) {
  $secretRelative = "./secrets/notification_master_key"
  Set-EnvValue "NOTIFICATION_CRYPTO_SECRET_FILE" $secretRelative
}
$secretPath = $secretRelative
if (-not [System.IO.Path]::IsPathRooted($secretPath)) {
  $secretPath = Join-Path $Root ($secretRelative -replace "^\.[/\\]", "")
}
$secretDir = Split-Path -Parent $secretPath
if (-not (Test-Path -LiteralPath $secretDir)) {
  New-Item -ItemType Directory -Path $secretDir -Force | Out-Null
  Restrict-Acl $secretDir
}
if (-not (Test-Path -LiteralPath $secretPath)) {
  [System.IO.File]::WriteAllText($secretPath, (Get-RandomUrlSafeBase64))
  Restrict-Acl $secretPath
  Write-Info "已生成通知加密主密钥：$secretRelative"
}

# ---------- Compose 校验/构建/启动 ----------
Write-Info "校验 Compose 配置。"
& $ComposeWrapper config *> $null
if ($LASTEXITCODE -ne 0) { Die "Compose 配置校验失败。"; }
Write-Info "构建服务镜像（首次构建需要数分钟）。"
& $ComposeWrapper build
if ($LASTEXITCODE -ne 0) { Die "镜像构建失败。"; }
Write-Info "准备 bind-mount 存储目录（Docker Desktop 无需 chown 属主修复）。"
foreach ($dir in @("ml-platform\backend\data", "ml-platform\backend\uploads")) {
  $full = Join-Path $Root $dir
  if (-not (Test-Path -LiteralPath $full)) { New-Item -ItemType Directory -Path $full -Force | Out-Null }
}
Write-Info "启动服务。"
& $ComposeWrapper up -d --remove-orphans
if ($LASTEXITCODE -ne 0) { Die "服务启动失败。"; }

# ---------- 健康等待（120 × 3s，对齐 Ubuntu 版） ----------
Write-Info "等待公共健康端点（端口 $PublicPort）。"
for ($i = 1; $i -le 120; $i++) {
  & curl.exe --fail --silent --output NUL "http://127.0.0.1:$PublicPort/health"
  $healthOk = ($LASTEXITCODE -eq 0)
  & curl.exe --fail --silent --output NUL "http://127.0.0.1:$PublicPort/api/health"
  $apiOk = ($LASTEXITCODE -eq 0)
  if ($healthOk -and $apiOk) {
    Write-Info "安装完成。浏览器打开 http://<本机IP>:$PublicPort/"
    exit 0
  }
  Start-Sleep -Seconds 3
}

& $ComposeWrapper ps
& $ComposeWrapper logs --tail=100
Die "服务在六分钟内未达到健康状态。"
