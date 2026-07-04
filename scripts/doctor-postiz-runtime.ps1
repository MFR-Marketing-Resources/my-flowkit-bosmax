<#
.SYNOPSIS
    Read-only health check for the Postiz runtime provisioning — no secrets, no
    writes, no posting.

.DESCRIPTION
    Verifies the runtime `.env` has the required POSTIZ_* names (without printing
    the key), probes the Postiz base URL, and reads the BOSMAX Setup Doctor
    (GET /api/postiz/setup-status). It classifies the outcome so operators can
    tell a real config failure apart from the normal "configured but no social
    channel connected yet" state:

      READY                        - fully configured + >=1 channel connected.
      OWNER_CHANNEL_OAUTH_REQUIRED - config is correct (problems: []), but
                                     integrations_count=0. Connecting a channel
                                     is an owner-only OAuth step, NOT a defect.
      CONFIG_PROBLEMS              - setup-status reported problem codes.
      AGENT_DOWN                   - the BOSMAX agent did not answer.

.PARAMETER RuntimeRoot
    Runtime worktree root whose `.env` should be inspected.
    Defaults to the repository root that contains this script.

.PARAMETER AgentBaseUrl
    Base URL of the local BOSMAX agent. Default: http://127.0.0.1:8100

.OUTPUTS
    Safe status lines only (never a secret value).

.NOTES
    Exit code 0 = configuration is healthy (READY or OWNER_CHANNEL_OAUTH_REQUIRED).
    Exit code 1 = a real problem the operator must fix (CONFIG_PROBLEMS / AGENT_DOWN
    / missing runtime `.env` names).
#>
param(
    [string]$RuntimeRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$AgentBaseUrl = 'http://127.0.0.1:8100'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Test-HttpAnswers {
    # True if the URL produces ANY HTTP response — including an error status
    # (e.g. 502 while the Postiz backend boots). StrictMode-safe: never touches
    # a property that may be absent on a transport-level exception.
    param([string]$Url)
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 6 -ErrorAction Stop | Out-Null
        return $true
    } catch {
        $ex = $_.Exception
        if ($ex.PSObject.Properties.Match('Response').Count -gt 0 -and $null -ne $ex.Response) { return $true }
        if ($ex.PSObject.Properties.Match('StatusCode').Count -gt 0 -and $null -ne $ex.StatusCode) { return $true }
        return $false
    }
}

