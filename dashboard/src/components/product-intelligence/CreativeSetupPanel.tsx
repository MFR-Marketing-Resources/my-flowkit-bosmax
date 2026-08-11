import { useEffect, useState } from "react";

import {
	getCreativeSetupForProduct,
	getProductRecipes,
	reviewCreativeSelection,
	saveCreativeSelection,
	type AvatarLibraryItem,
	type CreativeSetup,
	type RecommendedAvatar,
	type SavedCreativeSelection,
	type ScenePromptTemplate,
} from "../../api/creativeIntelligence";

/**
 * The product-level creative plan editor.
 *
 * Recommendations are the primary setting surface. The full avatar roster is
 * available only when the operator explicitly expands it, and cameras are
 * always derived from the selected scenes. This keeps the editor coherent and
 * prevents the recommendation cards from becoming a second, disconnected
 * selection UI.
 */
export default function CreativeSetupPanel({ productId }: { productId: string }) {
	const [setup, setSetup] = useState<CreativeSetup | null>(null);
	const [saved, setSaved] = useState<SavedCreativeSelection | null>(null);
	const [avatars, setAvatars] = useState<string[]>([]);
	const [scenes, setScenes] = useState<string[]>([]);
	// scene_template_id -> camera_preset_code (camera follows scene; avatar-independent).
	const [sceneCameraMap, setSceneCameraMap] = useState<Record<string, string>>(
		{},
	);
	const [notes, setNotes] = useState("");
	const [loading, setLoading] = useState(true);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");

	useEffect(() => {
		let active = true;
		setLoading(true);
		setError("");
		setSetup(null);
		Promise.all([
			getCreativeSetupForProduct(productId),
			// Recipes provide the deterministic scene→camera binding. If this
			// enrichment is unavailable, the editor still works without camera chips.
			Promise.resolve(getProductRecipes(productId)).catch(() => null),
		])
			.then(([res, recipes]) => {
				if (!active) return;
				setSetup(res);
				const sel = res.saved_selection;
				const def = res.default_selection;
				setSaved(sel);
				setAvatars(
					sel
						? savedList(sel.selected_avatar_codes, sel.selected_avatar_code)
						: (def?.selected_avatar_codes ?? []),
				);
				setScenes(
					sel
						? savedList(
								sel.selected_scene_template_ids,
							sel.selected_scene_template_id,
						)
						: (def?.selected_scene_template_ids ?? []),
				);
				setNotes(sel?.notes ?? "");
				setSceneCameraMap(buildSceneCameraMap(recipes));
			})
			.catch((cause) => {
				if (active)
					setError(
						cause instanceof Error
							? cause.message
							: "Failed to load creative setup.",
					);
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
		setList(
			list.includes(code) ? list.filter((c) => c !== code) : [...list, code],
		);
	};

	// Camera is derived from the chosen scenes (never independently picked), so the
	// saved plan can never carry a camera that contradicts its scene.
	const derivedCameras = unique(
		scenes.map((sceneId) => sceneCameraMap[sceneId]).filter(Boolean),
	);

	const baselineAvatars = setup
		? saved
			? savedList(saved.selected_avatar_codes, saved.selected_avatar_code)
			: (setup.default_selection?.selected_avatar_codes ?? [])
		: [];
	const baselineScenes = setup
		? saved
			? savedList(
				saved.selected_scene_template_ids,
				saved.selected_scene_template_id,
			)
			: (setup.default_selection?.selected_scene_template_ids ?? [])
		: [];
	const baselineNotes = saved?.notes ?? "";
	const hasChanges =
		!saved ||
		!sameSet(avatars, baselineAvatars) ||
		!sameSet(scenes, baselineScenes) ||
		notes.trim() !== baselineNotes.trim();
	const selectionReady = avatars.length > 0 && scenes.length > 0;
	const canSave = Boolean(
		setup &&
		!setup.review_required &&
		selectionReady &&
		(!saved || hasChanges),
	);
	const canReview = Boolean(
		setup &&
		!setup.review_required &&
		selectionReady &&
		saved?.status === "DRAFT" &&
		!hasChanges,
	);

	async function handleSave() {
		if (!selectionReady || setup?.review_required) return;
		setBusy(true);
		setError("");
		try {
			const result = await saveCreativeSelection({
				product_id: productId,
				selected_avatar_codes: avatars,
				selected_scene_template_ids: scenes,
				// Keep the derived value visible in the request for legacy consumers;
				// the server recalculates it from scenes and ignores independent camera input.
				selected_camera_preset_codes: derivedCameras,
				notes: notes.trim() || null,
			});
			setSaved(result);
		} catch (cause) {
			setError(
				cause instanceof Error ? cause.message : "Failed to save selection.",
			);
		} finally {
			setBusy(false);
		}
	}

	async function handleUseRecommendation() {
		if (!setup) return;
		// This is intentionally read-only. It fills the local form; the operator
		// must press Save plan before any selection is written or review-gated.
		setBusy(true);
		setError("");
		try {
			const plan = await getProductRecipes(productId);
			const chosen = plan.recommended_pretick;
			if (!chosen.length) {
				setError(
					plan.review_required
						? "This product needs a verified category before a plan can be suggested."
						: "No recommended creative plan is available for this product.",
				);
				return;
			}
			setAvatars(unique(chosen.map((recipe) => recipe.avatar_code)));
			setScenes(unique(chosen.map((recipe) => recipe.scene_template_id)));
			setSceneCameraMap((previous) => ({
				...previous,
				...buildSceneCameraMap(plan),
			}));
		} catch (cause) {
			setError(
				cause instanceof Error
					? cause.message
					: "Failed to load the recommended plan.",
			);
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
			setError(
				cause instanceof Error ? cause.message : "Failed to review the plan.",
			);
		} finally {
			setBusy(false);
		}
	}

	const status = saved?.status ?? "NOT_SAVED";
	const statusCopy = hasChanges
		? "Unsaved changes"
		: status === "APPROVED"
			? "Approved plan"
			: status === "DRAFT"
				? "Ready for review"
				: "Not saved";
	const statusColor = hasChanges
		? "text-amber-200"
		: status === "APPROVED"
			? "text-emerald-300"
			: status === "REJECTED"
				? "text-red-300"
				: "text-slate-300";

	return (
		<div
			data-testid="creative-setup-panel"
			className="rounded-2xl border border-slate-700 bg-slate-900/70 p-4 shadow-xl md:p-5"
		>
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div className="min-w-0">
					<div className="flex flex-wrap items-center gap-2">
						<p className="text-[10px] font-bold uppercase tracking-[0.18em] text-indigo-300">
							Creative setup
						</p>
						{setup?.cluster && (
							<span className="rounded-full bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400">
								Recommended for {setup.cluster}
							</span>
						)}
					</div>
					<h2 className="mt-1 text-base font-bold text-white md:text-lg">
						Build the creative plan
					</h2>
					<p className="mt-1 max-w-2xl text-xs leading-relaxed text-slate-400">
						Choose the people and scenes. Camera presets follow the scene automatically.
					</p>
				</div>
				<div className="flex items-center gap-2">
					<span
						data-testid="creative-setup-status"
						className={`rounded-full bg-slate-800 px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide ${statusColor}`}
					>
						{hasChanges ? "UNSAVED" : status}
					</span>
					<span className="text-[11px] text-slate-500">{statusCopy}</span>
				</div>
			</div>

			{loading ? (
				<p className="mt-6 text-sm text-slate-400">Loading creative setup…</p>
			) : error && !setup ? (
				<p className="mt-6 text-sm font-medium text-red-300" role="alert">
					Unable to load creative setup: {error}
				</p>
			) : setup ? (
				<>
					<div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
						<section
							data-testid="recommended-avatars-card"
							className="rounded-xl border border-indigo-500/25 bg-indigo-500/5 p-3"
						>
							<div className="flex items-center justify-between gap-2">
								<div>
									<h3 className="text-sm font-semibold text-indigo-100">
										Recommended AI Avatars
									</h3>
									<p className="mt-0.5 text-[11px] text-slate-500">
										Select one or more
									</p>
								</div>
								<span className="text-[11px] text-slate-500">
									{avatars.length} selected
								</span>
							</div>

							<AvatarPicker
								selected={avatars}
								recommended={setup.recommended_avatars}
								library={setup.avatar_library ?? []}
								onToggle={(code) => toggle(avatars, setAvatars, code)}
							/>
						</section>

						<section className="rounded-xl border border-violet-500/25 bg-violet-500/5 p-3">
							<div className="flex items-center justify-between gap-2">
								<div>
									<h3 className="text-sm font-semibold text-violet-100">
										Recommended scenes
									</h3>
									<p className="mt-0.5 text-[11px] text-slate-500">
										Camera follows each scene
									</p>
								</div>
								<span className="text-[11px] text-slate-500">
									{scenes.length} selected
								</span>
							</div>
							<div
								data-testid="creative-setup-scene"
								className="mt-3 grid gap-2"
							>
								{setup.recommended_scene_templates.length === 0 ? (
									<p className="rounded-lg bg-slate-950/50 px-3 py-2 text-xs text-slate-500">
										No recommended scenes for this product.
									</p>
								) : (
									setup.recommended_scene_templates.map((template) => (
										<SceneChoice
											key={template.template_id}
											template={template}
											camera={sceneCameraMap[template.template_id]}
											checked={scenes.includes(template.template_id)}
											onChange={() =>
												toggle(
													scenes,
													setScenes,
													template.template_id,
												)
											}
										/>
									))
								)}
							</div>
						</section>
					</div>

					<div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(260px,0.38fr)]">
						<div className="rounded-xl border border-slate-800 bg-slate-950/40 p-3">
							<div className="flex items-center justify-between gap-2">
								<label
									className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400"
									htmlFor="creative-setup-notes"
								>
									Plan note <span className="font-normal normal-case tracking-normal text-slate-600">(optional)</span>
								</label>
								<span className="text-[10px] text-slate-600">Saved with this plan</span>
							</div>
							<textarea
								id="creative-setup-notes"
								data-testid="creative-setup-notes"
								rows={2}
								value={notes}
								onChange={(event) => setNotes(event.target.value)}
								placeholder="Add a short note for the next reviewer…"
								className="mt-2 w-full resize-y rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 outline-none placeholder:text-slate-600 focus:border-indigo-400"
							/>
						</div>
						<div
							data-testid="creative-setup-summary"
							className="rounded-xl border border-teal-500/20 bg-teal-500/5 p-3"
						>
							<p className="text-[10px] font-bold uppercase tracking-[0.16em] text-teal-200">
								Plan summary
							</p>
							<div className="mt-2 grid grid-cols-3 gap-2 text-center">
								<SummaryMetric value={avatars.length} label="avatars" />
								<SummaryMetric value={scenes.length} label="scenes" />
								<SummaryMetric value={derivedCameras.length} label="cameras" />
							</div>
							<p className="mt-2 text-[10px] leading-relaxed text-slate-500">
								Cameras are automatic and cannot be selected separately.
							</p>
						</div>
					</div>

					<div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-800 pt-4">
						<button
							type="button"
							data-testid="creative-setup-autofill"
							disabled={busy}
							onClick={handleUseRecommendation}
							className="rounded-lg border border-indigo-400/40 bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-100 hover:bg-indigo-500/20 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{busy ? "Loading…" : "Use recommended plan"}
						</button>
						<button
							type="button"
							data-testid="creative-setup-save"
							disabled={busy || !canSave}
							onClick={handleSave}
							className="rounded-lg bg-teal-600 px-4 py-2 text-xs font-semibold text-white hover:bg-teal-500 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500"
						>
							{busy ? "Saving…" : saved ? "Save changes" : "Save plan"}
						</button>
						{canReview && (
							<>
								<button
									type="button"
									data-testid="creative-setup-approve"
									disabled={busy}
									onClick={() => handleReview("APPROVE")}
									className="rounded-lg border border-emerald-500/50 px-3 py-2 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/10 disabled:opacity-50"
								>
									Approve plan
								</button>
								<button
									type="button"
									data-testid="creative-setup-reject"
									disabled={busy}
									onClick={() => handleReview("REJECT")}
									className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-400 hover:text-red-200 disabled:opacity-50"
								>
									Reject
								</button>
							</>
						)}
						{saved?.status === "DRAFT" && hasChanges && (
							<span className="text-[11px] text-amber-300">
								Save changes before review.
							</span>
						)}
						{!selectionReady && (
							<span className="text-[11px] text-amber-300">
								Select at least one avatar and one scene.
							</span>
						)}
					</div>

					{setup.review_required && (
						<p className="mt-3 text-xs text-amber-300" role="status">
							A verified product category is required before this plan can be saved.
						</p>
					)}
					{error && (
						<p className="mt-3 text-xs font-medium text-red-300" role="alert">
							{error}
						</p>
					)}
				</>
			) : null}
		</div>
	);
}

function AvatarPicker({
	selected,
	recommended,
	library,
	onToggle,
}: {
	selected: string[];
	recommended: RecommendedAvatar[];
	library: AvatarLibraryItem[];
	onToggle: (code: string) => void;
}) {
	const recommendedChoices: { code: string; name?: string; fit?: number }[] = recommended.length
		? recommended.map((avatar) => ({
				code: avatar.avatar_code,
				name: avatar.character_name,
				fit: avatar.fit_score,
			}))
		: library
				.filter((avatar) => avatar.recommended)
				.map((avatar) => ({
					code: avatar.avatar_code,
					name: avatar.character_name,
				}));
	const recommendedCodes = new Set(recommendedChoices.map((avatar) => avatar.code));
	const extraChoices = library.filter(
		(avatar) => !recommendedCodes.has(avatar.avatar_code),
	);

	return (
		<div data-testid="creative-setup-avatar" className="mt-3">
			{recommendedChoices.length === 0 ? (
				<p className="rounded-lg bg-slate-950/50 px-3 py-2 text-xs text-slate-500">
					No recommended avatars for this product.
				</p>
			) : (
				<div
					data-testid="creative-setup-avatar-recommended"
					className="grid gap-2 sm:grid-cols-2"
				>
					{recommendedChoices.map((avatar) => (
						<AvatarChoice
							key={avatar.code}
							code={avatar.code}
							name={avatar.name}
							fit={avatar.fit}
							checked={selected.includes(avatar.code)}
							onChange={() => onToggle(avatar.code)}
						/>
					))}
				</div>
			)}

			{extraChoices.length > 0 && (
				<details className="mt-3 rounded-lg border border-slate-800 bg-slate-950/40">
					<summary className="cursor-pointer list-none px-3 py-2 text-[11px] font-semibold text-slate-400 hover:text-slate-200">
						Browse all avatars ({extraChoices.length} more)
					</summary>
					<div
						data-testid="creative-setup-avatar-library"
						className="grid gap-1 border-t border-slate-800 p-2 sm:grid-cols-2"
					>
						{extraChoices.map((avatar) => (
							<AvatarChoice
								key={avatar.avatar_code}
								code={avatar.avatar_code}
									name={avatar.character_name}
									checked={selected.includes(avatar.avatar_code)}
									onChange={() => onToggle(avatar.avatar_code)}
							/>
						))}
					</div>
				</details>
			)}
		</div>
	);
}

function AvatarChoice({
	code,
	name,
	fit,
	checked,
	onChange,
}: {
	code: string;
	name?: string;
	fit?: number;
	checked: boolean;
	onChange: () => void;
}) {
	return (
		<label
			className={`flex min-w-0 cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-2 transition-colors ${
				checked
					? "border-indigo-400/60 bg-indigo-500/15"
					: "border-slate-800 bg-slate-950/50 hover:border-slate-700 hover:bg-slate-800/60"
			}`}
		>
			<input
				type="checkbox"
				className="mt-0.5 accent-indigo-500"
				checked={checked}
				onChange={onChange}
			/>
			<span className="min-w-0 flex-1">
				<span className="block truncate text-xs font-semibold text-slate-100" title={code}>
					{name || code}
				</span>
				<span className="mt-0.5 flex flex-wrap items-center gap-1 text-[10px] text-slate-500">
					<span className="font-mono">{code}</span>
					{fit != null && (
						<span className="rounded bg-slate-800 px-1.5 py-0.5 text-indigo-200">
							fit {Math.round(fit * 100)}%
						</span>
					)}
				</span>
			</span>
		</label>
	);
}

function SceneChoice({
	template,
	camera,
	checked,
	onChange,
}: {
	template: ScenePromptTemplate;
	camera?: string;
	checked: boolean;
	onChange: () => void;
}) {
	const description = [template.main_action, template.setting]
		.filter(Boolean)
		.join(" · ");

	return (
		<label
			className={`flex min-w-0 cursor-pointer items-start gap-2 rounded-lg border px-2.5 py-2 transition-colors ${
				checked
					? "border-violet-400/60 bg-violet-500/15"
					: "border-slate-800 bg-slate-950/50 hover:border-slate-700 hover:bg-slate-800/60"
			}`}
			title={description || template.template_id}
		>
			<input
				type="checkbox"
				className="mt-0.5 accent-violet-500"
				checked={checked}
				onChange={onChange}
			/>
			<span className="min-w-0 flex-1">
				<span className="flex flex-wrap items-center gap-1.5">
					<span className="font-mono text-[10px] text-violet-200">
						{template.template_id}
					</span>
					{template.variant && (
						<span className="text-[10px] font-semibold text-slate-300">
							{template.variant}
						</span>
					)}
					{camera && (
						<span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-teal-200">
							camera {camera}
						</span>
					)}
				</span>
				{description && (
					<span className="mt-1 block line-clamp-2 text-[11px] leading-relaxed text-slate-400">
						{description}
					</span>
				)}
			</span>
		</label>
	);
}

function SummaryMetric({ value, label }: { value: number; label: string }) {
	return (
		<div className="rounded-lg bg-slate-950/50 px-1.5 py-2">
			<div className="text-lg font-bold text-white">{value}</div>
			<div className="text-[9px] uppercase tracking-wide text-slate-500">{label}</div>
		</div>
	);
}

function savedList(list: string[] | undefined, primary: string | null | undefined) {
	if (list !== undefined) return unique(list);
	return primary ? [primary] : [];
}

function unique(values: string[]) {
	return Array.from(new Set(values.filter(Boolean)));
}

function sameSet(left: string[], right: string[]) {
	const uniqueLeft = unique(left);
	const uniqueRight = unique(right);
	return uniqueLeft.length === uniqueRight.length && uniqueLeft.every((value) => uniqueRight.includes(value));
}

/** Build scene_template_id → camera_preset_code from a recipe response. */
function buildSceneCameraMap(
	recipes:
		| {
				recipes?: Array<{
					scene_template_id?: string;
					camera_preset_code?: string;
				}>;
				recommended_pretick?: Array<{
					scene_template_id?: string;
					camera_preset_code?: string;
				}>;
		  }
		| null
		| undefined,
): Record<string, string> {
	const map: Record<string, string> = {};
	const all = [
		...(recipes?.recipes ?? []),
		...(recipes?.recommended_pretick ?? []),
	];
	for (const recipe of all) {
		if (
			recipe.scene_template_id &&
			recipe.camera_preset_code &&
			!map[recipe.scene_template_id]
		) {
			map[recipe.scene_template_id] = recipe.camera_preset_code;
		}
	}
	return map;
}
