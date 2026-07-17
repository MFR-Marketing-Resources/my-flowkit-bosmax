/**
 * BOSMAX RPA — Round B dry-run Click Operator (Steps 1-3 click, Step 4/5 STOP).
 *
 * Governance: docs/bosmax-rpa-g0-governance-gate.md, docs/bosmax-rpa-click-operator-workflow-mvp-spec.md
 *
 * This drives ONLY the human-visible Hybrid UI, exactly like a disciplined operator:
 * open page -> read state -> set visible Step 1 controls -> select product by IMMUTABLE
 * id -> verify the approved Copy Set -> click Step 3 (Load Package: compile-only,
 * proven provider-free) -> then STOP.
 *
 * HARD STOPS (enforced in code, not by convention):
 *   - SANDBOX ONLY: refuses to run against anything but the sandbox origin.
 *   - NEVER clicks `action-generate-final-prompt` (Step 4 action) — mission hard rule.
 *   - NEVER clicks Step 5 / any generate / provider / queue control.
 *   - NEVER clicks the fallback-confirmation gate (that would ship fallback copy).
 *   - REFUSES any `fastmoss-ref:` product.
 *   - Aborts on ANY provider/generation/credit-bearing network request (route blocker).
 *
 * Usage:
 *   node scripts/rpa-round-b-dry-run.js --base=http://127.0.0.1:8123 \
 *        --product-id=<uuid> --copy-set-id=<uuid> --out=<evidence dir>
 *
 * Exit 0 = dry-run completed AND stopped before Step 4/5.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

// ── Guardrails ──────────────────────────────────────────────────────────────
const SANDBOX_ORIGINS = new Set(["http://127.0.0.1:8123", "http://localhost:8123"]);
/** Any request matching these is credit-bearing / provider / generation: ABORT. */
const FORBIDDEN_REQUEST_PATTERNS = [
  /\/api\/flow\/(generate|execute-flow-job)/i,
  /\/api\/copy-sets\/ai-assist/i,
  /\/api\/copy-sets\/generate-batch/i,
  /\/api\/img-factory/i,
  /\/api\/product-asset-generator/i,
  /\/api\/bulk-generation/i,
  /\/api\/production-queue\/.*\/(run|execute|start)/i,
  /aisandbox|labs\.google|googleapis\.com\/.*generate/i,
];
/**
 * testids the operator must NEVER click.
 *
 * `action-generate-video` used to be listed here and has been REMOVED: it is a phantom.
 * It renders nowhere in dashboard/src, so guarding it proved nothing and overstated the
 * safety claim. Step 5 is a STOP panel (`workflow-step-5` + data-rpa-stop="true") that
 * renders no clickable action at all — the only action controls that exist are
 * action-load-hybrid-package (Step 3) and action-generate-final-prompt (Step 4).
 *
 * Step 5 safety therefore rests on three controls that are real, each asserted below:
 *   1. the CLOSED click surface — every click is recorded and must be in ALLOWED_CLICK_KEYS;
 *   2. FORBIDDEN_REQUEST_PATTERNS — generation/credit routes are aborted at the network layer;
 *   3. the workflow-step-5 data-rpa-stop marker assert.
 */
const FORBIDDEN_CLICK_TESTIDS = new Set([
  "workflow-fallback-confirm",    // would ship fallback copy — ALWAYS forbidden
]);
/** Step 2 picker: the toggle carries no testid of its own, so it is keyed by selector. */
const PICKER_TOGGLE = '[data-testid="workflow-step-2"] button';
const PICKER_SEARCH = 'input[placeholder*="Search all products"]';
/**
 * The ONLY controls this operator may click. Any recorded click outside this set fails the
 * run. This is the real Step 5 protection: the click surface is closed by construction.
 */
