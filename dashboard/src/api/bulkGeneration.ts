import { getAPI, postAPI } from "./client";

const BASE = "/api/bulk-generation";

export type BulkRunStatus =
	| "PENDING"
	| "RUNNING"
	| "COMPLETED"
	| "PARTIAL_FAILED"
	| "FAILED"
	| "CANCELLED"
	| "PAUSED";

export interface BulkRunSummary {
	bulk_run_id: string;
	kind: string;
	status: BulkRunStatus;
	total_expected: number;
	total_completed: number;
	total_failed: number;
	max_parallel_images?: number;
	max_parallel_videos?: number;
	status_counts?: Record<string, number>;
	items?: BulkRunItem[];
	config?: Record<string, unknown>;
}

export interface BulkRunItem {
	bulk_item_id: string;
	source_ref: string;
	item_type: string;
	status: string;
	job_id?: string | null;
	media_id?: string | null;
	local_path?: string | null;
	error?: string | null;
	retry_count?: number;
}

export interface CreateAvatarImageBulkRequest {
	avatar_codes: string[];
	aspect?: string;
	count?: number;
	image_model?: string | null;
	max_parallel_images?: number;
	skip_already_generated?: boolean;
	allow_regenerate?: boolean;
	confirm_credit_burn?: boolean;
}

export interface CreateAvatarImageBulkResponse {
	bulk_run_id: string;
	kind: string;
	status: string;
	total_expected: number;
	skipped: { avatar_code: string; reason: string }[];
	max_parallel_images: number;
}

export async function createAvatarImageBulk(
	input: CreateAvatarImageBulkRequest,
): Promise<CreateAvatarImageBulkResponse> {
	return postAPI<CreateAvatarImageBulkResponse>(`${BASE}/avatar-images`, input);
}

export async function startBulkRun(
	bulkRunId: string,
	opts: { confirm_credit_burn?: boolean; dry_run?: boolean } = {},
): Promise<Record<string, unknown>> {
	return postAPI(`${BASE}/${bulkRunId}/start`, opts);
}

export async function getBulkRun(bulkRunId: string): Promise<BulkRunSummary> {
	return getAPI<BulkRunSummary>(`${BASE}/${bulkRunId}`);
}

export async function pauseBulkRun(bulkRunId: string): Promise<Record<string, unknown>> {
	return postAPI(`${BASE}/${bulkRunId}/pause`, {});
}

export async function cancelBulkRun(bulkRunId: string): Promise<Record<string, unknown>> {
	return postAPI(`${BASE}/${bulkRunId}/cancel`, {});
}

export async function retryFailedBulkRun(
	bulkRunId: string,
): Promise<Record<string, unknown>> {
	return postAPI(`${BASE}/${bulkRunId}/retry-failed`, {});
}

export async function registerBulkAvatarAssets(
	bulkRunId: string,
): Promise<Record<string, unknown>> {
	return postAPI(`${BASE}/${bulkRunId}/register-avatar-assets`, {});
}