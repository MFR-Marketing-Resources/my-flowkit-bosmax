# Postiz Integration — Runtime Proof Report

Captured 2026-07-03 against a live local Postiz stack (infra/postiz/docker-compose.yml).
Adapter code under test: agent/services/postiz_client.py @ branch feat/postiz-integration.

## 1. Test proof — Postiz suites (unit + API + UI contracts)

```
$ python -m pytest tests/unit/test_postiz_client.py tests/api/test_postiz_api.py tests/ui/test_postiz_publish_ui_contract.py -q
..............................................                           [100%]
46 passed in 5.10s
(re-run after audit fixes: 46 passed — includes 2 new schedule_at ISO-validation tests)
```

## 2. Regression proof — locked 85-test gate

```
$ python -m pytest tests/unit/test_manual_lane_reroute.py tests/unit/test_make_video_binding.py tests/unit/test_agent_video.py tests/api/test_generate_validation.py tests/ui/test_extension_side_panel_ui_contract.py -q
=========================== short test summary info ===========================
FAILED tests/ui/test_extension_side_panel_ui_contract.py::test_dashboard_portal_reports_current_embedded_route_to_side_panel_parent
1 failed, 84 passed in 11.24s
```

The single failure (OperatorPage token `mode=${encodeURIComponent(mode)}`) pre-exists on
origin/main and is untouched by this branch (verified: token absent in `git show origin/main:...OperatorPage.tsx`).

## 3. Docker / Postiz startup proof

```
$ docker ps --format "{{.Names}}\t{{.Status}}" | grep -i postiz
bosmax-postiz-temporal	Up 3 hours (healthy)
bosmax-postiz-temporal-es	Up 3 hours (healthy)
bosmax-postiz-temporal-pg	Up 3 hours (healthy)
bosmax-postiz	Up 3 hours
bosmax-postiz-redis	Up 3 hours (healthy)
bosmax-postiz-postgres	Up 3 hours (healthy)
```

## 4. Live adapter runtime proof (health, 401, JPG+MP4 upload, draft payload)

```
1) HEALTH: {"enabled": true, "base_url": "http://localhost:5000", "api_key_present": true, "upload_mode": "file", "default_post_type": "draft", "public_media_base_url": null, "ok": true, "problems": []}
2) INTEGRATIONS (live): []
2b) BAD KEY handled safely: POSTIZ_API_ERROR:401:{"msg":"Invalid API key"}
3a) IMAGE uploaded: {"id": "f16bee31-c980-41be-86cf-90b437f81f9a", "path": "http://localhost:5000/uploads/2026/07/03/5bed15dae78cbc2a9c9e840162ea124e.jpg"}
3b) VIDEO (mp4) uploaded: {"id": "68bd4f39-ee92-4615-a20f-41e8b3a9f63a", "path": "http://localhost:5000/uploads/2026/07/03/5910289109a5799c792dcbb84a5f19fd4a.mp4"}
4) DRAFT PAYLOAD: {"type": "draft", "date": "2026-07-03T04:52:47Z", "shortLink": false, "posts": [{"integration": {"id": "INTEGRATION_ID_PLACEHOLDER"}, "value": [{"content": "BOSMAX runtime proof draft", "image": [{"id": "68bd4f39-ee92-4615-a20f-41e8b3a9f63a", "path": "http://localhost:5000/uploads/2026/07/03/5910289109a5799c792dcbb84a5f19fd4a.mp4"}]}], "settings": {"privacy_level": "SELF_ONLY", "duet": false, "stitch": false, "comment": false, "autoAddMusic": false, "brand_content_toggle": false, "brand_organic_toggle": false, "content_posting_method": "DIRECT_POST"}}]}
4b) POST /posts blocked as expected (no connected channels): POSTIZ_API_ERROR:400:{"message":"Integration with id INTEGRATION_ID_PLACEHOLDER not found","error":"Bad Request","statusCode":400}
RUNTIME_PROOF_COMPLETE
```

Notes: media ids/paths above are local ephemeral Postiz ids on the operator machine (not secrets).
Step 4b is the documented external boundary: POST /posts requires a CONNECTED channel,
and connecting channels requires provider OAuth apps (TikTok dev app + audit, Meta Live mode).

## 5. Migration proof (real-DB copy, zero row loss)

```
$ python migration_smoke.py   # init_db() against a COPY of the real flow_agent.db
MIGRATION_SMOKE_OK
row counts preserved: {'workspace_generation_package': 0, 'batch_generation_run': 2, 'generated_artifact': 13, 'product': 508, 'creative_asset': 16}
```

## 6. No-secrets proof

```
$ grep -rlF "<generated API key>" agent dashboard/src infra docs tests .env.example
CLEAN: generated API key appears in NO repo file
infra/postiz/.env
(second line: git check-ignore confirms infra/postiz/.env is gitignored)
```

## 7. Browser/UI proof

Dashboard /postiz served by a live agent (API_PORT=8120) with POSTIZ_ENABLED=true against the
live Postiz: health banner OK, real Library artifacts listed with previews, channel section
(empty — zero OAuth channels), "Draft (safe)" default, dry-run preview button.
Screenshot archived in the operator session: scratchpad/proof_postiz_ui_live.png.

## 8. POSTIZ_ENABLED=false unchanged-behavior proof

Covered by tests (test_integrations_and_publish_fail_closed_when_disabled,
test_disabled_flag_blocks_network_entry_points) and by the regression gate above running
with the flag unset. The adapter is additive: no existing module imports it.
