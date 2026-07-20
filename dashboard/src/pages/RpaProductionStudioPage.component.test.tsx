/**
 * RPA Production Studio — user-facing T2V studio contract + safety gate.
 *
 * Two things are asserted, the second matters most:
 *   1. the studio is REAL and product-first — pick product → configure → prepare →
 *      validate → one live T2V → result, wired to the actual safe endpoints;
 *   2. it CANNOT burn credits by accident — the live door opens only when every gate
 *      condition holds, latches on submit, and never fakes a success.
 *
 * State-bearing selectors are asserted in more than one state so the audit cannot
 * pass vacuously. No provider is called — every API is a fake.
 */
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchProductCatalog = vi.fn();
const searchProducts = vi.fn();
const createT2VGenerationPackage = vi.fn();
const approvePackages = vi.fn();
const createProductionRun = vi.fn();
const startProductionRun = vi.fn();
const getProductionRun = vi.fn();
const fetchVideoModels = vi.fn();

vi.mock("../api/products", () => ({
	fetchProductCatalog: (...a: unknown[]) => fetchProductCatalog(...a),
	searchProducts: (...a: unknown[]) => searchProducts(...a),
}));
const createFromExecutionPackage = vi.fn();
const createI2VGenerationPackage = vi.fn();
vi.mock("../api/workspaceGenerationPackages", () => ({
	createT2VGenerationPackage: (...a: unknown[]) => createT2VGenerationPackage(...a),
	createFromExecutionPackage: (...a: unknown[]) => createFromExecutionPackage(...a),
	createI2VGenerationPackage: (...a: unknown[]) => createI2VGenerationPackage(...a),
}));
const fetchCreativeAssets = vi.fn();
vi.mock("../api/creativeAssets", () => ({
	fetchCreativeAssets: (...a: unknown[]) => fetchCreativeAssets(...a),
}));
const fetchFlowPageState = vi.fn();
const openFlowNewProject = vi.fn();
vi.mock("../api/operator", () => ({
	fetchFlowPageState: (...a: unknown[]) => fetchFlowPageState(...a),
	openFlowNewProject: (...a: unknown[]) => openFlowNewProject(...a),
}));
vi.mock("../api/productionQueue", () => ({
	approvePackages: (...a: unknown[]) => approvePackages(...a),
	createProductionRun: (...a: unknown[]) => createProductionRun(...a),
	startProductionRun: (...a: unknown[]) => startProductionRun(...a),
	getProductionRun: (...a: unknown[]) => getProductionRun(...a),
	fetchVideoModels: (...a: unknown[]) => fetchVideoModels(...a),
	LIVE_GATE_ONE_SERIAL_T2V: "ONE_SERIAL_T2V",
	LIVE_CONFIRM_PHRASE: "AUTHORIZE_ONE_T2V_LIVE_RUN",
	LIVE_GATE_ONE_SERIAL_F2V: "ONE_SERIAL_F2V",
	LIVE_F2V_CONFIRM_PHRASE: "AUTHORIZE_ONE_F2V_LIVE_RUN",
	LIVE_GATE_ONE_SERIAL_I2V: "ONE_SERIAL_I2V",
	LIVE_I2V_CONFIRM_PHRASE: "AUTHORIZE_ONE_I2V_LIVE_RUN",
}));

// ── EXTEND (multi-block) lane fakes ──
const createWorkspaceExecutionPackage = vi.fn();
const previewQuantityCopyPlans = vi.fn();
const fetchCopyPoolReadiness = vi.fn();
const fetchBulkFanoutPlan = vi.fn();
const prepareBulkFanoutPackages = vi.fn();
const planVideoJob = vi.fn();
const authorizeVideoJob = vi.fn();
const startVideoJob = vi.fn();
const getVideoJobStatus = vi.fn();

vi.mock("../api/workspacePackages", () => ({
	createWorkspaceExecutionPackage: (...a: unknown[]) => createWorkspaceExecutionPackage(...a),
	previewQuantityCopyPlans: (...a: unknown[]) => previewQuantityCopyPlans(...a),
	fetchCopyPoolReadiness: (...a: unknown[]) => fetchCopyPoolReadiness(...a),
	fetchBulkFanoutPlan: (...a: unknown[]) => fetchBulkFanoutPlan(...a),
	prepareBulkFanoutPackages: (...a: unknown[]) => prepareBulkFanoutPackages(...a),
}));
vi.mock("../api/nativeExtend", () => ({
	planVideoJob: (...a: unknown[]) => planVideoJob(...a),
	authorizeVideoJob: (...a: unknown[]) => authorizeVideoJob(...a),
	startVideoJob: (...a: unknown[]) => startVideoJob(...a),
	getVideoJobStatus: (...a: unknown[]) => getVideoJobStatus(...a),
}));

import RpaProductionStudioPage from "./RpaProductionStudioPage";

const PRODUCT = { id: "prod-1", product_display_name: "ZZ Test Product", category: "Beauty", reference_only: false };
const REF_PRODUCT = { id: "fastmoss-ref:x", product_display_name: "Ref Only", reference_only: true };
const GREEN = { checked: 1, ready: 1, blocked: 0, note: "dry run", items: [{ package_id: "wgp_1", ok: true }] };

/** Approved copy pool that CAN supply the requested quantity. Preview only runs
 *  after readiness returns READY, so this is the happy-path default. */
const READY_POOL = {
	product_id: "prod-1", quantity_requested: 3, quantity_max: 5,
	approved_copy_count: 3, unique_dialogue_count: 3, shortage_count: 0,
	readiness_status: "READY", duplicate_fingerprint_groups: [],
	scanned_copy_set_count: 3, pool_scan_capped: false, compile_errors: [],
	next_action: null, credit: "NONE", provider_calls: 0, flow_calls: 0,
};

/** Stage 2A itemized fan-out plan: N separate intents, all prerequisites proven,
 *  yet live still refused at the Stage 3 credit boundary. */
