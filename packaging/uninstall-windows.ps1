#requires -Version 5.1
# 停止并移除容器；保留数据卷、.env 与 secrets/（与 uninstall-ubuntu.sh 同口径）。
$wrapper = Join-Path $PSScriptRoot "compose-windows.ps1"
& $wrapper down --remove-orphans
Write-Host "已停止并移除容器（数据卷、.env 与 secrets/ 均保留）。"
Write-Host "如需彻底清除数据卷（不可恢复）：pwsh -File '$wrapper' down -v"
exit $LASTEXITCODE
