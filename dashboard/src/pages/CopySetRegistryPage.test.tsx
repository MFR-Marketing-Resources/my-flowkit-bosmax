import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import CopySetRegistryPage from "./CopySetRegistryPage";

vi.mock("../components/workspace/SearchableProductSelect", () => ({
	default: () => <div data-testid="product-picker">Product picker</div>,
}));

vi.mock("../api/products", () => ({ fetchProductCatalog: vi.fn() }));
vi.mock("../api/copyRegisterV2", () => ({
	fetchCopyRegisterFormulas: vi.fn(),
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
	fetchCopyRegisterTruth,
	generateCopyRegisterAngles,
	generateFormulaCopyBlueprint,
	listCopyRegisterBlueprints,
} from "../api/copyRegisterV2";

const mockedCatalog = vi.mocked(fetchProductCatalog);
const mockedFormulas = vi.mocked(fetchCopyRegisterFormulas);
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
	};
}

function renderPage() {
	return render(
		<MemoryRouter initialEntries={["/creative/copy-registry?product_id=p1"]}>
			<Routes>
				<Route path="/creative/copy-registry" element={<CopySetRegistryPage />} />
			</Routes>
		</MemoryRouter>,
	);
}

describe("CopySetRegistryPage V2 cutover", () => {
	beforeEach(() => {
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
		mockedTruth.mockResolvedValue(truth);
		mockedList.mockResolvedValue({ product_id: "p1", items: [] });
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
		expect(await screen.findByText("V2 PRODUCTION_VALID")).toBeInTheDocument();
		fireEvent.click(await screen.findByTestId("activate-v2-blueprint"));
		await waitFor(() => expect(mockedActivate).toHaveBeenCalledWith("bpv2_test"));
		expect(await screen.findByText("ACTIVE · 8 REQUIRED LANES")).toBeInTheDocument();
	});
});
