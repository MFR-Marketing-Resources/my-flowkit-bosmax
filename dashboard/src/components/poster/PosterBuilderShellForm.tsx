import type {
	PosterBuilderSettings,
	PosterSettingOption,
} from "../../api/posterBuilderSettings";
import type { PosterBuilderDraft } from "../../types/posterReadiness";
import {
	POSTER_COPY_LIMITS,
	type PosterBuilderShellMode,
	missingPosterCopyFields,
	overLimitPosterCopyFields,
} from "../../poster/posterBuilderUi";

interface PosterBuilderShellFormProps {
	draft: PosterBuilderDraft;
	onChange: (draft: PosterBuilderDraft) => void;
	mode: PosterBuilderShellMode;
	settings: PosterBuilderSettings;
	promptDraftEnabled: boolean;
	promptDraftLabel: string;
	onPromptDraft: () => void;
	promptDraftLoading?: boolean;
	imageGenerateLabel: string;
	/** When true, show Manual Expert heading (manual working mode). */
	manualExpert?: boolean;
}

// Controlled (enum-like) fields — rendered as dropdowns backed by the settings
// SSOT, NEVER free text.
const COPY_FIELDS: {
	key: keyof PosterBuilderDraft;
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

export default function PosterBuilderShellForm({
	draft,
	onChange,
	mode,
	settings,
	promptDraftEnabled,
	promptDraftLabel,
	onPromptDraft,
	promptDraftLoading = false,
	imageGenerateLabel,
	manualExpert = false,
}: PosterBuilderShellFormProps) {
	const editable = mode === "full" || mode === "restricted" || mode === "preview";
	const previewOnly = mode === "preview";
	const missingCopy = missingPosterCopyFields(draft);
	const overLimit = overLimitPosterCopyFields(draft);

	const frameRatioOptions: PosterSettingOption[] =
		settings.flow_mirror.aspect_ratios.map((a) => ({ id: a, label: a }));
	const enumFields: {
		key: keyof PosterBuilderDraft;
		label: string;
		options: PosterSettingOption[];
	}[] = [
		{ key: "poster_objective", label: "Poster Objective", options: settings.poster_objectives },
		{ key: "poster_type", label: "Poster Type", options: settings.poster_types },
		{ key: "visual_route", label: "Visual Route", options: settings.visual_routes },
		{ key: "human_presence_mode", label: "Human Presence Mode", options: settings.human_presence_modes },
		{ key: "frame_ratio", label: "Frame Ratio", options: frameRatioOptions },
		{ key: "language", label: "Language", options: settings.languages },
		{ key: "text_density", label: "Text Density", options: settings.text_density_options },
	];

	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5"
			data-testid={manualExpert ? "poster-manual-expert-panel" : "poster-builder-shell-form"}
		>
			<div className="flex flex-wrap items-center justify-between gap-3">
				<h3 className="text-sm font-bold uppercase tracking-[0.16em] text-slate-200">
					{manualExpert ? "Manual Expert Mode (advanced / legacy)" : "Poster builder shell"}
				</h3>
				{mode === "restricted" ? (
					<span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[9px] font-bold uppercase text-amber-100">
						Restricted mode
					</span>
				) : null}
				{previewOnly ? (
					<span className="rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-1 text-[9px] font-bold uppercase text-sky-100">
						Preview / diagnostic
					</span>
				) : null}
			</div>

			{/* Controlled fields — dropdowns, not free text */}
			<div className="mt-4 grid gap-3 md:grid-cols-2">
				{enumFields.map(({ key, label, options }) => (
					<label key={key}>
						<span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
							{label}
						</span>
						<select
							data-testid={`shell-select-${key}`}
							className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
							value={String(draft[key] ?? "")}
							disabled={!editable}
							onChange={(e) => onChange({ ...draft, [key]: e.target.value })}
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

			{/* Copy fields — free text is correct here (headline/USP/CTA content) */}
			<div className="mt-3 grid gap-3 md:grid-cols-2">
				{COPY_FIELDS.map(({ key, label, maxLength }) => {
					const len = String(draft[key] ?? "").trim().length;
					const over = len > maxLength;
					return (
						<label key={key}>
							<div className="flex items-center justify-between">
								<span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
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
								className={`mt-1 w-full rounded-lg border bg-slate-900 px-3 py-2 text-sm text-slate-200 disabled:opacity-50 ${over ? "border-rose-500/60" : "border-slate-800"}`}
								value={String(draft[key] ?? "")}
								maxLength={maxLength}
								disabled={!editable}
								onChange={(e) => onChange({ ...draft, [key]: e.target.value })}
							/>
						</label>
					);
				})}
				<label className="md:col-span-2">
					<span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
						Notes / Operator Instruction
					</span>
					<textarea
						className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
						rows={3}
						value={String(draft.operator_notes ?? "")}
						disabled={!editable}
						onChange={(e) => onChange({ ...draft, operator_notes: e.target.value })}
					/>
				</label>
			</div>

			{promptDraftEnabled && missingCopy.length > 0 ? (
				<p
					data-testid="poster-copy-required-hint"
					className="mt-4 text-[11px] text-amber-300"
				>
					Isi dulu medan wajib: <strong>{missingCopy.join(", ")}</strong> sebelum
					menjana prompt draft.
				</p>
			) : null}
			{promptDraftEnabled && overLimit.length > 0 ? (
				<p
					data-testid="poster-copy-overlimit-hint"
					className="mt-4 text-[11px] text-rose-300"
				>
					Terlalu panjang untuk poster: <strong>{overLimit.join(", ")}</strong>.
					Pendekkan ayat supaya muat.
				</p>
			) : null}
			<div className="mt-4 flex flex-wrap gap-3">
				<button
					type="button"
					data-testid="generate-prompt-draft-button"
					disabled={
						!promptDraftEnabled ||
						promptDraftLoading ||
						missingCopy.length > 0 ||
						overLimit.length > 0
					}
					title={
						missingCopy.length > 0
							? `Isi dulu: ${missingCopy.join(", ")}`
							: overLimit.length > 0
								? `Terlalu panjang: ${overLimit.join(", ")}`
								: promptDraftLabel
					}
					onClick={onPromptDraft}
					className="rounded-xl border border-blue-500/50 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase tracking-[0.12em] text-blue-100 disabled:cursor-not-allowed disabled:opacity-40"
				>
					{promptDraftLoading ? "Generating…" : promptDraftLabel}
				</button>
				<span className="self-center text-xs text-slate-500">{imageGenerateLabel}</span>
			</div>
		</section>
	);
}
