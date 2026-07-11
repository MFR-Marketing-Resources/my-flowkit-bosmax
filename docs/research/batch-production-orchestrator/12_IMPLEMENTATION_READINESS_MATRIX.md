# Implementation readiness matrix

| Capability | As-is | Extend | New build | Blocker |
|------------|-------|--------|-----------|---------|
| Batch prompt 1–100 | Y | | | |
| Production serial video | Y | metrics | | Runtime scale proof |
| Bulk IMG parallel 2–3 | Y | | | Live proof |
| Daily plan / waves | | | Y | DECISION_REQUIRED |
| Max unique preflight | | | Y | MISSING |
| Poster bulk | | | Y | MISSING |
| Multi-lane video | | | Y | NOT_VERIFIED |
| Durable pause/resume | | Y | | PROCESS_MEMORY_ONLY |
| Unified orchestrator UI | | | Y | MISSING |

**Verdict:** `HOLD_RUNTIME_PROOF_REQUIRED` — not `READY_FOR_IMPLEMENTATION`.
