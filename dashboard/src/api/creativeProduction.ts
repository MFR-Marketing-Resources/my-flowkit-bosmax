import { getAPI, patchAPI, postAPI } from "./client";

export type PlanStatus =
	| "DRAFT"
	| "PREFLIGHT_BLOCKED"
	| "PREFLIGHT_READY"
	| "PENDING_APPROVAL"
	| "APPROVED"
	| "SCHEDULED"
	| "RUNNING"
	| "PAUSED"
	| "COMPLETED"
	| "COMPLETED_WITH_FAILURES"
	| "CANCELLED"
	| "FAILED";

export type ItemStatus =
	| "PLANNED"
	| "COMPILED"
	| "DEDUPE_BLOCKED"
	| "PENDING_APPROVAL"
	| "APPROVED"
	| "WAVE_ASSIGNED"
	| "QUEUED"
	| "DISPATCHING"
	| "SUBMITTED"
	| "GENERATING"
	| "GENERATED"
	| "RETRIEVING"
	| "RETRIEVED"
	| "QA_PENDING"
	| "QA_APPROVED"
	| "QA_REJECTED"
	| "REPLACEMENT_PLANNED"
	| "FAILED"
	| "CANCELLED"
	| "SUPERSEDED";

export interface CohortProduct {
	product_id: string;
	product_name: string;
	product_type_group: string;
	scene_strategy_id: string;
	image_url: string;
	image_readiness_status: string;
	readiness_status: string;
}

export interface CohortAuthority {
	cohort_count: number;
	cohort_sha256: string;
	product_ids: string[];
	products: CohortProduct[];
	matches_frozen_authority: boolean;
	p6_not_started: boolean;
}

export interface CreativePoolSelection {
	treatment_ids: string[];
	copy_set_ids: string[];
	poster_copy_set_ids: string[];
	avatar_codes: string[];
	product_reference_asset_ids: string[];
	finished_frame_asset_ids: string[];
	character_asset_ids: string[];
	scene_asset_ids: string[];
	style_asset_ids: string[];
	layout_ids: string[];
}

export interface CreateProductionPlanRequest {
	request_id: string;
	operator_id: string;
	name: string;
	campaign_key: string;
	product_ids: string[];
	product_video_allocations: ProductVideoAllocation[];
	target_video_count: number;
	target_image_count: number;
	target_poster_count: number;
	operating_window_hours: number;
	allocation_strategy: "ROUND_ROBIN" | "PRODUCT_WEIGHTED";
	variation_strategy:
		| "SAME_SCRIPT_DIFF_VISUALS"
		| "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS"
		| "DIFF_SCRIPT_DIFF_VISUALS"
		| "OPERATOR_MATRIX";
	logical_mode: "T2V" | "HYBRID" | "F2V" | "I2V";
	model_keys: string[];
	duration_seconds: number[];
	creative_format: CreativeTreatmentFormatPreference;
	pools: CreativePoolSelection;
	controlled_reuse_reason: string | null;
	controlled_reuse_max_per_dna: number;
	execution_policy: Record<string, unknown>;
}

export interface ProductVideoAllocation {
	product_id: string;
	video_count: number;
}

export type CreativeTreatmentFormatPreference =
	| "AUTO"
	| "UGC"
	| "PGC"
	| "CINEMATIC";

export interface TreatmentAvailabilityRequest {
	product_video_allocations: ProductVideoAllocation[];
	logical_mode: "T2V" | "HYBRID" | "F2V" | "I2V";
	model_key: string;
	duration_seconds: number;
	creative_format: CreativeTreatmentFormatPreference;
	treatment_ids: string[];
}

