import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { runProductAssetGeneratorPreview } from "../api/productAssetGenerator";
import ProductAssetGeneratorForm, {
	buildProductAssetGeneratorRequest,
} from "../components/product-asset-generator/ProductAssetGeneratorForm";
import ProductAssetGeneratorResultPanel from "../components/product-asset-generator/ProductAssetGeneratorResultPanel";
import type {
	ProductAssetGeneratorRequest,
	ProductAssetGeneratorResponse,
} from "../types";

type ProductAssetGeneratorDraft = ProductAssetGeneratorRequest & {
	product_payload_text: string;
};

type ProductAssetGeneratorPresetDefinition = {
	id: string;
	label: string;
	family: "PRODUCT_ONLY" | "HUMAN_PLUS_PRODUCT" | "PRODUCT_PLUS_SCENE";
	description: string;
	requiredInputs: string[];
	requiresDatabaseProduct: boolean;
	guidance: string;
	draftPatch: Partial<ProductAssetGeneratorDraft>;
};

export const PRODUCT_ASSET_GENERATOR_PRESETS: ProductAssetGeneratorPresetDefinition[] =
	[
		{
			id: "ecommerce_hero_clean_studio",
			label: "Ecommerce Hero / Clean Studio",
			family: "PRODUCT_ONLY",
			description:
				"Clean catalog-first product image lane with label-safe framing and scale truth anchored to the product row.",
			requiredInputs: ["Database product"],
			requiresDatabaseProduct: true,
			guidance:
				"Use the product row so package form, product physics, and scale truth stay locked before prompt preview.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "ecommerce_hero_soft_shadow",
			label: "Ecommerce Hero / Soft Shadow",
			family: "PRODUCT_ONLY",
			description:
				"Hero product still with softer depth cues while preserving front-label truth and compact commercial framing.",
			requiredInputs: ["Database product"],
			requiresDatabaseProduct: true,
			guidance:
				"Still use database product truth so the model does not hallucinate a larger or smaller pack.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "product_packshot_front_label",
			label: "Product Packshot / Front Label",
			family: "PRODUCT_ONLY",
			description:
				"Front-facing packshot preset for products that must keep label and silhouette readable in a single frame.",
			requiredInputs: ["Database product"],
			requiresDatabaseProduct: true,
			guidance:
				"Best for label-safe hero output where the product row is the sovereign source of packaging truth.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "product_flatlay_clean",
			label: "Product Flatlay / Clean",
			family: "PRODUCT_ONLY",
			description:
				"Top-down flatlay preparation lane for product-only compositions and clean merchandising layouts.",
			requiredInputs: ["Database product"],
			requiresDatabaseProduct: true,
			guidance:
				"Use this when you want product-first styling without character interaction but still need size discipline.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "avatar_holding_product_halfbody",
			label: "Avatar Holding Product / Half Body",
			family: "HUMAN_PLUS_PRODUCT",
			description:
				"Half-body creator lane where scale truth, hand grip, and torso-to-product proportion must stay believable.",
			requiredInputs: ["Database product", "Character reference"],
			requiresDatabaseProduct: true,
			guidance:
				"Product-holding presets require database product truth so physics DNA, grip hints, and scale prompts can lock the object.",
			draftPatch: {
				target_asset_intent: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: true,
				strict_validation: true,
			},
		},
		{
			id: "avatar_holding_product_closeup",
			label: "Avatar Holding Product / Closeup",
			family: "HUMAN_PLUS_PRODUCT",
			description:
				"Close framing for hand-product interaction where the product must stay readable without inflating the pack.",
			requiredInputs: ["Database product", "Character reference"],
			requiresDatabaseProduct: true,
			guidance:
				"Best when the hand and pack share the frame. Use database product truth before asking the model to scale the hold.",
			draftPatch: {
				target_asset_intent: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: true,
				strict_validation: true,
			},
		},
		{
			id: "avatar_seated_with_product_tabletop",
			label: "Avatar Seated / Tabletop Product",
			family: "HUMAN_PLUS_PRODUCT",
			description:
				"Tabletop creator composition where the product stays readable on-surface with a visible human anchor.",
			requiredInputs: [
				"Database product",
				"Character reference",
				"Scene reference",
			],
			requiresDatabaseProduct: true,
			guidance:
				"Use this when you want a gentler lifestyle scene but still need product size truth and surface placement discipline.",
			draftPatch: {
				target_asset_intent: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: true,
				strict_validation: true,
			},
		},
		{
			id: "creator_lifestyle_with_product_scene",
			label: "Creator Lifestyle / Product Scene",
			family: "PRODUCT_PLUS_SCENE",
			description:
				"Blend creator, product, and scene while keeping product truth sovereign over atmosphere and styling.",
			requiredInputs: [
				"Database product",
				"Character reference",
				"Scene reference",
			],
			requiresDatabaseProduct: true,
			guidance:
				"Use product row truth first, then let scene and creator references influence only the surrounding composition.",
			draftPatch: {
				target_asset_intent: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: true,
				strict_validation: true,
			},
		},
		{
			id: "hand_only_product_hold_macro",
			label: "Hand Only / Product Hold Macro",
			family: "HUMAN_PLUS_PRODUCT",
			description:
				"Macro-style hand focus where grip, label orientation, and object scale are the primary success criteria.",
			requiredInputs: ["Database product"],
			requiresDatabaseProduct: true,
			guidance:
				"Use this when the product must be held but the face is not the main subject. Scale drift is the main failure mode here.",
			draftPatch: {
				target_asset_intent: "CHARACTER_HOLDING_PRODUCT_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: true,
				strict_validation: true,
			},
		},
		{
			id: "product_on_counter_lifestyle",
			label: "Product On Counter / Lifestyle",
			family: "PRODUCT_PLUS_SCENE",
			description:
				"Scene-led product composition with environment cues while the product remains the visual anchor.",
			requiredInputs: ["Database product", "Scene reference"],
			requiresDatabaseProduct: true,
			guidance:
				"Scene should decorate around the product. Database product truth still governs size, label, and packaging edges.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "product_on_shelf_lifestyle",
			label: "Product On Shelf / Lifestyle",
			family: "PRODUCT_PLUS_SCENE",
			description:
				"Shelf or rack context preset where the product must stay correctly proportioned relative to its environment.",
			requiredInputs: ["Database product", "Scene reference"],
			requiresDatabaseProduct: true,
			guidance:
				"Use this for contextual merchandising where environment helps mood but must not distort product dimensions.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
		{
			id: "product_scene_style_blend",
			label: "Product + Scene + Style Blend",
			family: "PRODUCT_PLUS_SCENE",
			description:
				"Blend route for product, scene, and style references where the product remains the sovereign anchor and style stays secondary.",
			requiredInputs: [
				"Database product",
				"Scene reference",
				"Style reference",
			],
			requiresDatabaseProduct: true,
			guidance:
				"Use this when you already have scene or style inspiration but do not want the model to mutate the product pack.",
			draftPatch: {
				target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
				target_destination_mode: "IMAGE",
				include_product_in_hand: false,
				strict_validation: true,
			},
		},
	];

export function getProductAssetGeneratorPreset(
	presetId: string | null,
): ProductAssetGeneratorPresetDefinition | null {
	if (!presetId) {
		return null;
	}
	return (
		PRODUCT_ASSET_GENERATOR_PRESETS.find((preset) => preset.id === presetId) ||
		null
	);
}

function createInitialDraft(
	preset: ProductAssetGeneratorPresetDefinition | null = null,
): ProductAssetGeneratorDraft {
	return {
		product_id: "",
		product_payload_text: "",
		target_asset_intent: "PRODUCT_LIFESTYLE_IMAGE_PROMPT",
		gender: "",
		ethnicity: "",
		age_range: "",
		scene_context: "",
		platform: "TikTok",
		language: "Malay",
		camera_style: "",
		camera_behavior: "",
		wardrobe: "",
		headwear: "",
		include_product_in_hand: false,
		target_destination_mode: "IMAGE",
		strict_validation: false,
		dry_run_only: true,
		...(preset?.draftPatch || {}),
	};
}

export default function ProductAssetGeneratorPage() {
	const location = useLocation();
	const searchParams = useMemo(
		() => new URLSearchParams(location.search),
		[location.search],
	);
	const activePreset = useMemo(
		() => getProductAssetGeneratorPreset(searchParams.get("preset")),
		[searchParams],
	);
	const [draft, setDraft] = useState<ProductAssetGeneratorDraft>(() =>
		createInitialDraft(activePreset),
	);
	const [result, setResult] = useState<ProductAssetGeneratorResponse | null>(
		null,
	);
	const [analysisSignature, setAnalysisSignature] = useState<string | null>(
		null,
	);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const creativeLibraryRoute =
		searchParams.get("portal") === "side"
			? "/assets/creative-library?portal=side"
			: "/assets/creative-library";
	const presetPortalSuffix =
		searchParams.get("portal") === "side" ? "&portal=side" : "";

	useEffect(() => {
		setDraft(createInitialDraft(activePreset));
		setResult(null);
		setAnalysisSignature(null);
		setError(null);
	}, [activePreset]);

	async function handleSubmit() {
		setLoading(true);
		setError(null);
		try {
			const request = buildProductAssetGeneratorRequest(draft);
			const preview = await runProductAssetGeneratorPreview(request);
			setResult(preview);
			setAnalysisSignature(JSON.stringify(request));
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to run product asset generator preview",
			);
		} finally {
			setLoading(false);
		}
	}

	return (
		<div className="flex flex-col gap-6 p-4 md:p-6">
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
					Product Asset Generator Preview
				</div>
				<div className="mt-2 max-w-4xl text-sm text-slate-300">
					Product row or payload becomes preview-only asset suggestions and
					prompt suggestions. No real image generation, no upload, no Google
					Flow execution, and no Chrome extension execution happen here.
				</div>
				<div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
					{[
						"Preview is offline-only",
						"No real image generation",
						"No Google Flow execution",
						"No Chrome extension execution",
					].map((item) => (
						<div
							key={item}
							className="rounded-2xl border border-slate-800 bg-slate-900/60 px-3 py-3 text-[11px] text-slate-300"
						>
							{item}
						</div>
					))}
				</div>
				<div className="mt-3 flex flex-col gap-3 rounded-2xl border border-slate-800 bg-slate-900/60 p-3 text-[11px] text-slate-300 md:flex-row md:items-center md:justify-between">
					<div className="bosmax-wrap-safe">
						This page is preview-only. To persist reusable generated/external
						images, upload or save them in Creative Library.
					</div>
					<Link
						to={creativeLibraryRoute}
						className="inline-flex items-center justify-center rounded-xl border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-blue-200"
					>
						Open Creative Library
					</Link>
				</div>
				<div className="mt-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
					<div className="flex flex-wrap items-start justify-between gap-3">
						<div>
							<div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
								Preset Guided Workflow
							</div>
							<div className="mt-2 max-w-3xl text-[11px] text-slate-300">
								Preset selection only configures the preview lane. Database
								product truth remains the primary source for scale truth,
								product physics, handling cues, and label-safe framing.
							</div>
						</div>
						{activePreset ? (
							<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200">
								ACTIVE PRESET: {activePreset.label}
							</span>
						) : (
							<span className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300">
								NO PRESET LOCKED
							</span>
						)}
					</div>
					{activePreset ? (
						<div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
							<div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
								<div className="text-sm font-semibold text-slate-100">
									{activePreset.label}
								</div>
								<div className="mt-2 text-[11px] text-slate-300">
									{activePreset.description}
								</div>
								<div className="mt-3 grid gap-2 text-[11px] text-slate-300 md:grid-cols-2">
									<div>Preset ID: {activePreset.id}</div>
									<div>Family: {activePreset.family}</div>
									<div>
										Target Intent: {draft.target_asset_intent || "NOT_SET"}
									</div>
									<div>
										Target Mode: {draft.target_destination_mode || "NOT_SET"}
									</div>
									<div>
										Product In Hand:{" "}
										{draft.include_product_in_hand ? "REQUIRED" : "NO"}
									</div>
									<div>
										Database Product:{" "}
										{activePreset.requiresDatabaseProduct
											? "REQUIRED"
											: "OPTIONAL"}
									</div>
								</div>
								<div className="mt-3 rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-3 text-[11px] text-amber-100">
									{activePreset.guidance}
								</div>
							</div>
							<div className="space-y-3 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
								<div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
									Required Inputs
								</div>
								<div className="flex flex-wrap gap-2">
									{activePreset.requiredInputs.map((item) => (
										<span
											key={item}
											className="rounded-full border border-slate-700 bg-slate-900 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300"
										>
											{item}
										</span>
									))}
								</div>
								<div className="text-[11px] text-slate-300">
									If the preset carries a product in hand, pick a database
									product first. That lets the preview engine resolve package
									form, scale cues, physics DNA, and handling notes before the
									prompt is composed.
								</div>
								<div className="flex flex-wrap gap-2">
									{PRODUCT_ASSET_GENERATOR_PRESETS.map((preset) => (
										<Link
											key={preset.id}
											to={`/product-asset-generator?preset=${preset.id}${presetPortalSuffix}`}
											className={`rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] ${preset.id === activePreset.id ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-slate-700 bg-slate-950 text-slate-300"}`}
										>
											{preset.label}
										</Link>
									))}
								</div>
							</div>
						</div>
					) : (
						<div className="mt-4 rounded-xl border border-dashed border-slate-700 bg-slate-950/50 px-3 py-3 text-[11px] text-slate-400">
							No preset is active. Launch from Creative Library if you want a
							governed preset, or stay on the generic preview lane here.
						</div>
					)}
				</div>
			</section>

			<div className="grid gap-6 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)]">
				<ProductAssetGeneratorForm
					draft={draft}
					onChange={(patch) =>
						setDraft((current) => ({
							...current,
							...patch,
							dry_run_only: true,
						}))
					}
					onSubmit={handleSubmit}
					loading={loading}
					error={error}
					result={result}
					analysisSignature={analysisSignature}
				/>
				<ProductAssetGeneratorResultPanel result={result} />
			</div>
		</div>
	);
}
