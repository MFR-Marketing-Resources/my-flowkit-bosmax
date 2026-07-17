/**
 * Round E — RPA Queue Control rendered contract + safety gate.
 *
 * Two things are asserted here, and the second matters most:
 *   1. the panel is REAL — its buttons call the actual safe endpoints, not placeholders;
 *   2. the panel CANNOT burn credits — startProductionRun is only ever called with
 *      confirmLiveCreditBurn=false, and no live control is rendered.
 *
 * Following the Round A audit rule (G0 amendment M6), state-bearing selectors are
 * asserted in more than one state so the audit cannot pass vacuously.
 */
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchWorkspaceExecutionPackageHistory = vi.fn();
const createFromExecutionPackage = vi.fn();
const createT2VGenerationPackage = vi.fn();
const approvePackages = vi.fn();
const createProductionRun = vi.fn();
const startProductionRun = vi.fn();
const getProductionRun = vi.fn();

vi.mock("../api/workspacePackages", () => ({
	fetchWorkspaceExecutionPackageHistory: (...a: unknown[]) =>
		fetchWorkspaceExecutionPackageHistory(...a),
}));
vi.mock("../api/workspaceGenerationPackages", () => ({
	createFromExecutionPackage: (...a: unknown[]) => createFromExecutionPackage(...a),
	createT2VGenerationPackage: (...a: unknown[]) => createT2VGenerationPackage(...a),
}));
vi.mock("../api/productionQueue", () => ({
	approvePackages: (...a: unknown[]) => approvePackages(...a),
	createProductionRun: (...a: unknown[]) => createProductionRun(...a),
	startProductionRun: (...a: unknown[]) => startProductionRun(...a),
	getProductionRun: (...a: unknown[]) => getProductionRun(...a),
	LIVE_GATE_ONE_SERIAL_T2V: "ONE_SERIAL_T2V",
	LIVE_CONFIRM_PHRASE: "AUTHORIZE_ONE_T2V_LIVE_RUN",
}));

import RpaQueueControlPage from "./RpaQueueControlPage";

const WEP = {
	workspace_execution_package_id: "wep_test0001",
	product_id: "prod-1",
	product_name: "ZZ_TEST_PRODUCT",
	mode: "F2V",
};

const DRY_RUN_REPORT = {
	checked: 1,
	ready: 0,
	blocked: 1,
	note: "DRY RUN — nothing fired, no credits spent.",
	items: [
		{
			package_id: "wgp_test0001",
			ok: false,
			model: "Veo 3.1 - Lite",
			blockers: ["SLOT_NOT_UPLOADED_TO_FLOW:start_frame", "NO_FLOW_MEDIA_FOR_IMAGE_MODE"],
		},
	],
};

function renderPage() {
	return render(
		<MemoryRouter>
			<RpaQueueControlPage />
		</MemoryRouter>,
	);
}

/** Drives the full chain: pick -> bridge -> approve -> enqueue -> dry run. */
async function click(testid: string) {
	await act(async () => {
		fireEvent.click(screen.getByTestId(testid));
	});
}

async function runChain() {
	await screen.findByTestId("wep-option");
	await click("wep-option");
	await click("action-bridge-wep-to-wgp");
	await waitFor(() => expect(screen.getByTestId("status-wgp-id")).toHaveTextContent("wgp_test0001"));
	await click("action-approve-package");
	await waitFor(() => expect(screen.getByTestId("status-production-status")).toHaveTextContent("APPROVED"));
	await click("action-enqueue-dry-run");
	await waitFor(() => expect(screen.getByTestId("status-run-id")).toHaveTextContent("prun_test0001"));
	await click("action-run-dry-run");
	await waitFor(() => expect(screen.getByTestId("dry-run-report")).toBeInTheDocument());
}

