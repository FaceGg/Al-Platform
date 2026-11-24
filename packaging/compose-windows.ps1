#requires -Version 5.1
# 与 packaging/compose-ubuntu.sh 同构，并追加 Windows 专用覆盖（构建网络
# 回落默认桥接——legacy-cpu 硬编码的 network: host 在 Docker Desktop 有兼容
# 风险）。用法示例：pwsh -File packaging\compose-windows.ps1 ps
$Root = Split-Path -Parent $PSScriptRoot
& docker compose `
  -f (Join-Path $Root "docker-compose.yml") `
  -f (Join-Path $PSScriptRoot "docker-compose.legacy-cpu.yml") `
  -f (Join-Path $PSScriptRoot "docker-compose.windows.yml") `
  @args
exit $LASTEXITCODE
