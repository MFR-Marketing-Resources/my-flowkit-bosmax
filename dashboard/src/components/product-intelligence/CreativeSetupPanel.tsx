import { useEffect, useState } from "react";

import {
	getCreativeSetupForProduct,
	saveCreativeSelection,
	reviewCreativeSelection,
	type CreativeSetup,
	type SavedCreativeSelection,
} from "../../api/creativeIntelligence";

/**
 * Creative Setup / Saved Selection panel (Creative Intelligence — Round 4).
 * Composes the Round 1 avatar, Round 2 scene template, and Round 3 camera preset
 * recommendations into one product-level planning artifact. The user picks a
 * setup and saves it (review-gated DRAFT), then a reviewer may APPROVE/REJECT.
 * PLANNING ONLY — no generate/create-asset control, nothing is sent to
 * generation, and [AVATAR]/[PRODUCT] stay unresolved.
 */
export default function CreativeSetupPanel({ productId }: { productId: string }) {
	const [setup, setSetup] = useState<CreativeSetup | null>(null);
	const [saved, setSaved] = useState<SavedCreativeSelection | null>(null);
	const [avatar, setAvatar] = useState("");
	const [scene, setScene] = useState("");
	const [camera, setCamera] = useState("");
	const [notes, setNotes] = useState("");
	const [loading, setLoading] = useState(true);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");

	useEffect(() => {
		let active = true;
		setLoading(true);
		setError("");
		setSetup(null);
		void getCreativeSetupForProduct(productId)
			.then((res) => {
				if (!active) return;
				setSetup(res);
				const sel = res.saved_selection;
				setSaved(sel);
				setAvatar(sel?.selected_avatar_code ?? "");
				setScene(sel?.selected_scene_template_id ?? "");
				setCamera(sel?.selected_camera_preset_code ?? "");
				setNotes(sel?.notes ?? "");
			})
			.catch((cause) => {
				if (active) setError(cause instanceof Error ? cause.message : "Failed to load creative setup.");
			})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
	}, [productId]);

	async function handleSave() {
		setBusy(true);
		setError("");
		try {
			const result = await saveCreativeSelection({
				product_id: productId,
				selected_avatar_code: avatar || null,
				selected_scene_template_id: scene || null,
				selected_camera_preset_code: camera || null,
				notes: notes || null,
			});
			setSaved(result);
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : "Failed to save selection.");
		} finally {
			setBusy(false);
		}
	}

	async function handleReview(action: "APPROVE" | "REJECT") {
		setBusy(true);
		setError("");
		try {
			setSaved(await reviewCreativeSelection(productId, action));
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : "Failed to review selection.");
		} finally {
			setBusy(false);
		}
	}

	const preview = saved?.preview;
	const statusColor =
		saved?.status === "APPROVED" ? "text-emerald-300"
			: saved?.status === "REJECTED" ? "text-red-300" : "text-amber-300";

	return (
		<div
			data-testid="creative-setup-panel"
			className="rounded border border-teal-500/30 bg-teal-500/5 p-3"
		>
			<div className="flex items-center justify-between gap-2">
				<div className="text-sm font-bold text-teal-100">Creative Setup / Saved Selection</div>
				{saved && (
					<span data-testid="creative-setup-status" className={`rounded bg-slate-800 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${statusColor}`}>
						{saved.status}
					</span>
				)}
			</div>
			<p className="mt-1 text-[10px] leading-relaxed text-slate-400">
				Compose a saved creative plan (avatar + scene template + camera preset) for this
				product. Planning only — nothing is generated or sent to generation, and the{" "}
				<code className="text-teal-200">[AVATAR]</code>/<code className="text-teal-200">[PRODUCT]</code>{" "}
				placeholders stay unresolved.
			</p>

			{loading ? (
				<p className="mt-3 text-xs text-slate-400">Loading creative setup…</p>
			) : error && !setup ? (
				<p className="mt-3 text-xs font-medium text-red-300" role="alert">
					Unable to load creative setup: {error}
				</p>
			) : setup ? (
				<>
					<div className="mt-2 text-[10px] uppercase tracking-wide text-slate-500">
						cluster: {setup.cluster} · {setup.cluster_source}
					</div>
					<div className="mt-3 grid gap-2">
						<label className="text-xs text-slate-300">
							Avatar
							<select
								data-testid="creative-setup-avatar"
								className="mt-1 w-full rounded bg-slate-900 p-1 text-xs text-slate-100"
								value={avatar}
								onChange={(e) => setAvatar(e.target.value)}
							>
								<option value="">— none —</option>
								{setup.recommended_avatars.map((a) => (
									<option key={a.avatar_code} value={a.avatar_code}>
										{a.avatar_code} {a.character_name ? `· ${a.character_name}` : ""}
									</option>
								))}
							</select>
						</label>
						<label className="text-xs text-slate-300">
							Scene template
							<select
								data-testid="creative-setup-scene"
								className="mt-1 w-full rounded bg-slate-900 p-1 text-xs text-slate-100"
								value={scene}
								onChange={(e) => setScene(e.target.value)}
							>
								<option value="">— none —</option>
								{setup.recommended_scene_templates.map((t) => (
									<option key={t.template_id} value={t.template_id}>
										{t.template_id} {t.variant ? `· ${t.variant}` : ""}
									</option>
								))}
							</select>
						</label>
						<label className="text-xs text-slate-300">
							Camera preset
							<select
								data-testid="creative-setup-camera"
								className="mt-1 w-full rounded bg-slate-900 p-1 text-xs text-slate-100"
								value={camera}
								onChange={(e) => setCamera(e.target.value)}
							>
								<option value="">— none —</option>
								{setup.camera_library.named_presets.map((p) => (
									<option key={p.preset_code} value={p.preset_code}>
										{p.preset_code} {p.preset_name ? `· ${p.preset_name}` : ""}
									</option>
								))}
							</select>
						</label>
					</div>

					<div className="mt-3 flex flex-wrap items-center gap-2">
						<button
							type="button"
							data-testid="creative-setup-save"
							disabled={busy}
							onClick={handleSave}
							className="rounded bg-teal-600 px-3 py-1 text-xs font-semibold text-white disabled:opacity-50"
						>
							{saved ? "Update Selection" : "Save Selection"}
						</button>
						{saved?.status === "DRAFT" && (
							<>
								<button
									type="button"
									data-testid="creative-setup-approve"
									disabled={busy}
									onClick={() => handleReview("APPROVE")}
									className="rounded border border-emerald-500/50 px-3 py-1 text-xs text-emerald-200 disabled:opacity-50"
								>
									Approve
								</button>
								<button
									type="button"
									data-testid="creative-setup-reject"
									disabled={busy}
									onClick={() => handleReview("REJECT")}
									className="rounded border border-red-500/50 px-3 py-1 text-xs text-red-200 disabled:opacity-50"
								>
									Reject
								</button>
							</>
						)}
					</div>

					{error && (
						<p className="mt-2 text-xs font-medium text-red-300" role="alert">
							{error}
						</p>
					)}

					{preview && (
						<div data-testid="creative-setup-preview" className="mt-3 space-y-1 border-t border-slate-700/50 pt-2 text-[11px] text-slate-300">
							<div className="text-[10px] uppercase tracking-wide text-slate-500">Preview (not sent to generation)</div>
							<div>
								Avatar: <span className="font-mono text-teal-200">{saved?.selected_avatar_code || "—"}</span>{" "}
								{preview.avatar ? `· ${String((preview.avatar as { character_name?: string }).character_name ?? "")}` : ""}
							</div>
							<div>
								Scene: <span className="font-mono text-teal-200">{saved?.selected_scene_template_id || "—"}</span>{" "}
								{preview.scene_template?.main_action ? `· ${preview.scene_template.main_action}` : ""}
							</div>
							<div>
								Camera: <span className="font-mono text-teal-200">{saved?.selected_camera_preset_code || "—"}</span>{" "}
								{preview.camera_preset ? `· ${preview.camera_preset.shot_type ?? ""} · ${preview.camera_preset.distance_angle ?? ""} · ${preview.camera_preset.movement ?? ""}` : ""}
							</div>
						</div>
					)}
				</>
			) : null}
		</div>
	);
}
