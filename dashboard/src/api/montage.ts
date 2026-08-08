// Montage API — plan, durable runs, readiness, gated assemble (dry-run).
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

/** M-02 durable ledger: packages + per-scene job state. */
export async function createMontageRun(input: {
	product_id: string;
	hook_id?: string;
	background_id?: string;
	product_media_id?: string | null;
	default_policy?: string;
	scene_context_override?: string | null;
}): Promise<MontageRunResponse> {
	return postAPI("/api/montage/runs", {
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
	return postAPI(`/api/montage/runs/${encodeURIComponent(runId)}/assemble`, {
		job_id: jobId,
		dry_run: true,
		confirm_live_credit_burn: false,
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
