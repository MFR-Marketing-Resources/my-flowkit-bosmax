import type {
	Product,
	ProductCatalogResponse,
	ProductIntelligenceFieldProvenanceListResponse,
	ProductIntelligenceLatestSnapshotResponse,
	ProductIntelligenceReviewDraft,
	ProductIntelligenceReviewDraftListResponse,
	ProductIntelligenceReviewDraftMutationRequest,
	ProductIntelligenceReviewDraftValidationResponse,
	ProductIntelligenceSnapshot,
	ProductIntelligenceSnapshotListResponse,
	ProductIntelligenceSnapshotStatus,
	ProductStrategyTaxonomy,
	ProductStrategyTypeRegistrationRequest,
	ProductStrategyTypeRegistryEntry,
	ProductStrategyTypeRegistryResponse,
} from "../types";
import { fetchAPI } from "./client";

export async function fetchProductCatalog(
	limit = 250,
	purpose: "GENERATION" | "REVIEW" = "GENERATION",
): Promise<ProductCatalogResponse> {
	return fetchAPI<ProductCatalogResponse>(
		`/api/products?limit=${encodeURIComponent(String(limit))}&offset=0&purpose=${encodeURIComponent(purpose)}`,
	);
}

/**
 * Load one authoritative product row after an operator selects it from the
 * catalog.  The Cockpit grounding gate consumes image_url/local_image_path,
 * so it must not rely on a picker projection when binding the generation
 * product.
 */
export async function fetchProductDetail(productId: string): Promise<Product> {
	return fetchAPI<Product>(`/api/products/${encodeURIComponent(productId)}`);
}

export async function fetchProductStrategyTypeRegistry(): Promise<ProductStrategyTypeRegistryResponse> {
	return fetchAPI<ProductStrategyTypeRegistryResponse>(
		"/api/creative-intelligence/product-strategy-type-registry",
	);
}

export async function registerProductStrategyType(
	input: ProductStrategyTypeRegistrationRequest,
): Promise<ProductStrategyTypeRegistryEntry> {
	return fetchAPI<ProductStrategyTypeRegistryEntry>(
		"/api/creative-intelligence/product-strategy-type-registry",
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(input),
		},
	);
}

export async function reviewProductStrategyTaxonomy(
	productId: string,
	input: {
		expected_product_fingerprint: string;
		cluster: string;
		product_type_group: string;
		matched_scene_strategy_id: string;
		scene_coverage_status: "COVERED" | "PARTIAL" | "FALLBACK_ONLY";
		review_status: "VERIFIED" | "REVIEW_REQUIRED";
		reviewer_id: string;
		reviewer_note: string;
	},
): Promise<ProductStrategyTaxonomy> {
	return fetchAPI<ProductStrategyTaxonomy>(
		`/api/products/strategy-taxonomy/${encodeURIComponent(productId)}/review`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(input),
		},
	);
}

/**
 * Server-side product search. Unlike {@link fetchProductCatalog}, this queries
 * the full catalog rather than the first client-loaded page, so canonical
 * products that sit beyond the initial limit window (e.g. MANUAL products that
 * sort after the FastMoss rows) remain discoverable by name.
 */
export async function searchProducts(
	query: string,
	limit = 25,
	purpose?: "GENERATION",
): Promise<ProductCatalogResponse> {
	const purposeQuery = purpose ? `&purpose=${encodeURIComponent(purpose)}` : "";
	return fetchAPI<ProductCatalogResponse>(
		`/api/products/search?q=${encodeURIComponent(query)}&limit=${encodeURIComponent(
			String(limit),
		)}&offset=0${purposeQuery}`,
	);
}

export async function fetchProductIntelligence(
	productId: string,
): Promise<ProductIntelligenceLatestSnapshotResponse> {
	return fetchAPI<ProductIntelligenceLatestSnapshotResponse>(
		`/api/products/${encodeURIComponent(productId)}/intelligence`,
	);
}

export async function fetchProductIntelligenceSnapshots(
	productId: string,
	status?: ProductIntelligenceSnapshotStatus,
): Promise<ProductIntelligenceSnapshotListResponse> {
	const params = new URLSearchParams();
	if (status) params.set("status", status);
	const query = params.size > 0 ? `?${params.toString()}` : "";
	return fetchAPI<ProductIntelligenceSnapshotListResponse>(
		`/api/products/${encodeURIComponent(productId)}/intelligence/snapshots${query}`,
	);
}

export async function fetchProductIntelligenceProvenance(
	snapshotId: string,
	fieldName?: string,
): Promise<ProductIntelligenceFieldProvenanceListResponse> {
	const params = new URLSearchParams();
	if (fieldName) params.set("field_name", fieldName);
	const query = params.size > 0 ? `?${params.toString()}` : "";
	return fetchAPI<ProductIntelligenceFieldProvenanceListResponse>(
		`/api/product-intelligence/snapshots/${encodeURIComponent(snapshotId)}/provenance${query}`,
	);
}

export async function fetchProductIntelligenceReviewDrafts(
	productId: string,
): Promise<ProductIntelligenceReviewDraftListResponse> {
	return fetchAPI<ProductIntelligenceReviewDraftListResponse>(
		`/api/products/${encodeURIComponent(productId)}/intelligence/review-drafts`,
	);
}

