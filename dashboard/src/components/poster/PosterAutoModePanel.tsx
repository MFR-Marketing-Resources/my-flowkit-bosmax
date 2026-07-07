import type { PosterBuilderSettings } from "../../api/posterBuilderSettings";
import type { PosterBuilderDraft } from "../../types/posterReadiness";
import type { PosterCopyKit } from "../../types/posterCopyRecommendations";

function SourceBadge({ source, status }: { source: string; status: string }) {
	return (
		<span className="rounded border border-slate-700 px-1.5 py-0.5 text-[9px] uppercase text-slate-400">
			{source} · {status}
		</span>
	);
}

const COPY_FIELDS: { key: keyof PosterBuilderDraft; label: string }[] = [
	{ key: "angle", label: "Angle" },
	{ key: "hook", label: "Hook" },
	{ key: "subhook", label: "Subhook" },
	{ key: "usp_1", label: "USP 1" },
	{ key: "usp_2", label: "USP 2" },
	{ key: "usp_3", label: "USP 3" },
	{ key: "cta", label: "CTA" },
];

export default function PosterAutoModePanel({
	draft,
	onDraftChange,
	settings,
	kits,
	loading,
	error,
	warnings,
	onRefresh,
	onSelectKit,
	onUseKitForPromptDraft,
	onGeneratePromptDraft,
	promptDraftEnabled,
	promptDraftLabel,
	promptDraftLoading,
}: {
	draft: PosterBuilderDraft;
	onDraftChange: (d: PosterBuilderDraft) => void;
	settings: PosterBuilderSettings;
	kits: PosterCopyKit[];
	loading: boolean;
	error: string;
	warnings: string[];
	onRefresh: () => void;
	onSelectKit: (kit: PosterCopyKit) => void;
	onUseKitForPromptDraft: (kit: PosterCopyKit) => void;
	onGeneratePromptDraft: () => void;
	promptDraftEnabled: boolean;
	promptDraftLabel: string;
	promptDraftLoading: boolean;
}) {
	const dropdowns: {
		key: keyof PosterBuilderDraft;
		label: string;
		testid: string;
		options: PosterBuilderSettings["poster_objectives"];
	}[] = [
		{
			key: "poster_objective",
			label: "Objective",
			testid: "poster-objective-select",
			options: settings.poster_objectives,
		},
		{
			key: "poster_type",
			label: "Poster Type",
			testid: "poster-type-select",
			options: settings.poster_types,
		},
		{
			key: "language",
			label: "Language",
			testid: "poster-language-select",
			options: settings.languages,
		},
	];

	const aiReady = settings.ai_provider.configured;

	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5"
			data-testid="poster-auto-mode-panel"
		>
			<h3 className="text-sm font-bold text-slate-100">Auto / Quick Start</h3>
			<p className="mt-1 text-xs text-slate-400">
				Pick the poster settings, edit the copy draft, then generate the prompt
				package. AI suggestions are optional and never auto-approved.
			</p>

			{/* Poster settings — real dropdowns from the cockpit SSOT */}
			<div className="mt-4 grid gap-3 md:grid-cols-3">
				{dropdowns.map(({ key, label, testid, options }) => (
					<label key={key}>
						<span className="text-[10px] font-bold uppercase text-slate-500">{label}</span>
						<select
							data-testid={testid}
							className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200"
							value={String(draft[key])}
							onChange={(e) => onDraftChange({ ...draft, [key]: e.target.value })}
						>
							{options.map((opt) => (
								<option key={opt.id} value={opt.id}>
									{opt.label}
								</option>
							))}
						</select>
					</label>
				))}
			</div>

			{/* Copy draft — ALWAYS visible and editable, independent of recommendations */}
			<div
				className="mt-5 rounded-xl border border-slate-800 bg-slate-900/40 p-4"
				data-testid="poster-copy-draft-fields"
			>
				<h4 className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-300">
					Copy draft
				</h4>
				<p className="mt-1 text-[11px] text-slate-500">
					Edit directly, or apply an AI suggestion below. These fields drive the
					prompt package.
				</p>
				<div className="mt-3 grid gap-3 md:grid-cols-2">
					{COPY_FIELDS.map(({ key, label }) => (
						<label key={key}>
							<span className="text-[10px] font-bold uppercase text-slate-500">{label}</span>
							<input
								data-testid={`copy-field-${key}`}
								className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200"
								value={String(draft[key] ?? "")}
								onChange={(e) => onDraftChange({ ...draft, [key]: e.target.value })}
							/>
						</label>
					))}
				</div>
				<button
					type="button"
					data-testid="auto-generate-prompt-draft"
					disabled={!promptDraftEnabled || promptDraftLoading}
					onClick={onGeneratePromptDraft}
					className="mt-4 rounded-xl border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40"
				>
					{promptDraftLoading ? "Generating prompt draft…" : promptDraftLabel}
				</button>
			</div>

			{/* AI Copy Assist — deliberate, user-initiated candidate generation */}
			<section
				className="mt-5 rounded-xl border border-blue-500/20 bg-blue-950/20 p-4"
				data-testid="poster-ai-copy-assist"
			>
				<div className="flex flex-wrap items-center justify-between gap-2">
					<h4 className="text-[11px] font-bold uppercase tracking-[0.14em] text-blue-100">
						AI Copy Assist
					</h4>
					<span
						className="text-[10px] uppercase text-slate-400"
						data-testid="ai-assist-provider-status"
					>
						{aiReady
							? `AI provider ready · ${settings.ai_provider.lane}`
							: "AI provider unavailable · safe fallback templates only"}
					</span>
				</div>
				<p className="mt-1 text-[11px] text-slate-400">
					Candidates are grounded in product truth + your settings, filtered for
					safety, and marked <em>candidate</em> — never approved automatically.
				</p>
				<button
					type="button"
					data-testid="refresh-poster-recommendations"
					disabled={loading}
					onClick={onRefresh}
					className="mt-3 rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40"
				>
					{loading
						? "Generating suggestions…"
						: kits.length
							? "Regenerate copy suggestions"
							: "Generate copy suggestions"}
				</button>

				{error ? <p className="mt-3 text-sm text-rose-200">{error}</p> : null}
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
									Apply suggestion
								</button>
								<button
									type="button"
									data-testid={`use-kit-prompt-${kit.kit_id}`}
									onClick={() => onUseKitForPromptDraft(kit)}
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
						No AI suggestions loaded. Edit the copy draft above and generate a
						prompt package, use AI Copy Assist, or switch to Manual Expert.
					</p>
				) : null}
			</section>
		</section>
	);
}
