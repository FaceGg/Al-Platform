[CmdletBinding()]
param([string]$RuntimeDir = $env:ML_PLATFORM_RUNTIME_DIR)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProjectRoot = (Resolve-Path (Join-Path $Root "..")).Path
if (-not $RuntimeDir) { $RuntimeDir = Join-Path $ProjectRoot "temp_test\runtime" }
$RuntimeDir = [System.IO.Path]::GetFullPath($RuntimeDir)

function Stop-ProcessTree([int]$ProcessId) {
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) { Stop-ProcessTree ([int]$child.ProcessId) }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        try { $process.WaitForExit(5000) | Out-Null } catch { }
    }
}

foreach ($name in @("frontend", "backend")) {
    $pidFile = Join-Path $RuntimeDir "$name.pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $processId = [int](Get-Content -LiteralPath $pidFile -Raw)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($process) {
        Stop-ProcessTree $processId
        Write-Host "Stopped $name process $processId."
    }
    Remove-Item -LiteralPath $pidFile -Force
}
