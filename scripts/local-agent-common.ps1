$script:RepoRoot = Split-Path $PSScriptRoot -Parent
$script:LocalAgentTaskName = 'BOSMAX Flow Kit Local Agent'
$script:LocalAgentStateDir = Join-Path $script:RepoRoot '.local-agent'
$script:LocalAgentLogDir = Join-Path $script:LocalAgentStateDir 'logs'
$script:LocalAgentPidFile = Join-Path $script:LocalAgentStateDir 'backend.pid'
$script:LocalAgentStdout = Join-Path $script:LocalAgentLogDir 'backend.stdout.log'
$script:LocalAgentStderr = Join-Path $script:LocalAgentLogDir 'backend.stderr.log'
$script:LocalAgentWatchdogLog = Join-Path $script:LocalAgentLogDir 'watchdog.log'
$script:LocalAgentWatchdogLock = Join-Path $script:LocalAgentStateDir 'watchdog.lock'
$script:HealthUrl = 'http://127.0.0.1:8100/health'
$script:DashboardUrl = 'http://127.0.0.1:8100/operator'
$script:LocalAgentStatusUrl = 'http://127.0.0.1:8100/api/local-agent/status'
$script:BackendPort = 8100
$script:WsPort = 8101
$script:StartupShortcutPath = Join-Path ([Environment]::GetFolderPath('Startup')) 'BOSMAX Flow Kit Local Agent.lnk'

function Ensure-LocalAgentDirectories {
    New-Item -ItemType Directory -Force -Path $script:LocalAgentStateDir | Out-Null
    New-Item -ItemType Directory -Force -Path $script:LocalAgentLogDir | Out-Null
}

function Invoke-JsonRequest {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 5
    )

    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
    return @{
        StatusCode = $response.StatusCode
        Json = $response.Content | ConvertFrom-Json
    }
}

function Test-UrlHealthy {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 3
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec -ErrorAction Stop
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-UrlHealthy {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$Attempts = 45,
        [int]$DelaySeconds = 2
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        if (Test-UrlHealthy -Url $Url -TimeoutSec 3) {
            return $true
        }
        Start-Sleep -Seconds $DelaySeconds
    }
    return $false
}

function Get-ProcessCommandLine {
    param([int]$ProcessId)

    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
        return $proc.CommandLine
    } catch {
        return $null
    }
}

function Get-PortOwner {
    param([int]$Port)

    try {
        return Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
    } catch {
        return $null
    }
}

function Test-IsBosmaxAgentCommandLine {
    param([string]$CommandLine)

    if ([string]::IsNullOrWhiteSpace($CommandLine)) {
        return $false
    }

    return $CommandLine -match 'agent\.main'
}

function Get-BosmaxBackendProcess {
    $processes = @(Get-BosmaxBackendProcesses)
    if ($processes.Count -gt 0) {
        return $processes[0]
    }

    return $null
}

function Get-BosmaxBackendProcesses {
    $candidates = @()

    if (Test-Path $script:LocalAgentPidFile) {
        $pidText = (Get-Content $script:LocalAgentPidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        $pidValue = 0
        if ([int]::TryParse([string]$pidText, [ref]$pidValue) -and $pidValue -gt 0) {
            $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
            if ($process) {
                $commandLine = Get-ProcessCommandLine -ProcessId $pidValue
                if (Test-IsBosmaxAgentCommandLine -CommandLine $commandLine) {
                    $candidates += $process
                }
            }
        }
    }

    $portOwner = Get-PortOwner -Port $script:BackendPort
    if ($portOwner) {
        $commandLine = Get-ProcessCommandLine -ProcessId $portOwner.OwningProcess
        if (Test-IsBosmaxAgentCommandLine -CommandLine $commandLine) {
            $process = Get-Process -Id $portOwner.OwningProcess -ErrorAction SilentlyContinue
            if ($process) {
                $candidates += $process
            }
        }
    }

    return @(
        $candidates |
            Sort-Object -Property Id -Unique
    )
}

function Write-LocalAgentPid {
    param([int]$ProcessId)
    Ensure-LocalAgentDirectories
    Set-Content -Path $script:LocalAgentPidFile -Value $ProcessId -Encoding ascii
}

function Clear-LocalAgentPid {
    if (Test-Path $script:LocalAgentPidFile) {
        Remove-Item -LiteralPath $script:LocalAgentPidFile -Force -ErrorAction SilentlyContinue
    }
}

function Stop-BosmaxBackendProcess {
    $processes = @(Get-BosmaxBackendProcesses)
    if ($processes.Count -gt 0) {
        foreach ($process in $processes) {
            try {
                Stop-Process -Id $process.Id -Force -ErrorAction Stop
            } catch {
                if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
                    throw
                }
            }
        }
        Clear-LocalAgentPid
        return $true
    }

    Clear-LocalAgentPid
    return $false
}

