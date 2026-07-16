# BOSMAX RPA Click Operator — G0 Governance Gate

## Status

`G0_LEDGER_CLASSIFIED — AMENDMENTS APPLIED` (was `G0_READY_FOR_OWNER_REVIEW`).

**The owner has classified the Decision Ledger (§12) and the accepted amendments have been applied**
to `docs/bosmax-rpa-click-operator-workflow-mvp-spec.md` and
`docs/claude-fable-5-full-delivery-feasibility-contract.md` (see the "G0 Amendments (Binding)"
section at the end of each). Classification summary is recorded in §12 below.

This document is **governance only**. It authorizes nothing by itself.

**ROUND A REMAINS BLOCKED.** Applying the amendments cleared the *documentary* blockers (B1-B5), but
Round A cannot start while the **unresolved owner-only fields** stand — they cannot be invented by an
agent:

- `OWNER_DECISION_REQUIRED: BOSMAX auditor human name`
- `OWNER_DECISION_REQUIRED: Round A PR reviewer`
- `OWNER_DECISION_REQUIRED: rollback owner`
- `OWNER_DECISION_REQUIRED: safe non-production product + isolated DB for Round B`

**Rounds B-F remain BLOCKED** additionally on B6-B7 (environmental — no wording can fix them).

## Source Documents

| Document | Role |
|---|---|
| `docs/bosmax-rpa-click-operator-workflow-mvp-spec.md` | RPA workflow + MVP spec (rounds, selectors, acceptance) |
| `docs/claude-fable-5-full-delivery-feasibility-contract.md` | Feasibility / counter-review / capability interview contract |
| `AGENTS.md`, `.ai/contracts/*`, `.ai/decisions/ADR-007-*` | Repo-wide agent law. **Overrides both documents above on conflict.** |
| This document (`G0`) | The gate that converts counter-review findings into an owner-approvable decision |

**Precedence:** `AGENTS.md` > `.ai/contracts/*` > this G0 gate > RPA spec > feasibility contract.
Where the RPA spec or feasibility contract conflicts with `AGENTS.md` / ADR-007, `AGENTS.md` wins
and the conflict must be recorded, not silently resolved.

---

## 1. G0 Purpose

G0 exists because a counter-review of the RPA spec + feasibility contract produced findings that
make the workstream unsafe to start as documented. G0 converts those findings into a single
owner-approvable gate that answers exactly three questions:

1. **May Round A proceed?**
2. **Under what delivery authority?**
3. **With what proof?**

G0 is not an implementation plan. It contains no code, no selectors to add, and no Playwright
design. It is the precondition for authoring such a plan.

**G0 is satisfied when** the owner has classified every row of §12 and every blocker in §13 is
either cleared or explicitly waived in writing.

---

## 2. Owner Intent Lock

Carried forward verbatim in substance from `spec:25-31`. **Not open for amendment by any agent.**

- This project is **not** a new generation engine.
- Existing BOSMAX image/video generation modules are **already complete and API-backed**.
- **Playwright is only a UI-click RPA operator.** It operates the existing dashboard UI like a
  disciplined human operator: open page → follow visible section order → select existing
  controls → click existing buttons → wait for existing states → capture evidence.
- Playwright **must not replace, bypass, or rewrite** any existing generation module.
- Workspace Jobs, Results, and Library are **evidence surfaces after RPA actions**. They are
  **not** the primary MVP.
- The correct first MVP is **replacing repetitive preparation clicks while stopping before live
  generation** — not monitoring.

---

## 3. Protected Systems / Non-Goals

### Protected systems (do not touch unless separately authorized)

- API-first generation path (ADR-007).
- Google Flow transport.
- Existing video/image modules.
- Retrieval and artifact library.
- Frozen DOM lanes (per ADR-007 these are **delete-only, never repaired**).
- Existing Copy Set review and approval gates.
- Existing Hybrid readiness gates.
- Hybrid fallback confirmation behavior.
- Production Queue credit confirmation behavior.

### Non-goals

Do **not**:

- Rebuild image/video generation modules or replace API-backed functions.
- Call backend generation APIs directly from the RPA.
- Add new Google Flow DOM-driving logic.
- Redesign the production pipeline or rewrite database architecture.
- Bypass existing credit confirmations.
- Bypass existing Copy Set review/approval gates.
- Auto-approve AI-generated copy.
- Trigger live generation without explicit owner authorization.
- Turn this into a broad autonomous platform before the bounded RPA workflow is proven.