function primeHappyPath() {
	fetchWorkspaceExecutionPackageHistory.mockResolvedValue([WEP]);
	createFromExecutionPackage.mockResolvedValue({
		workspace_generation_package_id: "wgp_test0001",
		workspace_execution_package_id: "wep_test0001",
		status: "READY_MANUAL",
		production_status: "NONE",
	});
	approvePackages.mockResolvedValue({
		approved: 1,
		results: [{ package_id: "wgp_test0001", ok: true, production_status: "APPROVED" }],
	});
	createProductionRun.mockResolvedValue({
		production_run_id: "prun_test0001",
		dry_run: 1,
		status: "PENDING",
	});
	startProductionRun.mockResolvedValue({ run_id: "prun_test0001", dry_run: true, report: DRY_RUN_REPORT });
	getProductionRun.mockResolvedValue({
		run: {
			production_run_id: "prun_test0001",
			dry_run: 1,
			status: "PENDING",
			config_json: JSON.stringify({ last_dry_run_report: DRY_RUN_REPORT }),
		},
	});
}

afterEach(() => {
	cleanup();
	vi.clearAllMocks();
});

describe("Round E — RPA Queue Control: rendered contract", () => {
	it("renders the panel and every RPA locator the operator needs", async () => {
		primeHappyPath();
		renderPage();
		expect(await screen.findByTestId("rpa-queue-control")).toBeInTheDocument();
		for (const id of [
			"action-refresh-packages",
			"action-bridge-wep-to-wgp",
			"action-approve-package",
			"action-enqueue-dry-run",
			"action-run-dry-run",
			"action-refresh-report",
			"status-wep-id",
			"status-wgp-id",
			"status-production-status",
			"status-run-id",
			"dry-run-report-panel",
			"bulk-live-locked",
			"live-gate-panel",
			"live-confirm-phrase-input",
			"action-start-one-t2v-live",
			"live-result-panel",
		]) {
			expect(screen.getByTestId(id)).toBeInTheDocument();
		}
	});

	it("renders the empty state when there are no execution packages", async () => {
		fetchWorkspaceExecutionPackageHistory.mockResolvedValue([]);
		renderPage();
		expect(await screen.findByTestId("rpa-queue-empty")).toBeInTheDocument();
		expect(screen.queryByTestId("wep-option")).not.toBeInTheDocument();
	});

	it("renders an API-unavailable state when the packages call fails", async () => {
		fetchWorkspaceExecutionPackageHistory.mockRejectedValue(new Error("network down"));
		renderPage();
		expect(await screen.findByTestId("rpa-queue-api-unavailable")).toBeInTheDocument();
	});
});

describe("Round E — buttons are wired to the real safe endpoints", () => {
	it("drives WEP -> WGP -> approve -> enqueue -> dry run against the real API client", async () => {
		primeHappyPath();
		renderPage();
		await runChain();

		expect(createFromExecutionPackage).toHaveBeenCalledWith("wep_test0001", "F2V");
		expect(approvePackages).toHaveBeenCalledWith(["wgp_test0001"]);
		expect(createProductionRun).toHaveBeenCalledWith(
			expect.objectContaining({ package_ids: ["wgp_test0001"], model: "Veo 3.1 - Lite" }),
		);
		expect(startProductionRun).toHaveBeenCalledWith("prun_test0001", false);
		expect(getProductionRun).toHaveBeenCalledWith("prun_test0001");
	});

	it("renders the dry-run report counts, the run flags and the blocker reasons", async () => {
		primeHappyPath();
		renderPage();
		await runChain();

		expect(screen.getByTestId("report-checked")).toHaveTextContent("1");
		expect(screen.getByTestId("report-ready")).toHaveTextContent("0");
		expect(screen.getByTestId("report-blocked")).toHaveTextContent("1");
		expect(screen.getByTestId("report-dry-run-flag")).toHaveTextContent("1");
		expect(screen.getByTestId("report-run-status")).toHaveTextContent("PENDING");
		expect(screen.getByTestId("report-no-credit-notice")).toHaveTextContent(/no credit burn/i);

		const item = screen.getByTestId("dry-run-item");
		expect(item).toHaveAttribute("data-blocked", "true");
		const blockers = screen.getAllByTestId("dry-run-blocker").map((b) => b.getAttribute("data-blocker-code"));
		expect(blockers).toContain("SLOT_NOT_UPLOADED_TO_FLOW:start_frame");
		expect(blockers).toContain("NO_FLOW_MEDIA_FOR_IMAGE_MODE");
	});

	it("surfaces a refused approval instead of pretending it worked", async () => {
		primeHappyPath();
		approvePackages.mockResolvedValue({
			approved: 0,
			results: [{ package_id: "wgp_test0001", ok: false, error: "NOT_APPROVABLE_STATUS:BLOCKED" }],
		});
		renderPage();
		await screen.findByTestId("wep-option");
		await click("wep-option");
		await click("action-bridge-wep-to-wgp");
		await waitFor(() => expect(screen.getByTestId("status-wgp-id")).toHaveTextContent("wgp_test0001"));
		await click("action-approve-package");
		expect(await screen.findByTestId("rpa-queue-error")).toHaveTextContent("NOT_APPROVABLE_STATUS:BLOCKED");
	});
});

