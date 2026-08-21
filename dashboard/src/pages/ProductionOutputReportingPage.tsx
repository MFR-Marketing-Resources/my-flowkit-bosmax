import { useEffect, useState } from "react";
import { Section } from "../components/ui";
import { KpiCard, type KpiTone } from "../components/reporting/KpiCard";
import {
	fetchProductionLedger,
	fetchProductionReport,
	type ProductionFilterOptions,
	type ProductionLedgerRow,
	type ProductionQuery,
	type ProductionReport,
} from "../api/productionOutputReporting";

const PAGE_SIZE = 25;

function localDate(offsetDays = 0) {
	const value = new Date();
	value.setDate(value.getDate() + offsetDays);
	return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, "0")}-${String(value.getDate()).padStart(2, "0")}`;
}

function rate(value: number | null) {
	return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function SelectFilter({
	label,
	value,
	options,
	onChange,
	}: {
	label: string;
	value: string;
	options: { value: string; label: string }[] | string[];
	onChange: (value: string) => void;
}) {
	return (
		<label className="flex min-w-[132px] flex-1 flex-col gap-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
			{label}
			<select
				value={value}
				onChange={(event) => onChange(event.target.value)}
				className="h-9 rounded-lg border border-slate-700 bg-slate-950 px-2 text-xs font-normal normal-case tracking-normal text-slate-200 outline-none focus:border-sky-500"
			>
				<option value="">All</option>
				{options.map((option) => {
					const item = typeof option === "string" ? { value: option, label: option } : option;
					return (
						<option key={item.value} value={item.value}>
							{item.label}
						</option>
					);
				})}
			</select>
		</label>
	);
}

function FilterBar({
	query,
	options,
	onChange,
	onReset,
}: {
	query: ProductionQuery;
	options: ProductionFilterOptions;
	onChange: (key: keyof ProductionQuery, value: string) => void;
	onReset: () => void;
}) {
	return (
		<div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="flex flex-wrap items-end gap-3">
				<label className="flex min-w-[145px] flex-1 flex-col gap-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
					Start date
					<input
						type="date"
						value={query.start_date}
						onChange={(event) => onChange("start_date", event.target.value)}
						className="h-9 rounded-lg border border-slate-700 bg-slate-950 px-2 text-xs font-normal normal-case tracking-normal text-slate-200 outline-none focus:border-sky-500"
					/>
				</label>
				<label className="flex min-w-[145px] flex-1 flex-col gap-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
					End date
					<input
						type="date"
						value={query.end_date}
						onChange={(event) => onChange("end_date", event.target.value)}
						className="h-9 rounded-lg border border-slate-700 bg-slate-950 px-2 text-xs font-normal normal-case tracking-normal text-slate-200 outline-none focus:border-sky-500"
					/>
				</label>
				<SelectFilter label="Staff" value={query.staff ?? ""} options={options.staff} onChange={(value) => onChange("staff", value)} />
				<SelectFilter label="Media type" value={query.media_type ?? ""} options={options.media_types} onChange={(value) => onChange("media_type", value)} />
				<SelectFilter label="Recipe" value={query.production_recipe ?? ""} options={options.production_recipes} onChange={(value) => onChange("production_recipe", value)} />
				<SelectFilter label="Product" value={query.product_id ?? ""} options={options.products} onChange={(value) => onChange("product_id", value)} />
				<SelectFilter label="Provider" value={query.provider ?? ""} options={options.providers} onChange={(value) => onChange("provider", value)} />
				<SelectFilter label="Model" value={query.model_key ?? ""} options={options.models} onChange={(value) => onChange("model_key", value)} />
				<SelectFilter label="Status" value={query.status ?? ""} options={options.statuses} onChange={(value) => onChange("status", value)} />
				<SelectFilter label="QA status" value={query.qa_status ?? ""} options={options.qa_statuses} onChange={(value) => onChange("qa_status", value)} />
				<button
					type="button"
					onClick={onReset}
					className="h-9 rounded-lg border border-slate-700 px-3 text-xs text-slate-400 transition hover:border-sky-500 hover:text-slate-100"
				>
					Reset
				</button>
			</div>
		</div>
	);
}

function Trend({ rows }: { rows: ProductionReport["daily_trend"] }) {
	const max = Math.max(1, ...rows.map((row) => row.successful_video + row.successful_image_poster + row.failed_attempts));
	return (
		<div className="space-y-2">
			{rows.map((row) => {
				const total = row.successful_video + row.successful_image_poster + row.failed_attempts;
				return (
					<div key={row.date} className="grid grid-cols-[92px_1fr_180px] items-center gap-3 text-xs">
						<span className="font-mono text-slate-500">{row.date}</span>
						<div className="h-3 overflow-hidden rounded-full bg-slate-800">
							<div className="flex h-full" style={{ width: `${(total / max) * 100}%` }}>
								<div className="bg-sky-400" style={{ width: `${total ? (row.successful_video / total) * 100 : 0}%` }} />
								<div className="bg-violet-400" style={{ width: `${total ? (row.successful_image_poster / total) * 100 : 0}%` }} />
								<div className="bg-rose-400" style={{ width: `${total ? (row.failed_attempts / total) * 100 : 0}%` }} />
							</div>
						</div>
						<span className="text-right text-[11px] text-slate-500">{row.successful_video} video · {row.successful_image_poster} poster · {row.failed_attempts} failed</span>
					</div>
				);
			})}
		</div>
	);
}

function LedgerTable({
	rows,
	total,
	page,
	onPage,
	loading,
}: {
	rows: ProductionLedgerRow[];
	total: number;
	page: number;
	onPage: (page: number) => void;
	loading: boolean;
}) {
	const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
	return (
		<div className="space-y-3">
			<div className="overflow-x-auto rounded-xl border border-slate-800">
				<table className="min-w-[1180px] w-full text-left text-xs">
					<thead className="bg-slate-950 text-[10px] uppercase tracking-[0.12em] text-slate-500">
						<tr>
							{["Output", "Recipe", "Product", "Staff", "Status", "QA", "Provider / model", "Attempt", "Completed"].map((heading) => <th key={heading} className="px-3 py-3">{heading}</th>)}
						</tr>
					</thead>
					<tbody className="divide-y divide-slate-800/80">
						{loading ? <tr><td colSpan={9} className="px-3 py-8 text-center text-slate-500">Loading ledger…</td></tr> : null}
						{!loading && rows.length === 0 ? <tr><td colSpan={9} className="px-3 py-8 text-center text-slate-500">No actual output records match this window.</td></tr> : null}
						{rows.map((row) => (
							<tr key={`${row.attempt_id}-${row.output_id}`} className="align-top text-slate-300">
								<td className="max-w-[160px] px-3 py-3 font-mono text-[10px] text-slate-400"><details><summary className="cursor-pointer text-sky-300">{row.output_id ?? "—"}</summary><div className="mt-2 space-y-1 text-slate-500"><div>Attempt: {row.attempt_id ?? "—"}</div><div>Plan/run: {row.plan_or_run_id ?? "—"}</div><div>Artifact: {row.artifact_media_id ?? "—"}</div><div>Failure: {row.failure_code ?? "—"}</div></div></details></td>
								<td className="px-3 py-3"><div>{row.production_recipe ?? "—"}</div><div className="mt-1 text-[10px] text-slate-500">{row.origin_surface ?? "—"}</div></td>
								<td className="px-3 py-3"><div>{row.product_name ?? "—"}</div><div className="mt-1 font-mono text-[10px] text-slate-500">{row.product_id ?? "—"}</div></td>
								<td className="px-3 py-3">{row.operator_display_name ?? "Unattributed"}</td>
								<td className="px-3 py-3"><span className={row.status === "SUCCESS" ? "text-emerald-300" : row.status === "FAILED" ? "text-rose-300" : "text-amber-300"}>{row.status}</span></td>
								<td className="px-3 py-3">{row.qa_status}</td>
								<td className="px-3 py-3">{row.provider ?? "—"}<div className="mt-1 text-[10px] text-slate-500">{row.model_key ?? "—"}</div></td>
								<td className="px-3 py-3 text-center">#{row.attempt_number}{row.retry_count ? <div className="text-[10px] text-amber-300">retry</div> : null}</td>
								<td className="whitespace-nowrap px-3 py-3 text-slate-500">{row.completed_at ?? row.created_at ?? "—"}</td>
							</tr>
						))}
					</tbody>
				</table>
			</div>
			<div className="flex items-center justify-between text-xs text-slate-500">
				<span>{total.toLocaleString()} ledger record(s)</span>
				<div className="flex items-center gap-2">
					<button type="button" disabled={page === 0} onClick={() => onPage(page - 1)} className="rounded border border-slate-700 px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40">Previous</button>
					<span>Page {page + 1} / {pageCount}</span>
					<button type="button" disabled={page + 1 >= pageCount} onClick={() => onPage(page + 1)} className="rounded border border-slate-700 px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40">Next</button>
				</div>
			</div>
		</div>
	);
}

const DEFAULT_OPTIONS: ProductionFilterOptions = {
	staff: [],
	media_types: ["VIDEO", "IMAGE", "POSTER"],
	production_recipes: ["HYBRID", "FACELESS", "MONTAGE", "POSTER_BUILDER"],
	origin_surfaces: ["PRODUCTION_STUDIO", "STANDALONE", "POSTER_BUILDER"],
	products: [],
	providers: [],
	models: [],
	statuses: [],
	qa_statuses: [],
};

export default function ProductionOutputReportingPage() {
	const [query, setQuery] = useState<ProductionQuery>({ start_date: localDate(-29), end_date: localDate() });
	const [report, setReport] = useState<ProductionReport | null>(null);
	const [ledger, setLedger] = useState<{ items: ProductionLedgerRow[]; total: number } | null>(null);
	const [loading, setLoading] = useState(true);
	const [ledgerLoading, setLedgerLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [page, setPage] = useState(0);
	const options = report?.filters ?? DEFAULT_OPTIONS;

	useEffect(() => {
		let active = true;
		queueMicrotask(() => {
			if (!active) return;
			setLoading(true);
			setLedgerLoading(true);
			setError(null);
			Promise.all([fetchProductionReport(query), fetchProductionLedger(query, PAGE_SIZE, page * PAGE_SIZE)])
				.then(([nextReport, nextLedger]) => {
					if (!active) return;
					setReport(nextReport);
					setLedger({ items: nextLedger.items, total: nextLedger.total });
				})
				.catch((reason: unknown) => {
					if (active) setError(reason instanceof Error ? reason.message : "Production reporting unavailable");
				})
				.finally(() => {
					if (!active) return;
					setLoading(false);
					setLedgerLoading(false);
				});
		});
		return () => { active = false; };
	}, [query, page]);

	function change(key: keyof ProductionQuery, value: string) {
		setPage(0);
		setQuery((current) => {
			const next = { ...current };
			if (value) next[key] = value as never;
			else delete next[key];
			return next;
		});
	}

	function reset() {
		setPage(0);
		setQuery({ start_date: localDate(-29), end_date: localDate() });
	}

	const overview = report?.overview;
	const kpis: { label: string; value: string; hint: string; tone: KpiTone }[] = [
		{ label: "Successful video", value: String(overview?.successful_video_outputs ?? 0), hint: "distinct actual outputs", tone: "info" },
		{ label: "Successful image / poster", value: String(overview?.successful_image_poster_outputs ?? 0), hint: "Poster Builder scope", tone: "info" },
		{ label: "QA approved", value: String(overview?.qa_approved ?? 0), hint: "authoritative QA only", tone: "success" },
		{ label: "Failed attempts", value: String(overview?.failed_attempts ?? 0), hint: `${overview?.total_attempts ?? 0} total attempts`, tone: (overview?.failed_attempts ?? 0) ? "danger" : "success" },
		{ label: "Success rate", value: rate(overview?.success_rate ?? null), hint: "outputs ÷ attempts", tone: "neutral" },
		{ label: "Active staff", value: String(overview?.active_staff ?? 0), hint: "attributed rows", tone: "neutral" },
		{ label: "Unique products", value: String(overview?.unique_products ?? 0), hint: "actual output records", tone: "neutral" },
		{ label: "Retry rate", value: rate(overview?.retry_rate ?? null), hint: `${overview?.retry_attempts ?? 0} retry attempt(s)`, tone: (overview?.retry_attempts ?? 0) ? "warn" : "neutral" },
	];

	return (
		<div className="space-y-6" data-testid="production-output-reporting-page">
			<div className="flex flex-wrap items-end justify-between gap-3">
				<div>
					<h2 className="text-lg font-semibold text-slate-100">Production Output</h2>
					<p className="text-xs text-slate-500">Actual daily output and staff performance · {report?.reporting_timezone ?? "Asia/Kuala_Lumpur"}</p>
				</div>
				<div className="text-right text-[11px] text-slate-500">Current management view · bounded date window · read-only</div>
			</div>

			<FilterBar query={query} options={options} onChange={change} onReset={reset} />
			{error ? <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-xs text-rose-300">{error}</div> : null}

			<div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-8">
				{kpis.map((kpi) => <KpiCard key={kpi.label} {...kpi} loading={loading} />)}
			</div>

			<Section title="Recipe output" helper="Server-side aggregation of distinct successful outputs. The business recipe remains separate from the originating surface.">
				<div className="grid gap-5 lg:grid-cols-2">
					<div>
						<h4 className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Video</h4>
						<div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="text-[10px] uppercase tracking-[0.12em] text-slate-500"><tr><th className="pb-2">Recipe</th><th className="pb-2">Outputs</th><th className="pb-2">QA</th><th className="pb-2">Failed</th><th className="pb-2">Success</th></tr></thead><tbody className="divide-y divide-slate-800">{(report?.video_breakdown ?? []).map((row) => <tr key={row.production_recipe}><td className="py-2 font-medium text-slate-200">{row.production_recipe}</td><td className="py-2">{row.successful_outputs}</td><td className="py-2">{row.qa_approved}</td><td className="py-2">{row.failed_attempts}</td><td className="py-2">{rate(row.success_rate)}</td></tr>)}</tbody></table></div>
					</div>
					<div>
						<h4 className="mb-3 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">Image / poster</h4>
						<div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead className="text-[10px] uppercase tracking-[0.12em] text-slate-500"><tr><th className="pb-2">Surface</th><th className="pb-2">Outputs</th><th className="pb-2">QA</th><th className="pb-2">Failed</th><th className="pb-2">Success</th></tr></thead><tbody className="divide-y divide-slate-800">{(report?.poster_breakdown ?? []).map((row) => <tr key={row.production_recipe}><td className="py-2 font-medium text-slate-200">Poster Builder</td><td className="py-2">{row.successful_outputs}</td><td className="py-2">{row.qa_approved}</td><td className="py-2">{row.failed_attempts}</td><td className="py-2">{rate(row.success_rate)}</td></tr>)}</tbody></table></div>
					</div>
				</div>
			</Section>

			<Section title="Daily trend" helper="Calendar boundaries and trend dates are interpreted in Asia/Kuala_Lumpur.">
				{loading ? <p className="text-xs text-slate-500">Loading trend…</p> : <Trend rows={report?.daily_trend ?? []} />}
			</Section>

			<Section title="Staff performance" helper="Staff rows prioritize successful outputs and QA-approved outputs. Unattributed records remain in overall metrics but are not ranked here.">
				<div className="overflow-x-auto"><table className="min-w-[1050px] w-full text-left text-xs"><thead className="text-[10px] uppercase tracking-[0.12em] text-slate-500"><tr>{["Staff", "Hybrid", "Faceless", "Montage", "Poster", "Successful outputs", "QA approved", "Failed attempts", "Retry rate", "Success rate", "Unique products"].map((heading) => <th key={heading} className="px-2 pb-2">{heading}</th>)}</tr></thead><tbody className="divide-y divide-slate-800">{(report?.staff_performance ?? []).map((row) => <tr key={row.staff} className="text-slate-300"><td className="px-2 py-2 font-medium text-slate-200">{row.staff_display_name}</td><td className="px-2 py-2">{row.hybrid}</td><td className="px-2 py-2">{row.faceless}</td><td className="px-2 py-2">{row.montage}</td><td className="px-2 py-2">{row.poster}</td><td className="px-2 py-2 font-semibold text-emerald-300">{row.successful_outputs}</td><td className="px-2 py-2">{row.qa_approved}</td><td className="px-2 py-2">{row.failed_attempts}</td><td className="px-2 py-2">{rate(row.retry_rate)}</td><td className="px-2 py-2">{rate(row.success_rate)}</td><td className="px-2 py-2">{row.unique_products}</td></tr>)}</tbody></table>{!loading && !(report?.staff_performance.length) ? <p className="py-5 text-xs text-slate-500">No attributable staff rows in this window.</p> : null}</div>
			</Section>

			<Section title="Generation ledger" helper="Paginated read-only detail sourced from the authoritative output ledgers. Expand an output for attempt, run, artifact, and failure evidence.">
				<LedgerTable rows={ledger?.items ?? []} total={ledger?.total ?? 0} page={page} onPage={setPage} loading={ledgerLoading} />
			</Section>
		</div>
	);
}
