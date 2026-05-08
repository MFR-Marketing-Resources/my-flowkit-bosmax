$script:RepoRoot = Split-Path $PSScriptRoot -Parent
$script:LocalAgentTaskName = 'BOSMAX Flow Kit Local Agent'
$script:LocalAgentStateDir = Join-Path $script:RepoRoot '.local-agent'
$script:LocalAgentLogDir = Join-Path $script:LocalAgentStateDir 'logs'
$script:LocalAgentPidFile = Join-Path $script:LocalAgentStateDir 'backend.pid'
$script:LocalAgentStdout = Join-Path $script:LocalAgentLogDir 'backend.stdout.log'
$script:LocalAgentStderr = Join-Path $script:LocalAgentLogDir 'backend.stderr.log'
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
    if (Test-Path $script:LocalAgentPidFile) {
        $pidText = (Get-Content $script:LocalAgentPidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        $pidValue = 0
        if ([int]::TryParse([string]$pidText, [ref]$pidValue) -and $pidValue -gt 0) {
            $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
            if ($process) {
                $commandLine = Get-ProcessCommandLine -ProcessId $pidValue
                if (Test-IsBosmaxAgentCommandLine -CommandLine $commandLine) {
                    return $process
                }
            }
        }
    }

    $portOwner = Get-PortOwner -Port $script:BackendPort
    if ($portOwner) {
        $commandLine = Get-ProcessCommandLine -ProcessId $portOwner.OwningProcess
        if (Test-IsBosmaxAgentCommandLine -CommandLine $commandLine) {
            return Get-Process -Id $portOwner.OwningProcess -ErrorAction SilentlyContinue
        }
    }

    return $null
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
    $process = Get-BosmaxBackendProcess
    if ($process) {
        Stop-Process -Id $process.Id -Force -ErrorAction Stop
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
