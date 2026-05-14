# Architecture Reset

## Diagnosis
- Repeated failure was systemic architecture and testing-method failure, not just one bad selector.
- `content-flow-dom.js` accumulated reactive fallbacks, mixed proven and failed selectors, direct upload tricks, recursive shadow scanning, and telemetry mixed with execution logic.

## Reset Decision
- Freeze proven mode/config paths.
- Rebuild runtime handshake, telemetry, selector evidence, and upload strategy in phases.
- Move live debugging out of Google Flow and into a local harness first.

## Phase Order
1. Runtime/build handshake and telemetry lockdown
2. Playwright persistent-context harness
3. Selector and evidence registry
4. CDP upload proof of concept
5. Upload-lane decontamination
6. One-shot live UAT
