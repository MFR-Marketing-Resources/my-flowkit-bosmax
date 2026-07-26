/**
 * Exact-product final-output client.
 *
 * For products with exact_product_composite_required the operator path is:
 *   1. resolveExactGenerationGate (fail closed before credits)
 *   2. Generate scene-only plate (NO product reference to Flow)
 *   3. POST compose-from-plate → final composite media only
 *
 * Policy resolution is FAIL-CLOSED when a product is selected:
 * only an explicit successful response with
 * exact_product_composite_required === false may use the standard
 * reference-conditioned route. Network/parse failures block generation.
 */
import { getAPI, postAPI } from "./client";

export const EXACT_PRODUCT_POLICY_UNAVAILABLE = "EXACT_PRODUCT_POLICY_UNAVAILABLE";

export interface ExactProductPolicy {
	product_id: string;
	product_display_name?: string | null;
	exact_product_composite_required: boolean;
	scene_only_required?: boolean;
	send_product_reference_to_flow?: boolean;
	canonical_valid?: boolean;
	canonical?: {
		schema_key?: string;
		source_sha256?: string;
		source_path?: string;
	} | null;
	error?: { code?: string; message?: string } | null;
	scene_only_prompt_block?: string;
	progress_stages?: string[];
	ok?: boolean;
}

export interface ExactComposeResult {
	ok: boolean;
	product_id: string;
	media_id: string;
	url: string;
	output_sha256: string;
	size_mb: number;
	status: string;
	truth_status: string;
	preview_sha_equals_saved_sha: boolean;
	lineage: {
		raw_plate_media_id?: string | null;
		raw_plate_sha256?: string;
		final_media_id?: string;
		final_output_sha256?: string;
		raw_plate_approvable?: boolean;
		truth_status?: string;
		transform?: Record<string, number>;
		qa?: Record<string, unknown>;
	};
	stages_completed?: string[];
}

export type ExactGenerationGate =
	| { mode: "no_product" }
	| { mode: "standard"; policy: ExactProductPolicy }
	| { mode: "exact"; policy: ExactProductPolicy }
	| { mode: "blocked"; code: string; message: string };

/**
 * Fail-closed exact-policy gate before any provider credit spend.
 * - no product selected → no_product (caller decides lane rules)
 * - explicit exact_product_composite_required === false → standard
 * - explicit true (+ canonical valid) → exact
 * - fetch failure / inconclusive → blocked (never assume non-exact)
 */
export async function resolveExactGenerationGate(
	productId: string | null | undefined,
	fetchPolicy: (
		id: string,
	) => Promise<ExactProductPolicy> = fetchExactProductPolicy,
): Promise<ExactGenerationGate> {
	const id = (productId ?? "").trim();
	if (!id) {
		return { mode: "no_product" };
	}
	try {
		const policy = await fetchPolicy(id);
		if (policy.exact_product_composite_required === true) {
			if (policy.canonical_valid === false) {
				return {
					mode: "blocked",
					code:
						policy.error?.code || "CANONICAL_PRODUCT_SOURCE_INVALID",
					message:
						policy.error?.message ||
						"Canonical product source invalid — exact composite blocked before credit spend.",
				};
			}
			return { mode: "exact", policy };
		}
		if (policy.exact_product_composite_required === false) {
			return { mode: "standard", policy };
		}
		return {
			mode: "blocked",
			code: EXACT_PRODUCT_POLICY_UNAVAILABLE,
			message:
				"Exact-product policy response inconclusive — generation blocked. Retry policy lookup before spending credits.",
		};
	} catch (err) {
		const detail =
			err instanceof Error && err.message
				? err.message
				: "exact product policy endpoint unavailable";
		return {
			mode: "blocked",
			code: EXACT_PRODUCT_POLICY_UNAVAILABLE,
			message: `${EXACT_PRODUCT_POLICY_UNAVAILABLE}: ${detail}`,
		};
	}
}

export async function fetchExactProductPolicy(
	productId: string,
): Promise<ExactProductPolicy> {
	return getAPI<ExactProductPolicy>(`/api/exact-product/policy/${productId}`);
}

export async function validateExactProduct(
	productId: string,
): Promise<ExactProductPolicy> {
	return postAPI<ExactProductPolicy>(
		`/api/exact-product/validate/${productId}`,
		{},
	);
}

export async function buildExactSceneOnlyPrompt(
	productId: string,
	prompt: string,
): Promise<{
	product_id: string;
	exact_product_composite_required: boolean;
	prompt: string;
	send_product_reference_to_flow: boolean;
}> {
	return postAPI(`/api/exact-product/scene-only-prompt`, {
		product_id: productId,
		prompt,
	});
}

export async function composeExactFromPlate(input: {
	product_id: string;
	background_media_id?: string;
	background_local_path?: string;
	lane?: "studio" | "poster" | "product_only_hero";
	job_id?: string;
}): Promise<ExactComposeResult> {
	return postAPI<ExactComposeResult>("/api/exact-product/compose-from-plate", {
		product_id: input.product_id,
		background_media_id: input.background_media_id ?? null,
		background_local_path: input.background_local_path ?? null,
		lane: input.lane ?? "studio",
		job_id: input.job_id ?? null,
	});
}
