import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import CopySetRegistryPage from "./CopySetRegistryPage";

vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: ({ onSelect }: { onSelect: (p: unknown) => void }) => (
		<div data-testid="product-picker">
			Product picker
			<button
				type="button"
				data-testid="mock-select-p2"
				onClick={() =>
					onSelect({ id: "p2", raw_product_title: "Second Product", product_display_name: "Second Product", source: "MANUAL", category: "Skincare" })
				}
			>
				select p2
			</button>
			<button type="button" data-testid="mock-clear-product" onClick={() => onSelect(null)}>
				clear
			</button>
		</div>
	),
}));

vi.mock("../api/products", () => ({ fetchProductCatalog: vi.fn(), fetchProductDetail: vi.fn() }));
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

import { fetchProductCatalog, fetchProductDetail } from "../api/products";
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
const mockedProductDetail = vi.mocked(fetchProductDetail);
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
		// A healthy DRAFT (product truth ready + lineage matching) is current-authority
		// VALID — only the human approval step is outstanding. This mirrors the backend
		// projection (get_blueprint_current_authority_validation), where `valid` is
		// truth-readiness-based and independent of the DRAFT/approved status.
		current_authority_valid: status === "PRODUCTION_VALID" || status === "DRAFT",
		current_authority_activation_allowed: status === "PRODUCTION_VALID",
		current_authority_reason: status === "PRODUCTION_VALID" ? null : "EXPLICIT_HUMAN_APPROVAL_REQUIRED",
	};
}

// A DRAFT whose current authority is NOT valid (product truth stale/incomplete):
// it cannot be approved as-is and must render "Approval Blocked" with the reason.
function blockedDraftBlueprint() {
	return {
		...blueprint("DRAFT"),
		current_authority_valid: false,
		current_authority_reason: "V2_PRODUCT_TRUTH_APPROVAL_REQUIRED, EXPLICIT_HUMAN_APPROVAL_REQUIRED",
	};
}

