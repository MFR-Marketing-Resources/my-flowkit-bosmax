# CHROME EXTENSION MV3 DEBUG CONTRACT

This contract must be loaded for any debugging tasks involving the Chrome Extension.

## Mandatory Audit Points

You must audit the following areas for potential failure points:

1. **Message Passing:** `chrome.runtime.onMessage` listeners and `sendMessage` calls.
2. **Lifecycle:** Service worker and content script lifecycle transitions.
3. **Stale Contexts:** Already-open tabs with stale content scripts after extension reload.
4. **Async Listeners:** Ensure listeners returning `true` for async `sendResponse` actually guarantee the response is sent.
5. **Race Conditions:** Extension reload/update vs tab interaction.

## Required Audit Tables

### Message Topology
| Sender | Receiver | API | File | Risk |
|--------|----------|-----|------|------|
|        |          |     |      |      |

### Listener Return Audit
| File | Listener | async? | returns true? | sendResponse guaranteed? | Risk |
|------|----------|--------|---------------|--------------------------|------|
|      |          |        |               |                          |      |

## Validation Requirements
- Confirm behavior after `chrome.runtime.reload()`.
- Test on a fresh tab and an existing tab.
- Verify manifest permissions match API usage.
