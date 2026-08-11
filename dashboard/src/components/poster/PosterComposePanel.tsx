import { useState } from "react";
import {
	composePoster,
	posterDeliverableOutputUrl,
	savePosterToLibrary,
} from "../../api/posterCopySets";
import type {
	PosterComposeResponse,
	PosterCopySet,
} from "../../types/posterCopySet";

/** Deterministic compose + QA + save panel (POSTER_BUILDER_V2).
 *
 * Takes the CLEAN generated scene (media id) + the approved Poster Copy Set and
 * renders the final marketing text/components via the Chromium compositor —
 * credit-free, offline. Preview and save use the exact same bytes; saving
 * registers the poster in the Creative Library. */
export default function PosterComposePanel({
	productId,
	recipeId,
	copySet,
	backgroundMediaId,
}: {
	productId: string;
	recipeId: string;
	copySet: PosterCopySet | null;
	backgroundMediaId: string;
}) {
	const [result, setResult] = useState<PosterComposeResponse | null>(null);
	const [loading, setLoading] = useState(false);
	const [saving, setSaving] = useState(false);
	const [savedAssetId, setSavedAssetId] = useState("");
	const [error, setError] = useState("");

	const ready = !!copySet && !!backgroundMediaId && !!recipeId;

	const handleCompose = async () => {
		if (!copySet) return;
		setLoading(true);
		setError("");
		setResult(null);
		setSavedAssetId("");
		try {
			const res = await composePoster({
				product_id: productId,
				poster_copy_set_id: copySet.poster_copy_set_id,
				recipe_id: recipeId,
				background_media_id: backgroundMediaId,
			});
			setResult(res);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Poster composite failed.");
		} finally {
			setLoading(false);
		}
	};

	const handleSave = async () => {
		if (!result) return;
		setSaving(true);
		setError("");
		try {
			const res = await savePosterToLibrary(
				result.deliverable.poster_deliverable_id,
			);
			setSavedAssetId(res.creative_asset_id);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Save to Creative Library failed.");
		} finally {
			setSaving(false);
		}
	};

	const qa = result?.qa_report ?? null;

	return (
		<section
			className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5 space-y-3"
			data-testid="poster-compose-panel"
		>
			<h3 className="text-sm font-bold text-slate-100">
				7. Final text composite (deterministic · free)
			</h3>
			<p className="text-[11px] text-slate-500">
				Marketing text is drawn by the compositor (not image AI) — exact spelling,
				zone-fit, and text kept away from product areas DEFINED by the
				template (not real product detection). Preview = the SAVED
				file (byte-identical). Human review is still required: placement, identity,
				product label & scale in the generated scene.
			</p>
			{!ready ? (
				<p className="text-[11px] text-amber-300" data-testid="poster-compose-waiting">
					{!copySet
						? "Approve the Poster Copy Set first (step 3)."
						: "Generate a clean scene first (step 6)."}
				</p>
			) : (
				<button
					type="button"
					data-testid="poster-compose-button"
					disabled={loading}
					onClick={() => void handleCompose()}
					className="rounded-xl border border-blue-500/50 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40"
				>
					{loading ? "Compositing…" : "Composite poster (free)"}
				</button>
			)}
			{qa ? (
				<div className="space-y-1" data-testid="poster-compose-qa">
					<p
						className={`text-[11px] font-bold ${qa.ok ? "text-emerald-300" : "text-rose-300"}`}
					>
						QA: {qa.ok ? "PASS" : `${qa.block_count} blocking issues`}
						{qa.warn_count ? ` · ${qa.warn_count} warnings` : ""}
					</p>
					{qa.findings.map((f) => (
						<p
							key={`${f.code}-${f.zone_id}`}
							className={`text-[11px] ${f.severity === "BLOCK" ? "text-rose-300" : "text-amber-300"}`}
						>
							[{f.severity}] {f.code}
							{f.zone_id ? ` (${f.zone_id})` : ""}: {f.message}
						</p>
					))}
				</div>
			) : null}
			{result ? (
				<div className="space-y-2" data-testid="poster-compose-result">
					<img
						src={posterDeliverableOutputUrl(
							result.deliverable.poster_deliverable_id,
						)}
						alt="Composited poster"
						className="max-h-96 rounded-xl border border-slate-800"
					/>
					<div className="flex flex-wrap items-center gap-3">
						<button
							type="button"
							data-testid="poster-save-library"
							disabled={saving || !qa?.ok || !!savedAssetId}
							onClick={() => void handleSave()}
							className="rounded-xl border border-emerald-500/50 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40"
						>
							{saving
								? "Saving…"
								: savedAssetId
									? "✓ Saved"
									: "Save to Creative Library"}
						</button>
						<a
							href={posterDeliverableOutputUrl(
								result.deliverable.poster_deliverable_id,
							)}
							target="_blank"
							rel="noopener noreferrer"
							className="rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] font-semibold text-slate-200"
						>
							Open / Download ↗
						</a>
					</div>
					{savedAssetId ? (
						<p data-testid="poster-saved-note" className="text-[11px] text-emerald-300">
							✓ Poster + configuration saved (asset {savedAssetId}). Can be reopened
							from Creative Library / deliverable{" "}
							{result.deliverable.poster_deliverable_id}.
						</p>
					) : null}
				</div>
			) : null}
			{error ? (
				<p data-testid="poster-compose-error" className="text-[11px] text-rose-300">
					{error}
				</p>
			) : null}
		</section>
	);
}
