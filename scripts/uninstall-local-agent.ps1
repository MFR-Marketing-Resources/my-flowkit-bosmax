Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

param(
    [switch]$DeleteData
)

. "$PSScriptRoot\local-agent-common.ps1"

Set-Location $script:RepoRoot

$task = Get-TaskState
if ($task) {
    Unregister-ScheduledTask -TaskName $script:LocalAgentTaskName -Confirm:$false | Out-Null
    Write-Host "TASK_REMOVED: YES" -ForegroundColor Green
} else {
    Write-Host "TASK_REMOVED: NO_TASK" -ForegroundColor Yellow
}

if (Test-Path $script:StartupShortcutPath) {
    Remove-Item -LiteralPath $script:StartupShortcutPath -Force
    Write-Host "STARTUP_SHORTCUT_REMOVED: YES" -ForegroundColor Green
} else {
    Write-Host "STARTUP_SHORTCUT_REMOVED: NO_SHORTCUT" -ForegroundColor Yellow
}

$stopped = Stop-BosmaxBackendProcess
Write-Host "BACKEND_STOPPED: $(if ($stopped) { 'YES' } else { 'NO' })"

if ($DeleteData) {
    if (Test-Path $script:LocalAgentStateDir) {
        Remove-Item -LiteralPath $script:LocalAgentStateDir -Recurse -Force
    }
    Write-Host "LOCAL_AGENT_STATE_REMOVED: YES"
} else {
    Write-Host "LOCAL_AGENT_STATE_REMOVED: NO"
}

Write-Host "UNINSTALL_LOCAL_AGENT: PASS" -ForegroundColor Green