// A blueprint whose PERSISTED status is historically approved (PRODUCTION_VALID)
// but whose CURRENT authority projection is stale — the Product Truth / evidence
// lineage advanced after approval. This is exactly the shape the backend returns
// for the reported COPY_V2_EVIDENCE_STALE incident, and the shape the Authority
// Library card must refuse to present as activatable.
function staleHistoricalBlueprint() {
	return {
		...blueprint("PRODUCTION_VALID"),
		current_authority_status: "STALE_AUTHORITY_LINEAGE",
		current_authority_valid: false,
		current_authority_activation_allowed: false,
		current_authority_reason: "COPY_V2_EVIDENCE_STALE",
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
		// The top angle and its evidence facts are auto-anchored; go straight to generate.
		await waitFor(() => expect(screen.getByTestId("generate-new-formula-copy")).toBeEnabled());
		fireEvent.click(screen.getByTestId("generate-new-formula-copy"));
		await waitFor(() => expect(mockedGenerate).toHaveBeenCalled());
		// Generation lands a DRAFT; approval now lives in the Authority Library tab.
		fireEvent.click(screen.getByTestId("tab-library"));
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

	// SMART auto-anchor: generating angles auto-selects the top angle AND its grounded
	// evidence facts, so the operator never maps facts one-by-one. Generation uses the
	// angle's facts; the manual editor stays available for adjustment.
	it("auto-anchors the angle's evidence facts so generation needs no manual fact mapping", async () => {
		renderPage();
		fireEvent.click(await screen.findByTestId("tab-generator"));
		await screen.findByTestId("product-truth-proof");
		fireEvent.change(await screen.findByTestId("v2-formula-picker"), { target: { value: "PAS" } });
		fireEvent.click(await screen.findByTestId("generate-angle-options"));
		await waitFor(() => expect(mockedAngles).toHaveBeenCalled());
		// Facts are auto-anchored from the top angle — the summary reflects it and
		// generate is enabled with zero manual ticking.
		expect(await screen.findByTestId("evidence-facts-summary")).toHaveTextContent(/auto-anchored/i);
		await waitFor(() => expect(screen.getByTestId("generate-new-formula-copy")).toBeEnabled());
		fireEvent.click(screen.getByTestId("generate-new-formula-copy"));
		// Generation carries the angle's grounded evidence facts.
		await waitFor(() => expect(mockedGenerate).toHaveBeenCalledWith(expect.objectContaining({ evidence_fact_ids: ["fact:p1:usp_json:0"] })));
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
		// Activation lives in the default Authority Library tab; the latest blueprint
		// is the review target on load.
		await screen.findByTestId("copy-library-view");

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

describe("Copy Authority Library — current-authority activation gate", () => {
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
		mockedActivate.mockResolvedValue({ blueprint_id: "bpv2_test", activated: true, bindings: [], required_lane_count: 8 });
	});

	function noActivation() {
		return { active_blueprint_id: null, active_revision: null, active_lane_count: 0, required_lane_count: 8, activated_at: null };
	}
	function activeOn(blueprintId: string) {
		return { active_blueprint_id: blueprintId, active_revision: 1, active_lane_count: 8, required_lane_count: 8, activated_at: "2026-08-15T00:00:00Z" };
	}

	// TEST 1 — a stale historical PRODUCTION_VALID blueprint must not be activatable.
	it("TEST 1 — stale historical PRODUCTION_VALID cannot be activated from the Library", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [staleHistoricalBlueprint()], activation: noActivation() });
		renderPage();
		await screen.findByTestId("copy-library-view");

		const activate = await screen.findByTestId("library-activate-bpv2_test");
		// The stale card is now actionable: it opens the review panel (regenerate /
		// revalidate) instead of being a dead disabled control — it just never activates.
		expect(activate).toBeEnabled();
		expect(activate).toHaveTextContent("Review / revalidate");
		// Truthful stale state + operator-friendly reason are surfaced.
		const stale = screen.getByTestId("library-stale-bpv2_test");
		expect(stale).toHaveTextContent(/revalidation required/i);
		expect(stale).toHaveTextContent(/current Product Truth/i);
		// Clicking the disabled control opens NO confirmation and calls NO activation.
		fireEvent.click(activate);
		expect(screen.queryByTestId("activation-confirm-overlay")).not.toBeInTheDocument();
		expect(mockedActivate).not.toHaveBeenCalled();
	});

	// TEST 2 — a stale historical V2_APPROVED blueprint is likewise non-activatable.
	it("TEST 2 — stale historical V2_APPROVED also cannot be activated", async () => {
		mockedList.mockResolvedValue({
			product_id: "p1",
			items: [{ ...staleHistoricalBlueprint(), status: "V2_APPROVED", current_authority_reason: "COPY_V2_TAXONOMY_AUTHORITY_STALE" }],
			activation: noActivation(),
		});
		renderPage();
		await screen.findByTestId("copy-library-view");

		const activate = await screen.findByTestId("library-activate-bpv2_test");
		expect(activate).toBeEnabled();
		expect(activate).toHaveTextContent("Review / revalidate");
		expect(screen.getByTestId("library-stale-bpv2_test")).toBeInTheDocument();
		fireEvent.click(activate);
		expect(screen.queryByTestId("activation-confirm-overlay")).not.toBeInTheDocument();
		expect(mockedActivate).not.toHaveBeenCalled();
	});

	// TEST 3 — a current PRODUCTION_VALID blueprint activates via confirm-exactly-once.
	it("TEST 3 — current PRODUCTION_VALID activates: confirm opens, cancel is a no-op, confirm activates once", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [blueprint("PRODUCTION_VALID")], activation: noActivation() });
		renderPage();
		await screen.findByTestId("copy-library-view");

		const activate = await screen.findByTestId("library-activate-bpv2_test");
		expect(activate).toBeEnabled();
		expect(activate).toHaveTextContent("Activate Authority");

		// First click opens the confirmation only.
		fireEvent.click(activate);
		expect(await screen.findByTestId("activation-confirm-overlay")).toBeInTheDocument();
		expect(mockedActivate).not.toHaveBeenCalled();

		// Cancel performs zero activation.
		fireEvent.click(screen.getByTestId("activation-cancel"));
		await waitFor(() => expect(screen.queryByTestId("activation-confirm-overlay")).not.toBeInTheDocument());
		expect(mockedActivate).not.toHaveBeenCalled();

		// Re-open and confirm activates exactly once.
		fireEvent.click(screen.getByTestId("library-activate-bpv2_test"));
		fireEvent.click(await screen.findByTestId("activation-confirm"));
		await waitFor(() => expect(mockedActivate).toHaveBeenCalledWith("bpv2_test"));
		expect(mockedActivate).toHaveBeenCalledTimes(1);
	});

	// TEST 4 — an active, current blueprint renders a truthful ACTIVE state, no redundant activation.
	it("TEST 4 — active and current renders truthful ACTIVE with no redundant activation", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [blueprint("PRODUCTION_VALID")], activation: activeOn("bpv2_test") });
		renderPage();
		await screen.findByTestId("copy-library-view");

		const card = await screen.findByTestId("library-card-bpv2_test");
		expect(card).toHaveTextContent("ACTIVE");
		expect(card).not.toHaveTextContent("STALE");
		const activate = screen.getByTestId("library-activate-bpv2_test");
		expect(activate).toBeDisabled();
		expect(activate).toHaveTextContent("Active in Creator");
		expect(screen.queryByTestId("library-stale-bpv2_test")).not.toBeInTheDocument();
		fireEvent.click(activate);
		expect(mockedActivate).not.toHaveBeenCalled();
	});

	// TEST 5 — an active but now-stale blueprint must NOT render a clean ACTIVE state.
	it("TEST 5 — active but stale renders a revalidation-required state, never a clean ACTIVE", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [staleHistoricalBlueprint()], activation: activeOn("bpv2_test") });
		renderPage();
		await screen.findByTestId("copy-library-view");

		const card = await screen.findByTestId("library-card-bpv2_test");
		expect(card).toHaveTextContent("ACTIVE · STALE — REVALIDATION REQUIRED");
		expect(screen.getByTestId("library-stale-bpv2_test")).toHaveTextContent(/Active authority is stale/i);
		const activate = screen.getByTestId("library-activate-bpv2_test");
		expect(activate).toBeEnabled();
		expect(activate).toHaveTextContent("Review / revalidate");
		fireEvent.click(activate);
		expect(screen.queryByTestId("activation-confirm-overlay")).not.toBeInTheDocument();
		expect(mockedActivate).not.toHaveBeenCalled();
	});

	// TEST 6 — a reviewable DRAFT offers an ACTIONABLE "Review & Approve" (never a
	// dead "Approval Required"), routes into the review workflow for THAT exact
	// blueprint, and never auto-approves or auto-activates.
	it("TEST 6 — reviewable DRAFT offers actionable Review & Approve and routes to the review workflow", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [blueprint("DRAFT")], activation: noActivation() });
		renderPage();
		await screen.findByTestId("copy-library-view");

		const reviewBtn = await screen.findByTestId("library-activate-bpv2_test");
		expect(reviewBtn).toBeEnabled();
		expect(reviewBtn).toHaveTextContent("Review & Approve");
		// A reviewable DRAFT is neither stale nor blocked.
		expect(screen.queryByTestId("library-stale-bpv2_test")).not.toBeInTheDocument();
		expect(screen.queryByTestId("library-blocked-bpv2_test")).not.toBeInTheDocument();
		// Clicking routes to the Direct V2 Authoring review workflow for THIS blueprint.
		fireEvent.click(reviewBtn);
		expect(await screen.findByTestId("v2-approval-panel")).toBeInTheDocument();
		expect(screen.getByTestId("review-target-indicator")).toHaveTextContent("bpv2_test");
		// It NEVER auto-approves or auto-activates.
		expect(mockedApprove).not.toHaveBeenCalled();
		expect(mockedActivate).not.toHaveBeenCalled();
	});

	// TEST 7 — a backend current-authority rejection stays fail-closed and refreshes the projection.
	it("TEST 7 — backend stale rejection is surfaced and the projection refreshes to the truthful state", async () => {
		// Page load sees an activatable blueprint; the post-failure refresh sees it stale.
		mockedList
			.mockResolvedValueOnce({ product_id: "p1", items: [blueprint("PRODUCTION_VALID")], activation: noActivation() })
			.mockResolvedValue({ product_id: "p1", items: [staleHistoricalBlueprint()], activation: noActivation() });
		mockedActivate.mockRejectedValue(
			new Error('{"detail":{"error":"COPY_V2_EVIDENCE_STALE","detail":"V2 blueprint is not production-valid and cannot bind"}}'),
		);
		renderPage();
		await screen.findByTestId("copy-library-view");

		const activate = await screen.findByTestId("library-activate-bpv2_test");
		expect(activate).toBeEnabled();
		fireEvent.click(activate);
		fireEvent.click(await screen.findByTestId("activation-confirm"));
		await waitFor(() => expect(mockedActivate).toHaveBeenCalledWith("bpv2_test"));

		// The backend failure is surfaced, not hidden or downgraded.
		expect(await screen.findByTestId("copy-registry-error")).toHaveTextContent(/COPY_V2_EVIDENCE_STALE/);
		// The projection refreshed → the card is now stale and non-actionable.
		expect(await screen.findByTestId("library-stale-bpv2_test")).toBeInTheDocument();
		expect(screen.getByTestId("library-activate-bpv2_test")).toHaveTextContent("Review / revalidate");
	});

	// TEST 8 — activation flows exclusively through the V2 authority contract (no legacy copy_set path).
	it("TEST 8 — activation uses the V2 contract signature only (no legacy /api/copy-sets path)", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [blueprint("PRODUCTION_VALID")], activation: noActivation() });
		renderPage();
		await screen.findByTestId("copy-library-view");

		fireEvent.click(await screen.findByTestId("library-activate-bpv2_test"));
		fireEvent.click(await screen.findByTestId("activation-confirm"));
		await waitFor(() => expect(mockedActivate).toHaveBeenCalledWith("bpv2_test"));
		// The V2 activation lane takes a bare blueprint_id; the retired copy_set
		// authoring contract is never invoked.
		expect(mockedActivate).toHaveBeenCalledTimes(1);
		expect(mockedActivate.mock.calls[0]).toEqual(["bpv2_test"]);
	});
});

