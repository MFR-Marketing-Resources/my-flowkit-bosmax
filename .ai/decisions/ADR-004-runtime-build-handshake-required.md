# ADR-004: Runtime Build Handshake Required

## Decision
- Background and content runtime contexts must prove the same build before execution is trusted.

## Consequence
- `build=legacy` is a rejection condition.
- Telemetry must carry synchronized build IDs.
