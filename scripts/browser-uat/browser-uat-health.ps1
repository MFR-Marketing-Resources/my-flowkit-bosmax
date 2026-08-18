<#
.SYNOPSIS
  Machine-readable + human health check for BOSMAX Browser UAT runtime.
.OUTPUTS
  Exit 0 when BROWSER_UAT_READY=true; non-zero otherwise.
#>
[CmdletBinding()]
param(
  [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\lib\common.ps1"
Ensure-BrowserUatDirectories

$browserExe = $null
$browserVersion = $null
try {
  $browserExe = Resolve-BrowserExecutable
  $browserVersion = Get-BrowserProductVersion -ExePath $browserExe
} catch {
  $browserExe = $null
  $browserVersion = $null
}

$cdpOk = Test-CdpHealthy
$loopbackOnly = $false
$chromePid = $null
$cdpBrowser = $null
if ($cdpOk) {
  $loopbackOnly = Test-CdpLoopbackOnly
  $pids = @(Get-CdpListenPids)
  if (@($pids).Count -gt 0) { $chromePid = $pids[0] }
  try {
    $ver = Get-CdpVersionObject
    $cdpBrowser = [string]$ver.Browser
  } catch {}
}

$bosmax = Get-BosmaxHealthObject
$bosmaxOk = $false
if ($null -ne $bosmax -and [string]$bosmax.status -eq 'ok') { $bosmaxOk = $true }
$runtimeSha = Get-BosmaxRuntimeSha

$ready = $cdpOk -and $loopbackOnly -and ($null -ne $browserExe)

$result = [ordered]@{
  BROWSER_UAT_READY     = $ready
  chrome_pid            = $chromePid
  chrome_path           = $browserExe
  chrome_version        = $browserVersion
  cdp_browser           = $cdpBrowser
  cdp_url               = $script:CdpBaseUrl
  cdp_port              = $script:CdpPort
  profile_path          = $script:ChromeProfileDir
  profile_kind          = 'DEDICATED_UAT'
  loopback_only         = $loopbackOnly
  json_version_ok       = $cdpOk
  bosmax_runtime_health = $(if ($bosmaxOk) { 'ok' } elseif ($null -eq $bosmax) { 'unreachable' } else { [string]$bosmax.status })
  bosmax_runtime_sha    = $runtimeSha
  bosmax_url            = $script:BosmaxUrl
  contract_path         = $script:ContractPath
  timestamp             = (Get-Date).ToUniversalTime().ToString('o')
}

if ($Json -or $true) {
  # Always print machine-readable block first.
  Write-Output ($result | ConvertTo-Json -Depth 5)
}

Write-Output ("BROWSER_UAT_READY={0}" -f ($(if ($ready) { 'true' } else { 'false' })).ToLower())
Write-Output ("cdp_url={0}" -f $script:CdpBaseUrl)
Write-Output ("loopback_only={0}" -f $loopbackOnly)
Write-Output ("json_version_ok={0}" -f $cdpOk)
Write-Output ("bosmax_runtime_health={0}" -f $result.bosmax_runtime_health)
Write-Output ("bosmax_runtime_sha={0}" -f $runtimeSha)
Write-Output ("chrome_pid={0}" -f $chromePid)
Write-Output ("profile_path={0}" -f $script:ChromeProfileDir)

if ($ready) { exit 0 } else { exit 1 }
