// Montage API — plan, durable runs, M-04 authorize-generation, readiness, gated assemble.
import { getAPI, postAPI } from "./client";
import type { VideoCapabilityMatrix } from "../utils/videoCapability";

export interface MontageScenePlan {
	scene_id: string;
	beat_id: string;
	block_index: number;
	route: string;
	reference_policy: string;
	transport_mode: string;
	source_mode: string;
	image_generation_required: boolean;
	video_generation_required: boolean;
	objective: string;
	visual_action: string;
	product_media_id: string | null;
	reference_media_ids: string[];
	previous_clip_media_id: string | null;
	role: string;
}

export interface MontagePlanResponse {
	product_id: string;
	hook_id: string;
	background_id: string;
	scene_count: number;
	scenes: MontageScenePlan[];
	assembly_path: string;
	credit_spend: boolean;
	execution_supported?: boolean;
	model: string;
	duration_seconds: number;
}

export interface MontageSceneJob {
	scene_id: string;
	beat_id: string;
	block_index: number;
	route: string;
	transport_mode: string;
	source_mode: string;
	reference_policy: string;
	status: string;
	workspace_execution_package_id: string | null;
	package_prompt?: string | null;
	start_asset_snapshot?: Record<string, unknown> | null;
	video_media_id: string | null;
	image_media_id: string | null;
	error_code: string | null;
	detail: string;
	bulk_item_id?: string;
	montage_run_id?: string;
}

export interface MontageExecuteResponse {
	product_id: string;
	scene_count: number;
	scenes: MontageSceneJob[];
	credit_spend: boolean;
	ok: boolean;
	detail: string;
	assembly_path: string;
	execution_supported?: boolean;
}

export interface MontageRunResponse {
	montage_run_id: string;
	kind: string;
	status: string;
	product_id?: string;
	ok?: boolean;
	detail?: string;
	total_scenes: number;
	scenes: MontageSceneJob[];
	execution_supported?: boolean;
	credit_spend?: boolean;
	assembly_path?: string;
	status_counts?: Record<string, number>;
	config?: Record<string, unknown>;
}

export interface MontageReadinessResponse {
	ok: boolean;
	code: string | null;
	detail: string;
	blockers: Array<Record<string, unknown>>;
	ready_scene_ids: string[];
	clip_media_ids: string[];
	blocked_incomplete_scene_set?: string | null;
	assembly_path: string;
	credit_spend?: boolean;
	montage_run_id?: string;
	scenes?: MontageSceneJob[];
}

export interface MontageAssembleResponse {
	ok: boolean;
	assembly_path: string;
	readiness: {
		ok: boolean;
		ready_scene_ids: string[];
		clip_media_ids: string[];
	};
	concat: Record<string, unknown>;
	credit_spend: boolean;
	montage_run_id?: string;
}

export interface MontageGenerationEstimate {
	montage_run_id: string;
	expected_video_generations: number;
	expected_image_operations?: number;
	expected_provider_operations?: number;
	pending_scene_ids: string[];
	pending_image_scene_ids?: string[];
	summary: string;
	authorization_required: boolean;
	credit_spend: boolean;
	run_status?: string;
	total_scenes?: number;
}

export interface MontageAuthorizeGenerationResponse extends MontageGenerationEstimate {
	ok: boolean;
	authorized: boolean;
	dry_run: boolean;
	dispatched: Array<Record<string, unknown>>;
	detail: string;
	run?: MontageRunResponse;
}

export async function fetchMontagePolicies(): Promise<{
	reference_policies: string[];
	execution_supported?: boolean;
	assembly_path?: string;
}> {
	return getAPI("/api/montage/policies");
}

export async function fetchMontageVideoCapability(): Promise<VideoCapabilityMatrix> {
	return getAPI("/api/flow/video-capability-matrix");
}

export async function createMontagePlan(input: {
	product_id: string;
	hook_id?: string;
	background_id?: string;
	product_media_id?: string | null;
	default_policy?: string;
	model: string;
	duration_seconds: number;
	copy_v2_context?: Record<string, unknown> | null;
	use_product_mascot?: boolean;
}): Promise<MontagePlanResponse> {
	return postAPI("/api/montage/plan", {
		product_id: input.product_id,
		hook_id: input.hook_id ?? "AUTO",
		background_id: input.background_id ?? "AUTO",
		product_media_id: input.product_media_id ?? null,
		default_policy: input.default_policy ?? "PRODUCT_ANCHOR",
		model: input.model,
		duration_seconds: input.duration_seconds,
		copy_v2_context: input.copy_v2_context ?? null,
		use_product_mascot: input.use_product_mascot ?? false,
		beats: [],
	});
}

