import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProductIntelligenceReviewDraftPanel, {
	describeApprovalBlockers,
	formatReviewDraftError,
} from "./ProductIntelligenceReviewDraftPanel";
import type { ProductIntelligenceReviewDraft, ProductIntelligenceReviewDraftValidationResponse } from "../../types";
import {
	aiFillMissingProductIntelligenceReviewDraft,
	fetchProductIntelligenceReviewDraft,
	fetchProductIntelligenceReviewDrafts,
} from "../../api/products";

vi.mock("../../api/products", () => ({
	fetchProductIntelligenceReviewDrafts: vi
		.fn()
		.mockResolvedValue({ product_id: "p1", items: [] }),
	fetchProductIntelligenceReviewDraft: vi.fn(),
	createProductIntelligenceReviewDraft: vi.fn(),
	prepareProductForCopywriting: vi.fn(),
	aiFillMissingProductIntelligenceReviewDraft: vi.fn(),
	updateProductIntelligenceReviewDraft: vi.fn(),
	validateProductIntelligenceReviewDraft: vi.fn(),
	approveProductIntelligenceReviewDraft: vi.fn(),
	rejectProductIntelligenceReviewDraft: vi.fn(),
}));

function makeDraft(overrides: Partial<ProductIntelligenceReviewDraft> = {}): ProductIntelligenceReviewDraft {
	return {
		draft_id: "d1", product_id: "p1", review_status: "NEEDS_REVISION",
		product_description: null, benefits_json: [], usp_json: [], usage_text: null,
		ingredients_text: null, warnings_text: null, target_customer_text: null,
		paste_anything_summary: null, source_urls_json: {}, image_evidence_json: {},
		package_notes: null, size_or_volume: null, product_form_factor: null,
		packaging_description: null, product_truth_lock: null, claim_gate: "CLAIM_REVIEW_REQUIRED",
		claim_risk_level: "LOW", claim_tokens_json: [], allowed_claims_json: [], blocked_claims_json: [],
		buyer_persona_snapshot_json: {}, copy_strategy_summary_json: {}, confidence_score: null,
		completeness_score: null, readiness_status: "MISSING_REQUIRED_FIELDS", reviewer_note: null,
		created_by: "promo", reviewed_by: null, approved_by: null, approved_at: null,
		rejected_by: null, rejected_at: null, created_at: "2026-07-15T00:00:00Z",
		updated_at: "2026-07-15T00:00:00Z", provenance_items: [],
		...overrides,
	};
}

describe("ProductIntelligenceReviewDraftPanel", () => {
	afterEach(() => cleanup());

	it("[UI smoke] renders the Prepare with AI (DeepSeek) button next to Create", async () => {
		render(
			<ProductIntelligenceReviewDraftPanel
				productId="p1"
				onApproved={async () => {}}
			/>,
		);
		expect(
			await screen.findByRole("button", { name: /Prepare with AI/i }),
		).toBeInTheDocument();
		expect(
			await screen.findByRole("button", { name: /Create Review Draft/i }),
		).toBeInTheDocument();
	});

	it("[AI Fill] shows distinct Recompute and AI Fill Missing controls and renders proposals", async () => {
		const draft = makeDraft();
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1", items: [draft],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(
			makeDraft({ product_description: "Insulated steel bottle." }),
		);
		vi.mocked(aiFillMissingProductIntelligenceReviewDraft).mockResolvedValue({
			draft_id: "d1", product_id: "p1", review_status: "NEEDS_REVISION",
			provider: "deepseek", model: "deepseek-chat", prompt_version: "product_intel_ai_fill_v1",
			generated_at: "2026-07-15T00:00:00Z", targeted_fields: ["product_description"],
			proposed: [{ field: "product_description", status: "FACT", confidence: 0.9, rationale: "title", previous_value: null, proposed_value: "Insulated steel bottle." }],
			unresolved: [{ field: "warnings_text", status: "INSUFFICIENT_EVIDENCE", rationale: "no evidence" }],
			provider_configured: true,
		});

		render(<ProductIntelligenceReviewDraftPanel productId="p1" onApproved={async () => {}} />);

		// Recompute (deterministic) and AI Fill Missing (DeepSeek) are DISTINCT controls.
		const aiFillBtn = await screen.findByTestId("ai-fill-missing-button");
		expect(aiFillBtn).toHaveTextContent(/AI Fill Missing/i);
		expect(screen.getByRole("button", { name: /Recompute/i })).toBeInTheDocument();
		// Helper text explains both, without conflating them.
		expect(screen.getByText(/deterministic, no AI/i)).toBeInTheDocument();
		expect(screen.getByText(/uses DeepSeek/i)).toBeInTheDocument();

		fireEvent.click(aiFillBtn);
		await waitFor(() =>
			expect(aiFillMissingProductIntelligenceReviewDraft).toHaveBeenCalledWith("d1"),
		);
		const result = await screen.findByTestId("ai-fill-result");
		expect(result).toHaveTextContent("product_description");
		expect(result).toHaveTextContent("deepseek");
		expect(result).toHaveTextContent(/insufficient evidence/i);
	});

	it("formatReviewDraftError turns a raw 409 into a human, actionable message", () => {
		const raw = new Error(
			'API 409: {"detail":"DRAFT_NOT_APPROVABLE:MISSING_REQUIRED_FIELDS:source_urls_json|CLAIM_BLOCKED:rawat,penyakit,ubat"}',
		);
		const msg = formatReviewDraftError(raw, "fallback");
		// No raw JSON / no "API 409" dumped at the operator.
		expect(msg).not.toContain("API 409");
		expect(msg).not.toContain("{");
		// Both blockers are explained with their specifics.
		expect(msg).toContain("source_urls_json");
		expect(msg).toContain("rawat,penyakit,ubat");
		expect(msg.toLowerCase()).toContain("belum boleh diluluskan");
	});

	it("formatReviewDraftError passes a non-approval error through unchanged", () => {
		expect(
			formatReviewDraftError(new Error("Source URLs must be valid JSON."), "fallback"),
		).toBe("Source URLs must be valid JSON.");
		expect(formatReviewDraftError("not-an-error", "fallback")).toBe("fallback");
	});

	const baseReport = (
		over: Partial<ProductIntelligenceReviewDraftValidationResponse>,
	): ProductIntelligenceReviewDraftValidationResponse =>
		({
			draft: {} as never,
			missing_required_fields: [],
			present_required_fields: [],
			completeness_score: 1,
			readiness_status: "READY_FOR_APPROVAL",
			claim_gate: "CLAIM_SAFE",
			claim_risk_level: "LOW",
			claim_tokens_json: [],
			allowed_claims_json: [],
			blocked_claims_json: [],
			approval_blockers: [],
			...over,
		}) as ProductIntelligenceReviewDraftValidationResponse;

	it("describeApprovalBlockers summarises structured blockers, or null when clean", () => {
		expect(describeApprovalBlockers(baseReport({}))).toBeNull();

		const msg = describeApprovalBlockers(
			baseReport({
				missing_required_fields: ["source_urls_json"],
				claim_gate: "CLAIM_BLOCKED",
				claim_risk_level: "HIGH",
				claim_tokens_json: ["rawat", "penyakit", "ubat"],
				approval_blockers: [
					"MISSING_REQUIRED_FIELDS:source_urls_json",
					"CLAIM_BLOCKED:rawat,penyakit,ubat",
				],
			}),
		);
		expect(msg).not.toBeNull();
		expect(msg as string).toContain("source_urls_json");
		expect(msg as string).toContain("rawat, penyakit, ubat");
	});
});
