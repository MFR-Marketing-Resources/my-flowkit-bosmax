# BOSMAX Engineering Lockdown

This repository is under strict surgical engineering control.

The goal is to prevent recurring regressions, accidental rewrites, formatter noise, scope creep, stale issue leakage, and AI-driven “fix one thing, break three things” behavior.

## 1. Prime Directive

Do not fix what is not broken.

A coding agent may only change code directly related to a proven defect.

Allowed:

```text
One defect → one minimal patch → one focused test → one evidence report
```

Forbidden:

```text
One defect → broad rewrite → refactor → reformat → architecture change → unrelated cleanup
```

## 2. Evidence Required Before Patch

Before changing code, the agent must identify:

```text
- exact symptom
- exact failing stage
- exact file/function involved
- expected behavior
- actual behavior
- evidence source
```

No evidence = no patch.

Acceptable evidence:

```text
- failing test
- runtime log
- browser console error
- service worker error
- network payload
- backend response
- bind-check diagnostic
- stack trace
- exact diff regression
```

Not acceptable:

```text
- "looks wrong"
- "probably"
- "should improve"
- "I noticed another issue"
- "while I am here"
- "cleanup"
- "refactor for clarity"
```

## 3. Surgical Patch Rule

Patch the smallest possible area.

Required behavior:

```text
- edit only the exact file(s) needed
- edit only the exact function/block needed
- preserve existing behavior outside the defect
- preserve approved copy, prompts, schemas, payloads, UI behavior, and runtime contracts
```

Forbidden behavior:

```text
- whole-file rewrite
- opportunistic refactor
- import reordering unless required
- formatter-only changes
- renaming unrelated variables
- moving logic for style
- changing UI copy without request
- changing payload shape unless defect proves it
- touching old verified fixes without regression evidence
```

## 4. No Formatter Noise

Formatting changes are forbidden unless the target line must be edited for the fix.

If formatter noise appears, the agent must remove it before commit.

Every patch report must include:

```bash
git diff --name-only
git diff --stat
git diff --numstat
```

If unrelated files appear, stop and revert those changes.

## 5. Scope Lock

Each task must declare scope before patching:

```text
Scope:
- files allowed:
- functions allowed:
- behavior allowed to change:
- behavior forbidden to change:
```

The agent may not exceed scope.

If the fix requires wider scope, stop and ask.

## 6. Closed Issue Protection

Once an issue is verified fixed, it becomes locked.

Do not modify that area again unless:

```text
- a new failing test proves regression
- runtime evidence proves regression
- user explicitly reopens that issue
```

Closed issues must not be reopened casually.

## 7. Runtime Truth Hierarchy

Truth priority:

```text
1. Runtime evidence
2. Tests
3. Code inspection
4. Agent reasoning
5. Assumption
```

Agents must not claim “fixed”, “working”, “proven”, “ready”, “safe”, or “done” unless supported by the required evidence for that layer.

Allowed wording:

```text
code-level fix applied
build passed
runtime not verified
dashboard payload verified
extension bind verified
end-to-end not verified
```

Forbidden wording:

```text
fully fixed
proven
done
ready to merge
safe
```

unless the required runtime layer is actually verified.

## 8. Layer Separation

Do not mix unrelated layers in one patch.

Layers:

```text
- dashboard UI
- dashboard payload builder
- backend API
- local agent
- Chrome extension background/service worker
- content script / DOM executor
- Google Flow page binding
- aisandbox request body
- retrieval/save pipeline
- tests/fixtures
- docs
```

One patch should normally touch one layer only.

If multiple layers are required, use separate commits and explain dependency.

## 9. Credit Safety

No agent may trigger credit-spending Google Flow generation without explicit user approval.

Allowed without approval:

```text
- dashboard payload interception
- bind-check
- extension self-test
- local-agent status
- dry-run
- browser console/network inspection
- service worker inspection
```

Forbidden without approval:

```text
- live generation
- approval/render click
- anything that consumes Google Flow credits
```

## 10. BOSMAX Runtime Debugging Rule

