import type {
	CatalogAuthorityReport,
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
	ProductStrategyTypeUpdateRequest,
	ProductTypeCopyEligibleReport,
} from "../types";
import { fetchAPI } from "./client";

export type ProductCatalogPurpose = "GENERATION" | "REVIEW";
export type ProductRegistrySort =
	| "PRODUCT_NAME_ASC"
	| "PRODUCT_SOLD_VERIFIED_DESC"
	| "SHOP_TOTAL_SOLD_DESC";

const PRODUCT_CATALOG_CACHE_TTL_MS = 30_000;
const PRODUCT_REGISTRY_CACHE_TTL_MS = 30_000;
const PRODUCT_STRATEGY_REGISTRY_CACHE_TTL_MS = 30_000;

type ProductCatalogCacheEntry = {
	data?: ProductCatalogResponse;
	expiresAt: number;
	promise?: Promise<ProductCatalogResponse>;
};

const productCatalogCache = new Map<string, ProductCatalogCacheEntry>();

type ProductRegistryCacheEntry = {
	data?: ProductCatalogResponse;
	expiresAt: number;
	promise?: Promise<ProductCatalogResponse>;
};

const productRegistryCache = new Map<string, ProductRegistryCacheEntry>();

type ProductStrategyRegistryCacheEntry = {
	data?: ProductStrategyTypeRegistryResponse;
	expiresAt: number;
	promise?: Promise<ProductStrategyTypeRegistryResponse>;
};

const productStrategyRegistryCache =
	new Map<string, ProductStrategyRegistryCacheEntry>();

function productCatalogCacheKey(
	limit: number,
	purpose: ProductCatalogPurpose,
): string {
	return `${purpose}:${limit}`;
}

/**
 * Clear the shared selector catalog cache after a product truth mutation.
 * Callers can clear one purpose/window or the complete cache.
 */
export function invalidateProductCatalogCache(options?: {
	limit?: number;
	purpose?: ProductCatalogPurpose;
}): void {
	if (options?.limit !== undefined && options.purpose) {
		productCatalogCache.delete(
			productCatalogCacheKey(options.limit, options.purpose),
		);
		return;
	}
	if (options?.limit !== undefined) {
		for (const purpose of ["GENERATION", "REVIEW"] as const) {
			productCatalogCache.delete(productCatalogCacheKey(options.limit, purpose));
		}
		return;
	}
	if (options?.purpose) {
		for (const key of productCatalogCache.keys()) {
			if (key.startsWith(`${options.purpose}:`)) productCatalogCache.delete(key);
		}
		return;
	}
	productCatalogCache.clear();
	// A no-argument invalidation is used at real product mutation boundaries. The
	// registry cache is separate because its key includes filters and pages, but
	// it must not survive a mutation that changes catalog-visible state.
	productRegistryCache.clear();
}

/** Clear all cached registry pages after a catalog-visible mutation. */
export function invalidateProductRegistryCache(): void {
	productRegistryCache.clear();
}

/** Clear the stable taxonomy metadata cache after a registry mutation. */
export function invalidateProductStrategyTypeRegistryCache(): void {
	productStrategyRegistryCache.clear();
}

/** Force a fresh request for one catalog window, retaining the normal cache. */
export function revalidateProductCatalog(
	limit = 50,
	purpose: ProductCatalogPurpose = "GENERATION",
): Promise<ProductCatalogResponse> {
	invalidateProductCatalogCache({ limit, purpose });
	return fetchProductCatalog(limit, purpose);
}

export async function fetchProductCatalog(
	limit = 50,
	purpose: ProductCatalogPurpose = "GENERATION",
): Promise<ProductCatalogResponse> {
	const key = productCatalogCacheKey(limit, purpose);
	const cached = productCatalogCache.get(key);
	if (cached?.data && cached.expiresAt > Date.now()) return cached.data;
	if (cached?.promise) return cached.promise;

	const request = fetchAPI<ProductCatalogResponse>(
		`/api/products?limit=${encodeURIComponent(String(limit))}&offset=0&purpose=${encodeURIComponent(purpose)}`,
	);
	productCatalogCache.set(key, { expiresAt: 0, promise: request });
	try {
		const response = await request;
		const current = productCatalogCache.get(key);
		if (current?.promise === request) {
			productCatalogCache.set(key, {
				data: response,
				expiresAt: Date.now() + PRODUCT_CATALOG_CACHE_TTL_MS,
			});
		}
		return response;
	} catch (error) {
		if (productCatalogCache.get(key)?.promise === request) {
			productCatalogCache.delete(key);
		}
		throw error;
	}
}