---

## 4. Runtime Target Origin

**DECISION (pinned by this gate):**

> **The canonical RPA target origin is `http://127.0.0.1:8100` — the built runtime.**

- `:8100` serves the built dashboard bundle from `dashboard/dist` and is the runtime the owner
  actually validates against.
- **`http://127.0.0.1:5173` (Vite dev) is NOT an accepted target or proof surface** unless it is
  explicitly launched for a specific task **and** the report names it and validates against it
  explicitly.

**Why this must be pinned:** the RPA spec's Evidence Baseline (`spec:73`) records the dashboard at
`:5173`, but `:5173` is a dev server that is not normally running, while `:8100` serves the built
bundle. Verified at G0 authoring time: `:5173` → not running; `:8100/` → HTTP 200. Round A's entire
deliverable is rendered selectors; proving them on one origin while the operator drives the other is
exactly the `CI/runtime mismatch` risk the feasibility contract itself lists.

**Sandbox exception (owner-authorized, Rounds B-D only).** An **isolated sandbox**
runtime may be validated on **`http://127.0.0.1:8123`** (`FLOW_AGENT_DIR=<sandbox>`,
`API_PORT=8123`, `WS_PORT=8124`) for Round B fixture work. This exception is narrow:

- **`:8100` remains the canonical origin** for all merged-code and production-like
  validation. A sandbox run may never be presented as canonical proof.
- The sandbox origin is only valid for **isolated fixture runs against a synthetic,
  non-production product** in a sandbox DB. It must never touch the live DB.
- A sandbox report must state the origin, the resolved `DB_PATH` (proving it is NOT
  the repo-root `flow_agent.db`), plus `git_head` and `source_stale_since_start`.
- `FLOW_AGENT_DIR` relocates **runtime storage only** (DB, `.local-agent`, outputs,
  product images). **Served code and built assets always resolve from the source
  root** — that boundary is what makes the sandbox's git/staleness/SPA proofs real
  rather than vacuous.
- **Known gap:** `FLOW_AGENT_DIR` does **not** isolate the avatar/scene bridge CSV
  (it is source-relative). Round B must not write the avatar registry.
- **Known gap:** FastMoss reference rows are read from a repo pack file and appear
  read-only in a sandbox. Round B must **never select a `fastmoss-ref:` product**.

**Mandatory consequences:**

1. Any report that claims a rendered selector/state proof **must name the origin** and the SHA the
   bundle was built from.
2. Because `:8100` serves a **built** bundle, a source-only change is invisible there until
   `npm run build` is re-run. Any Round A proof must be taken against a bundle **rebuilt from the
   commit under review**.
3. `:8100` has a documented history of serving a **stale worktree**. Every runtime proof must
   include `git_head` and `source_stale_since_start=false` from the live version-proof endpoint.

---

## 5. Phase Authority Model

Four delivery modes. Only the owner may raise a round's mode.

| Mode | Agent may | Agent may not |
|---|---|---|
| `PR-READY` | Prepare a patch/branch locally; report the diff | Push, PR, merge, run the thing live |
| `REMOTE PR` | Commit, push, open PR, report proof | **Merge**, restart runtime, run live |
| `FULL DELIVERY` | Commit, push, PR, **review**, merge, post-merge validation | — |
| `OWNER-ONLY` | Prepare/report only | Execute the action at all |

**FULL DELIVERY includes an independent `review` step.** Any restatement of FULL DELIVERY that omits
`review` is void. **No agent may merge its own PR.** The reviewer must be a named human.

**G0 ruling:** `FULL DELIVERY` is **refused for every round** of this workstream at this time. See
§14 for the conditions that would have to be true first.

---

## 6. Phase Breakdown

**Naming:** this workstream uses **Round A–F**, matching the RPA spec's Implementation Rounds table.
The feasibility contract's label "Phase A-E" is **retired** — it omits Round F and it collides with
the already-closed *Creative Registry Modernization Phase A–E*, a different workstream. In this
document **"Phase A" ≡ "Round A"**.

