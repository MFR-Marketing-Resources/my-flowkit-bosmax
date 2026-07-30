import { getAPI, postAPI } from "./client";

export type SupplyRunState =
	| "DRAFT"
	| "READY"
	| "RUNNING"
	| "PAUSED"
	| "COMPLETED"
	| "BLOCKED"
	| "CANCELLED";

export interface SupplyRunSummary {
	run_id: string;
	mission_id: string;
	roster_sha256: string;
	cohort_sha256: string;
	state: SupplyRunState;
	provider_budget_max: number;
	provider_calls_used: number;
	reviewer_id: string;
	pause_reason: string | null;
	last_error: string | null;
	created_at: string;
	updated_at: string;
}

export interface SupplyRun {
	run_id: string;
	mission_id: string;
	roster_sha256: string;
	cohort_sha256: string;
	roster: Array<{
		product_id: string;
		product_name: string;
		rank: number;
		role: "HERO" | "TOP10";
		selection_basis: string;
	}>;
	angle_plan: Array<{
		product_id: string;
		angle_key: string;
		angle_label: string;
	}>;
	target_policy: Record<string, unknown>;
	state: SupplyRunState;
	provider_budget_max: number;
	provider_calls_used: number;
	reviewer_id: string;
	pause_reason: string | null;
	last_error: string | null;
	created_at: string;
	updated_at: string;
}

export interface SupplyTask {
	task_id: string;
	run_id: string;
	product_id: string;
	angle_key: string;
	angle_label: string;
	component_type: "HOOK" | "SUBHOOK" | "USP_SET" | "CTA";
	task_kind: "AUTHOR_DEFICIT" | "LEGACY_AUDIT";
	deficit_round: number;
	target_approved_count: number;
	requested_count: number;
	attempt_count: number;
	provider_call_count: number;
	state: string;
	transient_failure_proven: number;
	last_error: string | null;
	result: {
		component_ids?: string[];
		warnings?: string[];
	};
}

export interface ReviewCandidate {
	component_id: string;
	product_id: string;
	angle_key: string;
	angle_label: string;
	component_type: string;
	content: string;
	status: string;
	content_sha256: string;
	provider_provenance: Record<string, unknown>;
}

export interface ReviewTask extends SupplyTask {
	candidates: ReviewCandidate[];
}

export interface SupplyProductStatus {
	product_id: string;
	product_name: string;
	rank: number;
	role: "HERO" | "TOP10";
	product_truth_readiness: string;
	approved_snapshot_status: string;
	claim_gate: string;
	angle_count: number;
	component_total: number;
	review_required_count: number;
	approved_count: number;
	rejected_count: number;
	deficits: Array<{
		angle_key: string;
		component_type: string;
		missing: number;
	}>;
	composable_capacity: number;
	capacity_target: number;
	approved_copy_set_count: number;
	avatar_readiness: string;
	scene_readiness: string;
	video_asset_readiness: {
		product_reference: boolean;
		composite_frame_reference: boolean;
	};
	poster_image_readiness: string;
	p6_preflight_status: string;
	blockers: string[];
	next_best_supply_action: string;
}

export interface SupplyRunStatus {
	run: SupplyRun;
	products: SupplyProductStatus[];
	tasks: SupplyTask[];
	task_counts: Record<string, number>;
	review_events: Array<{
		event_id: string;
		component_id: string;
		product_id: string;
		decision: "APPROVED" | "REJECTED";
		reasons: string[];
		reviewer_id: string;
		reviewed_at: string;
	}>;
	review_queue: ReviewTask[];
	provider_budget: {
		maximum: number;
		used: number;
		remaining: number;
		pending_or_retry_calls: number;
		within_ceiling: boolean;
	};
	exact_blockers: string[];
}

export function listSupplyRuns(): Promise<{ runs: SupplyRunSummary[] }> {
	return getAPI("/api/creative-supply/runs");
}

export function fetchSupplyRun(runId: string): Promise<SupplyRunStatus> {
	return getAPI(`/api/creative-supply/runs/${runId}`);
}

export function executeSupplyStep(runId: string): Promise<SupplyRunStatus> {
	return postAPI(`/api/creative-supply/runs/${runId}/step`, {});
}

export function controlSupplyRun(
	runId: string,
	action: "PAUSE" | "RESUME",
	reason = "",
): Promise<SupplyRunStatus> {
	return postAPI(`/api/creative-supply/runs/${runId}/control`, {
		action,
		reason,
	});
}

export function retrySupplyTask(
	runId: string,
	taskId: string,
): Promise<SupplyRunStatus> {
	return postAPI(
		`/api/creative-supply/runs/${runId}/tasks/${taskId}/retry`,
		{},
	);
}

export function requeueUnsubmittedSupplyTask(
	runId: string,
	taskId: string,
): Promise<SupplyRunStatus> {
	return postAPI(
		`/api/creative-supply/runs/${runId}/tasks/${taskId}/requeue-unsubmitted`,
		{},
	);
}

export function reconcileInterruptedSupplyTask(
	runId: string,
	taskId: string,
	evidenceReason: string,
): Promise<SupplyRunStatus> {
	return postAPI(
		`/api/creative-supply/runs/${runId}/tasks/${taskId}/reconcile-interrupted`,
		{ evidence_reason: evidenceReason },
	);
}

export function reviewSupplyComponent(
	runId: string,
	body: {
		task_id: string;
		component_id: string;
		decision: "APPROVED" | "REJECTED";
		reviewed_content_sha256: string;
		reasons: string[];
		reviewer_id: string;
	},
): Promise<{ run: SupplyRunStatus }> {
	return postAPI(`/api/creative-supply/runs/${runId}/review`, body);
}

export function composeSupplySample(
	runId: string,
	productId: string,
	count: number,
	dryRun = true,
): Promise<Record<string, unknown>> {
	return postAPI(`/api/creative-supply/runs/${runId}/compose`, {
		product_id: productId,
		count,
		dry_run: dryRun,
	});
}