/**
 * List the FULL committed product catalog across every source (MANUAL,
 * TIKTOKSHOP, FASTMOSS, IMPORTED). Deliberately omits `purpose` — unlike
 * {@link fetchProductCatalog}, passing no purpose keeps reference-only rows in
 * the result, so the "Semua Produk" tab shows everything, not just the
 * generation-eligible subset. Omit `source` to include all sources.
 */
export async function fetchProductRegistry(params: {
	source?:
		| "MANUAL"
		| "TIKTOKSHOP"
		| "FASTMOSS"
		| "IMPORTED"
		| "TEST"
		| "ALL";
	sourceLane?: string;
	q?: string;
	readiness?: string;
	includeArchived?: boolean;
	/** Exact taxonomy cluster (e.g. "food_cooking"). */
	cluster?: string;
	/** Exact product_type_group; usually paired with a cluster (its dependency). */
	productTypeGroup?: string;
	/** Product Intelligence state: READY / NEEDS_REVIEW / MISSING. */
	intelligenceStatus?: string;
	/** Claim risk tier: LOW / MEDIUM / HIGH. */
	claimRiskLevel?: string;
	/** Intelligence freshness roll-up: FRESH / STALE / UNKNOWN. */
	freshness?: string;
	/** Image availability: READY / MISSING. */
	image?: string;
	/** Restrict to one lifecycle (ACTIVE / ARCHIVED). ARCHIVED implies archived rows. */
	lifecycleStatus?: string;
	/** Drop read-only FastMoss reference rows (no product record) from the result. */
	excludeReference?: boolean;
	/** Product Intelligence browser filters not represented by the generic catalog. */
	group?: string;
	productFamily?: string;
	copyRoute?: string;
	claimGate?: string;
	intelligenceConfidence?: string;
	sort?: ProductRegistrySort;
	limit?: number;
	offset?: number;
	signal?: AbortSignal;
}): Promise<ProductCatalogResponse> {
	const query = new URLSearchParams();
	if (params.source) query.set("source", params.source);
	if (params.sourceLane) query.set("source_lane", params.sourceLane);
	if (params.q) query.set("q", params.q);
	if (params.readiness) query.set("readiness", params.readiness);
	if (params.includeArchived) query.set("include_archived", "true");
	if (params.excludeReference) query.set("exclude_reference", "true");
	if (params.cluster) query.set("cluster", params.cluster);
	if (params.productTypeGroup)
		query.set("product_type_group", params.productTypeGroup);
	if (params.intelligenceStatus)
		query.set("intelligence_status", params.intelligenceStatus);
	if (params.claimRiskLevel)
		query.set("claim_risk_level", params.claimRiskLevel);
	if (params.freshness) query.set("freshness", params.freshness);
	if (params.image) query.set("image", params.image);
	if (params.lifecycleStatus)
		query.set("lifecycle_status", params.lifecycleStatus);
	if (params.group) query.set("group", params.group);
	if (params.productFamily) query.set("product_family", params.productFamily);
	if (params.copyRoute) query.set("copy_route", params.copyRoute);
	if (params.claimGate) query.set("claim_gate", params.claimGate);
	if (params.intelligenceConfidence)
		query.set("intelligence_confidence", params.intelligenceConfidence);
	if (params.sort) query.set("sort", params.sort);
	query.set("view", "REGISTRY");
	query.set("limit", String(params.limit ?? 50));
	query.set("offset", String(params.offset ?? 0));
	const key = query.toString();
	const cached = productRegistryCache.get(key);
	if (cached?.data && cached.expiresAt > Date.now()) return cached.data;
	if (cached?.promise) return cached.promise;

	const request = fetchAPI<ProductCatalogResponse>(
		`/api/products?${key}`,
		{ signal: params.signal },
	);
	productRegistryCache.set(key, { expiresAt: 0, promise: request });
	try {
		const response = await request;
		const current = productRegistryCache.get(key);
		if (current?.promise === request) {
			productRegistryCache.set(key, {
				data: response,
				expiresAt: Date.now() + PRODUCT_REGISTRY_CACHE_TTL_MS,
			});
		}
		return response;
	} catch (error) {
		if (productRegistryCache.get(key)?.promise === request) {
			productRegistryCache.delete(key);
		}
		throw error;
	}
}

