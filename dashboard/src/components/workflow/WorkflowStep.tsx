import { useState } from "react";
import type { ReactNode } from "react";

export type WorkflowStepStatus = "done" | "active" | "upcoming";

export interface WorkflowStepProps {
	/** 1-based step number shown in the leading badge. */
	index: number;
	title: ReactNode;
	/** Drives the badge + border treatment. `done` collapses to `summary`. */
	status: WorkflowStepStatus;
	/** One-line resolved summary shown when the step is collapsed (typically
	 * once `status === "done"`) — e.g. "8s · 3 videos · Veo 3.1". */
	summary?: ReactNode;
	/** Helper line under the title — always say what the step is for. */
	helper?: ReactNode;
	/** Right-aligned control in the header (e.g. a "Tweak" / "Edit" button). */
	action?: ReactNode;
	/** Controlled open state. When omitted, the step manages its own state,
	 * seeded open while `status === "active"`. */
	open?: boolean;
	/** Called when the header toggle is pressed (fires in controlled and
	 * uncontrolled modes). */
	onToggleOpen?: () => void;
	/** When false, the step cannot be expanded (e.g. a blocked upcoming step). */
	collapsible?: boolean;
	className?: string;
	children?: ReactNode;
}

const BADGE: Record<WorkflowStepStatus, string> = {
	done: "border-v4-accent/40 bg-v4-accent/15 text-v4-accent-ink",
	active: "border-v4-accent bg-v4-accent/10 text-v4-accent-ink",
	upcoming: "border-slate-700 bg-slate-950 text-slate-500",
};

const FRAME: Record<WorkflowStepStatus, string> = {
	done: "border-slate-800 bg-slate-900/50",
	active: "border-v4-accent/50 bg-slate-900/70 shadow-lg shadow-black/20",
	upcoming: "border-slate-800/70 bg-slate-900/30",
};

/**
 * One guided step in the V4 workflow shell. Progressive disclosure: an active
 * step is expanded and shows its controls; a completed step collapses to a
 * one-line `summary`. Numbered because the workflow IS an ordered sequence.
 */
export function WorkflowStep({
	index,
	title,
	status,
	summary,
	helper,
	action,
	open,
	onToggleOpen,
	collapsible = true,
	className,
	children,
}: WorkflowStepProps) {
	const [internalOpen, setInternalOpen] = useState(status === "active");
	const isControlled = open !== undefined;
	const isOpen = collapsible ? (isControlled ? open : internalOpen) : true;

	const toggle = () => {
		if (!collapsible) return;
		onToggleOpen?.();
		if (!isControlled) setInternalOpen((v) => !v);
	};

	return (
		<section
			className={`rounded-2xl border p-4 transition-colors ${FRAME[status]}${className ? ` ${className}` : ""}`}
		>
			<div className="flex items-start gap-3">
				<span
					aria-hidden
					className={`mt-0.5 grid h-6 w-6 flex-none place-items-center rounded-lg border font-mono text-[11px] font-bold ${BADGE[status]}`}
				>
					{status === "done" ? "✓" : index}
				</span>

				<button
					type="button"
					onClick={toggle}
					disabled={!collapsible}
					aria-expanded={collapsible ? isOpen : undefined}
					className={`flex min-w-0 flex-1 items-start justify-between gap-3 text-left ${collapsible ? "cursor-pointer" : "cursor-default"}`}
				>
					<span className="min-w-0 space-y-0.5">
						<span className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-slate-200">
							{title}
						</span>
						{helper != null && isOpen && (
							<span className="block text-[10px] text-slate-500">{helper}</span>
						)}
						{!isOpen && summary != null && (
							<span className="block truncate text-[11px] text-slate-400">
								{summary}
							</span>
						)}
					</span>
					<span className="flex flex-none items-center gap-2">
						{action != null && isOpen && (
							<span
								className="shrink-0"
								onClick={(e) => e.stopPropagation()}
								role="presentation"
							>
								{action}
							</span>
						)}
						{collapsible && (
							<span
								aria-hidden
								className={`text-slate-500 transition-transform ${isOpen ? "rotate-180" : ""}`}
							>
								▾
							</span>
						)}
					</span>
				</button>
			</div>

			{isOpen && children != null && (
				<div className="mt-4 pl-9">{children}</div>
			)}
		</section>
	);
}
