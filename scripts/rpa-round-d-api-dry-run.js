#!/usr/bin/env node
/**
 * BOSMAX RPA — Round D-API: Production Queue dry-run operator (SANDBOX ONLY).
 *
 * Owner-authorized as D-API only (G0 §16.5). Round D is NOT a click operator:
 * `ProductionQueuePage.tsx` exposes ZERO data-testid, so there is nothing for a UI
 * operator to drive (G0 blocker B8). This harness therefore drives the QUEUE'S OWN
 * HTTP API — the same endpoints the page calls — and never touches the DOM.
 *
 * What it proves, end to end, against an isolated sandbox:
 *   Step 4 WEP -> bridge -> WGP -> approve -> enqueue -> DRY-RUN -> report
 * and that the dry run neither fired nor burned credits.
 *
 * The safety basis is three things that are real, not asserted:
 *   1. SANDBOX_ORIGINS  — refuses any base that is not the :8123 sandbox.
 *   2. FORBIDDEN_REQUEST_PATTERNS — provider/generation/live routes are refused
 *      before the request is made, not audited after.
 *   3. assertNoLiveBurn() — refuses ANY body carrying confirm_live_credit_burn=true,
 *      which is the single door to `make_video.start_generate`
 *      (agent/services/production_queue_service.py:341-344, :475-482). It is forbidden
 *      in EVERY environment, so the guard is unconditional — there is no flag to relax.
 *
 * "Dry-run" here means NO FIRING and NO CREDITS. It does NOT mean read-only: the dry
 * branch commits config_json.last_dry_run_report (production_queue_service.py:336).
 * Expected sandbox writes are declared in EXPECTED_SANDBOX_DELTAS below and proven by
 * the caller's before/after snapshots — never discovered after the fact.
 *
 * Usage:
 *   node scripts/rpa-round-d-api-dry-run.js --base=http://127.0.0.1:8123 \
 *     --product-id=<synthetic> --copy-set-id=<approved> --out=<evidence-dir> [--mode=F2V]
 */

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

// ── Guardrails ──────────────────────────────────────────────────────────────
/** The ONLY origins this operator may talk to. */
const SANDBOX_ORIGINS = new Set(["http://127.0.0.1:8123", "http://localhost:8123"]);

/** Any request matching these is provider / generation / credit-bearing / live: REFUSE. */
const FORBIDDEN_REQUEST_PATTERNS = [
  /\/api\/flow\/(generate|execute-flow-job)/i,
  /\/api\/copy-sets\/ai-assist/i,
  /\/api\/copy-sets\/generate-batch/i,
  /\/api\/img-factory/i,
  /\/api\/product-asset-generator/i,
  /\/api\/bulk-generation/i,
  /aisandbox|labs\.google|googleapis\.com\/.*generate/i,
];

/**
 * The ONLY endpoints this operator may call, in order. Anything else is a guardrail
 * failure — the request surface is closed by construction, exactly like Round B's
 * closed click surface.
 */
const ALLOWED_CALL_KEYS = new Set([
  "GET /api/local-agent/version-proof",
  "POST /api/workspace/execution-package",
  "POST /api/workspace/generation-packages/from-execution-package",
  "POST /api/workspace/generation-packages/approve",
  "POST /api/workspace/production-queue",
  "POST /api/workspace/production-queue/{run_id}/start",
  "GET /api/workspace/production-queue/{run_id}",
  "GET /api/workspace/production-queue",
]);

/**
 * Declared BEFORE the run (G0 §16.3): a dry run is allowed to write exactly these.
 * The caller proves the observed sandbox deltas match. Anything else = stop.
 */
const EXPECTED_SANDBOX_DELTAS = {
  workspace_execution_package: 1,   // Step 4 mints the WEP
  workspace_generation_package: 1,  // the bridge mints the queue's unit of work
  production_run: 1,                // enqueue creates the run, always dry_run=1
  // plus: production_run.config_json gains last_dry_run_report (an UPDATE, not a row)
  // plus: the WGP's production_status walks NONE -> APPROVED -> QUEUED
};