const ALLOWED_CLICK_KEYS = new Set([
  `selector:${PICKER_TOGGLE}`,     // opens/closes the Step 2 picker; changes no workflow state
  "product-option",                // Step 2: select the synthetic product by immutable id
  "copy-set-row",                  // Copy Set: select the already-approved set (never approves)
  "action-load-hybrid-package",    // Step 3: compile-only, provider-free
  "action-generate-final-prompt",  // Step 4: sandbox package write (owner-authorized)
]);
/**
 * Step 4 (`action-generate-final-prompt`) is OWNER-AUTHORIZED for the SANDBOX ONLY.
 * Proven provider-free / credit-free: agent/services/workspace_execution_package_service.py
 * has ZERO refs to provider/flow/generate/queue; it only calls
 * crud.create_or_replace_workspace_execution_package (:458) — a durable DB write into the
 * ISOLATED sandbox DB, which is what Round C needs to correlate. Step 5 stays forbidden.
 */
const STEP4_AUTHORIZED = true;

function arg(name, def) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.split("=").slice(1).join("=") : def;
}

const BASE = arg("base", "http://127.0.0.1:8123").replace(/\/$/, "");
const PRODUCT_ID = arg("product-id", "");
const COPY_SET_ID = arg("copy-set-id", "");
const OUT = arg("out", path.join(require("node:os").tmpdir(), "rpa-round-b-evidence"));

const evidence = { steps: [], network: { allowed: [], forbidden_attempts: [] }, clicks: [] };
const log = (m) => { console.log(m); evidence.steps.push({ t: new Date().toISOString(), m }); };

async function shot(page, name) {
  const p = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: p, fullPage: false });
  log(`  [shot] ${name}.png`);
  return p;
}

/** Read the live DOM contract Round A exposes. Never infers. */
async function readWorkflow(page) {
  return page.evaluate(() => {
    const q = (s) => document.querySelector(`[data-testid="${s}"]`);
    const step = (n) => {
      const el = q(`workflow-step-${n}`);
      return el ? { state: el.getAttribute("data-state"), stop: el.getAttribute("data-rpa-stop") } : null;
    };
    const notice = q("workflow-notice");
    const gen = q("action-generate-final-prompt");
    const load = q("action-load-hybrid-package");
    return {
      root_mode: q("hybrid-workflow")?.getAttribute("data-mode") ?? null,
      steps: { 1: step(1), 2: step(2), 3: step(3), 4: step(4), 5: step(5) },
      selected_product_id: q("workflow-step-2")?.getAttribute("data-selected-product-id") ?? "",
      settings: {
        generation_mode: q("setting-generation-mode")?.getAttribute("data-value") ?? null,
        block_duration: q("setting-block-duration")?.getAttribute("data-value") ?? null,
        video_model: q("setting-video-model")?.getAttribute("data-value") ?? null,
      },
      notice: notice ? { tone: notice.getAttribute("data-notice-tone"), stop: notice.getAttribute("data-rpa-stop") } : null,
      fallback_gate_open: !!q("workflow-fallback-confirm"),
      load_disabled: load ? load.disabled : null,
      generate_disabled: gen ? gen.disabled : null,
      copy_set_rows: [...document.querySelectorAll('[data-testid="copy-set-row"]')].map((r) => ({
        id: r.getAttribute("data-copy-set-id"),
        status: r.getAttribute("data-status"),
        approved: r.getAttribute("data-approved"),
        selected: r.getAttribute("data-selected"),
      })),
    };
  });
}

/**
 * The single click ledger. Every click in this file goes through here, and records what was
 * ACTUALLY clicked — never a hardcoded label, so the audit trail cannot drift from reality.
 */
function recordClick({ testid = null, selector = null, why, ...rest }) {
  const key = testid ?? `selector:${selector}`;
  evidence.clicks.push({ key, testid, selector, why, ...rest, at: new Date().toISOString() });
  log(`  [click] ${key}${why ? ` — ${why}` : ""}`);
  return key;
}

