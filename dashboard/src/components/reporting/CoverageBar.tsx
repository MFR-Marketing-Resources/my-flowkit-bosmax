// Presentational coverage progress bar: "covered / total (pct%)". Pure view.

export type CoverageTone = "info" | "success" | "warn" | "danger";

const FILL: Record<CoverageTone, string> = {
	info: "bg-sky-500",
	success: "bg-emerald-500",
	warn: "bg-amber-500",
	danger: "bg-red-500",
};

export interface CoverageBarProps {
	label: string;
	covered: number;
	total: number;
	tone?: CoverageTone;
}

export function CoverageBar({
	label,
	covered,
	total,
	tone = "info",
}: CoverageBarProps) {
	const pct = total > 0 ? Math.round((100 * covered) / total) : 0;
	return (
		<div className="space-y-1.5">
			<div className="flex items-baseline justify-between text-xs">
				<span className="text-slate-300">{label}</span>
				<span className="tabular-nums text-slate-400">
					{covered.toLocaleString()} / {total.toLocaleString()}{" "}
					<span className="text-slate-500">({pct}%)</span>
				</span>
			</div>
			<div className="h-2 overflow-hidden rounded-full bg-slate-800">
				<div
					className={`h-full rounded-full ${FILL[tone]} transition-all`}
					style={{ width: `${pct}%` }}
				/>
			</div>
		</div>
	);
}
