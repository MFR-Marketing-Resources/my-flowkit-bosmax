import { fetchAPI, getAPI, postAPI } from "./client";

export type V3AssistantMode = "CREATE" | "EXPAND" | "FILL_CAPACITY";

export interface V3ProviderStatus {
	lane: "text_assist";
	status: string;
	configured: boolean;
	provider_id?: string | null;
	model_id?: string | null;
	execution_enabled: boolean;
	provider_calls: number;
	credit_spend: number;
	fake_provider_allowed: boolean;
}

export interface V3AssistantGap {
	semantic_class: "HOOK" | "BODY_CORE" | "CTA";
	current_count: number;
	target_count: number;
	gap_count: number;
	reason: string;
}

export interface V3AssistantPlan {
	plan_id: string;
	run_id: string;
	product_id: string;
	recipe: { entity_id: string; revision: number };
	objective?: Record<string, string>;
	formula?: { formula_id?: string; formula_version?: string };
	angle?: { entity_id: string; revision: number } | null;
	storyline_family?: { entity_id: string; revision: number } | null;
	product_truth?: Record<string, unknown>;
	evidence_fact_ids?: string[];
	evidence_digest?: string;
	language_profile?: string;
	current_capacity?: Record<string, number>;
	mode: V3AssistantMode;
	target_counts: Record<string, number>;
	gaps: V3AssistantGap[];
	target_durations_seconds: number[];
	wps_mode: "SAFE" | "SWEET";
	provider: V3ProviderStatus;
	prompt_version: string;
	prompt_digest: string;
	estimated_provider_calls: number;
	estimated_output_tokens: number;
	estimated_credit_spend: number;
	max_proposals: number;
	max_provider_calls?: number;
	max_output_tokens?: number;
	max_cost?: number;
	cost_status?: string;
	supply_actions?: Record<string, string>;
	diversity_deficits?: string[];
	marginal_plan?: Record<string, number>;
	capacity_before?: { reviewable_capacity?: number; theoretical_capacity?: number; duration_counts?: Record<string, number> };
	evidence_selection?: { outcome?: string; fact_ids?: string[]; explanations?: Record<string, string[]>; score_by_fact?: Record<string, number> };
	explicit_execute_required: true;
	created_at: string;
	created_by: string;
}

export interface V3TruthFact {
	fact_id: string;
	fact_kind: string;
	text: string;
	text_digest: string;
	approved: boolean;
}

export interface V3QualitySignal {
	hard_pass: boolean;
	formula_valid: boolean;
	evidence_valid: boolean;
	bridge_valid: boolean;
	claim_safety_valid: boolean;
	truth_current: boolean;
	wps_valid: boolean;
	issue_codes: readonly string[];
	novelty_signal: "NOVEL" | "NEAR_DUPLICATE" | "EXACT_DUPLICATE" | "UNKNOWN";
	novelty_score: number;
	quality_dimensions?: Record<string, number>;
	quality_score: number;
}

export interface V3StoryboardStage {
	stage_key: string;
	formula_stage_key: string;
	semantic_class: string;
	authored_text: string;
	entry_key?: string;
	exit_key?: string;
	evidence_fact_ids?: string[];
	claim_bearing?: boolean;
	text_digest?: string;
}

// Macro Round 3 (P3): read-only V2 production materialization status. A single
// projection is NOT_MATERIALIZED / MATERIALIZED / STALE / BLOCKED; the item rollup
// additionally reports PARTIALLY_MATERIALIZED when only some projections are live.
export type V3MaterializationStatus = "NOT_MATERIALIZED" | "MATERIALIZED" | "STALE" | "BLOCKED";
export type V3MaterializationRollup = V3MaterializationStatus | "PARTIALLY_MATERIALIZED";

export interface V3ProjectionMaterialization {
	status: V3MaterializationStatus;
	link_id?: string | null;
	v2_blueprint_id?: string;
	v2_blueprint_revision?: number;
	v2_approval_snapshot_id?: string;
	materialization_digest?: string;
	reason?: string;
}