export interface TreatmentAvailability {
	ready: boolean;
	selection_mode: "AUTO" | "EXPLICIT";
	availability_sha256: string;
	requested: {
		logical_mode: string;
		model_key: string;
		duration_seconds: number;
		creative_format: CreativeTreatmentFormatPreference;
		video_count: number;
	};
	selected_treatment_ids: string[];
	selected_treatments: Array<Record<string, unknown>>;
	product_results: Array<{
		product_id: string;
		requested: number;
		eligible_capacity: number;
		selected_count: number;
		selected_treatment_ids: string[];
		ready: boolean;
		shortage: number;
	}>;
	supported_formats: Array<"UGC" | "PGC" | "CINEMATIC">;
	supported_configurations: Array<Record<string, unknown>>;
	blockers: Array<Record<string, unknown>>;
}

export interface PlanProductAllocationSnapshot extends ProductVideoAllocation {
	product_name: string;
}

export interface PlanVideoConfigurationSnapshot {
	model_key: string;
	model_label: string;
	requested_total_duration_seconds: number;
	engine_block_duration_seconds: number;
	generation_mode: "SINGLE" | "EXTEND";
	segment_count: number;
	execution_route: string;
}

export interface ProductionPlanCanonicalSnapshot {
	schema_version: 1;
	completeness: "COMPLETE" | "LEGACY_INCOMPLETE";
	missing_fields: string[];
	source: "CREATE_REQUEST" | "LEGACY_RECONCILIATION" | "LEGACY_PREVIEW";
	evidence: Record<string, unknown>;
	plan_id: string;
	plan_name: string;
	purpose: string | null;
	status: PlanStatus;
	operator_id: string;
	request_id: string;
	product_allocations: PlanProductAllocationSnapshot[];
	target_video_count: number;
	target_image_count: number;
	target_poster_count: number;
	logical_mode: "T2V" | "HYBRID" | "F2V" | "I2V";
	video_configurations: PlanVideoConfigurationSnapshot[];
	aspect_ratio: "9:16" | "16:9";
	operating_window_hours: number;
	allocation_strategy: string;
	variation_strategy: string;
	approved_pool_snapshot: Record<string, unknown> | null;
	pool_snapshot: Record<string, unknown>;
	cohort_snapshot: {
		cohort_sha256: string;
		cohort_count: number;
		product_ids: string[];
	};
	matrix_count: number;
	attempts_count: number;
	qa_count: number;
	created_at: string;
	updated_at: string;
}

export interface ProductionPlanSnapshotSummary {
	completeness: "COMPLETE" | "LEGACY_INCOMPLETE";
	missing_fields: string[];
	product_allocations: PlanProductAllocationSnapshot[];
	video_configurations: PlanVideoConfigurationSnapshot[];
	aspect_ratio: "9:16" | "16:9" | null;
}

export interface ProductionPlan {
	plan_id: string;
	request_id: string;
	created_by: string;
	name: string;
	campaign_key: string;
	product_scope: string[];
	plan_snapshot: ProductionPlanCanonicalSnapshot | Record<string, never>;
	snapshot_summary?: ProductionPlanSnapshotSummary;
	p58_cohort_sha256: string;
	p58_cohort_count: number;
	target_video_count: number;
	target_image_count: number;
	target_poster_count: number;
	operating_window_hours: number;
	allocation_strategy: string;
	variation_strategy: string;
	logical_mode: "T2V" | "HYBRID" | "F2V" | "I2V" | string;
	model_key?: string;
	model_keys: string[];
	duration_seconds: number[];
	aspect_ratio?: string;
	pool_snapshot: Record<string, unknown>;
	execution_policy: Record<string, unknown>;
	capacity_snapshot: Record<string, unknown>;
	compile_snapshot: Record<string, unknown>;
	blockers: Array<Record<string, unknown>>;
	status: PlanStatus;
	control_action: string;
	control_version: number;
	approved_by: string | null;
	approved_at: string | null;
	created_at: string;
	updated_at: string;
}