const BULK_PLAN = {
	product_id: "prod-1", quantity_requested: 3, quantity_max: 5,
	logical_mode: "T2V", generation_mode: "SINGLE", planned_intent_count: 3,
	intents: [0, 1, 2].map((i) => ({
		item_index: i, copy_variant_id: `cs${i}`, variation_salt: `v${i + 1}`,
		dialogue_fingerprint: `fp${i}`, hook: `hook ${i}`, dialogue_summary: `line ${i}`,
		seam_voice: null, logical_mode: "T2V", source_mode: "T2V", generation_mode: "SINGLE",
		workspace_generation_package_id: null, production_run_id: null, production_job_id: null,
		item_status: "PLANNED", compile_error: null,
		credit_state: "NOT_AUTHORIZED", credit_warning: "This item spends provider credit when fired.",
	})),
	bulk_plan_fingerprint: "bulkfp", copy_pool_readiness_status: "READY",
	dialogue_uniqueness_status: "UNIQUE", blockers: [], bulk_authorizable: true,
	live_bulk_status: "Bulk live fan-out not certified yet",
	live_bulk_stage: "STAGE_3_RUNTIME_CERTIFICATION_REQUIRED",
	required_confirm_phrase: "AUTHORIZE_BULK_FANOUT_LIVE_RUN",
	credit: "NONE", provider_calls: 0, flow_calls: 0,
};

/** Stage 2C prepared batch: N durable packages + one queued run, credit-free. */
const BULK_PREPARED = {
	bulk_run_id: "bulk_abc", bulk_plan_fingerprint: "bulkfp",
	production_run_id: "prun_bulk_1", product_id: "prod-1",
	logical_mode: "T2V", generation_mode: "SINGLE", quantity_requested: 3,
	prepared_package_count: 3,
	package_ids: ["wgp_0", "wgp_1", "wgp_2"],
	expect_dialogue_fingerprints: ["fp0", "fp1", "fp2"],
	items: [0, 1, 2].map((i) => ({
		item_index: i, copy_variant_id: `cs${i}`, variation_salt: `v${i + 1}`,
		dialogue_fingerprint: `fp${i}`, hook: `hook ${i}`, dialogue_summary: `line ${i}`,
		logical_mode: "T2V", source_mode: "T2V", generation_mode: "SINGLE",
		workspace_generation_package_id: `wgp_${i}`,
		item_status: "PREPARED", credit_state: "NOT_AUTHORIZED",
	})),
	reused_existing_batch: false, stage: "PACKAGES_PREPARED",
	next_step: "DRY_RUN_VALIDATE_ALL_ITEMS",
	live_bulk_status: "Bulk live fan-out not certified yet",
	live_bulk_stage: "STAGE_3_RUNTIME_CERTIFICATION_REQUIRED",
	required_confirm_phrase: "AUTHORIZE_BULK_FANOUT_LIVE_RUN",
	credit: "NONE", provider_calls: 0, flow_calls: 0,
};

function primeHappyPath(report: unknown = GREEN, items: unknown[] = []) {
	fetchCopyPoolReadiness.mockResolvedValue(READY_POOL);
	fetchBulkFanoutPlan.mockResolvedValue(BULK_PLAN);
	prepareBulkFanoutPackages.mockResolvedValue(BULK_PREPARED);
	fetchProductCatalog.mockResolvedValue({ items: [PRODUCT, REF_PRODUCT] });
	searchProducts.mockResolvedValue({ items: [PRODUCT] });
	fetchVideoModels.mockResolvedValue({
		default: "veo_3_1_lite",
		models: [{ key: "veo_3_1_lite", ui_label: "Veo 3.1 - Lite", default_duration_s: 8, allowed_durations_s: [8] }],
	});
	createT2VGenerationPackage.mockResolvedValue({ workspace_generation_package_id: "wgp_1", status: "READY_MANUAL" });
	approvePackages.mockResolvedValue({ approved: 1, results: [{ package_id: "wgp_1", ok: true }] });
	createProductionRun.mockResolvedValue({ production_run_id: "prun_1", dry_run: 1, status: "PENDING" });
	startProductionRun.mockResolvedValue({ run_id: "prun_1", dry_run: true, report });
	getProductionRun.mockResolvedValue({
		run: { production_run_id: "prun_1", dry_run: 1, status: "PENDING", config_json: JSON.stringify({ last_dry_run_report: report }) },
		items,
	});
}

function renderPage() {
	return render(<MemoryRouter><RpaProductionStudioPage /></MemoryRouter>);
}
async function click(testid: string) {
	await act(async () => { fireEvent.click(screen.getByTestId(testid)); });
}
async function typePhrase(value: string) {
	await act(async () => { fireEvent.change(screen.getByTestId("studio-phrase-input"), { target: { value } }); });
}
async function pickProduct() {
	await screen.findByTestId("studio-product-option");
	await click("studio-product-option");
}
async function prepareAndValidate() {
	await pickProduct();
	await click("studio-action-prepare");
	await waitFor(() => expect(screen.getByTestId("studio-status-wgp")).toHaveTextContent("wgp_1"));
	await click("studio-action-validate");
	await waitFor(() => expect(screen.getByTestId("studio-dryrun-report")).toBeInTheDocument());
}
function primeLiveResult(items: unknown[]) {
	startProductionRun.mockResolvedValue({ run_id: "prun_1", dry_run: false, status: "RUNNING" });
	getProductionRun.mockResolvedValue({
		run: { production_run_id: "prun_1", dry_run: 0, status: "RUNNING", config_json: JSON.stringify({ last_dry_run_report: GREEN }) },
		items,
	});
}

afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Production Studio — rendered contract", () => {
	it("renders the studio and every step a user needs", async () => {
		primeHappyPath();
		renderPage();
		expect(await screen.findByTestId("rpa-production-studio")).toBeInTheDocument();
		for (const id of [
			"studio-bulk-locked", "studio-product-search", "studio-mode-t2v",
			"studio-model", "studio-duration", "studio-aspect", "studio-quantity-status",
			"studio-action-prepare", "studio-action-validate", "studio-live-gate",
			"studio-phrase-input", "studio-action-go-live", "studio-result-panel",
		]) {
			expect(screen.getByTestId(id)).toBeInTheDocument();
		}
	});

	it("all four video lanes + IMG are enabled; T2V selected by default; bulk stays locked", async () => {
		primeHappyPath();
		renderPage();
		await screen.findByTestId("studio-mode-t2v");
		for (const m of ["t2v", "f2v", "hybrid", "i2v", "img"]) {
			expect(screen.getByTestId(`studio-mode-${m}`)).toHaveAttribute("data-enabled", "true");
		}
		expect(screen.getByTestId("studio-mode-t2v")).toHaveAttribute("data-selected", "true");
		expect(screen.getByTestId("studio-mode-f2v")).toHaveAttribute("data-selected", "false");
		expect(screen.getByTestId("studio-bulk-locked")).toHaveAttribute("data-locked", "true");
	});

	it("IMG card deep-links to the Fastlane with the selected product", async () => {
		primeHappyPath();
		renderPage();
		await pickProduct();
		const assign = vi.fn();
		const original = window.location;
		Object.defineProperty(window, "location", {
			value: { ...original, assign },
			writable: true,
		});
		try {
			await click("studio-mode-img");
			expect(assign).toHaveBeenCalledWith("/assets/img-fastlane?product_id=prod-1");
		} finally {
			Object.defineProperty(window, "location", { value: original, writable: true });
		}
	});

	it("exposes quantity as a capped stepper (Stage 1 preview), default 1", async () => {
		primeHappyPath();
		renderPage();
		const input = await screen.findByTestId("studio-quantity-input");
		expect(input).toHaveAttribute("type", "number");
		expect(input).toHaveAttribute("min", "1");
		expect(input).toHaveAttribute("max", "5");
		expect(input).toHaveValue(1);
	});

	it("excludes reference-only products from the selector", async () => {
		primeHappyPath();
		renderPage();
		await screen.findByTestId("studio-product-option");
		const ids = screen.getAllByTestId("studio-product-option").map((b) => b.getAttribute("data-product-id"));
		expect(ids).toContain("prod-1");
		expect(ids).not.toContain("fastmoss-ref:x");
	});
});