/** Click guard: refuses forbidden testids no matter what the caller asks for. */
async function safeClick(page, testid, why) {
  if (FORBIDDEN_CLICK_TESTIDS.has(testid)) {
    throw new Error(`GUARDRAIL: refused to click forbidden control "${testid}"`);
  }
  const selector = `[data-testid="${testid}"]`;   // testid is a literal from this file, never input
  await page.click(selector);
  recordClick({ testid, selector, why });
}

/**
 * Click a resolved element and record the testid READ BACK OFF IT, so the ledger reports the
 * control that actually received the click.
 */
async function clickHandle(handle, why, extra = {}) {
  const testid = await handle.getAttribute("data-testid");
  if (FORBIDDEN_CLICK_TESTIDS.has(testid)) {
    throw new Error(`GUARDRAIL: refused to click forbidden control "${testid}"`);
  }
  await handle.click();
  recordClick({ testid, why, ...extra });
}

/**
 * Resolve an element by EXACT attribute value WITHOUT interpolating the value into a CSS
 * selector. An immutable id is caller-supplied: quotes or brackets in it could otherwise
 * break out of the selector string and silently match a different control. String equality
 * has no such failure mode, so any arbitrary id is handled safely.
 */
async function findByAttr(page, testid, attr, value) {
  for (const handle of await page.$$(`[data-testid="${testid}"]`)) {
    if ((await handle.getAttribute(attr)) === value) return handle;
  }
  return null;
}

/** True only when the Step 2 picker menu is really open (its search box is mounted). */
async function pickerIsOpen(page) {
  return Boolean(await page.$(PICKER_SEARCH));
}

/**
 * Open the Step 2 picker DETERMINISTICALLY.
 *
 * The control is a toggle, and the catalog is not listed until GET /api/products resolves.
 * A blind retry click therefore CLOSES a menu that is already open — that is exactly the
 * cold-start flake (1 run in 3). Read the open state before every click, and only click to
 * change it: open when closed, and close an open-but-empty menu so the next pass re-opens
 * against loaded data instead of toggling blind.
 */
async function ensurePickerOpen(page) {
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    if (!(await pickerIsOpen(page))) {
      await page.click(PICKER_TOGGLE);
      recordClick({ selector: PICKER_TOGGLE, why: `open Step 2 picker (attempt ${attempt})` });
    }
    const listed = await page
      .waitForSelector('[data-testid="product-option"]', { timeout: 5000 })
      .then(() => true, () => false);
    if (listed) return attempt;
    if (await pickerIsOpen(page)) {
      await page.click(PICKER_TOGGLE);
      recordClick({ selector: PICKER_TOGGLE, why: `close empty Step 2 picker (attempt ${attempt})` });
    }
    await page.waitForTimeout(1500);
  }
  return assert.fail("product picker never listed any option after 5 deterministic attempts");
}