/**
 * Load one authoritative product row after an operator selects it from the
 * catalog.  The Cockpit grounding gate consumes image_url/local_image_path,
 * so it must not rely on a picker projection when binding the generation
 * product.
 */
export async function fetchProductDetail(
	productId: string,
	signal?: AbortSignal,
): Promise<Product> {
	const path = `/api/products/${encodeURIComponent(productId)}`;
	return signal
		? fetchAPI<Product>(path, { signal })
		: fetchAPI<Product>(path);
}

export async function fetchProductStrategyTypeRegistry(
	signal?: AbortSignal,
): Promise<ProductStrategyTypeRegistryResponse> {
	const key = "product-strategy-type-registry";
	const cached = productStrategyRegistryCache.get(key);
	if (cached?.data && cached.expiresAt > Date.now()) return cached.data;
	if (cached?.promise) return cached.promise;

	const request = fetchAPI<ProductStrategyTypeRegistryResponse>(
		"/api/creative-intelligence/product-strategy-type-registry",
		{ signal },
	);
	productStrategyRegistryCache.set(key, { expiresAt: 0, promise: request });
	try {
		const response = await request;
		const current = productStrategyRegistryCache.get(key);
		if (current?.promise === request) {
			productStrategyRegistryCache.set(key, {
				data: response,
				expiresAt: Date.now() + PRODUCT_STRATEGY_REGISTRY_CACHE_TTL_MS,
			});
		}
		return response;
	} catch (error) {
		if (productStrategyRegistryCache.get(key)?.promise === request) {
			productStrategyRegistryCache.delete(key);
		}
		throw error;
	}
}

export async function fetchProductTypeCopyEligibleReport(
	signal?: AbortSignal,
): Promise<ProductTypeCopyEligibleReport> {
	return fetchAPI<ProductTypeCopyEligibleReport>(
		"/api/copywriting/p4/eligible-report",
		{ signal },
	);
}

export async function fetchCatalogAuthorityReport(): Promise<CatalogAuthorityReport> {
	return fetchAPI<CatalogAuthorityReport>(
		"/api/copywriting/p5-8/catalog-authority",
	);
}

export async function registerProductStrategyType(
	input: ProductStrategyTypeRegistrationRequest,
): Promise<ProductStrategyTypeRegistryEntry> {
	const response = await fetchAPI<ProductStrategyTypeRegistryEntry>(
		"/api/creative-intelligence/product-strategy-type-registry",
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(input),
		},
	);
	invalidateProductStrategyTypeRegistryCache();
	invalidateProductRegistryCache();
	return response;
}

export async function updateProductStrategyType(
	cluster: string,
	productTypeGroup: string,
	input: ProductStrategyTypeUpdateRequest,
): Promise<ProductStrategyTypeRegistryEntry> {
	const response = await fetchAPI<ProductStrategyTypeRegistryEntry>(
		`/api/creative-intelligence/product-strategy-type-registry/${encodeURIComponent(cluster)}/${encodeURIComponent(productTypeGroup)}`,
		{
			method: "PATCH",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(input),
		},
	);
	invalidateProductStrategyTypeRegistryCache();
	invalidateProductRegistryCache();
	return response;
}