describe("Production Studio — the live gate is fail-closed", () => {
	it("is shut on load and stays shut until product + dry-run + phrase all pass", async () => {
		primeHappyPath();
		renderPage();
		// State 1: nothing selected.
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "false");
		expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();

		// State 2: prepared + validated green, but no phrase → still shut.
		await prepareAndValidate();
		expect(screen.getByTestId("studio-check-dryrun")).toHaveAttribute("data-ok", "true");
		expect(screen.getByTestId("studio-check-phrase")).toHaveAttribute("data-ok", "false");
		expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();

		// State 3: exact phrase → open.
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		expect(screen.getByTestId("studio-action-go-live")).toBeEnabled();
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "true");
	});

	it("stays shut when the dry run is blocked, even with the right phrase", async () => {
		primeHappyPath({ checked: 1, ready: 0, blocked: 1, items: [{ package_id: "wgp_1", ok: false, blockers: ["EMPTY_FINAL_PROMPT"] }] });
		renderPage();
		await prepareAndValidate();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		expect(screen.getByTestId("studio-check-dryrun")).toHaveAttribute("data-ok", "false");
		expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();
		expect(screen.getByTestId("studio-blocker")).toHaveTextContent("EMPTY_FINAL_PROMPT");
	});

	it("rejects a near-miss phrase", async () => {
		primeHappyPath();
		renderPage();
		await prepareAndValidate();
		for (const wrong of ["authorize_one_t2v_live_run", "AUTHORIZE_ONE_T2V_LIVE_RUN ", "yes"]) {
			await typePhrase(wrong);
			expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();
		}
	});

	it("requires validation before the phrase can open the gate", async () => {
		primeHappyPath();
		renderPage();
		await pickProduct();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN"); // phrase before any dry run
		expect(screen.getByTestId("studio-check-dryrun")).toHaveAttribute("data-ok", "false");
		expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();
	});
});

