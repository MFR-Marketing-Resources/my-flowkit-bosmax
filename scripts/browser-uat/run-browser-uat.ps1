<#
.SYNOPSIS
  PowerShell wrapper for Playwright CDP Browser UAT harness.
#>
[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$HarnessArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. "$PSScriptRoot\lib\common.ps1"
Ensure-BrowserUatDirectories

# Ensure CDP is up first
$startScript = Join-Path $PSScriptRoot 'start-browser-uat.ps1'
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript
if ($LASTEXITCODE -ne 0) {
  Write-Host "BROWSER_UAT_RUN: FAIL (could not start/reuse CDP)"
  exit $LASTEXITCODE
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$entry = Join-Path $PSScriptRoot 'run-browser-uat.mjs'
$node = 'C:\Program Files\nodejs\node.exe'
if (-not (Test-Path -LiteralPath $node)) {
  $node = 'node'
}

$env:BOSMAX_CDP_URL = $script:CdpBaseUrl
$env:BOSMAX_UAT_URL = $script:BosmaxUrl
$env:BOSMAX_BROWSER_UAT_ROOT = $script:BrowserUatRoot

Push-Location $repoRoot
try {
  & $node $entry @HarnessArgs
  exit $LASTEXITCODE
} finally {
  Pop-Location
}
