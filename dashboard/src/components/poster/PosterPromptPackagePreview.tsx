import type { CompositionPlan } from "../../types/posterCompositionPlan";
import type { PosterPromptDraftResponse } from "../../types/posterPromptDraft";
import CompositionPlanSummary from "./CompositionPlanSummary";

interface PosterPromptPackagePreviewProps {
	package_: PosterPromptDraftResponse | null;
	error?: string;
}

export default function PosterPromptPackagePreview({
	package_,
	error,
}: PosterPromptPackagePreviewProps) {
	if (error) {
		return (
			<section
				className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-5"
				data-testid="poster-prompt-draft-error"
			>
				<h3 className="text-sm font-bold text-rose-100">Prompt draft error</h3>
				<p className="mt-2 whitespace-pre-wrap text-sm text-rose-100/90">{error}</p>
			</section>
		);
	}
	if (!package_) return null;

	return (
		<section
			className="rounded-2xl border border-emerald-500/30 bg-emerald-950/20 p-5"
			data-testid="poster-prompt-package-preview"
		>
			<div className="flex flex-wrap items-center gap-2">
				<h3 className="text-sm font-bold text-emerald-100">Final prompt package</h3>
				<span className="rounded-full border border-slate-600 px-2 py-0.5 text-[9px] font-bold uppercase text-slate-300">
					{package_.prompt_package_status}
				</span>
				{package_.restricted_mode ? (
					<span className="rounded-full border border-amber-500/40 px-2 py-0.5 text-[9px] font-bold uppercase text-amber-100">
						Restricted
					</span>
				) : null}
			</div>
			{package_.validation_warnings?.length ? (
				<div
					data-testid="poster-copy-review-only"
					className="mt-3 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100"
				>
					<span className="font-bold uppercase">Review only — </span>
					copy is not an approved Copy Set ({package_.validation_warnings.join(", ")}).
					Bind an approved Copy Set or explicitly confirm fallback before production.
				</div>
			) : null}
			<div className="mt-3">
				<CompositionPlanSummary
					plan={(package_.composition_plan ?? null) as CompositionPlan | null}
				/>
			</div>
			{package_.poster_prompt ? (
				<>
					<p className="mt-3 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
						Poster prompt
					</p>
					<pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-xs text-slate-300">
						{package_.poster_prompt}
					</pre>
					<p className="mt-3 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
						Negative prompt
					</p>
					<pre className="mt-1 max-h-24 overflow-auto text-xs text-slate-400">
						{package_.negative_prompt}
					</pre>
				</>
			) : (
				<p className="mt-2 text-sm text-slate-400">
					No poster prompt assembled — resolve blockers or repair actions first.
				</p>
			)}
			<p className="mt-3 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
				Package JSON
			</p>
			<pre className="mt-1 max-h-40 overflow-auto text-[10px] text-slate-500">
				{JSON.stringify(package_, null, 2)}
			</pre>
		</section>
	);
}