describe("Round E — the prepare chain never burns credits", () => {
	it("the F2V prepare/dry-run chain only ever calls startProductionRun with false", async () => {
		primeHappyPath();
		renderPage();
		await runChain();

		expect(startProductionRun).toHaveBeenCalled();
		for (const callArgs of startProductionRun.mock.calls) {
			// The second argument is confirmLiveCreditBurn. The F2V chain can never
			// reach the live gate (it is T2V-only), so it must be false on EVERY call.
			expect(callArgs[1]).toBe(false);
		}
	});

	it("keeps BULK live locked", async () => {
		primeHappyPath();
		renderPage();
		const lock = await screen.findByTestId("bulk-live-locked");
		expect(lock).toHaveAttribute("data-locked", "true");
		expect(lock).toHaveTextContent(/bulk live generation is locked/i);
	});

	it("dry-run stage gating is falsifiable: actions are disabled before their turn and enabled after", async () => {
		primeHappyPath();
		renderPage();

		// State 1: nothing selected -> the chain is closed.
		expect(screen.getByTestId("action-bridge-wep-to-wgp")).toBeDisabled();
		expect(screen.getByTestId("action-run-dry-run")).toBeDisabled();
		expect(screen.getByTestId("rpa-queue-control")).toHaveAttribute("data-stage", "IDLE");

		// State 2: selected -> bridge opens, but dry run is still shut.
		await screen.findByTestId("wep-option");
		await click("wep-option");
		expect(screen.getByTestId("action-bridge-wep-to-wgp")).toBeEnabled();
		expect(screen.getByTestId("action-run-dry-run")).toBeDisabled();

		// State 3: full chain -> dry run ran, stage advanced.
		await runChain();
		expect(screen.getByTestId("rpa-queue-control")).toHaveAttribute("data-stage", "DRY_RUN_DONE");
	});
});

// ── Round F — the one-serial T2V live gate ────────────────────────────────

const T2V_WEP = {
	workspace_execution_package_id: "wep_t2v0001",
	product_id: "prod-t2v",
	product_name: "ZZ_TEST_T2V",
	mode: "T2V",
	duration_seconds: 8,
};

const GREEN_REPORT = {
	checked: 1,
	ready: 1,
	blocked: 0,
	note: "DRY RUN — nothing fired, no credits spent.",
	items: [{ package_id: "wgp_t2v0001", ok: true, model: "Veo 3.1 - Lite" }],
};

function primeT2V(report: unknown = GREEN_REPORT, items: unknown[] = []) {
	fetchWorkspaceExecutionPackageHistory.mockResolvedValue([T2V_WEP]);
	createT2VGenerationPackage.mockResolvedValue({
		workspace_generation_package_id: "wgp_t2v0001",
		status: "READY_MANUAL",
		production_status: "NONE",
	});
	approvePackages.mockResolvedValue({
		approved: 1,
		results: [{ package_id: "wgp_t2v0001", ok: true, production_status: "APPROVED" }],
	});
	createProductionRun.mockResolvedValue({
		production_run_id: "prun_t2v0001",
		dry_run: 1,
		status: "PENDING",
	});
	startProductionRun.mockResolvedValue({
		run_id: "prun_t2v0001",
		dry_run: true,
		report,
	});
	getProductionRun.mockResolvedValue({
		run: {
			production_run_id: "prun_t2v0001",
			dry_run: 1,
			status: "PENDING",
			config_json: JSON.stringify({ last_dry_run_report: report }),
		},
		items,
	});
}

