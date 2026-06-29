// Shared video-model dropdown — SSOT from GET /api/flow/video-models (patch I3).
// Shows "Veo 3.1 - Quality (100 credits, 8s default)" so the operator sees the cost
// before generating. Value is the model's ui_label (the backend resolves it).

export interface VideoModel {
	key: string;
	ui_label: string;
	default_duration_s: number;
	allowed_durations_s: number[];
	default_cost: number;
}

interface ModelSelectProps {
	models: VideoModel[];
	value: string;
	onChange: (uiLabel: string) => void;
}

// Retired/ghost models that legacy workspace packages may still carry. The backend now
// rejects these, so normalize any incoming package model against the SSOT before use.
const GHOST_MODELS = ["Veo 3.1 - Pro", "Nano Banana 2"];

export function normalizeModel(
	model: string | null | undefined,
	models: VideoModel[],
	fallback = "Veo 3.1 - Lite",
): string {
	if (!model || GHOST_MODELS.includes(model)) return fallback;
	if (models.length === 0) return model; // registry not loaded yet — don't clobber
	return models.some((m) => m.ui_label === model) ? model : fallback;
}

export default function ModelSelect({ models, value, onChange }: ModelSelectProps) {
	return (
		<div className="space-y-3">
			<p className="text-xs font-bold text-slate-400">Generation Model</p>
			<select
				title="Select generation model (mirrors Google Flow)"
				value={value}
				onChange={(e) => onChange(e.target.value)}
				className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-[10px] font-bold text-slate-300 outline-none"
			>
				{models.length === 0 ? (
					<option value={value}>{value || "Loading models…"}</option>
				) : (
					models.map((m) => (
						<option key={m.key} value={m.ui_label}>
							{m.ui_label} ({m.default_cost} credits, {m.default_duration_s}s default)
						</option>
					))
				)}
			</select>
		</div>
	);
}
