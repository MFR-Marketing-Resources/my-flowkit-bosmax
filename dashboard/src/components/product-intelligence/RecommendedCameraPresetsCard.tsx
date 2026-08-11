import { useEffect, useState } from "react";

import {
	getCameraPresetRecommendationForProduct,
	type CameraPreset,
	type CameraPresetRecommendation,
} from "../../api/creativeIntelligence";

/** Read-only camera reference. Camera selection itself remains scene-derived. */
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
				if (active) {
					setError(
						cause instanceof Error
							? cause.message
							: "Failed to load camera references.",
					);
				}
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [productId]);

	const recommendations = data?.block_recommendations ?? [];

	return (
		<div
			data-testid="recommended-camera-presets-card"
			className="rounded-2xl border border-amber-500/25 bg-amber-500/5 p-4"
		>
			<div className="flex flex-wrap items-start justify-between gap-2">
				<div>
					<p className="text-[10px] font-bold uppercase tracking-[0.16em] text-amber-300">
						Reference · Camera
					</p>
					<h3 className="mt-1 text-sm font-bold text-amber-100">
						Recommended camera / video presets
					</h3>
				</div>
				{data && (
					<div className="text-right text-[10px] text-slate-500">
						<div>{recommendations.length} presets</div>
					</div>
				)}
			</div>
			<p className="mt-2 text-[11px] leading-relaxed text-slate-400">
				These presets explain the shot language behind each creative block. The plan above
				derives the final camera from the chosen scene; there is no separate camera checkbox.
			</p>

			{loading ? (
				<p className="mt-4 text-xs text-slate-400">Loading camera references…</p>
			) : error ? (
				<p className="mt-4 text-xs font-medium text-red-300" role="alert">
					Unable to load camera references: {error}
				</p>
			) : recommendations.length === 0 ? (
				<p
					className="mt-4 rounded-lg bg-slate-950/50 px-3 py-2 text-xs text-slate-500"
					data-testid="recommended-camera-presets-empty"
				>
					No camera / video presets available for this product.
				</p>
			) : (
				<ul
					className="mt-4 grid gap-2 md:grid-cols-2"
					data-testid="recommended-camera-presets-list"
				>
					{recommendations.map((recommendation) => (
						<li
							key={`${recommendation.block_purpose}-${recommendation.content_type}`}
							className="min-w-0 rounded-xl border border-slate-700/70 bg-slate-950/45 p-3"
						>
							<div className="flex items-start justify-between gap-2">
								<span className="text-[11px] font-semibold text-amber-200">
									{recommendation.block_purpose || "Creative block"}
								</span>
								<span className="text-right text-[9px] uppercase tracking-wide text-slate-500">
									{recommendation.content_type || "Preset"}
								</span>
							</div>
							{recommendation.recommended_preset && (
								<PresetDetail preset={recommendation.recommended_preset} />
							)}
							{recommendation.alt_presets.length > 0 && (
								<details className="mt-2 border-t border-slate-800 pt-2">
									<summary className="cursor-pointer text-[10px] font-semibold text-amber-300 hover:text-amber-200">
										{recommendation.alt_presets.length} alternate preset{recommendation.alt_presets.length === 1 ? "" : "s"}
									</summary>
									<p className="mt-2 font-mono text-[10px] text-slate-500">
										{recommendation.alt_presets.map((preset) => preset.preset_code).join(" · ")}
									</p>
								</details>
							)}
						</li>
					))}
				</ul>
			)}
		</div>
	);
}

function PresetDetail({ preset }: { preset: CameraPreset }) {
	const descriptor = [preset.shot_type, preset.distance_angle, preset.movement]
		.filter(Boolean)
		.join(" · ");
	return (
		<div className="mt-2">
			<div className="flex flex-wrap items-center gap-2">
				<span className="font-mono text-xs font-semibold text-amber-100">
					{preset.preset_code}
				</span>
				<span className="text-[11px] text-slate-300">{preset.preset_name}</span>
			</div>
			{descriptor && (
				<p className="mt-1 text-[10px] leading-relaxed text-slate-500">
					{descriptor}
				</p>
			)}
		</div>
	);
}