async function runT2VChain() {
	await screen.findByTestId("wep-option");
	await click("wep-option");
	await click("action-bridge-wep-to-wgp");
	await waitFor(() =>
		expect(screen.getByTestId("status-wgp-id")).toHaveTextContent("wgp_t2v0001"),
	);
	await click("action-approve-package");
	await waitFor(() =>
		expect(screen.getByTestId("status-production-status")).toHaveTextContent("APPROVED"),
	);
	await click("action-enqueue-dry-run");
	await waitFor(() =>
		expect(screen.getByTestId("status-run-id")).toHaveTextContent("prun_t2v0001"),
	);
	await click("action-run-dry-run");
	await waitFor(() => expect(screen.getByTestId("dry-run-report")).toBeInTheDocument());
}

async function typePhrase(value: string) {
	await act(async () => {
		fireEvent.change(screen.getByTestId("live-confirm-phrase-input"), { target: { value } });
	});
}

/**
 * Re-point the run read at its POST-live state. A provider job id may only exist
 * after the live click — seeding one earlier would (correctly) shut the gate on
 * the "no prior job" condition, so the pre-live and post-live reads differ.
 */
function primeLiveResult(items: unknown[]) {
	startProductionRun.mockResolvedValue({
		run_id: "prun_t2v0001",
		dry_run: false,
		status: "RUNNING",
		live_gate: "ONE_SERIAL_T2V",
		package_id: "wgp_t2v0001",
	});
	getProductionRun.mockResolvedValue({
		run: {
			production_run_id: "prun_t2v0001",
			dry_run: 0,
			status: "RUNNING",
			config_json: JSON.stringify({ last_dry_run_report: GREEN_REPORT }),
		},
		items,
	});
}

describe("Round F — T2V takes the dedicated route", () => {
	it("mints a T2V package via /t2v, never through the bridge (which rejects T2V)", async () => {
		primeT2V();
		renderPage();
		await runT2VChain();

		expect(createT2VGenerationPackage).toHaveBeenCalledWith(
			expect.objectContaining({
				product_id: "prod-t2v",
				workspace_execution_package_id: "wep_t2v0001",
				generation_mode: "SINGLE",
			}),
		);
		expect(createFromExecutionPackage).not.toHaveBeenCalled();
	});

	it("still routes F2V through the bridge", async () => {
		primeHappyPath();
		renderPage();
		await runChain();
		expect(createFromExecutionPackage).toHaveBeenCalledWith("wep_test0001", "F2V");
		expect(createT2VGenerationPackage).not.toHaveBeenCalled();
	});
});

