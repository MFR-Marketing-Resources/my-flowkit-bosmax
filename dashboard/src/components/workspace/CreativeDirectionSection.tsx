/**
 * CreativeDirectionSection — the ONE reusable, descriptor-based creative-direction
 * control shared by every generation lane (T2V/F2V/Hybrid/I2V, IMG, Poster).
 *
 * Architecture (senior-architect intent):
 *  - Avatar / Scene strategy-template / Camera preset are TEXT DESCRIPTORS that shape
 *    the generation PROMPT — they are NOT image pickers. The prompt compiler is already
 *    descriptor-based (presenter_prose, scene background text, camera notes), so a text
 *    lane like T2V needs these dropdowns, never avatar/scene thumbnails.
 *  - Every option is PRODUCT-DEPENDENT: loaded from the product's knowledge-driven
 *    creative setup (gender-correct avatars, cluster-correct scenes), pre-filled from the
 *    saved selection else the smart default.
 *  - Image REFERENCES (for I2V/F2V/HYBRID) are a SEPARATE, opt-in sub-section rendered by
 *    those lanes — never here.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import {
	getCreativeSetupForProduct,
	type CreativeSetup,
} from "../../api/creativeIntelligence";

export interface CreativeDirection {
	avatarCodes: string[];
	sceneTemplateIds: string[];
	cameraPresetCodes: string[];
}

export const EMPTY_CREATIVE_DIRECTION: CreativeDirection = {
	avatarCodes: [],
	sceneTemplateIds: [],
	cameraPresetCodes: [],
};

interface Option {
	code: string;
	label: string;
	recommended?: boolean;
}

function MultiPick({
	title,
	options,
	selected,
	onToggle,
	emptyHint,
	testid,
}: {
	title: string;
	options: Option[];
	selected: string[];
	onToggle: (code: string) => void;
	emptyHint: string;
	testid: string;
}) {
	return (
		<div className="space-y-1.5" data-testid={testid}>
			<div className="flex items-center justify-between">
				<span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
					{title}
				</span>
				<span className="text-[10px] text-slate-500">{selected.length} selected</span>
			</div>
			{options.length === 0 ? (
				<p className="text-[11px] text-slate-500">{emptyHint}</p>
			) : (
				<div className="max-h-40 space-y-0.5 overflow-y-auto rounded border border-slate-800 bg-slate-950/50 p-1.5">
					{options.map((o) => (
						<label
							key={o.code}
							className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-[11px] text-slate-200 hover:bg-slate-800/60"
						>
							<input
								type="checkbox"
								checked={selected.includes(o.code)}
								onChange={() => onToggle(o.code)}
							/>
							<span className="flex-1">{o.label}</span>
							{o.recommended ? (
								<span className="text-[10px] text-teal-300">★</span>
							) : null}
						</label>
					))}
				</div>
			)}
		</div>
	);
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
	const [setup, setSetup] = useState<CreativeSetup | null>(null);
	const [loading, setLoading] = useState(false);
	// Tracks which product the current selection was seeded for, so a genuine
	// product SWITCH always re-seeds from the new product's default (the old
	// selection belonged to the old product) while a caller-provided initial
	// value is respected on first mount.
	const seededProductId = useRef<string | null>(null);

	useEffect(() => {
		if (!productId) {
			setSetup(null);
			return;
		}
		let active = true;
		setLoading(true);
		void getCreativeSetupForProduct(productId)
			.then((s) => {
				if (!active) return;
				setSetup(s);
				const isEmpty =
					value.avatarCodes.length === 0 &&
					value.sceneTemplateIds.length === 0 &&
					value.cameraPresetCodes.length === 0;
				const firstSeed = seededProductId.current === null;
				seededProductId.current = productId;
				// On the very first mount, respect a caller-provided selection (e.g. a
				// restored draft). On a product switch, always re-seed from the new
				// product's saved selection, else the smart (gender/cluster-correct)
				// default.
				if (firstSeed && !isEmpty) return;
				const sel = s.saved_selection;
				const def = s.default_selection;
				onChange({
					avatarCodes:
						sel?.selected_avatar_codes ?? def?.selected_avatar_codes ?? [],
					sceneTemplateIds:
						sel?.selected_scene_template_ids ??
						def?.selected_scene_template_ids ??
						[],
					cameraPresetCodes:
						sel?.selected_camera_preset_codes ??
						def?.selected_camera_preset_codes ??
						[],
				});
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

	const avatarOptions = useMemo<Option[]>(
		() =>
			(setup?.avatar_library ?? setup?.recommended_avatars ?? []).map((a) => ({
				code: a.avatar_code,
				label: `${a.avatar_code}${a.character_name ? ` · ${a.character_name}` : ""}`,
				recommended: "recommended" in a ? a.recommended : undefined,
			})),
		[setup],
	);
	const sceneOptions = useMemo<Option[]>(
		() =>
			(setup?.recommended_scene_templates ?? []).map((t) => ({
				code: t.template_id,
				label: `${t.template_id}${t.variant ? ` · ${t.variant}` : ""}`,
			})),
		[setup],
	);
	const cameraOptions = useMemo<Option[]>(
		() =>
			(setup?.camera_library?.named_presets ?? []).map((p) => ({
				code: p.preset_code,
				label: `${p.preset_code}${p.preset_name ? ` · ${p.preset_name}` : ""}`,
			})),
		[setup],
	);

	const toggle = (key: keyof CreativeDirection, code: string) => {
		const cur = value[key];
		const next = cur.includes(code)
			? cur.filter((c) => c !== code)
			: [...cur, code];
		onChange({ ...value, [key]: next });
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
			<div className="flex items-center justify-between">
				<span className="text-xs font-bold text-teal-100">Creative Direction</span>
				<span className="text-[10px] text-slate-400">
					{setup?.cluster ? `cluster: ${setup.cluster}` : ""}
				</span>
			</div>
			<p className="text-[10px] leading-relaxed text-slate-400">
				This product's creative direction — presenter, scene strategy, and camera
				framing — pre-filled from its knowledge base. Text descriptors, not image
				pickers; image references (I2V/F2V/Hybrid) live in their own section. The
				presenter drives the generated prompt today; scene-strategy and camera
				consumption is being wired into the compiler.
			</p>
			{loading ? (
				<p className="text-[11px] text-slate-400">Loading creative direction…</p>
			) : (
				<div className="grid gap-3 md:grid-cols-3">
					<MultiPick
						title="Avatar (presenter)"
						testid="creative-direction-avatar"
						options={avatarOptions}
						selected={value.avatarCodes}
						onToggle={(c) => toggle("avatarCodes", c)}
						emptyHint="No avatar for this product's cluster."
					/>
					<MultiPick
						title="Scene strategy / template"
						testid="creative-direction-scene"
						options={sceneOptions}
						selected={value.sceneTemplateIds}
						onToggle={(c) => toggle("sceneTemplateIds", c)}
						emptyHint="No scene template for this cluster."
					/>
					<MultiPick
						title="Camera preset"
						testid="creative-direction-camera"
						options={cameraOptions}
						selected={value.cameraPresetCodes}
						onToggle={(c) => toggle("cameraPresetCodes", c)}
						emptyHint="No camera preset."
					/>
				</div>
			)}
		</div>
	);
}
