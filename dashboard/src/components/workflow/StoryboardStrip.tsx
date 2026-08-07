import type { ReactNode } from "react";

export interface StoryboardShot {
	id?: string;
	/** Shot title, e.g. "Present → Close-up". */
	label: ReactNode;
	/** Sub line, e.g. "Farah · ECU · 0-3s". */
	sub?: ReactNode;
	/** Optional badge in the corner, e.g. the block purpose. */
	tag?: ReactNode;
}

export interface StoryboardStripProps {
	shots: StoryboardShot[];
	/** Shown when there are no shots yet. */
	emptyLabel?: ReactNode;
	className?: string;
}

/**
 * Horizontal filmstrip of the planned shots — the "see the storyboard before
 * you compile" surface. Scrolls inside its own container so the page never
 * scrolls sideways.
 */
export function StoryboardStrip({
	shots,
	emptyLabel = "Storyboard appears once length and creative direction are set.",
	className,
}: StoryboardStripProps) {
	if (shots.length === 0) {
		return (
			<div
				className={`rounded-xl border border-dashed border-slate-800 bg-slate-950/30 px-4 py-6 text-center text-[11px] text-slate-500${className ? ` ${className}` : ""}`}
			>
				{emptyLabel}
			</div>
		);
	}

	return (
		<div className={`overflow-x-auto${className ? ` ${className}` : ""}`}>
			<div className="flex gap-2.5 pb-1">
				{shots.map((shot, i) => (
					<div
						key={shot.id ?? i}
						className="flex w-36 flex-none flex-col gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-2.5"
					>
						<div className="relative aspect-[9/16] w-full overflow-hidden rounded-lg bg-gradient-to-br from-v4-accent/25 to-v4-auto/25">
							<span className="absolute left-1.5 top-1.5 rounded-md bg-slate-950/70 px-1.5 py-0.5 font-mono text-[9px] text-slate-300">
								{i + 1}
							</span>
							{shot.tag != null && (
								<span className="absolute right-1.5 top-1.5 rounded-md bg-slate-950/70 px-1.5 py-0.5 text-[9px] font-semibold text-v4-accent-ink">
									{shot.tag}
								</span>
							)}
						</div>
						<div className="min-w-0">
							<div className="truncate text-[11px] font-semibold text-slate-200">
								{shot.label}
							</div>
							{shot.sub != null && (
								<div className="truncate text-[10px] text-slate-500">
									{shot.sub}
								</div>
							)}
						</div>
					</div>
				))}
			</div>
		</div>
	);
}
