## PR #298 — Hermetic baseline & merge readiness (updated)

**State:** OPEN — **NOT MERGED** — **NOT on :8100** — zero credits

| | SHA |
|---|---|
| **origin/main** | `eda2b1a0443382038f29d4a39f8163aa232a5cb5` |
| **PR branch (local)** | see `git rev-parse HEAD` after push |

### Hermetic methodology (authoritative)
- Isolated `FLOW_AGENT_DIR` roots from `tests/fixtures/hermetic/` only — **never** canonical `_ref_flowkit` machine state.
- Product intelligence vision tests use **in-test monkeypatch** (`get_lane_provider`, `get_lane_api_key`, `_resolve_vision_model`, `analyze_product_image_payload`) — no operator `.local-agent` dependency.
- A/B harness: `scripts/pr298_hermetic_ab_compare.py` + machine-readable `docs/pr298_hermetic_ab_evidence.json`.
- Canonical guard: SHA256 of canonical `ai-provider-settings.json` unchanged across harness runs.

### Gaps closed this pass
1. **SQLite CRUD** — `tests/unit/test_extend_prompt_sqlite_persistence.py` (create → reload → raw `prompt_blocks_json`).
2. **Handoff Bank** — `HandoffExtendPromptBlocks` + `WorkspaceGenerationPackagesHandoff.component.test.tsx` (clipboard + fail-closed).
3. **Per-representation audio** — structured `prompt_representations` with `audio_seam_contract` per role; `test_extend_representation_audio_contracts.py`.

### Gates (branch worktree)
| Gate | Result |
|------|--------|
| `scripts/verify-gate.ps1` | **PASS** (MANDOR + build + vitest + backend smoke) |

### Run hermetic A/B locally
```powershell
cd C:\Users\USER\Desktop\_ref_flowkit_wt\feat-google-flow-extension-native-prompt-renderer-v1
$env:PYTHONPATH = "."
..\..\_ref_flowkit\.venv\Scripts\python.exe scripts\pr298_hermetic_ab_compare.py `
  --main-repo C:\Users\USER\Desktop\_ref_flowkit `
  --branch-repo (Get-Location) `
  --python C:\Users\USER\Desktop\_ref_flowkit\.venv\Scripts\python.exe `
  --evidence-dir $env:TEMP\pr298-ab-evidence
```

### PR
https://github.com/MFR-Marketing-Resources/my-flowkit-bosmax/pull/298