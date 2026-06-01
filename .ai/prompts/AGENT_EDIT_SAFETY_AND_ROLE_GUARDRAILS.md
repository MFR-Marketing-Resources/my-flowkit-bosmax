# Agent Edit-Safety & Role Guardrails (current)

**Why this exists:** Antigravity was handed an *implementation* instruction
("Add telemetry stage for Step 8b panel close…") and tried to apply it with
`replace_file_content`. Its `TargetContent` contained a literal `\n` (backslash-n)
embedded in the match text. The literal could not be matched, the tool did a **partial**
replacement, two code blocks were fused onto one line, and
`extension/f2v-flow-queue-runner.js` was left with a `SyntaxError` at line 2413. The
session stalled. These guardrails prevent a repeat.

---

## A. Role boundaries (non-negotiable)

| Agent | May do | Must NOT do |
|---|---|---|
| **Antigravity** | One-shot **live UAT** only; report telemetry-backed PASS/FAIL stages | Patch, edit, refactor, or repair files; debug loops; `git restore`; selector experiments |
| **Codex** | Implementation, local harness, repo cleanup, **file recovery**, commits, push | Live Google Flow debugging as a substitute for local proof |
| **Claude Code** | Review, architecture critique, refactor planning, prompt authoring | Implementation unless explicitly assigned |

➡️ **If a task asks Antigravity to change code, Antigravity stops and escalates to Codex.**
The broken runner above is Codex's to fix (see `CODEX_RECOVERY_F2V_RUNNER_SYNTAX_REPAIR.md`).

---

## B. Safe text-replacement rules (any agent that edits files)

1. **Never put escape sequences in match targets.** A match/`TargetContent` string must
   contain **real newlines**, never the two-character literal `\n`, `\t`, `\r`. If your
   tool serialises the target as JSON, the editor matches against literal `\n` and will
   either fail or partial-match. Send raw multi-line text.
2. **Match must be unique and complete.** Include enough surrounding context that the
   target appears exactly once. If the target spans multiple statements, the replacement
   must also be a complete, balanced set of statements (no half-open template literals,
   no unclosed `(`/`{`).
3. **Smallest viable edit.** Prefer anchoring on a single line or a tiny, self-contained
   block. Do not wrap a 60-line block when a 3-line anchor will do.
4. **Balanced-delimiters check before saving.** The new text must keep `()`, `{}`, `[]`,
   and `` ` `` template literals balanced *on its own*. If unsure, append rather than
   splice.
5. **`node --check` (or equivalent) immediately after every edit** to a `.js` file. A
   failed check means revert the *edit*, not the whole file.

---

## C. Recovery rules

1. A `SyntaxError` after an edit is repaired **surgically** at the wound, not by
   `git restore` of a file that holds uncommitted work. Run
   `git diff --stat <file>` first — if it shows insertions you would lose, do **not**
   restore.
2. Confirm the known-good shape from `git show HEAD:<file>` before rewriting a region.
3. Re-run the frozen harness gates (`node --check …`, `node scripts/test-f2v-asset-picker-modal.js`)
   before declaring recovery complete.

---

## D. Standing validation gates (before any commit touching the extension)
```
node --check extension/f2v-flow-queue-runner.js
node --check extension/content-flow-dom.js
node scripts/test-f2v-asset-picker-modal.js
```
No live Google Flow run until these pass and the
`.ai/contracts/ANTIGRAVITY_UAT_CONTRACT.md` preflight passes.
