## PR #298 — Extension-native Google Flow prompt representations (forensic repair)

**State:** OPEN — **NOT MERGED** — **NOT deployed to :8100** — **zero credits / no live generation**

### Base / head (verified)
| | SHA |
|---|---|
| **Base (`origin/main`)** | `007a8dbff402286088289b6c88d22676d6a26590` (POSTER_BUILDER_V2) |
| **Head** | `77fb6f855045784f79f5753452714892ca4cb14f` |

### Runtime separation
Canonical `:8100` runs **approved `main` only** (PID restarted via lifecycle; `source_stale_since_start=false`). PR branch is developed in isolated worktree — **never deployed to canonical runtime**.

### Architecture
- **Production route unchanged:** `GOOGLE_FLOW_INDEPENDENT_8S_BLOCKS`; `engine_prompt_text` = independent 9-section blocks.
- **Research layer:** `initial_generation_prompt_text` (Block 1 active voice seam), `flow_extend_prompt_text` (compact Extend prose), `flow_extend_prompt_validation`.
- **Dialogue:** pre-finalization packable compression + `omitted_utterances` audit; monotonic allocation; no post-finalization silent drops.
- **Continuity:** `CONTINUITY_STATE_MISMATCH` fail-closed (no prefer-side merge).
- **UI:** Extend only when `hasValidFlowExtendPrompt` (not `block_index>1`); malformed → **INVALID EXTEND REPRESENTATION**.

### Verification (branch worktree)
| Gate | Result |
|------|--------|
| Focused extend + integrity + persistence tests | **59 passed** |
| Dashboard Vitest (utils + Operator component) | **11 passed** |
| `scripts/verify-gate.ps1` | **PASS** |
| Full backend `tests/unit+ui+api` vs `main` | main **20** fail / branch **19** fail; **1 net-new** (`test_product_intelligence_service` — under investigation) |

### Known limitations
- Persistence proof uses `workspace_generation_package_service._json` round-trip (same serialization path as DB column); full SQLite CRUD integration test not added in this pass.
- `prompt_representations` map on blocks is not yet fully nested with per-representation audio objects (audio contract on block + validation metadata present).
- Prompt Handoff Bank: contract + shared util tests; no separate Handoff component render test yet.

### Commits on branch
1. `ec01276` — initial extend renderer  
2. `06620b0` — UI / production-research separation repair  
3. `77fb6f8` — dialogue integrity, continuity fail-closed, validation hardening  