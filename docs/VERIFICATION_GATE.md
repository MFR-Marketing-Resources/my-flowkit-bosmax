# Local Verification Gate

`scripts/verify-gate.ps1` is the **local** gate to run before opening or merging a PR. It
runs the checks that actually reflect the production + local-agent build path, so a change
**should not** be reported "green" while the real dashboard build is broken.

> **LOCAL GATE.** This remains the developer/agent process-control entry point. The same
> gate is now executed by `.github/workflows/verify.yml` for pull requests targeting `main`
> and by manual workflow dispatch. A local pass is still local proof; a remote pass is
> reported separately as GitHub Actions proof.

> **Enforcement status — workflow present, branch protection separate.** GitHub Actions now
> runs the gate, but `main` still requires repository-admin configuration before the check can
> become a mandatory branch-protection rule. Rule of thumb: **PRs should not be reported green
> unless `scripts/verify-gate.ps1` passes locally and the remote workflow is green.**

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

The CI workflow passes `-VitestTestTimeout 15000` because hosted Windows runners can be
slower than the local workstation for jsdom tests. This changes only the test deadline; it
does not skip or select fewer tests.

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

## Server-side enforcement status

`.github/workflows/verify.yml` runs the same layers on pull requests: dependency installation,
the real dashboard build, Vitest, the curated backend pytest smoke set, and Mandor ownership
validation. Marking the resulting `verify / verify` check as **required** via branch protection
on `main` remains a repository-admin action; until that is configured, the workflow is genuine
remote evidence but not an immutable merge block.