describe("Copy Authority — module forensic closure (RULE 2 / RULE 3 / RULE 4)", () => {
	afterEach(cleanup);

	beforeEach(() => {
		vi.clearAllMocks();
		mockedCatalog.mockResolvedValue({ items: [product] } as never);
		mockedFormulas.mockResolvedValue({
			formulas: [{ formula_id: "PAS", formula_version: "pas.v1", display_name: "Problem Agitate Solution", definition_status: "CANONICAL", compiler_family: "PAS", slots: [], best_for: [], unsuitable_for: [] }],
		});
		mockedProviderStatus.mockResolvedValue({ lane: "text_assist", status: "READY", configured: true, provider_id: "p", model_id: "m", execution_enabled: true, provider_calls: 0 });
		mockedTruth.mockResolvedValue(truth);
		mockedActivate.mockResolvedValue({ blueprint_id: "bpv2_test", activated: true, bindings: [], required_lane_count: 8 });
		mockedApprove.mockResolvedValue({ blueprint: blueprint("PRODUCTION_VALID"), production_valid: true, badge: "V2 PRODUCTION_VALID" });
	});

	function noActivation() {
		return { active_blueprint_id: null, active_revision: null, active_lane_count: 0, required_lane_count: 8, activated_at: null };
	}
	function draftWith(id: string, angleDef: string) {
		return { ...blueprint("DRAFT"), blueprint_id: id, angle: { angle_id: `angle:${id}`, definition: angleDef } };
	}
	function renderAt(search: string) {
		return render(
			<MemoryRouter initialEntries={[`/creative/copy-authority${search}`]}>
				<Routes>
					<Route path="/creative/copy-authority" element={<CopySetRegistryPage />} />
				</Routes>
			</MemoryRouter>,
		);
	}

	// RULE 3 — the operator approves the EXACT non-latest DRAFT they selected, never blueprints[0].
	it("approves the exact selected non-latest DRAFT, not blueprints[0]", async () => {
		// items[0] is the newest (bp-new); the operator deliberately selects the older bp-old.
		mockedList.mockResolvedValue({ product_id: "p1", items: [draftWith("bp-new", "Newest angle"), draftWith("bp-old", "Older angle")], activation: noActivation() });
		renderPage();
		await screen.findByTestId("copy-library-view");

		fireEvent.click(await screen.findByTestId("library-activate-bp-old"));
		expect(await screen.findByTestId("review-target-indicator")).toHaveTextContent("bp-old");
		for (const key of ["semantic", "provenance", "safety", "bridge", "duration"]) {
			fireEvent.click(screen.getByTestId(`approval-check-${key}`));
		}
		fireEvent.click(screen.getByTestId("approve-v2-blueprint"));
		await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith(expect.objectContaining({ blueprint_id: "bp-old" })));
		expect(mockedApprove).toHaveBeenCalledTimes(1);
	});

	// RULE 3 — selecting a non-latest card in the Authority Library re-points approval.
	it("re-selects the review target via the library card, retargeting approval", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [draftWith("bp-new", "Newest angle"), draftWith("bp-old", "Older angle")], activation: noActivation() });
		renderPage();
		await screen.findByTestId("copy-library-view");
		// Default review target is the newest (bp-new); the library card retargets to bp-old.
		expect(await screen.findByTestId("review-target-indicator")).toHaveTextContent("bp-new");
		fireEvent.click(await screen.findByTestId("library-activate-bp-old"));
		expect(await screen.findByTestId("review-target-indicator")).toHaveTextContent("bp-old");
		for (const key of ["semantic", "provenance", "safety", "bridge", "duration"]) {
			fireEvent.click(screen.getByTestId(`approval-check-${key}`));
		}
		fireEvent.click(screen.getByTestId("approve-v2-blueprint"));
		await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith(expect.objectContaining({ blueprint_id: "bp-old" })));
	});

	// RULE 2 — a blocked DRAFT is non-actionable, with the authoritative reason + corrective path.
	it("renders a blocked DRAFT as Approval Blocked with reason, never a working approve", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [blockedDraftBlueprint()], activation: noActivation() });
		renderPage();
		await screen.findByTestId("copy-library-view");

		const btn = await screen.findByTestId("library-activate-bpv2_test");
		// The blocked draft is now openable (shows the blocker + regenerate) — never a
		// dead button — but it still never exposes a working approve.
		expect(btn).toBeEnabled();
		expect(btn).toHaveTextContent("Open blocked draft");
		const blocked = screen.getByTestId("library-blocked-bpv2_test");
		expect(blocked).toHaveTextContent(/Product Truth is not approved/i);
		expect(screen.queryByTestId("library-stale-bpv2_test")).not.toBeInTheDocument();
		fireEvent.click(btn);
		expect(mockedApprove).not.toHaveBeenCalled();
		expect(screen.queryByTestId("activation-confirm-overlay")).not.toBeInTheDocument();
	});

	// RULE 3 — a blueprint_id deep-link resolves to the EXACT blueprint and opens review.
	it("resolves a blueprint_id deep-link to the exact blueprint and opens the review workflow", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [blueprint("DRAFT")], activation: noActivation() });
		renderAt("?product_id=p1&blueprint_id=bpv2_test");

		expect(await screen.findByTestId("review-target-indicator")).toHaveTextContent("bpv2_test");
		expect(screen.getByTestId("v2-approval-panel")).toBeInTheDocument();
		expect(screen.queryByTestId("copy-registry-deeplink-error")).not.toBeInTheDocument();
	});

	// RULE 3 — an unresolvable blueprint_id deep-link fails VISIBLY (no silent fallback).
	it("fails visibly when a blueprint_id deep-link cannot be resolved", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [blueprint("DRAFT")], activation: noActivation() });
		renderAt("?product_id=p1&blueprint_id=bp-does-not-exist");

		expect(await screen.findByTestId("copy-registry-deeplink-error")).toHaveTextContent("bp-does-not-exist");
	});

	// RULE 4 — switching product clears stale library search and never hides the new product's copy.
	it("clears stale library search when the product is switched", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [blueprint("PRODUCTION_VALID")], activation: noActivation() });
		renderPage();
		await screen.findByTestId("copy-library-view");

		const searchInput = screen.getByPlaceholderText(/Search copy/i);
		fireEvent.change(searchInput, { target: { value: "zzz-no-match" } });
		expect(screen.queryByTestId("library-card-bpv2_test")).not.toBeInTheDocument();

		fireEvent.click(screen.getByTestId("mock-select-p2"));
		await waitFor(() => expect((screen.getByPlaceholderText(/Search copy/i) as HTMLInputElement).value).toBe(""));
		expect(await screen.findByTestId("library-card-bpv2_test")).toBeInTheDocument();
	});

	// GOVERNANCE — human approval gates remain required (no auto-approval).
	it("keeps the approve action gated on reviewer + all human review checks", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [blueprint("DRAFT")], activation: noActivation() });
		renderPage();
		await screen.findByTestId("copy-library-view");
		fireEvent.click(await screen.findByTestId("library-activate-bpv2_test"));

		const approve = await screen.findByTestId("approve-v2-blueprint");
		expect(approve).toBeDisabled();
		for (const key of ["semantic", "provenance", "safety", "bridge"]) {
			fireEvent.click(screen.getByTestId(`approval-check-${key}`));
		}
		expect(approve).toBeDisabled(); // one check still missing
		fireEvent.click(screen.getByTestId("approval-check-duration"));
		expect(approve).toBeEnabled();
		fireEvent.change(screen.getByTestId("v2-reviewer-input"), { target: { value: "" } });
		expect(approve).toBeDisabled();
		expect(mockedApprove).not.toHaveBeenCalled();
	});

	// RULE 4 — a successful approval refreshes the exact target to its approved state.
	it("refreshes to the approved state after a successful approval", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [blueprint("DRAFT")], activation: noActivation() });
		renderPage();
		await screen.findByTestId("copy-library-view");
		fireEvent.click(await screen.findByTestId("library-activate-bpv2_test"));
		for (const key of ["semantic", "provenance", "safety", "bridge", "duration"]) {
			fireEvent.click(await screen.findByTestId(`approval-check-${key}`));
		}
		fireEvent.click(screen.getByTestId("approve-v2-blueprint"));
		await waitFor(() => expect(mockedApprove).toHaveBeenCalledWith(expect.objectContaining({ blueprint_id: "bpv2_test", approved_by: "operator" })));
		expect(await screen.findByTestId("copy-registry-success")).toHaveTextContent(/PRODUCTION_VALID/i);
		expect(await screen.findByTestId("activate-v2-blueprint")).toBeInTheDocument();
	});
});

