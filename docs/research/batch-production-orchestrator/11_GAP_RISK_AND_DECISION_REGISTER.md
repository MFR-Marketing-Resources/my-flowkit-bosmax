# Gap, risk, and decision register

| ID | Item | Classification | Owner decision |
|----|------|----------------|----------------|
| D1 | Target 200 video/day per account — achievable? | DECISION_REQUIRED | Business + runtime proof |
| D2 | Independent image lanes vs shared account limit | DECISION_REQUIRED | Provider |
| D3 | Retire legacy `batch` / `batch_planner` path? | DECISION_REQUIRED | Architecture |
| D4 | Multi-tab / multi-project concurrency | NOT_VERIFIED | Runtime study |
| D5 | Near-duplicate hard block threshold | DECISION_REQUIRED | Creative ops |
| D6 | Poster bulk orchestration model | PROPOSED | Product |
| D7 | Durable orchestrator state store | PROPOSED | Engineering |

## Risks

- **R1:** Assuming `max_parallel_jobs` column allows >1 without changing make_video lock — false concurrency (**VERIFIED_CODE** lock overrides).
- **R2:** Legacy batch UI/API confusion with WGP batch — operator error (**PARTIALLY_IMPLEMENTED**).
- **R3:** Rate limit 403 during high volume — **BLOCKED_BY_EXTERNAL_RUNTIME** (CURRENT_STATE).
