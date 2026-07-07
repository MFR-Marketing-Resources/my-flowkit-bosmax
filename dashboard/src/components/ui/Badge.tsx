import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "info" | "success" | "warn" | "danger";

const TONE: Record<BadgeTone, string> = {
	neutral: "border-slate-700 bg-slate-800/60 text-slate-300",
	info: "border-blue-500/30 bg-blue-500/10 text-blue-200",
	success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
	warn: "border-amber-500/30 bg-amber-500/10 text-amber-200",
	danger: "border-red-500/30 bg-red-500/10 text-red-200",
};

export interface BadgeProps {
	children: ReactNode;
	tone?: BadgeTone;
	className?: string;
}

/** Status pill. Colour + text (never colour alone) for consistent status UX. */
export function Badge({ children, tone = "neutral", className }: BadgeProps) {
	return (
		<span
			className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${TONE[tone]}${className ? ` ${className}` : ""}`}
		>
			{children}
		</span>
	);
}