| Round | Scope | Authority (G0 ruling) | Status |
|---|---|---|---|
| **A** | Selector/state patch only — no business logic | `REMOTE PR` | **BLOCKED** — see §13 |
| **B** | Hybrid Production-Prep Click Operator, Steps 1–4 | `REMOTE PR` | **BLOCKED** — no safe test data (§8) |
| **C** | Evidence attachment / reporting | `REMOTE PR` | Not authorized |
| **D** | Production Queue dry-run RPA | `PR-READY` → owner executes | Not authorized |
| **E** | One serial live Step 5 test | `OWNER-ONLY`, per-run written authorization | Not authorized |
| **F** | Prep RPA + bounded daily repeats | `OWNER-ONLY` / not planned | Not authorized |

### Bundling rules (binding)

Each round requires a **separate** owner decision. The following must **never** be bundled:

| Bundle | Rule | Reason |
|---|---|---|
| **D + E** | **NEVER** | Dry-run and live credit burn under one authorization. "Dry-run ≠ live run." |
| **A + B** | **NEVER** | Round A's job is to *discover* that the selector model is wrong. Bundling lets the agent that finds the gaps paper over them inside a click mission. **Note:** `spec:296-302` currently recommends authorizing A and B together as one package — that recommendation is **superseded by this gate** (see M1/M4). |
| **E + F** | **NEVER** | One authorized live test must not graduate into unattended repetition. |
| **B + C** | Avoid | A failed run must not self-report its own evidence. |
| **A + anything** | **NEVER** | A is the only "no business logic" round; bundling dissolves that constraint. |

**Rounds B–F are additionally constrained:** the RPA spec constrains only Round A from modifying
dashboard source. Until amended, **no round other than A may modify dashboard source without a new
owner decision.**

---

## 7. Phase A Entry Criteria

Round A may not begin until **all** of the following are true.

| # | Entry criterion |
|---|---|
| A1 | Owner has classified the §12 Decision Ledger, and M1–M9 are `Accept`ed and applied to the source docs. |
| A2 | `spec:5` no longer reads as an approval to implement, and `spec:296-302` ("Authorize Round A and Round B") is retracted or parked. |
| A3 | The selector model is corrected **on paper first**: Step 1 control selectors added; the fallback-confirmation gate added; `action-generate-video` removed or made conditional; the per-step-error contradiction resolved (see §13 B1–B3). |
| A4 | Round A's acceptance proof includes the repo's real build gate, not DOM inspection alone (§10). |
| A5 | Target origin `:8100` is acknowledged in the mission prompt (§4). |
| A6 | Delivery authority for Round A is stated as `REMOTE PR` — the agent will not merge. |
| A7 | A named human reviewer is assigned for the Round A PR. |
| A8 | The Round A mission prompt explicitly binds the agent to `AGENTS.md` + ADR-007 + `.ai/contracts/*`. |

**Round A scope boundary (for the future mission, not authorized here):** Round A adds only stable
selectors and rendered state to the existing Hybrid workflow surface. It changes **no** generation
logic, **no** API flow, **no** approval logic, and **no** credit safeguard. Any requirement that
cannot be met without changing those four categories is a **STOP-and-report**, not an improvisation.

---

## 8. Copy Set / AI Assistant Gate

**Rule (binding):** Copy Set readiness and approval are **mandatory prerequisites** wherever the
Hybrid production path requires them. The RPA **may select and verify** an approved Copy Set. The
RPA **must stop** if no approved Copy Set exists. The RPA **must not** generate, approve, or
auto-approve Copy Sets, and **must not** use fallback copy as the baseline production path.

### Verified integrity findings (these constrain what the rule can actually enforce)

| Finding | Evidence | Consequence |
|---|---|---|
| **Copy Set approval has no actor identity.** The client sends a hardcoded `approved_by: "operator"`; the backend defaults to the literal `"operator"`. | `dashboard/src/components/workspace/CopySelectionPanel.tsx:153`; `agent/services/copy_set_service.py:469,476` | Every approval in the DB reads `"operator"`. An RPA approval would be **indistinguishable from a human approval** in the record. The rule "RPA must not approve" is **unenforceable server-side and forensically unauditable**. |
| **The approval phrase is a client-side constant** readable from the repo. | `dashboard/src/api/copySets.ts:197` | It is a typed-confirmation pattern, **not** an identity gate. |
| **No safe test data exists.** The live DB holds **11 `COPY_APPROVED` Copy Sets, all belonging to ONE product** — a real brand's real production product — all `approved_by='operator'`. | live `flow_agent.db`, read-only query at G0 authoring time | `spec:205` requires "one designated **non-production** test product with immutable ID". **It does not exist.** The only viable Round B target today is **real production data in the single live DB bound to `:8100`**. |
| **Selection determinism undefined.** 11 approved sets exist for that one product. | as above | The spec speaks of "the approved Copy Set" as if singular. Which one the RPA picks is **undefined**. |
| **Approval state is a stale, un-polled client cache.** | counter-review, `copySets` client | Mid-run revocation or approval-drop is **invisible** to the RPA. |
| **Dedupe is exact-match.** | counter-review | Near-zero protection for the AI candidate generation Round F contemplates, while emitting a false "deduped" safety signal. |

