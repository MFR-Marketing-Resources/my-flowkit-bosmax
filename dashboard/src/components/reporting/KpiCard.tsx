import type { ReactNode } from "react";

// Presentational KPI card. Extends the inline pattern from DashboardPage into one
// reusable, optionally-clickable card (click → drill-down). No data fetching here.

export type KpiTone = "neutral" | "info" | "success" | "warn" | "danger";

const TONE: Record<KpiTone, string> = {
	neutral: "border-slate-800 bg-slate-900/50 text-slate-100",
	info: "border-blue-500/30 bg-blue-500/10 text-blue-100",
	success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-100",
	warn: "border-amber-500/30 bg-amber-500/10 text-amber-100",
	danger: "border-red-500/30 bg-red-500/10 text-red-100",
};

export interface KpiCardProps {
	label: string;
	value: ReactNode;
	hint?: ReactNode;
	tone?: KpiTone;
	loading?: boolean;
	onClick?: () => void;
}

export function KpiCard({
	label,
	value,
	hint,
	tone = "neutral",
	loading,
	onClick,
}: KpiCardProps) {
	const base = `rounded-2xl border px-4 py-3 text-left transition ${TONE[tone]}`;
	const inner = (
		<>
			<div className="text-[10px] font-semibold uppercase tracking-[0.18em] opacity-70">
				{label}
			</div>
			<div className="mt-2 text-3xl font-semibold tabular-nums">
				{loading ? "…" : value}
			</div>
			{hint != null && (
				<div className="mt-1 text-[11px] opacity-70">{hint}</div>
			)}
		</>
	);
	if (onClick) {
		return (
			<button
				type="button"
				onClick={onClick}
				className={`${base} w-full hover:brightness-125 focus:outline-none focus:ring-2 focus:ring-sky-500/40`}
			>
				{inner}
			</button>
		);
	}
	return <div className={base}>{inner}</div>;
}
