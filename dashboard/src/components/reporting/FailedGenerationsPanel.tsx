import { Badge } from "../ui";
import type { FailedGenerationReport } from "../../api/reporting";

// Pure view. Renders the honest failed-generation report: explicit time windows (so a
// historical all-time count is never read as "N active incidents") + the ADR-007
// dead-DOM-lane split + error grouping. All aggregation is server-side; this only renders.

export interface FailedGenerationsPanelProps {
	report: FailedGenerationReport | null;
	loading?: boolean;
	error?: string;
}

export function FailedGenerationsPanel({ report, loading, error }: FailedGenerationsPanelProps) {
	if (error) return <p className="text-xs text-red-400">{error}</p>;
	if (!report) return <p className="text-xs text-slate-500">{loading ? "Loading…" : "No data."}</p>;

	const w = report.windows;
	const windows: { label: string; value: number; tone: string }[] = [
		{ label: report.window_labels.last_24h ?? "last 24h", value: w.last_24h, tone: "text-emerald-200" },
		{ label: report.window_labels.last_7d ?? "last 7d", value: w.last_7d, tone: "text-amber-200" },
		{ label: report.window_labels.last_30d ?? "last 30d", value: w.last_30d, tone: "text-amber-200" },
		{ label: report.window_labels.all_time ?? "all-time (historical)", value: w.all_time, tone: "text-slate-300" },
	];

	return (
		<div className="space-y-4">
			<div className="grid grid-cols-2 gap-3 md:grid-cols-4">
				{windows.map((k) => (
					<div key={k.label} className="rounded-xl border border-slate-800 bg-slate-900/50 px-3 py-2">
						<div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{k.label}</div>
						<div className={`mt-1 text-2xl font-semibold tabular-nums ${k.tone}`}>
							{k.value.toLocaleString()}
						</div>
					</div>
				))}
			</div>

			<p className="text-[11px] leading-relaxed text-slate-500">
				All-time is <span className="text-slate-300">cumulative history</span>, not active
				incidents. Of {report.windows.all_time.toLocaleString()}:{" "}
				<span className="text-slate-300">{report.dead_dom_lane_count.toLocaleString()}</span>{" "}
				provable <span className="text-slate-400">ADR-007 dead DOM-lane</span>,{" "}
				{report.provenance_unverified_count.toLocaleString()} legacy-pattern (provenance
				unverified — not asserted dead), {report.other_count.toLocaleString()} other; across{" "}
				{report.distinct_products_all_time} products. Windows counted by{" "}
				<span className="font-mono">{report.windows_counted_by}</span>.
			</p>

			<div>
				<div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
					By error code
				</div>
				<div className="space-y-1">
					{report.by_error_code.slice(0, 8).map((e) => (
						<div key={e.error_code} className="flex items-center justify-between gap-2 text-xs">
							<span className="min-w-0 flex-1 truncate font-mono text-slate-300">{e.error_code}</span>
							{e.classification === "dead_dom_lane" && <Badge tone="neutral">dead DOM</Badge>}
							{e.classification === "legacy_pattern_provenance_unverified" && (
								<Badge tone="warn">unverified</Badge>
							)}
							<span className="tabular-nums text-slate-400">{e.count}</span>
						</div>
					))}
				</div>
			</div>
		</div>
	);
}
