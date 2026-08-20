import { Section } from "../components/ui";
import { KpiCard } from "../components/reporting/KpiCard";
import { CoverageBar } from "../components/reporting/CoverageBar";
import { BarPanel, type BarDatum } from "../components/reporting/charts/BarPanel";
import {
	DonutPanel,
	type DonutSlice,
} from "../components/reporting/charts/DonutPanel";
import {
	ReportingFilterProvider,
	useReportingFilters,
	asFilters,
} from "../components/reporting/ReportingFilterContext";
import {
	useClusterAudit,
	useCopywritingCoverage,
	useRegistrationQueueCoverage,
	useMappingSummary,
	useProductIntelligenceCoverage,
	usePromptReadiness,
} from "../api/reporting";

// Management Intelligence — the executive coverage picture. Every widget owns its data
// hook (independent load/fail). All aggregation is server-side; these are pure views.

function LifecycleToggle() {
	const f = useReportingFilters();
	return (
		<div className="inline-flex rounded-lg border border-slate-800 bg-slate-900 p-0.5 text-xs">
			{(["ACTIVE", "ALL"] as const).map((s) => (
				<button
					key={s}
					type="button"
					onClick={() => f.setLifecycle(s)}
					className={`rounded-md px-3 py-1 transition ${
						f.lifecycle_status === s
							? "bg-sky-600 text-white"
							: "text-slate-400 hover:text-slate-200"
					}`}
				>
					{s === "ACTIVE" ? "Active only" : "All (incl. archived)"}
				</button>
			))}
		</div>
	);
}

