import { getAPI, postAPI } from "./client";

export interface CopyFormulaV2 {
	formula_id: string;
	formula_version: string;
	display_name: string;
	definition_status: string;
	compiler_family: string;
	slots: Array<{ slot_id: string; purpose: string; required: boolean }>;
	best_for: string[];
	unsuitable_for: string[];
}

export interface EvidenceFactV2 {
	snapshot_id: string;
	fact_id: string;
	product_id: string;
	fact_kind: string;
	text: string;
	text_digest: string;
	snapshot_version: number;
	snapshot_status: string;
	approved: boolean;
	source_ref?: string | null;
}

export interface CopyAngleOptionV2 {
	angle_id: string;
	definition: string;
	evidence_fact_ids: string[];
	source: string;
}

export interface CopyTruthProofV2 {
	product_id: string;
	product: {
		display_name: string;
		category: string;
		subcategory: string;
		product_type: string;
		product_type_code?: string;
		product_family: string;
		product_family_reason?: string;
		cluster: string;
		canonical_copy_cluster?: string;
		visual_internal_silo?: string;
		visual_internal_silo_source?: string;
		visual_internal_silo_status?: string;
		visual_internal_silo_is_canonical_copy_cluster?: boolean;
	};
	product_truth: {
		approved: boolean;
		snapshot: {
			snapshot_id: string;
			version: number;
			status: string;
			digest: string;
			approved_by?: string | null;
			approved_at?: string | null;
		} | null;
		lineage: Record<string, unknown> | null;
		persona: Record<string, unknown>;
		allowed_claims: string[];
		blocked_claims: string[];
		warnings: string[];
	};
	facts: EvidenceFactV2[];
	blockers: string[];
	blocker_details?: Array<Record<string, unknown>>;
	authority?: {
		authority_version?: string;
		authority_fingerprint?: string | null;
	};
	ready_for_copy: boolean;
}

export interface CopyBlueprintV2Record {
	version: "2";
	blueprint_id: string;
	product_id: string;
	revision: number;
	status: string;
	formula_id: string;
	formula_version: string;
	objective: { objective_id: string; definition: string };
	angle: { angle_id: string; definition: string };
	stages: Array<{
		stage_key: string;
		order: number;
		authored_text: string;
		semantic_role: string;
		formula_stage_key: string;
		bridge: {
			entry: string;
			exit: string;
			continuity_requirements: string[];
		};
		claim_bearing: boolean;
		fact_refs: Array<{ fact_id: string; text_digest: string; fact_kind: string }>;
		validation: { valid: boolean; error_codes: string[] };
	}>;
	evidence_refs: Array<{ fact_id: string; text_digest: string; fact_kind: string }>;
	product_truth_lineage: Record<string, unknown>;
	approval_snapshot?: Record<string, unknown> | null;
	semantic_review?: Record<string, unknown> | null;
	readiness_proof?: Record<string, unknown> | null;
	approved_execution_text: Array<{ stage_key: string; text: string }>;
	target_duration_seconds?: number | null;
	wps_profile?: string | null;
	estimated_word_count: number;
	derived_projection?: Record<string, unknown> | null;
	v2_badge?: string | null;
	current_authority_status?: string;
	current_authority_valid?: boolean;
	current_authority_activation_allowed?: boolean;
	current_authority_reason?: string | null;
	current_authority_mismatches?: Array<Record<string, unknown>>;
	current_authority_fingerprint?: string | null;
	blueprint_authority_fingerprint?: string | null;
}

export interface CopyExecutionBindingV2Record {
	binding_id: string;
	lane: string;
	media_kind: "VIDEO" | "IMAGE";
	copy_policy: "REQUIRED";
	blueprint_id: string;
	revision: number;
	formula_id: string;
	formula_version: string;
	approval_snapshot_id: string;
	product_truth_lineage: Record<string, unknown>;
	evidence_lineage: Record<string, unknown>;
	compiler_binding_version: string;
	feature_flag_state: Record<string, unknown>;
	binding_status: "BOUND";
	bound_at: string;
}

export interface TextAssistLaneStatusV2 {
	lane: "text_assist";
	status: string;
	configured: boolean;
	provider_id?: string | null;
	model_id?: string | null;
	execution_enabled: boolean;
	provider_calls: 0;
}

export interface CopyRegisterActivationStatusV2 {
	active_blueprint_id: string | null;
	active_revision: number | null;
	active_lane_count: number;
	required_lane_count: number;
	activated_at: string | null;
	activation_allowed?: boolean;
	activation_reason?: string | null;
}

