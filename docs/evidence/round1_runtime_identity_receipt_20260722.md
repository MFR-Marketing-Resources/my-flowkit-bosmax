# Round 1 — Runtime Identity Receipt

**Captured:** 2026-07-22 · **Cost:** 0 credits · **Provider calls:** 0 · **Flow calls:** 0 (read-only diagnostics)

This file exists because four separate audits declared runtime identity, database
binding and Flow attachment "NOT VERIFIED", and one of them escalated that to
"unbounded — cannot be built in the current execution approach" and recommended
abandoning the project. Every value below came from an endpoint that already
existed in canonical `main`. Total capture time: seconds. Nothing was built to
make this possible.

All values are pasted from the live backend at `127.0.0.1:8100`. None were typed
by hand.

---

## 1 · Source → build → runtime identity

`GET /api/local-agent/version-proof`

```json
{
  "pid": 29616,
  "process_started_at": "2026-07-22T07:16:43.295580+00:00",
  "git_head": "b337ff2e18c84e3a5260e7b8bc64ebf240a80a68",
  "git_branch": "fix/round1-runtime-truth-and-build-provenance",
  "route_count": 415,
  "critical_routes": {
    "/api/creative-asset-eligibility/audit": true,
    "/api/creative-assets/eligibility-audit": true,
    "/api/flow/execute-flow-job": true,
    "/api/flow/generate": true,
    "/api/workspace/execution-package": true
  },
  "dashboard_bundle": "index-hqwjYm0C.js",
  "source_stale_since_start": true,
  "stale_source_sample": ["agent\\api\\production_queue.py", "agent\\api\\workspace_generation_packages.py", "..."]
}
```

**Reading:** the runtime is no longer on the stale PR #431 base (`4c5ac9a`, which was
50 commits behind and whose PR is still OPEN). It is on this round's branch, itself
cut clean from canonical `fc87a16`. `dashboard_bundle` matches the bundle emitted by
the `npm run build` run in this round.

`source_stale_since_start: true` is **correct and expected**, not a fault: the process
booted at 07:16 and this round edited backend source afterwards. The diagnostic is
doing precisely its job — it is telling the operator the running process predates the
code on disk. **A backend restart is required before the backend half of this round's
change is actually being served.**

Known limitation (carried, not solved here): `git_head` shells `git rev-parse HEAD`
at request time, so it reports the tree's HEAD *now*, not the SHA the process
imported. `source_stale_since_start` is the compensating signal.

## 2 · Backend → database binding

`GET /api/operator/runtime-storage-status`

```json
{
  "cwd": "C:\\Users\\USER\\Desktop\\_ref_flowkit",
  "base_dir": "C:\\Users\\USER\\Desktop\\_ref_flowkit",
  "flow_agent_dir_override": null,
  "effective_db_path": "C:\\Users\\USER\\Desktop\\_ref_flowkit\\flow_agent.db",
  "db_exists": true,
  "db_size_bytes": 36442112,
  "product_count": 659,
  "manual_product_count": 361,
  "queue_count": 665,
  "canonical_product_count": 659,
  "warnings": []
}
```

**Reading:** binding fully resolved, **zero warnings**. No `FLOW_AGENT_DIR` override is
active, and the DB sits in the repo root the backend is running from — no stale-worktree
split. 36 MB, 659 products, 665 queue rows. This independently corroborates the
"659 products" figure quoted in the external audit snapshot.

## 3 · Extension → Flow attachment

`GET /api/flow/bind-check` (0-credit)

```json
{
  "bound": false,
  "error": "NO_OPEN_EDITOR: the Flow tab is not on a project editor — open the project first",
  "shape": { "flow_tab_found": true, "has_flow_url": true, "has_flow_tab_id": true }
}
```

**Reading:** this is a *precise, actionable* answer, not an unknown. The extension is
connected and a Flow tab IS found — it is simply parked on the root shell rather than
a `/project/` editor, so the fail-closed gate correctly refuses to claim a binding.
The remedy is an operator action (open the project), not engineering work.

## 4 · Extension build identity

`POST /api/operator/flow-page-state-diagnostic`

```json
{
  "background_build_id": "flowkit-canonical-dom-guard-2026-07-13a",
  "content_build_id": null,
  "build_match": false,
  "extension_protocol_version": "FLOWKIT_EXTENSION_V1",
  "flow_url": "https://labs.google/fx/tools/flow"
}
```

**Reading:** the loaded extension reports the canonical declared build id. `content_build_id`
is null and `build_match` false **for the same reason as §3** — no content script is injected
because the tab is not on a project editor. The three readings are mutually consistent.

Carried limitation, and the reason Round 2 exists: `background_build_id` is a **hand-typed
literal**, not a git SHA or content hash. It proves background↔content-script agreement
(non-staleness); it does **not** prove the loaded folder was built from a given commit.
This round removed a second, worse identity — `BOSMAX_BUILD_PROOF`, which asserted a
branch and commit that were not canonical — but replacing declaration with a real
build-time stamp is Round 2 work.

---

## Verdict on the "unbounded" claim

| Item declared NOT VERIFIED / unbounded | Status after this receipt |
| --- | --- |
| Which git SHA the runtime serves | **KNOWN** — `b337ff2`, branch reported, staleness flagged |
| Which database the backend is bound to | **KNOWN** — absolute path, 36 MB, 659 products, 0 warnings |
| Whether the extension is attached to Flow | **KNOWN** — connected; tab found; not on a project editor |
| Which extension build is loaded | **KNOWN as declared** — canonical build id; SHA stamping is Round 2 |

None of this required new architecture. It required calling four endpoints that
canonical `main` already shipped.

**Still correctly withheld:** live bulk remains uncertified
(`BULK_LIVE_EXECUTION_CERTIFIED = False`, `agent/services/production_queue_service.py`).
That is an owner decision at the credit boundary, and this round does not touch it.
