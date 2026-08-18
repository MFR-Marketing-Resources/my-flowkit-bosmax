<#
.SYNOPSIS
  Install user-level logon autostart for BOSMAX Browser UAT CDP runtime.
#>
[CmdletBinding()]
param([switch]$Remove)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\lib\common.ps1"
Ensure-BrowserUatDirectories

$taskName = 'BOSMAX Browser UAT Runtime'
$runtimeScripts = Join-Path $script:BrowserUatRoot 'scripts'
New-Item -ItemType Directory -Path $runtimeScripts -Force | Out-Null

# Runtime-local launcher (stable path for Task Scheduler)
$runtimeCommon = Join-Path $runtimeScripts 'common.ps1'
$runtimeStart = Join-Path $runtimeScripts 'start-browser-uat.ps1'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'lib\common.ps1') -Destination $runtimeCommon -Force

# Build a self-contained start script that dotsources sibling common.ps1
$startBody = @'
<#
.SYNOPSIS
  Runtime-mirrored start for BOSMAX Browser UAT (autostart).
#>
[CmdletBinding()]
param([switch]$ForceRestartUatOnly)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\common.ps1"
# Delegate to repo copy if available; else inline minimal start via common helpers.
$repoStartCandidates = @(
  'C:\Users\USER\Desktop\_ref_flowkit\scripts\browser-uat\start-browser-uat.ps1',
  (Join-Path (Split-Path $PSScriptRoot -Parent) '..\..\scripts\browser-uat\start-browser-uat.ps1')
)
foreach ($c in $repoStartCandidates) {
  try {
    $resolved = (Resolve-Path -LiteralPath $c -ErrorAction SilentlyContinue)
    if ($resolved) {
      # Prefer calling the repo script when present (full logic)
    }
  } catch {}
}

# Inline start (always works from mirrored common.ps1)
Ensure-BrowserUatDirectories
$logPath = Join-Path $script:LogsDir ("start-browser-uat-{0:yyyyMMdd}.log" -f (Get-Date))
function Write-UatLog([string]$Message) {
  $line = "[{0:o}] {1}" -f (Get-Date).ToUniversalTime(), $Message
  Add-Content -LiteralPath $logPath -Value $line -Encoding utf8
  Write-Host $line
}

