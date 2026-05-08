$repoRoot = Split-Path $PSScriptRoot -Parent
cd "$repoRoot\dashboard"

$port = 5173
$busy = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }

if ($busy) {
    $proc = Get-Process -Id $busy[0].OwningProcess -ErrorAction SilentlyContinue
    Write-Host "PORT_5173_BUSY: FAIL" -ForegroundColor Red
    Write-Host "PID: $($busy[0].OwningProcess)"
    Write-Host "ProcessName: $($proc.Name)"
    Write-Host "CommandLine: $((Get-CimInstance Win32_Process -Filter "ProcessId=$($busy[0].OwningProcess)").CommandLine)"
    exit 1
}

Write-Host "Starting dashboard on port $port with --strictPort..."
npm run dev -- --host 127.0.0.1 --port $port --strictPort

Write-Host "Dashboard target: http://127.0.0.1:5173/operator"
