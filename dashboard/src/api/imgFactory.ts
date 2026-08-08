import type { CreativeAsset } from "../types";
import { fetchAPI, getAPI, postAPI } from "./client";

export interface ImgAssetLane {
	lane_id: string;
	label: string;
	family: string;
	purpose: string;
	required_inputs: string[];
	optional_inputs: string[];
	requires_product_id: boolean;
	requires_character_reference: boolean;
	requires_scene_reference: boolean;
	requires_style_reference: boolean;
	default_semantic_role: string;
	default_asset_subtype: string;
	default_allowed_modes: string[];
	default_engine_slot_eligibility: string[];
	allows_rendered_text: boolean;
	default_contains_rendered_text: boolean;
	default_approved_for_video_support: boolean;
	default_approved_for_poster: boolean;
}

export interface ImgAssetLaneListResponse {
	items: ImgAssetLane[];
	total: number;
}

export type ImgFastlaneRoute = "FRAMES" | "INGREDIENTS";
export type ImgFastlaneIngredientRole =
	| "AVATAR_REFERENCE"
	| "SCENE_REFERENCE"
	| "STYLE_REFERENCE"
	| "PRODUCT_REFERENCE";

export interface ImgFastlanePreset {
	preset_id: string;
	label: string;
	route: ImgFastlaneRoute;
	lane_id: string;
	ingredient_role?: ImgFastlaneIngredientRole | null;
	description: string;
	required_inputs: string[];
	output_spec: string;
	tags: string[];
}

export interface ImgFastlanePresetListResponse {
	items: ImgFastlanePreset[];
	total: number;
}

export interface ImgFastlanePromptPreviewInput {
	preset_id: string;
	route: ImgFastlaneRoute;
	ingredient_role?: ImgFastlaneIngredientRole | null;
	product_id?: string | null;
	character_reference_asset_id?: string | null;
	scene_reference_asset_id?: string | null;
	style_reference_asset_id?: string | null;
	product_reference_asset_id?: string | null;
	advanced_override_notes?: string | null;
	// A scene-context registry SceneCode; injects the scene's Background: text into
	// the compiled prompt (any of the 20 scenes usable without a generated image).
	scene_context_code?: string | null;
	creative_mode?: string | null;
	requested_outputs?: number;
}

export interface CreativeCampaignContext {
	intelligence_status: "READY" | "INCOMPLETE";
	grounding_source: string;
	approved_snapshot_id?: string | null;
	approved_snapshot_version?: number | null;
	product_family: string;
	formula: string;
	audience: string;
	desire: string;
	objection: string;
	trigger: string;
	safe_angle: string;
	tone: string;
	approved_facts: string[];
	missing_fields: string[];
	field_provenance: Record<string, string>;
	art_direction: {
		creative_territory: string;
		layout_family: string;
		visual_tension: string;
		product_anchor: string;
		copy_anchor: string;
		headline_personality: string;
		headline_line_budget: number;
		type_contrast: string;
		cta_treatment: string;
		negative_space_strategy: string;
		brand_visual_codes: string[];
		anti_cliche_rules: string[];
	};
}

export interface ImgFastlanePromptPreview {
	preset_id: string;
	route: ImgFastlaneRoute;
	ingredient_role?: ImgFastlaneIngredientRole | null;
	lane_id: string;
	prompt_text: string;
	// Clean, engine-agnostic brief actually sent to the generator (no internal
	// preset/route/lane ids) — portable verbatim to Flow, ChatGPT Image, and Grok.
	engine_prompt_text: string;
	display_name_suggestion: string;
	blockers: string[];
	warnings: string[];
	output_spec: string;
	negative_rules: string[];
	reference_map: string[];
	creative_direction?: {
		mode?: string;
		compiler_version?: string;
		prompt_fingerprint?: string;
		reference_pack_id?: string;
		provider_operation_plan?: {
			max_provider_operations: number;
			max_retry_operations: number;
		};
		creative_context?: CreativeCampaignContext;
	};
}

export interface ImgProviderStatus {
	provider_state:
		| "SAVE_TO_LIBRARY_READY_GENERATION_RUNTIME_EXTERNAL"
		| "NOT_CONFIGURED";
	detail: string;
	generation_endpoint?: string | null;
}

export interface SaveImgOutputInput {
	lane_id: string;
	display_name: string;
	description?: string | null;
	generated_artifact_media_id?: string | null;
	image_base64?: string | null;
	file_name?: string | null;
	product_id?: string | null;
	source_character_asset_id?: string | null;
	source_scene_asset_id?: string | null;
	source_style_asset_id?: string | null;
	source_prompt_fingerprint?: string | null;
	source_workspace_execution_package_id?: string | null;
	source_prompt_package_snapshot_id?: string | null;
	creative_mode?: string | null;
	category?: string | null;
	silo?: string | null;
	product_type?: string | null;
	identity_lock_status?: string | null;
	scale_truth_status?: string | null;
	claim_safety_status?: string | null;
	review_status?: "DRAFT" | "PENDING_REVIEW" | "APPROVED" | "REJECTED";
}

