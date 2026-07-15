import { useEffect, useState } from "react";

import {
	getCameraPresetRecommendationForProduct,
	type CameraPreset,
	type CameraPresetRecommendation,
} from "../../api/creativeIntelligence";

/**
 * Read-only "Recommended Camera / Video Presets" card (Creative Intelligence —
 * Round 3). Shows the block-content -> preset mapping (HOOK / BODY / CTA / TRANS)
 * with each named preset's shot type, distance + angle, and movement, plus the
 * universal camera vocabulary counts. Reference/preview only — this card never
 * generates, approves, writes product camera columns, or feeds generation.
 */
export default function RecommendedCameraPresetsCard({ productId }: { productId: string }) {
	const [data, setData] = useState<CameraPresetRecommendation | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");

	useEffect(() => {
		let active = true;
		setLoading(true);
		setError("");
		setData(null);
		void getCameraPresetRecommendationForProduct(productId)
			.then((response) => {
				if (active) setData(response);
			})
			.catch((cause) => {
				if (active) setError(cause instanceof Error ? cause.message : "Failed to load camera presets.");
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [productId]);

	const recs = data?.block_recommendations ?? [];
	const lib = data?.library;

	const presetLine = (p?: CameraPreset | null) =>
		p ? `${p.preset_code} · ${p.shot_type ?? ""} · ${p.distance_angle ?? ""} · ${p.movement ?? ""}` : "";

	return (
		<div
			data-testid="recommended-camera-presets-card"
			className="rounded border border-amber-500/30 bg-amber-500/5 p-3"
		>
			<div className="flex items-center justify-between gap-2">
				<div className="text-sm font-bold text-amber-100">Recommended Camera / Video Presets</div>
				{data && (
					<span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
						cluster: {data.cluster} · {data.cluster_source}
					</span>
				)}
			</div>
			<p className="mt-1 text-[10px] leading-relaxed text-slate-400">
				Read-only creative suggestion — shot distance, camera angle, movement, e-commerce
				shot type, and named HOOK / BODY / CTA / TRANS presets mapped by block purpose.
				Reference only — nothing is generated, approved, written to product camera settings,
				or sent to generation here.
			</p>

			{loading ? (
				<p className="mt-3 text-xs text-slate-400">Loading camera presets…</p>
			) : error ? (
				<p className="mt-3 text-xs font-medium text-red-300" role="alert">
					Unable to load camera presets: {error}
				</p>
			) : recs.length === 0 ? (
				<p className="mt-3 text-xs text-slate-400" data-testid="recommended-camera-presets-empty">
					No camera / video presets available.
				</p>
			) : (
				<>
					<ul className="mt-3 space-y-2" data-testid="recommended-camera-presets-list">
						{recs.slice(0, 6).map((rec) => (
							<li
								key={`${rec.block_purpose}-${rec.content_type}`}
								className="rounded border border-slate-700/60 bg-slate-900/40 p-2 text-xs text-slate-200"
							>
								<div className="flex items-center justify-between gap-2">
									<span className="text-[11px] font-semibold text-amber-200">
										{rec.block_purpose}
									</span>
									<span className="text-[9px] uppercase tracking-wide text-slate-500">
										{rec.content_type}
									</span>
								</div>
								{rec.recommended_preset && (
									<p className="mt-1">
										<span className="text-slate-400">Preset: </span>
										<span className="font-mono text-[10px] text-amber-100">
											{rec.recommended_preset.preset_code}
										</span>{" "}
										{rec.recommended_preset.preset_name}
									</p>
								)}
								<p className="mt-0.5 font-mono text-[10px] text-slate-400">
									{presetLine(rec.recommended_preset)}
								</p>
								{rec.alt_presets.length > 0 && (
									<p className="mt-0.5 text-[9px] text-slate-500">
										alt: {rec.alt_presets.map((p) => p.preset_code).join(", ")}
									</p>
								)}
							</li>
						))}
					</ul>
					{lib && (
						<div className="mt-3 border-t border-slate-700/50 pt-2 text-[10px] text-slate-400">
							<span className="uppercase tracking-wide text-slate-500">Library: </span>
							{lib.shot_distances.length} distances · {lib.camera_angles.length} angles ·{" "}
							{lib.camera_movements.length} movements · {lib.ecomm_shot_types.length} shot types ·{" "}
							{lib.named_presets.length} named presets
						</div>
					)}
				</>
			)}
		</div>
	);
}
