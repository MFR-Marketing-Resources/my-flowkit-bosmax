# Test Pyramid

## Required Order
1. Static checks
2. Helper and unit tests
3. DOM fixture tests
4. Playwright persistent-context extension harness
5. Live Google Flow smoke only after local proof
6. Final one-shot Antigravity UAT only after preflight

## Policy
- JSDOM is acceptable for pure helpers and fixture assertions.
- Playwright persistent context is the primary integration harness.
- Live Google Flow is not the primary debug environment.
