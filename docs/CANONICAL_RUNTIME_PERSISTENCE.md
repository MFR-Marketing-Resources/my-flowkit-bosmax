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
it — the stale dev-root launcher won :8100.

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
3. Registers a logon Scheduled Task **`BOSMAX-Canonical-Runtime`** (hidden,
   single-instance, restart-on-failure).
4. Disables the legacy dev-root Startup shortcut → `…\BOSMAX Flow Kit Local Agent.lnk.disabled`.

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
pwsh -File scripts/deploy-canonical-release.ps1 -Sha <full origin/main SHA>
# then restart the runtime now (else it applies on next logon):
Stop-ScheduledTask -TaskName BOSMAX-Canonical-Runtime; Start-ScheduledTask -TaskName BOSMAX-Canonical-Runtime
pwsh -File scripts/verify-runtime-canonical.ps1
```

Merge → `deploy-canonical-release.ps1 <sha>` → verify. That is the whole loop.

## Rollback
```powershell
Unregister-ScheduledTask -TaskName BOSMAX-Canonical-Runtime -Confirm:$false
Rename-Item "$([Environment]::GetFolderPath('Startup'))\BOSMAX Flow Kit Local Agent.lnk.disabled" `
            "$([Environment]::GetFolderPath('Startup'))\BOSMAX Flow Kit Local Agent.lnk"
```

## Guarantees / non-goals
- The dev-root worktree (V4/Faceless/Montage WIP) is **left untouched** — only the
  boot *launcher* changes, never that branch's files.
- If the chosen Python is ever missing its deps, the launcher **fail-closes**
  (serves nothing) rather than serving stale code — `verify-runtime-canonical.ps1`
  will say so.
- This does not auto-advance `current` on merge; that stays an explicit step
  (`deploy-canonical-release.ps1`) so a build is never served before it is pinned.
