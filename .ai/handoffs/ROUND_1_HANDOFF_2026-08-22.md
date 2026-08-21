# Round 2 Live-Certification Handoff

## Canonical runtime

- Runtime SHA: `13904eb09f6e8634f54d60f93a476df20a265385`
- Runtime proof: `runtime_sha == origin_main`, `source_stale=false`, `db_canonical=true`, `bundle_matches=true`.
- Runtime URL: `http://127.0.0.1:8100`.

## Current direct-lane truth

- Readiness contract: `direct-video-readiness-v1`.
- Reference-bearing direct execution is `BLOCKED` until the captured route is enabled and certified.
- `DIRECT_VIDEO_LANE_ENABLED` is currently disabled.
- `provider_calls=0` and `credit_spend=false` on the readiness surface.
- The configured `direct_video_model_keys` map is exactly `{}`. No model key is inferred from the registry or provider defaults.
- For a reference-bearing 10-second request, the machine blocker is exactly `DIRECT_10S_CONTRACT_NOT_CERTIFIED`; status is `NOT_CERTIFIED` and `provider_calls=0`.

## Safe live-capture entrypoint

Use the API-first route only after per-run owner authorization:

```text
POST /api/flow/execute-flow-job
_direct_capture=true
DIRECT_VIDEO_CAPTURE_ENABLED=1
confirm_live_credit_burn=true
request_id=<stable per-run idempotency key>
```

The request must carry the selected `mode`, `source_mode`, `model`, `duration_s`, `aspect`, project/reference identity, and the exact approval/credit confirmation. A failed readiness check must stop before this entrypoint. Do not use the frozen DOM generation lane.

## Owner authorization boundary

Round 2 may spend Google Flow video credit only after the owner explicitly authorizes that bounded run and confirms the intended model, duration, references, and maximum provider operations. Round 1 performed no live generation or model-key capture.

## Minimum progressive live-UAT order

1. Reference direct lane at proven 8s.
2. Owner-authorized Omni Flash reference 10s capture and contract recording.
3. Native Extend 16s.
4. Native Extend 24s.
5. Hybrid.
6. Faceless.
7. Montage scene sequencing and final assembly.
8. Production Studio / P6.
9. Results, Video Library, page reload, and backend restart recovery.

Stop at the first failed stage; do not retry by resubmitting an uncertain provider operation.

## Evidence required for every live run

Capture: `request_id`, implementation/runtime SHA, first-fail stage, full structured error, model key, requested and observed duration, aspect, reference IDs/fingerprints, project ID, provider operation/workflow/media IDs, submit count, credit before/after, lifecycle states, artifact path/size/SHA-256, artifact DB readback, UI result identity, page-reload/restart recovery, and raw telemetry proving provider touch or `provider_calls=0`.
