# Testing Instructions

Applies to scripts, tests, and harness work.

- Local harness comes before live UAT.
- Preferred order:
  - static checks
  - helper and unit tests
  - DOM fixture tests
  - Playwright persistent-context extension tests
  - live smoke only after local proof
- Do not remove existing tests to make a change pass.
- Do not replace harness proof with screenshots.