### Gate rulings

1. **Round B must be read-only with respect to approval.** It may read and verify; it may never write approval state.
2. **A designated non-production test product + an isolated test DB are a hard prerequisite for Round B.** Not a nicety.
3. **A server-side actor/provenance check on Copy Set approval is a hard prerequisite for Round F** (AI candidate generation).
4. **Deterministic selection must be defined** before Round B: which approved Copy Set, by what rule.
5. **The fallback path is a trap.** When the fallback-confirmation gate opens it disables the Step 4 button, and "Continue with fallback" becomes the only enabled control inside the Step 4 container. A naive RPA clicking "the enabled control in Step 4" would **ship fallback copy**. Round B acceptance **must** require positive evidence that the fallback modal did not fire.

---

## 9. Runtime / Access Gate

### Verified environment facts (at G0 authoring time)

| Fact | Status |
|---|---|
| CI | **ABSENT** — no `.github/workflows` directory |
| Branch protection on `main` | **ABSENT** — GitHub API returns `404 Branch not protected` |
| Repo write / merge capability | **Already held** by the agent token — never withheld |
| Deployed environment for post-merge validation | **Does not exist** — `:8100` is a laptop-local uvicorn serving the working tree |
| Isolated test DB / designated test product | **Does not exist** — single live `flow_agent.db` |
| Playwright | **Present** — `playwright ^1.60.0`, with an existing persistent-context script precedent |
| Canonical origin | `:8100` built runtime (pinned, §4) |
| Google Flow authenticated / credit-bearing session | **Must NOT be granted for Rounds A–D** |
| Named human reviewer | **Undefined** |
| Rollback owner / revert authority | **Undefined** |

### Gate rulings

1. **"CI results" may never be cited as proof** while no CI exists. A proof line that cannot be produced must not appear in any report.
2. **"Merge rights" is not a meaningful control here** — it was never withheld. Restraint is therefore *procedural*, not technical: an agent operating under `REMOTE PR` must not merge even though it technically can. This is the single weakest control in the workstream and the owner should treat it as such.
3. **"Post-merge validation" must be defined concretely or not claimed.** Minimum definition: runtime restarted from the canonical worktree; live `git_head` equals the merge SHA; `source_stale_since_start=false`; the affected surface re-rendered and observed.
4. **No credit-bearing session for Rounds A–D.**

---

## 10. Mandatory Proof Matrix

| Round | Mandatory proof (all required) |
|---|---|
| **A** Selector/state | 1. Origin named = `:8100`, bundle **rebuilt from the commit under review**. 2. **Falsifiable rendered locator audit**: each selector asserted in **≥2 states** (e.g. `NOT_READY` *and* `READY`) — an audit that only ever runs in the one observed state (Step 4 disabled, Step 5 absent, Queue empty) passes vacuously and is **not accepted**. 3. Step 1 controls expose a **readable current value**, not just enablement. 4. `scripts/verify-gate.ps1` passes (real `npm run build` = `tsc -b && vite build`, vitest, backend pytest smoke, mandor-check). **`tsc --noEmit` is NOT sufficient** — it missed the PR #265 build regression. 5. **Non-HYBRID regression statement**: OperatorPage also serves T2V / I2V / F2V / IMG; name which were re-rendered and confirmed unbroken. 6. Diff proof that none of generation logic / API flow / approval logic / credit safeguard changed. |
| **B** Steps 1–4 | Product selected **by immutable ID**; approved Copy Set verified **by ID + status**; **positive evidence the fallback-confirmation modal did not fire**; package + final-prompt IDs captured; terminal states reached; **generation-request-count delta = 0** (proving it stopped before Step 5). |
| **C** Evidence | Workspace Jobs / Results correlated to Round B's captured IDs; report format pre-cleared against `.ai/contracts/REPORT_REJECTION_RULES.md` (a `REQUEST_ID=N/A` report is auto-rejected). |
| **D** Queue dry-run | One known run/item reaches a terminal **dry-run** state, with the flag that distinguishes dry-run from live capture in the evidence. Dry-run evidence may never be presented as live evidence. |
| **E** Live Step 5 | 1. **Per-run written owner authorization**, quoted in the report — never a standing grant. 2. **Pre-run baseline** (credit balance, job/request/artifact counts). 3. **Post-run delta** vs that baseline proving **exactly one** submission. 4. `REQUEST_ID` + `COMMIT_SHA` + telemetry-backed stage list. 5. **Duplicate-submission detection method defined in advance**. 6. Reconciliation with `AGENTS.md`'s live-UAT rule (one-shot, post-preflight) — state which rule governs. |
| **Merge / post-merge** | Named human reviewer approved the PR; merge SHA; runtime restarted; live `git_head == merge SHA`; `source_stale_since_start=false`; affected surface re-observed. |

