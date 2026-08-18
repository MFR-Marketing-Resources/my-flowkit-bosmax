import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import CopySetRegistryPage from "./CopySetRegistryPage";

vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: () => <div data-testid="product-picker">Product picker</div>,
}));

vi.mock("../api/products", () => ({ fetchProductCatalog: vi.fn() }));
vi.mock("../api/copyRegisterV2", () => ({
	fetchCopyRegisterFormulas: vi.fn(),
	fetchCopyRegisterProviderStatus: vi.fn(),
	fetchCopyRegisterTruth: vi.fn(),
	generateCopyRegisterAngles: vi.fn(),
	generateFormulaCopyBlueprint: vi.fn(),
	listCopyRegisterBlueprints: vi.fn(),
	regenerateFormulaStage: vi.fn(),
	approveFormulaBlueprint: vi.fn(),
	activateFormulaBlueprint: vi.fn(),
}));

import { fetchProductCatalog } from "../api/products";
import {
	approveFormulaBlueprint,
	activateFormulaBlueprint,
	fetchCopyRegisterFormulas,
	fetchCopyRegisterProviderStatus,
	fetchCopyRegisterTruth,
	generateCopyRegisterAngles,
	generateFormulaCopyBlueprint,
	listCopyRegisterBlueprints,
} from "../api/copyRegisterV2";

const mockedCatalog = vi.mocked(fetchProductCatalog);
const mockedFormulas = vi.mocked(fetchCopyRegisterFormulas);
const mockedProviderStatus = vi.mocked(fetchCopyRegisterProviderStatus);
const mockedTruth = vi.mocked(fetchCopyRegisterTruth);
const mockedAngles = vi.mocked(generateCopyRegisterAngles);
const mockedGenerate = vi.mocked(generateFormulaCopyBlueprint);
const mockedList = vi.mocked(listCopyRegisterBlueprints);
const mockedApprove = vi.mocked(approveFormulaBlueprint);
const mockedActivate = vi.mocked(activateFormulaBlueprint);

const product = {
	id: "p1",
	raw_product_title: "Synthetic Product",
	product_display_name: "Synthetic Product",
	source: "MANUAL",
	category: "Skincare",
};

const fact = {
	snapshot_id: "snapshot-p1-v1",
	fact_id: "fact:p1:usp_json:0",
	product_id: "p1",
	fact_kind: "USP",
	text: "formula ringan",
	text_digest: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
	snapshot_version: 1,
	snapshot_status: "APPROVED",
	approved: true,
};

const truth = {
	product_id: "p1",
	product: {
		display_name: "Synthetic Product",
		category: "Skincare",
		subcategory: "Serum",
		product_type: "Topical",
		product_family: "",
		cluster: "",
	},
	product_truth: {
		approved: true,
		snapshot: {
			snapshot_id: "snapshot-p1-v1",
			version: 1,
			status: "APPROVED",
			digest: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
			approved_by: "truth-reviewer",
			approved_at: "2026-08-14T00:00:00Z",
		},
		lineage: {},
		persona: { audience: "qualified buyers" },
		allowed_claims: ["formula ringan"],
		blocked_claims: [],
		warnings: [],
	},
	facts: [fact],
	blockers: [],
	ready_for_copy: true,
};