export async function deleteProductStrategyType(
	cluster: string,
	productTypeGroup: string,
): Promise<ProductStrategyTypeRegistryEntry> {
	const response = await fetchAPI<ProductStrategyTypeRegistryEntry>(
		`/api/creative-intelligence/product-strategy-type-registry/${encodeURIComponent(cluster)}/${encodeURIComponent(productTypeGroup)}`,
		{ method: "DELETE" },
	);
	invalidateProductStrategyTypeRegistryCache();
	invalidateProductRegistryCache();
	return response;
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
	const response = await fetchAPI<ProductStrategyTaxonomy>(
		`/api/products/strategy-taxonomy/${encodeURIComponent(productId)}/review`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(input),
		},
	);
	invalidateProductRegistryCache();
	return response;
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
	signal?: AbortSignal,
): Promise<ProductCatalogResponse> {
	const purposeQuery = purpose ? `&purpose=${encodeURIComponent(purpose)}` : "";
	return fetchAPI<ProductCatalogResponse>(
		`/api/products/search?q=${encodeURIComponent(query)}&limit=${encodeURIComponent(
			String(limit),
		)}&offset=0${purposeQuery}`,
		{ signal },
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

export interface ProductIntelligenceRecomputeResult {
	product_id: string;
	draft_id: string | null;
	source_url: string;
	intake_outcome: string | null;
	extracted_fields: Record<string, unknown>;
	/**
	 * Fields where the page stated a value but the draft's existing evidence was
	 * preserved. Carries the discarded text so a reviewer can adopt it deliberately.
	 */
	evidence_skipped?: {
		field: string;
		reason: string;
		extracted_value_not_stored?: string;
	}[];
	/** Fields we LOOKED for and the page does not state — distinct from "not checked". */
	unresolved: Record<string, string>;
	variant: string | null;
	variant_resolution: string | null;
	size_resolution: string | null;
	evidence_methods: string[];
	candidate_status: string | null;
	candidates_persisted: { field: string; value: unknown }[];
	candidates_skipped: { field: string; reason: string }[];
	provider: string | null;
	model: string | null;
	refused_model_fields: string[];
	/** DIRECT_FETCH, or AUTHENTICATED_BROWSER_RELAY when TikTok's wall forced the browser lane. */
	acquisition_mode?: string | null;
	relay?: {
		tab_id: number | null;
		matched_tabs: number | null;
		replayed: boolean | null;
		/** Keys the backend refused from the extension reply — the allowlist, made visible. */
		dropped_keys: string[];
		evidence_request_id: string | null;
	} | null;
	approved: boolean;
}

/**
 * A Recompute that stopped because the operator has to do something in their own browser.
 * Carries the backend code VERBATIM — the UI explains it, it never replaces it.
 */
export interface TikTokRelayBlocker {
	code: string;
	reason: string;
	product_url: string;
	operator_actionable: boolean;
}

/**
 * Re-acquire an EXISTING product's evidence from its own stored source link.
 *
 * Deliberately NOT `/api/products/import-tiktokshop`: that route creates a product, so
 * using it to refresh a catalogue item would mint a duplicate row on every press.
 */
export async function recomputeProductIntelligence(
	productId: string,
): Promise<ProductIntelligenceRecomputeResult> {
	return fetchAPI<ProductIntelligenceRecomputeResult>(
		`/api/product-intelligence/${encodeURIComponent(productId)}/recompute`,
		{ method: "POST", headers: { "Content-Type": "application/json" } },
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

/**
 * Create a review draft SEEDED from the product's latest APPROVED snapshot
 * (fill-if-empty, keep-if-exists), instead of a blank/product-only draft. Used by
 * the "Create Review Draft" action so the editor opens on the current approved
 * truth rather than empty fields. Idempotent for the single open draft; unrelated
 * open drafts are superseded (content preserved) by the backend revision lifecycle.
 */
export async function createProductIntelligenceRevisionDraft(
	productId: string,
	options?: { created_by?: string; revision_reason?: string },
): Promise<ProductIntelligenceReviewDraft> {
	return fetchAPI<ProductIntelligenceReviewDraft>(
		`/api/products/${encodeURIComponent(productId)}/intelligence/revision-drafts`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(options ?? {}),
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

/**
 * 08D: record one governed absence disposition on the OPEN draft. The server is the
 * authority on which dispositions are legal per field/category; the response is the
 * same validation payload /validate returns.
 */
export async function setProductIntelligenceFieldDisposition(
	draftId: string,
	payload: {
		field_name: string;
		disposition:
			| "NOT_STATED_IN_SOURCE"
			| "NOT_APPLICABLE"
			| "REQUIRES_EXTERNAL_EVIDENCE";
		reviewed_by: string;
		reviewer_note: string;
	},
): Promise<ProductIntelligenceReviewDraftValidationResponse> {
	return fetchAPI<ProductIntelligenceReviewDraftValidationResponse>(
		`/api/product-intelligence/review-drafts/${encodeURIComponent(draftId)}/field-dispositions`,
		{
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
		},
	);
}

export async function approveProductIntelligenceReviewDraft(
	draftId: string,
	payload: {
		approved_by?: string | null;
		approval_note?: string | null;
		/**
		 * 08D: records that the approver READ the review-required claim set. Clears
		 * CLAIM_REVIEW_REQUIRED only — CLAIM_BLOCKED is absolute and has no override.
		 */
		claim_review_acknowledged?: boolean;
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