export async function fetchImgAssetLanes(): Promise<ImgAssetLaneListResponse> {
	return fetchAPI<ImgAssetLaneListResponse>("/api/img-factory/lanes");
}

export async function fetchImgFastlanePresets(): Promise<ImgFastlanePresetListResponse> {
	return fetchAPI<ImgFastlanePresetListResponse>("/api/img-factory/fastlane-presets");
}

export async function compileImgFastlanePromptPreview(
	input: ImgFastlanePromptPreviewInput,
): Promise<ImgFastlanePromptPreview> {
	return postAPI<ImgFastlanePromptPreview>("/api/img-factory/fastlane-preview", input);
}

export async function fetchImgProviderStatus(): Promise<ImgProviderStatus> {
	return fetchAPI<ImgProviderStatus>("/api/img-factory/provider-status");
}

export async function saveImgOutputToLibrary(
	input: SaveImgOutputInput,
): Promise<CreativeAsset> {
	return postAPI<CreativeAsset>("/api/img-factory/save", input);
}

export interface CreativeCampaignPromptPreviewInput {
	product_id: string;
	output_intent?: "COMPLETE_POSTER" | "CLEAN_KEY_VISUAL" | "COMPLETE_IMAGE";
	model?: string;
	objective?: string;
	composition?: string;
	camera?: string;
	lighting?: string;
	scene_direction?: string;
	/** Structural copy-space only; never actual headline/support/CTA wording. */
	copy_space?: Record<string, string | number | boolean>;
	copy_layout?: Record<string, string>;
	negative_constraints?: string[];
	aspect_ratio?: string;
	creative_mode?: string;
}

export interface CreativeCampaignPromptPreview {
	compiler_version: string;
	product_id: string;
	output_intent: string;
	aspect_ratio: string;
	compiled_prompt: string;
	prompt_fingerprint: string;
	reference_pack: { pack_id: string; pack_status: string };
	blockers: string[];
	warnings: string[];
	provider_operation_plan: {
		max_provider_operations: number;
		max_retry_operations: number;
	};
	creative_context?: CreativeCampaignContext;
}

export interface ProductReferencePackSummary {
	pack_id: string;
	product_id: string;
	pack_status: "DRAFT" | "PENDING_REVIEW" | "APPROVED" | "REJECTED";
	machine_qa_status: "PASS" | "WARN" | "FAIL";
	physical_measurements?: {
		physical_width_mm?: number | null;
		physical_height_mm?: number | null;
		physical_depth_mm?: number | null;
		volume_ml?: number | null;
		scale_evidence_source?: string;
		scale_confidence?: string;
	};
	references?: Array<{
		role: string;
		approved: boolean;
		local_file_path?: string | null;
		sha256?: string | null;
	}>;
}

export async function fetchProductReferencePack(
	productId: string,
): Promise<ProductReferencePackSummary> {
	return fetchAPI<ProductReferencePackSummary>(
		`/api/img-factory/products/${encodeURIComponent(productId)}/reference-pack`,
	);
}

export async function approveProductReferencePack(
	productId: string,
	input: { reviewed_by: string; note?: string },
): Promise<ProductReferencePackSummary> {
	return postAPI<ProductReferencePackSummary>(
		`/api/img-factory/products/${encodeURIComponent(productId)}/reference-pack/approve`,
		input,
	);
}

export async function compileCreativeCampaignPrompt(
	input: CreativeCampaignPromptPreviewInput,
): Promise<CreativeCampaignPromptPreview> {
	return postAPI<CreativeCampaignPromptPreview>(
		"/api/img-factory/creative-campaign/preview",
		input,
	);
}

// ── Gated live IMG generation ─────────────────────────────────────────────────
// These call the SAME proven one-door lane OperatorPage uses. They are wired for
// the cockpit but MUST only ever run behind an explicit operator confirmation —
// never auto-fire. IMG does not use Google Flow video credits. Live generation is
// NOT fired or verified in the build session; the register-output/review/save path
// below is credit-free.

export interface StartImgGenerationInput {
	prompt: string;
	/** Server-side product lineage key; client never supplies truth bytes/status. */
	product_id?: string;
	/** Route context used only to select the server strategy; lock validation stays server-owned. */
	visual_lane_id?: string;
	image_media_ids?: string[];
	aspect?: string;
	model?: string;
	image_model?: string;
	duration_s?: number;
	count?: number;
	refs?: Record<string, any>;
	startAsset?: Record<string, any>;
	image_contract_version?: string;
	reference_pack_id?: string;
	poster_copy_set_id?: string;
	output_intent?: string;
	creative_mode?: string;
	confirm_live_credit_burn?: boolean;
	maximum_provider_operations?: number;
	max_retry_operations?: number;
}

