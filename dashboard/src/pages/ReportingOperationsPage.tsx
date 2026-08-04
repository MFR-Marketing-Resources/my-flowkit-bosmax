import { useEffect, useState } from "react";
import { Section } from "../components/ui";
import { KpiCard, type KpiTone } from "../components/reporting/KpiCard";
import { ExceptionTable } from "../components/reporting/ExceptionTable";
import { IntelligenceStagePanel } from "../components/reporting/IntelligenceStagePanel";
import {
	ReportingFilterProvider,
	useReportingFilters,
	asFilters,
} from "../components/reporting/ReportingFilterContext";
import {
	useExceptions,
	useRegistrationQueueCoverage,
	useExceptionPage,
	type IntelligenceStage,
	useFailedGenerations,
	usePiQuality,
	type ExceptionKind,
	type LifecycleScope,
	type PiQualityClass,
} from "../api/reporting";
import { FailedGenerationsPanel } from "../components/reporting/FailedGenerationsPanel";

// Operational Intelligence — exception-first. Show what's broken, count it, and drill
// into the exact product list. Every exception widget owns its own fetch.

const KIND_META: { kind: ExceptionKind; label: string; tone: KpiTone }[] = [
	{ kind: "missing_copy", label: "Missing copywriting", tone: "danger" },
	{ kind: "missing_intelligence", label: "Missing product intel", tone: "warn" },
	{ kind: "missing_image", label: "Missing image", tone: "warn" },
	{ kind: "missing_cluster", label: "Missing cluster", tone: "warn" },
	{ kind: "missing_product_type", label: "Missing product type", tone: "warn" },
	{ kind: "mapping_blocked", label: "Mapping blocked", tone: "danger" },
	{ kind: "prompt_not_ready", label: "Prompt not ready", tone: "info" },
	{ kind: "scene_strategy_gaps", label: "Scene strategy gaps", tone: "warn" },
	{ kind: "failed_generation", label: "Failed gen (all-time historical)", tone: "danger" },
];

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

function ExceptionKpi({
	kind,
	label,
	tone,
	selected,
	onSelect,
}: {
	kind: ExceptionKind;
	label: string;
	tone: KpiTone;
	selected: boolean;
	onSelect: (k: ExceptionKind) => void;
}) {
	const f = useReportingFilters();
	const { data, loading } = useExceptions(kind, asFilters(f));
	// The headline must match the SELECTED SCOPE. Under "All (incl. archived)" it is the
	// real missing total across every real product; headlining the ACTIVE figure there
	// made the two tabs look identical and hid archived catalogue debt. Test fixtures are
	// excluded from both (they are harness rows, not products) and disclosed separately.
	const app = data?.applicability;
	const isAll = f.lifecycle_status === "ALL";
	const active = app?.active_missing ?? 0;
	const archived = app?.archived_missing ?? 0;
	const fixtures = app?.test_fixture_excluded ?? 0;
	// `total` is the real-product count (fixtures are quarantined out of the default
	// query), so the headline is the SAME number the drill-down pager reports. Deriving it
	// separately is what let the card say 402 while the table said "1-15 of 410".
	const headline = data?.total ?? 0;

	// The breakdown stays visible when the card is selected — it is the whole point of
	// the ALL tab and must not be replaced by "shown below".
	const parts: string[] = [];
	if (isAll && app) {
		parts.push(`${active.toLocaleString()} active`);
		parts.push(`${archived.toLocaleString()} archived`);
	}
	if (fixtures > 0) parts.push(`${fixtures.toLocaleString()} test fixtures excluded`);
	const breakdown = parts.join(" + ");
	const hint = [breakdown, selected ? "▾ shown below" : "click to drill"]
		.filter(Boolean)
		.join(" · ");

	return (
		<KpiCard
			label={label}
			value={headline.toLocaleString()}
			tone={headline === 0 ? "success" : tone}
			hint={hint}
			loading={loading}
			onClick={() => onSelect(kind)}
		/>
	);
}

