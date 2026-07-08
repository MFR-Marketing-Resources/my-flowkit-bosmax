<#
.SYNOPSIS
    BOSMAX Flow Kit — LOCAL verification gate.

.DESCRIPTION
    ONE authoritative pre-PR / pre-merge gate that runs the checks that actually
    reflect the production + local-agent build path — so a change can NEVER be
    reported "green" while the real dashboard build is broken.

    Why this exists: `tsc --noEmit -p tsconfig.json` and `vitest` can both pass while
    `npm run build` (`tsc -b && vite build`, stricter via project references) FAILS.
    PR #265 merged exactly that way and broke the dashboard bundle rebuild. This gate
    runs the REAL build, not a weaker proxy. See docs/VERIFICATION_GATE.md.

    LOCAL ONLY — this is not CI. It runs on the developer/agent machine. Do not report
    a change as CI-verified on the basis of this gate.

.PARAMETER Full
    Run the FULL backend pytest suite instead of the curated smoke set. The full suite
    has known pre-existing failures (see AGENTS.md) unrelated to a given change, so the
    default gate runs a stable, high-signal smoke set.

.PARAMETER SkipMandor
    Skip the ownership (mandor-check) gate. Use only when intentionally running the gate
    on a clean tree with nothing to own-check.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\verify-gate.ps1
