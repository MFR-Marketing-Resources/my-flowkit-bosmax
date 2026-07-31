import { useEffect, useState } from "react";
import { Section } from "../components/ui";
import { KpiCard, type KpiTone } from "../components/reporting/KpiCard";
import { ExceptionTable } from "../components/reporting/ExceptionTable";
import {
	ReportingFilterProvider,
	useReportingFilters,
	asFilters,
} from "../components/reporting/ReportingFilterContext";
import {
	useExceptions,
	useExceptionPage,
	useFailedGenerations,
	type ExceptionKind,
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

function OperationsInner() {
	const f = useReportingFilters();
	const [selected, setSelected] = useState<ExceptionKind>("missing_copy");
	const PAGE_SIZE = 15;
	const [page, setPage] = useState(1);
	const [q, setQ] = useState("");
	const [sortBy, setSortBy] = useState("updated_at");
	const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

	// Any change of cohort or ordering invalidates the current page number.
	useEffect(() => {
		setPage(1);
	}, [selected, f.lifecycle_status, f.cluster, f.product_type_group, q, sortBy, sortDir]);

	const table = useExceptionPage(selected, asFilters(f), {
		limit: PAGE_SIZE,
		offset: (page - 1) * PAGE_SIZE,
		q,
		sort_by: sortBy,
		sort_dir: sortDir,
	});
	const failed = useFailedGenerations();
	const selectedLabel =
		KIND_META.find((m) => m.kind === selected)?.label ?? selected;

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
