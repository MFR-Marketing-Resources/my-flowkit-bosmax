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
	duration_s?: number;
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
		duration_s: input.duration_s,
	});
}

export async function pollImgGenerationJob(jobId: string): Promise<ImgGenerationJob> {
	return getAPI<ImgGenerationJob>(`/api/flow/generate-job/${jobId}`);
}

/** Finished IMAGE artifacts, for the register-output picker (credit-free). */
export async function fetchImageArtifacts(limit = 50): Promise<ImageArtifact[]> {
	const response = await getAPI<{ artifacts: ImageArtifact[] }>(
		`/api/flow/artifacts?kind=image&limit=${limit}`,
	);
	return response.artifacts ?? [];
}