describe("Production Studio — Stage 1 quantity preview (credit-free, live stays blocked)", () => {
	async function setQuantity(n: number) {
		await act(async () => {
			fireEvent.change(await screen.findByTestId("studio-quantity-input"), { target: { value: String(n) } });
		});
	}

	const UNIQUE_PREVIEW = {
		quantity_requested: 3, quantity_max: 5, planned_item_count: 3, logical_mode: "T2V",
		generation_mode: "SINGLE", copy_source: "SCRIPT_LIBRARY", copy_rotation_warnings: [],
		items: [
			{ item_index: 0, variation_salt: "v1", copy_variant_id: "cs0", hook: "h0", dialogue_summary: "one", dialogue_fingerprint: "aaaa1111", seam_voice: null, compile_error: null },
			{ item_index: 1, variation_salt: "v2", copy_variant_id: "cs1", hook: "h1", dialogue_summary: "two", dialogue_fingerprint: "bbbb2222", seam_voice: null, compile_error: null },
			{ item_index: 2, variation_salt: "v3", copy_variant_id: "cs2", hook: "h2", dialogue_summary: "three", dialogue_fingerprint: "cccc3333", seam_voice: null, compile_error: null },
		],
		dialogue_uniqueness_status: "UNIQUE", duplicate_dialogue_groups: [], blockers: [],
		preview_ready: true, live_bulk_status: "Bulk live fan-out not enabled yet",
		live_bulk_stage: "STAGE_2_REQUIRED", credit: "NONE", provider_calls: 0, flow_calls: 0,
	};

	it("quantity > 1 blocks live submit and is preview-only (Stage 2 note shown)", async () => {
		primeHappyPath();
		renderPage();
		await pickProduct();
		await setQuantity(3);
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "false");
		expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();
		expect(screen.getByTestId("studio-live-bulk-blocked")).toHaveAttribute("data-blocked", "true");
		expect(screen.getByTestId("studio-action-prepare")).toBeDisabled();
		expect(createProductionRun).not.toHaveBeenCalled();
	});

	it("preview plans N unique copy variants credit-free — no createProductionRun", async () => {
		primeHappyPath();
		previewQuantityCopyPlans.mockResolvedValue(UNIQUE_PREVIEW);
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		const preview = await screen.findByTestId("studio-quantity-preview");
		expect(preview).toHaveAttribute("data-uniqueness", "UNIQUE");
		expect(preview).toHaveAttribute("data-count", "3");
		expect(screen.getAllByTestId("studio-preview-item")).toHaveLength(3);
		expect(previewQuantityCopyPlans).toHaveBeenCalledWith(expect.objectContaining({ quantity: 3 }));
		expect(createProductionRun).not.toHaveBeenCalled();
	});

	it("preview BLOCKS on duplicate dialogue (fail-closed, not warning)", async () => {
		primeHappyPath();
		previewQuantityCopyPlans.mockResolvedValue({
			...UNIQUE_PREVIEW,
			items: [
				{ item_index: 0, variation_salt: "v1", copy_variant_id: "cs0", hook: "h", dialogue_summary: "dup", dialogue_fingerprint: "same", seam_voice: null, compile_error: null },
				{ item_index: 1, variation_salt: "v2", copy_variant_id: "cs0", hook: "h", dialogue_summary: "dup", dialogue_fingerprint: "same", seam_voice: null, compile_error: null },
				{ item_index: 2, variation_salt: "v3", copy_variant_id: "cs1", hook: "h2", dialogue_summary: "ok", dialogue_fingerprint: "diff", seam_voice: null, compile_error: null },
			],
			dialogue_uniqueness_status: "DUPLICATE_DIALOGUE_BLOCKED", duplicate_dialogue_groups: [[0, 1]],
			blockers: ["DUPLICATE_DIALOGUE_ACROSS_ITEMS:0,1"], preview_ready: false,
		});
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		const preview = await screen.findByTestId("studio-quantity-preview");
		expect(preview).toHaveAttribute("data-uniqueness", "DUPLICATE_DIALOGUE_BLOCKED");
		expect(preview).toHaveAttribute("data-ready", "false");
		expect(screen.getByTestId("studio-preview-blocker")).toHaveTextContent("DUPLICATE_DIALOGUE_ACROSS_ITEMS");
		expect(createProductionRun).not.toHaveBeenCalled();
	});

	it("shows approved copy-pool readiness before previewing", async () => {
		primeHappyPath();
		previewQuantityCopyPlans.mockResolvedValue(UNIQUE_PREVIEW);
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		const pool = await screen.findByTestId("studio-copy-pool-readiness");
		expect(pool).toHaveAttribute("data-readiness", "READY");
		expect(pool).toHaveAttribute("data-unique", "3");
		expect(pool).toHaveAttribute("data-shortage", "0");
		// readiness is checked BEFORE the preview compile
		expect(fetchCopyPoolReadiness).toHaveBeenCalledWith(expect.objectContaining({ quantity: 3 }));
		expect(previewQuantityCopyPlans).toHaveBeenCalled();
	});

	it("BLOCKS preview and shows the exact shortage when the pool is too small", async () => {
		primeHappyPath();
		fetchCopyPoolReadiness.mockResolvedValue({
			...READY_POOL, approved_copy_count: 3, unique_dialogue_count: 2,
			shortage_count: 1, readiness_status: "COPY_POOL_SHORTAGE",
			next_action: "GENERATE_AND_APPROVE_COPY",
		});
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		const pool = await screen.findByTestId("studio-copy-pool-readiness");
		expect(pool).toHaveAttribute("data-readiness", "COPY_POOL_SHORTAGE");
		expect(screen.getByTestId("studio-copy-pool-shortage")).toHaveTextContent("Short by 1 unique dialogue");
		// fail-closed: the preview compile never runs against a short pool
		expect(previewQuantityCopyPlans).not.toHaveBeenCalled();
		expect(screen.queryByTestId("studio-quantity-preview")).toBeNull();
		expect(createProductionRun).not.toHaveBeenCalled();
	});

	it("offers a copy-seeding route when no approved copy exists", async () => {
		primeHappyPath();
		fetchCopyPoolReadiness.mockResolvedValue({
			...READY_POOL, approved_copy_count: 0, unique_dialogue_count: 0,
			shortage_count: 3, readiness_status: "NO_APPROVED_COPY_AVAILABLE",
			scanned_copy_set_count: 0, next_action: "GENERATE_AND_APPROVE_COPY",
		});
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		const pool = await screen.findByTestId("studio-copy-pool-readiness");
		expect(pool).toHaveAttribute("data-readiness", "NO_APPROVED_COPY_AVAILABLE");
		expect(screen.getByTestId("studio-copy-pool-shortage")).toHaveTextContent("No approved copy");
		expect(screen.getByTestId("studio-copy-pool-seed-cta")).toHaveAttribute(
			"href", "/creative/copy-registry?product_id=prod-1");
		expect(previewQuantityCopyPlans).not.toHaveBeenCalled();
	});

	it("readiness never unlocks live — quantity > 1 stays preview-only", async () => {
		primeHappyPath();
		previewQuantityCopyPlans.mockResolvedValue(UNIQUE_PREVIEW);
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		await screen.findByTestId("studio-copy-pool-readiness");
		// a READY pool + a UNIQUE preview must STILL leave live fully closed
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "false");
		expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();
		expect(screen.getByTestId("studio-action-prepare")).toBeDisabled();
		expect(screen.getByTestId("studio-live-bulk-blocked")).toHaveAttribute("data-blocked", "true");
		expect(createProductionRun).not.toHaveBeenCalled();
	});

	it("READY + UNIQUE preview plans N itemized intents with per-item identity", async () => {
		primeHappyPath();
		previewQuantityCopyPlans.mockResolvedValue(UNIQUE_PREVIEW);
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		const section = await screen.findByTestId("studio-bulk-fanout-section");
		expect(section).toHaveAttribute("data-intent-count", "3");
		expect(section).toHaveAttribute("data-authorizable", "true");
		const intents = screen.getAllByTestId("studio-bulk-intent");
		expect(intents).toHaveLength(3);
		expect(new Set(intents.map((i) => i.getAttribute("data-fingerprint"))).size).toBe(3);
		expect(new Set(intents.map((i) => i.getAttribute("data-variant"))).size).toBe(3);
		for (const i of intents) {
			expect(i).toHaveAttribute("data-credit", "NOT_AUTHORIZED");
			expect(i).toHaveAttribute("data-status", "PLANNED");
		}
		expect(fetchBulkFanoutPlan).toHaveBeenCalledWith(expect.objectContaining({ quantity: 3 }));
	});

	it("an authorizable bulk plan STILL does not unlock live (credit boundary holds)", async () => {
		primeHappyPath();
		previewQuantityCopyPlans.mockResolvedValue(UNIQUE_PREVIEW);
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		await screen.findByTestId("studio-bulk-fanout-section");
		expect(screen.getByTestId("studio-bulk-live-gate-state")).toHaveAttribute("data-live-blocked", "true");
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "false");
		expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();
		expect(screen.getByTestId("studio-action-prepare")).toBeDisabled();
		expect(screen.getByTestId("studio-live-bulk-blocked")).toHaveAttribute("data-blocked", "true");
		expect(createProductionRun).not.toHaveBeenCalled();
		expect(startProductionRun).not.toHaveBeenCalled();
	});

	it("does NOT plan a fan-out when the pool is short (blocked before preview)", async () => {
		primeHappyPath();
		fetchCopyPoolReadiness.mockResolvedValue({
			...READY_POOL, unique_dialogue_count: 2, shortage_count: 1,
			readiness_status: "COPY_POOL_SHORTAGE",
		});
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		await screen.findByTestId("studio-copy-pool-readiness");
		expect(previewQuantityCopyPlans).not.toHaveBeenCalled();
		expect(fetchBulkFanoutPlan).not.toHaveBeenCalled();
		expect(screen.queryByTestId("studio-bulk-fanout-section")).toBeNull();
	});

	it("does NOT plan a fan-out when the preview is duplicate-blocked", async () => {
		primeHappyPath();
		previewQuantityCopyPlans.mockResolvedValue({
			...UNIQUE_PREVIEW,
			dialogue_uniqueness_status: "DUPLICATE_DIALOGUE_BLOCKED",
			blockers: ["DUPLICATE_DIALOGUE_ACROSS_ITEMS:0,1"], preview_ready: false,
		});
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		await screen.findByTestId("studio-quantity-preview");
		expect(fetchBulkFanoutPlan).not.toHaveBeenCalled();
		expect(screen.queryByTestId("studio-bulk-fanout-section")).toBeNull();
	});

	it("quantity 1 plans no bulk fan-out at all", async () => {
		primeHappyPath();
		previewQuantityCopyPlans.mockResolvedValue({ ...UNIQUE_PREVIEW, quantity_requested: 1 });
		renderPage();
		await pickProduct();
		await click("studio-action-preview");
		await screen.findByTestId("studio-quantity-preview");
		expect(fetchBulkFanoutPlan).not.toHaveBeenCalled();
		expect(screen.queryByTestId("studio-bulk-fanout-section")).toBeNull();
	});

	it("bulk prepare creates N itemized packages and dry-runs every one, credit-free", async () => {
		primeHappyPath({ checked: 3, ready: 3, blocked: 0, note: "bulk dry run", items: [] });
		previewQuantityCopyPlans.mockResolvedValue(UNIQUE_PREVIEW);
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		await screen.findByTestId("studio-bulk-fanout-section");
		await click("studio-action-bulk-prepare");

		const prepared = await screen.findByTestId("studio-bulk-prepared");
		expect(prepared).toHaveAttribute("data-package-count", "3");
		expect(prepared).toHaveAttribute("data-stage", "PACKAGES_PREPARED");
		expect(prepared).toHaveAttribute("data-run", "prun_bulk_1");

		const pkgs = screen.getAllByTestId("studio-bulk-package");
		expect(pkgs).toHaveLength(3);
		expect(new Set(pkgs.map((p) => p.getAttribute("data-package"))).size).toBe(3);
		expect(new Set(pkgs.map((p) => p.getAttribute("data-variant"))).size).toBe(3);
		expect(new Set(pkgs.map((p) => p.getAttribute("data-fingerprint"))).size).toBe(3);

		// every item dry-run validated, no credit
		const dry = screen.getByTestId("studio-bulk-dryrun");
		expect(dry).toHaveAttribute("data-checked", "3");
		expect(dry).toHaveAttribute("data-ready", "3");
		expect(dry).toHaveAttribute("data-blocked", "0");

		// the plan the operator saw is pinned so a stale preview is refused
		expect(prepareBulkFanoutPackages).toHaveBeenCalledWith(
			expect.objectContaining({ quantity: 3, expect_bulk_plan_fingerprint: "bulkfp" }));
		// dry-run only — never a live start
		expect(startProductionRun).toHaveBeenCalledWith("prun_bulk_1", false);
	});

	it("a PREPARED bulk batch still does NOT unlock live", async () => {
		primeHappyPath({ checked: 3, ready: 3, blocked: 0, note: "bulk dry run", items: [] });
		previewQuantityCopyPlans.mockResolvedValue(UNIQUE_PREVIEW);
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		await screen.findByTestId("studio-bulk-fanout-section");
		await click("studio-action-bulk-prepare");
		await screen.findByTestId("studio-bulk-prepared");

		expect(screen.getByTestId("studio-bulk-live-gate-state")).toHaveAttribute("data-live-blocked", "true");
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "false");
		expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();
		// no live start was ever issued
		for (const call of startProductionRun.mock.calls) {
			expect(call[1]).toBe(false);
		}
	});

	it("surfaces a server bulk-prepare refusal without faking success", async () => {
		primeHappyPath();
		previewQuantityCopyPlans.mockResolvedValue(UNIQUE_PREVIEW);
		prepareBulkFanoutPackages.mockRejectedValue(new Error("BULK_PLAN_FINGERPRINT_STALE:abc,def"));
		renderPage();
		await pickProduct();
		await setQuantity(3);
		await click("studio-action-preview");
		await screen.findByTestId("studio-bulk-fanout-section");
		await click("studio-action-bulk-prepare");
		expect(await screen.findByTestId("studio-bulk-prepare-error")).toHaveTextContent("BULK_PLAN_FINGERPRINT_STALE");
		expect(screen.queryByTestId("studio-bulk-prepared")).toBeNull();
	});

	it("quantity 1 never offers bulk prepare", async () => {
		primeHappyPath();
		previewQuantityCopyPlans.mockResolvedValue({ ...UNIQUE_PREVIEW, quantity_requested: 1 });
		renderPage();
		await pickProduct();
		await click("studio-action-preview");
		await screen.findByTestId("studio-quantity-preview");
		expect(screen.queryByTestId("studio-action-bulk-prepare")).toBeNull();
		expect(prepareBulkFanoutPackages).not.toHaveBeenCalled();
	});

	it("quantity 1 keeps the single-serial live path (no bulk-blocked note)", async () => {
		primeHappyPath();
		renderPage();
		await pickProduct();
		expect(screen.getByTestId("studio-quantity-input")).toHaveValue(1);
		expect(screen.queryByTestId("studio-live-bulk-blocked")).not.toBeInTheDocument();
		expect(screen.getByTestId("studio-action-prepare")).not.toBeDisabled();
	});
});

