$repoRoot = $PSScriptRoot
if ($repoRoot -eq "") { $repoRoot = "." }

Write-Host "Starting Flow Kit Dev Environment..."

# Start Backend in a new window
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "$repoRoot\start-backend.ps1"

# Start Dashboard in a new window
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "$repoRoot\start-dashboard.ps1"

Write-Host "Backend: http://127.0.0.1:8100/health"
Write-Host "Dashboard: http://127.0.0.1:5173/operator"
