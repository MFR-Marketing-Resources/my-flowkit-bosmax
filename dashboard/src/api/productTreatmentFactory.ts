import { getAPI, postAPI } from "./client";

export type FactoryPlanStatus =
	| "DRAFT"
	| "SCANNED"
	| "PREPARING"
	| "PAUSED"
	| "COMPLETED"
	| "COMPLETED_WITH_BLOCKERS"
	| "FAILED";

export type FactoryTaskStatus =
	| "PENDING"
	| "READY"
	| "RUNNING"
	| "REVIEW_REQUIRED"
	| "SATISFIED"
	| "PAUSED"
	| "FAILED"
	| "SUPERSEDED";

export type FactoryTaskType =
	| "PRODUCT_TRUTH_REVIEW"
	| "EVIDENCE_REVIEW"
	| "COPY_GROUNDING"
	| "COPY_COMPOSITION"
	| "COPY_REVIEW"
	| "CREATIVE_SELECTION"
	| "ASSET_SUPPLY"
	| "TREATMENT_CANDIDATE"
	| "TREATMENT_REVIEW"
	| "P6_CAPACITY";

export type FactoryFormat = "UGC" | "PGC" | "CINEMATIC";
export type FactoryLogicalMode = "T2V" | "F2V" | "I2V" | "HYBRID";
export type FactoryGenerationMode = "SINGLE" | "EXTEND";

export interface FactoryContextDefaults {
	selected_action_index: number;
	format: FactoryFormat;
	logical_mode: FactoryLogicalMode;
	generation_mode: FactoryGenerationMode;
	model_key: string;
	duration_seconds: number;
}

export interface FactoryProductContext extends FactoryContextDefaults {
	product_id: string;
	target_video_count?: number;
}

export interface CreateFactoryPlanRequest {
	products: FactoryProductContext[];
	scan_all_active: boolean;
	target_video_count: number;
	defaults: FactoryContextDefaults;
	created_by: string;
	provider_calls_enabled: false;
	media_generation_enabled: false;
}

export interface PrepareFactoryPlanRequest {
	actor_id: string;
	max_tasks: number;
	materialize_copy_composition: boolean;
	materialize_treatment_candidates: boolean;
	provider_calls_enabled: false;
	media_generation_enabled: false;
}

export interface FactoryPlanControlRequest {
	actor_id: string;
	reason: string;
}

export interface FactoryTaskProjection {
	task_id: string;
	plan_id: string;
	product_id: string;
	task_type: FactoryTaskType;
	status: FactoryTaskStatus;
	task_identity_sha256: string;
	required_authority_sha256: string;
	blocker_code: string | null;
	next_action: string | null;
	template_id: string | null;
	template_sha256: string | null;
	treatment_id: string | null;
	treatment_sha256: string | null;
	snapshot: Record<string, unknown>;
	result: Record<string, unknown>;
	error_code: string | null;
	attempt_count: number;
	created_at: string;
	updated_at: string;
}

export interface FactoryPlanProjection {
	plan_id: string;
	plan_identity_sha256: string;
	cohort_sha256: string;
	context_sha256: string;
	status: FactoryPlanStatus;
	product_count: number;
	request: Record<string, unknown>;
	authority_versions: Record<string, unknown>;
	readiness_summary: Record<string, number>;
	capacity_summary: Record<string, unknown>;
	failure_count: number;
	provider_calls_enabled: false;
	media_generation_enabled: false;
	created_by: string;
	created_at: string;
	updated_at: string;
	tasks: FactoryTaskProjection[];
}

export interface FactoryPlanListResponse {
	plans: FactoryPlanProjection[];
}

const FACTORY_PATH = "/api/product-treatment-factory";

export function listFactoryPlans(
	status?: FactoryPlanStatus,
): Promise<FactoryPlanListResponse> {
	const query = status ? `?status=${encodeURIComponent(status)}` : "";
	return getAPI(`${FACTORY_PATH}/plans${query}`);
}

export function getFactoryPlan(planId: string): Promise<FactoryPlanProjection> {
	return getAPI(`${FACTORY_PATH}/plans/${encodeURIComponent(planId)}`);
}

export function createFactoryPlan(
	body: CreateFactoryPlanRequest,
): Promise<FactoryPlanProjection> {
	return postAPI(`${FACTORY_PATH}/plans`, body);
}

export function prepareFactoryPlan(
	planId: string,
	body: PrepareFactoryPlanRequest,
): Promise<FactoryPlanProjection> {
	return postAPI(
		`${FACTORY_PATH}/plans/${encodeURIComponent(planId)}/prepare`,
		body,
	);
}

export function pauseFactoryPlan(
	planId: string,
	body: FactoryPlanControlRequest,
): Promise<FactoryPlanProjection> {
	return postAPI(
		`${FACTORY_PATH}/plans/${encodeURIComponent(planId)}/pause`,
		body,
	);
}

export function resumeFactoryPlan(
	planId: string,
	body: FactoryPlanControlRequest,
): Promise<FactoryPlanProjection> {
	return postAPI(
		`${FACTORY_PATH}/plans/${encodeURIComponent(planId)}/resume`,
		body,
	);
}
