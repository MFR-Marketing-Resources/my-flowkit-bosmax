# Throughput capacity and credit model (repair v1.1)

All numeric scenarios are **assumption-bound**. Labels: **theoretical** | **code-configured** | **test-supported** | **runtime-proven** | **unknown provider**.

## Variables (symbols)

| Symbol | Meaning | Default (code) |
|--------|---------|----------------|
| `I` | Inter-job interval (s) | U(45,120) production; U(5,15) bulk IMG |
| `G` | Mean generation time (s) | **unknown** — operator/provider |
| `P` | Mean poll+retrieve (s) | **unknown** |
| `C` | Cooldown (s) | 300 production / 60 bulk |
| `N` | Jobs per cooldown cycle | 5 |
| `L` | Verified video lanes | 1 (`VERIFIED_CODE`) |
| `W` | Image workers | 2–3 (`code-configured`, `NOT_VERIFIED` live) |
| `F` | Failure rate | parameter |
| `R` | Retry rate | parameter |
| `H` | Operating hours/day | 8, 12, 24 scenarios |

## Single video lane — cycle time (nominal)

Per job wall time (theoretical lower bound):

`T_job ≈ I + G + P` (serial; `VERIFIED_CODE`)

Every `N` jobs add `C`:

`T_batch(N) ≈ N * T_job + C`

Jobs per hour (theoretical):

`J_h = 3600 / T_job` (ignoring cooldown) — **overoptimistic**

With cooldown (code-configured):

`J_h ≈ N / (N*T_job + C) * (3600/N)` simplified per 5-job block.

### Scenarios (G and P assumed — **NOT_VERIFIED**)

Assume `G+P = 120s` (optimistic), `I_mean = 82.5s` → `T_job ≈ 202.5s` → **~17.8 jobs/h theoretical**.

| Window | Optimistic (G+P=120s) | Nominal (G+P=300s) | Pessimistic (G+P=600s, F=10%) |
|--------|----------------------|---------------------|-------------------------------|
| 8h | ~142 | ~72 | ~40 |
| 12h | ~214 | ~108 | ~60 |
| 24h | ~427 | ~216 | ~120 |

**Claim:** 200 videos/day on **one** lane requires either 24h window with optimistic G+P **or** multiple verified lanes — **NOT_VERIFIED** at runtime.

Lanes required (theoretical): `ceil(200 / J_day)` where `J_day = J_h * H`.

## Image capacity (code-configured)

Upper bound workers `W_max = 3`. If mean IMG job `T_img = 60s`:

`IMG_h_max ≈ W * 3600 / T_img` → 180/h at W=3 — **theoretical**.

200 posters/day in 8h needs **25/h** — code-configured may suffice; **runtime-proven: NO**.

## Combined uncertainty

Video lock does not block IMG in-process (`VERIFIED_CODE`); Google account rate limit may block both — **NOT_VERIFIED**.

## Credit

- Live burn gates: `confirm_live_credit_burn`, `confirm_credit_burn` — **VERIFIED_TEST_IN_THIS_AUDIT**
- Daily budget field on legacy `batch` only — **SCHEMA_ONLY** for WGP orchestrator

## Retries and retrieval bottlenecks

Retry multiplies effective `T_job` by `(1+R)`. Retrieval failure leaves `GENERATED` without `DOWNLOADED` — operator/manual (**VERIFIED_CODE** partial recovery).

**Do not claim 200+200/day achievable** without runtime proof and D1 decisions.