describe("Production Studio — exactly one live submission, no fakery", () => {
	it("sends exactly ONE live request with the gate params", async () => {
		primeHappyPath();
		renderPage();
		await prepareAndValidate();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		primeLiveResult([{ package_id: "wgp_1", production_status: "RUNNING", production_job_id: "g_live_1" }]);
		await click("studio-action-go-live");

		const live = startProductionRun.mock.calls.filter((c) => c[1] === true);
		expect(live).toHaveLength(1);
		expect(live[0]).toEqual(["prun_1", true, { live_gate: "ONE_SERIAL_T2V", confirm_phrase: "AUTHORIZE_ONE_T2V_LIVE_RUN", expect_package_id: "wgp_1" }]);
	});

	it("latches against a double submit", async () => {
		primeHappyPath();
		renderPage();
		await prepareAndValidate();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		primeLiveResult([{ package_id: "wgp_1", production_status: "RUNNING", production_job_id: "g_live_1" }]);
		await click("studio-action-go-live");
		await click("studio-action-go-live");
		await click("studio-action-go-live");
		expect(startProductionRun.mock.calls.filter((c) => c[1] === true)).toHaveLength(1);
		expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();
	});

	it("shows a server refusal in plain language and no fake success", async () => {
		primeHappyPath();
		renderPage();
		await prepareAndValidate();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		startProductionRun.mockRejectedValue(new Error("RATE_LIMITED: blocked before approval"));
		await click("studio-action-go-live");
		expect(await screen.findByTestId("studio-live-refused")).toHaveTextContent(/rate limiter/i);
		expect(screen.queryByTestId("studio-result-success")).not.toBeInTheDocument();
	});
});

