[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [string]$RuntimeDir = $env:ML_PLATFORM_RUNTIME_DIR
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ProjectRoot = (Resolve-Path (Join-Path $Root "..")).Path
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
if (-not $RuntimeDir) { $RuntimeDir = Join-Path $ProjectRoot "temp_test\runtime" }
$RuntimeDir = [System.IO.Path]::GetFullPath($RuntimeDir)

function Get-MajorVersion([string]$Command, [string[]]$Arguments) {
    $output = & $Command @Arguments 2>&1
    if ($LASTEXITCODE -ne 0 -or $output -notmatch '(\d+)\.') {
        throw "Unable to determine version for $Command."
    }
    return [int]$Matches[1]
}

function Assert-PortFree([int]$Port) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($listener) { throw "Port $Port is already in use. Stop the existing process or choose another port." }
}

foreach ($command in @("python", "node", "npm")) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Required command '$command' was not found in PATH."
    }
}
if ((Get-MajorVersion "python" @("--version")) -lt 3) { throw "Python 3.10 or newer is required." }
$pythonVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pythonVersion -lt [version]"3.10") { throw "Python 3.10 or newer is required; found $pythonVersion." }
if ((Get-MajorVersion "node" @("--version")) -lt 18) { throw "Node.js 18 or newer is required." }
if (-not (Test-Path (Join-Path $BackendDir "requirements.txt"))) { throw "Backend requirements.txt is missing." }
if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) { throw "Frontend dependencies are missing. Run 'npm ci' in frontend." }

Assert-PortFree $BackendPort
Assert-PortFree $FrontendPort
New-Item -ItemType Directory -Force $RuntimeDir | Out-Null
$probe = Join-Path $RuntimeDir ".write-test"
Set-Content -LiteralPath $probe -Value "ok"
Remove-Item -LiteralPath $probe

$backend = Start-Process -FilePath (Get-Command python).Source `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
    -WorkingDirectory $BackendDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $RuntimeDir "backend.log") `
    -RedirectStandardError (Join-Path $RuntimeDir "backend.err.log")
Set-Content -LiteralPath (Join-Path $RuntimeDir "backend.pid") -Value $backend.Id

$frontend = Start-Process -FilePath (Get-Command npm.cmd).Source `
    -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort") `
    -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $RuntimeDir "frontend.log") `
    -RedirectStandardError (Join-Path $RuntimeDir "frontend.err.log")
Set-Content -LiteralPath (Join-Path $RuntimeDir "frontend.pid") -Value $frontend.Id

try {
    & (Join-Path $PSScriptRoot "health-check.ps1") -BackendPort $BackendPort -FrontendPort $FrontendPort -Attempts 30
} catch {
    & (Join-Path $PSScriptRoot "stop.ps1") -RuntimeDir $RuntimeDir
    throw
}

Write-Host "Backend:  http://127.0.0.1:$BackendPort"
Write-Host "Frontend: http://127.0.0.1:$FrontendPort"
Write-Host "Runtime:  $RuntimeDir"
