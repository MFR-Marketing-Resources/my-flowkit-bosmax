import { useEffect, useState } from "react";

import {
	getAvatarRecommendationForProduct,
	type AvatarRecommendation,
} from "../../api/creativeIntelligence";

/**
 * Read-only "Recommended AI Avatars" card (Creative Intelligence — Round 1).
 * Resolves the product's category -> creative cluster and shows recommended
 * BOS_ avatars from the existing avatar pool. No generation controls; this card
 * never mutates Product Truth, Copy Sets, Copy Registry, or generates anything.
 */
export default function RecommendedAvatarsCard({ productId }: { productId: string }) {
	const [data, setData] = useState<AvatarRecommendation | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");

	useEffect(() => {
		let active = true;
		setLoading(true);
		setError("");
		setData(null);
		void getAvatarRecommendationForProduct(productId)
			.then((response) => {
				if (active) setData(response);
			})
			.catch((cause) => {
				if (active) setError(cause instanceof Error ? cause.message : "Failed to load avatar recommendations.");
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [productId]);

	return (
		<div
			data-testid="recommended-avatars-card"
			className="rounded border border-sky-500/30 bg-sky-500/5 p-3"
		>
			<div className="flex items-center justify-between gap-2">
				<div className="text-sm font-bold text-sky-100">Recommended AI Avatars</div>
				{data && (
					<span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300">
						cluster: {data.cluster} · {data.cluster_source}
					</span>
				)}
			</div>
			<p className="mt-1 text-[10px] leading-relaxed text-slate-400">
				Read-only creative suggestion — resolves this product's category into a creative
				cluster and lists suitable avatars from the existing avatar pool. Nothing is
				generated, approved, or written to Product Truth here.
			</p>

			{loading ? (
				<p className="mt-3 text-xs text-slate-400">Loading avatar recommendations…</p>
			) : error ? (
				<p className="mt-3 text-xs font-medium text-red-300" role="alert">
					Unable to load recommendations: {error}
				</p>
			) : !data || data.avatars.length === 0 ? (
				<p className="mt-3 text-xs text-slate-400">No avatar recommendations available.</p>
			) : (
				<ul className="mt-3 space-y-1" data-testid="recommended-avatars-list">
					{data.avatars.slice(0, 8).map((avatar) => (
						<li
							key={avatar.avatar_code}
							className="flex items-baseline gap-2 text-xs text-slate-200"
						>
							<span className="font-mono text-[11px] text-sky-200">{avatar.avatar_code}</span>
							{avatar.character_name && (
								<span className="text-slate-400">{avatar.character_name}</span>
							)}
							<span className="rounded bg-slate-800 px-1 text-[9px] text-slate-300">
								fit {avatar.fit_score}
							</span>
							<span className="text-[9px] uppercase tracking-wide text-slate-500">
								{avatar.fit_source}
							</span>
						</li>
					))}
				</ul>
			)}
		</div>
	);
}