describe("Round F — the live gate is locked by default", () => {
	it("is shut on load, before anything is selected", async () => {
		primeT2V();
		renderPage();
		const panel = await screen.findByTestId("live-gate-panel");
		expect(panel).toHaveAttribute("data-gate-open", "false");
		expect(screen.getByTestId("action-start-one-t2v-live")).toBeDisabled();
	});

	it("stays shut after a green dry run until the phrase is typed", async () => {
		primeT2V();
		renderPage();
		await runT2VChain();

		// Every condition except the phrase is met — the gate must still be shut.
		expect(screen.getByTestId("live-gate-check-mode-t2v")).toHaveAttribute("data-ok", "true");
		expect(screen.getByTestId("live-gate-check-dry-run-ready")).toHaveAttribute("data-ok", "true");
		expect(screen.getByTestId("live-gate-check-phrase")).toHaveAttribute("data-ok", "false");
		expect(screen.getByTestId("action-start-one-t2v-live")).toBeDisabled();
	});

	it("opens only once the EXACT phrase is typed", async () => {
		primeT2V();
		renderPage();
		await runT2VChain();

		// Near-misses must not open it.
		for (const wrong of [
			"authorize_one_t2v_live_run",
			"AUTHORIZE_ONE_T2V_LIVE_RUN ",
			"AUTHORIZE_ONE_T2V_LIVE",
			"yes",
		]) {
			await typePhrase(wrong);
			expect(screen.getByTestId("action-start-one-t2v-live")).toBeDisabled();
		}

		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		expect(screen.getByTestId("action-start-one-t2v-live")).toBeEnabled();
		expect(screen.getByTestId("live-gate-panel")).toHaveAttribute("data-gate-open", "true");
	});

	it("stays shut when the dry run is blocked, even with the right phrase", async () => {
		primeT2V({ checked: 1, ready: 0, blocked: 1, items: [{ package_id: "wgp_t2v0001", ok: false }] });
		renderPage();
		await runT2VChain();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");

		expect(screen.getByTestId("live-gate-check-dry-run-ready")).toHaveAttribute("data-ok", "false");
		expect(screen.getByTestId("action-start-one-t2v-live")).toBeDisabled();
	});

	it("stays shut for a non-T2V package, even with a green dry run and the right phrase", async () => {
		primeHappyPath();
		startProductionRun.mockResolvedValue({
			run_id: "prun_test0001",
			dry_run: true,
			report: GREEN_REPORT,
		});
		getProductionRun.mockResolvedValue({
			run: {
				production_run_id: "prun_test0001",
				dry_run: 1,
				status: "PENDING",
				config_json: JSON.stringify({ last_dry_run_report: GREEN_REPORT }),
			},
			items: [],
		});
		renderPage();
		await runChain();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");

		expect(screen.getByTestId("live-gate-check-mode-t2v")).toHaveAttribute("data-ok", "false");
		expect(screen.getByTestId("action-start-one-t2v-live")).toBeDisabled();
	});

	it("stays shut when the dry run covered more than one item", async () => {
		primeT2V({
			checked: 2,
			ready: 1,
			blocked: 0,
			items: [{ package_id: "wgp_t2v0001", ok: true }, { package_id: "wgp_t2v0002", ok: true }],
		});
		renderPage();
		await runT2VChain();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");

		expect(screen.getByTestId("live-gate-check-one-item")).toHaveAttribute("data-ok", "false");
		expect(screen.getByTestId("action-start-one-t2v-live")).toBeDisabled();
	});

	it("stays shut when the item already has a provider job id", async () => {
		primeT2V(GREEN_REPORT, [
			{ package_id: "wgp_t2v0001", production_status: "RUNNING", production_job_id: "job_prior" },
		]);
		renderPage();
		await runT2VChain();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");

		expect(screen.getByTestId("live-gate-check-no-prior-job")).toHaveAttribute("data-ok", "false");
		expect(screen.getByTestId("action-start-one-t2v-live")).toBeDisabled();
	});
});

describe("Round F — exactly one live submission", () => {
	it("sends exactly ONE live request, with the gate params", async () => {
		primeT2V();
		renderPage();
		await runT2VChain();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");

		startProductionRun.mockResolvedValue({
			run_id: "prun_t2v0001",
			dry_run: false,
			status: "RUNNING",
			live_gate: "ONE_SERIAL_T2V",
			package_id: "wgp_t2v0001",
		});
		await click("action-start-one-t2v-live");

		const liveCalls = startProductionRun.mock.calls.filter((c) => c[1] === true);
		expect(liveCalls).toHaveLength(1);
		expect(liveCalls[0]).toEqual([
			"prun_t2v0001",
			true,
			{
				live_gate: "ONE_SERIAL_T2V",
				confirm_phrase: "AUTHORIZE_ONE_T2V_LIVE_RUN",
				expect_package_id: "wgp_t2v0001",
			},
		]);
	});

	it("locks against double submit — a second click sends nothing", async () => {
		primeT2V();
		renderPage();
		await runT2VChain();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");

		startProductionRun.mockResolvedValue({
			run_id: "prun_t2v0001",
			dry_run: false,
			status: "RUNNING",
		});
		await click("action-start-one-t2v-live");
		await click("action-start-one-t2v-live");
		await click("action-start-one-t2v-live");

		expect(startProductionRun.mock.calls.filter((c) => c[1] === true)).toHaveLength(1);
		expect(screen.getByTestId("action-start-one-t2v-live")).toBeDisabled();
		expect(screen.getByTestId("live-gate-check-not-submitted")).toHaveAttribute("data-ok", "false");
	});

	it("stays locked after a server refusal and reports it truthfully", async () => {
		primeT2V();
		renderPage();
		await runT2VChain();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");

		startProductionRun.mockRejectedValue(new Error("LIVE_REQUIRES_EXACTLY_ONE_ITEM:2"));
		await click("action-start-one-t2v-live");

		expect(await screen.findByTestId("live-gate-refused")).toHaveTextContent(
			"LIVE_REQUIRES_EXACTLY_ONE_ITEM:2",
		);
		expect(screen.getByTestId("live-gate-refused")).toHaveTextContent(/nothing fired/i);
		// No fake success, and no retry loophole.
		expect(screen.queryByTestId("result-success")).not.toBeInTheDocument();
		expect(screen.getByTestId("action-start-one-t2v-live")).toBeDisabled();
	});
});