function Read-EnvMap {
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

$configOk = $true
$verdict = 'UNKNOWN'

# ── 1) Static runtime .env checks (no secret values printed) ──────────────
$envPath = Join-Path $RuntimeRoot '.env'
$envPresent = Test-Path -LiteralPath $envPath
Write-Host "ENV_PATH=$envPath"
Write-Host "ENV_FILE_PRESENT=$($envPresent.ToString().ToLower())"

$m = Read-EnvMap -Path $envPath
function Test-EnvKey { param($m, $k) return ($m.Contains($k) -and -not [string]::IsNullOrEmpty([string]$m[$k])) }

$enabledVal = if ($m.Contains('POSTIZ_ENABLED')) { [string]$m['POSTIZ_ENABLED'] } else { '' }
$enabledTrue = ($enabledVal.Trim().ToLower() -eq 'true')
$baseUrlSet = (Test-EnvKey $m 'POSTIZ_BASE_URL')
$keyPresent = ((Test-EnvKey $m 'POSTIZ_API_KEY') -and ([string]$m['POSTIZ_API_KEY'] -ne '<paste key>'))
$prefixSet = (Test-EnvKey $m 'POSTIZ_API_PREFIX')

Write-Host "POSTIZ_ENABLED_TRUE=$($enabledTrue.ToString().ToLower())"
Write-Host "POSTIZ_BASE_URL_SET=$($baseUrlSet.ToString().ToLower())"
Write-Host "POSTIZ_API_KEY_PRESENT=$($keyPresent.ToString().ToLower())"
Write-Host "POSTIZ_API_PREFIX_SET=$($prefixSet.ToString().ToLower())"

if (-not $envPresent -or -not $enabledTrue -or -not $baseUrlSet -or -not $keyPresent -or -not $prefixSet) {
    $configOk = $false
}

# ── 2) Probe the Postiz base URL (any HTTP answer = reachable) ────────────
$postizReachable = $false
if ($baseUrlSet) {
    $baseUrl = [string]$m['POSTIZ_BASE_URL']
    $postizReachable = Test-HttpAnswers $baseUrl
    if (-not $postizReachable) {
        # Windows IPv6 trap: `localhost` may resolve to ::1 where Docker's proxy
        # never answers while 127.0.0.1 does. Mirror the agent's own fallback so
        # the doctor does not falsely report an up service as unreachable.
        $u = $null
        try { $u = [Uri]$baseUrl } catch { $u = $null }
        if ($null -ne $u -and $u.Host -eq 'localhost') {
            if (Test-HttpAnswers ($baseUrl.Replace('localhost', '127.0.0.1'))) { $postizReachable = $true }
        }
    }
}
Write-Host "POSTIZ_REACHABLE=$($postizReachable.ToString().ToLower())"

# ── 3) BOSMAX Setup Doctor (authoritative live state) ─────────────────────
$setupUrl = "$AgentBaseUrl/api/postiz/setup-status"
$agentAnswered = $false
$problems = @()
$ready = $false
$integrationsCount = $null
try {
    $resp = Invoke-WebRequest -Uri $setupUrl -UseBasicParsing -TimeoutSec 12 -ErrorAction Stop
    $agentAnswered = $true
    $status = $resp.Content | ConvertFrom-Json
    if ($null -ne $status.problems) { $problems = @($status.problems) }
    $ready = [bool]$status.ready
    $integrationsCount = $status.integrations_count
    Write-Host "AGENT_SETUP_STATUS=reachable"
    Write-Host "SETUP_HEALTH_OK=$($status.health_ok.ToString().ToLower())"
    Write-Host "SETUP_POSTIZ_REACHABLE=$($status.postiz_reachable)"
    Write-Host "SETUP_INTEGRATIONS_COUNT=$integrationsCount"
    Write-Host "SETUP_READY=$($ready.ToString().ToLower())"
    Write-Host "SETUP_PROBLEMS=$([string]::Join(',', $problems))"
} catch {
    Write-Host "AGENT_SETUP_STATUS=unreachable"
}

# ── 4) Classify ───────────────────────────────────────────────────────────
if (-not $agentAnswered) {
    $verdict = 'AGENT_DOWN'
    $configOk = $false
} elseif ($problems.Count -gt 0) {
    $verdict = 'CONFIG_PROBLEMS'
    $configOk = $false
} elseif ($ready) {
    $verdict = 'READY'
} elseif ((($null -eq $integrationsCount) -or ($integrationsCount -eq 0)) -and $problems.Count -eq 0) {
    # Config is correct; the only missing piece is an owner OAuth channel connect.
    $verdict = 'OWNER_CHANNEL_OAUTH_REQUIRED'
} else {
    $verdict = 'CONFIG_PROBLEMS'
    $configOk = $false
}

Write-Host ""
Write-Host "DOCTOR_VERDICT=$verdict" -ForegroundColor $(
    if ($verdict -eq 'READY') { 'Green' }
    elseif ($verdict -eq 'OWNER_CHANNEL_OAUTH_REQUIRED') { 'Cyan' }
    else { 'Red' }
)

switch ($verdict) {
    'OWNER_CHANNEL_OAUTH_REQUIRED' {
        Write-Host "Postiz config is correct (problems: []). Connect a social channel"
        Write-Host "in the Postiz UI (Add Channel -> official OAuth) to reach READY."
    }
    'CONFIG_PROBLEMS' {
        Write-Host "Fix the problem codes above. Re-provision with:"
        Write-Host "  scripts/setup-postiz-runtime.ps1 -RuntimeRoot `"$RuntimeRoot`""
        Write-Host "then restart: scripts/start-local-agent.ps1 -ForceRestart"
    }
    'AGENT_DOWN' {
        Write-Host "The BOSMAX agent did not answer at $setupUrl."
        Write-Host "Start it: scripts/start-local-agent.ps1"
    }
}

if ($configOk) { exit 0 } else { exit 1 }
