import { useEffect, useState } from "react";
import { getAPI } from "./client";

// BOSMAX Command Centre — Tier A data layer.
//
// ALL aggregation lives in the backend (agent/services/reporting_service.py). This
// module is transport + typing only: it calls the read-only /api/reporting endpoints
// (gaps) plus a few existing aggregation endpoints (reuse, not duplicated), and exposes
// independent per-widget hooks so each widget loads and fails on its own.
//
// The cross-filter + pagination SEAM: every request forwards the active filters as query
// params. Tier-A UI only drives lifecycle_status today; cluster / product_type_group are
// carried through so cross-filter can light up later without an API change.

export type LifecycleScope = "ACTIVE" | "ALL";

export interface ReportingFilters {
	lifecycle_status: LifecycleScope;
	cluster?: string | null;
	product_type_group?: string | null;
}

export type ExceptionKind =
	| "missing_cluster"
	| "missing_product_type"
	| "mapping_blocked"
	| "missing_copy"
	| "missing_intelligence"
	| "missing_image"
	| "prompt_not_ready"
	| "scene_strategy_gaps"
	| "failed_generation"
	// 08D PI quality drill-downs (same server pagination/search/sort machinery)
	| "pi_fully_complete"
	| "pi_governed_absence"
	| "pi_legacy_incomplete"
	| "pi_missing_approved";

/** 08D INTEL QUALITY DEBT — the four mutually-exclusive PI classes, fixture-quarantined,
 * each split ACTIVE vs ARCHIVED. Backend is the single counting authority. */
export type PiQualityClass =
	| "FULLY_COMPLETE"
	| "APPROVED_WITH_GOVERNED_ABSENCE"
	| "LEGACY_APPROVED_INCOMPLETE"
	| "MISSING_APPROVED_INTELLIGENCE";

export interface PiQualitySummary {
	total_real_products: number;
	test_fixtures_excluded: number;
	classes: Record<PiQualityClass, { total: number; active: number; archived: number }>;
	drill_down_kinds: Record<PiQualityClass, ExceptionKind>;
}

/** Reason-aware product-level copy classes from the shared strict validity
 * authority (agent/services/copy_set_validity_service). APPROVED_COPY_VALID is
 * the only production-ready state; the rest are the exact blockers. */
export type CopyClassification =
	| "APPROVED_COPY_VALID"
	| "APPROVED_COPY_STALE"
	| "APPROVED_COPY_UNSAFE"
	| "APPROVED_COPY_INCOMPLETE"
	| "APPROVED_COPY_GENERIC"
	| "APPROVED_COPY_MISSING_REVIEW"
	| "APPROVED_COPY_FORMULA_REVIEW"
	| "APPROVED_COPY_SALES_CLARITY_REVIEW"
	| "APPROVED_COPY_INVALID_LINEAGE"
	| "COPY_REVIEW_REQUIRED_ONLY"
	| "DRAFT_COPY_ONLY"
	| "REJECTED_COPY_ONLY"
	| "MISSING_COPY"
	| "BLOCKED_WITH_REASON"
	| "VALIDITY_EVALUATION_FAILED";

export interface CopywritingCoverage {
	total_products: number;
	products_with_copy: number;
	products_missing_copy: number;
	products_with_approved_copy: number;
	/** STRICT production readiness — a valid current approved Copy Set (grounded,
	 * safe, complete, non-generic, semantically reviewed). NOT raw row coverage. */
	products_with_valid_approved_copy: number;
	products_without_valid_approved_copy: number;
	/** Products whose strict evaluation raised — fail-closed, never counted valid. */
	validity_evaluation_failed: number;
	/** Reason-aware breakdown for drill-down (values sum to total_products). */
	copy_classification_counts: Partial<Record<CopyClassification, number>> | null;
	coverage_pct: number;
	valid_approved_coverage_pct: number;
	total_copy_sets: number;
	avg_sets_per_covered_product: number;
	copy_set_by_status: Record<string, number>;
}

