# Local Verification Gate

`scripts/verify-gate.ps1` is the single authoritative **local** gate to run before opening
or merging a PR. It runs the checks that actually reflect the production + local-agent
build path, so a change can **never** be reported "green" while the real dashboard build
is broken.

> **LOCAL ONLY.** This is not CI. It runs on the developer/agent machine. Do not report a
> change as CI-verified on the basis of this gate — the repo has no CI workflow.

## Why this exists

`tsc --noEmit -p tsconfig.json` and `vitest` can both pass while `npm run build`
(`tsc -b && vite build`) **fails** — `tsc -b` uses project references and is stricter.
PR #265 merged exactly that way: it added a `boolean` field to `PosterBuilderDraft`, which
broke `PosterBuilderShellForm`'s generic `value={draft[key]}` binding under `tsc -b`, so the
dashboard bundle could no longer be rebuilt — but the weaker checks that had been run were
green. PR #266 fixed the regression; this gate makes the class of miss impossible to repeat.

**Acceptance:** if the real dashboard build fails, the gate exits non-zero — even when
vitest and pytest are green. (Verified: a transient `tsc -b` error yields
`DASHBOARD_BUILD FAIL` / `GATE RESULT: FAIL` / exit 1 while the other gates pass.)

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
with each sub-gate's status). Never report a change green if `DASHBOARD_BUILD` is FAIL.
