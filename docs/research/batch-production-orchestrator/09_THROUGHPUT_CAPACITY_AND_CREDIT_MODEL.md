# Throughput capacity and credit model

## Theoretical video throughput (one lane, production queue defaults)

Assumptions from code: 1 job at a time; interval uniform 45–120s; cooldown 300s every 5 jobs.

- Mean gap ≈ 82.5s → ~43 jobs/hour idealized → ~1032/day **if** 24h continuous with zero failures.
- **Reality factors:** job runtime (minutes), `VIDEO_JOB_IN_FLIGHT`, Google rate limits (CURRENT_STATE item 2), operator sleep — **BLOCKED_BY_EXTERNAL_RUNTIME**.

**Claim:** 200 videos/day on **one verified lane** is **NOT_VERIFIED** at runtime; code does not forbid 24h run but provider/credit/operator constraints dominate.

## Image throughput

- Up to 3 parallel IMG workers in bulk service — upper bound **code-configured** only.
- 200 images/day ≈ 8.3/hour — plausible in code if jobs complete quickly — **NOT_VERIFIED** live.

## Credit governance

- `confirm_live_credit_burn` / `confirm_credit_burn` on bulk and production live starts — **VERIFIED_CODE**.
- `daily_credit_limit` on legacy batch table — **SCHEMA_ONLY** for modern WGP path.
