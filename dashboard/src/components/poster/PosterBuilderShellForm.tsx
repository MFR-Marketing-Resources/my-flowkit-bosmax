import type { PosterBuilderDraft } from "../../types/posterReadiness";
import type { PosterBuilderShellMode } from "../../poster/posterBuilderUi";

interface PosterBuilderShellFormProps {
	draft: PosterBuilderDraft;
	onChange: (draft: PosterBuilderDraft) => void;
	mode: PosterBuilderShellMode;
	generateButtonLabel: string;
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
	generateButtonLabel,
}: PosterBuilderShellFormProps) {
	const editable = mode === "full" || mode === "restricted" || mode === "preview";
	const previewOnly = mode === "preview";

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5">
			<div className="flex flex-wrap items-center justify-between gap-3">
				<h3 className="text-sm font-bold uppercase tracking-[0.16em] text-slate-200">
					Poster builder shell
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
								value={draft[key]}
								disabled={!editable}
								onChange={(e) => onChange({ ...draft, [key]: e.target.value })}
							/>
						) : (
							<input
								className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
								value={draft[key]}
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
					disabled
					title={generateButtonLabel}
					className="cursor-not-allowed rounded-xl border border-slate-700 bg-slate-800 px-4 py-2 text-xs font-bold uppercase tracking-[0.12em] text-slate-400"
				>
					Generate poster
				</button>
				<span className="self-center text-xs text-slate-500">{generateButtonLabel}</span>
			</div>
		</section>
	);
}