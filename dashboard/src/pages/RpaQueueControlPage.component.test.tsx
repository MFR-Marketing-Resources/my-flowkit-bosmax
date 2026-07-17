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
}));
vi.mock("../api/productionQueue", () => ({
	approvePackages: (...a: unknown[]) => approvePackages(...a),
	createProductionRun: (...a: unknown[]) => createProductionRun(...a),
	startProductionRun: (...a: unknown[]) => startProductionRun(...a),
	getProductionRun: (...a: unknown[]) => getProductionRun(...a),
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
			"live-generation-locked",
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

describe("Round E — live generation safety gate", () => {
	it("never calls startProductionRun with confirmLiveCreditBurn=true", async () => {
		primeHappyPath();
		renderPage();
		await runChain();

		expect(startProductionRun).toHaveBeenCalled();
		for (const callArgs of startProductionRun.mock.calls) {
			// The second argument is confirmLiveCreditBurn. It must be false on EVERY call.
			expect(callArgs[1]).toBe(false);
			expect(callArgs[1]).not.toBe(true);
		}
	});

	it("renders live generation as locked and exposes no live control", async () => {
		primeHappyPath();
		renderPage();
		const lock = await screen.findByTestId("live-generation-locked");
		expect(lock).toHaveAttribute("data-locked", "true");
		expect(lock).toHaveTextContent(/Round F/i);
		// No live/burn control exists on this page in any state.
		expect(screen.queryByTestId("action-run-live")).not.toBeInTheDocument();
		expect(screen.queryByText(/burns credits/i)).not.toBeInTheDocument();
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
