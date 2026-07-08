import type { PosterBuilderSettings } from "../../api/posterBuilderSettings";
import type { PosterBuilderDraft } from "../../types/posterReadiness";
import type { PosterCopyKit } from "../../types/posterCopyRecommendations";
import {
	POSTER_COPY_LIMITS,
	missingPosterCopyFields,
	overLimitPosterCopyFields,
} from "../../poster/posterBuilderUi";

function SourceBadge({ source, status }: { source: string; status: string }) {
	return (
		<span className="rounded border border-slate-700 px-1.5 py-0.5 text-[9px] uppercase text-slate-400">
			{source} · {status}
		</span>
	);
}

const COPY_FIELDS: {
	key: keyof typeof POSTER_COPY_LIMITS;
	label: string;
	maxLength: number;
}[] = [
	{ key: "hook", label: "Hook", maxLength: POSTER_COPY_LIMITS.hook },
	{ key: "subhook", label: "Subhook", maxLength: POSTER_COPY_LIMITS.subhook },
	{ key: "usp_1", label: "USP 1", maxLength: POSTER_COPY_LIMITS.usp_1 },
	{ key: "usp_2", label: "USP 2", maxLength: POSTER_COPY_LIMITS.usp_2 },
	{ key: "usp_3", label: "USP 3", maxLength: POSTER_COPY_LIMITS.usp_3 },
	{ key: "cta", label: "CTA", maxLength: POSTER_COPY_LIMITS.cta },
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
	const missingCopy = missingPosterCopyFields(draft);
	const overLimit = overLimitPosterCopyFields(draft);

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
					{COPY_FIELDS.map(({ key, label, maxLength }) => {
						const len = String(draft[key] ?? "").trim().length;
						const over = len > maxLength;
						return (
							<label key={key}>
								<div className="flex items-center justify-between">
									<span className="text-[10px] font-bold uppercase text-slate-500">
										{label}
									</span>
									<span
										data-testid={`copy-count-${key}`}
										className={`text-[9px] ${over ? "text-rose-300" : "text-slate-500"}`}
									>
										{len}/{maxLength}
									</span>
								</div>
								<input
									data-testid={`copy-field-${key}`}
									maxLength={maxLength}
									className={`mt-1 w-full rounded-lg border bg-slate-900 px-3 py-2 text-sm text-slate-200 ${over ? "border-rose-500/60" : "border-slate-800"}`}
									value={String(draft[key] ?? "")}
									onChange={(e) =>
										onDraftChange({
											...draft,
											[key]: e.target.value,
											// A manual copy edit invalidates any approved binding: the copy is
											// now operator-authored (non-approved) and re-enters governance.
											copy_source: "manual",
											copy_set_id: "",
											copy_fallback_confirmed: false,
										})
									}
								/>
							</label>
						);
					})}
				</div>
				{draft.copy_source === "APPROVED_COPY_SET" ? (
					<p
						data-testid="poster-copy-grounded"
						className="mt-3 text-[11px] text-emerald-300"
					>
						Copy is bound to an approved Copy Set — production-eligible.
					</p>
				) : (
					<label
						data-testid="poster-copy-fallback-confirm"
						className="mt-3 flex items-center gap-2 text-[11px] text-amber-200"
					>
						<input
							type="checkbox"
							checked={draft.copy_fallback_confirmed}
							onChange={(e) =>
								onDraftChange({ ...draft, copy_fallback_confirmed: e.target.checked })
							}
						/>
						<span>
							This copy is not an approved Copy Set. Without an approved set the prompt
							draft is review-only — tick to explicitly confirm fallback copy.
						</span>
					</label>
				)}
				{promptDraftEnabled && missingCopy.length > 0 ? (
					<p
						data-testid="poster-copy-required-hint"
						className="mt-3 text-[11px] text-amber-300"
					>
						Isi dulu: <strong>{missingCopy.join(", ")}</strong>. Taip terus di medan
						Copy draft di atas, atau tekan <em>Apply suggestion</em> pada satu cadangan
						AI di bawah untuk mengisinya.
					</p>
				) : null}
				{promptDraftEnabled && overLimit.length > 0 ? (
					<p
						data-testid="poster-copy-overlimit-hint"
						className="mt-3 text-[11px] text-rose-300"
					>
						Terlalu panjang untuk poster: <strong>{overLimit.join(", ")}</strong>.
						Pendekkan ayat supaya muat — copy poster mesti ringkas, bukan panjang
						macam copywriting video.
					</p>
				) : null}
				<button
					type="button"
					data-testid="auto-generate-prompt-draft"
					disabled={
						!promptDraftEnabled ||
						promptDraftLoading ||
						missingCopy.length > 0 ||
						overLimit.length > 0
					}
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
								{kit.formula_validated ? (
									<span
										data-testid={`kit-formula-validated-${kit.kit_id}`}
										className="rounded border border-emerald-500/40 px-1.5 py-0.5 text-[9px] uppercase text-emerald-300"
									>
										Formula ✓
									</span>
								) : null}
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