export interface StartImgGenerationResult {
	job_id: string;
}

export interface ImgGenerationJob {
	status: string;
	media_id?: string | null;
	video_media_id?: string | null;
	artifact?: string | null;
	url?: string | null;
	size_mb?: number | string | null;
	local_path?: string | null;
	error?: string | null;
}

export interface ImageArtifact {
	media_id: string;
	artifact_kind: string;
	local_path?: string | null;
	size_mb?: number | null;
	mode?: string | null;
	created_at?: string | null;
}

/**
 * Start a REAL IMG generation via the proven one-door lane.
 * Call ONLY after an explicit operator confirmation.
 */
export async function startImgGeneration(
	input: StartImgGenerationInput,
): Promise<StartImgGenerationResult> {
	return postAPI<StartImgGenerationResult>("/api/flow/generate", {
		mode: "IMG",
		prompt: input.prompt,
		product_id: input.product_id,
		visual_lane_id: input.visual_lane_id,
		image_media_ids: input.image_media_ids ?? [],
		aspect: input.aspect ?? "9:16",
		model: input.model,
		image_model: input.image_model,
		duration_s: input.duration_s,
		count: input.count,
	refs: input.refs,
	startAsset: input.startAsset,
	image_contract_version: input.image_contract_version,
	reference_pack_id: input.reference_pack_id,
	poster_copy_set_id: input.poster_copy_set_id,
	output_intent: input.output_intent,
	creative_mode: input.creative_mode,
	confirm_live_credit_burn: input.confirm_live_credit_burn,
	maximum_provider_operations: input.maximum_provider_operations,
	max_retry_operations: input.max_retry_operations,
	});
}

const IMG_JOB_TERMINAL_STATES = new Set([
	"DONE",
	"COMPLETE",
	"COMPLETED",
	"FAILED",
	"ERROR",
	"CANCELLED",
	"GENERATED_BUT_UNRETRIEVED",
]);

/**
 * Poll the generate job until it reaches a terminal state. The backend job is
 * asynchronous (starts as SUBMITTED/GENERATING), so a single GET returns before
 * the image exists. Loops every `intervalMs` up to `maxAttempts`, then returns
 * the last-seen job. This is a read-only poll — it never starts a generation.
 */
export async function pollImgGenerationJob(
	jobId: string,
	opts: { intervalMs?: number; maxAttempts?: number } = {},
): Promise<ImgGenerationJob> {
	const intervalMs = opts.intervalMs ?? 3000;
	const maxAttempts = opts.maxAttempts ?? 150;
	let last: ImgGenerationJob = { status: "SUBMITTED" };
	for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
		last = await getAPI<ImgGenerationJob>(`/api/flow/generate-job/${jobId}`);
		if (last.status && IMG_JOB_TERMINAL_STATES.has(last.status)) {
			return last;
		}
		await new Promise((resolve) => setTimeout(resolve, intervalMs));
	}
	return last;
}

/** Finished IMAGE artifacts, for the register-output picker (credit-free). */
export async function fetchImageArtifacts(limit = 50): Promise<ImageArtifact[]> {
	const response = await getAPI<{ artifacts: ImageArtifact[] }>(
		`/api/flow/artifacts?kind=image&limit=${limit}`,
	);
	return response.artifacts ?? [];
}

// ── F2V composite-frame resolver (safe validation gate) ───────────────────────

export interface F2vResolvedFrame {
	slot_key: string;
	source_kind: string;
	asset_id?: string | null;
	display_name?: string | null;
	preview_url?: string | null;
	download_url?: string | null;
	media_id?: string | null;
	local_file_path?: string | null;
	asset_fingerprint?: string | null;
}

export interface F2vFrameSourcesResponse {
	mode: string;
	start_frame: F2vResolvedFrame | null;
	end_frame: F2vResolvedFrame | null;
	resolved_frames: F2vResolvedFrame[];
	warnings: string[];
	blockers: string[];
}

export interface F2vFrameSourcesInput {
	product_id?: string | null;
	start_frame_asset_id?: string | null;
	end_frame_asset_id?: string | null;
	start_frame_manual_upload_present?: boolean;
}

/**
 * Validate/resolve F2V start/end frame selections through the backend resolver.
 * The resolver enforces COMPOSITE_FRAME_REFERENCE role + ACTIVE + F2V + APPROVED +
 * poster (rendered-text) exclusion — so a picker must gate selections through here.
 */
export async function resolveF2vFrameSources(
	input: F2vFrameSourcesInput,
): Promise<F2vFrameSourcesResponse> {
	return postAPI<F2vFrameSourcesResponse>(
		"/api/img-factory/f2v-frame-sources",
		input,
	);
}
