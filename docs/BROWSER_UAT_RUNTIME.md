# BOSMAX Browser UAT Runtime — contract for every AI coding agent

## Rule (mandatory)

Before claiming browser UAT is unavailable / NOT_VERIFIED / "Chrome consent required":

1. Run health:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/browser-uat/browser-uat-health.ps1
   ```
2. If unhealthy, start the dedicated runtime:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/browser-uat/start-browser-uat.ps1
   ```
3. Prefer **Chrome DevTools MCP** attached to the existing CDP endpoint  
   `http://127.0.0.1:9222` through the checked-in launcher
   `scripts/browser-uat/claude-chrome-devtools-wrapper.cmd`. The launcher runs
   the health preflight with stdin disconnected, then starts the pinned global
   `chrome-devtools-mcp@1.8.0` entry point so MCP stdio framing is preserved.
4. If MCP is unavailable in this agent, use the **Playwright/CDP shell fallback**:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/browser-uat/run-browser-uat.ps1 smoke
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/browser-uat/bosmax-click-path-uat.ps1
   ```
5. Only report `INTERACTIVE_BROWSER_UAT=NOT_VERIFIED` after **both** MCP and Playwright/CDP paths genuinely fail.

**"Chrome remote debugging consent" / `chrome://inspect` Allow is NOT the canonical path** and must not be treated as a hard blocker when the dedicated localhost CDP runtime is available.

## Canonical endpoints

| Item | Value |
|---|---|
| CDP | `http://127.0.0.1:9222` |
| BOSMAX | `http://127.0.0.1:8100` |
| Profile | `C:\Users\USER\Desktop\_bosmax_runtime\browser_uat\chrome-profile` |
| Contract | `C:\Users\USER\Desktop\_bosmax_runtime\browser_uat\browser-uat.json` |
| Env | `BOSMAX_CDP_URL`, `BOSMAX_UAT_URL`, `BOSMAX_BROWSER_UAT_ROOT` |

## Security

- CDP bound to **127.0.0.1 only** (never `0.0.0.0`)
- Dedicated UAT profile only — never the user's personal Chrome profile
- Do not copy cookies/passwords from personal Chrome
- Do not kill unrelated Chrome processes
- Profile/state/logs/screenshots are machine-local and gitignored

## Autostart

User-level Scheduled Task + Startup shortcut:

`BOSMAX Browser UAT Runtime`

Install/reinstall:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/browser-uat/install-browser-uat-autostart.ps1
```

## Agent MCP configuration

Server name: **`chrome-devtools`**

```json
{
  "command": "C:\\Users\\USER\\Desktop\\_ref_flowkit\\scripts\\browser-uat\\claude-chrome-devtools-wrapper.cmd",
  "args": []
}
```

The direct `npx` command is a fallback for environments without the launcher;
do not use it for the managed Claude Desktop or Claude Code configuration.

Do **not** launch a second random Chrome profile per agent (`--isolated` is not the BOSMAX UAT default).

## Concurrency

- Shared browser runtime, separate tabs
- Soft lease file: `_bosmax_runtime/browser_uat/state/uat-lease.json`
- Never `browser.close()` in a way that stops the shared Chrome; harness disconnects only
- Never restart CDP Chrome while another UAT lease is active unless health is hard-fail

## Smoke / click-path

Read-only. No Product Truth writes. No provider credit spend.

```powershell
scripts/browser-uat/bosmax-smoke-uat.ps1
scripts/browser-uat/bosmax-click-path-uat.ps1
```

Receipts + screenshots land under `_bosmax_runtime/browser_uat/`.