export interface CopyReviewQueueRowV2 {
	blueprint_id: string;
	revision: number;
	product_id: string;
	product_name: string;
	formula_id: string;
	claim_safe_copy_status: string | null;
	claim_risk_level: string | null;
	truth_status: string | null;
	truth_current: boolean;
	batch_approvable: boolean;
	draft_blocked_reason: string | null;
	current_authority_reason: string | null;
	current_authority_mismatches: Array<Record<string, unknown>>;
	draft_preview: {
		angle: { angle_id: string; definition: string };
		stages: Array<{
			stage_key: string;
			formula_stage_key: string;
			text: string;
			claim_bearing: boolean;
		}>;
	} | null;
	individual_review_path: string | null;
	error_detail?: string;
}

export interface CopyReviewQueueResponseV2 {
	items: CopyReviewQueueRowV2[];
	total: number;
	filters: { only_claim_safe: boolean; product_id: string | null };
	provider_calls: 0;
	credit_spend: 0;
	activation_mutations: 0;
}

export interface CopyBatchApprovalResultV2 {
	blueprint_id: string;
	status: "APPROVED" | "FAILED";
	production_status?: string | null;
	error_code?: string | null;
	error_detail?: string;
}

export interface CopyActivationCandidateV2 {
	blueprint_id: string;
	revision: number;
	product_id: string;
	product_name: string;
	status: "PRODUCTION_VALID" | string;
	formula_id: string;
	angle: { angle_id: string; definition: string } | null;
	activatable: boolean;
	activation_allowed: boolean;
	current_authority_state: "NONE" | "CURRENT" | "STALE" | string;
	blocked_reason: string | null;
	current_authority_reason: string | null;
	current_authority_mismatches: Array<Record<string, unknown>>;
	active_blueprint_id: string | null;
	active_revision: number | null;
	active_lane_count: number;
	required_lane_count: number;
	draft_preview?: CopyReviewQueueRowV2["draft_preview"];
	error_detail?: string;
}

export interface CopyActivationCandidatesResponseV2 {
	items: CopyActivationCandidateV2[];
	total: number;
	max_batch_size: number;
	provider_calls: 0;
	credit_spend: 0;
	activation_mutations: 0;
}

export interface CopyBatchActivationResultV2 {
	blueprint_id: string;
	activated: boolean;
	idempotent: boolean;
	status: "ACTIVATED" | "ALREADY_ACTIVE" | "FAILED" | string;
	lane_count: number;
	error_code: string | null;
	error_detail?: string;
}

export async function fetchCopyRegisterFormulas(): Promise<{ formulas: CopyFormulaV2[] }> {
	return getAPI<{ formulas: CopyFormulaV2[] }>("/api/copy-register/v2/formulas");
}

export async function fetchCopyRegisterProviderStatus(): Promise<TextAssistLaneStatusV2> {
	return getAPI<TextAssistLaneStatusV2>("/api/copy-register/v2/provider-status");
}

export async function fetchCopyRegisterTruth(productId: string): Promise<CopyTruthProofV2> {
	return getAPI<CopyTruthProofV2>(
		`/api/copy-register/v2/product/${encodeURIComponent(productId)}/truth`,
	);
}

export async function fetchCopyReviewQueue(filters?: {
	only_claim_safe?: boolean;
	product_id?: string;
}): Promise<CopyReviewQueueResponseV2> {
	const params = new URLSearchParams();
	if (filters?.only_claim_safe) params.set("only_claim_safe", "true");
	if (filters?.product_id) params.set("product_id", filters.product_id);
	const query = params.toString();
	return getAPI<CopyReviewQueueResponseV2>(
		`/api/copy-register/v2/bulk/review-queue${query ? `?${query}` : ""}`,
	);
}

export async function batchApproveCopyDrafts(input: {
	blueprint_ids: string[];
	reviewer: string;
	rationale: string;
	readiness_proof: {
		readiness_validated: boolean;
		provenance_validated: boolean;
		safety_validated: boolean;
		bridge_validated: boolean;
		duration_validated: boolean;
	};
	confirmation_phrase: string;
}): Promise<{
	results: CopyBatchApprovalResultV2[];
	approved_count: number;
	failed_count: number;
	automatic_approval: false;
	activation_mutations: 0;
	provider_calls: 0;
	credit_spend: 0;
}> {
	return postAPI(
		"/api/copy-register/v2/bulk/review-queue/approve",
		input,
	);
}

