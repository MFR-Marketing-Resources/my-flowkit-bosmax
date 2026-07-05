import { useEffect, useMemo, useState } from "react";
import {
	type ImgAssetLane,
	fetchImgAssetLanes,
	saveImgOutputToLibrary,
} from "../../api/imgFactory";
import type { CreativeAsset } from "../../types";

function fileToDataUrl(file: File): Promise<string> {
	return new Promise((resolve, reject) => {
		const reader = new FileReader();
		reader.onload = () => resolve(String(reader.result || ""));
		reader.onerror = reject;
		reader.readAsDataURL(file);
	});
}

/**
 * Minimal IMG Asset Factory hook: save an approved REAL image output into the
 * Creative Library under a governed lane. The lane (not the operator) decides the
 * semantic role, allowed modes, and poster/clean classification — previewed here
 * before saving so the user sees exactly what the saved asset will become.
 *
 * This is intentionally minimal; the full IMG cockpit (inline generate/review)
 * is a separate fast-follow.
 */
export default function SaveToCreativeLibraryPanel({
	onSaved,
}: {
	onSaved?: () => void;
}) {
	const [lanes, setLanes] = useState<ImgAssetLane[]>([]);
	const [laneId, setLaneId] = useState("");
	const [displayName, setDisplayName] = useState("");
	const [productId, setProductId] = useState("");
	const [file, setFile] = useState<File | null>(null);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [saved, setSaved] = useState<CreativeAsset | null>(null);

	useEffect(() => {
		void fetchImgAssetLanes()
			.then((response) => setLanes(response.items))
			.catch(() => setError("Failed to load IMG lanes."));
	}, []);

	const selectedLane = useMemo(
		() => lanes.find((lane) => lane.lane_id === laneId) ?? null,
		[lanes, laneId],
	);

	const productMissing = Boolean(
		selectedLane?.requires_product_id && !productId.trim(),
	);
	const canSave = Boolean(
		selectedLane && displayName.trim() && file && !productMissing && !saving,
	);

	const handleSave = async () => {
		if (!selectedLane || !file) return;
		setSaving(true);
		setError(null);
		setSaved(null);
		try {
			const dataUrl = await fileToDataUrl(file);
			const asset = await saveImgOutputToLibrary({
				lane_id: selectedLane.lane_id,
				display_name: displayName.trim(),
				image_base64: dataUrl,
				file_name: file.name,
				product_id: productId.trim() || null,
			});
			setSaved(asset);
			setDisplayName("");
			setFile(null);
			onSaved?.();
		} catch (err) {
			setError(
				err instanceof Error ? err.message : "Failed to save to Creative Library.",
			);
		} finally {
			setSaving(false);
		}
	};

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4 space-y-4">
			<div>
				<div className="text-sm font-semibold text-slate-100">
					Save IMG Output for Review → Creative Library
				</div>
				<div className="mt-1 text-[11px] text-slate-400">
					Pick a lane, then upload the image output. It is saved as
					PENDING_REVIEW (not auto-approved). The lane governs the asset's
					semantic role, allowed modes, and poster/clean-frame classification —
					no manual mislabeling.
				</div>
			</div>

			<div className="grid gap-3 md:grid-cols-2">
				<label className="text-[11px] text-slate-300 space-y-1">
					<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
						Lane
					</span>
					<select
						value={laneId}
						onChange={(event) => setLaneId(event.target.value)}
						className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
					>
						<option value="">Select a lane…</option>
						{lanes.map((lane) => (
							<option key={lane.lane_id} value={lane.lane_id}>
								{lane.label}
							</option>
						))}
					</select>
				</label>

				<label className="text-[11px] text-slate-300 space-y-1">
					<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
						Display name
					</span>
					<input
						value={displayName}
						onChange={(event) => setDisplayName(event.target.value)}
						className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
						placeholder="e.g. Avatar A — front"
					/>
				</label>

				{selectedLane?.requires_product_id ? (
					<label className="text-[11px] text-slate-300 space-y-1">
						<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
							Product ID (required for this lane)
						</span>
						<input
							value={productId}
							onChange={(event) => setProductId(event.target.value)}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200"
							placeholder="product id"
						/>
					</label>
				) : null}

				<label className="text-[11px] text-slate-300 space-y-1">
					<span className="font-semibold uppercase tracking-[0.14em] text-slate-500">
						Approved output image
					</span>
					<input
						type="file"
						accept="image/*"
						onChange={(event) => setFile(event.target.files?.[0] ?? null)}
						className="w-full text-[11px] text-slate-400 file:mr-3 file:rounded-md file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-slate-200"
					/>
				</label>
			</div>

			{selectedLane ? (
				<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3 text-[11px] text-slate-300">
					<div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
						This lane will save as
					</div>
					<div className="mt-2 flex flex-wrap gap-2">
						<span className="rounded-full border border-blue-500/30 bg-blue-500/10 px-2.5 py-1 text-[10px] font-semibold text-blue-200">
							{selectedLane.default_semantic_role}
						</span>
						{selectedLane.default_allowed_modes.map((mode) => (
							<span
								key={mode}
								className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[10px] font-semibold text-slate-300"
							>
								{mode}
							</span>
						))}
						{selectedLane.default_contains_rendered_text ? (
							<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold text-amber-200">
								Poster (rendered text) — not a clean video frame
							</span>
						) : (
							<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-200">
								Clean frame — video-support eligible
							</span>
						)}
					</div>
					<div className="mt-2 text-[10px] text-slate-500">
						{selectedLane.purpose}
					</div>
				</div>
			) : null}

			{error ? (
				<div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
					{error}
				</div>
			) : null}

			{saved ? (
				<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-100">
					Saved <strong>{saved.display_name}</strong> as{" "}
					<strong>{saved.semantic_role}</strong> ·{" "}
					<strong>{saved.review_status}</strong>
					{saved.allowed_modes.length > 0
						? ` · reusable in ${saved.allowed_modes.join(", ")}`
						: " · terminal asset (no video reuse)"}
					.
				</div>
			) : null}

			<button
				type="button"
				onClick={handleSave}
				disabled={!canSave}
				className="w-full rounded-xl bg-gradient-to-r from-blue-600 to-purple-600 py-3 text-sm font-bold text-white disabled:opacity-50 disabled:grayscale transition-all"
			>
				{saving ? "Saving…" : "Save for Review"}
			</button>
			{productMissing ? (
				<p className="text-center text-[10px] text-amber-300/70">
					This lane requires a product ID to preserve product truth.
				</p>
			) : null}
		</section>
	);
}
