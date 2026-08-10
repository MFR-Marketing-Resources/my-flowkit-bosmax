import { useEffect, useState } from "react";

import {
	getScenePromptRecommendationForProduct,
	type ScenePromptRecommendation,
} from "../../api/creativeIntelligence";

/** Read-only scene reference for the product's creative plan. */
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
				if (active) {
					setError(
						cause instanceof Error
							? cause.message
							: "Failed to load scene references.",
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

	const templates = data?.templates ?? [];
	const globalCfg = data?.global_config ?? {};

	return (
		<div
			data-testid="recommended-scene-prompts-card"
			className="rounded-2xl border border-violet-500/25 bg-violet-500/5 p-4"
		>
			<div className="flex flex-wrap items-start justify-between gap-2">
				<div>
					<p className="text-[10px] font-bold uppercase tracking-[0.16em] text-violet-300">
						Reference · Scene
					</p>
					<h3 className="mt-1 text-sm font-bold text-violet-100">
						Recommended scene / image prompts
					</h3>
				</div>
				{data && (
					<div className="text-right text-[10px] text-slate-500">
						<div>{templates.length} templates</div>
					</div>
				)}
			</div>
			<p className="mt-2 text-[11px] leading-relaxed text-slate-400">
				Choose scenes in the plan above. Open a template here when you need the full
				prompt; <code className="text-violet-200">[AVATAR]</code> and{" "}
				<code className="text-violet-200">[PRODUCT]</code> stay unresolved in this reference.
			</p>

			{loading ? (
				<p className="mt-4 text-xs text-slate-400">Loading scene references…</p>
			) : error ? (
				<p className="mt-4 text-xs font-medium text-red-300" role="alert">
					Unable to load scene references: {error}
				</p>
			) : templates.length === 0 ? (
				<p
					className="mt-4 rounded-lg bg-slate-950/50 px-3 py-2 text-xs text-slate-500"
					data-testid="recommended-scene-prompts-empty"
				>
					No scene / image prompt templates available for this product.
				</p>
			) : (
				<>
					<ul
						className="mt-4 grid gap-2 md:grid-cols-2"
						data-testid="recommended-scene-prompts-list"
					>
						{templates.map((template) => (
							<li
								key={template.template_id}
								className="min-w-0 rounded-xl border border-slate-700/70 bg-slate-950/45 p-3"
							>
								<div className="flex items-start justify-between gap-2">
									<span className="font-mono text-[10px] font-semibold text-violet-200">
										{template.template_id}
									</span>
									{template.variant && (
										<span className="text-right text-[9px] uppercase tracking-wide text-slate-500">
											{template.variant}
										</span>
									)}
								</div>
								{template.main_action && (
									<p className="mt-2 line-clamp-2 text-xs leading-relaxed text-slate-200">
										{template.main_action}
									</p>
								)}
								{template.setting && (
									<p className="mt-1 line-clamp-1 text-[11px] text-slate-500">
										{template.setting}
									</p>
								)}
								{template.full_prompt_template && (
									<details className="mt-2 border-t border-slate-800 pt-2">
										<summary className="cursor-pointer text-[10px] font-semibold text-violet-300 hover:text-violet-200">
											View prompt template
										</summary>
										<p className="mt-2 break-words font-mono text-[10px] leading-relaxed text-slate-400">
											{template.full_prompt_template}
										</p>
									</details>
								)}
							</li>
						))}
					</ul>
					{(globalCfg.style_suffix || globalCfg.negative_prompt) && (
						<details className="mt-3 border-t border-slate-800 pt-3">
							<summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wide text-slate-500 hover:text-slate-300">
								Global prompt guidance
							</summary>
							<div className="mt-2 space-y-1 text-[10px] leading-relaxed text-slate-500">
								{globalCfg.style_suffix && (
									<p data-testid="scene-global-style">
										<span className="text-slate-400">Style: </span>
										{globalCfg.style_suffix}
									</p>
								)}
								{globalCfg.negative_prompt && (
									<p>
										<span className="text-slate-400">Avoid: </span>
										{globalCfg.negative_prompt}
									</p>
								)}
							</div>
						</details>
					)}
				</>
			)}
		</div>
	);
}
