import { useState } from "react";
import { Section } from "../components/ui";
import { KpiCard, type KpiTone } from "../components/reporting/KpiCard";
import { ExceptionTable } from "../components/reporting/ExceptionTable";
import {
	ReportingFilterProvider,
	useReportingFilters,
	asFilters,
} from "../components/reporting/ReportingFilterContext";
import { useExceptions, useFailedGenerations, type ExceptionKind } from "../api/reporting";
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
	// Headline the number that is actually actionable. Archived products are
	// ARCHIVED_NOT_IN_SCOPE (P5.8), so folding them into one figure overstates the work.
	const app = data?.applicability;
	const required = app?.required_missing ?? data?.total ?? 0;
	const archived = app?.documented_na_archived ?? 0;
	const hint = selected
		? "▾ shown below"
		: archived > 0
			? `+${archived.toLocaleString()} archived N/A · click to drill`
			: "click to drill";
	return (
		<KpiCard
			label={label}
			value={required.toLocaleString()}
			tone={required === 0 ? "success" : tone}
			hint={hint}
			loading={loading}
			onClick={() => onSelect(kind)}
		/>
	);
}

function OperationsInner() {
	const f = useReportingFilters();
	const [selected, setSelected] = useState<ExceptionKind>("missing_copy");
	const table = useExceptions(selected, asFilters(f));
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
