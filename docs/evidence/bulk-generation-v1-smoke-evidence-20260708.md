# Bulk Generation V1 — Post-Smoke Evidence Pack

**Date (UTC):** 2026-07-08  
**Merge:** PR #282 → `main` @ `dee11976c6eb73808bd6a0901ecbaa3f8ff81b29` (`dee1197`)  
**Smoke run:** `5642201d-2124-433a-b3a8-e8d1e87a50dc` (AVATAR_IMAGE, 2 items)  
**Scope:** Live Google Flow + Chrome extension via local agent `127.0.0.1:8100`

## Verification scope (explicit)

| Claim | Status |
|--------|--------|
| **Live AVATAR_IMAGE bulk** | **Passed** (2/2 generated + registered) |
| **Live video bulk smoke** | **Not run** |
| **V1 video concurrency** | **Serial** (`max_parallel_videos=1`) |
| **CI** | **Not available** — evidence is **local operator + API/DB** only |

---

## 1. Agent startup log (post-restart, port conflict resolved)

Captured when agent bound successfully after stopping stale PID **4460** on `:8100`:

```text
INFO:     Waiting for application startup.
2026-07-08 22:54:18,xxx [INFO] agent.db.schema: Database initialized at <REPO_ROOT>/flow_agent.db
2026-07-08 22:54:18,xxx [INFO] agent.main: RUNTIME_STORAGE base_dir=<REPO_ROOT> db=<REPO_ROOT>/flow_agent.db products=516 queue=298 branch=main sha=dee1197
2026-07-08 22:54:18,xxx [INFO] agent.main: Flow Kit starting on 127.0.0.1:8100
INFO:     Application startup complete.
2026-07-08 22:54:18,775 [INFO] agent.services.flow_client: Extension connected #1
2026-07-08 22:54:18,777 [INFO] agent.services.flow_client: Extension ready, flowKey=yes
```

`<REPO_ROOT>` = Flow Kit checkout root (e.g. `my-flowkit-bosmax` clone).

**`/health` (evidence refresh):**

```json
{
  "status": "ok",
  "extension_connected": true,
  "extension_state": "idle",
  "flow_key_present": true,
  "dashboard_url": "http://127.0.0.1:8100/operator"
}
```

**Prior failure (forensic):** background agent start exit **1** — `[Errno 10048]` bind conflict on `127.0.0.1:8100` while stale process served pre-#282 API.

---

## 2. `GET /api/bulk-generation/5642201d-2124-433a-b3a8-e8d1e87a50dc`

Refreshed **2026-07-08** — summary:

| Field | Value |
|--------|--------|
| `kind` | `AVATAR_IMAGE` |
| `status` | `COMPLETED` |
| `total_expected` / `total_completed` / `total_failed` | 2 / 2 / 0 |
| `status_counts` | `{ "REGISTERED": 2 }` |
| `confirm_credit_burn` | `true` |
| `max_parallel_images` | 2 |

---

## 3. Items (API + SQLite `bulk_generation_item`)

| source_ref | status | job_id | media_id | creative_asset_id |
|------------|--------|--------|----------|-------------------|
| BOS_F_ZARA_03 | REGISTERED | g_0362198ff0ba | 663b48bb-da35-427b-ad97-2d38d6e1aa0d | ca_0b3ebf3ea0074deb |
| BOS_F_ZARA_04 | REGISTERED | g_958b9ab2d162 | 9c0806cc-3e15-49a5-a2fc-f6f816a5a9f2 | ca_739930083cf5414f |

**local_path (API, relative to repo):**

- `output/retrieved/663b48bb-da35-427b-ad97-2d38d6e1aa0d.jpg`
- `output/retrieved/9c0806cc-3e15-49a5-a2fc-f6f816a5a9f2.jpg`

---

## 4. Creative assets

| asset_id | semantic_role | description |
|----------|---------------|-------------|
| ca_0b3ebf3ea0074deb | CHARACTER_REFERENCE | AVATAR_CODE:BOS_F_ZARA_03 — bulk orchestrator IMG lane |
| ca_739930083cf5414f | CHARACTER_REFERENCE | AVATAR_CODE:BOS_F_ZARA_04 — bulk orchestrator IMG lane |

---

## 5. Dashboard UI confirmation

**Automated capture limitation:** Headless browser loaded shell/sidebar only; operator SPA needs live WebSocket to the same agent. **Manual** confirmation on operator machine:

1. Open `http://127.0.0.1:8100/operator/workspace/avatar-registry`
2. **Recent bulk runs** → select `5642201d-2124-433a-b3a8-e8d1e87a50dc`
3. Item table shows **BOS_F_ZARA_03** / **BOS_F_ZARA_04** → **REGISTERED**

**Archived partial screenshot (sidebar only):**  
`assets/bulk-v1-smoke-dashboard-sidebar-20260708.png`

**API substitute for item table:** `GET` bulk run `items[]` is authoritative for forensic trace.

---

## 6. Video bulk

**Live smoke not run.** Bulk video V1 remains **serial** (`max_parallel_videos=1`, APPROVED-only governance). No production claim for video lane.

---

## Verdict

**AVATAR_IMAGE bulk:** live Flow smoke **accepted** — 2/2 generated, registered, CHARACTER_REFERENCE + AVATAR_CODE markers confirmed via API/DB.

**Implementation:** closed unless a **new runtime bug** is reported.