**Screenshots are supporting evidence only, never sole proof** (`AGENTS.md`: no manual
screenshot-only proof). **Negative claims require positive evidence** — "the RPA stopped before
Step 5" must be proven by a zero request-count delta, not asserted.

---

## 11. Live Action / Credit Burn Rules

1. **No live provider/credit action without explicit, written, per-run owner authorization.** This applies to Google Flow generation, image generation, and any AI/text-assist lane that spends tokens.
2. **Rounds A–D must spend zero credits.** Any credit spend during A–D is an incident, not a variance.
3. **Round E is `OWNER-ONLY`**: authorization is per run, never standing, never inferable from a prior approval.
4. **The agent may never self-authorize a live action**, and may never treat a prior owner approval of a *different* action as covering a live one.
5. **Existing credit confirmations must not be bypassed or auto-clicked.** The Production Queue credit confirmation is a protected system (§3).
6. **`AGENTS.md` live-UAT law governs** on conflict with this workstream's docs.
7. **Any unexpected credit or state drift halts the workstream** and is reported before any further round.

---

## 12. Accept / Reject / Park Decision Ledger

Per the feasibility contract's Counter-Review Audit Rule: a counter-review does not change the plan.
The BOSMAX auditor must classify each row. **Only `Accept`ed rows amend the source documents.**

**Recording requirement (M10 — now accepted and applied):** each classification is recorded with a
one-line reason; a `Reject` must state which disqualifier applies (conflicts with owner intent |
lacks evidence). An unrecorded `Reject` is void. A `Reject` of a BLOCKER-derived row requires owner
countersignature.

### CLASSIFICATION — RECORDED

| Group | Classification | Applied to |
|---|---|---|
| **M1-M15** (all fifteen) | **ACCEPT** | SPEC + CONTRACT "G0 Amendments (Binding)" sections |
| **O1** state model (`AWAITING_HUMAN_CONFIRMATION`, non-monotonic states) | **ACCEPT** | SPEC §F |
| **O2** evidence redaction/retention | **ACCEPT** | CONTRACT §7 |
| **O3** Round C report format pre-cleared vs REPORT_REJECTION_RULES | **ACCEPT** | SPEC §F |
| **O4** dedupe key beyond exact-match | **PARK — until Round F** | SPEC §G, CONTRACT §8 — **not** a Round A prerequisite; **must** be resolved before Round F |
| **O5** expiry / re-review trigger; stale Evidence Baseline | **ACCEPT** | SPEC §F, CONTRACT §7 |
| **O6** answer key is readable by the interviewee | **ACCEPT** | CONTRACT §7 |
| **D1-D6** | **ACCEPT as "keep as-is"** — retained unchanged | SPEC §H, CONTRACT §9 |

**B1 decision (owner): option (a) — ACCEPTED.** Tag the **single existing global notice** and
**downgrade the per-step error requirement to a GLOBAL STOP**. Any error notice is a global STOP; it
must not be attributed to a step and must not be treated as recoverable.
**State-plumbing is NOT authorized** — Round A must not split, re-scope, or add step attribution to
the notice. Per-step attribution would be a **new owner decision**. Recorded in SPEC §B.4.

*The ballot tables below are retained as the historical record of what was put to the owner.*

### Must-update

