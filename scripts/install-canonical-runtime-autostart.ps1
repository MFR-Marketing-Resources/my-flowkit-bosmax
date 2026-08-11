<#
.SYNOPSIS
  Make the CANONICAL :8100 runtime survive reboots, and retire the stale dev-root
  launcher that reverted the app to an unmerged branch every morning.

.DESCRIPTION
  Root cause of "my updates disappear after I reboot": a Startup-folder shortcut
  ("BOSMAX Flow Kit Local Agent.lnk") launched scripts/start-local-agent.ps1 from
  the DEV ROOT (C:\Users\USER\Desktop\_ref_flowkit) — an unmerged WIP branch — so
  every logon served a stale dashboard bundle. Merged code was never lost; the
  boot server was just the wrong tree.

  This installer:
    1. Resolves a full-stack Python (fastapi + onnxruntime + Pillow + aiosqlite).
    2. Copies the fail-closed launcher (start-canonical-runtime.ps1) to a STABLE
       location under the runtime root, so boot never depends on the dev root or
       a version-pinned release path. The launcher itself re-resolves the pinned
       `current` release on every (re)start and refuses to serve on drift.
    3. Registers a logon Scheduled Task ("BOSMAX-Canonical-Runtime") that runs the
       stable launcher hidden, single-instance, restart-on-failure.
    4. Disables the legacy dev-root Startup shortcut (renamed *.disabled) so it can
       never again race for :8100 and serve stale UI.

  Idempotent (safe to re-run). Does NOT modify the dev-root working tree, does NOT
  touch the canonical DB, spends no provider credits. Reversible: see the runbook
  docs/CANONICAL_RUNTIME_PERSISTENCE.md.

.PARAMETER Python
  Override the interpreter. Default: auto-detect a full-stack venv.

.PARAMETER NoDisableLegacy
  Keep the legacy dev-root Startup shortcut in place (not recommended).
#>
param(
  [string]$Repo = "C:\Users\USER\Desktop\_ref_flowkit",
  [string]$RuntimeRoot = "C:\Users\USER\Desktop\_bosmax_runtime",
  [string]$Python = "",
  [string]$TaskName = "BOSMAX-Canonical-Runtime",
  [switch]$NoDisableLegacy
)
$ErrorActionPreference = "Stop"

function Test-FullStackPython([string]$exe) {
  if (-not $exe -or -not (Test-Path $exe)) { return $false }
  try {
    & $exe -c "import fastapi,uvicorn,onnxruntime,PIL,numpy,aiosqlite" 2>$null
    return ($LASTEXITCODE -eq 0)
  } catch { return $false }
}

# 1) Resolve a full-stack Python (has the cutout engine deps too).
$candidates = @()
if ($Python) { $candidates += $Python }
$candidates += @(
  "C:\tmp\cutout-activation-venv\Scripts\python.exe",
  (Join-Path $Repo ".venv\Scripts\python.exe")
)
$chosen = $candidates | Where-Object { Test-FullStackPython $_ } | Select-Object -First 1
if (-not $chosen) {
  Write-Error ("NO_FULLSTACK_PYTHON: none of [" + ($candidates -join "; ") + "] import fastapi+uvicorn+onnxruntime+PIL+numpy+aiosqlite. Install the deps (pip install -r requirements.txt -r requirements-cutout.txt) into one of them, or pass -Python.")
  exit 3
}
Write-Host "python: $chosen"

# 2) Copy the fail-closed launcher to a STABLE, version-independent location.
$currentPtr = Join-Path $RuntimeRoot "current"
if (-not (Test-Path $currentPtr)) { Write-Error "NO_CURRENT_RELEASE: $currentPtr missing. Deploy first: scripts/deploy-canonical-release.ps1 -Sha <origin/main SHA>"; exit 3 }
$releaseDir = (Get-Content $currentPtr -Raw).Trim()
$launcherSrc = Join-Path $releaseDir "scripts\start-canonical-runtime.ps1"
if (-not (Test-Path $launcherSrc)) { $launcherSrc = Join-Path $Repo "scripts\start-canonical-runtime.ps1" }
if (-not (Test-Path $launcherSrc)) { Write-Error "LAUNCHER_MISSING: start-canonical-runtime.ps1 not found in release or repo."; exit 3 }
$launcherDir = Join-Path $RuntimeRoot "launcher"
New-Item -ItemType Directory -Force -Path $launcherDir | Out-Null
$launcherDst = Join-Path $launcherDir "start-canonical-runtime.ps1"
Copy-Item $launcherSrc $launcherDst -Force
Write-Host "launcher: $launcherDst (copied from $launcherSrc)"

$psArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$launcherDst`" -Repo `"$Repo`" -RuntimeRoot `"$RuntimeRoot`" -Python `"$chosen`""
$psExe  = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"

# 3) PRIMARY (no admin required): a per-user Startup shortcut -> the stable
#    launcher. This matches how the machine already auto-starts and needs no
#    elevation, so it works in a locked-down session.
$startup = [Environment]::GetFolderPath('Startup')
$lnkPath = Join-Path $startup "BOSMAX Canonical Runtime.lnk"
$sh  = New-Object -ComObject WScript.Shell
$lnk = $sh.CreateShortcut($lnkPath)
$lnk.TargetPath       = $psExe
$lnk.Arguments        = $psArgs
$lnk.WorkingDirectory = $RuntimeRoot
$lnk.WindowStyle      = 7   # minimized / hidden
$lnk.Description       = "Fail-closed BOSMAX :8100 canonical runtime (pinned release); replaces the stale dev-root launcher."
$lnk.Save()
Write-Host "startup shortcut: $lnkPath (runs at logon, no admin required)"

# 3b) BONUS (only if elevated): a logon Scheduled Task with restart-on-failure.
#     Non-fatal when it needs admin — the Startup shortcut above is the active
#     mechanism either way.
try {
  $action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $psArgs
  $trigger = New-ScheduledTaskTrigger -AtLogOn
  $settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -RunLevel Limited -Force -ErrorAction Stop `
    -Description "Fail-closed BOSMAX :8100 canonical runtime (serves the pinned 'current' release, refuses the stale dev root)." | Out-Null
  Write-Host "scheduled task registered (bonus, restart-on-failure): $TaskName"
} catch {
  Write-Host "scheduled task skipped (needs elevation): $($_.Exception.Message)"
  Write-Host "  -> the Startup shortcut is the active auto-start; re-run elevated to also add the task."
}

# 4) Disable the legacy dev-root Startup shortcut (the stale-serving culprit).
if (-not $NoDisableLegacy) {
  $legacy = Join-Path ([Environment]::GetFolderPath('Startup')) "BOSMAX Flow Kit Local Agent.lnk"
  if (Test-Path $legacy) {
    $bak = "$legacy.disabled"
    if (Test-Path $bak) { Remove-Item $bak -Force }
    Rename-Item $legacy $bak -Force
    Write-Host "disabled legacy Startup shortcut -> $bak"
  } else {
    Write-Host "legacy Startup shortcut already absent/disabled"
  }
}

Write-Host ("INSTALL_OK autostart={0} launcher={1} python={2} current={3}" -f $lnkPath, $launcherDst, $chosen, $releaseDir)
Write-Host "Next: log off/on (or run the launcher now), then verify with scripts/verify-runtime-canonical.ps1."