When debugging BOSMAX/ref_flowkit runtime, the trigger must come from the BOSMAX system path unless explicitly stated otherwise:

```text
BOSMAX dashboard/system UI
→ /api/flow/generate
→ backend/local-agent
→ Chrome extension
→ bound Google Flow editor
```

Do not manually generate inside Google Flow and call that a system test.

Every runtime report must identify the failing stage:

```text
A. dashboard did not send correct payload
B. backend rejected payload
C. backend did not call local-agent/extension
D. extension did not receive command
E. extension selected wrong Flow tab
F. Flow editor bound but DOM executor failed
G. Google Flow page crashed / project became broken
H. aisandbox request malformed
I. approval/render credit gate reached
J. video generated but retrieval/save failed
```

## 11. Broken Flow Project Recovery Rule

If a Flow project/editor shows:

```text
Something went wrong
BROKEN_EDITOR_PAGE
TARGET_PROJECT_BROKEN
FLOW_PROJECT_EDITOR_NOT_READY
ABORT_FLOW_COMPOSER_NOT_READY
```

Do not patch dashboard payload or extension logic automatically.

First classify:

```text
- stale/broken Flow project
- wrong tab selection
- extension disconnect
- DOM executor failure
- backend payload failure
```

If the project itself is broken, the system must stop reusing it and recover to a fresh healthy Flow editor before live generation.

## 12. Required Report After Every Patch

Every patch report must include:

```text
Task:
Root cause:
Scope:
Files changed:
Diff:
Tests:
Runtime:
Regression protection:
Risk:
Rollback:
Decision:
```

Template:

```text
Task:
Root cause:
Scope:
Files changed:
- ...

Diff:
- git diff --name-only:
- git diff --stat:
- git diff --numstat:

Patch:
- ...

Tests:
- command:
- result:

Runtime:
- verified:
- not verified:

Regression protection:
- what old behavior was protected:

Risk:
- ...

Rollback:
- ...

Decision:
- safe to continue? yes/no
- safe to merge? yes/no
```

## 13. Stop Conditions

Agent must stop immediately if:

```text
- more than expected files are changed
- formatter noise appears
- target file has unexpected architecture mismatch
- fix requires unrelated refactor
- runtime evidence contradicts assumption
- Flow generation may spend credits
- project/editor is broken before system trigger
- user-approved scope is no longer enough
```

Stop means:

```text
- do not patch further
- do not invent workaround
- report exact blocker
```

## 14. Commit Discipline

Commits must be atomic.

Good:

```text
fix(dashboard): map F2V start frame into image_media_ids
fix(dashboard): enforce I2V min-2 guard
fix(extension): prevent duplicate content-script injection
docs(engineering): add lockdown rules
```

Bad:

```text
fix stuff
update files
runtime fixes
cleanup
refactor flow
```

Each commit must contain only one logical change.

## 15. Pull Request Discipline

A PR must state:

```text
- exact defect fixed
- files changed
- tests run
- runtime evidence
- unverified layers
- merge risk
```

Audit-only PRs must be labeled:

```text
AUDIT ONLY — NOT A MERGE CANDIDATE
```

## 16. Forbidden AI Behavior

The following are banned:

```text
- “while I was here” changes
- broad cleanup
- silent rewrite
- hidden formatter run
- changing old fixed logic
- editing generated-looking files casually
- touching unrelated modes
- claiming runtime proof from code inspection
- using stale previous runtime proof as current proof
- bypassing user credit approval
- asking user for screenshots/log copy-paste before trying available browser/devtools/local-agent tools
```

## 17. Default Agent Workflow

Every task must follow:

```text
1. Read current state
2. Identify exact failing layer
3. Produce diagnosis
4. Propose minimal patch
5. Patch only approved scope
6. Run focused test
7. Report evidence
8. Stop
```

The agent must not continue into additional fixes unless explicitly asked.

## 18. Final Rule

If unsure, do less.

A small incomplete honest patch is better than a large confident rewrite that creates regressions.
