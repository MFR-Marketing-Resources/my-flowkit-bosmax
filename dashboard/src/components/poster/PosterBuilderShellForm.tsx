import type { PosterBuilderDraft } from "../../types/posterReadiness";
import type { PosterBuilderShellMode } from "../../poster/posterBuilderUi";

interface PosterBuilderShellFormProps {
	draft: PosterBuilderDraft;
	onChange: (draft: PosterBuilderDraft) => void;
	mode: PosterBuilderShellMode;
	promptDraftEnabled: boolean;
	promptDraftLabel: string;
	onPromptDraft: () => void;
	promptDraftLoading?: boolean;
	imageGenerateLabel: string;
	/** When true, show Manual Expert heading (manual working mode). */
	manualExpert?: boolean;
}

const FIELDS: { key: keyof PosterBuilderDraft; label: string; multiline?: boolean }[] = [
	{ key: "poster_objective", label: "Poster Objective" },
	{ key: "poster_type", label: "Poster Type" },
	{ key: "visual_route", label: "Visual Route" },
	{ key: "human_presence_mode", label: "Human Presence Mode" },
	{ key: "frame_ratio", label: "Frame Ratio" },
	{ key: "language", label: "Language" },
	{ key: "text_density", label: "Text Density" },
	{ key: "angle", label: "Angle" },
	{ key: "hook", label: "Hook" },
	{ key: "subhook", label: "Subhook" },
	{ key: "usp_1", label: "USP 1" },
	{ key: "usp_2", label: "USP 2" },
	{ key: "usp_3", label: "USP 3" },
	{ key: "cta", label: "CTA" },
	{ key: "operator_notes", label: "Notes / Operator Instruction", multiline: true },
];

export default function PosterBuilderShellForm({
	draft,
	onChange,
	mode,
	promptDraftEnabled,
	promptDraftLabel,
	onPromptDraft,
	promptDraftLoading = false,
	imageGenerateLabel,
	manualExpert = false,
}: PosterBuilderShellFormProps) {
	const editable = mode === "full" || mode === "restricted" || mode === "preview";
	const previewOnly = mode === "preview";

	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5"
			data-testid={manualExpert ? "poster-manual-expert-panel" : "poster-builder-shell-form"}
		>
			<div className="flex flex-wrap items-center justify-between gap-3">
				<h3 className="text-sm font-bold uppercase tracking-[0.16em] text-slate-200">
					{manualExpert ? "Manual Expert Mode" : "Poster builder shell"}
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

			<div className="mt-4 grid gap-3 md:grid-cols-2">
				{FIELDS.map(({ key, label, multiline }) => (
					<label key={key} className={multiline ? "md:col-span-2" : ""}>
						<span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
							{label}
						</span>
						{multiline ? (
							<textarea
								className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
								rows={3}
								value={String(draft[key] ?? "")}
								disabled={!editable}
								onChange={(e) => onChange({ ...draft, [key]: e.target.value })}
							/>
						) : (
							<input
								className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
								value={String(draft[key] ?? "")}
								disabled={!editable}
								onChange={(e) => onChange({ ...draft, [key]: e.target.value })}
							/>
						)}
					</label>
				))}
			</div>

			<div className="mt-4 flex flex-wrap gap-3">
				<button
					type="button"
					data-testid="generate-prompt-draft-button"
					disabled={!promptDraftEnabled || promptDraftLoading}
					title={promptDraftLabel}
					onClick={onPromptDraft}
					className="rounded-xl border border-blue-500/50 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase tracking-[0.12em] text-blue-100 disabled:cursor-not-allowed disabled:opacity-40"
				>
					{promptDraftLoading ? "Generating…" : promptDraftLabel}
				</button>
				<button
					type="button"
					data-testid="generate-poster-button"
					disabled
					title={imageGenerateLabel}
					className="cursor-not-allowed rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-bold uppercase tracking-[0.12em] text-slate-400"
				>
					Generate poster (image)
				</button>
				<span className="self-center text-xs text-slate-500">{imageGenerateLabel}</span>
			</div>
		</section>
	);
}