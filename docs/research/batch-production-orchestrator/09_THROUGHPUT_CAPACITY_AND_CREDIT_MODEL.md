# Throughput capacity and credit model (repair v1.1 — throughput math corrected)

All numeric scenarios are **assumption-bound** and **NOT_VERIFIED** at runtime (generation, polling, retrieval, provider limits were **not** re-executed in this audit).

Labels: **theoretical** | **code-configured** | **test-supported** | **runtime-proven** | **unknown provider**.

## Variables (symbols)

| Symbol | Meaning | Default (code) |
|--------|---------|----------------|
| `I` | Inter-job interval (s) | U(45,120) production; **mean 82.5s** in scenarios below |
| `G` | Mean generation time (s) | **unknown** — operator/provider |
| `P` | Mean poll+retrieve (s) | **unknown** |
| `C` | Cooldown (s) | 300 production |
| `N` | Jobs per cooldown cycle | 5 |
| `L` | Verified video lanes | 1 (`VERIFIED_CODE`) |
| `H` | Operating hours/day | 8, 12, 24 |

## Single verified video lane — jobs per hour (with cooldown)

Per job:

```text
T_job = I_mean + G + P
```

Per `N`-job block (code-configured cooldown):

```text
T_block = (N × T_job) + C
J_h = (N × 3600) / T_block
```

Equivalent:

```text
effective_time_per_job = T_job + (C / N)
J_h = 3600 / effective_time_per_job
```

**Do not** use `N / (N×T_job + C) × (3600/N)` — that incorrectly cancels `N`.

Fixed for scenarios: `I_mean = 82.5`, `N = 5`, `C = 300`.

### Optimistic (`G + P = 120` s)

```text
T_job = 202.5 s
T_block = 5 × 202.5 + 300 = 1,312.5 s
J_h = 5 × 3600 / 1,312.5 ≈ 13.71 jobs/hour
```

Daily capacity before failure/retry allowance (`J_day = J_h × H`):

| Window | Capacity (jobs) |
|--------|-----------------|
| 8h | ≈ 110 |
| 12h | ≈ 165 |
| 24h | ≈ 329 |

### Nominal (`G + P = 300` s)

```text
T_job = 382.5 s
T_block = 5 × 382.5 + 300 = 2,212.5 s
J_h = 5 × 3600 / 2,212.5 ≈ 8.14 jobs/hour
```

| Window | Capacity (jobs) |
|--------|-----------------|
| 8h | ≈ 65 |
| 12h | ≈ 98 |
| 24h | ≈ 195 |

### Pessimistic (`G + P = 600` s)

```text
T_job = 682.5 s
T_block = 5 × 682.5 + 300 = 3,712.5 s
J_h = 5 × 3600 / 3,712.5 ≈ 4.85 jobs/hour
```

Before failure/retry allowance:

| Window | Capacity (jobs) |
|--------|-----------------|
| 8h | ≈ 39 |
| 12h | ≈ 58 |
| 24h | ≈ 116 |

**10% effective capacity reduction** (simple planning model: multiply capacity by 0.9; **not** mixing undefined failure rate + retry rate):

| Window | After 10% loss (jobs) |
|--------|------------------------|
| 8h | ≈ 35 |
| 12h | ≈ 52 |
| 24h | ≈ 105 |

## Lanes required for 200 videos/day (theoretical)

```text
required_lanes = ceil(200 / single_lane_daily_capacity)
```

| Scenario | 8h | 12h | 24h |
|----------|----|----|-----|
| Optimistic (no failure allowance) | 2 | 2 | 1 |
| Nominal (no failure allowance) | 4 | 3 | 2 |
| Pessimistic before 10% loss | 6 | 4 | 2 |
| Pessimistic after 10% loss | 6 | 4 | 2 |

## Findings (throughput — theoretical)

- **One verified video lane is not sufficient** for 200 videos within an **8-hour** or **12-hour** operating window under **any** documented scenario here.
- Under the **nominal 24-hour** model, one lane yields **≈195** jobs/day before failure/retry allowance — **does not reliably meet** 200/day.
- **One lane reaches 200/day only** under the **optimistic 24-hour** assumption (≈329 before allowance).
- All values remain **theoretical**; **runtime proof** is required before approving additional execution lanes or any **200/day SLA**.

## Image capacity (code-configured, NOT_VERIFIED live)

Upper bound workers `W_max = 3`. Separate from video lane math above.

## Credit

- Live burn gates: `confirm_live_credit_burn`, `confirm_credit_burn` — **VERIFIED_TEST_IN_THIS_AUDIT**
- Daily budget on legacy `batch` only — **SCHEMA_ONLY** for WGP orchestrator

## Retries and retrieval

Retry/repair increases effective `T_job`; not folded into tables above except the explicit **10% capacity reduction** row. Retrieval failure paths — **VERIFIED_CODE** partial recovery only.

**Do not claim 200+200/day achievable** without runtime proof and D1 decisions.