import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { runProductAssetGeneratorPreview } from "../api/productAssetGenerator";
import ProductAssetGeneratorForm, {
	buildProductAssetGeneratorRequest,
} from "../components/product-asset-generator/ProductAssetGeneratorForm";
import ProductAssetGeneratorResultPanel from "../components/product-asset-generator/ProductAssetGeneratorResultPanel";
import {
	getProductAssetGeneratorPreset,
	PRODUCT_ASSET_GENERATOR_PRESETS,
} from "../components/product-asset-generator/presets";
import type {
	ProductAssetGeneratorRequest,
	ProductAssetGeneratorResponse,
} from "../types";

export type { ProductAssetGeneratorPresetDefinition } from "../components/product-asset-generator/presets";
// Re-export preset registry so existing imports from this page continue to work
export { getProductAssetGeneratorPreset, PRODUCT_ASSET_GENERATOR_PRESETS };

type ProductAssetGeneratorDraft = ProductAssetGeneratorRequest & {
	product_payload_text: string;
};

function createInitialDraft(
	preset: { draftPatch?: Partial<ProductAssetGeneratorDraft> } | null = null,
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
	// ?preset= hydration: initial preset comes from query param on first load
	const initialPresetId = searchParams.get("preset");
	const [selectedPresetId, setSelectedPresetId] = useState<string>(
		initialPresetId || "",
	);
	const activePreset = useMemo(
		() => getProductAssetGeneratorPreset(selectedPresetId || null),
		[selectedPresetId],
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

	// When preset changes, patch the draft with preset defaults while preserving product selection
	useEffect(() => {
		setDraft((current) => ({
			...createInitialDraft(activePreset),
			product_id: current.product_id,
			product_payload_text: current.product_payload_text,
		}));
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

	// Block submit when the active preset requires a database product but none is selected
	const presetRequiresProductButMissing =
		Boolean(activePreset?.requiresDatabaseProduct) && !draft.product_id;

	return (
		<div className="flex flex-col gap-6 p-4 md:p-6">
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="flex flex-wrap items-center justify-between gap-3">
					<div>
						<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
							Product Asset Generator
						</div>
						<div className="mt-1 text-[11px] text-slate-400">
							Preview-only · No image generation · No Flow execution
							{activePreset ? (
								<span className="ml-2 inline-flex rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.14em] text-emerald-200">
									{activePreset.label}
								</span>
							) : null}
						</div>
					</div>
					<Link
						to={creativeLibraryRoute}
						className="inline-flex items-center justify-center rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-300 hover:border-blue-500/40 hover:text-blue-200"
					>
						Creative Library →
					</Link>
				</div>
			</section>

			<div className="grid gap-6 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)]">
				{/* LEFT: inputs (Step 1) → preset dropdown (Step 2) → submit (Step 3) */}
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
					activePreset={activePreset}
					selectedPresetId={selectedPresetId}
					onPresetChange={(presetId) => setSelectedPresetId(presetId)}
					presetRequiresProductButMissing={presetRequiresProductButMissing}
				/>
				{/* Step 4: Result panel */}
				<ProductAssetGeneratorResultPanel result={result} />
			</div>
		</div>
	);
}
