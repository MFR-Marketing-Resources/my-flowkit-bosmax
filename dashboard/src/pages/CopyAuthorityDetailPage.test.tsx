import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import CopyAuthorityDetailPage from "./CopyAuthorityDetailPage";

vi.mock("../api/copyRegisterV2", () => ({
	fetchCopyRegisterBlueprint: vi.fn(),
	listCopyRegisterBlueprints: vi.fn(),
	batchActivateCopyBlueprints: vi.fn(),
}));
vi.mock("../api/products", () => ({ fetchProductDetail: vi.fn() }));

import {
	batchActivateCopyBlueprints,
	fetchCopyRegisterBlueprint,
	listCopyRegisterBlueprints,
} from "../api/copyRegisterV2";
import { fetchProductDetail } from "../api/products";

const mockedBlueprint = vi.mocked(fetchCopyRegisterBlueprint);
const mockedList = vi.mocked(listCopyRegisterBlueprints);
const mockedActivate = vi.mocked(batchActivateCopyBlueprints);
const mockedProduct = vi.mocked(fetchProductDetail);

const baseBlueprint = {
	version: "2" as const,
	blueprint_id: "bp1",
	product_id: "p1",
	revision: 3,
	status: "PRODUCTION_VALID",
	formula_id: "PAS",
	formula_version: "pas.v1",
	objective: { objective_id: "conversion", definition: "Convert qualified buyers" },
	angle: { angle_id: "angle-1", definition: "A grounded angle" },
	stages: [
		{ stage_key: "hook", order: 0, authored_text: "Hook text", semantic_role: "HOOK", formula_stage_key: "hook", bridge: { entry: "OPEN", exit: "HOOK", continuity_requirements: [] }, claim_bearing: false, fact_refs: [], validation: { valid: true, error_codes: [] } },
		{ stage_key: "body", order: 1, authored_text: "Body text", semantic_role: "BODY_CORE", formula_stage_key: "body_core", bridge: { entry: "HOOK", exit: "BODY", continuity_requirements: [] }, claim_bearing: true, fact_refs: [{ fact_id: "fact-1", text_digest: "d", fact_kind: "BENEFIT" }], validation: { valid: true, error_codes: [] } },
		{ stage_key: "cta", order: 2, authored_text: "CTA text", semantic_role: "CTA", formula_stage_key: "cta", bridge: { entry: "BODY", exit: "DONE", continuity_requirements: [] }, claim_bearing: false, fact_refs: [], validation: { valid: true, error_codes: [] } },
	],
	evidence_refs: [{ fact_id: "fact-1", text_digest: "d", fact_kind: "BENEFIT" }],
	product_truth_lineage: { taxonomy_authority_fingerprint: "truth-1" },
	approval_snapshot: {},
	semantic_review: {},
	readiness_proof: {},
	approved_execution_text: [],
	estimated_word_count: 3,
	current_authority_status: "CURRENT · PRODUCTION_VALID",
	current_authority_valid: true,
	current_authority_activation_allowed: true,
	current_authority_reason: null,
	current_authority_mismatches: [],
	current_authority_fingerprint: "truth-1",
	blueprint_authority_fingerprint: "truth-1",
};

function renderPage() {
	return render(
		<MemoryRouter initialEntries={["/creative/copy-authority?product_id=p1&blueprint_id=bp1"]}>
			<Routes>
				<Route path="/creative/copy-authority" element={<CopyAuthorityDetailPage />} />
			</Routes>
		</MemoryRouter>,
	);
}

describe("CopyAuthorityDetailPage", () => {
	afterEach(cleanup);

	beforeEach(() => {
		vi.clearAllMocks();
		mockedBlueprint.mockResolvedValue(baseBlueprint as never);
		mockedProduct.mockResolvedValue({ id: "p1", product_display_name: "Product One", raw_product_title: "Product One", source: "MANUAL" } as never);
		mockedList.mockResolvedValue({ product_id: "p1", items: [baseBlueprint as never, { ...baseBlueprint, blueprint_id: "bp-other", product_id: "p1" } as never], activation: { active_blueprint_id: "bp1", active_revision: 3, active_lane_count: 8, required_lane_count: 8, activated_at: "2026-08-20T00:00:00Z" } });
		mockedActivate.mockResolvedValue({ results: [{ blueprint_id: "bp1", activated: true, idempotent: false, status: "ACTIVATED", lane_count: 8, error_code: null }], activated_count: 1, idempotent_count: 0, failed_count: 0, activation_mutations: 1, bound_lane_count: 8, provider_calls: 0, credit_spend: 0 });
	});

	it("renders one exact blueprint as a minimal detail surface", async () => {
		renderPage();
		expect(await screen.findByTestId("copy-authority-detail-page")).toBeInTheDocument();
		expect(screen.getByTestId("authority-blueprint-id")).toHaveTextContent("bp1");
		expect(screen.getByText("Hook text")).toBeInTheDocument();
		expect(screen.queryByText("bp-other")).not.toBeInTheDocument();
		expect(screen.queryByTestId("authority-product-selector")).not.toBeInTheDocument();
		expect(screen.queryByTestId("authority-generator-tab")).not.toBeInTheDocument();
		expect(screen.queryByTestId("authority-activation-queue")).not.toBeInTheDocument();
	});

	it("shows CURRENT without redundant activation", async () => {
		renderPage();
		expect(await screen.findByTestId("authority-state-current")).toBeInTheDocument();
		expect(screen.queryByTestId("authority-activate-button")).not.toBeInTheDocument();
	});

	it("shows a governed exact activation only for READY", async () => {
		mockedList.mockResolvedValue({ product_id: "p1", items: [baseBlueprint as never], activation: { active_blueprint_id: null, active_revision: null, active_lane_count: 0, required_lane_count: 8, activated_at: null } });
		renderPage();
		expect(await screen.findByTestId("authority-state-ready")).toBeInTheDocument();
		fireEvent.click(screen.getByTestId("authority-activate-button"));
		expect(screen.getByTestId("authority-activation-confirm")).toBeInTheDocument();
		expect(mockedActivate).not.toHaveBeenCalled();
	});

	it("routes STALE to replacement authoring and DRAFT to Governance Queue", async () => {
		mockedBlueprint.mockResolvedValue({ ...baseBlueprint, current_authority_valid: false, current_authority_activation_allowed: false, current_authority_status: "STALE_AUTHORITY_LINEAGE", current_authority_reason: "COPY_V2_EVIDENCE_STALE" } as never);
		mockedList.mockResolvedValue({ product_id: "p1", items: [], activation: { active_blueprint_id: null, active_revision: null, active_lane_count: 0, required_lane_count: 8, activated_at: null } });
		renderPage();
		expect(await screen.findByTestId("authority-state-stale")).toHaveTextContent("Product Truth");
		expect(screen.getByTestId("authority-open-landbank")).toHaveAttribute("href", "/creative/storyboard-landbank-v3?product_id=p1");

		mockedBlueprint.mockResolvedValue({ ...baseBlueprint, status: "DRAFT", current_authority_status: "DRAFT", current_authority_valid: true, current_authority_activation_allowed: false, current_authority_reason: "EXPLICIT_HUMAN_APPROVAL_REQUIRED" } as never);
		cleanup();
		renderPage();
		expect(await screen.findByTestId("authority-state-draft")).toBeInTheDocument();
		expect(screen.getByTestId("authority-open-governance")).toHaveAttribute("href", "/creative/copy-review-queue?product_id=p1");
	});
});