$browserExe = Resolve-BrowserExecutable
$browserVersion = Get-BrowserProductVersion -ExePath $browserExe
$lock = $null
try {
  $lock = Acquire-StartLock -TimeoutSec 45
  if ((Test-CdpHealthy)) {
    $pids = @(Get-CdpListenPids)
    $allUat = $true
    foreach ($procId in $pids) {
      if (-not (Test-ProcessIsUatChrome -ProcessId $procId)) { $allUat = $false; break }
    }
    if ($allUat -and (Test-CdpLoopbackOnly) -and -not $ForceRestartUatOnly) {
      $mainPid = @($pids | Select-Object -First 1)[0]
      Write-BrowserUatContract -BrowserPath $browserExe -BrowserVersion $browserVersion -ChromePid $mainPid
      if ($mainPid) { Set-Content -LiteralPath $script:PidPath -Value $mainPid -Encoding ascii }
      Write-UatLog "REUSE healthy UAT CDP on $($script:CdpBaseUrl) pid=$mainPid"
      Write-Host "BROWSER_UAT_START: REUSE"
      exit 0
    }
    if (-not $allUat) {
      Write-Host "BROWSER_UAT_START: FAIL"
      Write-Host "Reason: CDP port occupied by non-UAT process"
      exit 2
    }
  } else {
    $listeners = @(Get-LoopbackListeners -Port $script:CdpPort)
    if (@($listeners).Count -gt 0) {
      Write-Host "BROWSER_UAT_START: FAIL"
      Write-Host "Reason: port listening but CDP unhealthy"
      exit 3
    }
  }

  if ($ForceRestartUatOnly) {
    foreach ($procId in @(Get-CdpListenPids)) {
      if (Test-ProcessIsUatChrome -ProcessId $procId) {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
      } else {
        Write-Host "BROWSER_UAT_START: FAIL non-UAT pid=$procId"
        exit 4
      }
    }
    Start-Sleep -Seconds 1
  }

  $args = @(
    "--remote-debugging-port=$($script:CdpPort)",
    "--remote-debugging-address=$($script:CdpHost)",
    "--user-data-dir=$($script:ChromeProfileDir)",
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-sync',
    '--disable-background-networking',
    '--disable-component-update',
    '--password-store=basic',
    'about:blank'
  )
  Write-UatLog "START $browserExe $($args -join ' ')"
  $proc = Start-Process -FilePath $browserExe -ArgumentList $args -PassThru -WindowStyle Minimized
  Set-Content -LiteralPath $script:PidPath -Value $proc.Id -Encoding ascii
  $deadline = (Get-Date).AddSeconds(30)
  $healthy = $false
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 400
    if (Test-CdpHealthy) { $healthy = $true; break }
  }
  if (-not $healthy) {
    Write-Host "BROWSER_UAT_START: FAIL CDP timeout"
    exit 5
  }
  if (-not (Test-CdpLoopbackOnly)) {
    try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
    Write-Host "BROWSER_UAT_START: FAIL not loopback-only"
    exit 6
  }
  $listenPid = @(Get-CdpListenPids | Select-Object -First 1)[0]
  if (-not $listenPid) { $listenPid = $proc.Id }
  Write-BrowserUatContract -BrowserPath $browserExe -BrowserVersion $browserVersion -ChromePid $listenPid
  Set-Content -LiteralPath $script:PidPath -Value $listenPid -Encoding ascii
  Write-UatLog "READY pid=$listenPid"
  Write-Host "BROWSER_UAT_START: PASS"
  exit 0
} catch {
  Write-UatLog "ERROR $_"
  Write-Host "BROWSER_UAT_START: FAIL"
  Write-Host "Reason: $_"
  exit 1
} finally {
  Release-StartLock -FileStream $lock
}
'@
Set-Content -LiteralPath $runtimeStart -Value $startBody -Encoding utf8

$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runtimeStart`""

if ($Remove) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  $startup = [Environment]::GetFolderPath('Startup')
  $lnk = Join-Path $startup 'BOSMAX Browser UAT Runtime.lnk'
  if (Test-Path -LiteralPath $lnk) { Remove-Item -LiteralPath $lnk -Force }
  Write-Host 'BROWSER_UAT_AUTOSTART: REMOVED'
  exit 0
}

$taskOk = $false
try {
  $action = New-ScheduledTaskAction -Execute $ps -Argument $arg
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
  $taskOk = $true
  Write-Host "BROWSER_UAT_AUTOSTART: TASK=$taskName"
} catch {
  Write-Warning "Scheduled task register failed: $_"
}

$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup 'BOSMAX Browser UAT Runtime.lnk'
$w = New-Object -ComObject WScript.Shell
$sc = $w.CreateShortcut($lnkPath)
$sc.TargetPath = $ps
$sc.Arguments = $arg
$sc.WorkingDirectory = $script:BrowserUatRoot
$sc.WindowStyle = 7
$sc.Description = 'BOSMAX dedicated UAT Chrome CDP 127.0.0.1:9222'
$sc.Save()
Write-Host "BROWSER_UAT_AUTOSTART: STARTUP_LNK=$lnkPath"

[Environment]::SetEnvironmentVariable('BOSMAX_CDP_URL', $script:CdpBaseUrl, 'User')
[Environment]::SetEnvironmentVariable('BOSMAX_UAT_URL', $script:BosmaxUrl, 'User')
[Environment]::SetEnvironmentVariable('BOSMAX_BROWSER_UAT_ROOT', $script:BrowserUatRoot, 'User')
$env:BOSMAX_CDP_URL = $script:CdpBaseUrl
$env:BOSMAX_UAT_URL = $script:BosmaxUrl
$env:BOSMAX_BROWSER_UAT_ROOT = $script:BrowserUatRoot

Write-BrowserUatContract -BrowserPath (Resolve-BrowserExecutable) -BrowserVersion (Get-BrowserProductVersion -ExePath (Resolve-BrowserExecutable)) -ChromePid $null
Write-Host "BROWSER_UAT_AUTOSTART: PASS task_ok=$taskOk"
exit 0
