import { useEffect, useState } from "react";

import {
	getCreativeSetupForProduct,
	getProductRecipes,
	saveCreativeSelection,
	reviewCreativeSelection,
	type CreativeSetup,
	type SavedCreativeSelection,
} from "../../api/creativeIntelligence";

/**
 * Creative Setup / Saved Selection panel (Creative Intelligence — Round 4).
 * Composes the Round 1 avatar, Round 2 scene template, and Round 3 camera preset
 * recommendations into a product-level planning artifact. Now MULTI-SELECT: tick
 * multiple avatars / scenes / cameras (the chosen SET); the first of each is the
 * backward-compatible primary. "Smart suggest (fill all)" sets + approves the full
 * in one click. PLANNING ONLY — nothing is generated or sent to generation, and
 * [AVATAR]/[PRODUCT] stay unresolved.
 */
export default function CreativeSetupPanel({ productId }: { productId: string }) {
	const [setup, setSetup] = useState<CreativeSetup | null>(null);
	const [saved, setSaved] = useState<SavedCreativeSelection | null>(null);
	const [avatars, setAvatars] = useState<string[]>([]);
	const [scenes, setScenes] = useState<string[]>([]);
	const [cameras, setCameras] = useState<string[]>([]);
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
				// Pre-configure from the saved selection if one exists, else from the
				// live smart default (auto-derived from the cluster mapping) so EVERY
				// product opens ready without the operator hand-picking.
				const def = res.default_selection;
				setSaved(sel);
				setAvatars(sel?.selected_avatar_codes ?? def?.selected_avatar_codes ?? []);
				setScenes(
					sel?.selected_scene_template_ids ?? def?.selected_scene_template_ids ?? [],
				);
				setCameras(
					sel?.selected_camera_preset_codes ?? def?.selected_camera_preset_codes ?? [],
				);
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

	const toggle = (
		list: string[],
		setList: (next: string[]) => void,
		code: string,
	) => {
		setList(list.includes(code) ? list.filter((c) => c !== code) : [...list, code]);
	};

	async function handleSave() {
		setBusy(true);
		setError("");
		try {
			const result = await saveCreativeSelection({
				product_id: productId,
				selected_avatar_codes: avatars,
				selected_scene_template_ids: scenes,
				selected_camera_preset_codes: cameras,
				notes: notes || null,
			});
			setSaved(result);
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : "Failed to save selection.");
		} finally {
			setBusy(false);
		}
	}

	async function handleAutoFill() {
		if (!setup) return;
		// Smart suggest: build a COHERENT recipe plan (avatar × scene where the camera
		// FOLLOWS the scene) and tick the capped, arc-spread recommended set — NOT the
		// old fill-all (all avatars × all scenes × all 17 cameras) that produced
		// incoherent combos. The camera list is derived from the picked recipes so it can
		// never include a camera that does not match a chosen scene.
		setBusy(true);
		setError("");
		try {
			const plan = await getProductRecipes(productId);
			const chosen = plan.recommended_pretick;
			if (!chosen.length) {
				setError(
					plan.review_required
						? "This product needs a verified cluster before recipes can be built."
						: "No coherent recipe to auto-fill for this product.",
				);
				return;
			}
			const dedupe = (xs: string[]) => Array.from(new Set(xs.filter(Boolean)));
			const a = dedupe(chosen.map((r) => r.avatar_code));
			const s = dedupe(chosen.map((r) => r.scene_template_id));
			const c = dedupe(chosen.map((r) => r.camera_preset_code));
			await saveCreativeSelection({
				product_id: productId,
				selected_avatar_codes: a,
				selected_scene_template_ids: s,
				selected_camera_preset_codes: c,
				notes: "Smart suggest: coherent recipe plan (camera follows scene)",
			});
			setAvatars(a);
			setScenes(s);
			setCameras(c);
			setSaved(await reviewCreativeSelection(productId, "APPROVE"));
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : "Failed to auto-fill selection.");
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
				Compose a saved creative plan for this product — tick one or MORE avatars,
				scene templates, and camera presets. Planning only — nothing is generated or
				sent to generation, and the{" "}
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
					<div className="mt-2 flex items-center justify-between gap-2">
						<div className="text-[10px] uppercase tracking-wide text-slate-500">
							cluster: {setup.cluster} · {setup.cluster_source}
						</div>
						<button
							type="button"
							data-testid="creative-setup-autofill"
							disabled={busy}
							onClick={handleAutoFill}
							title="Smart suggest: build a COHERENT recipe plan (avatar × scene, camera follows scene) and tick the capped arc-spread set (intro → body → detail → benefit), then approve — no incoherent combos"
							className="rounded bg-indigo-600 px-2 py-1 text-[10px] font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
						>
							⚡ Smart suggest (coherent recipes)
						</button>
					</div>

					<div className="mt-3 grid gap-3">
						<MultiPickList
							label="Avatars"
							testid="creative-setup-avatar"
							selected={avatars}
							options={(setup.avatar_library?.length
								? setup.avatar_library
								: setup.recommended_avatars
							).map((a) => ({
								code: a.avatar_code,
								label:
									`${a.avatar_code}${a.character_name ? ` · ${a.character_name}` : ""}` +
									("recommended" in a && a.recommended ? " ★" : ""),
							}))}
							onToggle={(code) => toggle(avatars, setAvatars, code)}
						/>
						<MultiPickList
							label="Scene templates"
							testid="creative-setup-scene"
							selected={scenes}
							options={setup.recommended_scene_templates.map((t) => ({
								code: t.template_id,
								label: `${t.template_id}${t.variant ? ` · ${t.variant}` : ""}`,
							}))}
							onToggle={(code) => toggle(scenes, setScenes, code)}
						/>
						<MultiPickList
							label="Camera presets"
							testid="creative-setup-camera"
							selected={cameras}
							options={setup.camera_library.named_presets.map((p) => ({
								code: p.preset_code,
								label: `${p.preset_code}${p.preset_name ? ` · ${p.preset_name}` : ""}`,
							}))}
							onToggle={(code) => toggle(cameras, setCameras, code)}
						/>
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
						<span className="text-[10px] text-slate-500">
							{avatars.length} avatar · {scenes.length} scene · {cameras.length} camera
						</span>
					</div>

					{error && (
						<p className="mt-2 text-xs font-medium text-red-300" role="alert">
							{error}
						</p>
					)}
				</>
			) : null}
		</div>
	);
}

function MultiPickList({
	label,
	testid,
	selected,
	options,
	onToggle,
}: {
	label: string;
	testid: string;
	selected: string[];
	options: { code: string; label: string }[];
	onToggle: (code: string) => void;
}) {
	return (
		<div>
			<div className="mb-1 flex items-center justify-between">
				<span className="text-xs text-slate-300">{label}</span>
				<span className="text-[10px] text-slate-500">{selected.length} selected</span>
			</div>
			{options.length === 0 ? (
				<p className="rounded bg-slate-900 px-2 py-1 text-[10px] text-slate-500">
					No recommendations for this product.
				</p>
			) : (
				<div
					data-testid={testid}
					className="max-h-32 space-y-0.5 overflow-y-auto rounded bg-slate-900 p-1"
				>
					{options.map((o) => (
						<label
							key={o.code}
							className="flex cursor-pointer items-center gap-2 rounded px-1 py-0.5 text-[11px] text-slate-200 hover:bg-slate-800"
						>
							<input
								type="checkbox"
								className="accent-teal-500"
								checked={selected.includes(o.code)}
								onChange={() => onToggle(o.code)}
							/>
							<span className="truncate">{o.label}</span>
						</label>
					))}
				</div>
			)}
		</div>
	);
}
