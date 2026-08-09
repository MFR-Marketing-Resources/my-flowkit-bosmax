import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProductIntelligenceReviewDraftPanel, {
	describeApprovalBlockers,
	formatReviewDraftError,
	parseRelayBlocker,
	describeRelayBlocker,
} from "./ProductIntelligenceReviewDraftPanel";
import type { ProductIntelligenceReviewDraft, ProductIntelligenceReviewDraftValidationResponse } from "../../types";
import {
	aiFillMissingProductIntelligenceReviewDraft,
	approveClaimSafeRewrite,
	approveProductIntelligenceReviewDraft,
	createProductIntelligenceRevisionDraft,
	fetchClaimSafeRewritePreview,
	fetchProductIntelligenceReviewDraft,
	fetchProductIntelligenceReviewDrafts,
	recomputeProductIntelligence,
	setProductIntelligenceFieldDisposition,
	updateProductIntelligenceReviewDraft,
	validateProductIntelligenceReviewDraft,
} from "../../api/products";

vi.mock("../../api/products", () => ({
	fetchProductIntelligenceReviewDrafts: vi
		.fn()
		.mockResolvedValue({ product_id: "p1", items: [] }),
	fetchProductIntelligenceReviewDraft: vi.fn(),
	createProductIntelligenceReviewDraft: vi.fn(),
	createProductIntelligenceRevisionDraft: vi.fn(),
	prepareProductForCopywriting: vi.fn(),
	recomputeProductIntelligence: vi.fn(),
	aiFillMissingProductIntelligenceReviewDraft: vi.fn(),
	fetchClaimSafeRewritePreview: vi.fn(),
	approveClaimSafeRewrite: vi.fn(),
	updateProductIntelligenceReviewDraft: vi.fn(),
	validateProductIntelligenceReviewDraft: vi.fn(),
	setProductIntelligenceFieldDisposition: vi.fn(),
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
			await screen.findByRole("button", { name: /Create Revision Draft/i }),
		).toBeInTheDocument();
	});

	it("selects the newest editable draft ahead of newer terminal history", async () => {
		const approved = makeDraft({
			draft_id: "d-approved",
			review_status: "APPROVED",
			updated_at: "2026-08-09T10:00:00Z",
		});
		const editable = makeDraft({
			draft_id: "d-editable",
			review_status: "NEEDS_REVISION",
			updated_at: "2026-08-09T09:00:00Z",
		});
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1",
			items: [approved, editable],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockImplementation(
			async (draftId) => (draftId === editable.draft_id ? editable : approved),
		);

		render(<ProductIntelligenceReviewDraftPanel productId="p1" onApproved={async () => {}} />);

		await waitFor(() =>
			expect(fetchProductIntelligenceReviewDraft).toHaveBeenCalledWith("d-editable"),
		);
		expect(screen.getByTestId("draft-queue-item-d-editable")).toHaveClass(
			"border-sky-400",
		);
	});

	it("keeps an approved draft historical and blocks every terminal mutation path", async () => {
		const approved = makeDraft({
			review_status: "APPROVED",
			updated_at: "2026-08-09T10:00:00Z",
		});
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1",
			items: [approved],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(approved);

		render(<ProductIntelligenceReviewDraftPanel productId="p1" onApproved={async () => {}} />);

		expect(await screen.findByTestId("terminal-draft-notice")).toHaveTextContent(
			/Create Revision Draft/,
		);
		for (const button of [
			screen.getByRole("button", { name: /^Save Draft$/i }),
			screen.getByRole("button", { name: /Recompute \(Validate\)/i }),
			screen.getByRole("button", { name: /Analyze & Repair from source/i }),
			screen.getByTestId("ai-fill-missing-button"),
			screen.getByRole("button", { name: /Approve Draft/i }),
			screen.getByRole("button", { name: /Reject Draft/i }),
		]) {
			expect(button).toBeDisabled();
			fireEvent.click(button);
		}
		expect(screen.getByLabelText("Product Description")).toBeDisabled();
		expect(screen.getByRole("button", { name: /Create Revision Draft/i })).toBeEnabled();
		expect(updateProductIntelligenceReviewDraft).not.toHaveBeenCalled();
		expect(validateProductIntelligenceReviewDraft).not.toHaveBeenCalled();
		expect(recomputeProductIntelligence).not.toHaveBeenCalled();
	});

	it("creates and selects an editable revision from terminal history", async () => {
		const approved = makeDraft({ review_status: "APPROVED" });
		const revision = makeDraft({
			draft_id: "d-revision",
			review_status: "NEEDS_REVISION",
		});
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1",
			items: [approved],
		});
		vi.mocked(createProductIntelligenceRevisionDraft).mockResolvedValue(revision);
		vi.mocked(fetchProductIntelligenceReviewDraft).mockImplementation(
			async (draftId) => (draftId === revision.draft_id ? revision : approved),
		);

		render(<ProductIntelligenceReviewDraftPanel productId="p1" onApproved={async () => {}} />);
		fireEvent.click(
			await screen.findByRole("button", { name: /Create Revision Draft/i }),
		);

		await waitFor(() =>
			expect(createProductIntelligenceRevisionDraft).toHaveBeenCalledWith("p1", {
				created_by: "operator",
			}),
		);
		await waitFor(() => {
			expect(screen.queryByTestId("terminal-draft-notice")).toBeNull();
			expect(screen.getByRole("button", { name: /^Save Draft$/i })).toBeEnabled();
			expect(screen.getByTestId("draft-queue-item-d-revision")).toHaveClass(
				"border-sky-400",
		);
		});
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

	it("translates terminal draft update errors into the revision action", () => {
		const msg = formatReviewDraftError(
			new Error('API 409: {"detail":"DRAFT_UPDATE_FORBIDDEN:APPROVED"}'),
			"fallback",
		);
		expect(msg).toMatch(/Create Revision Draft/);
		expect(msg).not.toContain("API 409");
		expect(msg).not.toContain("{");
	});

	// ── authenticated TikTok relay ────────────────────────────────────────────
	const relay409 = (code: string, product_url = "https://shop.tiktok.com/view/product/17") =>
		new Error(
			`API 409: ${JSON.stringify({
				detail: { code, reason: "", product_url, operator_actionable: true },
			})}`,
		);

	it("parseRelayBlocker recognises the structured relay detail and ignores everything else", () => {
		const blocker = parseRelayBlocker(relay409("TIKTOK_RELAY_SECURITY_CHECK_PRESENT"));
		expect(blocker?.code).toBe("TIKTOK_RELAY_SECURITY_CHECK_PRESENT");
		expect(blocker?.product_url).toBe("https://shop.tiktok.com/view/product/17");
		// A plain approval failure is NOT a relay blocker and must keep its own handling.
		expect(
			parseRelayBlocker(new Error('API 409: {"detail":"DRAFT_NOT_APPROVABLE:X"}')),
		).toBeNull();
		expect(parseRelayBlocker(new Error("network down"))).toBeNull();
		expect(parseRelayBlocker("not-an-error")).toBeNull();
	});

	it("describeRelayBlocker gives the four operator steps, and refuses to offer a Retry that cannot work", () => {
		const captcha = describeRelayBlocker({
			code: "TIKTOK_RELAY_SECURITY_CHECK_PRESENT",
			reason: "", product_url: "", operator_actionable: true,
		});
		expect(captcha.retryable).toBe(true);
		expect(captcha.steps).toEqual([
			"Open the stored TikTok product link.",
			"Complete TikTok Security Check manually if shown.",
			"Keep the product tab open.",
			"Press Retry.",
		]);
		// The system never claims it will clear the challenge itself.
		expect(captcha.headline.toLowerCase()).toContain("never solve it for you");

		// A link on an unsupported host can never be relayed — offering Retry would be a
		// loop the operator can never escape.
		const wrongHost = describeRelayBlocker({
			code: "TIKTOK_RELAY_HOST_NOT_SUPPORTED",
			reason: "", product_url: "", operator_actionable: false,
		});
		expect(wrongHost.retryable).toBe(false);

		// A permission-blind extension reports zero tabs even with the product open on
		// screen. Telling the operator to open a tab would be advice they have already
		// followed, so this state must send them to chrome://extensions instead.
		const blind = describeRelayBlocker({
			code: "TIKTOK_RELAY_HOST_PERMISSION_MISSING",
			reason: "", product_url: "", operator_actionable: true,
		});
		expect(blind.headline).toMatch(/even though the tab is open/i);
		expect(blind.steps[0]).toMatch(/chrome:\/\/extensions/);
		expect(blind.steps.join(" ")).not.toMatch(/Open the stored TikTok product link/);
	});

	it("[relay] a walled Recompute shows the actionable panel with the raw code and a working Retry", async () => {
		vi.mocked(recomputeProductIntelligence)
			.mockRejectedValueOnce(relay409("TIKTOK_RELAY_NO_MATCHING_TAB"))
			.mockResolvedValueOnce({
				product_id: "p1", draft_id: "d1",
				source_url: "https://shop.tiktok.com/view/product/17",
				intake_outcome: "DRAFT_UPDATED", extracted_fields: { size_or_volume: "25ml" },
				// B-08B-D1: a preserved field is REPORTED with the discarded page text —
				// silent preservation would be indistinguishable from failed extraction.
				evidence_skipped: [{
					field: "product_description",
					reason: "EXISTING_EVIDENCE_PRESERVED",
					extracted_value_not_stored: "Buy Gift Bag on TikTok Shop. Shop now!",
				}],
				unresolved: {}, variant: "25ml", variant_resolution: "EXACT_VARIANT_RESOLVED",
				size_resolution: "EXTRACTED", evidence_methods: ["AUTHENTICATED_DOM"],
				candidate_status: "REVIEW_REQUIRED", candidates_persisted: [],
				candidates_skipped: [], provider: "deepseek", model: "deepseek-chat",
				refused_model_fields: [], acquisition_mode: "AUTHENTICATED_BROWSER_RELAY",
				relay: {
					tab_id: 7, matched_tabs: 1, replayed: false,
					dropped_keys: [], evidence_request_id: "req-1",
				},
				approved: false,
			});
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1", items: [makeDraft()],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(makeDraft());

		render(<ProductIntelligenceReviewDraftPanel productId="p1" onApproved={async () => {}} />);
		fireEvent.click(await screen.findByTestId("recompute-from-source-button"));

		const panel = await screen.findByTestId("recompute-relay-blocker");
		expect(panel).toHaveTextContent(/nothing was saved/i);
		expect(panel).toHaveTextContent("Press Retry.");
		// The backend code stays on screen — an operator reporting a problem has to be able
		// to quote what actually failed.
		expect(await screen.findByTestId("relay-blocker-code")).toHaveTextContent(
			"TIKTOK_RELAY_NO_MATCHING_TAB",
		);
		expect(await screen.findByTestId("relay-product-link")).toHaveAttribute(
			"href", "https://shop.tiktok.com/view/product/17",
		);

		// Retry runs the same lane again; the second attempt succeeds via the browser.
		fireEvent.click(await screen.findByTestId("relay-retry-button"));
		await waitFor(() =>
			expect(recomputeProductIntelligence).toHaveBeenCalledTimes(2),
		);
		expect(await screen.findByTestId("recompute-acquisition-mode")).toHaveTextContent(
			"AUTHENTICATED_BROWSER_RELAY",
		);
		// the blocker panel is gone once the acquisition succeeds
		expect(screen.queryByTestId("recompute-relay-blocker")).toBeNull();
		// preservation is visible: which field kept its evidence AND what the page said
		const preserved = await screen.findByTestId("recompute-evidence-preserved");
		expect(preserved).toHaveTextContent("product_description");
		expect(preserved).toHaveTextContent("Buy Gift Bag on TikTok Shop");
		expect(preserved).toHaveTextContent(/a refresh fills, it never replaces/i);
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


describe("Analyze & Repair from source (existing-product recompute)", () => {
	afterEach(() => {
		cleanup();
		vi.clearAllMocks();
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1",
			items: [],
		});
	});

	function recomputeResult(overrides: Record<string, unknown> = {}) {
		return {
			product_id: "p1", draft_id: "d1",
			source_url: "https://shop.tiktok.com/view/product/1",
			intake_outcome: "UPDATED_REVIEW_REQUIRED",
			extracted_fields: { size_or_volume: "25ml", materials_text: "minyak kelapa" },
			unresolved: { warnings_text: "NOT_STATED_IN_SOURCE" },
			variant: "25ml", variant_resolution: "EXACT_VARIANT_RESOLVED",
			size_resolution: "EXTRACTED", evidence_methods: ["JSONLD", "META"],
			candidate_status: "REVIEW_REQUIRED",
			candidates_persisted: [{ field: "usp_json", value: ["Formula tradisional"] }],
			candidates_skipped: [], provider: "deepseek", model: "deepseek-chat",
			refused_model_fields: ["warnings_text"], approved: false,
			...overrides,
		};
	}

	async function renderWithDraft() {
		const draft = makeDraft();
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1", items: [draft],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(draft);
		render(<ProductIntelligenceReviewDraftPanel productId="p1" onApproved={async () => {}} />);
		expect(await screen.findByTestId("recompute-from-source-button")).toBeInTheDocument();
	}

	it("acquires source evidence and re-reads the draft from the database", async () => {
		await renderWithDraft();
		vi.mocked(recomputeProductIntelligence).mockResolvedValue(recomputeResult() as never);

		fireEvent.click(screen.getByTestId("recompute-from-source-button"));

		await waitFor(() =>
			expect(recomputeProductIntelligence).toHaveBeenCalledWith("p1"),
		);
		// the panel must re-read persisted state, not trust the response optimistically
		await waitFor(() =>
			expect(fetchProductIntelligenceReviewDraft).toHaveBeenCalledWith("d1"),
		);
		const panel = await screen.findByTestId("recompute-source-result");
		expect(panel).toHaveTextContent("JSONLD+META");
		expect(panel).toHaveTextContent("shop.tiktok.com");
	});

	it("shows AI candidates as review-required and never as approved", async () => {
		await renderWithDraft();
		vi.mocked(recomputeProductIntelligence).mockResolvedValue(recomputeResult() as never);

		fireEvent.click(screen.getByTestId("recompute-from-source-button"));

		const candidates = await screen.findByTestId("recompute-ai-candidates");
		expect(candidates).toHaveTextContent("usp_json");
		expect(candidates).toHaveTextContent("AI_PROPOSED");
		expect(candidates).toHaveTextContent(/Nothing is auto-approved/i);
	});

	it("shows unresolved fields explicitly instead of leaving them silently blank", async () => {
		await renderWithDraft();
		vi.mocked(recomputeProductIntelligence).mockResolvedValue(recomputeResult() as never);

		fireEvent.click(screen.getByTestId("recompute-from-source-button"));

		const unresolved = await screen.findByTestId("recompute-unresolved");
		expect(unresolved).toHaveTextContent("warnings_text");
		expect(unresolved).toHaveTextContent("NOT_STATED_IN_SOURCE");
		expect(unresolved).toHaveTextContent(/Nothing was invented/i);
	});

	it("surfaces a failure instead of reporting silent success", async () => {
		await renderWithDraft();
		vi.mocked(recomputeProductIntelligence).mockRejectedValue(
			new Error("TIKTOKSHOP_FETCH_FAILED:http_404"),
		);

		fireEvent.click(screen.getByTestId("recompute-from-source-button"));

		expect(await screen.findByText(/TIKTOKSHOP_FETCH_FAILED/)).toBeInTheDocument();
		expect(screen.queryByTestId("recompute-source-result")).not.toBeInTheDocument();
	});

	it("disables the action while it is running so it cannot be double-fired", async () => {
		await renderWithDraft();
		let release: (value: unknown) => void = () => {};
		vi.mocked(recomputeProductIntelligence).mockReturnValue(
			new Promise((resolve) => {
				release = resolve;
			}) as never,
		);

		const button = screen.getByTestId("recompute-from-source-button");
		fireEvent.click(button);
		await waitFor(() => expect(button).toBeDisabled());
		expect(button).toHaveTextContent(/Acquiring source evidence/i);

		release(recomputeResult());
		await waitFor(() => expect(button).not.toBeDisabled());
	});

	// ── Mission-08D: governed absence workflow + claim acknowledgement ────────
	const gapDraft = (
		overrides: Partial<ProductIntelligenceReviewDraft> = {},
	) =>
		makeDraft({
			product_description: "Windshield washer concentrate 30ml.",
			benefits_json: ["clear view"],
			usp_json: ["compact"],
			target_customer_text: "Drivers",
			allowed_claims_json: ["water repellent effect"],
			source_urls_json: { source_url: "https://example.com/p" },
			image_evidence_json: { image_url: "https://example.com/i.jpg" },
			buyer_persona_snapshot_json: { audience: "drivers" },
			copy_strategy_summary_json: { angles: ["safety"] },
			reviewed_by: "owner",
			...overrides,
		});

	const gapValidation = (over: Partial<ProductIntelligenceReviewDraftValidationResponse> = {}) =>
		({
			draft: gapDraft(),
			missing_required_fields: ["usage_text", "ingredients_text", "warnings_text"],
			present_required_fields: [],
			completeness_score: 0.79,
			readiness_status: "MISSING_REQUIRED_FIELDS",
			claim_gate: "CLAIM_SAFE",
			claim_risk_level: "LOW",
			claim_tokens_json: [],
			allowed_claims_json: [],
			blocked_claims_json: [],
			approval_blockers: [
				"MISSING_REQUIRED_FIELDS:usage_text,ingredients_text,warnings_text",
			],
			governed_absent_fields: {},
			unresolved_external_fields: [],
			// Automotive = strict category: server offers NSIS/REE but NOT NA.
			disposition_options: {
				usage_text: ["NOT_STATED_IN_SOURCE", "REQUIRES_EXTERNAL_EVIDENCE"],
				ingredients_text: ["NOT_STATED_IN_SOURCE", "REQUIRES_EXTERNAL_EVIDENCE"],
				warnings_text: ["NOT_STATED_IN_SOURCE", "REQUIRES_EXTERNAL_EVIDENCE"],
			},
			...over,
		}) as ProductIntelligenceReviewDraftValidationResponse;

	it("[08D] resolve-absence records a disposition with a mandatory note and shows the badge", async () => {
		const draft = gapDraft();
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1", items: [draft],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(draft);
		vi.mocked(updateProductIntelligenceReviewDraft).mockResolvedValue(draft);
		vi.mocked(validateProductIntelligenceReviewDraft).mockResolvedValue(gapValidation());
		vi.mocked(setProductIntelligenceFieldDisposition).mockResolvedValue(
			gapValidation({
				governed_absent_fields: { ingredients_text: "NOT_STATED_IN_SOURCE" },
				approval_blockers: ["MISSING_REQUIRED_FIELDS:usage_text,warnings_text"],
			}),
		);

		render(<ProductIntelligenceReviewDraftPanel productId="p1" onApproved={async () => {}} />);
		// Validate first so the server-derived options are on screen.
		fireEvent.click(await screen.findByRole("button", { name: /Recompute \(Validate\)/i }));
		fireEvent.click(await screen.findByTestId("resolve-absence-ingredients_text"));

		const form = await screen.findByTestId("disposition-form");
		expect(form).toHaveTextContent(/never writes a placeholder/i);
		// NA is server-disabled for this strict category, with the reason shown.
		expect(screen.queryByTestId("disposition-option-NOT_APPLICABLE")).toBeNull();
		expect(screen.getByTestId("disposition-na-disabled")).toHaveTextContent(/risk-strict/i);

		fireEvent.click(screen.getByTestId("disposition-option-NOT_STATED_IN_SOURCE"));
		// mandatory note: submit stays disabled until a real note is typed
		expect(screen.getByTestId("disposition-submit")).toBeDisabled();
		fireEvent.change(screen.getByTestId("disposition-note"), {
			target: { value: "Halaman sumber tidak menyatakan bahan." },
		});
		expect(screen.getByTestId("disposition-submit")).toBeEnabled();
		fireEvent.click(screen.getByTestId("disposition-submit"));

		await waitFor(() =>
			expect(setProductIntelligenceFieldDisposition).toHaveBeenCalledWith("d1", {
				field_name: "ingredients_text",
				disposition: "NOT_STATED_IN_SOURCE",
				reviewed_by: "owner",
				reviewer_note: "Halaman sumber tidak menyatakan bahan.",
			}),
		);
		expect(await screen.findByTestId("disposition-badge-ingredients_text"))
			.toHaveTextContent("NOT_STATED_IN_SOURCE");
	});



	it("[08D] governed absence cannot be recorded without explicit reviewer identity", async () => {
		const draft = gapDraft({ reviewed_by: null });
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1",
			items: [draft],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(draft);
		vi.mocked(updateProductIntelligenceReviewDraft).mockResolvedValue(draft);
		vi.mocked(validateProductIntelligenceReviewDraft).mockResolvedValue(
			gapValidation({ draft }),
		);

		render(
			<ProductIntelligenceReviewDraftPanel
				productId="p1"
				onApproved={async () => {}}
			/>,
		);
		fireEvent.click(
			await screen.findByRole("button", { name: /Recompute \(Validate\)/i }),
		);
		fireEvent.click(
			await screen.findByTestId("resolve-absence-ingredients_text"),
		);
		fireEvent.click(
			screen.getByTestId("disposition-option-NOT_STATED_IN_SOURCE"),
		);
		fireEvent.change(screen.getByTestId("disposition-note"), {
			target: { value: "Source does not state the ingredients." },
		});
		expect(screen.getByTestId("disposition-reviewer-required")).toBeVisible();
		expect(screen.getByTestId("disposition-submit")).toBeDisabled();

		fireEvent.change(screen.getByLabelText("Reviewed By"), {
			target: { value: "owner-08d" },
		});
		expect(screen.getByTestId("disposition-submit")).toBeEnabled();
	});

	it("[08D] persisted disposition badge survives reload before revalidation", async () => {
		const draft = gapDraft({
			provenance_items: [
				{
					review_provenance_id: "rp-1",
					field_name: "ingredients_text",
					evidence_kind: "FIELD_ABSENCE_DISPOSITION",
					verification_status: "NOT_STATED_IN_SOURCE",
				} as never,
			],
		});
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1",
			items: [draft],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(draft);

		render(
			<ProductIntelligenceReviewDraftPanel
				productId="p1"
				onApproved={async () => {}}
			/>,
		);
		expect(
			await screen.findByTestId("disposition-badge-ingredients_text"),
		).toHaveTextContent("NOT_STATED_IN_SOURCE");
		expect(validateProductIntelligenceReviewDraft).not.toHaveBeenCalled();
	});



	it("[08D] only eligible gaps expose absence controls and external evidence stays blocking", async () => {
		const draft = gapDraft({ allowed_claims_json: [] });
		const external = gapValidation({
			draft,
			missing_required_fields: ["allowed_claims_json", "ingredients_text"],
			unresolved_external_fields: ["ingredients_text"],
			approval_blockers: [
				"MISSING_REQUIRED_FIELDS:allowed_claims_json",
				"REQUIRES_EXTERNAL_EVIDENCE:ingredients_text",
			],
			disposition_options: {
				ingredients_text: [
					"NOT_STATED_IN_SOURCE",
					"REQUIRES_EXTERNAL_EVIDENCE",
				],
			},
		});
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1",
			items: [draft],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(draft);
		vi.mocked(updateProductIntelligenceReviewDraft).mockResolvedValue(draft);
		vi.mocked(validateProductIntelligenceReviewDraft).mockResolvedValue(external);

		render(
			<ProductIntelligenceReviewDraftPanel
				productId="p1"
				onApproved={async () => {}}
			/>,
		);
		fireEvent.click(
			await screen.findByRole("button", { name: /Recompute \(Validate\)/i }),
		);
		expect(screen.getByTestId("missing-field-allowed_claims_json"))
			.toHaveTextContent(/no governed absence permitted/i);
		expect(screen.queryByTestId("resolve-absence-allowed_claims_json")).toBeNull();
		expect(await screen.findByTestId("disposition-badge-ingredients_text"))
			.toHaveTextContent(/still blocking/i);

		fireEvent.click(screen.getByRole("button", { name: /Approve Draft/i }));
		await waitFor(() =>
			expect(approveProductIntelligenceReviewDraft).not.toHaveBeenCalled(),
		);
	});

	it("[08D] NOT_APPLICABLE needs a second confirmation before it is recorded", async () => {
		const draft = gapDraft();
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1", items: [draft],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(draft);
		vi.mocked(updateProductIntelligenceReviewDraft).mockResolvedValue(draft);
		// confirmable category: server offers NA
		vi.mocked(validateProductIntelligenceReviewDraft).mockResolvedValue(
			gapValidation({
				disposition_options: {
					ingredients_text: [
						"NOT_STATED_IN_SOURCE", "NOT_APPLICABLE", "REQUIRES_EXTERNAL_EVIDENCE",
					],
				},
			}),
		);
		vi.mocked(setProductIntelligenceFieldDisposition).mockResolvedValue(
			gapValidation({
				governed_absent_fields: { ingredients_text: "NOT_APPLICABLE" },
			}),
		);

		render(<ProductIntelligenceReviewDraftPanel productId="p1" onApproved={async () => {}} />);
		fireEvent.click(await screen.findByRole("button", { name: /Recompute \(Validate\)/i }));
		fireEvent.click(await screen.findByTestId("resolve-absence-ingredients_text"));
		fireEvent.click(await screen.findByTestId("disposition-option-NOT_APPLICABLE"));
		fireEvent.change(screen.getByTestId("disposition-note"), {
			target: { value: "Produk tekstil, tiada bahan ramuan." },
		});
		// first click ARMS the confirmation — nothing recorded yet
		fireEvent.click(screen.getByTestId("disposition-submit"));
		expect(setProductIntelligenceFieldDisposition).not.toHaveBeenCalled();
		expect(await screen.findByTestId("disposition-na-confirm"))
			.toHaveTextContent(/DOES NOT APPLY/i);
		// second click records it
		fireEvent.click(screen.getByTestId("disposition-submit"));
		await waitFor(() =>
			expect(setProductIntelligenceFieldDisposition).toHaveBeenCalledTimes(1),
		);
	});

	it("[08D] claim acknowledgement is offered ONLY for review-required and travels with approve", async () => {
		const draft = gapDraft();
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1", items: [draft],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(draft);
		vi.mocked(updateProductIntelligenceReviewDraft).mockResolvedValue(draft);
		const reviewRequired = gapValidation({
			missing_required_fields: [],
			readiness_status: "CLAIM_REVIEW_REQUIRED",
			claim_gate: "CLAIM_REVIEW_REQUIRED",
			claim_tokens_json: ["treat"],
			approval_blockers: ["CLAIM_REVIEW_REQUIRED:treat"],
			disposition_options: {},
		});
		vi.mocked(validateProductIntelligenceReviewDraft).mockResolvedValue(reviewRequired);
		vi.mocked(approveProductIntelligenceReviewDraft).mockResolvedValue({
			snapshot_id: "snap-1", version: 1,
		} as never);

		render(<ProductIntelligenceReviewDraftPanel productId="p1" onApproved={async () => {}} />);
		fireEvent.click(await screen.findByRole("button", { name: /Recompute \(Validate\)/i }));

		const ack = await screen.findByTestId("claim-ack-checkbox");
		// Without the acknowledgement, Approve fail-closes client-side.
		fireEvent.click(screen.getByRole("button", { name: /Approve Draft/i }));
		await waitFor(() =>
			expect(approveProductIntelligenceReviewDraft).not.toHaveBeenCalled(),
		);
		// An edit invalidates the prior validation and acknowledgement.
		fireEvent.click(ack);
		fireEvent.change(screen.getByLabelText("Reviewed By"), {
			target: { value: "owner-08d" },
		});
		expect(screen.queryByTestId("claim-ack-checkbox")).toBeNull();
		fireEvent.click(
			screen.getByRole("button", { name: /Recompute \(Validate\)/i }),
		);
		const resetAck = await screen.findByTestId("claim-ack-checkbox");
		expect(resetAck).not.toBeChecked();
		fireEvent.click(resetAck);
		// Only the fresh acknowledgement travels with approve.
		fireEvent.click(screen.getByRole("button", { name: /Approve Draft/i }));
		await waitFor(() =>
			expect(approveProductIntelligenceReviewDraft).toHaveBeenCalledWith("d1", {
				approved_by: expect.any(String),
				approval_note: null,
				claim_review_acknowledged: true,
			}),
		);
		const updateOrder = vi.mocked(updateProductIntelligenceReviewDraft)
			.mock.invocationCallOrder.at(-1) ?? 0;
		const validateOrder = vi.mocked(validateProductIntelligenceReviewDraft)
			.mock.invocationCallOrder.at(-1) ?? 0;
		const approveOrder = vi.mocked(approveProductIntelligenceReviewDraft)
			.mock.invocationCallOrder.at(-1) ?? 0;
		expect(updateOrder).toBeLessThan(validateOrder);
		expect(validateOrder).toBeLessThan(approveOrder);
	});

	it("[08D] CLAIM_BLOCKED shows the absolute-block notice and never an acknowledgement", async () => {
		const draft = gapDraft();
		vi.mocked(fetchProductIntelligenceReviewDrafts).mockResolvedValue({
			product_id: "p1", items: [draft],
		});
		vi.mocked(fetchProductIntelligenceReviewDraft).mockResolvedValue(draft);
		vi.mocked(validateProductIntelligenceReviewDraft).mockResolvedValue(
			gapValidation({
				missing_required_fields: [],
				readiness_status: "CLAIM_BLOCKED",
				claim_gate: "CLAIM_BLOCKED",
				claim_tokens_json: ["ubat"],
				approval_blockers: ["CLAIM_BLOCKED:ubat"],
				disposition_options: {},
			}),
		);

		render(<ProductIntelligenceReviewDraftPanel productId="p1" onApproved={async () => {}} />);
		fireEvent.click(await screen.findByRole("button", { name: /Recompute \(Validate\)/i }));
		expect(await screen.findByTestId("claim-blocked-absolute"))
			.toHaveTextContent(/mutlak/i);
		expect(screen.queryByTestId("claim-ack-checkbox")).toBeNull();
	});

	it("[08D] describeApprovalBlockers honours governed absence, external evidence and ack", () => {
		// governed fields no longer block
		expect(
			describeApprovalBlockers(
				gapValidation({
					missing_required_fields: ["ingredients_text"],
					governed_absent_fields: { ingredients_text: "NOT_STATED_IN_SOURCE" },
					approval_blockers: [],
				}),
			),
		).toBeNull();
		// REQUIRES_EXTERNAL_EVIDENCE keeps blocking, ack or not
		const external = gapValidation({
			missing_required_fields: ["ingredients_text"],
			unresolved_external_fields: ["ingredients_text"],
			approval_blockers: ["REQUIRES_EXTERNAL_EVIDENCE:ingredients_text"],
		});
		expect(describeApprovalBlockers(external, true)).toMatch(/bukti luaran/);
		// ack clears ONLY a review-required claim blocker
		const review = gapValidation({
			missing_required_fields: [],
			claim_gate: "CLAIM_REVIEW_REQUIRED",
			claim_tokens_json: ["treat"],
			approval_blockers: ["CLAIM_REVIEW_REQUIRED:treat"],
		});
		expect(describeApprovalBlockers(review, false)).toMatch(/pengakuan/);
		expect(describeApprovalBlockers(review, true)).toBeNull();
		const blocked = gapValidation({
			missing_required_fields: [],
			claim_gate: "CLAIM_BLOCKED",
			claim_tokens_json: ["ubat"],
			approval_blockers: ["CLAIM_BLOCKED:ubat"],
		});
		expect(describeApprovalBlockers(blocked, true)).toMatch(/disekat/);
	});

});
