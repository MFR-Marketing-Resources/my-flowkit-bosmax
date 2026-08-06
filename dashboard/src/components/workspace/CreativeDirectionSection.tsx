/**
 * CreativeDirectionSection — the ONE reusable, descriptor-based creative-direction
 * control shared by every generation lane (T2V/F2V/Hybrid/I2V, IMG, Poster).
 *
 * RECIPE MODEL (owner architecture, 2026-08-06):
 *  - A creative direction is a set of COHERENT recipes — each recipe is one
 *    (avatar, scene, camera) tuple where the CAMERA FOLLOWS THE SCENE (resolved by the
 *    scene->variation->camera bridge on the backend). It is NEVER three independent flat
 *    lists with a fill-all default — that let operators build incoherent combos (a
 *    wrong-gender avatar, a cooking product with an office-clothes scene, a camera that
 *    does not match the scene) that waste generation credits.
 *  - Avatars are gender+cluster filtered and scenes are cluster filtered on the backend,
 *    so every recipe row is already product-appropriate.
 *  - "Smart suggest" ticks a capped, arc-spread set of coherent recipes (intro -> body ->
 *    detail -> benefit); the full pool stays available for manual override / mass rotation.
 *  - These are TEXT descriptors, never image pickers; image references (I2V/F2V/HYBRID)
 *    live in their own opt-in section (CanonicalReferenceBindingControls).
 *
 * The component keeps emitting the backward-compatible CreativeDirection (three derived
 * code lists) PLUS the selected coherent `recipes`, so existing consumers (T2V wires the
 * primary avatar) keep working while the compiler wiring (later) consumes the tuples.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import {
	getProductRecipes,
	type CreativeRecipe,
} from "../../api/creativeIntelligence";

export type { CreativeRecipe };

export interface CreativeDirection {
	avatarCodes: string[];
	sceneTemplateIds: string[];
	cameraPresetCodes: string[];
	/** The selected coherent (avatar, scene, camera) tuples — the source of truth. */
	recipes: CreativeRecipe[];
}

export const EMPTY_CREATIVE_DIRECTION: CreativeDirection = {
	avatarCodes: [],
	sceneTemplateIds: [],
	cameraPresetCodes: [],
	recipes: [],
};

function recipeKey(recipe: CreativeRecipe): string {
	// camera is derived from the scene, so (avatar, scene) uniquely identifies a recipe
	return `${recipe.avatar_code}||${recipe.scene_template_id}`;
}

function uniq(values: string[]): string[] {
	return Array.from(new Set(values.filter(Boolean)));
}

/** Derive the backward-compatible 3 code lists from the selected coherent recipes. */
function directionFromRecipes(recipes: CreativeRecipe[]): CreativeDirection {
	return {
		avatarCodes: uniq(recipes.map((r) => r.avatar_code)),
		sceneTemplateIds: uniq(recipes.map((r) => r.scene_template_id)),
		cameraPresetCodes: uniq(recipes.map((r) => r.camera_preset_code)),
		recipes,
	};
}

function genderTag(code: string): string {
	if (code.includes("_F_")) return "♀";
	if (code.includes("_M_")) return "♂";
	return "";
}

function sceneLabel(recipe: CreativeRecipe): string {
	const variant = recipe.scene_variant.replace(/^Variation\s*\d+\s*[-:]\s*/i, "").trim();
	const varTag = recipe.variation != null ? `Var${recipe.variation}` : "scene";
	return variant ? `${varTag} · ${variant}` : `${varTag} · ${recipe.scene_template_id}`;
}

