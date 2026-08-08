// Montage API — plan, execute packages, readiness, gated assemble (dry-run).
import { getAPI, postAPI } from "./client";

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
	video_media_id: string | null;
	image_media_id: string | null;
	error_code: string | null;
	detail: string;
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

export interface MontageReadinessResponse {
	ok: boolean;
	code: string | null;
	detail: string;
	blockers: Array<Record<string, unknown>>;
	ready_scene_ids: string[];
	clip_media_ids: string[];
	blocked_incomplete_scene_set: string | null;
	assembly_path: string;
	credit_spend: boolean;
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
}

export async function fetchMontagePolicies(): Promise<{
	reference_policies: string[];
	execution_supported?: boolean;
	assembly_path?: string;
}> {
	return getAPI("/api/montage/policies");
}

export async function createMontagePlan(input: {
	product_id: string;
	hook_id?: string;
	background_id?: string;
	product_media_id?: string | null;
	default_policy?: string;
}): Promise<MontagePlanResponse> {
	return postAPI("/api/montage/plan", {
		product_id: input.product_id,
		hook_id: input.hook_id ?? "AUTO",
		background_id: input.background_id ?? "AUTO",
		product_media_id: input.product_media_id ?? null,
		default_policy: input.default_policy ?? "PRODUCT_ANCHOR",
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
}): Promise<MontageExecuteResponse> {
	return postAPI("/api/montage/execute-scenes", {
		product_id: input.product_id,
		hook_id: input.hook_id ?? "AUTO",
		background_id: input.background_id ?? "AUTO",
		product_media_id: input.product_media_id ?? null,
		default_policy: input.default_policy ?? "PRODUCT_ANCHOR",
		beats: [],
		copy_fallback_confirmed: true,
		scene_context_override: input.scene_context_override ?? null,
		allow_live_generate: false,
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
