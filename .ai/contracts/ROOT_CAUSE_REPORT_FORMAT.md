# ROOT CAUSE REPORT FORMAT

All debugging tasks must conclude with a report in this format.

## STATUS
- FIXED / PARTIAL / BLOCKED

## VERIFIED
- **Root cause:** [Clear explanation]
- **Evidence:** [Logs, traces, file/line citations]
- **Files changed:** [List of files]
- **Tests run:** [Validation steps]
- **Result:** [Pass/Fail]

## NOT VERIFIED
- **Remaining uncertainty:** [What is still unknown or unproven]

## REMOTE PROOF
- **Branch:** [Name]
- **Commit SHA:** [Full SHA if committed]
- **PR URL:** [Link if available]
- **Diff summary:** [Brief summary of changes]
- **Test command:** [Command used to verify]
- **Test result:** [Output snippet]

## RISKS
- **Regression risk:** [Potential impact on other areas]
- **Edge cases:** [Cases not covered by the fix]

## NEXT DECISION
- Merge / review / manual QA / provide missing logs