export interface V3Projection {
	projection_id: string;
	revision: number;
	target_duration_seconds: number;
	exact_resolved_dialogue: string;
	derivation_source: string;
	authoring_run_id?: string | null;
	status: string;
	per_block_word_budgets: number[];
	wps_mode?: string;
	wps_authority_digest?: string;
	stage_allocations?: Array<{ master_stage_key: string; transform_mode: string; projected_text?: string; target_block_indices?: number[] }>;
	// Read-only enrichment from the GET landbank endpoint (Round 3 P3).
	exact_projection_digest?: string;
	materialization?: V3ProjectionMaterialization;
}

export interface V3LandbankItem {
	master: {
		master_id: string;
		revision: number;
	product_id: string;
	objective?: { objective_id?: string; definition?: string };
	recipe?: { entity_id: string; revision: number };
	formula: { formula_id: string; formula_version: string };
		angle: { entity_id: string; revision: number };
		storyline_family: { entity_id: string; revision: number };
	stages: readonly V3StoryboardStage[];
		status: string;
		source: string;
		exact_content_digest: string;
		word_count: number;
		resolved_component_refs?: Array<{ entity_id: string; revision: number }>;
	};
	projections: readonly V3Projection[];
	quality: V3QualitySignal;
	current_truth: boolean;
	approval_receipt?: V3ApprovalReceipt | null;
	// Round 3 P3 replaces the Round 2 "NOT_IN_ROUND2" stub with a truthful rollup.
	v2_materialization: V3MaterializationRollup | "NOT_IN_ROUND2";
	p6_status: string;
}

export interface V3ApprovalReceipt {
	receipt_id?: string;
	[key: string]: unknown;
}

export interface V3LandbankResponse {
	source: "V3_COPY_REGISTER";
	product_id: string;
	items: V3LandbankItem[];
	total: number;
	limit: number;
	offset: number;
	has_more: boolean;
	provider_calls: number;
	v2_mixed: false;
	full_storyboard_first: true;
}

export interface V3AssistantExecution {
	run_id: string;
	plan_id: string;
	status: "EXECUTED";
	provider: { mode: "LIVE_TEXT_ASSIST" | "FAKE_TEST"; provider_id?: string | null; model_id?: string | null };
	master: { entity_id: string; revision: number };
	projections: Array<{ entity_id: string; revision: number }>;
	quality: V3QualitySignal;
	provider_calls: number;
	credit_spend: number;
	projection_derivation: string;
}

export interface V3ApprovalChecklist {
	semantic_reviewed: boolean;
	product_truth_reviewed: boolean;
	formula_reviewed: boolean;
	evidence_reviewed: boolean;
	bridge_reviewed: boolean;
	safety_reviewed: boolean;
	duration_reviewed: boolean;
}

function requestId(prefix: string): string {
	const uuid = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
	return `${prefix}:${uuid}`;
}

export type V3RecipePreset = "QUICK TEST" | "FAST54" | "MULTI-ANGLE" | "SCALE" | "CUSTOM";

export async function fetchV3CopyRegisterProviderStatus(): Promise<V3ProviderStatus> {
	return getAPI<V3ProviderStatus>("/api/storyboard-landbank/v3/copy-register/provider-status");
}

export async function setupV3Campaign(input: {
	product_id: string;
	objective_id: string;
	objective_definition?: string;
	formula_id: string;
	preset: V3RecipePreset;
	supported_durations_seconds?: number[];
	target_capacity?: number;
	language_profile?: string;
	wps_mode?: "SAFE" | "SWEET";
	component_count_targets?: Record<string, number>;
}): Promise<{ recipe_id: string; recipe_revision: number; preset: string; reused: boolean; recipe: Record<string, unknown> }> {
	return postAPI("/api/storyboard-landbank/v3/copy-register/setup-campaign", {
		...input,
		actor_id: "dashboard-operator",
		request_id: requestId("v3-setup"),
	});
}

