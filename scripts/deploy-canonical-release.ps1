<#
.SYNOPSIS
  Build an immutable BOSMAX production release for :8100 and pin it as `current`.

.DESCRIPTION
  Creates C:\Users\USER\Desktop\_bosmax_runtime\releases\<sha> as a clean git
  worktree at <sha>, builds the dashboard SPA there, stamps runtime_manifest.json,
  and updates the `current` release pointer. Code lives in the release; the
  canonical MUTABLE DB and product byte store stay in a stable external state
  root (never copied into the release).

  Production must NEVER be launched directly from the mutable dev checkout
  (C:\Users\USER\Desktop\_ref_flowkit). Use start-canonical-runtime.ps1 to serve.

.PARAMETER Sha
  Full origin/main commit SHA to deploy.
#>
param(
  [Parameter(Mandatory = $true)][string]$Sha,
  [string]$Repo = "C:\Users\USER\Desktop\_ref_flowkit",
  [string]$RuntimeRoot = "C:\Users\USER\Desktop\_bosmax_runtime",
  [string]$StateRoot = "",
  [string]$Python = "C:\tmp\cutout-activation-venv\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($StateRoot)) { $StateRoot = Join-Path $RuntimeRoot "state" }
$repoResolved = [System.IO.Path]::GetFullPath($Repo).TrimEnd('\')
$stateResolved = [System.IO.Path]::GetFullPath($StateRoot).TrimEnd('\')
if ($stateResolved.Equals($repoResolved, [System.StringComparison]::OrdinalIgnoreCase) -or
    $stateResolved.StartsWith($repoResolved + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
  Write-Error "PRODUCTION_RUNTIME_STATE_ROOT_NOT_EXTERNAL: $stateResolved"
  exit 1
}
if (-not (Test-Path -LiteralPath $StateRoot -PathType Container)) {
  Write-Error "PRODUCTION_RUNTIME_STATE_ROOT_MISSING: run scripts/migrate-canonical-runtime-state.ps1 -Apply"
  exit 1
}
$Release = Join-Path $RuntimeRoot "releases\$Sha"
$CanonicalDb = Join-Path $StateRoot "flow_agent.db"
if (-not (Test-Path -LiteralPath $CanonicalDb -PathType Leaf)) {
  Write-Error "PRODUCTION_RUNTIME_STATE_DB_MISSING: $CanonicalDb"
  exit 1
}
if (-not (Test-Path -LiteralPath (Join-Path $StateRoot "data") -PathType Container)) {
  Write-Error "PRODUCTION_RUNTIME_STATE_DATA_MISSING: $StateRoot"
  exit 1
}
$env:BOSMAX_RUNTIME_ROOT = $RuntimeRoot
$env:BOSMAX_CANONICAL_STATE_ROOT = $StateRoot
$env:BOSMAX_CANONICAL_DB = $CanonicalDb

Write-Host "Deploying $Sha -> $Release"
New-Item -ItemType Directory -Force -Path (Join-Path $RuntimeRoot "releases") | Out-Null

if (-not (Test-Path (Join-Path $Release "agent\main.py"))) {
  & git -C $Repo fetch origin --quiet
  & git -C $Repo worktree add --detach $Release $Sha
}

# Immutable release must be clean.
$dirty = (& git -C $Release status --porcelain)
if ($dirty) { Write-Error "PRODUCTION_RUNTIME_DIRTY: release worktree is not clean"; exit 1 }

# Build the SPA in the release (dashboard/dist is gitignored — a source asset).
Push-Location (Join-Path $Release "dashboard")
try { & npm ci; & npm run build } finally { Pop-Location }
if (-not (Test-Path (Join-Path $Release "dashboard\dist\index.html"))) {
  Write-Error "PRODUCTION_BUNDLE_MISSING: dashboard build produced no dist"; exit 1
}

# Stamp the manifest (deployed_sha + built bundle) via the shared Python gate.
$stamp = (Get-Date).ToUniversalTime().ToString("o")
Push-Location $Release
try { & $Python -m agent.runtime_release write-manifest $Release --sha $Sha --at $stamp --db $CanonicalDb }
finally { Pop-Location }

# Fail-closed validation before pinning.
Push-Location $Release
try { $val = (& $Python -m agent.runtime_release validate $Release --db $CanonicalDb | Out-String) }
finally { Pop-Location }
$res = $val | ConvertFrom-Json
if (-not $res.ok) { Write-Error ("PROVENANCE_VALIDATION_FAILED " + $res.error_code); exit 1 }

# Pin `current` ONLY after validation passes.
Set-Content -Path (Join-Path $RuntimeRoot "current") -Value $Release -NoNewline
Write-Host "OK deployed_sha=$Sha release=$Release current=updated"