function blueprint(status: string = "DRAFT") {
	return {
		version: "2" as const,
		blueprint_id: "bpv2_test",
		product_id: "p1",
		revision: 1,
		status,
		formula_id: "PAS",
		formula_version: "pas.v1",
		objective: { objective_id: "conversion", definition: "A grounded objective" },
		angle: { angle_id: "angle:test:0", definition: "formula ringan" },
		stages: [
			{ stage_key: "stage-0-problem", order: 0, authored_text: "Problem", semantic_role: "problem", formula_stage_key: "problem", bridge: { entry: "OPEN", exit: "ONE", continuity_requirements: [] }, claim_bearing: true, fact_refs: [fact], validation: { valid: true, error_codes: [] } },
			{ stage_key: "stage-1-agitate", order: 1, authored_text: "Agitate", semantic_role: "agitate", formula_stage_key: "agitate", bridge: { entry: "ONE", exit: "TWO", continuity_requirements: [] }, claim_bearing: true, fact_refs: [fact], validation: { valid: true, error_codes: [] } },
			{ stage_key: "stage-2-solution", order: 2, authored_text: "Solution", semantic_role: "solution", formula_stage_key: "solution", bridge: { entry: "TWO", exit: "THREE", continuity_requirements: [] }, claim_bearing: true, fact_refs: [fact], validation: { valid: true, error_codes: [] } },
			{ stage_key: "stage-3-cta", order: 3, authored_text: "CTA", semantic_role: "cta", formula_stage_key: "cta", bridge: { entry: "THREE", exit: "DONE", continuity_requirements: [] }, claim_bearing: false, fact_refs: [], validation: { valid: true, error_codes: [] } },
		],
		evidence_refs: [fact],
		product_truth_lineage: {},
		approval_snapshot: status === "PRODUCTION_VALID" ? {} : null,
		semantic_review: status === "PRODUCTION_VALID" ? {} : null,
		readiness_proof: status === "PRODUCTION_VALID" ? {} : null,
		approved_execution_text: status === "PRODUCTION_VALID" ? [{ stage_key: "stage-0-problem", text: "Problem" }] : [],
		estimated_word_count: 4,
		v2_badge: status === "PRODUCTION_VALID" ? "V2 PRODUCTION_VALID" : null,
		current_authority_status: status === "PRODUCTION_VALID" ? "CURRENT · PRODUCTION_VALID" : "DRAFT",
		current_authority_valid: status === "PRODUCTION_VALID",
		current_authority_activation_allowed: status === "PRODUCTION_VALID",
		current_authority_reason: status === "PRODUCTION_VALID" ? null : "EXPLICIT_HUMAN_APPROVAL_REQUIRED",
	};
}

function renderPage() {
	return render(
		<MemoryRouter initialEntries={["/creative/copy-authority?product_id=p1"]}>
			<Routes>
				<Route path="/creative/copy-authority" element={<CopySetRegistryPage />} />
			</Routes>
		</MemoryRouter>,
	);
}