describe("Production Studio — result panel is honest", () => {
	it("shows nothing until a live job runs", async () => {
		primeHappyPath();
		renderPage();
		await prepareAndValidate();
		expect(screen.getByTestId("studio-result-empty")).toBeInTheDocument();
		expect(screen.queryByTestId("studio-result")).not.toBeInTheDocument();
	});

	it("renders in-flight, then a registered artifact success", async () => {
		primeHappyPath();
		renderPage();
		await prepareAndValidate();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		primeLiveResult([{ package_id: "wgp_1", production_status: "GENERATED", production_job_id: "g_live_1", artifact_media_ids: ["media_abc"] }]);
		await click("studio-action-go-live");

		const result = await screen.findByTestId("studio-result");
		expect(result).toHaveAttribute("data-registered", "true");
		expect(screen.getByTestId("studio-result-job")).toHaveTextContent("g_live_1");
		expect(screen.getByTestId("studio-result-success")).toHaveTextContent("Registered");
		expect(screen.getByTestId("studio-result-artifact")).toHaveAttribute("data-media-id", "media_abc");
	});

	it("shows a failure in plain language, never as success", async () => {
		primeHappyPath();
		renderPage();
		await prepareAndValidate();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		primeLiveResult([{ package_id: "wgp_1", production_status: "FAILED", production_job_id: "g_live_1", production_error: "CAPTCHA_FAILED: stale tab" }]);
		await click("studio-action-go-live");

		expect(await screen.findByTestId("studio-result-failure")).toHaveTextContent(/stale/i);
		expect(screen.queryByTestId("studio-result-success")).not.toBeInTheDocument();
		expect(screen.getByTestId("studio-result")).toHaveAttribute("data-registered", "false");
	});

	it("calls a generated-but-unbound video 'not registered', not success", async () => {
		primeHappyPath();
		renderPage();
		await prepareAndValidate();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		primeLiveResult([{ package_id: "wgp_1", production_status: "GENERATED", production_job_id: "g_live_1", production_error: "GENERATED_BUT_UNRETRIEVED", artifact_media_ids: [] }]);
		await click("studio-action-go-live");

		expect(await screen.findByTestId("studio-result-generated-not-registered")).toHaveTextContent(/not a success/i);
		expect(screen.queryByTestId("studio-result-success")).not.toBeInTheDocument();
	});
});

// ═══ EXTEND multi-block lane — wired to the PROVEN orchestrator, never the queue ═══

const EXTEND_WEP = {
	workspace_execution_package_id: "wep_ext1",
	request_lineage_payload: {
		compiler: {
			dialogue_word_budget_per_block: [18, 14],
			prompt_blocks: [{ block_index: 1 }, { block_index: 2 }],
		},
	},
};
const EXTEND_PLAN = {
	job_id: "vj_ext1",
	status: "CREATED",
	plan_fingerprint: "fp_abcdef1234567890",
	plan: {
		requested_seconds: 16,
		segment_count: 2,
		operation_counts: { initial_generation: 1, extend: 1, final_render: 1, total: 3 },
		credit_estimate: {},
	},
};

function primeExtend() {
	primeHappyPath();
	createWorkspaceExecutionPackage.mockResolvedValue(EXTEND_WEP);
	planVideoJob.mockResolvedValue(EXTEND_PLAN);
	authorizeVideoJob.mockResolvedValue({ job_id: "vj_ext1", authorization_token: "tok", expires_in_seconds: 300 });
	startVideoJob.mockResolvedValue({ job_id: "vj_ext1", status: "INITIAL_SUBMITTING", human_stage: "initial", complete: false, credit_summary: "MAY_HAVE_SPENT", no_credit_used: false });
	getVideoJobStatus.mockResolvedValue({ job_id: "vj_ext1", status: "INITIAL_POLLING", human_stage: "initial", complete: false, credit_summary: "MAY_HAVE_SPENT", no_credit_used: false });
}

async function pickExtendDuration(total: string) {
	await act(async () => {
		fireEvent.change(screen.getByTestId("studio-duration"), { target: { value: total } });
	});
}

