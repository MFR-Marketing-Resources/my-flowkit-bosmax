<#
.SYNOPSIS
  Dry-run or explicitly apply the one-time move to the durable runtime state root.

.DESCRIPTION
  Copies the canonical DB and runtime byte store out of the source checkout into
  <RuntimeRoot>\state. The default is read-only. -Apply requires a new, empty
  destination, verifies DB hashes and Product Truth row/byte diagnostics in a
  staging directory, then moves the verified directory into place. It never
  deletes the source store.
#>
param(
  [string]$Repo = "C:\Users\USER\Desktop\_ref_flowkit",
  [string]$RuntimeRoot = "C:\Users\USER\Desktop\_bosmax_runtime",
  [string]$StateRoot = "",
  [string]$Python = "python",
  [switch]$Apply
)
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($StateRoot)) { $StateRoot = Join-Path $RuntimeRoot "state" }
$repoResolved = (Resolve-Path -LiteralPath $Repo).Path.TrimEnd('\')
$stateResolved = [System.IO.Path]::GetFullPath($StateRoot).TrimEnd('\')
if ($stateResolved.Equals($repoResolved, [System.StringComparison]::OrdinalIgnoreCase) -or
    $stateResolved.StartsWith($repoResolved + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
  Write-Error "PRODUCTION_RUNTIME_STATE_ROOT_NOT_EXTERNAL: $stateResolved"
  exit 1
}

$sourceDb = Join-Path $repoResolved "flow_agent.db"
$sourceData = Join-Path $repoResolved "data"
$verifier = Join-Path $PSScriptRoot "verify-canonical-runtime-state.py"
if (-not (Test-Path -LiteralPath $sourceDb -PathType Leaf)) {
  Write-Error "PRODUCTION_RUNTIME_STATE_SOURCE_DB_MISSING: $sourceDb"
  exit 1
}
if (-not (Test-Path -LiteralPath $sourceData -PathType Container)) {
  Write-Error "PRODUCTION_RUNTIME_STATE_SOURCE_DATA_MISSING: $sourceData"
  exit 1
}
if (-not (Test-Path -LiteralPath $verifier -PathType Leaf)) {
  Write-Error "PRODUCTION_RUNTIME_STATE_VERIFIER_MISSING: $verifier"
  exit 1
}

function Read-StateReport([string]$Root, [string]$Db) {
  $json = (& $Python $verifier --root $Root --db $Db --json | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -and -not $json) { throw "PRODUCTION_RUNTIME_STATE_VERIFY_FAILED: $Root" }
  return $json | ConvertFrom-Json
}

$sourceReport = Read-StateReport -Root $repoResolved -Db $sourceDb
Write-Host ("SOURCE state={0} db={1} truth_locks={2} approved={3} approved_missing={4} approved_sha_mismatch={5}" -f `
  $repoResolved, $sourceDb, $sourceReport.truth_lock_rows, $sourceReport.approved_truth_locks,
  $sourceReport.approved_missing_bytes, $sourceReport.approved_sha_mismatches)
if ($sourceReport.error) { Write-Error "PRODUCTION_RUNTIME_STATE_SOURCE_INVALID: $($sourceReport.error)"; exit 1 }
if ([int]$sourceReport.approved_missing_bytes -gt 0 -or [int]$sourceReport.approved_sha_mismatches -gt 0) {
  Write-Warning "SOURCE_HAS_EXISTING_TRUTH_LOCK_DESYNC: tombstones/recovery will preserve this evidence; migration will not invent bytes."
}

if (-not $Apply) {
  Write-Host "DRY_RUN_OK: no files changed. Re-run with -Apply after reviewing the source report."
  exit 0
}

if (Test-Path -LiteralPath $StateRoot) {
  Write-Error "PRODUCTION_RUNTIME_STATE_TARGET_EXISTS: choose a new empty state root or remove only the explicitly named empty target before applying."
  exit 1
}

$stateParent = Split-Path -Parent $stateResolved
New-Item -ItemType Directory -Force -Path $stateParent | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$staging = Join-Path $stateParent ".runtime-state-migration-$stamp"
if (Test-Path -LiteralPath $staging) { Write-Error "PRODUCTION_RUNTIME_STATE_STAGING_EXISTS: $staging"; exit 1 }

New-Item -ItemType Directory -Force -Path $staging | Out-Null
try {
  Copy-Item -LiteralPath $sourceDb -Destination (Join-Path $staging "flow_agent.db") -Force
  Copy-Item -LiteralPath $sourceData -Destination (Join-Path $staging "data") -Recurse -Force

  $stagedDb = Join-Path $staging "flow_agent.db"
  $sourceHash = (Get-FileHash -LiteralPath $sourceDb -Algorithm SHA256).Hash
  $stagedHash = (Get-FileHash -LiteralPath $stagedDb -Algorithm SHA256).Hash
  if ($sourceHash -ne $stagedHash) { throw "PRODUCTION_RUNTIME_STATE_DB_HASH_MISMATCH" }

  $stagedReport = Read-StateReport -Root $staging -Db $stagedDb
  foreach ($key in @("product_count", "truth_lock_rows", "approved_truth_locks", "approved_missing_bytes", "approved_sha_mismatches", "truth_lock_paths_outside_root")) {
    if ([string]$sourceReport.$key -ne [string]$stagedReport.$key) {
      throw "PRODUCTION_RUNTIME_STATE_REPORT_MISMATCH: $key source=$($sourceReport.$key) staged=$($stagedReport.$key)"
    }
  }

  Move-Item -LiteralPath $staging -Destination $stateResolved
  $receipt = [ordered]@{
    schema = "bosmax-runtime-state-migration/1"
    migrated_at = (Get-Date).ToUniversalTime().ToString("o")
    source_root = $repoResolved
    state_root = $stateResolved
    source_db_sha256 = $sourceHash
    product_count = $stagedReport.product_count
    truth_lock_rows = $stagedReport.truth_lock_rows
    approved_truth_locks = $stagedReport.approved_truth_locks
    approved_missing_bytes = $stagedReport.approved_missing_bytes
    approved_sha_mismatches = $stagedReport.approved_sha_mismatches
  }
  $receipt | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $stateResolved "state-migration-receipt.json") -Encoding UTF8
  Write-Host "APPLY_OK: verified state root created at $stateResolved"
} catch {
  if (Test-Path -LiteralPath $staging) {
    Write-Warning "STAGING_LEFT_FOR_RECOVERY: $staging"
  }
  throw
}
