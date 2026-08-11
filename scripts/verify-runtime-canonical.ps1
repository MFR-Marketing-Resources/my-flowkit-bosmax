<#
.SYNOPSIS
  One-shot health check: is :8100 serving the CANONICAL pinned release (not the
  stale dev checkout)?

.DESCRIPTION
  Queries /api/local-agent/runtime-provenance and fails (non-zero exit) if the
  runtime is not canonical, is serving the dev root, is behind origin/main, is on
  a non-canonical DB, or is serving a mismatched dashboard bundle. Use it after a
  reboot (or any time the UI "looks like an old version") to confirm what is
  actually serving. Read-only; never restarts or mutates anything.

.EXAMPLE
  pwsh -File scripts/verify-runtime-canonical.ps1
  # RUNTIME_CANONICAL_OK sha=c0834222... db_canonical=True

.EXAMPLE
  pwsh -File scripts/verify-runtime-canonical.ps1 -Quiet; if ($LASTEXITCODE) { ... }
#>
param(
  [string]$ApiBase = "http://127.0.0.1:8100",
  [switch]$Quiet
)
$ErrorActionPreference = "Stop"

try {
  $p = Invoke-RestMethod -Uri "$ApiBase/api/local-agent/runtime-provenance" -TimeoutSec 10
} catch {
  Write-Error "RUNTIME_UNREACHABLE: $ApiBase is not serving /api/local-agent/runtime-provenance ($($_.Exception.Message))"
  exit 2
}

$problems = @()
if (-not $p.canonical_runtime)         { $problems += "NOT_CANONICAL" }
if ($p.dev_root_serving_production)    { $problems += "DEV_ROOT_SERVING_PRODUCTION" }
if ($p.source_stale)                   { $problems += "SOURCE_STALE(runtime=$($p.runtime_sha) origin_main=$($p.origin_main))" }
if (-not $p.db_canonical)              { $problems += "DB_NOT_CANONICAL($($p.db_path))" }
if (-not $p.bundle_matches)            { $problems += "DASHBOARD_BUNDLE_MISMATCH" }
if ($p.release_dirty)                  { $problems += "RELEASE_DIRTY" }

if ($problems.Count -gt 0) {
  Write-Error ("RUNTIME_NOT_CANONICAL: " + ($problems -join ", ") + " -- run scripts/install-canonical-runtime-autostart.ps1, or deploy the latest SHA with scripts/deploy-canonical-release.ps1 then restart the runtime.")
  exit 1
}

if (-not $Quiet) {
  Write-Host ("RUNTIME_CANONICAL_OK sha={0} db_canonical={1} bundle={2}" -f $p.runtime_sha, $p.db_canonical, $p.dashboard_bundle)
}
exit 0
