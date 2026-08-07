# BOSMAX — Greenfield Build Projects (additive V4 lanes)

**Purpose:** self-contained build briefs so **any** implementation-capable AI agent
(Codex, Claude Code, Cursor, Grok, DeepSeek, Antigravity per its UAT role, …) can
pick up and build a **new operator lane** WITHOUT breaking the sealed, live-proven
generation system.

These briefs are **subordinate** to the repo contract. On any conflict, `AGENTS.md`,
`.ai/status/CURRENT_STATE.md`, and `.ai/contracts/*` win.

---

## The golden rule (read this before anything)

Each project is a **new operator lane/page in the V4 workflow shell**.

> **Separate UI, SHARED engine.**
> A new lane UI = ✅. A new generation engine = ❌.
> Every lane calls the SAME one-door
> (`POST /api/flow/generate` → `make_video.start_generate`) + the SAME reference
> contract, run-ledger, retrieval, and product-truth compiler. **Never fork or clone
> the engine** — that is exactly the "duplicate automation module files" debt this repo
> explicitly rejects (see Origin below).

Because lanes are **additive**, existing lanes' code is untouched → they **cannot
break**. Safety is by construction, backed by the validation gates.

---

## Trigger keywords (how the owner starts a build)

The owner pastes a **trigger** to any implementation-capable agent. The trigger names
the brief + read-order; the agent reads it and starts. (This mirrors how `.ai/handovers/*`
are handed to agents — the entry point is handed, not auto-discovered.)

| Project | Status | Trigger keyword | Brief |
|---|---|---|---|
| **Faceless Video** | ✅ READY TO BUILD — rides the hardened I2V/F2V one-door | `BUILD: FACELESS VIDEO MODULE` | [`FACELESS_VIDEO_BUILD_BRIEF.md`](FACELESS_VIDEO_BUILD_BRIEF.md) |
| **Montage** *(rebrand of the owner's "Infinity" / SESAAT "FLOWNITY")* | ⛔ BLOCKED — needs Laluan-B hardening rounds first | `BUILD: MONTAGE MODULE` | [`MONTAGE_BUILD_BRIEF.md`](MONTAGE_BUILD_BRIEF.md) |

The full trigger caption sits at the top of each brief (`## 0. TRIGGER`).

**Why "Montage" and not "Infinity":** the repo already has a real *infinite-length*
mechanism — the sealed **native-extend** path (ADR-009). Naming a **different**,
discrete-scene module "Infinity" would collide with that in every agent's head.
"Montage" = discrete scenes stitched into one video, which is exactly what it is.
The name is a one-line swap if the owner prefers otherwise.

---

## Mandatory read-order for any agent

1. `AGENTS.md` — repo contract (top authority)
2. `.ai/status/CURRENT_STATE.md` — the sealed generation system + ADR-007 (API-first)
3. `.ai/ENGINEERING_LOCKDOWN.md` — surgical/additive rules
4. `.ai/handovers/HANDOVER-2026-08-07-v4-rollout-and-creative-config.md` — the V4 shell pattern to replicate
5. the project's brief in this folder
6. the cited source files

---

## Origin

Derived from the **verified SESAAT-vs-BOSMAX field-intelligence review (2026-08-07)**.
SESAAT is a rival Google Flow automation Chrome extension. Verdict: **research source,
NOT a codebase to merge.** Both modules below are BOSMAX-native equivalents rebuilt on
canonical, API-first primitives:

- **Faceless Video** ≈ SESAAT's **GOYANG** (single-clip, image→video, batch).
- **Montage** ≈ SESAAT's **FLOWNITY** (discrete N-scene → concat into one video).

**Never import** from SESAAT: DOM-clicking / `chrome.debugger` CDP / synthetic paste /
drag-drop upload (dead per ADR-007), the `promptVideo1..N` / `videoScript1..N` flat
schema, prompt tags (`##IMAGE-SET1##`), `URL.createObjectURL` Blob hacks, hardcoded 8s,
or skip-scene-after-retry. BOSMAX already has stronger equivalents (real media/operation
IDs, USER-SETTINGS-ARE-LAW, fail-closed contracts).