describe("Production Studio — EXTEND multi-block lane", () => {
	afterEach(cleanup);

	it("offers extend totals beyond the single-shot max and marks them as EXTEND", async () => {
		primeExtend();
		renderPage();
		await screen.findByTestId("studio-product-option");
		const options = Array.from(
			(screen.getByTestId("studio-duration") as HTMLSelectElement).options,
		).map((o) => o.text);
		expect(options.some((t) => t.includes("16") && t.includes("EXTEND"))).toBe(true);
		expect(options.some((t) => t.includes("24") && t.includes("EXTEND"))).toBe(true);
	});

	it("prepares an EXTEND execution package + reviewed plan — and NEVER touches the queue lane", async () => {
		primeExtend();
		renderPage();
		await pickProduct();
		await pickExtendDuration("16");
		expect(screen.getByTestId("studio-extend-note")).toBeInTheDocument();

		await click("studio-action-prepare");

		// The PROVEN lane: WEP with generation_mode EXTEND + the orchestrator plan.
		expect(createWorkspaceExecutionPackage).toHaveBeenCalledWith(
			expect.objectContaining({
				mode: "T2V",
				generation_mode: "EXTEND",
				requested_total_duration_seconds: 16,
			}),
		);
		expect(planVideoJob).toHaveBeenCalledWith(
			expect.objectContaining({
				execution_package_id: "wep_ext1",
				requested_total_duration_seconds: 16,
				aspect_ratio: "VIDEO_ASPECT_RATIO_PORTRAIT",
			}),
		);
		// The single-shot queue lane must NOT be used for a multi-block request.
		expect(createT2VGenerationPackage).not.toHaveBeenCalled();
		expect(createProductionRun).not.toHaveBeenCalled();
		expect(startProductionRun).not.toHaveBeenCalled();

		// The reviewed plan + per-block WPS budgets are shown (the compiled blocks
		// are the canonical 9-section prompts; budgets come from the planner).
		expect(screen.getByTestId("studio-extend-plan")).toHaveAttribute("data-segments", "2");
		expect(screen.getAllByTestId("studio-extend-wps-block")).toHaveLength(2);
		expect(screen.getByTestId("studio-extend-blocks").textContent).toContain("2 canonical 9-section");
	});

	it("extend gate opens ONLY with the extend phrase, and firing authorizes the plan fingerprint then starts", async () => {
		primeExtend();
		renderPage();
		await pickProduct();
		await pickExtendDuration("16");
		await click("studio-action-prepare");

		const gate = screen.getByTestId("studio-live-gate");
		expect(gate).toHaveAttribute("data-lane", "EXTEND");
		expect(gate).toHaveAttribute("data-gate-open", "false");

		// The T2V phrase must NOT open the extend gate.
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "false");

		await typePhrase("AUTHORIZE_EXTEND_VIDEO_JOB");
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "true");

		await click("studio-action-go-live");
		expect(authorizeVideoJob).toHaveBeenCalledWith("vj_ext1", "fp_abcdef1234567890");
		expect(startVideoJob).toHaveBeenCalledWith("vj_ext1");
		// Queue live door untouched.
		expect(startProductionRun).not.toHaveBeenCalled();
		await waitFor(() => {
			expect(screen.getByTestId("studio-extend-result")).toBeInTheDocument();
		});
	});
});

// ═══ One-click F2V / HYBRID / I2V lanes — proven pipeline, per-lane gates ═══

const FRAME_ASSET = { asset_id: "ca_frame_916", display_name: "Frame 9:16", review_status: "APPROVED" };
const PRODREF_ASSET = { asset_id: "ca_prodref_916", display_name: "Anchor 9:16", review_status: "APPROVED" };
const CHAR_ASSET = { asset_id: "ca_char", display_name: "Char", review_status: "APPROVED" };
const SCENE_ASSET = { asset_id: "ca_scene", display_name: "Scene", review_status: "APPROVED" };

function primeImageModes() {
	primeHappyPath();
	fetchCreativeAssets.mockImplementation((input: { semantic_role?: string }) => {
		const role = input?.semantic_role;
		const items = role === "COMPOSITE_FRAME_REFERENCE" ? [FRAME_ASSET]
			: role === "PRODUCT_REFERENCE" ? [PRODREF_ASSET]
			: role === "CHARACTER_REFERENCE" ? [CHAR_ASSET]
			: role === "SCENE_CONTEXT_REFERENCE" ? [SCENE_ASSET] : [];
		return Promise.resolve({ items });
	});
	createWorkspaceExecutionPackage.mockResolvedValue({ workspace_execution_package_id: "wep_x" });
	createFromExecutionPackage.mockResolvedValue({ workspace_generation_package_id: "wgp_1" });
	createI2VGenerationPackage.mockResolvedValue({ workspace_generation_package_id: "wgp_1" });
	fetchFlowPageState.mockResolvedValue({ editor_capability_ready: true, build_match: true, flow_url: "x/project/p1" });
}

async function pickSelect(testid: string, value: string) {
	await act(async () => { fireEvent.change(screen.getByTestId(testid), { target: { value } }); });
}

