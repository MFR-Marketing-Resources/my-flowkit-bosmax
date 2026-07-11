# Gap, risk, and decision register (repair v1.1)

## D1 — Daily video volume (split)

| ID | Question | Options | Evidence | Recommendation | Risk if undecided |
|----|----------|---------|----------|----------------|-------------------|
| D1A | Is 200 videos/day hard SLA, target, or aspirational? | SLA / target / aspirational | Throughput doc 09 | Treat as **target** until runtime proof | Over-build or under-build |
| D1B | Scope: per product, campaign, account, workspace? | each | No unified plan table | **per workspace account** default | Credit attribution wrong |
| D1C | Operating window | 8h / 12h / 24h | Operator practice unknown | **12h** default for planning | Lane count wrong |
| D1D | Duration/model mix | Veo 8s vs others | EMD resolver | Lock in plan metadata | Throughput variance |
| D1E | Acceptable failure+retry rate | 0–20% | No SLO in repo | **5%** planning default | Credit buffer |

**Owner:** Business + architecture | **Deadline:** before implementation contract | **Schema:** daily plan fields | **UX:** targets screen

## D2 — Concurrency units (do not conflate)

| Unit | Current evidence |
|------|------------------|
| Process worker | 1 video in-flight `make_video` — `VERIFIED_CODE` |
| Execution lane | **PROPOSED** first-class; today == process + browser session |
| Browser profile / tab | **NOT_VERIFIED** independent |
| Google account / Flow project | **NOT_VERIFIED** |
| Provider rate-limit bucket | **BLOCKED_BY_EXTERNAL_RUNTIME** |
| Engine / media type | IMG exempt from video lock in-process — `VERIFIED_CODE` |

**Recommendation:** Model **execution_lane_id** in orchestrator; default **1 lane** until proof.

## D3 — Legacy batch

| Option | Consequences | Proof needed |
|--------|--------------|--------------|
| Retain | Dual authority, failing tests, INSERT 20/21 bug | Fix planner or tests |
| Integrate | High migration cost | Map variants→WGP |
| Freeze | No new features | Document deprecation |
| Retire | Remove API/UI | Confirm zero usage |

**Recommendation:** **Retire** long-term; **freeze** short-term. Migration proof: grep dashboard for `/api/batches`.

## D4 — Execution lanes (architecture)

Browser tabs are **not** the domain model. **PROPOSED:** lane = {account, browser profile, extension connection, engine policy}.

**NOT_VERIFIED:** >1 lane safe.

## D5 — Dedupe thresholds (separate)

| Surface | Current | Decision |
|---------|---------|----------|
| Dialogue semantic | 0.90 soft in planner | hard block threshold? |
| Hook | partial fingerprint | operator policy |
| Creative DNA | missing | define vector or rule bundle |
| Visual output similarity | missing | provider QA |
| Controlled reuse | SAME_SCRIPT_* strategies | explicit quota |

## D6 — Poster production item model

| Model | Description |
|-------|-------------|
| Independent item | Separate poster targets in plan |
| Derivative child | Poster tied to video concept ID |
| Paired campaign | Linked IDs, separate execution |
| Hybrid | **Recommendation** for discussion |

## D7 — Durable orchestrator state

**Reclassified:** `REQUIRED_ARCHITECTURE_CAPABILITY` for 400-output long runs.

Pause/resume today: `_run_control` **PROCESS_MEMORY_ONLY** for production run.

**Required:** DB-backed run lease, item attempts, idempotency keys — **PROPOSED** schema in `06` / `current_schema_matrix.csv`.

## Risks (unchanged + repair)

- **R1:** `max_parallel_jobs` >1 without lane proof — false confidence
- **R2:** Legacy vs WGP batch confusion
- **R3:** Provider 403 — CURRENT_STATE
- **R4:** Manifest SHA self-reference — mitigated in v1.1 provenance