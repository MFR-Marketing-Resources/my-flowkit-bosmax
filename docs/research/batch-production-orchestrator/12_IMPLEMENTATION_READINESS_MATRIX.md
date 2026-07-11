# Implementation readiness matrix (repair v1.1)

| Capability | As-is | Extend | New build | Blocker |
|------------|-------|--------|-----------|---------|
| Batch prompt 1–100 | Y | | | |
| Production serial video | Y | metrics | | Runtime scale proof |
| Bulk IMG parallel 2–3 | Y | | | Live proof |
| Daily plan / waves | | | Y | D1 DECISION_REQUIRED |
| Max unique preflight | | | Y | PROPOSED doc 13 |
| Poster bulk | | | Y | D6 |
| Multi-lane video | | | Y | NOT_VERIFIED |
| Durable pause/resume | | Y | | D7 REQUIRED |
| Unified orchestrator UI | | | Y | PROPOSED |
| Failed legacy batch tests | broken | fix or retire | | D3 |

**Verdict (post-repair):** `READY_FOR_ARCHITECTURE_LOCK_REVIEW`

Runtime proof for throughput/concurrency remains **REQUIRED** before `READY_FOR_IMPLEMENTATION` (not used).

**Manifest provenance:** final PR head SHA is **not** embedded in committed `manifest.json` — see delivery report.