# CODEX PROMPT — Recover `f2v-flow-queue-runner.js` (surgical, NO full restore)

**Role:** Codex (implementation / repo cleanup). Antigravity must NOT run this.
**Status of file:** `extension/f2v-flow-queue-runner.js` has a `SyntaxError` (`missing )
after argument list`) at line ~2413. `node --check` fails.

## ⛔ Do NOT `git restore` this file
The working tree contains **582 insertions / 99 deletions** of uncommitted work vs `HEAD`.
A `git restore extension/f2v-flow-queue-runner.js` would destroy all of it. The actual
damage is **two localised wounds** introduced by a bad `replace_file_content` edit that
matched partial text (its target contained a literal `\n`). Repair only those two wounds.

## Wound 1 — broken `recordStage(... 'FAIL' ...)` call + missing `return` (≈ line 2410–2413)

Current (corrupted):
```js
      const clickRes = await _clickVisibleOptionExact(scripting, tabId, step, opts);
      if (!clickRes.ok) {
        recordStage(step.stage, 'FAIL',
          `${clickRes.error} detail=${clickRes.detail} candidates=${JSON.stringify(clickRes    // Step 8b: Unconditionally close the settings panel before inserting the prompt.
    // Google Flow sets contenteditable="false" ...
    const panelCloseResult = await _runMainWorld(...) { ... }, []);
    recordStage('F2V_SOP_SETTINGS_PANEL_CLOSE_ATTEMPT', 'PASS', JSON.stringify(panelCloseResult || {}));
    await _sleep(800);
```

The `recordStage` template literal and its `JSON.stringify(...)` argument are cut off
mid-expression, the closing `)` and `;` are gone, the `if` block's `return { ok: false … }`
was deleted, and the Step 8b block was jammed onto the same physical line.

**Target shape** (reference: `HEAD` lines 1992–2002 used `clickRes.visible_candidates`;
confirm the property the *current* `_clickVisibleOptionExact` returns before committing —
it is `visible_candidates` in HEAD):
```js
      const clickRes = await _clickVisibleOptionExact(scripting, tabId, step, opts);
      if (!clickRes.ok) {
        recordStage(step.stage, 'FAIL',
          `${clickRes.error} detail=${clickRes.detail} candidates=${JSON.stringify(clickRes.visible_candidates || [])}`);
        return {
          ok: false,
          error: clickRes.error,
          detail: clickRes.detail,
          stages,
          stage_results: stageResults,
          visible_candidates: clickRes.visible_candidates || [],
        };
      }
      // ... (preserve any success-path recordStage lines that belong here) ...

      // Step 8b: Unconditionally close the settings panel before inserting the prompt.
      // ... panelCloseResult block stays, correctly indented, INSIDE the function ...
```
The Step 8b block must sit **after** the closing `}` of the `if (!clickRes.ok)` block —
never inside it.

## Wound 2 — orphaned duplicate panel-close block (≈ line 2476–2507)

After the GOOD panel-close block ends at:
```js
    recordStage('F2V_SOP_SETTINGS_PANEL_CLOSE_ATTEMPT', 'PASS', JSON.stringify(panelCloseResult || {}));
    await _sleep(800);
```
there is leftover garbage and a **second, stale copy** of the same scan loop that returns
bare strings (`'pill_closed_pass1'`, `'pill_closed_expanded'`, `'escape_on_focused'`,
`'no_close_action_taken'`) and ends with another `}, []);` + `await _sleep(800);`. The
first corrupted token is:
```js
    await _sleep(800);o+1x, frames+1x)   // <-- "o+1x, frames+1x)" is garbage
      for (var i = 0; i < buttons.length; i++) {   // <-- start of stale duplicate
      ...
      return 'no_close_action_taken';
    }, []);
    await _sleep(800);                              // <-- stale duplicate ends here
```
**Delete the entire stale duplicate**, from the `o+1x, frames+1x)` garbage through the
duplicated `}, []);` + `await _sleep(800);`, so that the GOOD block flows straight into:
```js
    // Step 9 — insert prompt.
    const promptResult = await _insertPrompt(scripting, tabId, job?.prompt || '');
```
Keep exactly **one** `F2V_SOP_SETTINGS_PANEL_CLOSE_ATTEMPT` record and **one**
`await _sleep(800);` before Step 9.

## Validation gates (must all pass before commit)
```
node --check extension/f2v-flow-queue-runner.js
node scripts/test-f2v-asset-picker-modal.js
node --check extension/content-flow-dom.js
```
Plus: `grep -c "F2V_SOP_SETTINGS_PANEL_CLOSE_ATTEMPT" extension/f2v-flow-queue-runner.js`
must return **1**.

## Report back (Codex final-report format)
`STATUS` · exact changed files · the three validation commands + pass/fail ·
full 40-char commit SHA · push target · push result · `NEXT_DECISION`.
Do not include `REQUEST_ID=N/A` or `build=legacy`.
