# Bulk Generation — All 4 Lanes Live-Proven (2026-07-23)

Overnight autonomous run. Owner approved credit spend. All live fires driven through
the **UI** (Playwright on the dashboard), never the backend API. Runtime on branch
`fix/round1-runtime-truth-and-build-provenance` @ `eb9898c` (= origin, not stale).

## EXTEND (16s multi-block) — all four lanes produced real 16.000s videos

| Lane | Run | Result | Artifact(s) | Duration | Bound copy? |
|---|---|---|---|---|---|
| **T2V** | prun_e9d9c6a7 | **2/2** | final_vj_b27421258690, final_vj_9513ce18c2c8 | 16.000s | yes, 2 unique |
| **HYBRID** | prun_f6d1f323 | 1/2 (#2 rate-limited) | final_vj_3e5136ee2433 | 16.000s | yes, product+avatar |
| **I2V** | prun_cd563d56 | **2/2** | final_vj_a1f822e3458f, final_vj_7f00704726ab | 16.000s | yes, 2 unique, char+scene |
| **F2V** | prun_dac472ed | 1/2 (#0 rate-limited) | final_vj_ed1a0358d640 | 16.000s | yes, start-frame |

Every EXTEND video: ffprobe **16.000000s**, dialogue = the item's bound approved copy
(SECTION 6), NO landbank/fallback text, real product "Minyak Warisan Tok Cap Burung".
Each fired as its own durable `vj_*` job through /video-jobs (initial → extend →
concat), serial fan-out — never one `count:N` submission.

## SINGLE (8s) — "5 videos at once"

| Lane | Run | Result | Notes |
|---|---|---|---|
| **T2V** | prun_a69685dc | **4/5** (#1 rate-limited) | 5 UNIQUE dialogues, no duplicate |
| **HYBRID** | (earlier) | 2/2 | 2 real 8s MP4s |

T2V qty-5: dry run `checked 5 · ready 5 · blocked 0`, five distinct product-specific
dialogues, four rendered to real 8s videos.

## The ONLY failure mode = Google rate limiter, correctly classified ZERO-CREDIT

Every failure this run carried `RATE_LIMITED: Google anti-abuse` →
`submission_state=NOT_ATTEMPTED, credit_state=NOT_SPENT, retry_safety=SAFE`. The system
proves no provider side effect on a pre-submit 403, so rate-limit failures cost nothing
and are safely re-fireable. **Rate math for production:** each EXTEND item ≈ 3 provider
ops (~12-15 min); Google throttles at ~>10 ops / 2h → ~30 min of 403 silence. So a
5-item EXTEND batch (~15 ops) WILL hit the limiter partway — pace it, or accept that late
items 403 (free) and retry after cooldown. 5 SINGLE videos (~5 ops) are well under the
limit.

## What this proves against the owner's goals

- 5 videos at once — yes (T2V single 4/5, five unique dialogues).
- Single OR extend — both, all lanes.
- T2V / F2V / HYBRID / I2V — all four EXTEND-proven with real 16s videos.
- No duplicate dialogue — enforced by the content_combination UNIQUE ledger; verified
  distinct on every run.
- Extend dialogue follows the storyboard — one global plan split into blocks; each block's
  bound copy reaches the video (ghost-copy fix proven live).
- Avatar usable — HYBRID (avatar+product anchor) and I2V (character+scene) proven.
- Product usable — every video carries the real product truth.

## Firing procedure (for the team)

1. Studio: pick product → mode → select the lane's reference → Quantity → Preview →
   Prepare. Wait for dry run **green** (image lanes upload the reference first — this
   takes ~1-2 min, credit-free).
2. Click **Open fresh Flow project**, wait until the editor is on a `/project/` URL and
   ready (bind-check `bound:true`). Do NOT fire before this — firing into an unbound
   editor stalls.
3. Type `AUTHORIZE_BULK_FANOUT_LIVE_RUN`, click Fire.
4. EXTEND items take ~12-15 min each and show `INITIAL_SUBMITTING` for most of it — that
   is normal mid-render. **Never cancel a running EXTEND.**
