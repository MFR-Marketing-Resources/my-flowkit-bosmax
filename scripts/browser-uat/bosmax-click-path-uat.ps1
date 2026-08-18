<#
.SYNOPSIS
  BOSMAX interactive click-path UAT (read-only) via dedicated CDP Chrome.
#>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\run-browser-uat.ps1" click-path
exit $LASTEXITCODE