describe("Copy Authority — product deep-link by-id resolution (out-of-window)", () => {
	afterEach(cleanup);

	// A product that is NOT in the first-50 catalog window (mockedCatalog returns
	// only p1) — it must resolve via the deterministic by-id product-detail seam.
	const outProduct = { id: "p-out", raw_product_title: "Out Of Window Product", product_display_name: "Out Of Window Product", source: "MANUAL", category: "Skincare" };

	beforeEach(() => {
		vi.clearAllMocks();
		mockedCatalog.mockResolvedValue({ items: [product] } as never); // window excludes p-out
		mockedFormulas.mockResolvedValue({
			formulas: [{ formula_id: "PAS", formula_version: "pas.v1", display_name: "Problem Agitate Solution", definition_status: "CANONICAL", compiler_family: "PAS", slots: [], best_for: [], unsuitable_for: [] }],
		});
		mockedProviderStatus.mockResolvedValue({ lane: "text_assist", status: "READY", configured: true, provider_id: "p", model_id: "m", execution_enabled: true, provider_calls: 0 });
		mockedTruth.mockResolvedValue(truth);
		mockedList.mockResolvedValue({ product_id: "p-out", items: [], activation: { active_blueprint_id: null, active_revision: null, active_lane_count: 0, required_lane_count: 8, activated_at: null } });
	});

	function renderAt(search: string) {
		return render(
			<MemoryRouter initialEntries={[`/creative/copy-authority${search}`]}>
				<Routes>
					<Route path="/creative/copy-authority" element={<CopySetRegistryPage />} />
				</Routes>
			</MemoryRouter>,
		);
	}

	// first-50 MISS — an out-of-window product_id resolves via fetchProductDetail (no eager catalog load).
	it("resolves an out-of-window product_id via the by-id seam (no full-catalog load)", async () => {
		mockedProductDetail.mockResolvedValue(outProduct as never);
		renderAt("?product_id=p-out");
		await waitFor(() => expect(mockedProductDetail).toHaveBeenCalledWith("p-out"));
		// The deep-linked product resolves and its library renders — no manual selection.
		expect(await screen.findByTestId("copy-library-view")).toBeInTheDocument();
		expect(screen.queryByTestId("copy-registry-deeplink-error")).not.toBeInTheDocument();
	});

	// FAST PATH — an in-window product must NOT trigger a by-id fetch.
	it("uses the fast path for an in-window product and never calls the by-id seam", async () => {
		mockedProductDetail.mockResolvedValue(outProduct as never);
		renderAt("?product_id=p1"); // p1 is in the catalog window
		expect(await screen.findByTestId("copy-library-view")).toBeInTheDocument();
		expect(mockedProductDetail).not.toHaveBeenCalled();
	});

	// INVALID id — fails VISIBLY, never substitutes another product.
	it("fails visibly when an out-of-window product_id cannot be resolved", async () => {
		mockedProductDetail.mockRejectedValue(new Error("PRODUCT_NOT_FOUND"));
		renderAt("?product_id=p-bad");
		expect(await screen.findByTestId("copy-registry-deeplink-error")).toHaveTextContent("p-bad");
		// No product resolved → no library rendered, and no substitute was selected.
		expect(screen.queryByTestId("copy-library-view")).not.toBeInTheDocument();
	});

	// product_id + blueprint_id (both out-of-window) — resolve the EXACT product first,
	// then the EXACT blueprint. This is also the refresh case (fresh mount, full deep link).
	it("resolves product_id then blueprint_id for an out-of-window deep link (refresh-safe)", async () => {
		mockedProductDetail.mockResolvedValue(outProduct as never);
		mockedList.mockResolvedValue({ product_id: "p-out", items: [blueprint("PRODUCTION_VALID")], activation: { active_blueprint_id: null, active_revision: null, active_lane_count: 0, required_lane_count: 8, activated_at: null } });
		renderAt("?product_id=p-out&blueprint_id=bpv2_test");
		await waitFor(() => expect(mockedProductDetail).toHaveBeenCalledWith("p-out"));
		expect(await screen.findByTestId("review-target-indicator")).toHaveTextContent("bpv2_test");
		expect(screen.queryByTestId("copy-registry-deeplink-error")).not.toBeInTheDocument();
	});
});