export interface ProductionItem {
	item_id: string;
	plan_id: string;
	item_ordinal: number;
	product_id: string;
	media_type: "VIDEO" | "IMAGE" | "POSTER";
	logical_mode: string;
	creative_dimensions: Record<string, string>;
	creative_dna_sha256: string;
	controlled_reuse_reason: string | null;
	prompt_fingerprint: string | null;
	workspace_generation_package_id: string | null;
	prompt_package: Record<string, unknown>;
	status: ItemStatus;
	output_media_id: string | null;
	replacement_for_item_id: string | null;
	replaced_by_item_id: string | null;
}

export interface GenerationAttempt {
	attempt_id: string;
	item_id: string;
	attempt_number: number;
	idempotency_key: string;
	lane_id: string | null;
	attempt_state: string;
	payload_sha256: string;
	credit_spend_intended: boolean;
	provider_job_id: string | null;
	artifact_media_id: string | null;
	failure_stage: string | null;
	failure_code: string | null;
	recovery_class: string | null;
}

export interface ExecutionLane {
	lane_id: string;
	provider: string;
	engine: string;
	eligible_media_types: string[];
	verified_max_inflight: number;
	min_interval_seconds: number;
	cooldown_seconds: number;
	next_available_at: string | null;
	completed_job_count: number;
	health_status: string;
	enabled: boolean;
	runtime_proof_status: string;
	evidence_reference: string;
	active_lease_count: number;
}

export interface PlanDetail {
	plan: ProductionPlan;
	snapshot: ProductionPlanCanonicalSnapshot;
	waves: Array<Record<string, unknown>>;
	batches: Array<Record<string, unknown>>;
	items: ProductionItem[];
	attempts: GenerationAttempt[];
	qa: Array<Record<string, unknown>>;
	audit_events: Array<Record<string, unknown>>;
	progress: {
		total: number;
		terminal: number;
		percent: number;
		by_status: Record<string, number>;
	};
}

export interface CapacityPreflight {
	plan_id: string;
	status: "PREFLIGHT_READY" | "PREFLIGHT_BLOCKED";
	requested: Record<string, number>;
	safe_capacity: Record<string, number>;
	pool_counts: Record<string, number>;
	quota_pressure: Record<string, number>;
	historical_exclusions: number;
	blockers: Array<Record<string, unknown>>;
	remediation: Array<Record<string, unknown>>;
	assumptions: Record<string, unknown>;
	snapshot_sha256: string;
}

export const P6_LIVE_CONFIRMATION = "AUTHORIZE_P6_LIVE_CREDIT_SPEND";

export interface GovernedPoolAuthority {
	product_ids: string[];
	logical_mode: string;
	products: Array<Record<string, unknown>>;
	copy_sets: Array<Record<string, unknown>>;
	poster_copy_sets: Array<Record<string, unknown>>;
	avatar_profiles: Array<Record<string, unknown>>;
	product_reference_assets: Array<Record<string, unknown>>;
	finished_frame_assets: Array<Record<string, unknown>>;
	character_assets: Array<Record<string, unknown>>;
	scene_assets: Array<Record<string, unknown>>;
	style_assets: Array<Record<string, unknown>>;
	poster_recipes: Array<Record<string, unknown>>;
	blockers: Array<Record<string, unknown>>;
	copy_reuse_cap: number;
	near_duplicate_threshold: number;
	credit_spend: 0;
}

function planAction(operatorId: string) {
	return {
		request_id: crypto.randomUUID(),
		operator_id: operatorId,
	};
}

export function fetchCohortAuthority(): Promise<CohortAuthority> {
	return getAPI("/api/creative-production/cohort-authority");
}

export function listProductionPlans(): Promise<{ plans: ProductionPlan[] }> {
	return getAPI("/api/creative-production/plans");
}

export function fetchProductionPlan(planId: string): Promise<PlanDetail> {
	return getAPI(`/api/creative-production/plans/${planId}`);
}

export function createProductionPlan(
	body: CreateProductionPlanRequest,
): Promise<ProductionPlan> {
	return postAPI("/api/creative-production/plans", body);
}