export async function deriveV3AiAssistedProjection(input: {
	master_id: string;
	master_revision?: number;
	duration_seconds: number;
	provider_mode: "LIVE_TEXT_ASSIST" | "FAKE_TEST";
	language_profile?: string;
	wps_mode?: "SAFE" | "SWEET";
}): Promise<{ derivation_source: string; compressed_stages: string[]; projection: Record<string, unknown>; automatic_approval: false }> {
	return postAPI("/api/storyboard-landbank/v3/copy-register/assistant/projection/ai-assisted", {
		...input,
		actor_id: "dashboard-operator",
		request_id: requestId("v3-ai-projection"),
	});
}

export async function reviewV3Entity(action: "validate" | "submit" | "reject" | "archive", entityType: string, entityId: string, revision: number): Promise<Record<string, unknown>> {
	// `revision` is honoured as a query param (validate) and in the body (submit/reject/archive).
	return postAPI(`/api/storyboard-landbank/v3/review/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}/${action}?revision=${revision}`, {
		revision,
		actor_id: "dashboard-operator",
		request_id: requestId(`v3-${action}`),
	});
}

export async function regenerateV3Component(componentId: string, revision: number, providerMode: "LIVE_TEXT_ASSIST" | "FAKE_TEST"): Promise<{ new_revision: number; source_revision: number; component: Record<string, unknown>; automatic_approval: false; run_id: string }> {
	return postAPI(`/api/storyboard-landbank/v3/copy-register/components/${encodeURIComponent(componentId)}/regenerate`, {
		revision,
		provider_mode: providerMode,
		actor_id: "dashboard-operator",
		request_id: requestId("v3-regenerate"),
	});
}

export async function deleteV3Draft(entityType: string, entityId: string, revision: number): Promise<{ deleted: boolean }> {
	// DELETE draft endpoint reads X-Actor-Id / X-Request-Id headers; backend fails closed if unsafe.
	return fetchAPI(`/api/storyboard-landbank/v3/drafts/${encodeURIComponent(entityType)}/${encodeURIComponent(entityId)}/${revision}`, {
		method: "DELETE",
		headers: { "X-Actor-Id": "dashboard-operator", "X-Request-Id": requestId("v3-delete") },
	});
}

export async function planV3Assistant(input: {
	product_id: string;
	recipe_id: string;
	mode: V3AssistantMode;
	additional_count?: number;
	semantic_class?: string;
	target_capacity?: number;
	evidence_fact_ids?: string[];
	max_provider_calls?: number;
	max_output_tokens?: number;
	max_cost?: number;
}): Promise<{ plan: V3AssistantPlan; provider_calls: number; credit_spend: number }> {
	return postAPI("/api/storyboard-landbank/v3/copy-register/assistant/plan", {
		...input,
		actor_id: "dashboard-operator",
		request_id: requestId("v3-plan"),
	});
}

export async function fetchV3AssistantPromptPreview(planId: string): Promise<{ preview: { prompt_digest: string; system_instructions: string; untrusted_truth_json: string; requested_output_contract: Record<string, unknown> }; provider_calls: number; credit_spend: number }> {
	return postAPI(`/api/storyboard-landbank/v3/copy-register/assistant/plans/${encodeURIComponent(planId)}/prompt-preview`, {});
}

export async function executeV3Assistant(planId: string, provider_mode: "LIVE_TEXT_ASSIST" | "FAKE_TEST"): Promise<V3AssistantExecution> {
	return postAPI(`/api/storyboard-landbank/v3/copy-register/assistant/plans/${encodeURIComponent(planId)}/execute`, {
		provider_mode,
		actor_id: "dashboard-operator",
		request_id: requestId("v3-execute"),
	});
}

export async function fetchV3ProductTruth(productId: string): Promise<{ product_id: string; lineage: Record<string, unknown>; facts: V3TruthFact[]; fact_count: number; provider_calls: number; mutations: number }> {
	return getAPI(`/api/storyboard-landbank/v3/products/${encodeURIComponent(productId)}/truth`);
}

