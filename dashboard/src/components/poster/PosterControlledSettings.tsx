import type { PosterBuilderSettings } from "../../api/posterBuilderSettings";
import type { PosterBuilderDraft } from "../../types/posterReadiness";
import type { PosterRecipe } from "../../types/posterRecipe";

/** All controlled (enum-like) poster fields as dropdowns backed by the builder
 * settings SSOT — never free text. Text density is constrained to the selected
 * recipe's allowed_text_density; frame ratio comes from the Flow Mirror aspect
 * list. */
export default function PosterControlledSettings({
	draft,
	onDraftChange,
	settings,
	recipe,
}: {
	draft: PosterBuilderDraft;
	onDraftChange: (d: PosterBuilderDraft) => void;
	settings: PosterBuilderSettings;
	recipe: PosterRecipe | null;
}) {
	const densityOptions = settings.text_density_options.filter(
		(o) =>
			!recipe ||
			recipe.allowed_text_density.length === 0 ||
			recipe.allowed_text_density.includes(o.id),
	);

	const selects: {
		key: keyof PosterBuilderDraft;
		label: string;
		testid: string;
		options: { id: string; label: string }[];
	}[] = [
		{
			key: "poster_objective",
			label: "Objective",
			testid: "ctrl-poster_objective",
			options: settings.poster_objectives,
		},
		{
			key: "poster_type",
			label: "Poster Type",
			testid: "ctrl-poster_type",
			options: settings.poster_types,
		},
		{
			key: "visual_route",
			label: "Visual Route",
			testid: "ctrl-visual_route",
			options: settings.visual_routes,
		},
		{
			key: "human_presence_mode",
			label: "Human Presence",
			testid: "ctrl-human_presence_mode",
			options: settings.human_presence_modes,
		},
		{
			key: "frame_ratio",
			label: "Frame Ratio",
			testid: "ctrl-frame_ratio",
			options: settings.flow_mirror.aspect_ratios.map((a) => ({ id: a, label: a })),
		},
		{
			key: "language",
			label: "Language",
			testid: "ctrl-language",
			options: settings.languages,
		},
		{
			key: "text_density",
			label: "Text Density",
			testid: "ctrl-text_density",
			options: densityOptions,
		},
	];

	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5"
			data-testid="poster-controlled-settings"
		>
			<h3 className="text-sm font-bold text-slate-100">2. Poster settings</h3>
			<p className="mt-1 text-xs text-slate-400">
				Controlled options only — every field is a selector, not free text.
			</p>
			<div className="mt-4 grid gap-3 md:grid-cols-3">
				{selects.map(({ key, label, testid, options }) => (
					<label key={key}>
						<span className="text-[10px] font-bold uppercase text-slate-500">{label}</span>
						<select
							data-testid={testid}
							className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200"
							value={String(draft[key] ?? "")}
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
		</section>
	);
}
