# GOOGLE FLOW EXECUTION SAFETY CONTRACT

## OBJECTIVE
Define preflight verification and real-time execution guards for the extension-based executor.

## PREFLIGHT GATES
- **Agent Status**: Local BOSMAX agent must be online and responsive.
- **Extension Connectivity**: Chrome extension must report `extension_connected: true`.
- **Tab State**: Target Google Flow tab must be active and correctly URL-routed.
- **Mode Matching**: Selected Google Flow UI mode must exactly match the `google_flow_mode` in the variant plan.
- **Asset Integrity**: Any required asset (Image/Start Frame/End Frame) must be uploaded and verified in the DOM.
- **Prompt Injection**: Prompt must be visible in the target textarea before clicking Generate.
- **Control Readiness**: Generate button must be in an enabled state.
- **Traceability**: `request_id` and `variant_id` must be logged alongside execution events.

## ABORT TRIGGERS
- Missing Product Creative Brief or Variant Plan.
- Variant prompt is empty or malformed.
- Required image/frame asset is missing or failed to upload.
- UI mode mismatch detected at runtime.
- MV3 telemetry or DOM monitoring is unavailable.
- Credit limit or failure threshold exceeded.
