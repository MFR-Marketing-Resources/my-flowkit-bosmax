import type { ReactNode } from "react";

export type CockpitState = "idle" | "online" | "running" | "done";

export interface CockpitPlanRow {
	k: ReactNode;
	v: ReactNode;
	/** Render the value in the mono/teal "resolved code" treatment. */
	mono?: boolean;
	tone?: "default" | "good" | "muted";
}

export interface CockpitGenerate {
	label: string;
	/** Small print under the CTA — the credit-honesty line. */
	note?: ReactNode;
	disabled?: boolean;
	loading?: boolean;
	onClick?: () => void;
}

export interface OperatorCockpitProps {
	/** Lane name shown under the mark, e.g. "Text to Video". */
	laneLabel: ReactNode;
	status?: { label: ReactNode; state: CockpitState };
	product?: { name: ReactNode; sub?: ReactNode; thumb?: ReactNode };
	planTitle?: ReactNode;
	plan?: CockpitPlanRow[];
	/** Queue / sets area between the plan and the Generate CTA. */
	queueTitle?: ReactNode;
	children?: ReactNode;
	generate?: CockpitGenerate;
	debugLabel?: ReactNode;
	/** Diagnostics content, hidden inside a collapsed drawer. */
	debug?: ReactNode;
	className?: string;
}

const DOT: Record<CockpitState, string> = {
	idle: "bg-slate-500",
	online: "bg-emerald-400",
	running: "bg-amber-400",
	done: "bg-emerald-400",
};

const VALUE_TONE: Record<NonNullable<CockpitPlanRow["tone"]>, string> = {
	default: "text-slate-200",
	good: "text-emerald-300",
	muted: "text-slate-500",
};

function GroupTitle({ children }: { children: ReactNode }) {
	return (
		<div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
			<span>{children}</span>
			<span className="h-px flex-1 bg-slate-800" />
		</div>
	);
}

/**
 * The operator cockpit — the V4 right-rail. It answers three questions at a
 * glance: what am I about to make (plan), what will it cost (Generate note),
 * and where is it (queue). Engine diagnostics live in a collapsed Debug drawer,
 * not on the surface. One component; each lane feeds it different plan rows.
 */
export function OperatorCockpit({
	laneLabel,
	status,
	product,
	planTitle = "Production plan",
	plan,
	queueTitle = "Queue",
	children,
	generate,
	debugLabel = "Debug",
	debug,
	className,
}: OperatorCockpitProps) {
	return (
		<aside
			className={`flex flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60 shadow-lg shadow-black/20${className ? ` ${className}` : ""}`}
		>
			<div className="flex items-center gap-2.5 border-b border-slate-800 bg-slate-900/80 px-3.5 py-3">
				<span className="grid h-6 w-6 flex-none place-items-center rounded-lg bg-gradient-to-br from-v4-accent to-v4-auto text-[12px] font-black text-slate-950">
					B
				</span>
				<div className="min-w-0">
					<div className="text-[13px] font-bold text-slate-100">Cockpit</div>
					<div className="truncate text-[10px] text-slate-500">{laneLabel}</div>
				</div>
				{status != null && (
					<span className="ml-auto flex items-center gap-1.5 text-[11px] font-semibold text-slate-300">
						<span
							className={`h-1.5 w-1.5 rounded-full ${DOT[status.state]}`}
						/>
						{status.label}
					</span>
				)}
			</div>

			<div className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto p-3.5">
				{product != null && (
					<div className="flex items-center gap-2.5 rounded-xl border border-slate-800 bg-slate-950/40 p-2">
						<div className="h-8 w-8 flex-none overflow-hidden rounded-lg bg-gradient-to-br from-orange-600 to-red-800">
							{product.thumb}
						</div>
						<div className="min-w-0">
							<div className="truncate text-[12px] font-bold text-slate-100">
								{product.name}
							</div>
							{product.sub != null && (
								<div className="truncate text-[10px] text-slate-500">
									{product.sub}
								</div>
							)}
						</div>
					</div>
				)}

				{plan != null && plan.length > 0 && (
					<div className="space-y-2">
						<GroupTitle>{planTitle}</GroupTitle>
						<div className="overflow-hidden rounded-xl border border-slate-800">
							{plan.map((row, i) => (
								<div
									key={i}
									className="flex items-center justify-between gap-3 border-t border-slate-800 px-3 py-2 text-[12px] first:border-t-0"
								>
									<span className="text-slate-500">{row.k}</span>
									<span
										className={`text-right font-semibold ${row.mono ? "font-mono text-[11px] text-v4-accent-ink" : VALUE_TONE[row.tone ?? "default"]}`}
									>
										{row.v}
									</span>
								</div>
							))}
						</div>
					</div>
				)}

				{children != null && (
					<div className="space-y-2">
						<GroupTitle>{queueTitle}</GroupTitle>
						<div className="space-y-1.5">{children}</div>
					</div>
				)}
			</div>

			{(generate != null || debug != null) && (
				<div className="space-y-2.5 border-t border-slate-800 bg-slate-900/80 p-3.5">
					{generate != null && (
						<>
							<button
								type="button"
								onClick={generate.onClick}
								disabled={generate.disabled || generate.loading}
								className="w-full rounded-xl bg-gradient-to-br from-v4-accent to-v4-auto px-3 py-3 text-[13px] font-bold text-slate-950 shadow-lg shadow-v4-accent/20 transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
							>
								{generate.loading ? "Working…" : generate.label}
							</button>
							{generate.note != null && (
								<p className="text-center text-[11px] text-slate-500">
									{generate.note}
								</p>
							)}
						</>
					)}

					{debug != null && (
						<details className="group rounded-xl border border-dashed border-slate-800 open:bg-slate-950/40">
							<summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-[11px] font-semibold text-slate-500 marker:content-none">
								<span aria-hidden>🔧</span>
								{debugLabel}
								<span
									aria-hidden
									className="ml-auto text-slate-600 transition-transform group-open:rotate-180"
								>
									▾
								</span>
							</summary>
							<div className="border-t border-slate-800 px-3 py-2 text-[11px] text-slate-500">
								{debug}
							</div>
						</details>
					)}
				</div>
			)}
		</aside>
	);
}