export interface ProductIntelligenceCoverage {
	total_products: number;
	with_snapshot: number;
	missing_snapshot: number;
	coverage_pct: number;
}

export interface PromptReadinessHistogram {
	total_products: number;
	READY: number;
	NEEDS_REVIEW: number;
	MISSING_FIELDS: number;
	not_evaluated: number;
}

/** Derived preparation stage. The `missing_intelligence` HEADLINE still means
 * "no approved snapshot" — these stages expose how much of that debt is already
 * prepared, without redefining the predicate. Ordered worst -> best. */
export type IntelligenceStage =
	| "NO_DRAFT"
	| "CLAIM_BLOCKED"
	| "CLAIM_REVIEW_REQUIRED"
	| "DRAFT_INCOMPLETE"
	| "READY_FOR_REVIEW"
	| "APPROVED_SNAPSHOT";

export const INTELLIGENCE_STAGES: IntelligenceStage[] = [
	"NO_DRAFT",
	"CLAIM_BLOCKED",
	"CLAIM_REVIEW_REQUIRED",
	"DRAFT_INCOMPLETE",
	"READY_FOR_REVIEW",
	"APPROVED_SNAPSHOT",
];

export const INTELLIGENCE_STAGE_LABEL: Record<IntelligenceStage, string> = {
	NO_DRAFT: "No draft",
	CLAIM_BLOCKED: "Claim blocked",
	CLAIM_REVIEW_REQUIRED: "Awaiting human review",
	DRAFT_INCOMPLETE: "Draft incomplete",
	READY_FOR_REVIEW: "Ready for review",
	APPROVED_SNAPSHOT: "Approved snapshot",
};

export interface ExceptionItem {
	product_id?: string | null;
	product_display_name?: string | null;
	category?: string | null;
	product_type?: string | null;
	cluster?: string | null;
	product_type_group?: string | null;
	mapping_status?: string | null;
	prompt_readiness_status?: string | null;
	image_asset_status?: string | null;
	asset_status?: string | null;
	lifecycle_status?: string | null;
	// authoritative scene-strategy contract, evaluated server-side per row
	scene_strategy_id?: string | null;
	scene_variants_count?: number | null;
	scene_coverage?: string | null;
	scene_contract_status?: string | null;
	scene_gap_reasons?: string[] | null;
	// derived Product-Intelligence stage, evaluated server-side per row
	intelligence_stage?: IntelligenceStage | null;
	draft_id?: string | null;
	draft_status?: string | null;
	missing_fields?: string[] | null;
	missing_field_count?: number | null;
	claim_gate?: string | null;
	claim_risk_level?: string | null;
	claim_reasons?: string[] | null;
	approved_snapshot?: boolean | null;
	snapshot_id?: string | null;
	// 08D PI-quality drill-down rows (server-computed per page)
	pi_quality?: PiQualityClass | null;
	governed_dispositions?: {
		field_name: string;
		disposition: string;
		reviewed_by?: string | null;
		reviewer_note?: string | null;
		reviewed_at?: string | null;
	}[] | null;
	snapshot_status?: string | null;
	copy_blocked?: boolean | null;
	source?: string | null;
	source_url?: string | null;
	tiktok_product_url?: string | null;
	// failed_generation rows carry request-telemetry fields instead:
	request_id?: string | null;
	mode?: string | null;
	status?: string | null;
	error_code?: string | null;
	error_message?: string | null;
	created_at?: string | null;
	failed_at?: string | null;
}

/** Explicit accounting so the UI never infers a headline. `total` keeps its previous
 * meaning (every row matching the predicate in the requested scope).
 * Archived rows are real catalogue debt that merely must not enter production; test
 * fixtures are harness rows that are not products at all. */
export interface ExceptionApplicability {
	active_missing: number;
	archived_missing: number;
	real_product_missing: number;
	test_fixture_excluded: number;
	documented_na_reason: string;
	/** retained for the previous consumer contract */
	required_missing: number;
	documented_na_archived: number;
}

