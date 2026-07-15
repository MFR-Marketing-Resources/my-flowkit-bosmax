import { useEffect, useState } from "react";

import {
	getScenePromptRecommendationForProduct,
	type ScenePromptRecommendation,
} from "../../api/creativeIntelligence";

/**
 * Read-only "Recommended Scene / Image Prompts" card (Creative Intelligence —
 * Round 2). Resolves the product's category -> creative cluster and lists
 * reconciled scene/action/placement image-prompt templates from the committed
 * library. The [AVATAR] and [PRODUCT] placeholders stay UNRESOLVED here — this
 * card never generates, approves, resolves placeholders, or writes anything.
 */
export default function RecommendedScenePromptsCard({ productId }: { productId: string }) {
	const [data, setData] = useState<ScenePromptRecommendation | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");

	useEffect(() => {
		let active = true;
		setLoading(true);
		setError("");
		setData(null);
		void getScenePromptRecommendationForProduct(productId)
			.then((response) => {
				if (active) setData(response);
			})
			.catch((cause) => {
				if (active) setError(cause instanceof Error ? cause.message : "Failed to load scene prompts.");
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [productId]);

	const templates = data?.templates ?? [];
	const globalCfg = data?.global_config ?? {};

	return (
		<div
			data-testid="recommended-scene-prompts-card"
			className="rounded border border-violet-500/30 bg-violet-500/5 p-3"
		>
			<div className="flex items-center justify-between gap-2">
				<div className="text-sm font-bold text-violet-100">Recommended Scene / Image Prompts</div>
				{data && (
					<span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
						cluster: {data.cluster} · {data.cluster_source}
					</span>
				)}
			</div>
			<p className="mt-1 text-[10px] leading-relaxed text-slate-400">
				Read-only creative suggestion — resolves this product's category into a creative
				cluster and lists reusable scene/action/placement prompt templates. The{" "}
				<code className="text-violet-200">[AVATAR]</code> and{" "}
				<code className="text-violet-200">[PRODUCT]</code> placeholders are left unresolved.
				Nothing is generated, approved, or sent to generation here.
			</p>

			{loading ? (
				<p className="mt-3 text-xs text-slate-400">Loading scene prompts…</p>
			) : error ? (
				<p className="mt-3 text-xs font-medium text-red-300" role="alert">
					Unable to load scene prompts: {error}
				</p>
			) : templates.length === 0 ? (
				<p className="mt-3 text-xs text-slate-400" data-testid="recommended-scene-prompts-empty">
					No scene / image prompt templates available for this cluster yet.
				</p>
			) : (
				<>
					<ul className="mt-3 space-y-2" data-testid="recommended-scene-prompts-list">
						{templates.slice(0, 6).map((tpl) => (
							<li
								key={tpl.template_id}
								className="rounded border border-slate-700/60 bg-slate-900/40 p-2 text-xs text-slate-200"
							>
								<div className="flex items-center justify-between gap-2">
									<span className="font-mono text-[10px] text-violet-200">{tpl.template_id}</span>
									{tpl.variant && (
										<span className="text-[9px] uppercase tracking-wide text-slate-500">{tpl.variant}</span>
									)}
								</div>
								{tpl.main_action && (
									<p className="mt-1">
										<span className="text-slate-400">Action: </span>
										{tpl.main_action}
									</p>
								)}
								{tpl.setting && (
									<p className="mt-0.5">
										<span className="text-slate-400">Setting: </span>
										{tpl.setting}
									</p>
								)}
								{tpl.full_prompt_template && (
									<p className="mt-1 line-clamp-2 font-mono text-[10px] text-slate-400">
										{tpl.full_prompt_template}
									</p>
								)}
							</li>
						))}
					</ul>
					{(globalCfg.style_suffix || globalCfg.negative_prompt) && (
						<div className="mt-3 space-y-1 border-t border-slate-700/50 pt-2 text-[10px] text-slate-400">
							{globalCfg.style_suffix && (
								<p data-testid="scene-global-style">
									<span className="uppercase tracking-wide text-slate-500">Global style: </span>
									{globalCfg.style_suffix}
								</p>
							)}
							{globalCfg.negative_prompt && (
								<p>
									<span className="uppercase tracking-wide text-slate-500">Negative: </span>
									{globalCfg.negative_prompt}
								</p>
							)}
						</div>
					)}
				</>
			)}
		</div>
	);
}