| # | Recommendation | Accept / Reject / Park |
|---|---|---|
| M1 | Change `spec:5` to "Planning baseline — **NOT approved for implementation**"; retract/park `spec:296-302` ("Authorize Round A and Round B") | ☐ A ☐ R ☐ P |
| M2 | Refuse FULL DELIVERY for all rounds; adopt the §6 authority table | ☐ A ☐ R ☐ P |
| M3 | Pin the RPA target origin to `:8100` built runtime, rebuilt from the merge SHA (§4) | ☐ A ☐ R ☐ P |
| M4 | Add the bundling rule: separate owner decision per round; **D+E, A+B, E+F never bundle** | ☐ A ☐ R ☐ P |
| M5 | Fix the Round A selector model: add Step 1 control selectors with readable values; add the fallback-confirmation gate; remove/condition `action-generate-video`; resolve the per-step-error contradiction | ☐ A ☐ R ☐ P |
| M6 | Add the Round A build gate (`verify-gate.ps1` + ownership + non-HYBRID regression statement); DOM inspection alone is not acceptance | ☐ A ☐ R ☐ P |
| M7 | Record that Copy Set approval is client-attributed with no identity → "RPA must not approve" is unenforceable; Round B read-only w.r.t. approval; server-side actor check is a Round F prerequisite | ☐ A ☐ R ☐ P |
| M8 | Safe test data is a hard prerequisite for Round B: designated non-production product + isolated DB; define deterministic Copy Set selection | ☐ A ☐ R ☐ P |
| M9 | Bind both source docs to `AGENTS.md` / ADR-007 / `.ai/contracts`; add them to the `AGENTS.md` Read First list; state `AGENTS.md` overrides | ☐ A ☐ R ☐ P |
| M10 | Name the BOSMAX auditor as a specific human; no AI may Accept/Reject/Park; record reasons under `.ai/audits/`; unrecorded Reject of a BLOCKER is void | ☐ A ☐ R ☐ P |
| M11 | Restore `review` to every FULL DELIVERY enumeration; add Red Flag "proposes merging its own PR"; add Auditor Rule "names an independent reviewer and does not self-merge" | ☐ A ☐ R ☐ P |
| M12 | Add a rollback clause: named revert owner; revert on failed post-merge validation; define post-merge validation concretely | ☐ A ☐ R ☐ P |
| M13 | Make the counter-review pass mandatory (not "if the owner wants"); no counter-review artifact ⇒ the feasibility answer is void | ☐ A ☐ R ☐ P |
| M14 | Live Step 5 proof: pre-run baseline + post-run delta + `REQUEST_ID`/`COMMIT_SHA`; per-run authorization; predefined duplicate-submission method; zero-delta proof of "stopped before Step 5" | ☐ A ☐ R ☐ P |
| M15 | Rename to **Round A–F** everywhere; retire "Phase A-E"; reinstate Round F in the contract | ☐ A ☐ R ☐ P |

### Optional-update

| # | Recommendation | Accept / Reject / Park |
|---|---|---|
| O1 | Add an "awaiting human confirmation" state value; document that Step 3 `COMPLETED` can revert to `NOT_READY` | ☐ A ☐ R ☐ P |
| O2 | Evidence redaction/retention policy (the runner holds live authenticated state) | ☐ A ☐ R ☐ P |
| O3 | Pre-clear Round C's report format against `REPORT_REJECTION_RULES.md` | ☐ A ☐ R ☐ P |
| O4 | Strengthen the dedupe key beyond exact-match before Round F | ☐ A ☐ R ☐ P |
| O5 | Contract expiry / re-review trigger; refresh the stale Evidence Baseline (`spec:63-80`) | ☐ A ☐ R ☐ P |
| O6 | Note that the evaluation answer key is checked into the repo the interviewed agent can read — it grades prose, not behavior | ☐ A ☐ R ☐ P |

### Do-not-update (keep as written)

| # | Item | Accept / Reject / Park |
|---|---|---|
| D1 | Owner Intent Lock, Non-Goals, Protected Areas | ☐ A ☐ R ☐ P |
| D2 | "Stop before Step 5" MVP boundary | ☐ A ☐ R ☐ P |
| D3 | Human-only Copy Set approval; no auto-approval in the first MVP | ☐ A ☐ R ☐ P |
| D4 | The A→F round decomposition shape | ☐ A ☐ R ☐ P |
| D5 | The Accept/Reject/Park mechanism itself (only add recording, M10) | ☐ A ☐ R ☐ P |
| D6 | Do not reduce this workstream to Workspace Jobs monitoring — prep-click is the correct MVP | ☐ A ☐ R ☐ P |