/** Tables that must NOT move: any delta here means something fired. */
const FORBIDDEN_DELTA_TABLES = [
  "request", "request_stage_event", "request_telemetry",
  "video_production_job", "video_job_side_effect", "video",
  "generation_result", "generated_artifact",
  "batch_generation_run", "batch_queue_event",
  "bulk_generation_run", "bulk_generation_item", "copy_generation_batch",
];

function arg(name, def) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.split("=").slice(1).join("=") : def;
}

const BASE = arg("base", "");
const PRODUCT_ID = arg("product-id", "");
const COPY_SET_ID = arg("copy-set-id", "");
const MODE = arg("mode", "F2V");
const OUT = arg("out", path.join(require("node:os").tmpdir(), "rpa-round-d-evidence"));

const evidence = {
  round: "D-API",
  steps: [],
  calls: [],
  network: { allowed: [], refused: [] },
  guards: {},
};
const log = (m) => { console.log(m); evidence.steps.push({ t: new Date().toISOString(), m }); };

/** Refuses to even construct a live-burn request. Unconditional by design. */
function assertNoLiveBurn(body) {
  const raw = typeof body === "string" ? body : JSON.stringify(body ?? {});
  if (/"confirm_live_credit_burn"\s*:\s*true/i.test(raw)) {
    throw new Error("GUARDRAIL: confirm_live_credit_burn=true is forbidden in every environment");
  }
}

/**
 * The single HTTP door. Every call is keyed, checked against the closed surface,
 * screened against the forbidden patterns, and recorded truthfully.
 */
