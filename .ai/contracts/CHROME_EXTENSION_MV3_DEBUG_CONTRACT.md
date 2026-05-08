# CHROME EXTENSION MV3 DEBUG CONTRACT

This contract is MANDATORY for all Chrome Extension Manifest V3 debugging tasks.

## Objective: Fix Common MV3 Issues
- "message port closed before a response was received"
- "listener indicated async response but channel closed"
- Service worker lifecycle bugs
- Content script stale tab bugs (after reload/update)
- chrome.runtime.sendMessage / chrome.tabs.sendMessage race conditions

## MV3 HARD RULES for Debugging Agents

1. **Map Message Topology:**
   - Map every sender/receiver pair.
   - Use the Message Topology table below.

2. **Audit Message Listeners:**
   - Audit every `chrome.runtime.onMessage` listener.
   - Check if the listener returns `true` for async paths.
   - Check if `sendResponse` is GUARANTEED to be called on every path (even error paths).
   - Check for async listeners returning a Promise accidentally (MV3 requires literal `true`).

3. **Audit Message Senders:**
   - Audit every `chrome.tabs.sendMessage` and `chrome.runtime.sendMessage` call.
   - Check for missing callback/promise error handling (e.g., `chrome.runtime.lastError`).

4. **Audit Lifecycle:**
   - Check Service Worker lifecycle (is it suspended? does it have persistent state it shouldn't?).
   - Check Content Script lifecycle in already-open tabs (stale scripts).
   - Check Extension reload/update behavior.
   - Check Tab reload/reinjection strategy.

## Required Audit Tables

### Message Topology
| Sender | Receiver | API | File | Risk |
|--------|----------|-----|------|------|

### Listener Return Audit
| File | Listener | async? | returns true? | sendResponse guaranteed? | Risk |
|------|----------|--------|---------------|--------------------------|------|

## Patching & Validation
- Patch ONLY the verified failure path.
- Validate using the Extension Reload + Manual Protocol.
- Report must follow the format in [.ai/contracts/ROOT_CAUSE_REPORT_FORMAT.md](file:///c:/Users/USER/Desktop/_ref_flowkit/.ai/contracts/ROOT_CAUSE_REPORT_FORMAT.md).
