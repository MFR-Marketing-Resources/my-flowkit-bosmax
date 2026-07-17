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
vi.mock("../api/workspaceGenerationPackages", () => ({
	createT2VGenerationPackage: (...a: unknown[]) => createT2VGenerationPackage(...a),
}));
vi.mock("../api/productionQueue", () => ({
	approvePackages: (...a: unknown[]) => approvePackages(...a),
	createProductionRun: (...a: unknown[]) => createProductionRun(...a),
	startProductionRun: (...a: unknown[]) => startProductionRun(...a),
	getProductionRun: (...a: unknown[]) => getProductionRun(...a),
	fetchVideoModels: (...a: unknown[]) => fetchVideoModels(...a),
	LIVE_GATE_ONE_SERIAL_T2V: "ONE_SERIAL_T2V",
	LIVE_CONFIRM_PHRASE: "AUTHORIZE_ONE_T2V_LIVE_RUN",
}));

import RpaProductionStudioPage from "./RpaProductionStudioPage";

const PRODUCT = { id: "prod-1", product_display_name: "ZZ Test Product", category: "Beauty", reference_only: false };
const REF_PRODUCT = { id: "fastmoss-ref:x", product_display_name: "Ref Only", reference_only: true };
const GREEN = { checked: 1, ready: 1, blocked: 0, note: "dry run", items: [{ package_id: "wgp_1", ok: true }] };

function primeHappyPath(report: unknown = GREEN, items: unknown[] = []) {
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
			"studio-model", "studio-duration", "studio-aspect", "studio-quantity",
			"studio-action-prepare", "studio-action-validate", "studio-live-gate",
			"studio-phrase-input", "studio-action-go-live", "studio-result-panel",
		]) {
			expect(screen.getByTestId(id)).toBeInTheDocument();
		}
	});

	it("enables T2V and locks F2V/I2V/Hybrid/IMG + bulk", async () => {
		primeHappyPath();
		renderPage();
		await screen.findByTestId("studio-mode-t2v");
		expect(screen.getByTestId("studio-mode-t2v")).toHaveAttribute("data-enabled", "true");
		for (const m of ["f2v", "i2v", "hybrid", "img"]) {
			expect(screen.getByTestId(`studio-mode-${m}`)).toHaveAttribute("data-locked", "true");
			expect(screen.getByTestId(`studio-mode-${m}`)).toHaveAttribute("data-enabled", "false");
		}
		expect(screen.getByTestId("studio-bulk-locked")).toHaveAttribute("data-locked", "true");
	});

	it("fixes quantity to 1 and offers no way to change it", async () => {
		primeHappyPath();
		renderPage();
		const qty = await screen.findByTestId("studio-quantity");
		expect(qty).toHaveValue("1");
		expect(qty).toBeDisabled();
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
