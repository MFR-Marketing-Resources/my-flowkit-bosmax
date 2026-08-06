import type { ReactNode } from "react";

export type QueueStatus = "queued" | "ready" | "running" | "done" | "error";

export interface QueueRowProps {
	title: ReactNode;
	sub?: ReactNode;
	status: QueueStatus;
	/** 0-100. When `status === "running"`, renders a progress track. */
	progress?: number;
	/** Optional leading thumbnail node; falls back to a gradient placeholder. */
	thumb?: ReactNode;
	className?: string;
}

const STATUS_LABEL: Record<QueueStatus, string> = {
	queued: "Queued",
	ready: "Ready",
	running: "Running",
	done: "Done",
	error: "Failed",
};

const STATUS_CHIP: Record<QueueStatus, string> = {
	queued: "border-slate-700 bg-slate-800/60 text-slate-400",
	ready: "border-slate-700 bg-slate-800/60 text-slate-300",
	running: "border-amber-500/30 bg-amber-500/10 text-amber-200",
	done: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
	error: "border-red-500/30 bg-red-500/10 text-red-200",
};

/** One item in the production queue — title, status, optional live progress. */
export function QueueRow({
	title,
	sub,
	status,
	progress,
	thumb,
	className,
}: QueueRowProps) {
	const clamped =
		progress == null ? null : Math.max(0, Math.min(100, progress));

	return (
		<div
			className={`flex items-center gap-2.5 rounded-xl border border-slate-800 bg-slate-900/50 p-2${className ? ` ${className}` : ""}`}
		>
			<div className="h-11 w-8 flex-none overflow-hidden rounded-md bg-gradient-to-br from-v4-accent/25 to-v4-auto/25">
				{thumb}
			</div>
			<div className="min-w-0 flex-1">
				<div className="truncate text-[12px] font-semibold text-slate-200">
					{title}
				</div>
				{sub != null && (
					<div className="truncate text-[10px] text-slate-500">{sub}</div>
				)}
				{status === "running" && clamped != null && (
					<div className="mt-1 h-1 overflow-hidden rounded-full bg-slate-800">
						<div
							className="h-full rounded-full bg-gradient-to-r from-v4-accent to-v4-auto transition-[width]"
							style={{ width: `${clamped}%` }}
						/>
					</div>
				)}
			</div>
			<span
				className={`flex-none rounded-full border px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.05em] ${STATUS_CHIP[status]}`}
			>
				{status === "running" && clamped != null
					? `${clamped}%`
					: STATUS_LABEL[status]}
			</span>
		</div>
	);
}
