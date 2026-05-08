Write-Host "Checking Flow Kit endpoints..."

$backendHealth = "http://127.0.0.1:8100/health"
$operatorPack = "http://127.0.0.1:8100/api/operator/content-pack"
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

$backendResult = $false
$dashboardResult = $false
$sidePanelApiStatus = $false
$extensionState = "OFF"
$productsCount = 0
$enginesCount = 0
$silosCount = 0

try {
    $healthResponse = Invoke-WebRequest -Uri $backendHealth -Method Get -TimeoutSec 5 -ErrorAction Stop
    if ($healthResponse.StatusCode -eq 200) {
        $backendResult = $true
        $healthJson = $healthResponse.Content | ConvertFrom-Json
        $extensionStateValue = if ($null -ne $healthJson.extension_state -and "$($healthJson.extension_state)".Trim() -ne "") {
            $healthJson.extension_state
        } else {
            "off"
        }
        $extensionState = $extensionStateValue.ToString().ToUpper()
        Write-Host "BACKEND_HEALTH: PASS" -ForegroundColor Green
    } else {
        Write-Host "BACKEND_HEALTH: FAIL (Status: $($healthResponse.StatusCode))" -ForegroundColor Red
    }
} catch {
    Write-Host "BACKEND_HEALTH: FAIL (Error: $($_.Exception.Message))" -ForegroundColor Red
}

try {
    $packResponse = Invoke-WebRequest -Uri $operatorPack -Method Get -TimeoutSec 10 -ErrorAction Stop
    $packJson = $packResponse.Content | ConvertFrom-Json
    $productsCount = @($packJson.products).Count
    $enginesCount = @($packJson.engines).Count
    $silosCount = @($packJson.silos).Count
    $sidePanelApiStatus = (
        $packResponse.StatusCode -eq 200 -and
        $packJson.available -eq $true -and
        $productsCount -gt 0 -and
        $enginesCount -gt 0 -and
        $silosCount -gt 0
    )
    if ($sidePanelApiStatus) {
        Write-Host "SIDE_PANEL_API_STATUS: PASS" -ForegroundColor Green
    } else {
        Write-Host "SIDE_PANEL_API_STATUS: FAIL" -ForegroundColor Red
    }
} catch {
    Write-Host "SIDE_PANEL_API_STATUS: FAIL (Error: $($_.Exception.Message))" -ForegroundColor Red
}

$dashboardResult = Check-Endpoint -url $dashboardOperator -name "DASHBOARD_OPERATOR_5173"

Write-Host "EXTENSION_STATE: $extensionState" -ForegroundColor $(if ($extensionState -eq "IDLE") { "Green" } else { "Yellow" })
Write-Host "PRODUCTS_COUNT: $productsCount"
Write-Host "ENGINES_COUNT: $enginesCount"
Write-Host "SILOS_COUNT: $silosCount"

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

if ($backendResult -and $sidePanelApiStatus -and $dashboardResult -and $extensionState -eq "IDLE") {
    exit 0
} else {
    exit 1
}
