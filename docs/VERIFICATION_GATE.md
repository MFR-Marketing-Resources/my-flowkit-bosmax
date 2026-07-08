# Local Verification Gate

`scripts/verify-gate.ps1` is the **local** gate to run before opening or merging a PR. It
runs the checks that actually reflect the production + local-agent build path, so a change
**should not** be reported "green" while the real dashboard build is broken.

> **LOCAL ONLY.** This is not CI. It runs on the developer/agent machine. Do not report a
> change as CI-verified on the basis of this gate — the repo has no CI workflow.

> **Enforcement status — advisory, not a hard block.** There is no GitHub Actions CI and no
> required branch protection, and the pre-push hook is optional (not installed). The gate is a
> **local process control**: a human or agent *can* still bypass it, so it does not make a
> broken build *impossible* to merge. Rule of thumb: **PRs should not be reported green unless
> `scripts/verify-gate.ps1` passes locally.** Making this server-side enforceable (CI / required
> checks) is a separate future step — see the end of this doc.

## Why this exists

`tsc --noEmit -p tsconfig.json` and `vitest` can both pass while `npm run build`
(`tsc -b && vite build`) **fails** — `tsc -b` uses project references and is stricter.
PR #265 merged exactly that way: it added a `boolean` field to `PosterBuilderDraft`, which
broke `PosterBuilderShellForm`'s generic `value={draft[key]}` binding under `tsc -b`, so the
dashboard bundle could no longer be rebuilt — but the weaker checks that had been run were
green. PR #266 fixed the regression; this gate closes the local-verification gap that let it
through (it does not, by itself, make the miss impossible — see Enforcement status above).

**Acceptance (gate behavior):** if the real dashboard build fails, the gate exits non-zero —
even when vitest and pytest are green. (Verified: a transient `tsc -b` error yields
`DASHBOARD_BUILD FAIL` / `GATE RESULT: FAIL` / exit 1 while the other gates pass.) This
guarantees the gate's *own* exit code, not that the gate was run — running it is a process
discipline until server-side enforcement exists.

## What it runs

| Gate | Command | Notes |
|------|---------|-------|
| `MANDOR_CHECK` | `npx tsx scripts/mandor-check.ts` | Ownership (owned_paths). Auto-**SKIP** on a clean tree (nothing to check). |
| `DASHBOARD_BUILD` | `npm run build` (`tsc -b && vite build`) | The **real** build — load-bearing gate. |
| `DASHBOARD_VITEST` | `npm test` (`vitest run`) | Frontend component/unit smoke. |
| `BACKEND_PYTEST_SMOKE` | `python -m pytest <curated suites>` | Stable, high-signal backend suites. |

The full backend suite has known pre-existing failures (DB/fixture issues; see `AGENTS.md`)
that are unrelated to a given change, so the default gate runs a curated smoke set. Run the
full suite with `-Full`.

## Usage

```powershell
# Standard pre-PR gate:
powershell -ExecutionPolicy Bypass -File scripts\verify-gate.ps1

# Full backend suite (periodic deep check):
powershell -ExecutionPolicy Bypass -File scripts\verify-gate.ps1 -Full

# Clean tree / nothing staged (skip ownership check):
powershell -ExecutionPolicy Bypass -File scripts\verify-gate.ps1 -SkipMandor
```

Frontend-only convenience (build + vitest):

```bash
cd dashboard && npm run verify
```

## Optional: enable as a git pre-push hook

Not installed by default (it adds ~40s to every push). To opt in, create
`.git/hooks/pre-push` (make it executable) with:

```sh
#!/bin/sh
powershell -ExecutionPolicy Bypass -File scripts/verify-gate.ps1 || {
  echo "verify-gate failed — push blocked. Fix the build/tests or push --no-verify to override.";
  exit 1;
}
```

## Reporting rule

When reporting a change as verified, cite the gate's exact result (e.g. `GATE RESULT: PASS`
with each sub-gate's status) and label it **local proof only** (no CI ran). Never report a
change green if `DASHBOARD_BUILD` is FAIL. Prefer "PRs should not be reported green unless
`scripts/verify-gate.ps1` passes locally" over absolute claims like "impossible to merge broken"
— that is only true once server-side enforcement exists.

## Future: server-side enforcement (not yet done)

The gate is currently local/advisory only. To make it actually enforceable so a broken build
cannot merge regardless of who runs it:

1. Add a GitHub Actions workflow (`.github/workflows/verify.yml`) that runs the same layers on
   PRs: `npm ci` + `npm run build` + `npm test` (dashboard) and `pytest` (the curated smoke set).
2. Mark that workflow as a **required status check** via branch protection on `main`
   (needs repo-admin permission).

Until both exist, treat this gate as a discipline, not a guarantee.