// 08D INTEL QUALITY DEBT: "has a snapshot" stopped being the truth the day 318
// approvals froze MISSING_REQUIRED_FIELDS inside them. Four mutually-exclusive classes,
// counted by the backend, drill-down through the same exception machinery — no
// frontend-only counting anywhere.
const PI_QUALITY_META: {
	cls: PiQualityClass;
	label: string;
	tone: KpiTone;
}[] = [
	{ cls: "FULLY_COMPLETE", label: "PI fully complete", tone: "info" },
	{
		cls: "APPROVED_WITH_GOVERNED_ABSENCE",
		label: "Approved · governed absence",
		tone: "info",
	},
	{
		cls: "LEGACY_APPROVED_INCOMPLETE",
		label: "Legacy approved incomplete",
		tone: "warn",
	},
	{
		cls: "MISSING_APPROVED_INTELLIGENCE",
		label: "Missing approved intel",
		tone: "danger",
	},
];

function IntelQualityDebt({
	selected,
	onSelect,
	lifecycle,
}: {
	selected: ExceptionKind;
	onSelect: (k: ExceptionKind) => void;
	lifecycle: LifecycleScope;
}) {
	const { data, loading, error } = usePiQuality(lifecycle);
	return (
		<Section
			title="Intel quality debt"
			helper={
				data
					? `${data.total_real_products.toLocaleString()} real products — ${data.test_fixtures_excluded.toLocaleString()} test fixtures excluded. Legacy incomplete are historical approvals WITHOUT governed dispositions; they are never relabelled.`
					: error || "Loading…"
			}
		>
			<div
				className="grid grid-cols-2 gap-4 md:grid-cols-4"
				data-testid="intel-quality-debt-card"
			>
				{PI_QUALITY_META.map(({ cls, label, tone }) => {
					const entry = data?.classes?.[cls];
					const kind = data?.drill_down_kinds?.[cls];
					return (
						<KpiCard
							key={cls}
							label={label}
							value={(entry?.total ?? 0).toLocaleString()}
							tone={
								cls === "FULLY_COMPLETE"
									? "success"
									: (entry?.total ?? 0) === 0
										? "success"
										: tone
							}
							hint={[
								`${(entry?.active ?? 0).toLocaleString()} active + ${(entry?.archived ?? 0).toLocaleString()} archived`,
								kind && selected === kind ? "▾ shown below" : "click to drill",
							].join(" · ")}
							loading={loading}
							onClick={() => kind && onSelect(kind)}
						/>
					);
				})}
			</div>
		</Section>
	);
}

// Pre-commit registration-queue backlog. SEPARATE from the product KPIs above so
// "Missing cluster = 0" (committed products) reads unambiguously next to the drafts
// that still await a cluster. Not exception-drill-downs — a different data source.
function RegistrationQueueBacklog() {
	const { data, loading } = useRegistrationQueueCoverage();
	const pending = data?.pending_drafts ?? 0;
	const missingCluster = data?.pending_missing_cluster ?? 0;
	const missingType = data?.pending_missing_product_type ?? 0;
	return (
		<div className="mt-2">
			<div className="mb-2 flex flex-wrap items-baseline gap-2">
				<h3 className="text-sm font-semibold text-slate-200">
					Registration queue (pre-commit)
				</h3>
				<span className="text-[11px] text-slate-500">
					Drafts not yet committed to products — the product KPIs above cannot see
					these. A draft is assigned its cluster at recompute/commit.
				</span>
			</div>
			<div className="grid grid-cols-2 gap-4 md:grid-cols-4">
				<KpiCard
					label="Queue · pending drafts"
					value={pending.toLocaleString()}
					tone="neutral"
					loading={loading}
					hint="uncommitted"
				/>
				<KpiCard
					label="Queue · missing cluster"
					value={missingCluster.toLocaleString()}
					tone={missingCluster === 0 ? "success" : "warn"}
					loading={loading}
					hint="pending drafts with no cluster"
				/>
				<KpiCard
					label="Queue · missing product type"
					value={missingType.toLocaleString()}
					tone={missingType === 0 ? "success" : "warn"}
					loading={loading}
					hint="pending drafts with no product type"
				/>
			</div>
		</div>
	);
}