export async function fetchCopyActivationCandidates(): Promise<CopyActivationCandidatesResponseV2> {
	return getAPI<CopyActivationCandidatesResponseV2>(
		"/api/copy-register/v2/bulk/activation-candidates",
	);
}

export async function batchActivateCopyBlueprints(input: {
	blueprint_ids: string[];
	confirmation_phrase: string;
	owner_authorization: boolean;
}): Promise<{
	results: CopyBatchActivationResultV2[];
	activated_count: number;
	idempotent_count: number;
	failed_count: number;
	activation_mutations: number;
	bound_lane_count: number;
	provider_calls: 0;
	credit_spend: 0;
}> {
	return postAPI(
		"/api/copy-register/v2/bulk/activate",
		input,
	);
}

export async function generateCopyRegisterAngles(input: {
	product_id: string;
	formula_id: string;
	objective?: string;
}): Promise<{
	angles: CopyAngleOptionV2[];
	facts: EvidenceFactV2[];
	formula_id: string;
	formula_version: string;
}> {
	return postAPI<{
		angles: CopyAngleOptionV2[];
		facts: EvidenceFactV2[];
		formula_id: string;
		formula_version: string;
	}>("/api/copy-register/v2/angle-options", input);
}

export async function listCopyRegisterBlueprints(productId: string): Promise<{
	product_id: string;
	items: CopyBlueprintV2Record[];
	activation: CopyRegisterActivationStatusV2;
}> {
	return getAPI<{
		product_id: string;
		items: CopyBlueprintV2Record[];
		activation: CopyRegisterActivationStatusV2;
	}>(
		`/api/copy-register/v2/product/${encodeURIComponent(productId)}/blueprints`,
	);
}

export async function generateFormulaCopyBlueprint(input: {
	product_id: string;
	formula_id: string;
	objective_id: string;
	objective_definition: string;
	angle_id: string;
	angle_definition: string;
	evidence_fact_ids: string[];
	target_duration_seconds?: number;
}): Promise<{ blueprint: CopyBlueprintV2Record; production_valid: boolean }> {
	return postAPI<{ blueprint: CopyBlueprintV2Record; production_valid: boolean }>(
		"/api/copy-register/v2/blueprints/generate",
		input,
	);
}

export async function regenerateFormulaStage(
	blueprintId: string,
	stageKey: string,
): Promise<{ blueprint: CopyBlueprintV2Record; new_revision: number }> {
	return postAPI<{ blueprint: CopyBlueprintV2Record; new_revision: number }>(
		`/api/copy-register/v2/blueprints/${encodeURIComponent(blueprintId)}/stages/${encodeURIComponent(stageKey)}/regenerate`,
		{},
	);
}

export async function approveFormulaBlueprint(input: {
	blueprint_id: string;
	approved_by: string;
	semantic_review: {
		decision: "APPROVED";
		reviewer: string;
		rationale: string;
		reviewed_at: string;
	};
	readiness_proof: {
		readiness_validated: boolean;
		provenance_validated: boolean;
		safety_validated: boolean;
		bridge_validated: boolean;
		duration_validated: boolean;
	};
}): Promise<{ blueprint: CopyBlueprintV2Record; production_valid: boolean; badge: string | null }> {
	const { blueprint_id, ...body } = input;
	return postAPI<{ blueprint: CopyBlueprintV2Record; production_valid: boolean; badge: string | null }>(
		`/api/copy-register/v2/blueprints/${encodeURIComponent(blueprint_id)}/approve`,
		body,
	);
}

export async function activateFormulaBlueprint(blueprintId: string): Promise<{
	blueprint_id: string;
	activated: boolean;
	bindings: CopyExecutionBindingV2Record[];
	required_lane_count: number;
}> {
	return postAPI<{
		blueprint_id: string;
		activated: boolean;
		bindings: CopyExecutionBindingV2Record[];
		required_lane_count: number;
	}>(
		`/api/copy-register/v2/blueprints/${encodeURIComponent(blueprintId)}/activate`,
		{},
	);
}

export async function fetchCopyBindingResolution(
	productId: string,
	lane: string,
): Promise<Record<string, unknown>> {
	return getAPI<Record<string, unknown>>(
		`/api/copy-register/v2/bindings/${encodeURIComponent(productId)}/${encodeURIComponent(lane)}/resolution`,
	);
}
