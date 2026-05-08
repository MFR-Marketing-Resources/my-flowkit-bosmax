param(
    [switch]$KillStale
)

$repoRoot = $PSScriptRoot
if ($repoRoot -eq "") { $repoRoot = "." }

if ($KillStale) {
    Write-Host "Killing stale ports (8100, 5173, 5174, 5175)..." -ForegroundColor Yellow
    $ports = @(8100, 5173, 5174, 5175)
    foreach ($port in $ports) {
        $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
        foreach ($conn in $conns) {
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
}

# Detect busy ports
$ports = @(8100, 5173)
foreach ($port in $ports) {
    $busy = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
    if ($busy) {
        Write-Host "PORT_$port`_BUSY: FAIL" -ForegroundColor Red
        Write-Host "Run with -KillStale to force reset."
        exit 1
    }
}

Write-Host "Starting Flow Kit Dev Environment..."

# Start Backend in a new window
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "$repoRoot\start-backend.ps1"

# Start Dashboard in a new window
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy", "Bypass", "-File", "$repoRoot\start-dashboard.ps1"

Write-Host "Backend: http://127.0.0.1:8100/health"
Write-Host "Dashboard: http://127.0.0.1:5173/operator"
