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
        Write-Host "${name}: FAIL (Error: $($_.Exception.Message))" -ForegroundColor Red
        return $false
    }
}

$backendResult = Check-Endpoint -url $backendHealth -name "BACKEND_HEALTH"
$dashboardResult = Check-Endpoint -url $dashboardOperator -name "DASHBOARD_OPERATOR"

if ($backendResult -and $dashboardResult) {
    exit 0
} else {
    exit 1
}
