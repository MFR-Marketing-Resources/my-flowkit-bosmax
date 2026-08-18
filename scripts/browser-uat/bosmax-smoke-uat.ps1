<#
.SYNOPSIS
  BOSMAX SPA smoke UAT via dedicated CDP Chrome.
#>
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\run-browser-uat.ps1" smoke
exit $LASTEXITCODE