#>
param(
    [switch]$Full,
    [switch]$SkipMandor
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$DashboardDir = Join-Path $RepoRoot 'dashboard'
$LogDir = Join-Path $env:TEMP 'bosmax-verify-gate'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# Curated backend smoke set: stable, fast, high-signal suites that must stay green.
# (The FULL suite carries pre-existing DB/fixture reds tracked in AGENTS.md; -Full runs it.)
$SmokeTests = @(
    'tests/unit/test_copywriting_readiness_service.py',
    'tests/api/test_copywriting_readiness_api.py',
    'tests/unit/test_copyset_approval_formula_gate.py',
    'tests/unit/test_poster_copy_governance.py',
    'tests/unit/test_poster_copy_recommendation_service.py',
    'tests/unit/test_poster_prompt_draft_service.py',
    'tests/unit/test_claim_boundary.py',
    'tests/unit/test_female_health_sensitive.py',
    'tests/unit/test_canonical_prompt_compiler.py',
    'tests/unit/test_formula_validator_service.py',
    'tests/unit/test_copy_set_service.py',
    'tests/unit/test_copy_binding_service.py',
    'tests/api/test_copy_sets_api.py'
)

$results = @()

function Add-Result {
    param([string]$Name, [string]$Status, [double]$Seconds, [string]$LogFile = '', [string]$Note = '')
    $script:results += [pscustomobject]@{
        Name = $Name; Status = $Status; Seconds = [math]::Round($Seconds, 1); LogFile = $LogFile; Note = $Note
    }
}

function Invoke-Gate {
    param([string]$Name, [string]$WorkingDir, [scriptblock]$Command)
    $log = Join-Path $LogDir ("{0}.log" -f ($Name -replace '[^A-Za-z0-9]', '_'))
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    Push-Location $WorkingDir
    try {
        & $Command *>&1 | Tee-Object -FilePath $log | Out-Null
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        $sw.Stop()
    }
    if ($code -eq 0) {
        Add-Result -Name $Name -Status 'PASS' -Seconds $sw.Elapsed.TotalSeconds -LogFile $log
    } else {
        Add-Result -Name $Name -Status 'FAIL' -Seconds $sw.Elapsed.TotalSeconds -LogFile $log -Note "exit=$code"
    }
}

Write-Host ''
Write-Host '================================================================' -ForegroundColor Cyan
Write-Host '  BOSMAX FLOW KIT - LOCAL VERIFICATION GATE' -ForegroundColor Cyan
Write-Host '  LOCAL ONLY - this is NOT CI. Run before opening / merging a PR.' -ForegroundColor Cyan
Write-Host '================================================================' -ForegroundColor Cyan

# Gate 1 - Ownership (mandor-check). Skips cleanly when there is nothing to check.
if ($SkipMandor) {
    Add-Result -Name 'MANDOR_CHECK' -Status 'SKIP' -Seconds 0 -Note 'skipped by flag'
} else {
    $log = Join-Path $LogDir 'MANDOR_CHECK.log'
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    Push-Location $RepoRoot
    try {
        & npx tsx scripts/mandor-check.ts *>&1 | Tee-Object -FilePath $log | Out-Null
        $code = $LASTEXITCODE
    } finally { Pop-Location; $sw.Stop() }
    $out = (Get-Content $log -Raw -ErrorAction SilentlyContinue)
    if ($code -eq 0) {
        Add-Result -Name 'MANDOR_CHECK' -Status 'PASS' -Seconds $sw.Elapsed.TotalSeconds -LogFile $log
    } elseif ($out -match 'No changed files') {
        Add-Result -Name 'MANDOR_CHECK' -Status 'SKIP' -Seconds $sw.Elapsed.TotalSeconds -LogFile $log -Note 'no changed files to own-check'
    } else {
        Add-Result -Name 'MANDOR_CHECK' -Status 'FAIL' -Seconds $sw.Elapsed.TotalSeconds -LogFile $log -Note "exit=$code"
    }
}

# Gate 2 - THE REAL dashboard build (tsc -b && vite build). This is the load-bearing gate.
Invoke-Gate -Name 'DASHBOARD_BUILD' -WorkingDir $DashboardDir -Command { & npm run build }

# Gate 3 - Frontend vitest smoke.
Invoke-Gate -Name 'DASHBOARD_VITEST' -WorkingDir $DashboardDir -Command { & npm test }

# Gate 4 - Backend pytest smoke (or full with -Full).
$pytestArgs = if ($Full) { @('-m', 'pytest', '-q') } else { @('-m', 'pytest', '-q') + $SmokeTests }
$gateName = if ($Full) { 'BACKEND_PYTEST_FULL' } else { "BACKEND_PYTEST_SMOKE ($($SmokeTests.Count) suites)" }
Invoke-Gate -Name $gateName -WorkingDir $RepoRoot -Command { & python @pytestArgs }

# ---- Summary ----
Write-Host ''
Write-Host '----------------------------------------------------------------' -ForegroundColor Cyan
$anyFail = $false
foreach ($r in $results) {
    $color = switch ($r.Status) { 'PASS' { 'Green' } 'SKIP' { 'Yellow' } default { 'Red' } }
    if ($r.Status -eq 'FAIL') { $anyFail = $true }
    $line = "  {0,-40} {1,-5} {2,6}s {3}" -f $r.Name, $r.Status, $r.Seconds, $r.Note
    Write-Host $line -ForegroundColor $color
}
Write-Host '----------------------------------------------------------------' -ForegroundColor Cyan

# On failure, echo the tail of each failing gate's log so the cause is visible inline.
foreach ($r in ($results | Where-Object { $_.Status -eq 'FAIL' -and $_.LogFile })) {
    Write-Host ''
    Write-Host ("  ---- {0} : last 25 lines ----" -f $r.Name) -ForegroundColor Red
    Get-Content $r.LogFile -Tail 25 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" }
}

Write-Host ''
if ($anyFail) {
    Write-Host '  GATE RESULT: FAIL' -ForegroundColor Red
    Write-Host '  LOCAL ONLY - no CI ran. Do NOT report this change as green.' -ForegroundColor Red
    Write-Host '================================================================' -ForegroundColor Cyan
    exit 1
} else {
    Write-Host '  GATE RESULT: PASS' -ForegroundColor Green
    Write-Host '  LOCAL ONLY - no CI ran. Do not claim CI verification.' -ForegroundColor Green
    Write-Host '================================================================' -ForegroundColor Cyan
    exit 0
}
