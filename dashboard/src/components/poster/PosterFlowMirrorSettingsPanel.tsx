import { useImageGenSettings } from "../../api/imageGenSettings";
import type { PosterFlowMirrorSettings, PosterFlowVariantCount } from "../../types/posterFlowMirror";
import { isPosterFlowAspectRatio } from "../../types/posterFlowMirror";

export default function PosterFlowMirrorSettingsPanel({
	settings,
	onChange,
	disabled = false,
}: {
	settings: PosterFlowMirrorSettings;
	onChange: (next: PosterFlowMirrorSettings) => void;
	disabled?: boolean;
}) {
	const imageGen = useImageGenSettings();

	const aspects = imageGen.aspect_options.filter(isPosterFlowAspectRatio);
	const counts = imageGen.count_options.filter(
		(n): n is PosterFlowVariantCount => n >= 1 && n <= 4,
	);
	const models = imageGen.models.filter((m) => !m.pending);

	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5"
			data-testid="poster-flow-mirror-settings"
		>
			<h3 className="text-sm font-bold text-slate-100">Flow Mirror Settings</h3>
			<p className="mt-1 text-xs text-slate-400">
				Output control for future gated image / Google Flow handoff. Does not run
				generation.
			</p>

			<div className="mt-4">
				<p className="text-[10px] font-bold uppercase text-slate-500">Aspect Ratio</p>
				<div className="mt-2 flex flex-wrap gap-2">
					{aspects.map((ratio) => (
						<button
							key={ratio}
							type="button"
							data-testid={`flow-aspect-${ratio.replace(":", "-")}`}
							disabled={disabled}
							onClick={() => onChange({ ...settings, aspect_ratio: ratio })}
							className={`rounded-lg border px-3 py-1.5 text-xs font-semibold ${
								settings.aspect_ratio === ratio
									? "border-blue-500/50 bg-blue-600/20 text-blue-100"
									: "border-slate-700 text-slate-300"
							}`}
						>
							{ratio}
						</button>
					))}
				</div>
			</div>

			<div className="mt-4">
				<p className="text-[10px] font-bold uppercase text-slate-500">Count</p>
				<div className="mt-2 flex flex-wrap gap-2">
					{counts.map((n) => (
						<button
							key={n}
							type="button"
							data-testid={`flow-count-${n}x`}
							disabled={disabled}
							onClick={() => onChange({ ...settings, count: n })}
							className={`rounded-lg border px-3 py-1.5 text-xs font-semibold ${
								settings.count === n
									? "border-blue-500/50 bg-blue-600/20 text-blue-100"
									: "border-slate-700 text-slate-300"
							}`}
						>
							{n}x
						</button>
					))}
				</div>
			</div>

			<label className="mt-4 block max-w-md">
				<span className="text-[10px] font-bold uppercase text-slate-500">Image Model</span>
				<select
					data-testid="flow-image-model"
					disabled={disabled}
					className="mt-1 w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-sm text-slate-200"
					value={settings.image_model}
					onChange={(e) => onChange({ ...settings, image_model: e.target.value })}
				>
					{models.map((m) => (
						<option key={m.key} value={m.label}>
							{m.label}
						</option>
					))}
				</select>
			</label>
		</section>
	);
}