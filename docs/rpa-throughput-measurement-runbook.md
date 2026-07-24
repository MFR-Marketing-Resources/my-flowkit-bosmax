# RPA Throughput Measurement Runbook (Phase 1)

**Goal:** measure the *real* single-account video generation rate on a live batch,
so we know honestly whether **one account can reach 200/day** or whether
multi-account parallelism (Phase 2) is required. No number in the "200/day" plan
should be a guess — this runbook produces the measured one.

> Scope: this is a **measurement**, not a production run. It spends a small,
> bounded number of real credits (one per fired video). The owner performs the
> credit-spending steps (certify + fire); the analysis is read-only and free.

---

## What the code actually does (measured findings)

| Fact | Source |
|---|---|
| Queue fires **serially**, one item at a time | `production_queue_service._live_production_loop` |
| **Single-flight** video lane — one generation at a time | `make_video._VIDEO_LANE_JOB`, `production_run.max_parallel_jobs = 1` |
| Pacing: interval **45–120 s** between fires; cooldown **300 s after every 5 jobs** | `production_run.interval_min/max_seconds`, `cooldown_*` |
| Fire waits for the video to reach terminal before the next | `_fire_and_wait` |
| Bulk live is gated by a flag, default **off** | `BULK_LIVE_EXECUTION_CERTIFIED = False` (`.env` to flip) |
| No multi-account / parallel-worker support | single provider boundary per worker |

**Implication:** the serial queue can physically pace ~one video every few
minutes (≈ hundreds/day *if unthrottled*). The real ceiling is the **provider's
per-account rate limit** — the one number we cannot read from code and must
measure. The single-flight design means one account's limit **is** our ceiling
until Phase 2.

---

## Procedure

### Production reality (owner, 2026-07-24)
- Only **T2V** and **Hybrid** are practical at 200/day. **F2V/I2V are out** — they
  need many pre-built images (F2V: avatar+product; I2V: avatar+product+scene).
- Durations are a **FLEXIBLE MIX** — **8 s, 10 s (Omni Flash), 16 s, 24 s**.
  **Nothing is hardcoded.** Single-shot durations (8 s, 10 s) are fast (~1 op);
  **16 s / 24 s use the EXTEND lane** (~13 min/item observed) — the durations, not
  the mode, are the dominant throughput driver.
- **16 s is used here only as a TIMING SAMPLE** for the slow (EXTEND) lane, per the
  owner. It is *not* a mandatory production duration.

### Throughput-by-lane ceiling (single account, before any rate-limit)
| Lane | ~time/item | 24 h ceiling / account |
|---|---|---|
| 8 s single (T2V / Hybrid) | ~1–3 min | ~300–500 |
| 10 s (Omni Flash, single) | ~1–3 min | ~300–500 |
| **16 s EXTEND (Hybrid)** | **~13 min** | **~110** |
| 24 s EXTEND | ~longer | ~70–90 |

**Consequence:** 200/day feasibility depends on the **duration MIX**. A mix
dominated by 8 s / 10 s singles → reachable on ~1 account; a mix heavy on 16 s /
24 s EXTEND drops the ceiling sharply (16 s alone ~110/day) → 2–3 accounts
(Phase 2). So measure **per-duration timing**, not one fixed duration.

### 1. Prepare the measurement batch (credit-free)
- **Measure per lane.** Start with the owner-chosen **EXTEND timing sample**:
  **MWTCB, Hybrid, 16 s, 9:16** (Hybrid needs a 9:16 product anchor — MWTCB
  auto-anchors; confirm it resolves in the dry run). Then repeat with a
  **single-shot sample** (8 s or 10 s Omni Flash) so the plan covers the real
  8/10/16/24 mix — 16 s alone would only tell us the *slow* lane.
- Queue **~15–20 items per sample** into a production run (`QUANTITY (PREVIEW)`
  caps at 5, so queue in passes — or ask Claude for a credit-free dry-run
  batch-prep helper).
- **Dry run** (no `confirm_live_credit_burn`). Every item must report `ok: true`
  **and** a resolved anchor/media (for Hybrid). Zero credits.

### 2. Certify (owner) — the credit gate
- Set in `.env` at repo root, then restart the agent:
  ```
  BULK_LIVE_EXECUTION_CERTIFIED=1
  ```
  ```bash
  pwsh -NoProfile -File scripts/start-local-agent.ps1 -ForceRestart
  ```
- This is the owner's explicit authorization to spend credits on bulk live.

### 3. Fire the batch live (owner)
- Start the run **live** with the bulk fan-out gate + confirm phrase
  (`LIVE_GATE_BULK_FANOUT`). Let it run to completion (or until throttling is
  clearly visible). Do **not** cancel mid-render — a submitted job keeps costing.

### 4. Read the real rate (free)
```bash
python scripts/rpa_throughput_telemetry.py
```
It reports, from the real run: fired / completed / failed, **throttle hits**
(rate-limit / 403 / quota / captcha), **sustained videos/hour**, the honest
**videos/day** extrapolation, and the median gap between completions.

### 5. Interpret
- `≥ ~230/day (24h)` → **one account is enough** for 200/day. Ship Phase 3
  (resume/telemetry/auto-pace) and you're done.
- `~180–230/day` → **marginal**. Measure longer, or add a second account for
  safety margin.
- `< ~180/day`, or **throttle hits climb over time** → **one account is not
  enough** → Phase 2 (multi-account parallel lanes: lift the single-flight
  `_VIDEO_LANE_JOB` to per-account, run K accounts; K × per-account/day = 200).

---

## Honesty notes
- A 24 h extrapolation assumes the rate **holds unthrottled all day**. If throttle
  hits rise as the batch runs, the true sustained/day is lower — that rising curve
  *is* the signal to add accounts.
- A batch of **< 10 items is inconclusive** (one slow/failed item skews the rate);
  the telemetry says so. The current DB already has a 2-item run
  (`prun_dac472edf6fc471e`, 1 done / 1 failed) — that is a cert attempt, **not** a
  throughput measurement.
- Turning `BULK_LIVE_EXECUTION_CERTIFIED` back off after the measurement re-arms
  the gate.