---

## 13. Risk Register & Blockers Before Round A

### Blockers — Round A cannot start while these stand

> **STATUS UPDATE (ledger applied).** The **documentary** blockers **B1-B5 are now RESOLVED** by the
> accepted amendments (see the "G0 Amendments (Binding)" section in each source doc). **Round A is
> still BLOCKED** — on the four unresolved `OWNER_DECISION_REQUIRED` fields (§Status), which no agent
> may invent. **B6-B7 remain open** and additionally block Rounds B-F.
>
> - **B1 → RESOLVED**: owner chose **option (a)** — tag the single global notice; per-step error
>   downgraded to a **global STOP**; **state-plumbing NOT authorized**.
> - **B2 → RESOLVED**: Step 1 control selectors (with readable `data-value`) added to Round A scope (M5).
> - **B3 → RESOLVED**: `action-generate-video` made conditional, not unconditional (M5).
> - **B4 → RESOLVED**: both source docs now bind to `AGENTS.md` / ADR-007 / `.ai/contracts` and state
>   that `AGENTS.md` overrides (M9). *Residual:* adding the two docs to AGENTS.md's own Read First list
>   was **not** performed — `AGENTS.md` is outside this amendment's authorized scope and is a
>   repo-wide contract. → `OWNER_DECISION_REQUIRED: authorize AGENTS.md Read First insertion`.
> - **B5 → RESOLVED**: `spec` "Next Owner Decision" retracted; A+B bundling forbidden (M1 + M4).

| # | Blocker | Evidence | Clears when |
|---|---|---|---|
| **B1** | **Per-step error/completion state does not exist.** OperatorPage has ONE global `notice` object shared by Steps 3/4/5, with no step attribution and no freshness marker. The spec requires a visible error/completion region **per step**, while also forbidding business-logic change in Round A. Both cannot be satisfied as written. | `dashboard/src/pages/OperatorPage.tsx:731` (single `notice`), 23 `setNotice` call sites | Owner picks: (a) tag the single global notice and downgrade per-step attribution to a global STOP (**default**), or (b) authorize a state-plumbing exception with a regression gate. |
| **B2** | **Zero Step 1 setting selectors.** Round B is required to set EXTEND + authorized duration, but the selector list contains no control-level selectors. Missing duration keeps Step 3 disabled, so the RPA would face a permanently disabled Step 3 with no reachable control — discovered only in Round B, after Round A closed. | RPA spec selector list vs `OperatorPage.tsx` state (`generationMode`, `requestedTotalDuration`, `extendTotalRequired` gating Step 3) | Selector list amended to include Step 1 controls with readable current values (M5). |
| **B3** | **`action-generate-video` inside `workflow-step-5` cannot exist** as specified — Step 5 renders no clickable control when EXTEND/duration prerequisites are unmet. | `spec:77` Evidence Baseline | Selector removed or made explicitly conditional (M5). |
| **B4** | **The two governance systems are mutually invisible.** Neither source doc binds the agent to `AGENTS.md` / ADR-007 / `.ai/contracts`, and neither doc appears in the `AGENTS.md` Read First list — while `AGENTS.md`'s Conflict Rule says it overrides. | `AGENTS.md`, both source docs | M9 accepted and applied. |
| **B5** | **The spec pre-authorizes the forbidden bundle.** `spec:296-302` recommends authorizing Round A **and** Round B as one package. | `spec:296-302` | M1 + M4 accepted and applied. |

### Blockers — Rounds B–F (environmental; no wording can fix these)

| # | Blocker | Clears when |
|---|---|---|
| **B6** | **No safe test product and no isolated DB.** The only product with approved Copy Sets is a real brand's real production product in the single live DB bound to `:8100`. | A designated non-production test product + isolated test DB exist (M8). |
| **B7** | **Copy Set approval has no server-side actor identity** — every approval reads `"operator"`, so an RPA approval is indistinguishable from a human one. | Round B constrained read-only w.r.t. approval (M7); server-side actor check before Round F. |

### Risk register

