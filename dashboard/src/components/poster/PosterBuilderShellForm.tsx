import type {
	PosterBuilderSettings,
	PosterSettingOption,
} from "../../api/posterBuilderSettings";
import type { PosterBuilderDraft } from "../../types/posterReadiness";
import type { PosterBuilderShellMode } from "../../poster/posterBuilderUi";

interface PosterBuilderShellFormProps {
	draft: PosterBuilderDraft;
	onChange: (draft: PosterBuilderDraft) => void;
	/** DB-backed option lists (same cockpit SSOT the Auto / Quick Start panel uses). */
	settings: PosterBuilderSettings;
	mode: PosterBuilderShellMode;
	promptDraftEnabled: boolean;
	promptDraftLabel: string;
	onPromptDraft: () => void;
	promptDraftLoading?: boolean;
	imageGenerateLabel: string;
	/** When true, show Manual Expert heading (manual working mode). */
	manualExpert?: boolean;
}

type FieldKind = "select" | "text" | "multiline";

const FIELDS: { key: keyof PosterBuilderDraft; label: string; kind: FieldKind }[] = [
	{ key: "poster_objective", label: "Poster Objective", kind: "select" },
	{ key: "poster_type", label: "Poster Type", kind: "select" },
	{ key: "visual_route", label: "Visual Route", kind: "select" },
	{ key: "human_presence_mode", label: "Human Presence Mode", kind: "select" },
	{ key: "frame_ratio", label: "Frame Ratio", kind: "select" },
	{ key: "language", label: "Language", kind: "select" },
	{ key: "text_density", label: "Text Density", kind: "select" },
	{ key: "angle", label: "Angle", kind: "text" },
	{ key: "hook", label: "Hook", kind: "text" },
	{ key: "subhook", label: "Subhook", kind: "text" },
	{ key: "usp_1", label: "USP 1", kind: "text" },
	{ key: "usp_2", label: "USP 2", kind: "text" },
	{ key: "usp_3", label: "USP 3", kind: "text" },
	{ key: "cta", label: "CTA", kind: "text" },
	{ key: "operator_notes", label: "Notes / Operator Instruction", kind: "multiline" },
];

const INPUT_CLASS =
	"mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200 disabled:opacity-50";

export default function PosterBuilderShellForm({
	draft,
	onChange,
	settings,
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

	// Every settings field is driven by the same cockpit SSOT option lists as the
	// Auto / Quick Start panel — Manual Expert must never diverge into free text.
	const selectOptions: Partial<
		Record<keyof PosterBuilderDraft, PosterSettingOption[]>
	> = {
		poster_objective: settings.poster_objectives,
		poster_type: settings.poster_types,
		visual_route: settings.visual_routes,
		human_presence_mode: settings.human_presence_modes,
		language: settings.languages,
		text_density: settings.text_density_options,
		frame_ratio: settings.flow_mirror.aspect_ratios.map((ratio) => ({
			id: ratio,
			label: ratio,
		})),
	};

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
				{FIELDS.map(({ key, label, kind }) => {
					const options = selectOptions[key];
					return (
						<label key={key} className={kind === "multiline" ? "md:col-span-2" : ""}>
							<span className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
								{label}
							</span>
							{options ? (
								<select
									data-testid={`poster-manual-${key}-select`}
									className={INPUT_CLASS}
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
							) : kind === "multiline" ? (
								<textarea
									data-testid={`poster-manual-${key}-input`}
									className={INPUT_CLASS}
									rows={3}
									value={String(draft[key] ?? "")}
									disabled={!editable}
									onChange={(e) => onChange({ ...draft, [key]: e.target.value })}
								/>
							) : (
								<input
									data-testid={`poster-manual-${key}-input`}
									className={INPUT_CLASS}
									value={String(draft[key] ?? "")}
									disabled={!editable}
									onChange={(e) => onChange({ ...draft, [key]: e.target.value })}
								/>
							)}
						</label>
					);
				})}
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
