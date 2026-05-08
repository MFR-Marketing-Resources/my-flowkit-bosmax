Write-Host "Resetting Flow Kit Dev Environment..." -ForegroundColor Cyan

$scriptDir = $PSScriptRoot

# 1. Kill stale ports
& "$scriptDir\start-dev.ps1" -KillStale

# 2. Wait 2 seconds
Write-Host "Waiting 2 seconds..."
Start-Sleep -Seconds 2

# 3. Start dev environment (already done by start-dev.ps1 -KillStale if we modified it to continue, 
# but start-dev.ps1 normally exits after Start-Process. Let's make sure it's clear.)
# Actually, start-dev.ps1 with -KillStale will kill then start.

# 4. Wait 10 seconds for startup
Write-Host "Waiting 10 seconds for startup..."
Start-Sleep -Seconds 10

# 5. Run health check
& "$scriptDir\check-dev.ps1"
