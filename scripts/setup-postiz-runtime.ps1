<#
.SYNOPSIS
    Safely (re)provision the BOSMAX runtime `.env` for the Postiz integration.

.DESCRIPTION
    The BOSMAX agent loads the repo-root `.env` at startup (agent/config.py).
    `.env` is gitignored, so it is NOT carried by Git and is LOST whenever a new
    runtime worktree is created or reset — which is why the Postiz Setup Doctor
    keeps regressing to POSTIZ_DISABLED / POSTIZ_BASE_URL_MISSING /
    POSTIZ_API_KEY_MISSING. This script makes that provisioning repeatable and
    safe: it fills in the non-secret POSTIZ_* keys, preserves an existing API
    key (or copies one from a source `.env` WITHOUT printing it), backs up any
    file it modifies, and never echoes secrets or the full `.env`.

    It changes ONLY the POSTIZ_* lines; every other line in an existing `.env`
    is preserved verbatim. Running it twice is idempotent.

.PARAMETER RuntimeRoot
    The runtime worktree root whose `.env` should be provisioned.
    Defaults to the repository root that contains this script.

.PARAMETER SourceEnv
    Optional path to another `.env` from which to copy POSTIZ_API_KEY when the
    runtime `.env` does not already have one. The value is never printed.

.PARAMETER BaseUrl
    Value for POSTIZ_BASE_URL. Default: http://localhost:5000
    (On Windows where `localhost` resolves to IPv6 first, use
    http://127.0.0.1:5000 — the Setup Doctor detects that trap.)

.PARAMETER ApiPrefix
    Value for POSTIZ_API_PREFIX. Default: /api/public/v1 (self-hosted Postiz).

.OUTPUTS
    Safe status lines only (no secret values):
      ENV_PATH=<path>
      KEY_PRESENT=true|false
      BASE_URL_SET=true|false
      CHANGED=true|false

.EXAMPLE
    pwsh -File scripts/setup-postiz-runtime.ps1

.EXAMPLE
    pwsh -File scripts/setup-postiz-runtime.ps1 -RuntimeRoot C:\path\to\worktree -SourceEnv C:\other\.env

.NOTES
    Never commit `.env`, `.env.backup-*`, or the API key. All are gitignored.
    After this script runs, RESTART the agent so the new values load:
      scripts/start-local-agent.ps1 -ForceRestart
#>
param(
    [string]$RuntimeRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$SourceEnv = '',
    [string]$BaseUrl = 'http://localhost:5000',
    [string]$ApiPrefix = '/api/public/v1'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$KEY_PLACEHOLDER = '<paste key>'

function Read-EnvMap {
    # Returns an ordered hashtable of KEY -> raw value string for a .env file.
    param([string]$Path)
    $map = [ordered]@{}
    if (-not (Test-Path -LiteralPath $Path)) { return $map }
    foreach ($raw in Get-Content -LiteralPath $Path) {
        $line = $raw.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { continue }
        if ($line.StartsWith('export ')) { $line = $line.Substring(7).TrimStart() }
        $idx = $line.IndexOf('=')
        if ($idx -lt 1) { continue }
        $k = $line.Substring(0, $idx).Trim()
        $v = $line.Substring($idx + 1).Trim()
        if ($v.Length -ge 2 -and $v[0] -eq $v[$v.Length - 1] -and ($v[0] -eq '"' -or $v[0] -eq "'")) {
            $v = $v.Substring(1, $v.Length - 2)
        }
        if ($k -ne '') { $map[$k] = $v }
    }
    return $map
}

function Get-PostizKey {
    # Returns the POSTIZ_API_KEY value from a .env, or '' — never printed.
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return '' }
    $m = Read-EnvMap -Path $Path
    if ($m.Contains('POSTIZ_API_KEY')) { return [string]$m['POSTIZ_API_KEY'] }
    return ''
}

if (-not (Test-Path -LiteralPath $RuntimeRoot -PathType Container)) {
    Write-Host "SETUP_POSTIZ_RUNTIME: FAIL" -ForegroundColor Red
    Write-Host "Reason: RuntimeRoot does not exist: $RuntimeRoot"
    exit 1
}

$envPath = Join-Path $RuntimeRoot '.env'

# ── Resolve the API key without ever printing it ──────────────────────────
$existingKey = Get-PostizKey -Path $envPath
$keyValue = $existingKey
$keySource = 'existing'
if ([string]::IsNullOrEmpty($keyValue) -or $keyValue -eq $KEY_PLACEHOLDER) {
    if ($SourceEnv -ne '') {
        if (-not (Test-Path -LiteralPath $SourceEnv)) {
            Write-Host "SETUP_POSTIZ_RUNTIME: FAIL" -ForegroundColor Red
            Write-Host "Reason: SourceEnv not found: $SourceEnv"
            exit 1
        }
        $srcKey = Get-PostizKey -Path $SourceEnv
        if (-not [string]::IsNullOrEmpty($srcKey) -and $srcKey -ne $KEY_PLACEHOLDER) {
            $keyValue = $srcKey
            $keySource = 'copied-from-source'
        }
    }
}
if ([string]::IsNullOrEmpty($keyValue)) {
    $keyValue = $KEY_PLACEHOLDER
    $keySource = 'placeholder'
}
$keyPresent = ($keyValue -ne $KEY_PLACEHOLDER)

# ── Desired non-secret POSTIZ_* values (API key handled above) ────────────
$desired = [ordered]@{
    'POSTIZ_ENABLED'           = 'true'
    'POSTIZ_BASE_URL'          = $BaseUrl
    'POSTIZ_API_KEY'           = $keyValue
    'POSTIZ_UPLOAD_MODE'       = 'file'
    'POSTIZ_DEFAULT_POST_TYPE' = 'draft'
    'POSTIZ_API_PREFIX'        = $ApiPrefix
}

# ── Rewrite ONLY the POSTIZ_* lines; preserve everything else verbatim ────
$origLines = @()
if (Test-Path -LiteralPath $envPath) { $origLines = @(Get-Content -LiteralPath $envPath) }

$seen = @{}
$newLines = New-Object System.Collections.Generic.List[string]
foreach ($raw in $origLines) {
    $trim = $raw.Trim()
    $handled = $false
    if ($trim -ne '' -and -not $trim.StartsWith('#')) {
        $probe = $trim
        if ($probe.StartsWith('export ')) { $probe = $probe.Substring(7).TrimStart() }
        $idx = $probe.IndexOf('=')
        if ($idx -ge 1) {
            $k = $probe.Substring(0, $idx).Trim()
            if ($desired.Contains($k)) {
                $newLines.Add("$k=$($desired[$k])")
                $seen[$k] = $true
                $handled = $true
            }
        }
    }
    if (-not $handled) { $newLines.Add($raw) }
}
# Append any POSTIZ_* keys that were not already present.
$appended = $false
foreach ($k in $desired.Keys) {
    if (-not $seen.ContainsKey($k)) {
        if (-not $appended) {
            if ($newLines.Count -gt 0 -and $newLines[$newLines.Count - 1].Trim() -ne '') { $newLines.Add('') }
            $newLines.Add('# Postiz integration (provisioned by scripts/setup-postiz-runtime.ps1)')
            $appended = $true
        }
        $newLines.Add("$k=$($desired[$k])")
    }
}

$newContent = ($newLines -join "`n") + "`n"
$oldContent = if (Test-Path -LiteralPath $envPath) { (Get-Content -LiteralPath $envPath -Raw) } else { '' }
$changed = ($newContent -ne $oldContent)

if ($changed) {
    if (Test-Path -LiteralPath $envPath) {
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $backup = Join-Path $RuntimeRoot ".env.backup-$stamp"
        Copy-Item -LiteralPath $envPath -Destination $backup -Force
        Write-Host "BACKUP=$backup"
    }
    # UTF-8 without BOM so the agent's dotenv parser reads the first key cleanly.
    [System.IO.File]::WriteAllText($envPath, $newContent, (New-Object System.Text.UTF8Encoding($false)))
}

# ── Safe status output (never the key, never the full file) ───────────────
Write-Host "SETUP_POSTIZ_RUNTIME: PASS" -ForegroundColor Green
Write-Host "ENV_PATH=$envPath"
Write-Host "KEY_PRESENT=$($keyPresent.ToString().ToLower())"
Write-Host "KEY_SOURCE=$keySource"
$baseUrlSet = (-not [string]::IsNullOrEmpty($BaseUrl))
Write-Host "BASE_URL_SET=$($baseUrlSet.ToString().ToLower())"
Write-Host "CHANGED=$($changed.ToString().ToLower())"
if (-not $keyPresent) {
    Write-Host ""
    Write-Host "ACTION REQUIRED (owner-only): no API key yet." -ForegroundColor Yellow
    Write-Host "  Open $BaseUrl -> Settings -> Public API -> generate an API key,"
    Write-Host "  then set POSTIZ_API_KEY in: $envPath  (do not commit it)."
}
Write-Host ""
Write-Host "NEXT: restart the agent so the new values load:" -ForegroundColor Cyan
Write-Host "  scripts/start-local-agent.ps1 -ForceRestart"

# Missing key is a documented owner step, not a script failure.
exit 0
