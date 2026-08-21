<#
.SYNOPSIS
  Start (or reuse) the dedicated BOSMAX Browser UAT Chrome with loopback CDP :9222.

.DESCRIPTION
  - Never uses the user's personal Chrome profile.
  - Binds remote debugging to 127.0.0.1 only.
  - Idempotent: healthy existing UAT CDP is reused.
  - Fails clearly if :9222 is occupied by a non-UAT process.
  - Does not kill unrelated Chrome instances.
#>
[CmdletBinding()]
param(
  [switch]$ForceRestartUatOnly,
  [string]$ExtensionPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\lib\common.ps1"
Ensure-BrowserUatDirectories

$logPath = Join-Path $script:LogsDir ("start-browser-uat-{0:yyyyMMdd}.log" -f (Get-Date))
function Write-UatLog([string]$Message) {
  $line = "[{0:o}] {1}" -f (Get-Date).ToUniversalTime(), $Message
  Add-Content -LiteralPath $logPath -Value $line -Encoding utf8
  Write-Host $line
}

$browserExe = Resolve-BrowserExecutable
$browserVersion = Get-BrowserProductVersion -ExePath $browserExe
$extensionPathWasExplicit = -not [string]::IsNullOrWhiteSpace($ExtensionPath)
if (-not $extensionPathWasExplicit) {
  $ExtensionPath = [Environment]::GetEnvironmentVariable('BOSMAX_EXTENSION_PATH')
}
if ([string]::IsNullOrWhiteSpace($ExtensionPath)) {
  $repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
  $extensionCandidates = @(
    'C:\Users\USER\Desktop\_ref_flowkit\extension',
    (Join-Path $repoRoot 'extension')
  )
  foreach ($candidate in $extensionCandidates) {
    if (Test-Path -LiteralPath (Join-Path $candidate 'manifest.json')) {
      $ExtensionPath = $candidate
      break
    }
  }
}
if (-not [string]::IsNullOrWhiteSpace($ExtensionPath)) {
  $ExtensionPath = [System.IO.Path]::GetFullPath($ExtensionPath)
  if (-not (Test-Path -LiteralPath (Join-Path $ExtensionPath 'manifest.json'))) {
    if ($extensionPathWasExplicit) {
      throw "UAT extension manifest not found: $ExtensionPath"
    }
    Write-UatLog "WARN: extension path has no manifest; starting generic Browser UAT only path=$ExtensionPath"
    $ExtensionPath = ''
  }
}
$lock = $null

try {
  $lock = Acquire-StartLock -TimeoutSec 45

  if ((Test-CdpHealthy)) {
    $pids = @(Get-CdpListenPids)
    $allUat = $true
    foreach ($procId in $pids) {
      if (-not (Test-ProcessIsUatChrome -ProcessId $procId)) {
        $allUat = $false
        break
      }
    }
    if ($allUat -and (Test-CdpLoopbackOnly) -and -not $ForceRestartUatOnly) {
      $mainPid = @($pids | Select-Object -First 1)[0]
      Write-BrowserUatContract -BrowserPath $browserExe -BrowserVersion $browserVersion -ChromePid $mainPid -ExtensionPath $ExtensionPath
      if ($mainPid) { Set-Content -LiteralPath $script:PidPath -Value $mainPid -Encoding ascii }
      Write-UatLog "REUSE healthy UAT CDP on $($script:CdpBaseUrl) pid=$mainPid"
      Write-Host "BROWSER_UAT_START: REUSE"
      Write-Host "CDP_URL=$($script:CdpBaseUrl)"
      Write-Host "CHROME_PID=$mainPid"
      Write-Host "PROFILE=$($script:ChromeProfileDir)"
      exit 0
    }
    if (-not $allUat) {
      Write-UatLog "FAIL: port $($script:CdpPort) healthy but not dedicated UAT Chrome. pids=$($pids -join ',')"
      Write-Host "BROWSER_UAT_START: FAIL"
      Write-Host "Reason: CDP port $($script:CdpPort) is occupied by a non-UAT process."
      Write-Host "Stop that process manually, then re-run. Do not kill unrelated personal Chrome."
      exit 2
    }
  } else {
    $listeners = @(Get-LoopbackListeners -Port $script:CdpPort)
    if ($listeners.Count -gt 0) {
      $pids = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
      Write-UatLog "FAIL: port occupied unhealthy pids=$($pids -join ',')"
      Write-Host "BROWSER_UAT_START: FAIL"
      Write-Host "Reason: port $($script:CdpPort) is listening but /json/version is unhealthy."
      Write-Host "OwningProcess=$($pids -join ',')"
      exit 3
    }
  }

  if ($ForceRestartUatOnly) {
    $pids = @(Get-CdpListenPids)
    foreach ($procId in $pids) {
      if (Test-ProcessIsUatChrome -ProcessId $procId) {
        Write-UatLog "ForceRestart: stopping UAT chrome pid=$procId"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
      } else {
        Write-Host "BROWSER_UAT_START: FAIL"
        Write-Host "Reason: -ForceRestartUatOnly refused to touch non-UAT pid=$procId"
        exit 4
      }
    }
    Start-Sleep -Seconds 1
  }

  $stdoutLog = Join-Path $script:LogsDir 'chrome-uat.stdout.log'
  $stderrLog = Join-Path $script:LogsDir 'chrome-uat.stderr.log'

  # Chrome accepts --remote-debugging-address on modern Stable; bind loopback only.
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
    '--about-blank'
  )
  if (-not [string]::IsNullOrWhiteSpace($ExtensionPath)) {
    $args += "--load-extension=$ExtensionPath"
  }

  Write-UatLog "START $browserExe $($args -join ' ')"
  $proc = Start-Process -FilePath $browserExe -ArgumentList $args -PassThru -WindowStyle Minimized
  Set-Content -LiteralPath $script:PidPath -Value $proc.Id -Encoding ascii

  $deadline = (Get-Date).AddSeconds(30)
  $healthy = $false
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 400
    if (Test-CdpHealthy) {
      $healthy = $true
      break
    }
  }

  if (-not $healthy) {
    Write-UatLog "FAIL: CDP not healthy after start pid=$($proc.Id)"
    Write-Host "BROWSER_UAT_START: FAIL"
    Write-Host "Reason: CDP $($script:CdpVersionUrl) did not become healthy within 30s."
    Write-Host "Logs: $logPath"
    exit 5
  }

  if (-not (Test-CdpLoopbackOnly)) {
    Write-UatLog 'FAIL: CDP not loopback-only after start'
    Write-Host "BROWSER_UAT_START: FAIL"
    Write-Host 'Reason: CDP listener is not loopback-only. Stopping UAT chrome.'
    try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue } catch {}
    exit 6
  }

  if (-not (Test-ProcessIsUatChrome -ProcessId $proc.Id)) {
    # Parent may hand off to a child; accept any UAT pid on the port.
    $ok = $false
    foreach ($listenPid in (Get-CdpListenPids)) {
      if (Test-ProcessIsUatChrome -ProcessId $listenPid) { $ok = $true; break }
    }
    if (-not $ok) {
      Write-UatLog 'WARN: could not prove command line contains UAT profile; continuing because CDP healthy + loopback'
    }
  }

  $listenPid = @(Get-CdpListenPids | Select-Object -First 1)[0]
  if (-not $listenPid) { $listenPid = $proc.Id }
  Write-BrowserUatContract -BrowserPath $browserExe -BrowserVersion $browserVersion -ChromePid $listenPid -ExtensionPath $ExtensionPath
  Set-Content -LiteralPath $script:PidPath -Value $listenPid -Encoding ascii

  $ver = Get-CdpVersionObject
  Write-UatLog "READY pid=$listenPid browser=$($ver.Browser) webSocketDebuggerUrl=$($ver.webSocketDebuggerUrl)"
  Write-Host "BROWSER_UAT_START: PASS"
  Write-Host "CDP_URL=$($script:CdpBaseUrl)"
  Write-Host "CHROME_PID=$listenPid"
  Write-Host "PROFILE=$($script:ChromeProfileDir)"
  if (-not [string]::IsNullOrWhiteSpace($ExtensionPath)) {
    Write-Host "EXTENSION_PATH=$ExtensionPath"
  }
  Write-Host "BROWSER=$($ver.Browser)"
  exit 0
}
catch {
  Write-UatLog "ERROR $_"
  Write-Host "BROWSER_UAT_START: FAIL"
  Write-Host "Reason: $_"
  exit 1
}
finally {
  Release-StartLock -FileStream $lock
}
