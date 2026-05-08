Write-Host "Checking Flow Kit endpoints..."

$backendHealth = "http://127.0.0.1:8100/health"
$dashboardOperator = "http://127.0.0.1:5173/operator"

function Check-Endpoint {
    param($url, $name)
    try {
        $response = Invoke-WebRequest -Uri $url -Method Get -TimeoutSec 5 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Host "${name}: PASS" -ForegroundColor Green
            return $true
        } else {
            Write-Host "${name}: FAIL (Status: $($response.StatusCode))" -ForegroundColor Red
            return $false
        }
    } catch {
        return $false
    }
}

$backendResult = Check-Endpoint -url $backendHealth -name "BACKEND_HEALTH"
$dashboardResult = Check-Endpoint -url $dashboardOperator -name "DASHBOARD_OPERATOR_5173"

if (!$backendResult) {
    Write-Host "BACKEND_HEALTH: FAIL" -ForegroundColor Red
}

if (!$dashboardResult) {
    Write-Host "DASHBOARD_OPERATOR_5173: FAIL" -ForegroundColor Red
}

# Wrong port detection
$wrong5174 = Get-NetTCPConnection -LocalPort 5174 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
$wrong5175 = Get-NetTCPConnection -LocalPort 5175 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }

$c5174 = if ($wrong5174) { "Yellow" } else { "Gray" }
$s5174 = if ($wrong5174) { "YES" } else { "NO" }
$c5175 = if ($wrong5175) { "Yellow" } else { "Gray" }
$s5175 = if ($wrong5175) { "YES" } else { "NO" }

Write-Host "WRONG_PORT_5174_ACTIVE: $s5174" -ForegroundColor $c5174
Write-Host "WRONG_PORT_5175_ACTIVE: $s5175" -ForegroundColor $c5175

if (!$dashboardResult -and ($wrong5174 -or $wrong5175)) {
    Write-Host "FAIL: Dashboard is running on wrong port. Restart with strictPort." -ForegroundColor Red
}

if ($backendResult -and $dashboardResult) {
    exit 0
} else {
    exit 1
}
