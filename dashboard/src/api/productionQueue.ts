import { getAPI, postAPI } from "./client";

// ─── Batch Prompt generation (Prompt Queue) ──────────────────

export type BatchLogicalMode = "T2V" | "HYBRID" | "F2V" | "I2V";

export type BatchVariationStrategy =
	| "SAME_SCRIPT_DIFF_VISUALS"
	| "DIFF_SCRIPT_DIFF_VISUALS"
	| "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS";

export type PackageProductionStatus =
	| "NONE"
	| "APPROVED"
	| "QUEUED"
	| "RUNNING"
	| "GENERATED"
	| "DOWNLOADED"
	| "FAILED"
	| "CANCELLED";

export interface BatchPromptsRequest {
	product_id: string;
	logical_mode: BatchLogicalMode;
	quantity: number;
	variation_strategy: BatchVariationStrategy;
	interval_seconds: number;
	duration_seconds: number;
	target_language: string;
	avatar_codes: string[];
	character_asset_ids: string[];
	scene_asset_ids: string[];
	style_asset_ids: string[];
	scene_contexts: string[];
	hook_angles: string[];
	finished_frame_asset_id: string | null;
}

export interface BatchPromptsResponse {
	ok: boolean;
	batch_run_id: string;
	logical_mode: string;
	variation_strategy: string;
	total_expected: number;
	status: string;
}

export type BatchRunTerminalStatus = "COMPLETED" | "FAILED" | "CANCELLED";

export interface BatchRunStatus {
	batch_run_id?: string;
	status: "PENDING" | "RUNNING" | BatchRunTerminalStatus;
	total_expected: number;
	total_completed: number;
	total_failed: number;
	error_log_json?: unknown;
	[key: string]: unknown;
}

const GEN_BASE = "/api/workspace/generation-packages";

// ─── Duration authority (WPS workbook) ───────────────────────

export interface DurationAuthorityResponse {
	engine: string;
	allowed_durations: number[];
	source: string;
}

export async function fetchDurationAuthority(): Promise<DurationAuthorityResponse> {
	return getAPI<DurationAuthorityResponse>(`${GEN_BASE}/duration-authority`);
}

export async function startBatchPrompts(
	input: BatchPromptsRequest,
): Promise<BatchPromptsResponse> {
	return postAPI<BatchPromptsResponse>(`${GEN_BASE}/batch-prompts`, input);
}

export async function getBatchRun(batchRunId: string): Promise<BatchRunStatus> {
	return getAPI<BatchRunStatus>(
		`${GEN_BASE}/batch/${encodeURIComponent(batchRunId)}`,
	);
}

export async function cancelBatchRun(
	batchRunId: string,
): Promise<BatchRunStatus> {
	return postAPI<BatchRunStatus>(
		`${GEN_BASE}/batch/${encodeURIComponent(batchRunId)}/cancel`,
		{},
	);
}

// ─── Approval ────────────────────────────────────────────────

export interface ApprovePackagesResult {
	package_id: string;
	ok: boolean;
	error?: string | null;
	production_status?: string | null;
}

export interface ApprovePackagesResponse {
	approved: number;
	results: ApprovePackagesResult[];
}

export async function approvePackages(
	packageIds: string[],
): Promise<ApprovePackagesResponse> {
	return postAPI<ApprovePackagesResponse>(`${GEN_BASE}/approve`, {
		package_ids: packageIds,
	});
}

// ─── Production Queue ────────────────────────────────────────

export interface ProductionRun {
	production_run_id: string;
	status: string;
	dry_run: boolean;
	total_expected: number;
	total_completed?: number;
	total_failed?: number;
	interval_min_seconds?: number;
	interval_max_seconds?: number;
	cooldown_after_n_jobs?: number;
	cooldown_seconds?: number;
	aspect?: string;
	model?: string | null;
	count?: number;
	config_json?: string | null;
	created_at?: string;
	[key: string]: unknown;
}

export interface ProductionRunItem {
	package_id: string;
	product_id: string;
	product_name_snapshot: string | null;
	logical_mode: string;
	production_status: string;
	production_job_id: string | null;
	production_error: string | null;
	artifact_media_ids: string[];
	sent_to_production_at: string | null;
}

export interface ProductionRunDetail extends ProductionRun {
	items: ProductionRunItem[];
}

export interface ProductionRunListResponse {
	runs: ProductionRun[];
	count: number;
}

export interface CreateProductionRunRequest {
	package_ids: string[];
	interval_min_seconds?: number;
	interval_max_seconds?: number;
	cooldown_after_n_jobs?: number;
	cooldown_seconds?: number;
	aspect?: string;
	model?: string | null;
	count?: number;
}

export interface ProductionDryRunReportItem {
	package_id?: string;
	ready?: boolean;
	blocked?: boolean;
	reason?: string;
	error?: string;
	model?: string | null;
	duration_s?: number | null;
	[key: string]: unknown;
}