export async function executeMontageScenes(input: {
	product_id: string;
	hook_id?: string;
	background_id?: string;
	product_media_id?: string | null;
	default_policy?: string;
	scene_context_override?: string | null;
	model: string;
	duration_seconds: number;
	copy_v2_context?: Record<string, unknown> | null;
	use_product_mascot?: boolean;
}): Promise<MontageExecuteResponse> {
	return postAPI("/api/montage/execute-scenes", {
		product_id: input.product_id,
		hook_id: input.hook_id ?? "AUTO",
		background_id: input.background_id ?? "AUTO",
		product_media_id: input.product_media_id ?? null,
		default_policy: input.default_policy ?? "PRODUCT_ANCHOR",
		beats: [],
		copy_fallback_confirmed: false,
		scene_context_override: input.scene_context_override ?? null,
		model: input.model,
		duration_seconds: input.duration_seconds,
		allow_live_generate: false,
		copy_v2_context: input.copy_v2_context ?? null,
		use_product_mascot: input.use_product_mascot ?? false,
	});
}

/** M-02 durable ledger: packages + per-scene job state. */
export async function createMontageRun(input: {
	product_id: string;
	hook_id?: string;
	background_id?: string;
	product_media_id?: string | null;
	default_policy?: string;
	scene_context_override?: string | null;
	model: string;
	duration_seconds: number;
	copy_v2_context?: Record<string, unknown> | null;
	use_product_mascot?: boolean;
}): Promise<MontageRunResponse> {
	return postAPI("/api/montage/runs", {
		product_id: input.product_id,
		hook_id: input.hook_id ?? "AUTO",
		background_id: input.background_id ?? "AUTO",
		product_media_id: input.product_media_id ?? null,
		default_policy: input.default_policy ?? "PRODUCT_ANCHOR",
		beats: [],
		copy_fallback_confirmed: false,
		scene_context_override: input.scene_context_override ?? null,
		allow_live_generate: false,
		model: input.model,
		duration_seconds: input.duration_seconds,
		copy_v2_context: input.copy_v2_context ?? null,
		use_product_mascot: input.use_product_mascot ?? false,
	});
}

export async function fetchMontageRun(runId: string): Promise<MontageRunResponse> {
	return getAPI(`/api/montage/runs/${encodeURIComponent(runId)}`);
}

export async function bindMontageSceneResult(
	runId: string,
	input: {
		scene_id: string;
		media_id: string;
		result_kind?: "video" | "image";
		job_id?: string | null;
	},
): Promise<MontageRunResponse> {
	return postAPI(`/api/montage/runs/${encodeURIComponent(runId)}/bind-result`, {
		scene_id: input.scene_id,
		media_id: input.media_id,
		result_kind: input.result_kind ?? "video",
		job_id: input.job_id ?? null,
	});
}

/** M-04 credit estimate — no spend. */
export async function fetchMontageGenerationEstimate(
	runId: string,
): Promise<MontageGenerationEstimate> {
	return getAPI(
		`/api/montage/runs/${encodeURIComponent(runId)}/generation-estimate`,
	);
}

/**
 * M-04 authorize multi-scene generation.
 * dryRun=true (default): validate count only.
 * dryRun=false: dispatches live one-door generate per pending scene (credits).
 */
export async function authorizeMontageGeneration(
	runId: string,
	input: {
		confirm_credit_burn: boolean;
		expected_video_generations: number;
		expected_provider_operations: number;
		dry_run?: boolean;
	},
): Promise<MontageAuthorizeGenerationResponse> {
	return postAPI(
		`/api/montage/runs/${encodeURIComponent(runId)}/authorize-generation`,
		{
			confirm_credit_burn: input.confirm_credit_burn,
			expected_video_generations: input.expected_video_generations,
			expected_provider_operations: input.expected_provider_operations,
			dry_run: input.dry_run ?? true,
		},
	);
}

export async function checkMontageRunReadiness(
	runId: string,
): Promise<MontageReadinessResponse> {
	return getAPI(
		`/api/montage/runs/${encodeURIComponent(runId)}/assembly-readiness`,
	);
}

export async function assembleMontageRunDryRun(
	runId: string,
	jobId = "montage-discrete-run",
): Promise<MontageAssembleResponse> {
	return assembleMontageRun(runId, {
		job_id: jobId,
		dry_run: true,
		confirm_live_credit_burn: false,
	});
}

export async function assembleMontageRun(
	runId: string,
	input: {
		job_id?: string;
		dry_run: boolean;
		confirm_live_credit_burn: boolean;
	},
): Promise<MontageAssembleResponse> {
	return postAPI(`/api/montage/runs/${encodeURIComponent(runId)}/assemble`, {
		job_id: input.job_id ?? "montage-discrete-run",
		dry_run: input.dry_run,
		confirm_live_credit_burn: input.confirm_live_credit_burn,
	});
}

export async function checkMontageAssemblyReadiness(
	scenes: Array<Record<string, unknown>>,
): Promise<MontageReadinessResponse> {
	return postAPI("/api/montage/assembly-readiness", { scenes });
}

export async function assembleMontageDryRun(
	scenes: Array<Record<string, unknown>>,
	jobId = "montage-discrete",
): Promise<MontageAssembleResponse> {
	return postAPI("/api/montage/assemble", {
		scenes,
		job_id: jobId,
		dry_run: true,
		confirm_live_credit_burn: false,
	});
}
