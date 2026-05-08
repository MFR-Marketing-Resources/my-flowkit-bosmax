Write-Host "Resetting Flow Kit Dev Environment..." -ForegroundColor Cyan

$scriptDir = $PSScriptRoot

# 1. Killing stale ports (8100, 8101, 5173, 5174, 5175)...
& "$scriptDir\start-dev.ps1" -KillStale

$maxAttempts = 12
$delaySeconds = 3

for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    Write-Host "Readiness probe $attempt/$maxAttempts..." -ForegroundColor Cyan
    & "$scriptDir\check-dev.ps1"
    if ($LASTEXITCODE -eq 0) {
        exit 0
    }

    if ($attempt -lt $maxAttempts) {
        Start-Sleep -Seconds $delaySeconds
    }
}

Write-Host "RESET_DEV_RESULT: FAIL" -ForegroundColor Red
exit 1
