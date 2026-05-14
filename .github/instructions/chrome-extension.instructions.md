# Chrome Extension Instructions

Applies to extension, background, and content-script work.

- Read `AGENTS.md`, `.ai/status/CURRENT_STATE.md`, and `.ai/contracts/CODEX_IMPLEMENTATION_CONTRACT.md`.
- Freeze proven mode/config logic unless the local harness proves a break.
- Do not add tactical upload fallback chains without tests.
- Do not patch runtime/build handshake or upload logic without matching harness coverage.
- Treat `content-flow-dom.js` as an unstable rebuild lane, not a reactive patch sink.
