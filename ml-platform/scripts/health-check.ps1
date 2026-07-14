[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [int]$Attempts = 1
)

$ErrorActionPreference = "Stop"
for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    try {
        $backend = Invoke-RestMethod -Uri "http://127.0.0.1:$BackendPort/api/health" -TimeoutSec 3
        $frontend = Invoke-WebRequest -Uri "http://127.0.0.1:$FrontendPort/" -TimeoutSec 3 -UseBasicParsing
        if ($backend.status -in @("ok", "healthy") -and $frontend.StatusCode -eq 200) {
            Write-Host "Health check passed: backend=$($backend.status), frontend=$($frontend.StatusCode)"
            return
        }
    } catch {
        if ($attempt -eq $Attempts) { throw "Health check failed after $Attempts attempts: $($_.Exception.Message)" }
    }
    Start-Sleep -Seconds 1
}
throw "Health check failed."
