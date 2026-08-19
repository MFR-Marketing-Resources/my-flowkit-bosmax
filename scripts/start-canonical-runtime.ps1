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
  [string]$Python = "C:\tmp\cutout-activation-venv\Scripts\python.exe",
  [string]$ApiPort = "8100",
  [string]$WsPort = "8101"
)
$ErrorActionPreference = "Stop"
$CurrentPtr = Join-Path $RuntimeRoot "current"
$CanonicalDb = Join-Path $Repo "flow_agent.db"

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
  $Release = Resolve-CurrentRelease
  Assert-Provenance $Release        # FAIL CLOSED before serving
  $env:FLOW_AGENT_DIR = $Repo       # canonical DB + data + .env stay external
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
