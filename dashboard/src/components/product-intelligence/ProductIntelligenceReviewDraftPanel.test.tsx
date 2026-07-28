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
	approveClaimSafeRewrite,
	fetchClaimSafeRewritePreview,
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
	fetchClaimSafeRewritePreview: vi.fn(),
	approveClaimSafeRewrite: vi.fn(),
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
	afterEach(() => {
		cleanup();
		vi.clearAllMocks();
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1",
			items: [],
		});
	});

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

	it("guides a blocked product through preview and explicit phrase-gated claim-safe approval", async () => {
		const draft = makeDraft({
			product_description: "Biskut susu.",
			benefits_json: ["Melt-in-mouth texture"],
			usp_json: ["330g pack"],
			target_customer_text: "Peminat biskut",
			buyer_persona_snapshot_json: { audience: "Peminat biskut" },
			copy_strategy_summary_json: { angles: ["taste"] },
			source_urls_json: { source_url: "https://example.com/product" },
			image_evidence_json: { image_url: "https://example.com/product.jpg" },
		});
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1",
			items: [draft],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(draft);
		vi.mocked(fetchClaimSafeRewritePreview).mockResolvedValue({
			product_id: "p1",
			product_name: "Biskut Makmur Susu",
			safe_claim_rewrite: "Biskut susu dengan fokus pada rasa dan format produk.",
			safe_hook_angles: ["Fokus rasa"],
			safe_usp_list: ["Pek 330g"],
			safe_cta_angles: ["Semak butiran produk."],
			claim_safe_copy_status: "CLAIM_SAFE_COPY_PREVIEW_ONLY",
			approval_required: true,
			approval_after_operator_review: true,
			approval_phrase: "APPROVE_CLAIM_SAFE_COPY_REVIEW",
			claim_gate: "CLAIM_REVIEW_REQUIRED",
			review_decision: "APPROVE_CANDIDATE",
			audit_notes: [],
			provenance: ["claim_safe_rewrite_service:v3", "draft_source:NOT_FOUND"],
			stored_status: null,
			stored_payload_available: false,
		});
		vi.mocked(approveClaimSafeRewrite).mockResolvedValue({
			product_id: "p1",
			product_name: "Biskut Makmur Susu",
			safe_claim_rewrite: "Biskut susu dengan fokus pada rasa dan format produk.",
			safe_hook_angles: ["Fokus rasa"],
			safe_usp_list: ["Pek 330g"],
			safe_cta_angles: ["Semak butiran produk."],
			claim_safe_copy_status: "CLAIM_SAFE_COPY_REVIEW_READY",
			approval_required: true,
			approval_after_operator_review: true,
			approval_phrase: "APPROVE_CLAIM_SAFE_COPY_REVIEW",
			claim_gate: "CLAIM_REVIEW_REQUIRED",
			review_decision: "APPROVE_CANDIDATE",
			audit_notes: [],
			provenance: ["claim_safe_rewrite_service:v3", "draft_source:NOT_FOUND"],
			approved_at: "2026-07-28T00:00:00Z",
		});
		const onClaimSafeApproved = vi.fn();

		render(
			<ProductIntelligenceReviewDraftPanel
				productId="p1"
				onApproved={async () => {}}
				guidedClaimSafe
				onClaimSafeApproved={onClaimSafeApproved}
			/>,
		);

		expect(await screen.findByTestId("guided-claim-safe-panel")).toHaveTextContent(
			"Biskut susu dengan fokus pada rasa",
		);
		await waitFor(() =>
			expect(
				screen.getByTestId("guided-claim-safe-missing-fields"),
			).toHaveTextContent("allowed_claims_json"),
		);
		expect(screen.getByTestId("approve-claim-safe-package")).toBeDisabled();
		expect(approveClaimSafeRewrite).not.toHaveBeenCalled();

		fireEvent.change(screen.getByTestId("claim-safe-approval-phrase"), {
			target: { value: "APPROVE_CLAIM_SAFE_COPY_REVIEW" },
		});
		fireEvent.click(screen.getByTestId("approve-claim-safe-package"));

		await waitFor(() =>
			expect(approveClaimSafeRewrite).toHaveBeenCalledWith("p1", {
				confirmation_phrase: "APPROVE_CLAIM_SAFE_COPY_REVIEW",
				approval_note: null,
			}),
		);
		expect(onClaimSafeApproved).toHaveBeenCalledWith(
			"CLAIM_SAFE_COPY_REVIEW_READY",
		);
	});

	it("surfaces a fail-closed claim-safe preview error without approving", async () => {
		vi.mocked(fetchClaimSafeRewritePreview).mockRejectedValue(
			new Error("API 409: CLAIM_SAFE_REVIEW_BLOCKED"),
		);

		render(
			<ProductIntelligenceReviewDraftPanel
				productId="p1"
				onApproved={async () => {}}
				guidedClaimSafe
			/>,
		);

		expect(await screen.findByTestId("guided-claim-safe-error")).toHaveTextContent(
			"CLAIM_SAFE_REVIEW_BLOCKED",
		);
		expect(approveClaimSafeRewrite).not.toHaveBeenCalled();
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