async function call(method, endpoint, { body, query, key } = {}) {
  const url = new URL(BASE + endpoint);
  for (const [k, v] of Object.entries(query || {})) url.searchParams.set(k, v);
  const full = url.toString();

  const bad = FORBIDDEN_REQUEST_PATTERNS.find((re) => re.test(full));
  if (bad) {
    evidence.network.refused.push({ url: full, blocked_by: String(bad) });
    throw new Error(`GUARDRAIL: refused forbidden request ${full}`);
  }
  if (!full.startsWith(BASE)) {
    throw new Error(`GUARDRAIL: refused off-sandbox request ${full}`);
  }
  assertNoLiveBurn(body);

  const callKey = `${method} ${key || endpoint}`;
  if (!ALLOWED_CALL_KEYS.has(callKey)) {
    throw new Error(`GUARDRAIL: ${callKey} is not on the closed call surface`);
  }

  const res = await fetch(full, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let payload = null;
  try { payload = await res.json(); } catch { /* non-json */ }

  evidence.network.allowed.push({ method, url: full, status: res.status });
  evidence.calls.push({ key: callKey, status: res.status, at: new Date().toISOString() });
  return { status: res.status, body: payload };
}

(async () => {
  // ── Guard 0: sandbox only, synthetic product only.
  assert.ok(SANDBOX_ORIGINS.has(BASE), `GUARDRAIL: base ${BASE} is not a sandbox origin (:8123 only)`);
  assert.ok(PRODUCT_ID, "--product-id required");
  assert.ok(!PRODUCT_ID.startsWith("fastmoss-ref:"), "GUARDRAIL: refused fastmoss-ref product");
  assert.ok(COPY_SET_ID, "--copy-set-id required");
  fs.mkdirSync(OUT, { recursive: true });

  evidence.guards = {
    sandbox_origins: [...SANDBOX_ORIGINS],
    forbidden_request_patterns: FORBIDDEN_REQUEST_PATTERNS.map(String),
    allowed_call_keys: [...ALLOWED_CALL_KEYS],
    expected_sandbox_deltas: EXPECTED_SANDBOX_DELTAS,
    forbidden_delta_tables: FORBIDDEN_DELTA_TABLES,
    confirm_live_credit_burn_sent: false,
  };

  try {
    // ── Provenance: prove which code the sandbox is serving.
    const vp = await call("GET", "/api/local-agent/version-proof");
    evidence.sandbox_version_proof = vp.body;
    log(`[provenance] git_head=${vp.body?.git_head} branch=${vp.body?.git_branch} stale=${vp.body?.source_stale_since_start}`);

    // ── Step 4: mint the WEP (proven provider-free in Rounds B/C).
    log(`[wep] POST /api/workspace/execution-package  product=${PRODUCT_ID} mode=${MODE}`);
    const wepRes = await call("POST", "/api/workspace/execution-package", {
      body: { product_id: PRODUCT_ID, mode: MODE, copy_set_id: COPY_SET_ID },
    });
    assert.equal(wepRes.status, 200, `WEP creation failed: ${JSON.stringify(wepRes.body)}`);
    const WEP_ID = wepRes.body?.workspace_execution_package_id;
    assert.ok(WEP_ID, "no workspace_execution_package_id returned");
    evidence.wep = { id: WEP_ID, mode: wepRes.body?.mode, product_id: wepRes.body?.product_id };
    log(`  WEP_ID=${WEP_ID}`);

    // ── Bridge WEP -> WGP. This is the link Rounds A-C never exercised: Step 4 mints
    //    a WEP, but the queue's unit of work is a workspace_generation_package.
    log(`[bridge] POST /api/workspace/generation-packages/from-execution-package`);
    const bridgeRes = await call("POST", "/api/workspace/generation-packages/from-execution-package", {
      query: { workspace_execution_package_id: WEP_ID, mode: MODE },
    });
    assert.equal(bridgeRes.status, 200, `bridge failed: ${JSON.stringify(bridgeRes.body)}`);
    const WGP_ID = bridgeRes.body?.workspace_generation_package_id;
    assert.ok(WGP_ID, "no workspace_generation_package_id returned");
    evidence.wgp = {
      id: WGP_ID,
      status: bridgeRes.body?.status,
      production_status: bridgeRes.body?.production_status,
      linked_wep: bridgeRes.body?.workspace_execution_package_id,
      blockers: bridgeRes.body?.blockers_json ?? bridgeRes.body?.blockers ?? null,
    };
    log(`  WGP_ID=${WGP_ID} status=${evidence.wgp.status} linked_wep=${evidence.wgp.linked_wep}`);
    // status is BLOCKED when blockers exist, else READY_MANUAL
    // (workspace_generation_package_service.py:271). Only the latter is approvable.
    assert.ok(
      ["READY_MANUAL", "READY_DOM_STAGED"].includes(evidence.wgp.status),
      `WGP not approvable: status=${evidence.wgp.status} blockers=${JSON.stringify(evidence.wgp.blockers)}`,
    );
    assert.equal(evidence.wgp.linked_wep, WEP_ID, "WGP does not link back to the WEP");

    // ── Approve the WGP (prompt-side gate; no execution).
    log(`[approve] POST /api/workspace/generation-packages/approve`);
    const apprRes = await call("POST", "/api/workspace/generation-packages/approve", {
      body: { package_ids: [WGP_ID] },
    });
    assert.equal(apprRes.status, 200, `approve failed: ${JSON.stringify(apprRes.body)}`);
    evidence.approve = apprRes.body;
    log(`  approve -> ${JSON.stringify(apprRes.body).slice(0, 160)}`);

    // ── Enqueue into a NEW production run. Always born dry_run=1
    //    (production_queue_service.py:164) — nothing fires here.
    log(`[enqueue] POST /api/workspace/production-queue`);
    const enqRes = await call("POST", "/api/workspace/production-queue", {
      body: { package_ids: [WGP_ID], model: "Veo 3.1 - Lite", aspect: "9:16", count: 1 },
    });
    assert.equal(enqRes.status, 200, `enqueue failed: ${JSON.stringify(enqRes.body)}`);
    const RUN_ID = enqRes.body?.production_run_id;
    assert.ok(RUN_ID, "no production_run_id returned");
    evidence.run = {
      id: RUN_ID,
      dry_run_at_creation: enqRes.body?.dry_run,
      status_at_creation: enqRes.body?.status,
      refused: enqRes.body?.refused,
    };
    log(`  RUN_ID=${RUN_ID} dry_run=${evidence.run.dry_run_at_creation} status=${evidence.run.status_at_creation}`);

    // ── DRY-RUN. confirm_live_credit_burn is OMITTED: the API defaults it to false
    //    (production_queue.py:31), and assertNoLiveBurn would refuse it as true anyway.
    log(`[dry-run] POST /api/workspace/production-queue/${RUN_ID}/start  (confirm_live_credit_burn omitted)`);
    const startRes = await call("POST", `/api/workspace/production-queue/${RUN_ID}/start`, {
      body: {},
      key: "/api/workspace/production-queue/{run_id}/start",
    });
    assert.equal(startRes.status, 200, `dry-run start failed: ${JSON.stringify(startRes.body)}`);
    assert.strictEqual(startRes.body?.dry_run, true, "start did NOT report dry_run=true");
    assert.ok(!("status" in (startRes.body || {})) || startRes.body.status !== "RUNNING",
      "GUARDRAIL VIOLATION: start returned RUNNING — the live branch was taken");
    evidence.dry_run_start = startRes.body;
    log(`  dry_run=${startRes.body?.dry_run}  report_keys=${Object.keys(startRes.body?.report || {})}`);

    // ── Retrieve the persisted report + terminal run state.
    log(`[detail] GET /api/workspace/production-queue/${RUN_ID}`);
    const detRes = await call("GET", `/api/workspace/production-queue/${RUN_ID}`, {
      key: "/api/workspace/production-queue/{run_id}",
    });
    assert.equal(detRes.status, 200, "run detail failed");
    const run = detRes.body?.run || detRes.body;
    let cfg = run?.config_json;
    if (typeof cfg === "string") { try { cfg = JSON.parse(cfg); } catch { cfg = {}; } }
    evidence.detail = {
      dry_run: run?.dry_run,
      status: run?.status,
      total_expected: run?.total_expected,
      last_dry_run_report: cfg?.last_dry_run_report ?? null,
      config_model: cfg?.model,
      config_package_ids: cfg?.package_ids,
    };
    log(`  dry_run=${run?.dry_run} status=${run?.status} report_present=${Boolean(cfg?.last_dry_run_report)}`);

    // ── The load-bearing assertions.
    assert.strictEqual(Number(run?.dry_run), 1, "production_run.dry_run is not 1");
    assert.notStrictEqual(run?.status, "RUNNING", "GUARDRAIL VIOLATION: run went RUNNING");
    assert.ok(cfg?.last_dry_run_report, "last_dry_run_report missing from config_json");
    assert.ok(
      JSON.stringify(cfg.last_dry_run_report).includes(WGP_ID),
      "last_dry_run_report does not correlate to the WGP",
    );

    // ── Closed call surface: every call made must be one we allow.
    const unexpected = evidence.calls.filter((c) => !ALLOWED_CALL_KEYS.has(c.key));
    assert.equal(unexpected.length, 0, `GUARDRAIL VIOLATION: unexpected calls ${JSON.stringify(unexpected)}`);
    evidence.closed_call_surface = {
      allowed: [...ALLOWED_CALL_KEYS],
      made: evidence.calls.map((c) => c.key),
      unexpected: [],
    };

    evidence.correlation = { wep_id: WEP_ID, wgp_id: WGP_ID, production_run_id: RUN_ID };
    evidence.ROUND_D_API_DRY_RUN_NEVER_WENT_LIVE = true;
    evidence.result = "PASS";
  } catch (err) {
    evidence.result = "FAIL";
    evidence.error = String(err && err.message ? err.message : err);
    console.error(`D-API DRY-RUN FAILED: ${evidence.error}`);
  }

  fs.writeFileSync(path.join(OUT, "evidence.json"), JSON.stringify(evidence, null, 2));
  console.log("\n=== ROUND D-API DRY-RUN SUMMARY ===");
  console.log(JSON.stringify({
    result: evidence.result,
    ROUND_D_API_DRY_RUN_NEVER_WENT_LIVE: evidence.ROUND_D_API_DRY_RUN_NEVER_WENT_LIVE === true,
    correlation: evidence.correlation,
    dry_run: evidence.detail?.dry_run,
    status: evidence.detail?.status,
    last_dry_run_report_present: Boolean(evidence.detail?.last_dry_run_report),
    calls: evidence.calls.map((c) => c.key),
    refused_requests: evidence.network.refused.length,
    confirm_live_credit_burn_sent: false,
    error: evidence.error,
    evidence_dir: OUT,
  }, null, 2));
  // Set exitCode and let the loop drain instead of process.exit(): forcing exit while
  // fetch's keep-alive sockets are still open crashes libuv on Windows
  // ("Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)") and returns 127, which
  // would report a PASSING run as a failure.
  process.exitCode = evidence.result === "PASS" ? 0 : 1;
})();