export async function fetchV3CopyRegisterLandbank(productId: string, params: { status?: string; duration_seconds?: number; quality?: string; formula_id?: string; angle_id?: string; storyline_family_id?: string; recipe_id?: string; source?: string; blocker?: string; search?: string; limit?: number; offset?: number } = {}): Promise<V3LandbankResponse> {
	const query = new URLSearchParams({ product_id: productId, limit: String(params.limit ?? 50), offset: String(params.offset ?? 0) });
	if (params.status) query.set("status", params.status);
	if (params.duration_seconds) query.set("duration_seconds", String(params.duration_seconds));
	if (params.quality) query.set("quality", params.quality);
	if (params.formula_id) query.set("formula_id", params.formula_id);
	if (params.angle_id) query.set("angle_id", params.angle_id);
	if (params.storyline_family_id) query.set("storyline_family_id", params.storyline_family_id);
	if (params.recipe_id) query.set("recipe_id", params.recipe_id);
	if (params.source) query.set("source", params.source);
	if (params.blocker) query.set("blocker", params.blocker);
	if (params.search) query.set("search", params.search);
	return getAPI<V3LandbankResponse>(`/api/storyboard-landbank/v3/copy-register/landbank?${query.toString()}`);
}

export async function approveV3Master(input: {
	master_id: string;
	projection_ids: Array<{ entity_id?: string; projection_id?: string; revision: number }>;
	approved_by: string;
	rationale: string;
	checklist: V3ApprovalChecklist;
}): Promise<{ receipt: Record<string, unknown>; master: V3LandbankItem["master"]; projections: V3Projection[]; automatic_approval: false }> {
	return postAPI(`/api/storyboard-landbank/v3/copy-register/approval/master/${encodeURIComponent(input.master_id)}`, {
		...input,
		actor_id: input.approved_by,
		request_id: requestId("v3-approval"),
	});
}

export async function approveV3MasterBatch(input: {
	targets: Array<{ master_id: string; projection_ids: Array<{ entity_id?: string; projection_id?: string; revision: number }> }>;
	approved_by: string;
	rationale: string;
	checklist: V3ApprovalChecklist;
}): Promise<{ batch_id: string; batch_digest?: string; approved_count: number; automatic_approval: false }> {
	return postAPI(`/api/storyboard-landbank/v3/copy-register/approval/batch`, {
		...input,
		actor_id: input.approved_by,
		request_id: requestId("v3-batch-approval"),
	});
}

export interface V3MaterializeResult {
	projection_id: string;
	status: "MATERIALIZED";
	blueprint_status: string;
	blueprint_id: string;
	revision: number;
	link_id: string;
	v2_approval_snapshot_id: string;
	materialization_digest: string;
	idempotent_reuse: boolean;
}

export interface V3MaterializeBlocked {
	projection_id: string | null;
	code: string;
	detail: string;
	details?: Record<string, unknown> | null;
}

export interface V3MaterializeBulkResult {
	requested: number;
	materialized_count: number;
	blocked_count: number;
	materialized: V3MaterializeResult[];
	blocked: V3MaterializeBlocked[];
}

// Round 3 P3: explicitly materialize ONE approved projection into a V2
// PRODUCTION_VALID blueprint. actor_id/request_id follow the same mutation-receipt
// pattern as approveV3Master; the human approval receipt is the authority carried
// forward, so a receipt_id is mandatory server-side.
export async function materializeV3Projection(input: { productId?: string; projectionId: string; receiptId: string }): Promise<V3MaterializeResult> {
	return postAPI("/api/storyboard-landbank/v3/copy-register/materialize", {
		projection_id: input.projectionId,
		receipt_id: input.receiptId,
		...(input.productId ? { product_id: input.productId } : {}),
		actor_id: "dashboard-operator",
		request_id: requestId("v3-materialize"),
	});
}

// Round 3 P3: bounded bulk materialization (partial success). Each item is
// independent — one blocked projection never poisons the clean ones. The server
// caps the batch at 25 items per call.
export async function materializeV3ProjectionsBulk(input: { items: Array<{ projectionId: string; receiptId: string }> }): Promise<V3MaterializeBulkResult> {
	return postAPI("/api/storyboard-landbank/v3/copy-register/materialize-bulk", {
		items: input.items.map((entry) => ({ projection_id: entry.projectionId, receipt_id: entry.receiptId })),
		actor_id: "dashboard-operator",
		request_id: requestId("v3-materialize-bulk"),
	});
}