function Get-TaskState {
    try {
        return Get-ScheduledTask -TaskName $script:LocalAgentTaskName -ErrorAction Stop
    } catch {
        return $null
    }
}

# --- Watchdog supervisor helpers -----------------------------------------
# Shared by the -Watchdog mode of start-local-agent.ps1. Kept here alongside
# the other lifecycle helpers so both one-shot and supervisor paths reuse the
# exact same process/port detection logic.

function Write-WatchdogLog {
    param(
        [Parameter(Mandatory = $true)][string]$EventName,
        [string]$Detail = ''
    )

    Ensure-LocalAgentDirectories
    $timestamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    $line = ("$timestamp [$EventName] $Detail").TrimEnd()
    try {
        Add-Content -Path $script:LocalAgentWatchdogLog -Value $line -Encoding utf8 -ErrorAction Stop
    } catch {
        # Never let logging failure crash the supervisor.
    }
    Write-Host $line
}

function Get-PortUnknownOwner {
    # Returns a descriptive string when $Port is held by a process whose command
    # line is NOT the BOSMAX agent (so the watchdog must NOT kill it or spawn a
    # duplicate). Returns $null when the port is free or owned by our agent.
    param([int]$Port = $script:BackendPort)

    $owner = Get-PortOwner -Port $Port
    if (-not $owner) {
        return $null
    }
    $commandLine = Get-ProcessCommandLine -ProcessId $owner.OwningProcess
    if (Test-IsBosmaxAgentCommandLine -CommandLine $commandLine) {
        return $null
    }
    return "PID=$($owner.OwningProcess) cmd=$commandLine"
}

function Get-WatchdogLockOwner {
    # Returns the PID of a LIVE watchdog (other than the current process) that
    # already owns the lock, else 0. Validates both liveness AND that the PID is
    # actually a start-local-agent.ps1 -Watchdog process (stale/false locks -> 0).
    if (-not (Test-Path $script:LocalAgentWatchdogLock)) {
        return 0
    }
    $pidText = (Get-Content $script:LocalAgentWatchdogLock -ErrorAction SilentlyContinue | Select-Object -First 1)
    $pidValue = 0
    if (-not ([int]::TryParse([string]$pidText, [ref]$pidValue))) {
        return 0
    }
    if ($pidValue -le 0 -or $pidValue -eq $PID) {
        return 0
    }
    $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if (-not $process) {
        return 0
    }
    $commandLine = Get-ProcessCommandLine -ProcessId $pidValue
    if ($commandLine -match 'start-local-agent\.ps1' -and $commandLine -match '-Watchdog') {
        return $pidValue
    }
    return 0
}

function Set-WatchdogLock {
    Ensure-LocalAgentDirectories
    Set-Content -Path $script:LocalAgentWatchdogLock -Value $PID -Encoding ascii
}

function Clear-WatchdogLock {
    if (-not (Test-Path $script:LocalAgentWatchdogLock)) {
        return
    }
    $pidText = (Get-Content $script:LocalAgentWatchdogLock -ErrorAction SilentlyContinue | Select-Object -First 1)
    $pidValue = 0
    if ([int]::TryParse([string]$pidText, [ref]$pidValue) -and $pidValue -eq $PID) {
        Remove-Item -LiteralPath $script:LocalAgentWatchdogLock -Force -ErrorAction SilentlyContinue
    }
}
