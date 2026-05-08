param(
    [switch]$ForceRestart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\local-agent-common.ps1"

Set-Location $script:RepoRoot
Ensure-LocalAgentDirectories

$dashboardBundle = Join-Path $script:RepoRoot 'dashboard\dist\index.html'
if (-not (Test-Path $dashboardBundle)) {
    Write-Host "LOCAL_AGENT_START: FAIL" -ForegroundColor Red
    Write-Host "Reason: Production dashboard bundle missing at $dashboardBundle"
    Write-Host "Repair: .\scripts\install-local-agent.ps1"
    exit 1
}

if ((-not $ForceRestart) -and (Test-UrlHealthy -Url $script:HealthUrl -TimeoutSec 3)) {
    Write-Host "LOCAL_AGENT_START: PASS" -ForegroundColor Green
    Write-Host "Backend already healthy."
    Write-Host "Health URL: $script:HealthUrl"
    Write-Host "Dashboard URL: $script:DashboardUrl"
    exit 0
}

$stopped = Stop-BosmaxBackendProcess
if ($stopped) {
    Start-Sleep -Seconds 2
}

$pythonExe = Join-Path $script:RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $pythonExe)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        Write-Host "LOCAL_AGENT_START: FAIL" -ForegroundColor Red
        Write-Host "Reason: Python runtime not found. Run .\scripts\install-local-agent.ps1"
        exit 1
    }
    $pythonExe = $pythonCommand.Source
}

$proc = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList @('-m', 'agent.main') `
    -WorkingDirectory $script:RepoRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $script:LocalAgentStdout `
    -RedirectStandardError $script:LocalAgentStderr `
    -PassThru

Write-LocalAgentPid -ProcessId $proc.Id

if (-not (Wait-UrlHealthy -Url $script:HealthUrl -Attempts 40 -DelaySeconds 2)) {
    try {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    } catch {}
    Clear-LocalAgentPid
    Write-Host "LOCAL_AGENT_START: FAIL" -ForegroundColor Red
    Write-Host "Reason: Backend did not become healthy."
    Write-Host "Stdout: $script:LocalAgentStdout"
    Write-Host "Stderr: $script:LocalAgentStderr"
    exit 1
}

Write-Host "LOCAL_AGENT_START: PASS" -ForegroundColor Green
Write-Host "PID: $($proc.Id)"
Write-Host "Health URL: $script:HealthUrl"
Write-Host "Dashboard URL: $script:DashboardUrl"