export interface ExceptionList {
	kind: ExceptionKind;
	total: number;
	applicability?: ExceptionApplicability;
	limit: number;
	offset: number;
	q?: string | null;
	sort_by?: string | null;
	sort_dir?: string;
	/** whole-cohort progress counts; populated for missing_intelligence */
	stage_breakdown?: Partial<Record<IntelligenceStage, number>>;
	intelligence_stage?: IntelligenceStage | null;
	claim_risk_level?: string | null;
	copy_blocked?: boolean | null;
	items: ExceptionItem[];
}

// ── existing endpoints reused (not duplicated) ───────────────────────────────
export interface ClusterAudit {
	product_total: number;
	cluster_counts: Record<string, number>;
	unknown_review_required: number;
}

export interface MappingSummary {
	total_products: number;
	ready: number;
	needs_review: number;
	blocked: number;
	null_mapping_status: number;
}

function qs(
	filters: ReportingFilters,
	extra?: Record<string, string | number | undefined>,
): string {
	const p = new URLSearchParams();
	p.set("lifecycle_status", filters.lifecycle_status);
	if (filters.cluster) p.set("cluster", filters.cluster);
	if (filters.product_type_group)
		p.set("product_type_group", filters.product_type_group);
	for (const [k, v] of Object.entries(extra ?? {})) {
		if (v !== undefined && v !== null) p.set(k, String(v));
	}
	return p.toString();
}

export const fetchCopywritingCoverage = (f: ReportingFilters) =>
	getAPI<CopywritingCoverage>(`/api/reporting/coverage/copywriting?${qs(f)}`);

export const fetchProductIntelligenceCoverage = (f: ReportingFilters) =>
	getAPI<ProductIntelligenceCoverage>(
		`/api/reporting/coverage/product-intelligence?${qs(f)}`,
	);

export interface RegistrationQueueCoverage {
	source: string;
	total_queue_rows: number;
	committed: number;
	pending_drafts: number;
	pending_missing_cluster: number;
	pending_missing_product_type: number;
}

/** Pre-commit registration-queue backlog — distinct from the committed-product
 * KPIs, so "0 missing cluster" (products) reads unambiguously next to the drafts
 * that still await a cluster. No filters: the queue is one global pipeline stage. */
export const fetchRegistrationQueueCoverage = () =>
	getAPI<RegistrationQueueCoverage>(
		"/api/reporting/coverage/registration-queue",
	);

export const fetchPromptReadiness = (f: ReportingFilters) =>
	getAPI<PromptReadinessHistogram>(
		`/api/reporting/coverage/prompt-readiness?${qs(f)}`,
	);

export interface ExceptionQuery {
	limit?: number;
	offset?: number;
	q?: string;
	sort_by?: string;
	sort_dir?: "asc" | "desc";
	intelligence_stage?: IntelligenceStage | "";
	claim_risk_level?: string;
	copy_blocked?: boolean;
}

/** Paging, search and sorting are all resolved SERVER-side over the whole cohort.
 * Never widen `limit` to "fetch everything and paginate locally" — the cohort is
 * hundreds of rows and a truncated fetch silently hides products. */
export const fetchExceptions = (
	kind: ExceptionKind,
	f: ReportingFilters,
	query: ExceptionQuery = {},
) =>
	getAPI<ExceptionList>(
		`/api/reporting/exceptions?${qs(f, {
			kind,
			limit: query.limit ?? 15,
			offset: query.offset ?? 0,
			q: query.q || undefined,
			sort_by: query.sort_by || undefined,
			sort_dir: query.sort_dir || undefined,
			intelligence_stage: query.intelligence_stage || undefined,
			claim_risk_level: query.claim_risk_level || undefined,
			// the query-string helper serialises strings/numbers only
			copy_blocked:
				query.copy_blocked === undefined
					? undefined
					: String(query.copy_blocked),
		})}`,
	);

export const fetchClusterAudit = () =>
	getAPI<ClusterAudit>("/api/creative-intelligence/product-cluster-audit");

