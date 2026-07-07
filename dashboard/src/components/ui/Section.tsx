import type { ReactNode } from "react";

export interface SectionProps {
	/** Optional step badge (e.g. "1", "2") shown before the title — the
	 * "section-by-section" affordance from the IMG Fastlane pattern. */
	step?: ReactNode;
	title: ReactNode;
	/** Optional right-aligned action (button/link) in the header row. */
	action?: ReactNode;
	/** Optional helper line under the title — always tell the user what this
	 * section is for. */
	helper?: ReactNode;
	className?: string;
	children?: ReactNode;
}

/**
 * Standard labelled section card. One consistent container for every page so
 * users read the UI the same way everywhere (see the IMG Fastlane reference).
 */
export function Section({
	step,
	title,
	action,
	helper,
	className,
	children,
}: SectionProps) {
	return (
		<section
			className={`rounded-2xl border border-slate-800 bg-slate-900/50 p-5 space-y-4 shadow-lg shadow-black/10${className ? ` ${className}` : ""}`}
		>
			<div className="flex items-start justify-between gap-3">
				<div className="space-y-1">
					<h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-slate-300">
						{step != null && (
							<span className="rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 font-mono text-[10px] text-slate-300">
								{step}
							</span>
						)}
						{title}
					</h3>
					{helper != null && (
						<p className="text-[10px] text-slate-500">{helper}</p>
					)}
				</div>
				{action != null && <div className="shrink-0">{action}</div>}
			</div>
			{children}
		</section>
	);
}
