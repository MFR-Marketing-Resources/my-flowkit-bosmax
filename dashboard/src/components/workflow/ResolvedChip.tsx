import type { ReactNode } from "react";

export interface ResolvedChipProps {
	/** What was resolved, e.g. "Scene → camera". */
	label: ReactNode;
	/** The resolved value, e.g. "Close-up · ECU + TOPDOWN". */
	value: ReactNode;
	/** Show the violet "AUTO" marker — this value came from the knowledge base
	 * rather than a manual pick. */
	auto?: boolean;
	/** Optional leading icon/emoji. */
	icon?: ReactNode;
	/** Optional override control — when provided, renders a "Tweak" button. */
	onTweak?: () => void;
	tweakLabel?: string;
	className?: string;
}

/**
 * A single knowledge-resolved fact shown read-only, with an optional escape
 * hatch to override it. The violet AUTO marker is the V4 signal for "the
 * system chose this for you"; teal is the resolved value itself.
 */
export function ResolvedChip({
	label,
	value,
	auto = true,
	icon,
	onTweak,
	tweakLabel = "Tweak",
	className,
}: ResolvedChipProps) {
	return (
		<div
			className={`flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2${className ? ` ${className}` : ""}`}
		>
			{icon != null && (
				<span className="grid h-7 w-7 flex-none place-items-center rounded-lg bg-slate-800/70 text-sm">
					{icon}
				</span>
			)}
			<div className="min-w-0 flex-1">
				<div className="flex items-center gap-1.5">
					<span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						{label}
					</span>
					{auto && (
						<span className="rounded-full border border-v4-auto/40 bg-v4-auto/15 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-[0.1em] text-v4-auto">
							Auto
						</span>
					)}
				</div>
				<div className="truncate text-sm font-semibold text-v4-accent-ink">
					{value}
				</div>
			</div>
			{onTweak != null && (
				<button
					type="button"
					onClick={onTweak}
					className="flex-none rounded-lg border border-slate-700 px-2.5 py-1 text-[11px] font-semibold text-slate-300 transition-colors hover:border-v4-accent/50 hover:text-v4-accent-ink"
				>
					{tweakLabel}
				</button>
			)}
		</div>
	);
}