| Risk | Severity | Mitigation in this gate |
|---|---|---|
| Selector brittleness / labels mutating between runs | MED | Immutable-ID-keyed selectors; `data-value` readback; ≥2-state audit (§10) |
| Round A silently regresses T2V/I2V/F2V/IMG (shared component) | **HIGH** | Real build gate + explicit non-HYBRID regression statement (§10) |
| RPA ships fallback copy unnoticed | **HIGH** | Positive proof the fallback modal did not fire (§8.5, §10 Round B) |
| Step 5 credit burn / duplicate submission | **HIGH** | `OWNER-ONLY`, per-run authorization, baseline+delta (§11, §10 Round E) |
| Dry-run mistaken for live | MED | Dry-run flag captured; D+E never bundled (§6) |
| Merge before proof / self-merge | **HIGH** | `REMOTE PR` only; named human reviewer; `review` restored (§5, M11) |
| Bad merge with no rollback on unprotected `main` | **HIGH** | Rollback clause required (M12) — **currently undefined** |
| Stale runtime / stale dist masking reality | MED | Origin pinned + `git_head` + `source_stale_since_start` in every proof (§4) |
| Approval revoked mid-run (stale client cache) | MED | Round B read-only w.r.t. approval; re-verify before Step 4 (§8) |
| Agent restraint is procedural, not technical | **HIGH** | Acknowledged explicitly (§9.2) — owner accepts this residual risk knowingly |

---

## 14. Conditions Required Before Any FULL DELIVERY Claim

`FULL DELIVERY` is **refused for every round of this workstream today**. The feasibility contract's
own Green Signal states an agent must not claim full delivery unless repo, **CI**, merge, runtime,
and post-merge validation access are available. Verified: **there is no CI and `main` is
unprotected**, so the claim is unavailable by the contract's own rule, and the contract's own
Auditor Rule concludes that the maximum acceptable next step is **phased delivery**.

All of the following must be true before FULL DELIVERY may even be *discussed*:

1. **CI exists** and runs the real build + tests on PRs.
2. **`main` is protected**, with required status checks.
3. **Required review by a named human** is enforced — and the agent cannot merge its own PR.
4. **`review` is present** in every definition of FULL DELIVERY.
5. **A real post-merge validation target exists** and post-merge validation is concretely defined (§9.3).
6. **A rollback owner and revert path are named**, with revert-on-failed-validation.
7. **Safe test data exists** (designated non-production product + isolated DB).
8. **Credit-bearing actions remain excluded** from any FULL DELIVERY grant — live generation stays `OWNER-ONLY` regardless.

Until then: **`REMOTE PR` is the ceiling for Rounds A–C, `PR-READY` for D, `OWNER-ONLY` for E–F.**

---

## 15. Final G0 Verdict

# `G0_READY_FOR_OWNER_REVIEW`

This gate is complete and internally consistent. Both required source documents were available and
read; the runtime origin question is **resolved and pinned** (`:8100`, §4), so neither
`G0_BLOCKED_MISSING_CONTRACT_INPUT` nor `G0_BLOCKED_RUNTIME_ACCESS_UNCLEAR` applies.

**This verdict authorizes nothing.** It states that the gate is ready for the owner to act on.

> **SUPERSEDED — the owner has since acted.** Current state:
> **`G0_LEDGER_CLASSIFIED — AMENDMENTS APPLIED`** (see the Status block at the top).
> M1-M15 Accepted; O1/O2/O3/O5/O6 Accepted; **O4 Parked until Round F**; D1-D6 Accepted as
> "keep as-is"; **B1 resolved as option (a)** — tag the single global notice, downgrade to a global
> STOP, **state-plumbing not authorized**. The accepted amendments are applied to both source
> documents ("G0 Amendments (Binding)" in each).
> **Round A is still BLOCKED** on the four unresolved `OWNER_DECISION_REQUIRED` fields; Rounds B-F
> additionally on B6-B7. The verdict line above is retained as the historical record of the gate as
> first presented.

**Round A remains BLOCKED** pending: owner classification of §12, acceptance and application of
M1–M9, and clearance of blockers B1–B5.
**Rounds B–F remain BLOCKED** additionally on B6–B7, which no document wording can fix.

**Next step:** owner classifies §12 (Accept / Reject / Park), amends the two source documents with
the accepted items, then a Round A implementation prompt may be authored — as `REMOTE PR`, with a
named reviewer, against `:8100`.

---

*G0 authored from the adversarial counter-review of the RPA spec and feasibility contract. All
environment facts in §8 and §9 were verified read-only at authoring time and carry no mutation. This
document contains no implementation instructions.*
