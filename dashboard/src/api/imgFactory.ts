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

// ── Gated live generation (credit-spending) ───────────────────────────────────
// These call the SAME proven one-door lane OperatorPage uses. They are wired for
// the cockpit but MUST only ever run behind an explicit operator credit-spend
// confirmation — never auto-fire. Live generation is NOT fired or verified in the
// build session; the register-output/review/save path below is credit-free.

export interface StartImgGenerationInput {
	prompt: string;
	image_media_ids?: string[];
	aspect?: string;
	model?: string;
	image_model?: string;
	duration_s?: number;
	count?: number;
	refs?: Record<string, any>;
	startAsset?: Record<string, any>;
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
 * Start a REAL, credit-spending IMG generation via the proven one-door lane.
 * Call ONLY after an explicit operator credit-spend confirmation.
 */
export async function startImgGeneration(
	input: StartImgGenerationInput,
): Promise<StartImgGenerationResult> {
	return postAPI<StartImgGenerationResult>("/api/flow/generate", {
		mode: "IMG",
		prompt: input.prompt,
		image_media_ids: input.image_media_ids ?? [],
		aspect: input.aspect ?? "9:16",
		model: input.model,
		image_model: input.image_model,
		duration_s: input.duration_s,
		count: input.count,
		refs: input.refs,
		startAsset: input.startAsset,
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
