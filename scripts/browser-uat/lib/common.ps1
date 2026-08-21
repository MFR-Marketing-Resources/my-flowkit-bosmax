# Shared constants for BOSMAX Browser UAT runtime (loopback CDP only).
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:BrowserUatRoot = 'C:\Users\USER\Desktop\_bosmax_runtime\browser_uat'
$script:ChromeProfileDir = Join-Path $script:BrowserUatRoot 'chrome-profile'
$script:LogsDir = Join-Path $script:BrowserUatRoot 'logs'
$script:StateDir = Join-Path $script:BrowserUatRoot 'state'
$script:ScreenshotsDir = Join-Path $script:BrowserUatRoot 'screenshots'
$script:TracesDir = Join-Path $script:BrowserUatRoot 'traces'
$script:ContractPath = Join-Path $script:BrowserUatRoot 'browser-uat.json'
$script:PidPath = Join-Path $script:StateDir 'chrome.pid'
$script:LockPath = Join-Path $script:StateDir 'start.lock'
$script:LeasePath = Join-Path $script:StateDir 'uat-lease.json'
$script:CdpHost = '127.0.0.1'
$script:CdpPort = 9222
$script:CdpBaseUrl = "http://$($script:CdpHost):$($script:CdpPort)"
$script:CdpVersionUrl = "$($script:CdpBaseUrl)/json/version"
$script:BosmaxUrl = 'http://127.0.0.1:8100'
$script:BosmaxHealthUrl = 'http://127.0.0.1:8100/health'
$script:ChromeExeCandidates = @(
  'C:\Program Files\Google\Chrome\Application\chrome.exe',
  'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
  (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'),
  'C:\Program Files\Google\Chrome for Testing\chrome.exe',
  'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
  'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
)

function Ensure-BrowserUatDirectories {
  foreach ($dir in @(
      $script:BrowserUatRoot,
      $script:ChromeProfileDir,
      $script:LogsDir,
      $script:StateDir,
      $script:ScreenshotsDir,
      $script:TracesDir
    )) {
    if (-not (Test-Path -LiteralPath $dir)) {
      New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
  }
}

function Resolve-BrowserExecutable {
  foreach ($path in $script:ChromeExeCandidates) {
    if ($path -and (Test-Path -LiteralPath $path)) {
      return $path
    }
  }
  throw 'No Chrome/Edge executable found for Browser UAT.'
}

function Get-BrowserProductVersion {
  param([string]$ExePath)
  try {
    return (Get-Item -LiteralPath $ExePath).VersionInfo.ProductVersion
  } catch {
    return 'unknown'
  }
}

function Test-CdpHealthy {
  try {
    $resp = Invoke-WebRequest -Uri $script:CdpVersionUrl -UseBasicParsing -TimeoutSec 3
    if ($resp.StatusCode -ne 200) { return $false }
    $null = $resp.Content | ConvertFrom-Json
    return $true
  } catch {
    return $false
  }
}

function Get-CdpVersionObject {
  $resp = Invoke-WebRequest -Uri $script:CdpVersionUrl -UseBasicParsing -TimeoutSec 5
  return ($resp.Content | ConvertFrom-Json)
}

function Get-LoopbackListeners {
  param([int]$Port)
  $items = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($null -eq $items) { return @() }
  return @($items)
}

function Get-Count {
  param($Value)
  if ($null -eq $Value) { return 0 }
  return @($Value).Count
}

function Test-CdpLoopbackOnly {
  $listeners = Get-LoopbackListeners -Port $script:CdpPort
  if ( (Get-Count $listeners)  -eq 0) { return $false }
  foreach ($l in $listeners) {
    $addr = [string]$l.LocalAddress
    if ($addr -ne '127.0.0.1' -and $addr -ne '::1') {
      return $false
    }
  }
  return $true
}

function Get-CdpListenPids {
  $listeners = Get-LoopbackListeners -Port $script:CdpPort
  return @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
}

function Test-ProcessIsUatChrome {
  param([int]$ProcessId)
  try {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
    $cmd = [string]$proc.CommandLine
    if (-not $cmd) { return $false }
    if ($cmd -notmatch [regex]::Escape("--remote-debugging-port=$($script:CdpPort)")) { return $false }
    if ($cmd -notmatch [regex]::Escape($script:ChromeProfileDir)) { return $false }
    return $true
  } catch {
    return $false
  }
}

function Write-BrowserUatContract {
  param(
    [string]$BrowserPath,
    [string]$BrowserVersion,
    [Nullable[int]]$ChromePid,
    [string]$ExtensionPath = ''
  )
  $payload = [ordered]@{
    schema            = 'bosmax-browser-uat/1'
    cdp_url           = $script:CdpBaseUrl
    cdp_host          = $script:CdpHost
    cdp_port          = $script:CdpPort
    bosmax_url        = $script:BosmaxUrl
    profile_path      = $script:ChromeProfileDir
    profile_kind      = 'DEDICATED_UAT'
    extension_path    = $ExtensionPath
    loopback_only     = $true
    browser_path      = $BrowserPath
    browser_version   = $BrowserVersion
    chrome_pid        = $ChromePid
    mcp_command       = 'npx -y chrome-devtools-mcp@latest --browser-url=http://127.0.0.1:9222'
    playwright_entry  = 'scripts/browser-uat/run-browser-uat.mjs'
    health_entry      = 'scripts/browser-uat/browser-uat-health.ps1'
    start_entry       = 'scripts/browser-uat/start-browser-uat.ps1'
    updated_at        = (Get-Date).ToUniversalTime().ToString('o')
  }
  $json = $payload | ConvertTo-Json -Depth 6
  Set-Content -LiteralPath $script:ContractPath -Value $json -Encoding utf8
}

function Acquire-StartLock {
  param([int]$TimeoutSec = 30)
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $fs = [System.IO.File]::Open(
        $script:LockPath,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
      )
      $bytes = [Text.Encoding]::UTF8.GetBytes("$PID $(Get-Date -Format o)")
      $fs.SetLength(0)
      $fs.Write($bytes, 0, $bytes.Length)
      $fs.Flush()
      return $fs
    } catch {
      Start-Sleep -Milliseconds 250
    }
  }
  throw "Could not acquire Browser UAT start lock: $($script:LockPath)"
}

function Release-StartLock {
  param($FileStream)
  if ($null -ne $FileStream) {
    try { $FileStream.Close() } catch {}
    try { $FileStream.Dispose() } catch {}
  }
}

function Get-BosmaxHealthObject {
  try {
    $resp = Invoke-WebRequest -Uri $script:BosmaxHealthUrl -UseBasicParsing -TimeoutSec 5
    return ($resp.Content | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Get-BosmaxRuntimeSha {
  try {
    $resp = Invoke-WebRequest -Uri 'http://127.0.0.1:8100/api/local-agent/runtime-provenance' -UseBasicParsing -TimeoutSec 5
    $obj = $resp.Content | ConvertFrom-Json
    return [string]$obj.runtime_sha
  } catch {
    return $null
  }
}
