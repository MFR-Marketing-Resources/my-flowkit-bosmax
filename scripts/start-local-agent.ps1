param(
    [switch]$ForceRestart,
    [switch]$Watchdog,
    [int]$IntervalSeconds = 5,
    [int]$FailThreshold = 2,
    [int]$MaxBackoffSeconds = 60
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\local-agent-common.ps1"

Set-Location $script:RepoRoot
Ensure-LocalAgentDirectories

$script:DashboardBundle = Join-Path $script:RepoRoot 'dashboard\dist\index.html'

function Test-DashboardBundle {
    return (Test-Path $script:DashboardBundle)
}

function Resolve-AgentPython {
    $venvPython = Join-Path $script:RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        return $venvPython
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }
    return $null
}

# Single source of truth for "make the backend running and healthy, once".
# Returns a hashtable: @{ ok = <bool>; reason = <string>; pid = <int?> }.
# Never throws for expected failure modes (build missing / port conflict /
# python missing / did-not-become-healthy) so the supervisor can react.
function Start-BackendOnce {
    param([switch]$Force)

    if (-not (Test-DashboardBundle)) {
        return @{ ok = $false; reason = 'BUILD_REQUIRED' }
    }

    if ((-not $Force) -and (Test-UrlHealthy -Url $script:HealthUrl -TimeoutSec 3)) {
        return @{ ok = $true; reason = 'ALREADY_HEALTHY' }
    }

    # Guardrail: never kill or race an unknown process that holds the port.
    $unknownOwner = Get-PortUnknownOwner -Port $script:BackendPort
    if ($unknownOwner) {
        return @{ ok = $false; reason = "PORT_CONFLICT ($unknownOwner)" }
    }

    $stopped = Stop-BosmaxBackendProcess
    if ($stopped) {
        Start-Sleep -Seconds 2
    }

    $pythonExe = Resolve-AgentPython
    if (-not $pythonExe) {
        return @{ ok = $false; reason = 'PYTHON_MISSING' }
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
        return @{ ok = $false; reason = 'UNHEALTHY_AFTER_START' }
    }

    return @{ ok = $true; reason = 'STARTED'; pid = $proc.Id }
}

# Durable supervisor: keep the backend healthy across mid-session death/kills.
# Blocks (this is the process the Startup shortcut / scheduled task runs at
# logon). Single-owner via watchdog.lock; bounded exponential backoff; refuses
# to fight an unknown process on the port; clear structured logging.
function Invoke-Watchdog {
    $owner = Get-WatchdogLockOwner
    if ($owner -gt 0) {
        Write-Host "LOCAL_AGENT_WATCHDOG: ALREADY_RUNNING (pid=$owner)" -ForegroundColor Yellow
        return
    }

    Set-WatchdogLock
    Write-WatchdogLog -EventName 'WATCHDOG_START' -Detail "pid=$PID repo=$($script:RepoRoot) interval=${IntervalSeconds}s threshold=$FailThreshold maxBackoff=${MaxBackoffSeconds}s"

    $consecutiveFail = 0
    $backoff = $IntervalSeconds

    try {
        $initial = Start-BackendOnce -Force:$ForceRestart
        if ($initial.ok) {
            Write-WatchdogLog -EventName 'AGENT_HEALTHY' -Detail $initial.reason
        } else {
            Write-WatchdogLog -EventName 'AGENT_START_FAILED' -Detail $initial.reason
        }

        while ($true) {
            Set-WatchdogLock

            if (Test-UrlHealthy -Url $script:HealthUrl -TimeoutSec 3) {
                if ($consecutiveFail -gt 0) {
                    Write-WatchdogLog -EventName 'HEALTH_RECOVERED' -Detail "after $consecutiveFail consecutive failure(s)"
                }
                $consecutiveFail = 0
                $backoff = $IntervalSeconds
                Start-Sleep -Seconds $IntervalSeconds
                continue
            }

            $consecutiveFail++
            Write-WatchdogLog -EventName 'HEALTH_FAIL' -Detail "count=$consecutiveFail/$FailThreshold"
            if ($consecutiveFail -lt $FailThreshold) {
                Start-Sleep -Seconds $IntervalSeconds
                continue
            }

            $unknownOwner = Get-PortUnknownOwner -Port $script:BackendPort
            if ($unknownOwner) {
                Write-WatchdogLog -EventName 'PORT_CONFLICT' -Detail "port $($script:BackendPort) held by non-agent process ($unknownOwner); NOT killing; backoff=${backoff}s"
                Start-Sleep -Seconds $backoff
                $backoff = [Math]::Min($backoff * 2, $MaxBackoffSeconds)
                continue
            }

            Write-WatchdogLog -EventName 'RESTART_ATTEMPT' -Detail "consecutiveFail=$consecutiveFail backoff=${backoff}s"
            $result = Start-BackendOnce -Force
            if ($result.ok) {
                $restartedPid = if ($result.ContainsKey('pid')) { $result.pid } else { '(unknown)' }
                Write-WatchdogLog -EventName 'RESTART_SUCCESS' -Detail "pid=$restartedPid"
                $consecutiveFail = 0
                $backoff = $IntervalSeconds
                Start-Sleep -Seconds $IntervalSeconds
            } else {
                Write-WatchdogLog -EventName 'RESTART_FAILURE' -Detail "reason=$($result.reason) backoff=${backoff}s"
                Start-Sleep -Seconds $backoff
                $backoff = [Math]::Min($backoff * 2, $MaxBackoffSeconds)
            }
        }
    } finally {
        Write-WatchdogLog -EventName 'WATCHDOG_STOP' -Detail "pid=$PID"
        Clear-WatchdogLock
    }
}

# ---- dispatch -----------------------------------------------------------

if ($Watchdog) {
    Invoke-Watchdog
    exit 0
}

# One-shot mode (unchanged contract: same messages and exit codes as before).
if (-not (Test-DashboardBundle)) {
    Write-Host "LOCAL_AGENT_START: FAIL" -ForegroundColor Red
    Write-Host "Reason: Production dashboard bundle missing at $script:DashboardBundle"
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

$startResult = Start-BackendOnce -Force:$ForceRestart

if (-not $startResult.ok) {
    Write-Host "LOCAL_AGENT_START: FAIL" -ForegroundColor Red
    if ($startResult.reason -eq 'BUILD_REQUIRED') {
        Write-Host "Reason: Production dashboard bundle missing at $script:DashboardBundle"
        Write-Host "Repair: .\scripts\install-local-agent.ps1"
    } elseif ($startResult.reason -eq 'PYTHON_MISSING') {
        Write-Host "Reason: Python runtime not found. Run .\scripts\install-local-agent.ps1"
    } else {
        Write-Host "Reason: Backend did not become healthy ($($startResult.reason))."
        Write-Host "Stdout: $script:LocalAgentStdout"
        Write-Host "Stderr: $script:LocalAgentStderr"
    }
    exit 1
}

Write-Host "LOCAL_AGENT_START: PASS" -ForegroundColor Green
if ($startResult.ContainsKey('pid')) {
    Write-Host "PID: $($startResult.pid)"
}
Write-Host "Health URL: $script:HealthUrl"
Write-Host "Dashboard URL: $script:DashboardUrl"
exit 0