function OperationsInner() {
	const f = useReportingFilters();
	const [selected, setSelected] = useState<ExceptionKind>("missing_copy");
	const PAGE_SIZE = 15;
	const [page, setPage] = useState(1);
	const [q, setQ] = useState("");
	const [sortBy, setSortBy] = useState("updated_at");
	const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
	const [stage, setStage] = useState<IntelligenceStage | "">("");
	const [risk, setRisk] = useState("");
	const [copyBlocked, setCopyBlocked] = useState("");

	// Any change of cohort or ordering invalidates the current page number.
	useEffect(() => {
		setPage(1);
	}, [
		selected,
		f.lifecycle_status,
		f.cluster,
		f.product_type_group,
		q,
		sortBy,
		sortDir,
		stage,
		risk,
		copyBlocked,
	]);

	// Intelligence-only filters must not silently narrow another bucket's cohort.
	const isIntel = selected === "missing_intelligence";
	useEffect(() => {
		if (!isIntel) {
			setStage("");
			setRisk("");
			setCopyBlocked("");
		}
	}, [isIntel]);

	const table = useExceptionPage(selected, asFilters(f), {
		limit: PAGE_SIZE,
		offset: (page - 1) * PAGE_SIZE,
		q,
		sort_by: sortBy,
		sort_dir: sortDir,
		intelligence_stage: isIntel ? stage : "",
		claim_risk_level: isIntel ? risk : "",
		copy_blocked: isIntel && copyBlocked ? copyBlocked === "yes" : undefined,
	});
	const failed = useFailedGenerations();
	const PI_KIND_LABELS: Record<string, string> = {
		pi_fully_complete: "PI fully complete",
		pi_governed_absence: "Approved with governed absence",
		pi_legacy_incomplete: "Legacy approved incomplete",
		pi_missing_approved: "Missing approved intelligence",
	};
	const selectedLabel =
		KIND_META.find((m) => m.kind === selected)?.label ??
		PI_KIND_LABELS[selected] ??
		selected;

	return (
		<div className="space-y-6">
			<div className="flex flex-wrap items-center justify-between gap-3">
				<div>
					<h2 className="text-lg font-semibold text-slate-100">
						Operational Intelligence
					</h2>
					<p className="text-xs text-slate-500">
						Exception-first. Click a bucket to list the exact products, then open
						one to fix it.
					</p>
				</div>
				<LifecycleToggle />
			</div>

			<div className="grid grid-cols-2 gap-4 md:grid-cols-4">
				{KIND_META.map((m) => (
					<ExceptionKpi
						key={m.kind}
						kind={m.kind}
						label={m.label}
						tone={m.tone}
						selected={selected === m.kind}
						onSelect={setSelected}
					/>
				))}
			</div>

			<RegistrationQueueBacklog />

			<IntelQualityDebt
				selected={selected}
				onSelect={setSelected}
				lifecycle={f.lifecycle_status}
			/>

			<Section
				title="Failed generations — honest time windows"
				helper="All-time is cumulative history, not active incidents; ADR-007 dead DOM-lane failures are flagged, never deleted."
			>
				<FailedGenerationsPanel
					report={failed.data}
					loading={failed.loading}
					error={failed.error}
				/>
			</Section>

			<Section
				title={selectedLabel}
				helper={
					table.data
						? `${table.data.total.toLocaleString()} record(s). Row click opens the product.`
						: "Loading…"
				}
			>
				{isIntel ? (
					<IntelligenceStagePanel
						breakdown={table.data?.stage_breakdown}
						stage={stage}
						risk={risk}
						copyBlocked={copyBlocked}
						onStage={setStage}
						onRisk={setRisk}
						onCopyBlocked={setCopyBlocked}
					/>
				) : null}
				{table.error ? (
					<p className="text-xs text-red-400">{table.error}</p>
				) : (
					<ExceptionTable
						kind={selected}
						items={table.data?.items ?? []}
						loading={table.loading}
						total={table.data?.total ?? 0}
						page={page}
						pageSize={PAGE_SIZE}
						q={q}
						sortBy={sortBy}
						sortDir={sortDir}
						onPageChange={setPage}
						onSearchChange={setQ}
						onSortChange={(by, dir) => {
							setSortBy(by);
							setSortDir(dir);
						}}
					/>
				)}
			</Section>
		</div>
	);
}

export default function ReportingOperationsPage() {
	return (
		<ReportingFilterProvider>
			<OperationsInner />
		</ReportingFilterProvider>
	);
}
