import {
	INTELLIGENCE_STAGES,
	INTELLIGENCE_STAGE_LABEL,
	type IntelligenceStage,
} from "../../api/reporting";

/**
 * Progress breakdown + seam filters for the `missing_intelligence` drill-down.
 *
 * WHY THIS EXISTS
 * The headline predicate is "no approved Product Intelligence snapshot". That is the
 * truthful definition and it is NOT redefined to make progress look better. But because
 * only a HUMAN approval creates a snapshot, every machine-executable step — seeding a
 * review draft, rewriting a blocked claim, queueing for review — moves the headline by
 * zero. Without this panel the work is invisible and the bucket looks static.
 *
 * The counts come from the server over the WHOLE filtered cohort, never from the page.
 */
export interface IntelligenceStagePanelProps {
	breakdown?: Partial<Record<IntelligenceStage, number>>;
	stage: IntelligenceStage | "";
	risk: string;
	copyBlocked: string;
	onStage: (v: IntelligenceStage | "") => void;
	onRisk: (v: string) => void;
	onCopyBlocked: (v: string) => void;
}

const TONE: Record<IntelligenceStage, string> = {
	NO_DRAFT: "border-slate-600/50 text-slate-300",
	CLAIM_BLOCKED: "border-red-500/40 text-red-300",
	CLAIM_REVIEW_REQUIRED: "border-amber-500/40 text-amber-300",
	DRAFT_INCOMPLETE: "border-amber-400/30 text-amber-200",
	READY_FOR_REVIEW: "border-sky-500/40 text-sky-300",
	APPROVED_SNAPSHOT: "border-emerald-500/40 text-emerald-300",
};

const SELECT =
	"rounded-lg border border-slate-700 bg-slate-900/70 px-2 py-1 text-xs text-slate-200";

export function IntelligenceStagePanel({
	breakdown,
	stage,
	risk,
	copyBlocked,
	onStage,
	onRisk,
	onCopyBlocked,
}: IntelligenceStagePanelProps) {
	const total = INTELLIGENCE_STAGES.reduce(
		(sum, s) => sum + (breakdown?.[s] ?? 0),
		0,
	);
	return (
		<div className="mb-4 space-y-3" data-testid="intelligence-stage-panel">
			<p className="text-[11px] leading-relaxed text-slate-500">
				The headline counts products with{" "}
				<span className="font-semibold text-slate-300">
					no approved snapshot
				</span>{" "}
				— only a human approval clears it. These stages show how far preparation has
				already progressed inside that same cohort.
			</p>

			<div className="flex flex-wrap gap-2">
				{INTELLIGENCE_STAGES.map((s) => {
					const n = breakdown?.[s] ?? 0;
					const active = stage === s;
					return (
						<button
							key={s}
							type="button"
							data-testid={`stage-chip-${s}`}
							aria-pressed={active}
							onClick={() => onStage(active ? "" : s)}
							className={`rounded-lg border px-3 py-1.5 text-left text-xs transition ${TONE[s]} ${
								active ? "bg-slate-100/10 ring-1 ring-sky-400/50" : "bg-slate-900/40"
							}`}
						>
							<span className="font-bold tabular-nums">{n}</span>{" "}
							<span className="text-[11px]">{INTELLIGENCE_STAGE_LABEL[s]}</span>
						</button>
					);
				})}
			</div>

			<div className="flex flex-wrap items-center gap-2">
				<label className="text-[11px] text-slate-500">
					Stage{" "}
					<select
						className={SELECT}
						data-testid="filter-stage"
						value={stage}
						onChange={(e) => onStage(e.target.value as IntelligenceStage | "")}
					>
						<option value="">All</option>
						{INTELLIGENCE_STAGES.map((s) => (
							<option key={s} value={s}>
								{INTELLIGENCE_STAGE_LABEL[s]}
							</option>
						))}
					</select>
				</label>
				<label className="text-[11px] text-slate-500">
					Claim risk{" "}
					<select
						className={SELECT}
						data-testid="filter-claim-risk"
						value={risk}
						onChange={(e) => onRisk(e.target.value)}
					>
						<option value="">All</option>
						<option value="LOW">LOW</option>
						<option value="MEDIUM">MEDIUM</option>
						<option value="HIGH">HIGH</option>
					</select>
				</label>
				<label className="text-[11px] text-slate-500">
					Copy blocked{" "}
					<select
						className={SELECT}
						data-testid="filter-copy-blocked"
						value={copyBlocked}
						onChange={(e) => onCopyBlocked(e.target.value)}
					>
						<option value="">All</option>
						<option value="yes">Yes</option>
						<option value="no">No</option>
					</select>
				</label>
				<span className="text-[11px] text-slate-500" data-testid="stage-total">
					{total.toLocaleString()} in breakdown
				</span>
			</div>
		</div>
	);
}

export default IntelligenceStagePanel;
