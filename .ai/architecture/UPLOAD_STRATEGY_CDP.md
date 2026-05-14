# Upload Strategy: CDP

## Current Decision
- DOM upload from the content script is deprecated and unreliable as the primary strategy.
- `DataTransfer` drag and drop simulations are deprecated.
- `input.files` assignment from the isolated content script is deprecated.
- Chrome DevTools Protocol file chooser interception via `chrome.debugger` is the recommended technical path.

## Scope Boundary
- CDP implementation still requires a proof of concept.
- No CDP implementation is authorized until the Phase 2 prompt is approved.

## Content Script Role After CDP
- Trigger the visible upload control.
- Observe modal and slot state.
- Verify Start-slot preview.
- Avoid file-object manipulation.
