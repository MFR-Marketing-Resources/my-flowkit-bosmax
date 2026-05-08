Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\local-agent-common.ps1"

Set-Location $script:RepoRoot

$task = Get-TaskState
$taskInstalled = if ($task) { 'YES' } else { 'NO' }
$startupShortcutInstalled = if (Test-Path $script:StartupShortcutPath) { 'YES' } else { 'NO' }

$backendHealth = 'FAIL'
$dashboardServingMode = 'UNKNOWN'
$dashboardStatus = 'FAIL'
$extensionRuntimeHealth = 'UNKNOWN'
$extensionState = 'UNKNOWN'
$registrationOperatorId = ''
$registrationDeviceId = ''
$registrationApprovalStatus = ''
$registrationLicenseStatus = ''

try {
    $health = Invoke-JsonRequest -Url $script:HealthUrl -TimeoutSec 5
    $backendHealth = if ($health.StatusCode -eq 200) { 'PASS' } else { 'FAIL' }
    $extensionRuntimeHealth = if ($health.Json.extension_connected) { 'PASS' } else { 'FAIL' }
    $extensionState = [string]$health.Json.extension_state
    $dashboardServingMode = [string]$health.Json.dashboard_serving_mode
} catch {
    $backendHealth = 'FAIL'
}

try {
    $status = Invoke-JsonRequest -Url $script:LocalAgentStatusUrl -TimeoutSec 5
    $registration = $status.Json.registration
    $registrationOperatorId = [string]$registration.operator_id
    $registrationDeviceId = [string]$registration.device_id
    $registrationApprovalStatus = [string]$registration.approval_status
    $registrationLicenseStatus = [string]$registration.license_status
    if ([string]::IsNullOrWhiteSpace($dashboardServingMode)) {
        $dashboardServingMode = [string]$status.Json.dashboard_serving_mode
    }
} catch {}

try {
    $dashboardResponse = Invoke-WebRequest -Uri $script:DashboardUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($dashboardResponse.StatusCode -eq 200) {
        $dashboardStatus = 'PASS'
    }
} catch {
    $dashboardStatus = 'FAIL'
}

$port8100 = Get-PortOwner -Port $script:BackendPort
$port8101 = Get-PortOwner -Port $script:WsPort

Write-Host "TASK_INSTALLED: $taskInstalled" -ForegroundColor $(if ($taskInstalled -eq 'YES') { 'Green' } else { 'Yellow' })
Write-Host "STARTUP_SHORTCUT_INSTALLED: $startupShortcutInstalled" -ForegroundColor $(if ($startupShortcutInstalled -eq 'YES') { 'Green' } else { 'Gray' })
Write-Host "BACKEND_HEALTH: $backendHealth" -ForegroundColor $(if ($backendHealth -eq 'PASS') { 'Green' } else { 'Red' })
Write-Host "EXTENSION_RUNTIME_HEALTH: $extensionRuntimeHealth" -ForegroundColor $(if ($extensionRuntimeHealth -eq 'PASS') { 'Green' } elseif ($extensionRuntimeHealth -eq 'FAIL') { 'Yellow' } else { 'Gray' })
Write-Host "EXTENSION_STATE: $extensionState"
Write-Host "DASHBOARD_SERVING_MODE: $dashboardServingMode"
Write-Host "DASHBOARD_URL: $script:DashboardUrl"
Write-Host "DASHBOARD_STATUS: $dashboardStatus" -ForegroundColor $(if ($dashboardStatus -eq 'PASS') { 'Green' } else { 'Red' })
Write-Host "PORT_8100_LISTEN: $(if ($port8100) { 'YES' } else { 'NO' })"
Write-Host "PORT_8101_LISTEN: $(if ($port8101) { 'YES' } else { 'NO' })"
Write-Host "TASK_NAME: $script:LocalAgentTaskName"
Write-Host "OPERATOR_ID: $registrationOperatorId"
Write-Host "DEVICE_ID: $registrationDeviceId"
Write-Host "APPROVAL_STATUS: $registrationApprovalStatus"
Write-Host "LICENSE_STATUS: $registrationLicenseStatus"

if (($taskInstalled -eq 'YES' -or $startupShortcutInstalled -eq 'YES') -and $backendHealth -eq 'PASS' -and $dashboardStatus -eq 'PASS') {
    exit 0
}

exit 1
