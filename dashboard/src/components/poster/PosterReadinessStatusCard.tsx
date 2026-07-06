import { AlertTriangle, ShieldAlert } from "lucide-react";
import type { PosterReadinessResponse } from "../../types/posterReadiness";
import {
	posterStatusOperatorLabel,
	shouldShowHighRiskGuidance,
	statusToneClass,
} from "../../poster/posterBuilderUi";

interface PosterReadinessStatusCardProps {
	readiness: PosterReadinessResponse;
}

export default function PosterReadinessStatusCard({
	readiness,
}: PosterReadinessStatusCardProps) {
	const label = posterStatusOperatorLabel(readiness.poster_status);

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5">
			<div className="flex flex-wrap items-start justify-between gap-4">
				<div>
					<p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
						Poster readiness
					</p>
					<h2 className="mt-1 text-lg font-bold text-slate-100">
						{readiness.product_display_name || readiness.product_id}
					</h2>
					<p className="mt-1 font-mono text-[10px] text-slate-500">
						{readiness.product_id}
					</p>
				</div>
				<span
					className={`inline-flex rounded-full border px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.18em] ${statusToneClass(readiness.poster_status)}`}
				>
					{label}
				</span>
			</div>

			<div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
				<Flag label="Generation" value={readiness.generation_allowed ? "Allowed" : "Not allowed"} />
				<Flag
					label="Production"
					value={
						readiness.production_allowed
							? "Allowed"
							: readiness.restricted_generation_required
								? "Restricted"
								: "Not allowed"
					}
				/>
				<Flag label="Preview" value={readiness.preview_allowed ? "Allowed" : "Disabled"} />
				<Flag label="Image tier" value={readiness.image_tier} />
			</div>

			{readiness.next_best_action ? (
				<p className="mt-4 text-sm text-slate-300">
					<span className="font-semibold text-slate-200">Next best action:</span>{" "}
					{readiness.next_best_action}
				</p>
			) : null}

			{readiness.blockers.length > 0 ? (
				<div className="mt-4">
					<p className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
						Blockers
					</p>
					<ul className="mt-2 flex flex-wrap gap-2">
						{readiness.blockers.map((code) => (
							<li
								key={code}
								className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-[10px] font-semibold text-rose-100"
							>
								{code}
							</li>
						))}
					</ul>
				</div>
			) : null}

			{shouldShowHighRiskGuidance(readiness) ? (
				<div className="mt-4 flex gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-50">
					<ShieldAlert className="mt-0.5 shrink-0" size={18} />
					<p>
						This product is not blocked forever. Run safe claim clearance and
						restricted-safe approval before poster generation.
					</p>
				</div>
			) : null}

			{readiness.poster_status === "POSTER_READY_RESTRICTED" ? (
				<div className="mt-4 flex gap-3 rounded-xl border border-amber-500/30 bg-amber-950/40 p-4 text-sm text-amber-100">
					<AlertTriangle className="mt-0.5 shrink-0" size={18} />
					<div>
						<p className="font-semibold">Restricted safe poster rules apply:</p>
						<ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-amber-100/90">
							<li>no cure/treat/heal claim</li>
							<li>no disease claim</li>
							<li>no guaranteed relief</li>
							<li>no before-after</li>
							<li>no fake proof/certificate</li>
							<li>
								use routine, standby, lifestyle, comfort, heritage, portability,
								product-size angles only
							</li>
						</ul>
					</div>
				</div>
			) : null}

			{readiness.notes.length > 0 ? (
				<ul className="mt-4 space-y-1 text-xs text-slate-400">
					{readiness.notes.map((note) => (
						<li key={note}>{note}</li>
					))}
				</ul>
			) : null}
		</section>
	);
}

function Flag({ label, value }: { label: string; value: string }) {
	return (
		<div className="rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2">
			<p className="text-[9px] font-bold uppercase tracking-[0.16em] text-slate-500">
				{label}
			</p>
			<p className="mt-1 text-xs font-semibold text-slate-200">{value}</p>
		</div>
	);
}