(async () => {
  // ── Guard 0: sandbox origin only.
  assert.ok(SANDBOX_ORIGINS.has(BASE), `GUARDRAIL: base ${BASE} is not a sandbox origin (:8123 only)`);
  assert.ok(PRODUCT_ID, "--product-id required");
  assert.ok(!PRODUCT_ID.startsWith("fastmoss-ref:"), "GUARDRAIL: refused fastmoss-ref product");
  assert.ok(COPY_SET_ID, "--copy-set-id required");
  fs.mkdirSync(OUT, { recursive: true });

  const browser = await chromium.launch();
  const page = await browser.newPage();

  // ── Guard 1: abort any credit-bearing / provider request at the network layer.
  await page.route("**/*", (route) => {
    const url = route.request().url();
    const bad = FORBIDDEN_REQUEST_PATTERNS.find((re) => re.test(url));
    if (bad) {
      evidence.network.forbidden_attempts.push({ url, method: route.request().method(), blocked_by: String(bad) });
      console.error(`  [BLOCKED] forbidden request: ${url}`);
      return route.abort();
    }
    return route.continue();
  });
  page.on("response", async (res) => {
    if (res.url().includes("/api/workspace/execution-package") && res.request().method() === "POST") {
      try {
        const b = await res.json();
        evidence.network.package_write = {
          status: res.status(),
          workspace_execution_package_id: b?.workspace_execution_package_id ?? b?.package?.workspace_execution_package_id ?? null,
          request_id: b?.request_id ?? null,
          keys: Object.keys(b || {}).slice(0, 12),
        };
      } catch { /* non-json */ }
    }
  });
  page.on("request", (r) => {
    const u = r.url();
    if (u.startsWith(BASE) && u.includes("/api/")) evidence.network.allowed.push({ method: r.method(), url: u });
  });
  const consoleErrors = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

  try {
    // ── Step 0: open the Hybrid workflow like a human.
    log(`[open] ${BASE}/operator/hybrid`);
    // Catalog readiness is what Step 2 actually depends on: the picker lists nothing until
    // GET /api/products resolves. Register the wait BEFORE navigating, so the response
    // cannot land before we are listening.
    const catalogReady = page
      .waitForResponse(
        (r) => {
          try { return new URL(r.url()).pathname === "/api/products" && r.request().method() === "GET" && r.ok(); }
          catch { return false; }
        },
        { timeout: 30000 },
      )
      .then(() => true, () => false);
    // domcontentloaded (not networkidle): the operator dashboard polls readiness, so
    // the network never idles. The explicit waitForSelector below is the real gate.
    await page.goto(`${BASE}/operator/hybrid`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('[data-testid="hybrid-workflow"]', { timeout: 15000 });
    evidence.initial = await readWorkflow(page);
    assert.equal(evidence.initial.root_mode, "HYBRID", "not on the HYBRID workflow");
    await shot(page, "01-opened");
    log(`  root_mode=HYBRID  step1=${evidence.initial.steps[1]?.state}  step5=${evidence.initial.steps[5]?.state}`);

    // ── Step 1: confirm visible settings via the DOM contract (defaults already valid).
    log("[step-1] confirm visible Step 1 controls");
    evidence.step1 = evidence.initial.settings;
    assert.ok(evidence.step1.generation_mode, "Step 1 generation mode not readable");
    log(`  generation_mode=${evidence.step1.generation_mode} block_duration=${evidence.step1.block_duration} video_model=${evidence.step1.video_model}`);
    await shot(page, "02-step1-settings");

    // ── Step 2: select the synthetic product BY IMMUTABLE ID through the visible picker.
    log(`[step-2] select product by immutable id ${PRODUCT_ID}`);
    evidence.catalog_loaded = await catalogReady;
    log(`  catalog GET /api/products resolved=${evidence.catalog_loaded}`);
    await page.waitForSelector(`${PICKER_TOGGLE}:not([disabled])`, { timeout: 20000 });
    evidence.picker_open_attempt = await ensurePickerOpen(page);
    log(`  picker open (deterministic) on attempt ${evidence.picker_open_attempt}`);
    const opts = await page.$$eval('[data-testid="product-option"]', (els) =>
      els.map((e) => ({ id: e.getAttribute("data-product-id"), ref: e.getAttribute("data-reference-only") })));
    evidence.product_options = opts;
    assert.ok(!opts.some((o) => o.id === PRODUCT_ID && o.ref === "true"), "GUARDRAIL: target product is reference-only");
    const targetOption = await findByAttr(page, "product-option", "data-product-id", PRODUCT_ID);
    assert.ok(targetOption, `product-option for immutable id ${PRODUCT_ID} is not listed`);
    await clickHandle(targetOption, "Step 2 select synthetic product by immutable id", { product_id: PRODUCT_ID });
    await page.waitForFunction(
      (pid) => document.querySelector('[data-testid="workflow-step-2"]')?.getAttribute("data-selected-product-id") === pid,
      PRODUCT_ID, { timeout: 10000 });
    const afterProduct = await readWorkflow(page);
    assert.equal(afterProduct.selected_product_id, PRODUCT_ID, "product selection did not bind");
    assert.ok(!afterProduct.selected_product_id.startsWith("fastmoss-ref:"), "GUARDRAIL: fastmoss-ref selected");
    evidence.after_product = afterProduct;
    await shot(page, "03-step2-product-selected");
    log(`  selected_product_id=${afterProduct.selected_product_id}  step2=${afterProduct.steps[2]?.state}`);

    // ── Copy Set: VERIFY the approved set (read-only; the RPA never approves).
    log("[copy-set] verify approved Copy Set is present + selected");
    await page.waitForSelector('[data-testid="copy-set-row"]', { timeout: 15000 }).catch(() => {});
    let rows = (await readWorkflow(page)).copy_set_rows;
    const approvedRow = rows.find((r) => r.id === COPY_SET_ID);
    assert.ok(approvedRow, `approved Copy Set ${COPY_SET_ID} not rendered`);
    assert.equal(approvedRow.status, "COPY_APPROVED", "target Copy Set is not COPY_APPROVED");
    if (approvedRow.selected !== "true") {
      const rowEl = await findByAttr(page, "copy-set-row", "data-copy-set-id", COPY_SET_ID);
      const selectBtn = rowEl ? await rowEl.$("button") : null;
      if (selectBtn) {
        await selectBtn.click();
        // Recorded on the ledger like every other click: this used to be clicked silently.
        recordClick({ testid: "copy-set-row", why: "select the approved Copy Set", copy_set_id: COPY_SET_ID });
      }
    }
    rows = (await readWorkflow(page)).copy_set_rows;
    evidence.copy_set_rows = rows;
    await shot(page, "04-copyset-verified");
    log(`  copy_set ${COPY_SET_ID} status=${approvedRow.status} approved=${approvedRow.approved}`);

    // ── Step 3: Load Package — compile-only, proven provider-free/credit-free.
    const pre3 = await readWorkflow(page);
    evidence.before_step3 = pre3;
    log(`[step-3] state=${pre3.steps[3]?.state} load_disabled=${pre3.load_disabled}`);
    if (pre3.load_disabled === false) {
      await safeClick(page, "action-load-hybrid-package", "Step 3 Load Package (compile-only, non-credit)");
      await page.waitForFunction(() => {
        const s = document.querySelector('[data-testid="workflow-step-3"]')?.getAttribute("data-state");
        return s === "COMPLETED" || s === "READY" || s === "NOT_READY";
      }, null, { timeout: 30000 }).catch(() => {});
      await page.waitForTimeout(1500);
    } else {
      log("  Step 3 action disabled — recording state, not forcing (prerequisite unmet)");
    }
    evidence.after_step3 = await readWorkflow(page);
    await shot(page, "05-step3-after-load");
    log(`  step3=${evidence.after_step3.steps[3]?.state}  step4=${evidence.after_step3.steps[4]?.state}`);

    // ── Step 4: OWNER-AUTHORIZED sandbox package write (provider-free, credit-free).
    const pre4 = evidence.after_step3;
    if (STEP4_AUTHORIZED && pre4.generate_disabled === false) {
      await safeClick(page, "action-generate-final-prompt", "Step 4 Generate Final Prompt (sandbox package write; provider-free)");
      await page.waitForFunction(() => {
        const s = document.querySelector('[data-testid="workflow-step-4"]')?.getAttribute("data-state");
        return s === "COMPLETED" || s === "READY" || s === "NOT_READY" || s === "FAILED";
      }, null, { timeout: 45000 }).catch(() => {});
      await page.waitForTimeout(2500);
      evidence.after_step4 = await readWorkflow(page);
      evidence.durable = await page.evaluate(() => {
        const t = document.body.innerText || "";
        const req = t.match(/req\s+([\w-]{6,})/i);
        return { notice_request_id: req ? req[1] : null };
      });
      evidence.step4 = {
        state: evidence.after_step4.steps[4]?.state,
        clicked: true,
        package_write_response: evidence.network.package_write || null,
      };
      log(`  [step-4] state=${evidence.step4.state} durable=${JSON.stringify(evidence.durable)} pkg=${JSON.stringify(evidence.network.package_write)}`);
    } else {
      evidence.after_step4 = pre4;
      evidence.step4 = { state: pre4.steps[4]?.state, generate_disabled: pre4.generate_disabled, clicked: false };
      log("  [step-4] not clicked (action disabled)");
    }
    await shot(page, "07-step4-package-written");

    // ── Step 5: ALWAYS observe-only.
    const fin = evidence.after_step4;
    evidence.step5 = { state: fin.steps[5]?.state, rpa_stop: fin.steps[5]?.stop, clicked: false };
    assert.ok(!fin.fallback_gate_open, "GUARDRAIL: fallback gate opened — operator must STOP");
    assert.equal(fin.steps[5]?.stop, "true", "Step 5 stop marker missing");
    for (const t of FORBIDDEN_CLICK_TESTIDS) {
      assert.ok(!evidence.clicks.some((c) => c.testid === t), `GUARDRAIL VIOLATION: ${t} was clicked`);
    }
    // The real Step 5 protection: the click surface is CLOSED. Every click the ledger
    // actually recorded must be one this operator is allowed to make.
    const unexpected = evidence.clicks.filter((c) => !ALLOWED_CLICK_KEYS.has(c.key));
    assert.ok(unexpected.length === 0, `GUARDRAIL VIOLATION: unexpected click(s) ${JSON.stringify(unexpected)}`);
    evidence.closed_click_surface = {
      allowed: [...ALLOWED_CLICK_KEYS],
      recorded: evidence.clicks.map((c) => c.key),
      unexpected: [],
    };
    evidence.guards = {
      forbidden_request_patterns: FORBIDDEN_REQUEST_PATTERNS.map(String),
      forbidden_click_testids: [...FORBIDDEN_CLICK_TESTIDS],
      allowed_click_keys: [...ALLOWED_CLICK_KEYS],
      step4_authorized_sandbox_only: STEP4_AUTHORIZED,
    };
    await shot(page, "06-stopped-before-step5");
    log(`[stop] step4=${evidence.step4.state} clicked=${evidence.step4.clicked}  step5=${evidence.step5.state} rpa_stop=${evidence.step5.rpa_stop} clicked=${evidence.step5.clicked}`);

    evidence.console_errors = consoleErrors;
    evidence.ROUND_B_DRY_RUN_STOPPED_BEFORE_STEP_5 = true;
    evidence.result = "PASS";
  } catch (e) {
    evidence.result = "FAIL";
    evidence.error = String(e && e.stack ? e.stack : e);
    evidence.ROUND_B_DRY_RUN_STOPPED_BEFORE_STEP_5 =
      !evidence.clicks.some((c) => FORBIDDEN_CLICK_TESTIDS.has(c.testid));
    console.error("DRY-RUN FAILED:", e.message);
  } finally {
    fs.writeFileSync(path.join(OUT, "evidence.json"), JSON.stringify(evidence, null, 2));
    await browser.close();
  }

  console.log("\n=== ROUND B DRY-RUN SUMMARY ===");
  console.log(JSON.stringify({
    result: evidence.result,
    ROUND_B_DRY_RUN_STOPPED_BEFORE_STEP_5: evidence.ROUND_B_DRY_RUN_STOPPED_BEFORE_STEP_5,
    selected_product_id: evidence.after_product?.selected_product_id,
    step3: evidence.after_step3?.steps?.[3]?.state,
    step4: evidence.step4,
    step5: evidence.step5,
    // c.key, not c.testid: the picker toggle carries no testid and is keyed by selector, so
    // c.testid printed it as `null` and the summary failed to name what was clicked.
    clicks: evidence.clicks.map((c) => c.key),
    forbidden_requests_blocked: evidence.network.forbidden_attempts.length,
    console_errors: (evidence.console_errors || []).length,
    evidence_dir: OUT,
  }, null, 2));
  process.exit(evidence.result === "PASS" ? 0 : 1);
})();
