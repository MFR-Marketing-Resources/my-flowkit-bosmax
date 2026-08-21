import { fetchAPI, getAPI, postAPI } from "./client";

export interface MaintenanceStage {
	stage_key: string;
	order: number;
	formula_stage_key: string;
	semantic_class: string;
	authored_text: string;
	[key: string]: unknown;
}

export interface MaintenanceActions {
	can_edit: boolean;
	edit_mode: "CREATE_NEW_DRAFT" | "EDIT_DRAFT_REVISION";
	can_reject: boolean;
	can_delete: boolean;
	delete_reason: string;
	delete_blockers: string[];
}

export interface MaintenanceQuality {
	hard_pass: boolean;
	formula_valid: boolean;
	evidence_valid: boolean;
	bridge_valid: boolean;
	claim_safety_valid: boolean;
	truth_current: boolean;
	wps_valid: boolean;
	issue_codes: string[];
	novelty_signal: string;
	novelty_score: number;
	quality_dimensions: Record<string, number>;
	quality_score: number;
}

export interface MaintenanceProductCoverage {
	product_id: string;
	product_name: string;
	copy_sets: number;
	angles: number;
	hooks: number;
	body_core: number;
	cta: number;
	approved: number;
	production_ready: number;
	stale: number;
}

export interface MaintenanceProductOption {
	product_id: string;
	product_name: string;
}

export interface MaintenanceRecord {
	product: { id: string; name: string };
	master_id: string;
	revision: number;
	status: string;
	master: Record<string, unknown> & {
		master_id: string;
		revision: number;
		product_id: string;
		stages: MaintenanceStage[];
	};
	formula: { formula_id: string; formula_version: string };
	angle: { entity_id: string; revision: number };
	storyline_family: { entity_id: string; revision: number };
	stages: MaintenanceStage[];
	previews: { HOOK: string; BODY_CORE: string; CTA: string };
	quality: MaintenanceQuality;
	projection_count: number;
	projections: Array<Record<string, unknown>>;
	projection_status: string;
	v2_materialization: string;
	production_ready: boolean;
	stale: boolean;
	stale_reasons: string[];
	approval_receipt: Record<string, unknown> | null;
	created_at: string;
	created_by: string;
	actions: MaintenanceActions;
	provider_calls: number;
	mutations: number;
}

export interface MaintenanceSummary {
	total_products: number;
	products_with_copy: number;
	products_without_copy: number;
	total_copy_masters: number;
	total_master_revisions: number;
	draft: number;
	review_required: number;
	validated: number;
	approved: number;
	production_ready: number;
	stale: number;
}

export interface MaintenanceListResponse {
	source: "V3_COPY_REGISTER_MAINTENANCE";
	items: MaintenanceRecord[];
	total: number;
	limit: number;
	offset: number;
	sort_by: MaintenanceSortBy;
	sort_dir: MaintenanceSortDir;
	has_more: boolean;
	summary: MaintenanceSummary;
	count_basis: Record<string, string>;
	product_coverage: MaintenanceProductCoverage[];
	product_options: MaintenanceProductOption[];
	filter_options: { formulas: string[]; angles: string[] };
	provider_calls: number;
	mutations: number;
}

export type MaintenanceSortBy = "created_at" | "product_name" | "status" | "formula" | "revision";
export type MaintenanceSortDir = "asc" | "desc";

export interface MaintenanceDetail extends MaintenanceRecord {
	exact_revision: { master_id: string; revision: number };
	review_events: Array<Record<string, unknown>>;
	integrity: Record<string, unknown>;
	maintenance: {
		editable_fields: string[];
		immutable_fields: string[];
		approved_edit_behavior: string;
	};
}

export interface MaintenanceSaveResponse {
	master: MaintenanceRecord["master"];
	source_revision: number;
	new_revision: number;
	automatic_approval: false;
	approval_carried_forward: false;
	production_authority_carried_forward: false;
	projection_refresh_required: true;
	provider_calls: number;
	credit_spend: number;
}

function requestId(prefix: string): string {
	const uuid = typeof crypto !== "undefined" && "randomUUID" in crypto
		? crypto.randomUUID()
		: `${Date.now()}-${Math.random()}`;
	return `${prefix}:${uuid}`;
}

function queryString(params: Record<string, string | number | boolean | undefined>): string {
	const query = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value === undefined || value === "") continue;
		query.set(key, String(value));
	}
	const encoded = query.toString();
	return encoded ? `?${encoded}` : "";
}

export async function fetchCopywritingLandbankMaintenance(input: {
	product_id?: string;
	status?: string;
	formula_id?: string;
	angle_id?: string;
	search?: string;
	production_ready?: boolean;
	stale?: boolean;
	sort_by?: MaintenanceSortBy;
	sort_dir?: MaintenanceSortDir;
	limit?: number;
	offset?: number;
} = {}): Promise<MaintenanceListResponse> {
	return getAPI<MaintenanceListResponse>(
		`/api/storyboard-landbank/v3/copy-register/maintenance${queryString(input)}`,
	);
}

export async function fetchCopywritingLandbankMaintenanceDetail(
	masterId: string,
	revision: number,
): Promise<MaintenanceDetail> {
	return getAPI<MaintenanceDetail>(
		`/api/storyboard-landbank/v3/copy-register/maintenance/${encodeURIComponent(masterId)}?revision=${revision}`,
	);
}

export async function saveCopywritingLandbankRevision(input: {
	masterId: string;
	sourceRevision: number;
	stages: Array<{ stage_key: string; authored_text: string }>;
	reason?: string;
}): Promise<MaintenanceSaveResponse> {
	return postAPI<MaintenanceSaveResponse>(
		`/api/storyboard-landbank/v3/copy-register/maintenance/${encodeURIComponent(input.masterId)}/revisions`,
		{
			source_revision: input.sourceRevision,
			stages: input.stages,
			reason: input.reason || "MANUAL_COPY_MAINTENANCE",
			actor_id: "dashboard-operator",
			request_id: requestId("copy-landbank-maintenance-save"),
		},
	);
}

export async function deleteCopywritingLandbankDraft(
	masterId: string,
	revision: number,
): Promise<{ deleted: boolean; provider_calls: number; mutations: number }> {
	return fetchAPI(
		`/api/storyboard-landbank/v3/copy-register/maintenance/${encodeURIComponent(masterId)}/${revision}`,
		{
			method: "DELETE",
			headers: {
				"X-Actor-Id": "dashboard-operator",
				"X-Request-Id": requestId("copy-landbank-maintenance-delete"),
			},
		},
	);
}