export default function CreativeDirectionSection({
	productId,
	value,
	onChange,
}: {
	productId: string | null;
	value: CreativeDirection;
	onChange: (next: CreativeDirection) => void;
}) {
	const [pool, setPool] = useState<CreativeRecipe[]>([]);
	const [pretick, setPretick] = useState<CreativeRecipe[]>([]);
	const [cluster, setCluster] = useState<string | null>(null);
	const [reviewRequired, setReviewRequired] = useState(false);
	const [loading, setLoading] = useState(false);
	// Re-seed on a genuine product SWITCH (the old selection was for the old product);
	// respect a caller-provided selection only on first mount.
	const seededProductId = useRef<string | null>(null);

	useEffect(() => {
		if (!productId) {
			setPool([]);
			setPretick([]);
			setCluster(null);
			setReviewRequired(false);
			return;
		}
		let active = true;
		setLoading(true);
		void getProductRecipes(productId)
			.then((res) => {
				if (!active) return;
				setPool(res.recipes);
				setPretick(res.recommended_pretick);
				setCluster(res.cluster);
				setReviewRequired(Boolean(res.review_required));
				const isEmpty = value.recipes.length === 0;
				const firstSeed = seededProductId.current === null;
				seededProductId.current = productId;
				if (firstSeed && !isEmpty) return;
				onChange(directionFromRecipes(res.recommended_pretick));
			})
			.catch(() => {})
			.finally(() => {
				if (active) setLoading(false);
			});
		return () => {
			active = false;
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [productId]);

	const selectedKeys = useMemo(
		() => new Set(value.recipes.map(recipeKey)),
		[value.recipes],
	);

	const byAvatar = useMemo(() => {
		const groups = new Map<string, CreativeRecipe[]>();
		for (const recipe of pool) {
			const list = groups.get(recipe.avatar_code) ?? [];
			list.push(recipe);
			groups.set(recipe.avatar_code, list);
		}
		return Array.from(groups.entries());
	}, [pool]);

	const toggleRecipe = (recipe: CreativeRecipe) => {
		const key = recipeKey(recipe);
		const next = selectedKeys.has(key)
			? value.recipes.filter((r) => recipeKey(r) !== key)
			: [...value.recipes, recipe];
		onChange(directionFromRecipes(next));
	};

	if (!productId) {
		return (
			<p className="text-[11px] text-slate-500">
				Select a product to load its creative direction.
			</p>
		);
	}

	return (
		<div
			data-testid="creative-direction-section"
			className="space-y-3 rounded-lg border border-teal-500/25 bg-teal-500/5 p-3"
		>
			<div className="flex items-center justify-between gap-2">
				<span className="text-xs font-bold text-teal-100">Creative Direction</span>
				<span className="text-[10px] text-slate-400">
					{cluster ? `cluster: ${cluster}` : ""}
				</span>
			</div>
			<p className="text-[10px] leading-relaxed text-slate-400">
				Coherent recipes — each row is one <b>avatar × scene</b> and the{" "}
				<b>camera follows the scene</b> automatically. Avatars are gender/cluster
				correct and scenes fit the product, so no incoherent combos. Text descriptors,
				not image pickers; image references (I2V/F2V/Hybrid) live in their own section.
			</p>

			<div className="flex items-center justify-between gap-2">
				<button
					type="button"
					data-testid="creative-direction-smart-suggest"
					onClick={() => onChange(directionFromRecipes(pretick))}
					disabled={loading || pretick.length === 0}
					className="rounded-md border border-teal-400/40 bg-teal-500/15 px-2.5 py-1 text-[11px] font-semibold text-teal-100 hover:bg-teal-500/25 disabled:opacity-40"
					title="Tick a capped, coherent set spanning the shot arc (intro → body → detail → benefit). The full pool stays available below for manual override."
				>
					⚡ Smart suggest
				</button>
				<span className="text-[10px] text-slate-400" data-testid="creative-direction-summary">
					{value.recipes.length} selected · {pool.length} coherent options
				</span>
			</div>

			{loading ? (
				<p className="text-[11px] text-slate-400">Loading coherent recipes…</p>
			) : reviewRequired ? (
				<p className="text-[11px] text-amber-300">
					This product needs a verified cluster before recipes can be built.
				</p>
			) : pool.length === 0 ? (
				<p className="text-[11px] text-slate-500">
					No coherent recipes for this product yet.
				</p>
			) : (
				<div className="max-h-72 space-y-2 overflow-y-auto rounded border border-slate-800 bg-slate-950/50 p-1.5">
					{byAvatar.map(([avatar, recipes]) => (
						<div key={avatar} className="space-y-0.5">
							<div className="sticky top-0 bg-slate-950/90 px-1 py-0.5 text-[10px] font-bold uppercase tracking-widest text-slate-400">
								{genderTag(avatar)} {avatar}
							</div>
							{recipes.map((recipe) => {
								const key = recipeKey(recipe);
								const checked = selectedKeys.has(key);
								return (
									<label
										key={key}
										data-testid="creative-direction-recipe"
										className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-[11px] text-slate-200 hover:bg-slate-800/60"
									>
										<input
											type="checkbox"
											checked={checked}
											onChange={() => toggleRecipe(recipe)}
										/>
										<span className="flex-1">{sceneLabel(recipe)}</span>
										<span className="text-[10px] text-teal-300" title={recipe.content_type}>
											🎥 {recipe.camera_preset_code || "—"}
										</span>
									</label>
								);
							})}
						</div>
					))}
				</div>
			)}
		</div>
	);
}