describe("CopySetRegistryPage V2 cutover", () => {
	afterEach(cleanup);

	beforeEach(() => {
		vi.clearAllMocks();
		mockedCatalog.mockResolvedValue({ items: [product] } as never);
		mockedFormulas.mockResolvedValue({
			formulas: [{
				formula_id: "PAS",
				formula_version: "pas.v1",
				display_name: "Problem Agitate Solution",
				definition_status: "CANONICAL",
				compiler_family: "PAS",
				slots: [],
				best_for: [],
				unsuitable_for: [],
			}],
		});
		mockedProviderStatus.mockResolvedValue({
			lane: "text_assist",
			status: "READY",
			configured: true,
			provider_id: "synthetic-test-provider",
			model_id: "synthetic-test-model",
			execution_enabled: true,
			provider_calls: 0,
		});
		mockedTruth.mockResolvedValue(truth);
		mockedList.mockResolvedValue({
			product_id: "p1",
			items: [],
			activation: {
				active_blueprint_id: null,
				active_revision: null,
				active_lane_count: 0,
				required_lane_count: 8,
				activated_at: null,
			},
		});
		mockedAngles.mockResolvedValue({
			angles: [{ angle_id: "angle:test:0", definition: "formula ringan", evidence_fact_ids: [fact.fact_id], source: "APPROVED_PRODUCT_TRUTH" }],
			facts: [fact],
			formula_id: "PAS",
			formula_version: "pas.v1",
		});
		mockedGenerate.mockResolvedValue({ blueprint: blueprint(), production_valid: false });
		mockedApprove.mockResolvedValue({ blueprint: blueprint("PRODUCTION_VALID"), production_valid: true, badge: "V2 PRODUCTION_VALID" });
		mockedActivate.mockResolvedValue({
			blueprint_id: "bpv2_test",
			activated: true,
			bindings: [],
			required_lane_count: 8,
		});
	});

	it("walks product → truth → formula → angle/evidence → new V2 blueprint → approval", async () => {
		renderPage();
		expect(await screen.findByTestId("copy-set-registry-page")).toBeInTheDocument();
		// Copy Authority now defaults to the inspection Library; switch to the
		// advanced direct-authoring tab to exercise the generator flow.
		fireEvent.click(screen.getByTestId("tab-generator"));
		expect(await screen.findByTestId("product-truth-proof")).toBeInTheDocument();

		fireEvent.change(await screen.findByTestId("v2-formula-picker"), { target: { value: "PAS" } });
		fireEvent.click(await screen.findByTestId("generate-angle-options"));
		await waitFor(() => expect(mockedAngles).toHaveBeenCalledWith({ product_id: "p1", formula_id: "PAS", objective: "conversion" }));
		fireEvent.click(screen.getByRole("radio", { name: /formula ringan/ }));
		fireEvent.click(screen.getByRole("checkbox"));
		fireEvent.click(screen.getByTestId("generate-new-formula-copy"));
		await waitFor(() => expect(mockedGenerate).toHaveBeenCalled());
		expect(await screen.findByTestId("v2-blueprint-card")).toHaveTextContent("bpv2_test");
		expect(screen.getByTestId("v2-approval-panel")).toBeInTheDocument();

		for (const key of ["semantic", "provenance", "safety", "bridge", "duration"]) {
			fireEvent.click(screen.getByTestId(`approval-check-${key}`));
		}
		fireEvent.click(screen.getByTestId("approve-v2-blueprint"));
		await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith(expect.objectContaining({
			blueprint_id: "bpv2_test",
			approved_by: "operator",
			semantic_review: expect.objectContaining({ decision: "APPROVED" }),
			readiness_proof: expect.objectContaining({ safety_validated: true }),
		})));
		expect(await screen.findByText("CURRENT · PRODUCTION_VALID")).toBeInTheDocument();
		// Global activation is now gated behind an explicit confirmation dialog.
		fireEvent.click(await screen.findByTestId("activate-v2-blueprint"));
		expect(mockedActivate).not.toHaveBeenCalled();
		fireEvent.click(await screen.findByTestId("activation-confirm"));
		await waitFor(() => expect(mockedActivate).toHaveBeenCalledWith("bpv2_test"));
		expect(await screen.findByText("ACTIVE · 8 REQUIRED LANES")).toBeInTheDocument();
	});

	it("shows exact fail-closed reasons and never enables authoring without text_assist", async () => {
		mockedProviderStatus.mockResolvedValue({
			lane: "text_assist",
			status: "NOT_CONFIGURED",
			configured: false,
			provider_id: null,
			model_id: null,
			execution_enabled: false,
			provider_calls: 0,
		});
		renderPage();
		fireEvent.click(await screen.findByTestId("tab-generator"));
		await screen.findByTestId("product-truth-proof");

		expect(screen.getByTestId("generate-angle-disabled-reasons")).toHaveTextContent("formula required");
		expect(screen.getByTestId("generate-angle-disabled-reasons")).toHaveTextContent("Text Assist provider not configured");
		expect(screen.getByTestId("generate-blueprint-disabled-reasons")).toHaveTextContent("angle required");
		expect(screen.getByTestId("generate-blueprint-disabled-reasons")).toHaveTextContent("select 1–5 evidence facts");
		expect(screen.getByText("Requires a selected angle and at least one approved evidence fact.")).toBeInTheDocument();
		expect(screen.getByText("This step makes one additional text-assist call; it does not spend video/image credits.")).toBeInTheDocument();

		fireEvent.change(screen.getByTestId("v2-formula-picker"), { target: { value: "PAS" } });
		expect(screen.getByTestId("generate-angle-options")).toBeDisabled();
		expect(screen.getByTestId("generate-new-formula-copy")).toBeDisabled();
	});

	it("names Product Truth as the blocking authority when it is not ready", async () => {
		mockedTruth.mockResolvedValue({
			...truth,
			ready_for_copy: false,
			blockers: ["PRODUCT_TRUTH_NOT_APPROVED"],
		});
		renderPage();
		fireEvent.click(await screen.findByTestId("tab-generator"));
		await screen.findByTestId("product-truth-proof");

		expect(screen.getByTestId("generate-angle-disabled-reasons")).toHaveTextContent("Product Truth not ready");
		expect(screen.getByTestId("generate-blueprint-disabled-reasons")).toHaveTextContent("Product Truth not ready");
		expect(screen.getByTestId("generate-angle-options")).toBeDisabled();
		expect(screen.getByTestId("generate-new-formula-copy")).toBeDisabled();
	});

	it("hydrates the persisted all-lane activation state after reload", async () => {
		mockedList.mockResolvedValue({
			product_id: "p1",
			items: [blueprint("PRODUCTION_VALID")],
			activation: {
				active_blueprint_id: "bpv2_test",
				active_revision: 1,
				active_lane_count: 8,
				required_lane_count: 8,
				activated_at: "2026-08-15T00:00:00Z",
			},
		});
		renderPage();
		fireEvent.click(await screen.findByTestId("tab-generator"));

		expect(await screen.findByText("ACTIVE · 8 REQUIRED LANES")).toBeInTheDocument();
		expect(screen.getByTestId("activate-v2-blueprint")).toBeDisabled();
		expect(mockedActivate).not.toHaveBeenCalled();
	});
});