export interface ProductionDryRunReport {
	checked: number;
	ready: number;
	blocked: number;
	items: ProductionDryRunReportItem[];
	note?: string;
}

export interface ProductionStartResponse {
	run_id: string;
	dry_run: boolean;
	status?: string;
	report?: ProductionDryRunReport;
	live_gate?: string | null;
	package_id?: string | null;
}

/**
 * Round F — the one-serial T2V live lane. Opting in makes the server refuse
 * anything that is not exactly one ready T2V item confirmed by the exact
 * phrase. Omitting it leaves the pre-existing live path unchanged.
 */
export const LIVE_GATE_ONE_SERIAL_T2V = "ONE_SERIAL_T2V";
export const LIVE_CONFIRM_PHRASE = "AUTHORIZE_ONE_T2V_LIVE_RUN";
// First-frame family lane (F2V + HYBRID — both live-proven on the same engine)
// and the ingredients/references lane (I2V). Each lane has its own DISTINCT
// phrase server-side; a T2V confirmation can never authorize an image-mode fire.
export const LIVE_GATE_ONE_SERIAL_F2V = "ONE_SERIAL_F2V";
export const LIVE_F2V_CONFIRM_PHRASE = "AUTHORIZE_ONE_F2V_LIVE_RUN";
export const LIVE_GATE_ONE_SERIAL_I2V = "ONE_SERIAL_I2V";
export const LIVE_I2V_CONFIRM_PHRASE = "AUTHORIZE_ONE_I2V_LIVE_RUN";

// Stage 2A itemized BULK fan-out lane. Its phrase is DISTINCT from every
// single-run phrase, so a single-run confirmation can never be replayed as a
// bulk authorization. The server gate additionally stops at the Stage 3 credit
// boundary — bulk live cannot spend credit until it is runtime-certified.
export const LIVE_GATE_BULK_FANOUT = "BULK_FANOUT";
export const LIVE_BULK_CONFIRM_PHRASE = "AUTHORIZE_BULK_FANOUT_LIVE_RUN";

/** One-serial lanes keep `expect_package_id` REQUIRED; the bulk lane instead
 *  requires the pinned itemized set. A discriminated union so neither lane can
 *  be called with the other's shape. */
export type LiveGateOptions =
	| {
			live_gate:
				| typeof LIVE_GATE_ONE_SERIAL_T2V
				| typeof LIVE_GATE_ONE_SERIAL_F2V
				| typeof LIVE_GATE_ONE_SERIAL_I2V;
			confirm_phrase: string;
			expect_package_id: string;
	  }
	| {
			live_gate: typeof LIVE_GATE_BULK_FANOUT;
			confirm_phrase: string;
			/** Pin the EXACT itemized set that was previewed. */
			expect_package_ids: string[];
			expect_dialogue_fingerprints: string[];
	  };

// ─── Video model standard ────────────────────────────────────

export interface VideoModelInfo {
	key: string;
	ui_label: string;
	default_duration_s?: number;
	allowed_durations_s?: number[];
	cost?: unknown;
	[key: string]: unknown;
}

export interface VideoModelsResponse {
	default: string;
	models: VideoModelInfo[];
	[key: string]: unknown;
}

export async function fetchVideoModels(): Promise<VideoModelsResponse> {
	return getAPI<VideoModelsResponse>("/api/flow/video-models");
}

const PROD_BASE = "/api/workspace/production-queue";

export async function createProductionRun(
	input: CreateProductionRunRequest,
): Promise<ProductionRun> {
	return postAPI<ProductionRun>(PROD_BASE, input);
}

export async function listProductionRuns(): Promise<ProductionRunListResponse> {
	return getAPI<ProductionRunListResponse>(PROD_BASE);
}

export async function getProductionRun(
	runId: string,
): Promise<ProductionRunDetail> {
	return getAPI<ProductionRunDetail>(
		`${PROD_BASE}/${encodeURIComponent(runId)}`,
	);
}

export async function startProductionRun(
	runId: string,
	confirmLiveCreditBurn: boolean,
	liveGate?: LiveGateOptions,
): Promise<ProductionStartResponse> {
	return postAPI<ProductionStartResponse>(
		`${PROD_BASE}/${encodeURIComponent(runId)}/start`,
		{ confirm_live_credit_burn: confirmLiveCreditBurn, ...(liveGate ?? {}) },
	);
}

export async function pauseProductionRun(
	runId: string,
): Promise<ProductionRun> {
	return postAPI<ProductionRun>(
		`${PROD_BASE}/${encodeURIComponent(runId)}/pause`,
		{},
	);
}

export async function cancelProductionRun(
	runId: string,
): Promise<ProductionRun> {
	return postAPI<ProductionRun>(
		`${PROD_BASE}/${encodeURIComponent(runId)}/cancel`,
		{},
	);
}

export async function retryProductionRun(
	runId: string,
): Promise<ProductionRun> {
	return postAPI<ProductionRun>(
		`${PROD_BASE}/${encodeURIComponent(runId)}/retry`,
		{},
	);
}