export async function fetchProductIntelligenceReviewDraft(
	draftId: string,
): Promise<ProductIntelligenceReviewDraft> {
	return fetchAPI<ProductIntelligenceReviewDraft>(
		`/api/product-intelligence/review-drafts/${encodeURIComponent(draftId)}`,
	);
}

export interface ClaimSafeRewritePreview {
	product_id: string;
	product_name: string;
	safe_claim_rewrite: string;
	safe_hook_angles: string[];
	safe_usp_list: string[];
	safe_cta_angles: string[];
	claim_safe_copy_status: string;
	approval_required: boolean;
	approval_after_operator_review: boolean;
	approval_phrase: string;
	claim_gate: string;
	review_decision: string;
	audit_notes: string[];
	provenance: string[];
	stored_status?: string | null;
	stored_payload_available?: boolean;
	approved_at?: string | null;
}

export async function fetchClaimSafeRewritePreview(
	productId: string,
): Promise<ClaimSafeRewritePreview> {
	return fetchAPI<ClaimSafeRewritePreview>(
		`/api/products/${encodeURIComponent(productId)}/claim-safe-rewrite-preview`,
	);
}

export async function approveClaimSafeRewrite(
	productId: string,
	input: {
		confirmation_phrase: string;
		approval_note?: string | null;
	},
): Promise<ClaimSafeRewritePreview> {
	return fetchAPI<ClaimSafeRewritePreview>(
		`/api/products/${encodeURIComponent(productId)}/claim-safe-rewrite-approval`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(input),
		},
	);
}

// Prepare Product for Copywriting — the text_assist (DeepSeek) lane that drafts
// Product Knowledge + Customer Avatar + Recommended Formula into a review draft
// (NEVER approved). Operator-initiated; spends AI tokens on an explicit click.
export interface PrepareCopywritingResponse {
	review_draft_id: string;
	review_status: string;
	recommended_formula: string;
	grounding_source: string;
	claim_boundary: {
		overclaim_hits: string[];
		problem_language_present: string[];
		safe: boolean;
	};
	draft: ProductIntelligenceReviewDraft;
}

export async function prepareProductForCopywriting(
	productId: string,
): Promise<PrepareCopywritingResponse> {
	return fetchAPI<PrepareCopywritingResponse>(
		`/api/products/${encodeURIComponent(productId)}/intelligence/review-drafts/prepare`,
		{ method: "POST", body: JSON.stringify({}) },
	);
}

export interface ProductIntelligenceAIFillProposal {
	field: string;
	status: string;
	confidence: number | null;
	rationale: string;
	previous_value: unknown;
	proposed_value: unknown;
}

export interface ProductIntelligenceAIFillResult {
	draft_id: string;
	product_id: string;
	review_status: string;
	provider: string | null;
	model: string | null;
	prompt_version: string;
	generated_at: string | null;
	targeted_fields: string[];
	proposed: ProductIntelligenceAIFillProposal[];
	unresolved: { field: string; status: string; rationale: string }[];
	provider_configured: boolean;
}

export async function aiFillMissingProductIntelligenceReviewDraft(
	draftId: string,
	selectedFields?: string[],
): Promise<ProductIntelligenceAIFillResult> {
	return fetchAPI<ProductIntelligenceAIFillResult>(
		`/api/product-intelligence/review-drafts/${encodeURIComponent(draftId)}/ai-fill-missing`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(
				selectedFields ? { selected_fields: selectedFields } : {},
			),
		},
	);
}

export async function createProductIntelligenceReviewDraft(
	productId: string,
	payload: ProductIntelligenceReviewDraftMutationRequest,
): Promise<ProductIntelligenceReviewDraft> {
	return fetchAPI<ProductIntelligenceReviewDraft>(
		`/api/products/${encodeURIComponent(productId)}/intelligence/review-drafts`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
		},
	);
}

export async function updateProductIntelligenceReviewDraft(
	draftId: string,
	payload: ProductIntelligenceReviewDraftMutationRequest,
): Promise<ProductIntelligenceReviewDraft> {
	return fetchAPI<ProductIntelligenceReviewDraft>(
		`/api/product-intelligence/review-drafts/${encodeURIComponent(draftId)}`,
		{
			method: "PATCH",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
		},
	);
}

export async function validateProductIntelligenceReviewDraft(
	draftId: string,
): Promise<ProductIntelligenceReviewDraftValidationResponse> {
	return fetchAPI<ProductIntelligenceReviewDraftValidationResponse>(
		`/api/product-intelligence/review-drafts/${encodeURIComponent(draftId)}/validate`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({}),
		},
	);
}

export async function approveProductIntelligenceReviewDraft(
	draftId: string,
	payload: {
		approved_by?: string | null;
		approval_note?: string | null;
	},
): Promise<ProductIntelligenceSnapshot> {
	return fetchAPI<ProductIntelligenceSnapshot>(
		`/api/product-intelligence/review-drafts/${encodeURIComponent(draftId)}/approve`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
		},
	);
}

export async function rejectProductIntelligenceReviewDraft(
	draftId: string,
	payload: {
		rejected_by?: string | null;
		reviewer_note?: string | null;
	},
): Promise<ProductIntelligenceReviewDraft> {
	return fetchAPI<ProductIntelligenceReviewDraft>(
		`/api/product-intelligence/review-drafts/${encodeURIComponent(draftId)}/reject`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
		},
	);
}