export function fetchGovernedPoolAuthority(
	productIds: string[],
	logicalMode: string,
): Promise<GovernedPoolAuthority> {
	return postAPI("/api/creative-production/pool-authority", {
		product_ids: productIds,
		logical_mode: logicalMode,
	});
}

export function fetchTreatmentAvailability(
	body: TreatmentAvailabilityRequest,
): Promise<TreatmentAvailability> {
	return postAPI("/api/creative-production/treatment-availability", body);
}

export function preflightProductionPlan(
	planId: string,
	operatorId: string,
): Promise<CapacityPreflight> {
	return postAPI(
		`/api/creative-production/plans/${planId}/preflight`,
		planAction(operatorId),
	);
}

export function materializeContentMatrix(
	planId: string,
	operatorId: string,
): Promise<Record<string, unknown>> {
	return postAPI(
		`/api/creative-production/plans/${planId}/content-matrix`,
		planAction(operatorId),
	);
}

export function compileProductionPlan(
	planId: string,
	operatorId: string,
): Promise<Record<string, unknown>> {
	return postAPI(
		`/api/creative-production/plans/${planId}/compile`,
		planAction(operatorId),
	);
}

export function approveProductionPlan(
	planId: string,
	operatorId: string,
): Promise<ProductionPlan> {
	return postAPI(`/api/creative-production/plans/${planId}/approve`, {
		...planAction(operatorId),
	});
}

export function assignProductionWaves(
	planId: string,
	operatorId: string,
	waveCount: number,
	batchSize: number,
): Promise<Record<string, unknown>> {
	return postAPI(`/api/creative-production/plans/${planId}/waves`, {
		...planAction(operatorId),
		wave_count: waveCount,
		batch_size: batchSize,
	});
}

export function dryRunProductionPlan(
	planId: string,
	operatorId: string,
	aspect: "9:16" | "16:9",
): Promise<Record<string, unknown>> {
	return postAPI(`/api/creative-production/plans/${planId}/dry-run`, {
		...planAction(operatorId),
		aspect,
	});
}

export function startProductionPlan(
	planId: string,
	operatorId: string,
	confirmation: string,
	aspect: "9:16" | "16:9",
): Promise<Record<string, unknown>> {
	return postAPI(`/api/creative-production/plans/${planId}/start`, {
		...planAction(operatorId),
		aspect,
		live: true,
		credit_confirmation: confirmation,
	});
}

export function controlProductionPlan(
	planId: string,
	action: "pause" | "resume" | "cancel",
	operatorId: string,
): Promise<ProductionPlan> {
	return postAPI(`/api/creative-production/plans/${planId}/${action}`, {
		...planAction(operatorId),
	});
}

export function listExecutionLanes(): Promise<{
	lanes: ExecutionLane[];
	live_execution_certified: boolean;
}> {
	return getAPI("/api/creative-production/lanes");
}

export function patchExecutionLane(
	laneId: string,
	body: {
		health_status: string;
		enabled: boolean;
		runtime_proof_status: string;
		evidence_reference: string;
	},
): Promise<ExecutionLane> {
	return patchAPI(`/api/creative-production/lanes/${laneId}`, body);
}

export function reconcileAttempt(
	attemptId: string,
): Promise<Record<string, unknown>> {
	return postAPI(
		`/api/creative-production/attempts/${attemptId}/reconcile`,
		{},
	);
}

export function retryAttempt(
	attemptId: string,
	operatorId: string,
): Promise<Record<string, unknown>> {
	return postAPI(`/api/creative-production/attempts/${attemptId}/retry`, {
		...planAction(operatorId),
	});
}

export function decideItemQa(
	itemId: string,
	operatorId: string,
	decision: "QA_APPROVED" | "QA_REJECTED",
	requestReplacement: boolean,
	reviewerNote: string,
): Promise<Record<string, unknown>> {
	return postAPI(`/api/creative-production/items/${itemId}/qa`, {
		...planAction(operatorId),
		decision,
		reviewer_note: reviewerNote,
		request_replacement: requestReplacement,
	});
}
