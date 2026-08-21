<#
.SYNOPSIS
  Bootstrap the provider-ready state in the existing dedicated Browser UAT profile.

.DESCRIPTION
  This is a bounded, read-only-gated bootstrap.  It never touches a personal
  Chrome profile, copies cookies, selects a Google account, or submits a Flow
  generation.  A restart is performed only for the exact dedicated UAT Chrome
  and only when the readiness receipt proves the unpacked extension is absent.
#>
[CmdletBinding()]
param(
  [string]$ExtensionPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\lib\common.ps1"
Ensure-BrowserUatDirectories

$readinessScript = Join-Path $PSScriptRoot 'flow-provider-readiness.mjs'
$extensionPathWasExplicit = -not [string]::IsNullOrWhiteSpace($ExtensionPath)
if (-not $extensionPathWasExplicit) {
  $ExtensionPath = [Environment]::GetEnvironmentVariable('BOSMAX_EXTENSION_PATH')
}
if ([string]::IsNullOrWhiteSpace($ExtensionPath)) {
  $repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
  foreach ($candidate in @(
      'C:\Users\USER\Desktop\_ref_flowkit\extension',
      (Join-Path $repoRoot 'extension')
    )) {
    if (Test-Path -LiteralPath (Join-Path $candidate 'manifest.json')) {
      $ExtensionPath = $candidate
      break
    }
  }
}
if ([string]::IsNullOrWhiteSpace($ExtensionPath)) {
  $ExtensionPath = 'C:\Users\USER\Desktop\_ref_flowkit\extension'
}
$ExtensionPath = [System.IO.Path]::GetFullPath($ExtensionPath)

function Invoke-Readiness {
  $raw = (& node $readinessScript `
    --cdp-url $script:CdpBaseUrl `
    --bosmax-url $script:BosmaxUrl `
    --extension-path $ExtensionPath `
    --profile-path $script:ChromeProfileDir `
    --browser-uat-root $script:BrowserUatRoot 2>&1 | Out-String).Trim()
  $obj = $null
  try { $obj = $raw | ConvertFrom-Json } catch {}
  [pscustomobject]@{ raw = $raw; receipt = $obj }
}

function Open-CdpTarget([string]$TargetUrl) {
  $encoded = [Uri]::EscapeDataString($TargetUrl)
  try {
    $response = Invoke-WebRequest `
      -Method Put `
      -Uri "$($script:CdpBaseUrl)/json/new?$encoded" `
      -UseBasicParsing `
      -TimeoutSec 8
    return $response.StatusCode -eq 200
  } catch {
    Write-Host "CDP_TARGET_OPEN_FAILED=$($_.Exception.Message)"
    return $false
  }
}

function Emit-Receipt([pscustomobject]$Result) {
  if ($Result -and $Result.raw) { Write-Output $Result.raw }
}

$first = Invoke-Readiness
if ($first.receipt -and $first.receipt.flow_provider_uat_ready -eq $true) {
  Emit-Receipt $first
  exit 0
}

if (-not $first.receipt) {
  Write-Output $first.raw
  Write-Output 'PRIMARY_BLOCKER=UAT_BROWSER_NOT_READY'
  exit 2
}

if ($first.receipt.video_job_in_flight -eq $true) {
  Write-Output $first.raw
  Write-Output 'PRIMARY_BLOCKER=UAT_PROVIDER_JOB_IN_FLIGHT'
  Write-Output 'No Chrome restart or Flow action was taken while a video job was in flight.'
  exit 2
}

if ($first.receipt.primary_blocker -eq 'UAT_EXTENSION_NOT_LOADED') {
  if (-not (Test-Path -LiteralPath (Join-Path $ExtensionPath 'manifest.json'))) {
    Write-Output $first.raw
    Write-Output 'PRIMARY_BLOCKER=OWNER_UAT_EXTENSION_INSTALL_REQUIRED'
    Write-Output "OWNER_ACTION=Install the unpacked extension from: $ExtensionPath"
    exit 2
  }

  # This is the only restart path: the receipt already proved the extension is
  # absent, and the process is restricted to the exact dedicated UAT profile.
  & "$PSScriptRoot\start-browser-uat.ps1" `
    -ForceRestartUatOnly `
    -ExtensionPath $ExtensionPath
  if ($LASTEXITCODE -ne 0) {
    Write-Output 'PRIMARY_BLOCKER=UAT_BROWSER_NOT_READY'
    Write-Output 'The dedicated UAT Chrome could not be restarted safely.'
    exit 2
  }

  $afterRestart = $null
  for ($attempt = 0; $attempt -lt 12; $attempt++) {
    Start-Sleep -Seconds 1
    $afterRestart = Invoke-Readiness
    if ($afterRestart.receipt -and $afterRestart.receipt.extension_loaded -eq $true) { break }
  }
  if (-not $afterRestart -or -not $afterRestart.receipt -or $afterRestart.receipt.extension_loaded -ne $true) {
    # Leave the same dedicated browser on the one-time owner install surface.
    $null = Open-CdpTarget 'chrome://extensions/'
    if ($afterRestart -and $afterRestart.raw) { Write-Output $afterRestart.raw }
    Write-Output 'PRIMARY_BLOCKER=OWNER_UAT_EXTENSION_INSTALL_REQUIRED'
    Write-Output "OWNER_ACTION=In the dedicated UAT Chrome, enable Developer mode, choose Load unpacked, and select: $ExtensionPath"
    Write-Output 'OWNER_ACTION_ONCE=After loading it, leave this same profile running and rerun this bootstrap once.'
    exit 2
  }
  $first = $afterRestart
}

if ($first.receipt.primary_blocker -eq 'OWNER_GOOGLE_FLOW_LOGIN_REQUIRED') {
  Write-Output $first.raw
  Write-Output 'PRIMARY_BLOCKER=OWNER_GOOGLE_FLOW_LOGIN_REQUIRED'
  Write-Output 'OWNER_ACTION=Complete Google login in the visible dedicated UAT Chrome window only; do not choose an account blindly.'
  exit 2
}

if ($first.receipt.extension_loaded -eq $true -and
    $first.receipt.flow_project_tab_found -ne $true) {
  $hasFlowLanding = $first.receipt.proof.flow_page_target_count -gt 0
  if (-not $hasFlowLanding) {
    $null = Open-CdpTarget 'https://labs.google/fx/tools/flow'
    Start-Sleep -Seconds 3
    $first = Invoke-Readiness
  }
  if ($first.receipt.primary_blocker -eq 'OWNER_GOOGLE_FLOW_LOGIN_REQUIRED') {
    Write-Output $first.raw
    Write-Output 'PRIMARY_BLOCKER=OWNER_GOOGLE_FLOW_LOGIN_REQUIRED'
    Write-Output 'OWNER_ACTION=Complete Google login in the visible dedicated UAT Chrome window only; do not choose an account blindly.'
    exit 2
  }
}

Emit-Receipt $first
exit 2
