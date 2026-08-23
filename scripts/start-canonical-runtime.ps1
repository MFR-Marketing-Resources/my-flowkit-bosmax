<#
.SYNOPSIS
  Fail-closed production launcher + watchdog for BOSMAX :8100.

.DESCRIPTION
  Serves :8100 ONLY from the pinned `current` immutable release
  (C:\Users\USER\Desktop\_bosmax_runtime\current -> releases\<sha>), never from
  the mutable dev checkout. Before every (re)start it runs the shared Python
  provenance gate (agent.runtime_release validate) and REFUSES to launch on:
    PRODUCTION_RUNTIME_DEV_ROOT_FORBIDDEN
    PRODUCTION_RUNTIME_MANIFEST_MISSING / _SHA_UNRESOLVABLE / _FILES_MISSING
    PRODUCTION_RUNTIME_DIRTY
    PRODUCTION_RUNTIME_SHA_MISMATCH
    PRODUCTION_DB_PATH_MISMATCH
    PRODUCTION_RUNTIME_STATE_ROOT_MISSING / _DB_MISSING / _DATA_MISSING
    PRODUCTION_BUNDLE_MISMATCH
  The watchdog re-resolves `current` and re-validates on EACH restart, so it can
  never silently respawn a stale dev branch onto :8100.

.PARAMETER Once
  Run the backend once (no watchdog restart loop).
#>
param(
  [switch]$Once,
  [string]$Repo = "C:\Users\USER\Desktop\_ref_flowkit",
  [string]$RuntimeRoot = "C:\Users\USER\Desktop\_bosmax_runtime",
  [string]$StateRoot = "",
  [string]$Python = "C:\tmp\cutout-activation-venv\Scripts\python.exe",
  [string]$ApiPort = "8100",
  [string]$WsPort = "8101"
)
$ErrorActionPreference = "Stop"
$CurrentPtr = Join-Path $RuntimeRoot "current"
if ([string]::IsNullOrWhiteSpace($StateRoot)) { $StateRoot = Join-Path $RuntimeRoot "state" }
$CanonicalDb = Join-Path $StateRoot "flow_agent.db"

function Assert-CanonicalState {
  $repoResolved = [System.IO.Path]::GetFullPath($Repo).TrimEnd('\')
  $stateResolved = [System.IO.Path]::GetFullPath($StateRoot).TrimEnd('\')
  if ($stateResolved.Equals($repoResolved, [System.StringComparison]::OrdinalIgnoreCase) -or
      $stateResolved.StartsWith($repoResolved + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Error "PRODUCTION_RUNTIME_STATE_ROOT_NOT_EXTERNAL: $stateResolved"
    exit 3
  }
  if (-not (Test-Path -LiteralPath $StateRoot -PathType Container)) {
    Write-Error "PRODUCTION_RUNTIME_STATE_ROOT_MISSING: run scripts/migrate-canonical-runtime-state.ps1 -Apply"
    exit 3
  }
  if (-not (Test-Path -LiteralPath $CanonicalDb -PathType Leaf)) {
    Write-Error "PRODUCTION_RUNTIME_STATE_DB_MISSING: $CanonicalDb"
    exit 3
  }
  if ((Get-Item -LiteralPath $CanonicalDb).Length -le 0) {
    Write-Error "PRODUCTION_RUNTIME_STATE_DB_EMPTY: $CanonicalDb"
    exit 3
  }
  if (-not (Test-Path -LiteralPath (Join-Path $StateRoot "data") -PathType Container)) {
    Write-Error "PRODUCTION_RUNTIME_STATE_DATA_MISSING: $StateRoot"
    exit 3
  }
}

function Resolve-CurrentRelease {
  if (-not (Test-Path $CurrentPtr)) { Write-Error "PRODUCTION_RUNTIME_NO_CURRENT_RELEASE"; exit 3 }
  $r = (Get-Content $CurrentPtr -Raw).Trim()
  if (-not $r -or -not (Test-Path (Join-Path $r "agent\main.py"))) {
    Write-Error "PRODUCTION_RUNTIME_FILES_MISSING: current release invalid"; exit 3
  }
  return $r
}

function Assert-Provenance([string]$Release) {
  Push-Location $Release
  try { $out = (& $Python -m agent.runtime_release validate $Release --db $CanonicalDb | Out-String) }
  finally { Pop-Location }
  $res = $out | ConvertFrom-Json
  if (-not $res.ok) {
    Write-Error ("PROVENANCE_LOCK_REFUSED " + $res.error_code + " release=" + $Release)
    exit 4
  }
  Write-Host ("provenance OK sha=" + $res.provenance.runtime_sha + " release=" + $Release)
}

do {
  Assert-CanonicalState
  $env:BOSMAX_RUNTIME_ROOT = $RuntimeRoot
  $env:BOSMAX_CANONICAL_STATE_ROOT = $StateRoot
  $env:BOSMAX_CANONICAL_DB = $CanonicalDb
  $env:FLOW_AGENT_DIR = $StateRoot # canonical DB + data stay outside releases and source checkouts
  $Release = Resolve-CurrentRelease
  Assert-Provenance $Release        # FAIL CLOSED before serving
  $env:API_PORT = $ApiPort
  $env:WS_PORT = $WsPort
  # Final Prompt Approval Gate — ENFORCED on the canonical runtime. Every
  # credit-bearing VIDEO dispatch must present a matching APPROVED review
  # snapshot before a credit is spent (IMG stays observe-only — credit-free).
  # Runtime-scoped: tests / CI / dev do not use this launcher, so they keep the
  # default-OFF observe behaviour. This is the canonical enablement mechanism.
  $env:EXECUTION_APPROVAL_GATE_ENFORCED = "1"
  Push-Location $Release
  try { & $Python -m agent.main } finally { Pop-Location }
  if ($Once) { break }
  Write-Host "backend exited; watchdog restarting from CURRENT release in 3s..."
  Start-Sleep -Seconds 3
} while ($true)
