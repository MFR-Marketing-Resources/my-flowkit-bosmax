# DEBUG CONTRACT

This contract is mandatory for all debugging tasks. No code changes are permitted until the evidence and root cause are established.

## Mandatory Debugging Flow

1. **REPRO:**
   - Create a minimal reproduction case.
   - Run tests or manual scripts to confirm the failure.
   - Capture exact error logs/output.

2. **EVIDENCE:**
   - Cite exact file paths and line numbers.
   - Show the specific log entry or stack trace that proves the failure.
   - If evidence is insufficient, state "NOT VERIFIED".

3. **ROOT CAUSE:**
   - Explain *why* the failure is happening.
   - Map the failure path from trigger to error.
   - Do not guess; prove it with the code's logic.

4. **MINIMAL PATCH:**
   - Design the smallest safe patch possible.
   - Avoid refactoring or unrelated code changes.
   - Ensure the patch only addresses the verified root cause.

5. **VALIDATION:**
   - Verify the fix with the same repro steps.
   - Run existing test suites to ensure no regressions.
   - Provide "GIT PROOF" of the fix.

6. **GIT PROOF:**
   - Follow requirements in [.ai/contracts/GIT_PROOF_REQUIREMENTS.md](file:///c:/Users/USER/Desktop/_ref_flowkit/.ai/contracts/GIT_PROOF_REQUIREMENTS.md).

## Hard Rules
- **Do not code first.** Establish evidence first.
- **Do not guess.** Every claim must cite exact data.
- **Do not rewrite unrelated code.** Preserve the surrounding logic.
- **Do not mark fixed without validation proof.** Evidence of success is required.
- **Apply the smallest safe patch only.**