describe("Task B — Copy Authority surface consolidation", () => {
	afterEach(cleanup);

	beforeEach(() => {
		vi.clearAllMocks();
		mockedCatalog.mockResolvedValue({ items: [product] } as never);
		mockedFormulas.mockResolvedValue({
			formulas: [{
				formula_id: "PAS",
				formula_version: "pas.v1",
				display_name: "Problem Agitate Solution",
				definition_status: "CANONICAL",
				compiler_family: "PAS",
				slots: [],
				best_for: [],
				unsuitable_for: [],
			}],
		});
		mockedProviderStatus.mockResolvedValue({
			lane: "text_assist",
			status: "READY",
			configured: true,
			provider_id: "synthetic-test-provider",
			model_id: "synthetic-test-model",
			execution_enabled: true,
			provider_calls: 0,
		});
		mockedTruth.mockResolvedValue(truth);
		mockedList.mockResolvedValue({
			product_id: "p1",
			items: [],
			activation: { active_blueprint_id: null, active_revision: null, active_lane_count: 0, required_lane_count: 8, activated_at: null },
		});
		mockedActivate.mockResolvedValue({ blueprint_id: "bpv2_test", activated: true, bindings: [], required_lane_count: 8 });
	});

	// Test B — Copy Authority signposts itself as the ADVANCED console.
	it("presents itself as the advanced Copy Authority console with a Landbank advisory", async () => {
		renderPage();
		expect(await screen.findByTestId("copy-authority-title")).toHaveTextContent("Copy Authority");
		expect(screen.getByText(/Advanced V2 authority inspection, exception authoring and production activation/i)).toBeInTheDocument();
		expect(screen.getByTestId("copy-authority-advisory")).toHaveTextContent(/Normal campaign copy should be created in Copywriting Landbank/i);
	});

	// Test C — defaults to inspection (Authority Library), NOT the direct generator.
	it("defaults to the Authority Library, not the direct generator", async () => {
		renderPage();
		expect(await screen.findByTestId("copy-library-view")).toBeInTheDocument();
		expect(screen.queryByTestId("product-truth-proof")).not.toBeInTheDocument();
	});

	// Test D — direct V2 authoring still works when the advanced tab is chosen.
	it("runs direct V2 authoring only when the advanced tab is selected", async () => {
		renderPage();
		await screen.findByTestId("copy-library-view");
		fireEvent.click(screen.getByTestId("tab-generator"));
		expect(await screen.findByTestId("product-truth-proof")).toBeInTheDocument();
		expect(screen.getByTestId("v2-formula-picker")).toBeInTheDocument();
	});

	// Test G — the selected product is carried to Copywriting Landbank.
	it("hands the selected product off to Copywriting Landbank", async () => {
		renderPage();
		// Wait until the deep-linked product is selected (the Library view requires it)
		// so the advisory bridge has resolved the product_id into its href.
		await screen.findByTestId("copy-library-view");
		const link = screen.getByTestId("open-copywriting-landbank");
		expect(link).toHaveAttribute("href", "/creative/storyboard-landbank-v3?product_id=p1");
	});

	// Test E — global activation from the Library requires explicit confirmation.
	it("requires explicit confirmation before global activation", async () => {
		mockedList.mockResolvedValue({
			product_id: "p1",
			items: [blueprint("PRODUCTION_VALID")],
			activation: { active_blueprint_id: null, active_revision: null, active_lane_count: 0, required_lane_count: 8, activated_at: null },
		});
		renderPage();

		fireEvent.click(await screen.findByTestId("library-activate-bpv2_test"));
		// Dialog is shown; nothing is activated yet.
		expect(await screen.findByTestId("activation-confirm-overlay")).toBeInTheDocument();
		expect(mockedActivate).not.toHaveBeenCalled();

		// Cancelling must not activate.
		fireEvent.click(screen.getByTestId("activation-cancel"));
		await waitFor(() => expect(screen.queryByTestId("activation-confirm-overlay")).not.toBeInTheDocument());
		expect(mockedActivate).not.toHaveBeenCalled();

		// Re-open and confirm activates exactly once.
		fireEvent.click(screen.getByTestId("library-activate-bpv2_test"));
		fireEvent.click(await screen.findByTestId("activation-confirm"));
		await waitFor(() => expect(mockedActivate).toHaveBeenCalledWith("bpv2_test"));
	});
});