export const fetchMappingSummary = () =>
	getAPI<MappingSummary>("/api/products/mapping-summary");

// ── generic independent-widget async hook ────────────────────────────────────
export interface AsyncState<T> {
	data: T | null;
	loading: boolean;
	error: string;
	reload: () => void;
}

function useAsync<T>(
	fetcher: () => Promise<T>,
	deps: readonly unknown[],
): AsyncState<T> {
	const [data, setData] = useState<T | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState("");
	const [tick, setTick] = useState(0);
	useEffect(() => {
		let active = true;
		setLoading(true);
		setError("");
		void fetcher()
			.then((d) => {
				if (active) setData(d);
			})
			.catch((e) => {
				if (active)
					setError(e instanceof Error ? e.message : "Failed to load");
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [...deps, tick]);
	return { data, loading, error, reload: () => setTick((t) => t + 1) };
}

const fkey = (f: ReportingFilters) =>
	[f.lifecycle_status, f.cluster ?? "", f.product_type_group ?? ""] as const;

export const useCopywritingCoverage = (f: ReportingFilters) =>
	useAsync(() => fetchCopywritingCoverage(f), fkey(f));

export const useProductIntelligenceCoverage = (f: ReportingFilters) =>
	useAsync(() => fetchProductIntelligenceCoverage(f), fkey(f));

export const useRegistrationQueueCoverage = () =>
	useAsync(fetchRegistrationQueueCoverage, []);

export const usePromptReadiness = (f: ReportingFilters) =>
	useAsync(() => fetchPromptReadiness(f), fkey(f));

export const useClusterAudit = () => useAsync(fetchClusterAudit, []);

export const useMappingSummary = () => useAsync(fetchMappingSummary, []);

/** KPI cards only need the counts, so they request a single row. */
export const useExceptions = (kind: ExceptionKind, f: ReportingFilters) =>
	useAsync(() => fetchExceptions(kind, f, { limit: 1 }), [kind, ...fkey(f)]);

/** Drill-down table: one server page at a time. */
export const useExceptionPage = (
	kind: ExceptionKind,
	f: ReportingFilters,
	query: ExceptionQuery,
) =>
	useAsync(
		() => fetchExceptions(kind, f, query),
		[
			kind,
			...fkey(f),
			query.limit ?? 15,
			query.offset ?? 0,
			query.q ?? "",
			query.sort_by ?? "",
			query.sort_dir ?? "",
			query.intelligence_stage ?? "",
			query.claim_risk_level ?? "",
			query.copy_blocked === undefined ? "" : String(query.copy_blocked),
		],
	);

// ── failed-generation honesty ────────────────────────────────────────────────
export type ErrorProvenance =
	| "dead_dom_lane"
	| "legacy_pattern_provenance_unverified"
	| "other";

export interface FailedGenerationReport {
	windows: { last_24h: number; last_7d: number; last_30d: number; all_time: number };
	window_labels: Record<string, string>;
	windows_counted_by: string;
	distinct_products_all_time: number;
	time_span: { min: string | null; max: string | null };
	dead_dom_lane_count: number;
	provenance_unverified_count: number;
	other_count: number;
	classification_note: string;
	by_error_code: { error_code: string; count: number; classification: ErrorProvenance }[];
	by_mode: { mode: string; count: number }[];
}

export const fetchFailedGenerations = () =>
	getAPI<FailedGenerationReport>("/api/reporting/failed-generations");

export const useFailedGenerations = () => useAsync(fetchFailedGenerations, []);

/** 08D: INTEL QUALITY DEBT summary. Defaults to ALL so archived debt stays visible. */
export const fetchPiQuality = (lifecycle: LifecycleScope = "ALL") =>
	getAPI<PiQualitySummary>(
		`/api/reporting/pi-quality?lifecycle_status=${encodeURIComponent(lifecycle)}`,
	);

export const usePiQuality = (lifecycle: LifecycleScope = "ALL") =>
	useAsync(() => fetchPiQuality(lifecycle), [lifecycle]);