describe("Round F — result viewer", () => {
	it("shows nothing until a live job is started", async () => {
		primeT2V();
		renderPage();
		await runT2VChain();
		expect(screen.getByTestId("live-result-empty")).toBeInTheDocument();
		expect(screen.queryByTestId("live-result")).not.toBeInTheDocument();
	});

	it("renders the ids, the in-flight state and the duplicate-protection status", async () => {
		primeT2V();
		renderPage();
		await runT2VChain();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		primeLiveResult([
			{ package_id: "wgp_t2v0001", production_status: "RUNNING", production_job_id: "job_live_1" },
		]);
		await click("action-start-one-t2v-live");

		const result = await screen.findByTestId("live-result");
		expect(result).toHaveAttribute("data-terminal", "false");
		expect(result).toHaveAttribute("data-polling", "true");
		expect(screen.getByTestId("result-run-id")).toHaveTextContent("prun_t2v0001");
		expect(screen.getByTestId("result-wgp-id")).toHaveTextContent("wgp_t2v0001");
		expect(screen.getByTestId("result-job-id")).toHaveTextContent("job_live_1");
		expect(screen.getByTestId("result-in-flight")).toBeInTheDocument();
		expect(screen.getByTestId("result-duplicate-protection")).toHaveTextContent(
			/DUPLICATE_SUBMISSION_BLOCKED/,
		);
	});

	it("renders a terminal success with its artifact and stops polling", async () => {
		primeT2V();
		renderPage();
		await runT2VChain();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		primeLiveResult([
			{
				package_id: "wgp_t2v0001",
				production_status: "GENERATED",
				production_job_id: "job_live_1",
				artifact_media_ids: ["media_abc123"],
			},
		]);
		await click("action-start-one-t2v-live");

		const result = await screen.findByTestId("live-result");
		expect(result).toHaveAttribute("data-terminal", "true");
		expect(result).toHaveAttribute("data-polling", "false");
		expect(screen.getByTestId("result-success")).toHaveTextContent("GENERATED");
		expect(screen.getByTestId("result-artifact")).toHaveAttribute("data-media-id", "media_abc123");
		expect(screen.queryByTestId("result-in-flight")).not.toBeInTheDocument();
	});

	it("renders a terminal failure truthfully — no fake success", async () => {
		primeT2V();
		renderPage();
		await runT2VChain();
		await typePhrase("AUTHORIZE_ONE_T2V_LIVE_RUN");
		primeLiveResult([
			{
				package_id: "wgp_t2v0001",
				production_status: "FAILED",
				production_job_id: "job_live_1",
				production_error: "PROVIDER_REJECTED:CAPTCHA_FAILED",
			},
		]);
		await click("action-start-one-t2v-live");

		expect(await screen.findByTestId("result-failure")).toHaveTextContent(
			"PROVIDER_REJECTED:CAPTCHA_FAILED",
		);
		expect(screen.queryByTestId("result-success")).not.toBeInTheDocument();
		expect(screen.getByTestId("live-result")).toHaveAttribute("data-terminal", "true");
	});
});
