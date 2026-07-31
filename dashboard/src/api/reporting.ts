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
	| "failed_generation";

export interface CopywritingCoverage {
	total_products: number;
	products_with_copy: number;
	products_missing_copy: number;
	products_with_approved_copy: number;
	coverage_pct: number;
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
	// failed_generation rows carry request-telemetry fields instead:
	request_id?: string | null;
	mode?: string | null;
	status?: string | null;
	error_code?: string | null;
	error_message?: string | null;
	created_at?: string | null;
	failed_at?: string | null;
}

/** Additive split of `total`, never a filter — `total` keeps its previous meaning.
 * Archived products are ARCHIVED_NOT_IN_SCOPE under the merged P5.8 catalog authority,
 * so under "All (incl. archived)" they are documented N/A, not actionable coverage. */
export interface ExceptionApplicability {
	required_missing: number;
	documented_na_archived: number;
	documented_na_reason: string;
}

export interface ExceptionList {
	kind: ExceptionKind;
	total: number;
	applicability?: ExceptionApplicability;
	limit: number;
	offset: number;
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

export const fetchPromptReadiness = (f: ReportingFilters) =>
	getAPI<PromptReadinessHistogram>(
		`/api/reporting/coverage/prompt-readiness?${qs(f)}`,
	);

export const fetchExceptions = (
	kind: ExceptionKind,
	f: ReportingFilters,
	limit = 100,
	offset = 0,
) =>
	getAPI<ExceptionList>(
		`/api/reporting/exceptions?${qs(f, { kind, limit, offset })}`,
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

export const usePromptReadiness = (f: ReportingFilters) =>
	useAsync(() => fetchPromptReadiness(f), fkey(f));

export const useClusterAudit = () => useAsync(fetchClusterAudit, []);

export const useMappingSummary = () => useAsync(fetchMappingSummary, []);

export const useExceptions = (kind: ExceptionKind, f: ReportingFilters) =>
	useAsync(() => fetchExceptions(kind, f), [kind, ...fkey(f)]);

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
