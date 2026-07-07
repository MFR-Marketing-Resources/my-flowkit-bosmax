import type { PosterBuilderDraft } from "../../types/posterReadiness";
import type { PosterCopyKit } from "../../types/posterCopyRecommendations";

function SourceBadge({ source, status }: { source: string; status: string }) {
	return (
		<span className="rounded border border-slate-700 px-1.5 py-0.5 text-[9px] uppercase text-slate-400">
			{source} · {status}
		</span>
	);
}

export default function PosterAutoModePanel({
	draft,
	onDraftChange,
	kits,
	loading,
	error,
	warnings,
	onRefresh,
	onSelectKit,
	onUseForPromptDraft,
	promptDraftLoading,
}: {
	draft: PosterBuilderDraft;
	onDraftChange: (d: PosterBuilderDraft) => void;
	kits: PosterCopyKit[];
	loading: boolean;
	error: string;
	warnings: string[];
	onRefresh: () => void;
	onSelectKit: (kit: PosterCopyKit) => void;
	onUseForPromptDraft: () => void;
	promptDraftLoading: boolean;
}) {
	const miniFields: { key: keyof PosterBuilderDraft; label: string }[] = [
		{ key: "poster_objective", label: "Objective" },
		{ key: "poster_type", label: "Poster Type" },
		{ key: "frame_ratio", label: "Frame Ratio" },
		{ key: "language", label: "Language" },
	];

	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5"
			data-testid="poster-auto-mode-panel"
		>
			<h3 className="text-sm font-bold text-slate-100">Auto / Quick Start</h3>
			<p className="mt-1 text-xs text-slate-400">
				Fill minimum fields, then refresh recommendations. Kits are never auto-approved.
			</p>

			<div className="mt-4 grid gap-3 md:grid-cols-2">
				{miniFields.map(({ key, label }) => (
					<label key={key}>
						<span className="text-[10px] font-bold uppercase text-slate-500">{label}</span>
						<input
							className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200"
							value={draft[key]}
							onChange={(e) => onDraftChange({ ...draft, [key]: e.target.value })}
						/>
					</label>
				))}
			</div>

			<button
				type="button"
				data-testid="refresh-poster-recommendations"
				disabled={loading}
				onClick={onRefresh}
				className="mt-4 rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40"
			>
				{loading ? "Loading recommendations…" : "Generate / Refresh recommendations"}
			</button>

			{error ? (
				<p className="mt-3 text-sm text-rose-200">{error}</p>
			) : null}
			{warnings.map((w) => (
				<p key={w} className="mt-2 text-xs text-amber-200/90">
					{w}
				</p>
			))}

			<div className="mt-4 grid gap-3 md:grid-cols-2">
				{kits.map((kit) => (
					<article
						key={kit.kit_id}
						data-testid="poster-recommendation-card"
						className="rounded-xl border border-slate-800 bg-slate-900/50 p-4"
					>
						<div className="flex flex-wrap gap-2">
							<SourceBadge source={kit.source} status={kit.status} />
						</div>
						<p className="mt-2 text-xs text-slate-500">Angle: {kit.angle}</p>
						<p className="mt-1 text-sm font-semibold text-slate-100">{kit.hook}</p>
						<p className="text-xs text-slate-400">{kit.subhook}</p>
						<ul className="mt-2 list-inside list-disc text-xs text-slate-400">
							{[kit.usp_1, kit.usp_2, kit.usp_3].filter(Boolean).map((u) => (
								<li key={u}>{u}</li>
							))}
						</ul>
						<p className="mt-2 text-xs text-slate-300">CTA: {kit.cta}</p>
						<p className="text-[10px] text-slate-500">Visual: {kit.visual_route}</p>
						{kit.safety_notes?.length ? (
							<p className="mt-2 text-[10px] text-amber-200/80">
								{kit.safety_notes.join(" ")}
							</p>
						) : null}
						<div className="mt-3 flex flex-wrap gap-2">
							<button
								type="button"
								data-testid={`select-kit-${kit.kit_id}`}
								onClick={() => onSelectKit(kit)}
								className="rounded-lg border border-slate-600 px-2 py-1 text-[10px] font-bold uppercase text-slate-200"
							>
								Select kit
							</button>
							<button
								type="button"
								onClick={() => {
									onSelectKit(kit);
									onUseForPromptDraft();
								}}
								disabled={promptDraftLoading}
								className="rounded-lg border border-blue-500/40 px-2 py-1 text-[10px] font-bold uppercase text-blue-100"
							>
								Use for prompt draft
							</button>
						</div>
					</article>
				))}
			</div>
			{kits.length === 0 && !loading ? (
				<p className="mt-4 text-sm text-slate-500">
					No kits yet — adjust inputs and refresh, or switch to Manual Expert.
				</p>
			) : null}
		</section>
	);
}