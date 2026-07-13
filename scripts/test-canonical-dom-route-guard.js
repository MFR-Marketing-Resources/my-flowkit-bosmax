/**
 * SEV-0 canonical-mode DOM-route guard test.
 *
 * ADR-007: the four canonical production modes generate API-first only
 * (backend _run_manual_job_via_generate -> make_video.start_generate). The
 * DOM-clicking generation lane is DEAD for them. The runtime-skew incident
 * (JOB_PROMPT_EMPTY inside content-flow-dom.js::executeFlowJob while WS 8101
 * was refused) proved that a stale runtime / queued message could still push a
 * canonical job into the dead lane. This test pins the guards that make that
 * impossible:
 *   1. content-flow-dom.js exposes flowKitCanonicalModeOf() and executeFlowJob
 *      refuses canonical modes with ERR_CANONICAL_MODE_LEGACY_DOM_ROUTE_FORBIDDEN.
 *   2. background.js handleExecuteFlowJob refuses canonical modes at the router.
 *   3. agent/api/flow.py fails closed for canonical/source-canonical payloads
 *      before the DOM dispatch.
 *   4. background + content build ids agree (handshake invariant).
 *
 * Pure Node + JSDOM, no credits, no browser, no network.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

const EXT_DIR = path.join(__dirname, '..', 'extension');
const CONTENT_PATH = path.join(EXT_DIR, 'content-flow-dom.js');
const BACKGROUND_PATH = path.join(EXT_DIR, 'background.js');
const FLOW_PY_PATH = path.join(__dirname, '..', 'agent', 'api', 'flow.py');

const CONTENT_TEXT = fs.readFileSync(CONTENT_PATH, 'utf8');
const BACKGROUND_TEXT = fs.readFileSync(BACKGROUND_PATH, 'utf8');
const FLOW_PY_TEXT = fs.readFileSync(FLOW_PY_PATH, 'utf8');

const ERR_CODE = 'ERR_CANONICAL_MODE_LEGACY_DOM_ROUTE_FORBIDDEN';

let passed = 0;
let failed = 0;
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`PASS ${name}`);
  } catch (err) {
    failed += 1;
    console.error(`FAIL ${name}\n  ${err && err.message ? err.message : err}`);
  }
}

// ── Bootstrap content-flow-dom.js in JSDOM (mirrors the frozen harness) ──────
function loadContentHooks() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'https://labs.google/fx/tools/flow',
    pretendToBeVisual: true,
    runScripts: 'outside-only',
  });
  const { window } = dom;
  window.__FLOWKIT_TEST_MODE__ = true;
  window.__FLOWKIT_ENABLE_TEST_HOOKS__ = true;
  window.fetch = global.fetch.bind(global);
  window.chrome = {
    runtime: {
      lastError: null,
      onMessage: { addListener() {}, removeListener() {} },
      sendMessage(_payload, callback) {
        if (typeof callback === 'function') callback({ ok: true });
      },
    },
  };
  window.eval(CONTENT_TEXT);
  const hooks = window.__FLOWKIT_TEST_HOOKS__;
  assert.ok(hooks, 'Expected __FLOWKIT_TEST_HOOKS__ to be defined in test mode');
  return hooks;
}

const hooks = loadContentHooks();
const canonicalModeOf = hooks.flowKitCanonicalModeOf;

test('flowKitCanonicalModeOf is exposed on test hooks', () => {
  assert.equal(typeof canonicalModeOf, 'function');
});

const CANONICAL_CASES = [
  [{ mode: 'IMG' }, 'IMG'],
  [{ mode: 'T2V' }, 'T2V'],
  [{ mode: 'I2V' }, 'I2V'],
  [{ mode: 'F2V' }, 'F2V'],
  [{ mode: 'HYBRID' }, 'HYBRID'],
  [{ mode: 'INGREDIENTS' }, 'INGREDIENTS'],
  [{ mode: 'FRAMES' }, 'FRAMES'],
  [{ mode: 'f2v' }, 'F2V'], // case-insensitive
  [{ mode: '  T2V  ' }, 'T2V'], // trimmed
  [{ source_mode: 'HYBRID' }, 'HYBRID'], // source_mode authority
  [{ data: { mode: 'F2V' } }, 'F2V'], // nested data.mode
  [{ data: { source_mode: 'INGREDIENTS' } }, 'INGREDIENTS'],
  // OR-logic: aliased non-canonical `mode` + canonical source_mode/nested must
  // STILL be caught (first-non-empty precedence would have missed these).
  [{ mode: 'SMOKE', source_mode: 'HYBRID' }, 'HYBRID'],
  [{ mode: 'DEBUG', data: { mode: 'F2V' } }, 'F2V'],
  [{ mode: 'x', source_mode: 'y', data: { source_mode: 'I2V' } }, 'I2V'],
];
for (const [job, expected] of CANONICAL_CASES) {
  test(`canonical job ${JSON.stringify(job)} -> ${expected}`, () => {
    assert.equal(canonicalModeOf(job), expected);
  });
}

const NON_CANONICAL_CASES = [
  { mode: 'SMOKE' },
  { mode: 'DEBUG' },
  { lane: 'F2V_PACKAGE_UPLOAD_ONLY' }, // lane alone is NOT the authority
  {},
  null,
  undefined,
  'not-an-object',
];
for (const job of NON_CANONICAL_CASES) {
  test(`non-canonical job ${JSON.stringify(job)} -> ''`, () => {
    assert.equal(canonicalModeOf(job), '');
  });
}

// ── Static guard presence (extension + backend) ─────────────────────────────
test('content-flow-dom executeFlowJob throws the canonical guard error', () => {
  assert.ok(
    CONTENT_TEXT.includes(ERR_CODE),
    'content-flow-dom.js must throw ' + ERR_CODE,
  );
  assert.ok(
    CONTENT_TEXT.includes('CANONICAL_MODE_DOM_ROUTE_BLOCKED'),
    'content-flow-dom.js must log the CANONICAL_MODE_DOM_ROUTE_BLOCKED stage',
  );
  // The guard must sit at the top of the executeFlowJob try, before the
  // JOB_PROMPT_EMPTY branch, so a canonical job is refused before any DOM work.
  const guardIdx = CONTENT_TEXT.indexOf('CANONICAL_MODE_DOM_ROUTE_BLOCKED');
  const execIdx = CONTENT_TEXT.indexOf('async function executeFlowJob');
  const promptEmptyIdx = CONTENT_TEXT.indexOf("throw new Error('JOB_PROMPT_EMPTY')");
  assert.ok(execIdx !== -1 && guardIdx > execIdx, 'guard must be inside executeFlowJob');
  assert.ok(guardIdx < promptEmptyIdx, 'guard must precede the JOB_PROMPT_EMPTY branch');
});

test('background handleExecuteFlowJob refuses canonical modes', () => {
  assert.ok(BACKGROUND_TEXT.includes(ERR_CODE), 'background.js must return ' + ERR_CODE);
  assert.ok(
    BACKGROUND_TEXT.includes('backgroundCanonicalModeOf'),
    'background.js must define/use backgroundCanonicalModeOf',
  );
  const guardIdx = BACKGROUND_TEXT.indexOf('job.smoke_test ? "" : backgroundCanonicalModeOf(job)');
  const fnIdx = BACKGROUND_TEXT.indexOf('async function handleExecuteFlowJob');
  const gfv2Idx = BACKGROUND_TEXT.indexOf('if (isGfv2Lane(job))');
  assert.ok(fnIdx !== -1 && guardIdx > fnIdx, 'guard must be inside handleExecuteFlowJob');
  assert.ok(guardIdx < gfv2Idx, 'guard must precede any lane branch');
});

test('backend flow.py fails closed before the DOM dispatch', () => {
  assert.ok(FLOW_PY_TEXT.includes(ERR_CODE), 'flow.py must raise ' + ERR_CODE);
  const guardIdx = FLOW_PY_TEXT.indexOf(ERR_CODE);
  const dispatchIdx = FLOW_PY_TEXT.indexOf('result = await client.execute_flow_job(body)');
  assert.ok(dispatchIdx !== -1, 'flow.py must still contain the legacy DOM dispatch');
  assert.ok(guardIdx < dispatchIdx, 'guard must precede client.execute_flow_job');
});

// ── Smoke-probe exemption (non-generating readiness check must pass through) ──
test('extension guards exempt smoke_test before the canonical check', () => {
  assert.ok(
    /job && job\.smoke_test \? '' : flowKitCanonicalModeOf\(job\)/.test(CONTENT_TEXT),
    'content executeFlowJob guard must exempt job.smoke_test',
  );
  assert.ok(
    /job && job\.smoke_test \? "" : backgroundCanonicalModeOf\(job\)/.test(BACKGROUND_TEXT),
    'background handleExecuteFlowJob guard must exempt job.smoke_test',
  );
});

// ── Backend chokepoint guard (flow_client.execute_flow_job) ──────────────────
test('flow_client.execute_flow_job guards the shared WS chokepoint', () => {
  const flowClient = fs.readFileSync(
    path.join(__dirname, '..', 'agent', 'services', 'flow_client.py'), 'utf8',
  );
  assert.ok(flowClient.includes(ERR_CODE), 'flow_client.py must return ' + ERR_CODE);
  assert.ok(
    flowClient.includes('_CANONICAL_DOM_FORBIDDEN_MODES'),
    'flow_client.py must define the canonical forbidden-mode set',
  );
  // The guard must precede the actual _send('EXECUTE_FLOW_JOB', ...) dispatch.
  const guardIdx = flowClient.indexOf('if (not _jd.get("smoke_test")) and _canonical:');
  const sendIdx = flowClient.indexOf('_send("EXECUTE_FLOW_JOB", {"job": job_data}, timeout=120)');
  assert.ok(guardIdx !== -1 && sendIdx !== -1 && guardIdx < sendIdx,
    'guard must precede the EXECUTE_FLOW_JOB dispatch in execute_flow_job');
});

// ── Build-id handshake invariant ────────────────────────────────────────────
test('content and background build ids agree (handshake invariant)', () => {
  const contentMatch = CONTENT_TEXT.match(/FLOW_KIT_DOM_BUILD_ID\s*=\s*'([^']+)'/);
  const bgMatch = BACKGROUND_TEXT.match(/const BUILD_ID\s*=\s*"([^"]+)"/);
  assert.ok(contentMatch, 'content-flow-dom.js FLOW_KIT_DOM_BUILD_ID not found');
  assert.ok(bgMatch, 'background.js BUILD_ID not found');
  assert.equal(
    contentMatch[1],
    bgMatch[1],
    `build ids must match: content=${contentMatch[1]} background=${bgMatch[1]}`,
  );
});

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
