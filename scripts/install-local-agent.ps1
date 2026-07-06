Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\local-agent-common.ps1"

Set-Location $script:RepoRoot
Ensure-LocalAgentDirectories

function Require-Command {
    param([Parameter(Mandatory = $true)][string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Required command not found: $Name"
    }
    return $command.Source
}

function Register-StartupShortcut {
    $powershellExe = (Get-Command powershell.exe -ErrorAction Stop).Source
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($script:StartupShortcutPath)
    $shortcut.TargetPath = $powershellExe
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$script:RepoRoot\scripts\start-local-agent.ps1`" -Watchdog"
    $shortcut.WorkingDirectory = $script:RepoRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Start BOSMAX Flow Kit local agent on Windows logon.'
    $shortcut.Save()
}

Write-Host "INSTALL_LOCAL_AGENT: START" -ForegroundColor Cyan

$pythonSource = Require-Command -Name 'python'
$npmSource = Require-Command -Name 'npm'

$venvPython = Join-Path $script:RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Host "Creating local virtual environment..."
    & $pythonSource -m venv .venv
}

$venvPython = Join-Path $script:RepoRoot '.venv\Scripts\python.exe'
Write-Host "Installing backend dependencies..."
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r requirements.txt

Push-Location (Join-Path $script:RepoRoot 'dashboard')
try {
    if (-not (Test-Path 'node_modules')) {
        Write-Host "Installing dashboard dependencies..."
        if (Test-Path 'package-lock.json') {
            & $npmSource ci
        } else {
            & $npmSource install
        }
    }

    Write-Host "Building production dashboard..."
    & $npmSource run build
} finally {
    Pop-Location
}

$task = Get-TaskState
if ($task) {
    Unregister-ScheduledTask -TaskName $script:LocalAgentTaskName -Confirm:$false | Out-Null
}

$principalUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$actionArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$script:RepoRoot\scripts\start-local-agent.ps1`" -Watchdog"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $actionArgs
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $principalUser -LogonType Interactive -RunLevel Limited
$autoStartMode = 'SCHEDULED_TASK'

try {
    Register-ScheduledTask `
        -TaskName $script:LocalAgentTaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description 'Start BOSMAX Flow Kit local agent on Windows logon.' `
        -ErrorAction Stop | Out-Null
} catch {
    Register-StartupShortcut
    $autoStartMode = 'STARTUP_SHORTCUT'
}

if ($autoStartMode -eq 'SCHEDULED_TASK' -and (Test-Path $script:StartupShortcutPath)) {
    try {
        Remove-Item -LiteralPath $script:StartupShortcutPath -Force -ErrorAction Stop
    } catch {
        Write-Host "Warning: stale startup shortcut could not be removed at $script:StartupShortcutPath" -ForegroundColor Yellow
    }
}

Stop-BosmaxBackendProcess | Out-Null
& "$PSScriptRoot\start-local-agent.ps1" -ForceRestart

# Launch the durable watchdog supervisor detached for this session so the
# backend is auto-restarted on mid-session death immediately (not only at the
# next logon). It adopts the just-started healthy agent; the single-owner lock
# prevents a duplicate supervisor.
Start-Process `
    -FilePath 'powershell.exe' `
    -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "$script:RepoRoot\scripts\start-local-agent.ps1", '-Watchdog') `
    -WorkingDirectory $script:RepoRoot `
    -WindowStyle Hidden | Out-Null

Write-Host "INSTALL_LOCAL_AGENT: PASS" -ForegroundColor Green
Write-Host "TASK_NAME: $script:LocalAgentTaskName"
Write-Host "AUTO_START: $autoStartMode"
Write-Host "HEALTH_URL: $script:HealthUrl"
Write-Host "DASHBOARD_URL: $script:DashboardUrl"
