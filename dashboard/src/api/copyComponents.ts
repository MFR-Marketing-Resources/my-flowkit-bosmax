import { getAPI, postAPI } from "./client";

// Copy Components lane (Phase B/C): reusable per-product building blocks
// (HOOK/SUBHOOK/USP_SET/CTA) that COMPOSE into copy sets. Authoring spends AI
// tokens; composing is free (deterministic assembly of approved components).

export const COMPONENT_TYPES = ["HOOK", "SUBHOOK", "USP_SET", "CTA"] as const;
export type ComponentType = (typeof COMPONENT_TYPES)[number];

export const COMPONENT_TYPE_LABEL: Record<ComponentType, string> = {
	HOOK: "Hook",
	SUBHOOK: "Subhook",
	USP_SET: "USP set",
	CTA: "CTA",
};

export const COMPONENT_STATUS_APPROVED = "COMPONENT_APPROVED";
export const COMPONENT_STATUS_REVIEW = "COMPONENT_REVIEW_REQUIRED";

export interface CapacityPerAngle {
	angle_key: string;
	angle_label: string;
	combinations?: number;
	[key: string]: unknown;
}

export interface CopyComponentsCapacity {
	product_id: string;
	angles_derived: boolean;
	angle_warnings: string[];
	component_count: number;
	angle_count?: number;
	total_combinations: number;
	per_angle: CapacityPerAngle[];
	next_best?: {
		component_type: string;
		angle_key: string;
		angle_label?: string;
	} | null;
}

export interface CopyComponentRow {
	component_id: string;
	product_id: string;
	angle_key: string;
	angle_label?: string;
	component_type: string;
	content: string;
	status: string;
}

export interface ComposeResult {
	created: number;
	deduped: number;
	coverage?: { status?: string; dominant_share?: number } | null;
	warnings?: string[];
}

export interface AuthorResult {
	created_count: number;
	warnings?: string[];
}

export interface AddAnglesResult {
	ok: boolean;
	angle_count?: number;
	added?: number;
	capped?: boolean;
	claim_gate?: string;
	snapshot_version?: number;
	error?: string;
	claim_tokens?: string[];
}

// FREE — appends persona pains (angles) and re-approves; spends no AI tokens.
export async function addAngles(input: {
	product_id: string;
	pains: string[];
}): Promise<AddAnglesResult> {
	return postAPI<AddAnglesResult>("/api/copy-components/add-angles", input);
}

export interface SuggestAnglesResult {
	ok: boolean;
	suggestions: string[];
	existing_count?: number;
	remaining_slots?: number;
	warnings?: string[];
}

// SPENDS a small amount of AI tokens (one call). Proposes NEW candidate angles
// (buyer pains) grounded in the product's APPROVED knowledge + avatar. Returns
// suggestions for review — commits NOTHING; the operator edits then Adds them via
// addAngles (free, claim-gated).
export async function suggestAngles(input: {
	product_id: string;
	count?: number;
}): Promise<SuggestAnglesResult> {
	return postAPI<SuggestAnglesResult>(
		"/api/copy-components/suggest-angles",
		input,
	);
}

// ── Bulk angle suggestions (Phase 2) ────────────────────────────────────────

export interface EligibleProduct {
	product_id: string;
	name: string;
	angle_count: number;
	room: number;
}

export interface BulkSuggestProductResult {
	product_id: string;
	ok: boolean;
	suggestions?: string[];
	existing_count?: number;
	remaining_slots?: number;
	warnings?: string[];
	error?: string;
}

export interface BulkSuggestResult {
	results: BulkSuggestProductResult[];
	products: number;
	ok_products: number;
	total_suggestions: number;
}

// Read-only — the cross-product roster the bulk tool runs over (approved snapshot
// + room for more angles). No tokens.
export async function fetchEligibleProducts(): Promise<{
	items: EligibleProduct[];
	count: number;
}> {
	return getAPI("/api/copy-components/eligible-products");
}

// SPENDS AI tokens — one small text call per product (paced, server-side). Returns
// candidates per product for review; commits NOTHING (accept via addAngles). Send
// ids in chunks (~10-15) — the client drives the batching.
export async function bulkSuggestAngles(input: {
	product_ids: string[];
}): Promise<BulkSuggestResult> {
	return postAPI<BulkSuggestResult>("/api/copy-components/bulk-suggest", input);
}

export async function fetchCopyCapacity(
	productId: string,
): Promise<CopyComponentsCapacity> {
	return getAPI<CopyComponentsCapacity>(
		`/api/copy-components/capacity/${encodeURIComponent(productId)}`,
	);
}

export async function listCopyComponents(productId: string): Promise<{
	product_id: string;
	items: CopyComponentRow[];
	count: number;
}> {
	return getAPI(
		`/api/copy-components/product/${encodeURIComponent(productId)}`,
	);
}

// FREE — deterministic assembly, spends no AI tokens.
export async function composeCopyFromComponents(input: {
	product_id: string;
	count: number;
	formula_families?: string[];
	dry_run?: boolean;
}): Promise<ComposeResult> {
	return postAPI<ComposeResult>("/api/copy-components/compose", input);
}

// SPENDS AI TOKENS (unless dry_run). Authors ONE angle + ONE component type.
export async function authorCopyComponents(input: {
	product_id: string;
	angle_key: string;
	component_type: string;
	count: number;
	dry_run?: boolean;
}): Promise<AuthorResult> {
	return postAPI<AuthorResult>("/api/copy-components/author", input);
}

export async function approveCopyComponent(
	componentId: string,
	approvedBy = "operator",
): Promise<CopyComponentRow> {
	return postAPI<CopyComponentRow>(
		`/api/copy-components/${encodeURIComponent(componentId)}/approve`,
		{ approved_by: approvedBy },
	);
}