function ExecutiveInner() {
	const f = useReportingFilters();
	const filters = asFilters(f);
	const copy = useCopywritingCoverage(filters);
	const intel = useProductIntelligenceCoverage(filters);
	const prompt = usePromptReadiness(filters);
	const clusters = useClusterAudit();
	const mapping = useMappingSummary();
	const queue = useRegistrationQueueCoverage();

	const clusterData: BarDatum[] = clusters.data
		? Object.entries(clusters.data.cluster_counts)
				.map(([label, value]) => ({ label, value }))
				.sort((a, b) => b.value - a.value)
				.slice(0, 15)
		: [];

	// COPY-CORRECTIVE-B05 + Lapis-2 GAP-1: lead with STRICT production-readiness, then
	// split the remainder into STALE (activated but lineage-drifted — revalidation
	// required) vs no copy at all, so the stale class the old binary coverage hid is
	// visible. Falls back to the two-slice view if the tri-state is unavailable.
	const copyClasses = copy.data?.copy_classification_counts ?? null;
	const copyDonut: DonutSlice[] = copy.data
		? copyClasses
			? [
					{
						label: "Production-ready",
						value: copyClasses.APPROVED_COPY_VALID ?? 0,
						color: "#10b981",
					},
					{
						label: "Stale — revalidate",
						value: copyClasses.APPROVED_COPY_STALE ?? 0,
						color: "#f59e0b",
					},
					{
						label: "No copy",
						value: copyClasses.MISSING_COPY ?? 0,
						color: "#334155",
					},
					...(copyClasses.VALIDITY_EVALUATION_FAILED
						? [
								{
									label: "Eval failed",
									value: copyClasses.VALIDITY_EVALUATION_FAILED,
									color: "#ef4444",
								},
							]
						: []),
				]
			: [
					{
						label: "Production-ready",
						value: copy.data.products_with_valid_approved_copy,
						color: "#10b981",
					},
					{
						label: "Needs work",
						value: copy.data.products_without_valid_approved_copy,
						color: "#334155",
					},
				]
		: [];

	const clusterCount = clusters.data
		? Object.keys(clusters.data.cluster_counts).length
		: 0;

	return (
		<div className="space-y-6">
			<div className="flex flex-wrap items-center justify-between gap-3">
				<div>
					<h2 className="text-lg font-semibold text-slate-100">
						Management Intelligence
					</h2>
					<p className="text-xs text-slate-500">
						Catalogue coverage &amp; quality at a glance. Toggle scope; click a KPI
						to drill into the Operations tab.
					</p>
				</div>
				<LifecycleToggle />
			</div>

			<div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
				<KpiCard
					label="Products (scope)"
					value={(copy.data?.total_products ?? 0).toLocaleString()}
					hint={f.lifecycle_status === "ACTIVE" ? "active only" : "incl. archived"}
					loading={copy.loading}
				/>
				<KpiCard
					label="Copy production-ready"
					value={`${copy.data?.valid_approved_coverage_pct ?? 0}%`}
					hint={`${(copyClasses?.APPROVED_COPY_STALE ?? 0).toLocaleString()} stale · ${(copyClasses?.MISSING_COPY ?? copy.data?.products_missing_copy ?? 0).toLocaleString()} no copy`}
					tone={
						(copy.data?.valid_approved_coverage_pct ?? 0) >= 100
							? "success"
							: (copy.data?.valid_approved_coverage_pct ?? 0) < 50
								? "danger"
								: "warn"
					}
					loading={copy.loading}
				/>
				<KpiCard
					label="Product intel"
					value={`${intel.data?.coverage_pct ?? 0}%`}
					hint={`${(intel.data?.missing_snapshot ?? 0).toLocaleString()} missing`}
					tone={(intel.data?.coverage_pct ?? 0) < 50 ? "warn" : "success"}
					loading={intel.loading}
				/>
				<KpiCard
					label="Clusters"
					value={clusterCount}
					hint="canonical"
					loading={clusters.loading}
				/>
				<KpiCard
					label="Uncategorised"
					value={(clusters.data?.unknown_review_required ?? 0).toLocaleString()}
					hint="products · need cluster review"
					tone={(clusters.data?.unknown_review_required ?? 0) > 0 ? "warn" : "success"}
					loading={clusters.loading}
				/>
				<KpiCard
					label="Queue · missing cluster"
					value={(queue.data?.pending_missing_cluster ?? 0).toLocaleString()}
					hint="pre-commit drafts awaiting a cluster"
					tone={(queue.data?.pending_missing_cluster ?? 0) > 0 ? "warn" : "success"}
					loading={queue.loading}
				/>
				<KpiCard
					label="Prompt ready"
					value={(prompt.data?.READY ?? 0).toLocaleString()}
					hint={`${(prompt.data?.not_evaluated ?? 0).toLocaleString()} not evaluated`}
					loading={prompt.loading}
				/>
			</div>

			<Section
				title="Products per cluster"
				helper="Catalogue-wide distribution (not affected by the scope toggle)."
			>
				{clusters.error ? (
					<p className="text-xs text-red-400">{clusters.error}</p>
				) : clusterData.length === 0 ? (
					<p className="text-xs text-slate-500">
						{clusters.loading ? "Loading…" : "No cluster data."}
					</p>
				) : (
					<BarPanel data={clusterData} />
				)}
			</Section>

			<div className="grid gap-6 lg:grid-cols-2">
				<Section
					title="Copy production-readiness"
					helper="Products with a STRICT-VALID approved copy set (grounded, safe, complete, non-generic, reviewed) — not raw row coverage."
				>
					{copy.error ? (
						<p className="text-xs text-red-400">{copy.error}</p>
					) : (
						<DonutPanel
							data={copyDonut}
							centerValue={`${copy.data?.valid_approved_coverage_pct ?? 0}%`}
							centerLabel="production-ready"
						/>
					)}
				</Section>

				<Section
					title="Readiness"
					helper="Prompt-readiness and product-mapping state."
				>
					<div className="space-y-4">
						<CoverageBar
							label="Prompt ready"
							covered={prompt.data?.READY ?? 0}
							total={prompt.data?.total_products ?? 0}
							tone="info"
						/>
						<CoverageBar
							label="Product intelligence"
							covered={intel.data?.with_snapshot ?? 0}
							total={intel.data?.total_products ?? 0}
							tone="success"
						/>
						<CoverageBar
							label="Mapping ready"
							covered={mapping.data?.ready ?? 0}
							total={mapping.data?.total_products ?? 0}
							tone="success"
						/>
						<CoverageBar
							label="Mapping blocked"
							covered={mapping.data?.blocked ?? 0}
							total={mapping.data?.total_products ?? 0}
							tone="danger"
						/>
					</div>
				</Section>
			</div>
		</div>
	);
}

export default function ReportingExecutivePage() {
	return (
		<ReportingFilterProvider>
			<ExecutiveInner />
		</ReportingFilterProvider>
	);
}
