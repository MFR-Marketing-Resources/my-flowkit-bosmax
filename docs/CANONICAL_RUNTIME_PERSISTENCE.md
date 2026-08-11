# Canonical Runtime Persistence — "my updates disappear after I reboot"

## Symptom
After a reboot (or opening the laptop the next day), the dashboard on :8100 reverts
to an older version: the Smart Registration module falls back, and repaired UI /
new functions on the **Visual / Canva** tab vanish.

## Root cause (NOT lost code)
Merged work is safe in `main` and in the immutable release under
`_bosmax_runtime\releases\<sha>`. What reverted was the **running server**.

A Startup-folder shortcut — `…\Startup\BOSMAX Flow Kit Local Agent.lnk` — launched
`scripts\start-local-agent.ps1` **from the dev root** `C:\Users\USER\Desktop\_ref_flowkit`.
That checkout sits on the unmerged WIP branch `fix/v4-ui-shell-and-f2v-avatar`, which
is many commits behind `main`, so every logon served a **stale dashboard bundle**.
The session-scoped canonical runtime died on shutdown and nothing canonical replaced
it — the stale dev-root launcher won :8100. The older `BOSMAX Local Runner.lnk`
was also audited as a duplicate startup path and is disabled by the installer.

`BACKGROUND: the runtime being canonical ≠ the runtime being persistent.` The
provenance lock (`/api/local-agent/runtime-provenance`) proves *what* is serving;
persistence makes the *canonical* one serve on every boot.

## Fix — auto-start the canonical runtime, retire the stale launcher
Run once (idempotent, reversible, no dev-root mutation, no provider spend):

```powershell
pwsh -File scripts/install-canonical-runtime-autostart.ps1
```

It:
1. Resolves a full-stack Python (fastapi + onnxruntime + Pillow + aiosqlite).
2. Copies the fail-closed launcher `start-canonical-runtime.ps1` to a **stable**
   location `_bosmax_runtime\launcher\` (boot never depends on the dev root or a
   version-pinned release path; the launcher re-resolves the pinned `current`
   release on each restart and **refuses to serve on drift**).
3. Creates a per-user **Startup shortcut** `…\Startup\BOSMAX Canonical Runtime.lnk`
   → the stable launcher (no admin required; matches how the machine already
   auto-starts). If run elevated it *also* registers a logon Scheduled Task
   `BOSMAX-Canonical-Runtime` (restart-on-failure) as a bonus — but the shortcut
   is the active mechanism either way.
4. Disables the known legacy Startup shortcuts →
   `…\BOSMAX Flow Kit Local Agent.lnk.disabled` and
   `…\BOSMAX Local Runner.lnk.disabled`.

## Verify (after a reboot, or any time the UI "looks old")
```powershell
pwsh -File scripts/verify-runtime-canonical.ps1
```
`RUNTIME_CANONICAL_OK …` = good. A non-zero exit prints exactly what drifted
(`DEV_ROOT_SERVING_PRODUCTION`, `SOURCE_STALE`, `DASHBOARD_BUNDLE_MISMATCH`, …).

## Keeping new merges live (the forward process)
Boot persistence keeps whatever `current` points at. After a PR merges to `main`,
point `current` at the new build so the next boot serves it:

```powershell
git -C C:\Users\USER\Desktop\_ref_flowkit fetch origin
pwsh -File scripts/deploy-canonical-release.ps1 -Sha <full origin/main SHA>   # updates `current`
# apply now (else it applies on next logon): stop the backend; the launcher's
# watchdog re-resolves `current` and respawns from the new release in ~3s.
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'agent\.main' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
pwsh -File scripts/verify-runtime-canonical.ps1
```

## Definition-of-done lock — MERGED != DEPLOYED

`MERGED != DEPLOYED`. A BOSMAX change is only complete after this exact chain:

```text
commit
→ push
→ PR
→ CI green
→ merge
→ immutable release built from the merge SHA
→ current pointer updated
→ canonical runtime restarted
→ runtime SHA == origin/main
→ source_stale = false
→ post-merge Smart Registration smoke PASS
```

`deploy-canonical-release.ps1` enforces the immutable-release build, manifest
validation, and `current` update. `verify-runtime-canonical.ps1` enforces the
runtime/origin SHA match, canonical release, canonical DB, and bundle match.
The post-merge smoke must re-open Product Detail and confirm the four tabs and
the per-product Visual / Canva CRUD controls after the restart.

## Rollback
```powershell
Remove-Item "$([Environment]::GetFolderPath('Startup'))\BOSMAX Canonical Runtime.lnk" -Force
Unregister-ScheduledTask -TaskName BOSMAX-Canonical-Runtime -Confirm:$false -ErrorAction SilentlyContinue
Rename-Item "$([Environment]::GetFolderPath('Startup'))\BOSMAX Flow Kit Local Agent.lnk.disabled" `
            "$([Environment]::GetFolderPath('Startup'))\BOSMAX Flow Kit Local Agent.lnk"
Rename-Item "$([Environment]::GetFolderPath('Startup'))\BOSMAX Local Runner.lnk.disabled" `
            "$([Environment]::GetFolderPath('Startup'))\BOSMAX Local Runner.lnk"
```

## Guarantees / non-goals
- The dev-root worktree (V4/Faceless/Montage WIP) is **left untouched** — only the
  boot *launcher* changes, never that branch's files.
- If the chosen Python is ever missing its deps, the launcher **fail-closes**
  (serves nothing) rather than serving stale code — `verify-runtime-canonical.ps1`
  will say so.
- This does not auto-advance `current` on merge; that stays an explicit step
  (`deploy-canonical-release.ps1`) so a build is never served before it is pinned.
