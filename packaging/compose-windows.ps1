#requires -Version 5.1
# 与 packaging/compose-ubuntu.sh 同构：始终叠加 legacy-cpu 覆盖文件。
# 用法示例：pwsh -File packaging\compose-windows.ps1 ps
$Root = Split-Path -Parent $PSScriptRoot
& docker compose -f (Join-Path $Root "docker-compose.yml") -f (Join-Path $PSScriptRoot "docker-compose.legacy-cpu.yml") @args
exit $LASTEXITCODE