describe("Production Studio — one-click F2V / HYBRID / I2V", () => {
	afterEach(cleanup);

	it("derives visible reference controls from the selected mode profile", async () => {
		primeImageModes();
		renderPage();
		await screen.findByTestId("studio-mode-t2v");
		expect(screen.queryByTestId("studio-ref-start-frame")).not.toBeInTheDocument();
		expect(screen.queryByTestId("studio-ref-product")).not.toBeInTheDocument();
		expect(screen.queryByTestId("studio-ref-character")).not.toBeInTheDocument();
		expect(screen.queryByTestId("studio-ref-scene")).not.toBeInTheDocument();

		await click("studio-mode-f2v");
		expect(screen.getByTestId("studio-ref-start-frame")).toBeInTheDocument();
		expect(screen.queryByTestId("studio-ref-product")).not.toBeInTheDocument();
		expect(screen.queryByTestId("studio-ref-character")).not.toBeInTheDocument();

		await click("studio-mode-hybrid");
		expect(screen.getByTestId("studio-ref-product")).toBeInTheDocument();
		expect(screen.queryByTestId("studio-ref-start-frame")).not.toBeInTheDocument();
		expect(screen.queryByTestId("studio-ref-character")).not.toBeInTheDocument();

		await click("studio-mode-i2v");
		expect(screen.getByTestId("studio-ref-character")).toBeInTheDocument();
		expect(screen.getByTestId("studio-ref-scene")).toBeInTheDocument();
		expect(screen.queryByTestId("studio-ref-start-frame")).not.toBeInTheDocument();
		expect(screen.queryByTestId("studio-ref-product")).not.toBeInTheDocument();
	});

	it("F2V prepare runs the PROVEN chain: WEP(FRAMES + start frame) → bridge → approve → enqueue", async () => {
		primeImageModes();
		renderPage();
		await pickProduct();
		await click("studio-mode-f2v");
		// Prepare is held until the start frame is chosen.
		expect(screen.getByTestId("studio-action-prepare")).toBeDisabled();
		await pickSelect("studio-ref-start-frame", "ca_frame_916");
		await click("studio-action-prepare");

		expect(createWorkspaceExecutionPackage).toHaveBeenCalledWith(
			expect.objectContaining({
				mode: "F2V", source_mode: "FRAMES",
				start_frame_asset_id: "ca_frame_916",
			}),
		);
		expect(createFromExecutionPackage).toHaveBeenCalledWith("wep_x", "F2V");
		expect(approvePackages).toHaveBeenCalledWith(["wgp_1"]);
		expect(createProductionRun).toHaveBeenCalled();
		expect(createT2VGenerationPackage).not.toHaveBeenCalled();
	});

	it("HYBRID prepare uses source_mode HYBRID with the product reference", async () => {
		primeImageModes();
		renderPage();
		await pickProduct();
		await click("studio-mode-hybrid");
		await pickSelect("studio-ref-product", "ca_prodref_916");
		await click("studio-action-prepare");
		expect(createWorkspaceExecutionPackage).toHaveBeenCalledWith(
			expect.objectContaining({
				mode: "F2V", source_mode: "HYBRID",
				product_reference_asset_id: "ca_prodref_916",
			}),
		);
		expect(screen.getByTestId("studio-refs-hybrid")).toHaveTextContent("Product anchor");
		expect(screen.queryByTestId("studio-ref-start-frame")).not.toBeInTheDocument();
		expect(screen.queryByText(/start frame/i)).not.toBeInTheDocument();
	});

	it("HYBRID uses its logical copy with the server-compatible first-frame phrase and gate", async () => {
		primeImageModes();
		renderPage();
		await pickProduct();
		await click("studio-mode-hybrid");
		await pickSelect("studio-ref-product", "ca_prodref_916");
		await click("studio-action-prepare");
		await waitFor(() => expect(screen.getByTestId("studio-status-wgp")).toHaveTextContent("wgp_1"));
		await click("studio-action-validate");
		await waitFor(() => expect(screen.getByTestId("studio-dryrun-report")).toBeInTheDocument());

		expect(screen.getByTestId("studio-live-warning")).toHaveTextContent("HYBRID product-anchor");
		expect(screen.getByText(/authorize one HYBRID product-anchor run/i)).toBeInTheDocument();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		expect(screen.getByTestId("studio-action-go-live")).toBeDisabled();
		await typePhrase("AUTHORIZE_ONE_F2V_LIVE_RUN");
		expect(screen.getByTestId("studio-action-go-live")).toBeEnabled();

		primeLiveResult([{ package_id: "wgp_1", production_status: "RUNNING", production_job_id: "g_hybrid" }]);
		await click("studio-action-go-live");
		expect(startProductionRun).toHaveBeenLastCalledWith("prun_1", true, expect.objectContaining({
			live_gate: "ONE_SERIAL_F2V",
			confirm_phrase: "AUTHORIZE_ONE_F2V_LIVE_RUN",
			expect_package_id: "wgp_1",
		}));
	});

	it("switching mode clears stale reference, package, run, dry-run, and phrase state", async () => {
		primeImageModes();
		renderPage();
		await pickProduct();
		await click("studio-mode-f2v");
		await pickSelect("studio-ref-start-frame", "ca_frame_916");
		await click("studio-action-prepare");
		await waitFor(() => expect(screen.getByTestId("studio-status-wgp")).toHaveTextContent("wgp_1"));
		await click("studio-action-validate");
		await typePhrase("AUTHORIZE_ONE_F2V_LIVE_RUN");

		await click("studio-mode-hybrid");
		expect(screen.getByTestId("studio-refs-hybrid")).toBeInTheDocument();
		expect(screen.queryByTestId("studio-ref-start-frame")).not.toBeInTheDocument();
		expect(screen.getByTestId("studio-status-wgp")).toHaveTextContent("—");
		expect(screen.getByTestId("studio-status-run")).toHaveTextContent("—");
		expect(screen.queryByTestId("studio-dryrun-report")).not.toBeInTheDocument();
		expect(screen.getByTestId("studio-phrase-input")).toHaveValue("");
		expect(screen.getByTestId("studio-action-prepare")).toBeDisabled();
	});

	it("I2V prepare creates the package directly with character + scene", async () => {
		primeImageModes();
		renderPage();
		await pickProduct();
		await click("studio-mode-i2v");
		expect(screen.getByTestId("studio-action-prepare")).toBeDisabled();
		await pickSelect("studio-ref-character", "ca_char");
		await pickSelect("studio-ref-scene", "ca_scene");
		await click("studio-action-prepare");
		expect(createI2VGenerationPackage).toHaveBeenCalledWith(
			expect.objectContaining({
				product_id: "prod-1",
				character_reference_asset_id: "ca_char",
				scene_context_reference_asset_id: "ca_scene",
			}),
		);
		expect(createWorkspaceExecutionPackage).not.toHaveBeenCalled();
	});

	it("F2V fire uses the first-frame family gate + F2V phrase (T2V phrase refused by UI)", async () => {
		primeImageModes();
		renderPage();
		await pickProduct();
		await click("studio-mode-f2v");
		await pickSelect("studio-ref-start-frame", "ca_frame_916");
		await click("studio-action-prepare");
		await waitFor(() => expect(screen.getByTestId("studio-status-wgp")).toHaveTextContent("wgp_1"));
		await click("studio-action-validate");
		await waitFor(() => expect(screen.getByTestId("studio-dryrun-report")).toBeInTheDocument());

		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "false");
		await typePhrase("AUTHORIZE_ONE_F2V_LIVE_RUN");
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "true");

		primeLiveResult([{ package_id: "wgp_1", production_status: "RUNNING", production_job_id: "g_x" }]);
		await click("studio-action-go-live");
		expect(startProductionRun).toHaveBeenLastCalledWith("prun_1", true, expect.objectContaining({
			live_gate: "ONE_SERIAL_F2V",
			confirm_phrase: "AUTHORIZE_ONE_F2V_LIVE_RUN",
			expect_package_id: "wgp_1",
		}));
	});

	it("I2V fire uses the I2V gate + phrase", async () => {
		primeImageModes();
		renderPage();
		await pickProduct();
		await click("studio-mode-i2v");
		await pickSelect("studio-ref-character", "ca_char");
		await pickSelect("studio-ref-scene", "ca_scene");
		await click("studio-action-prepare");
		await waitFor(() => expect(screen.getByTestId("studio-status-wgp")).toHaveTextContent("wgp_1"));
		await click("studio-action-validate");
		await waitFor(() => expect(screen.getByTestId("studio-dryrun-report")).toBeInTheDocument());
		await typePhrase("AUTHORIZE_ONE_I2V_LIVE_RUN");
		expect(screen.getByTestId("studio-live-gate")).toHaveAttribute("data-gate-open", "true");
		primeLiveResult([{ package_id: "wgp_1", production_status: "RUNNING", production_job_id: "g_y" }]);
		await click("studio-action-go-live");
		expect(startProductionRun).toHaveBeenLastCalledWith("prun_1", true, expect.objectContaining({
			live_gate: "ONE_SERIAL_I2V",
			confirm_phrase: "AUTHORIZE_ONE_I2V_LIVE_RUN",
		}));
	});
});
