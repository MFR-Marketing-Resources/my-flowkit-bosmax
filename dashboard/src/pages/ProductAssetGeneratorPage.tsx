import { useState } from "react";
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

function createInitialDraft(): ProductAssetGeneratorDraft {
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
	};
}

export default function ProductAssetGeneratorPage() {
	const [draft, setDraft] =
		useState<ProductAssetGeneratorDraft>(createInitialDraft);
	const [result, setResult] = useState<ProductAssetGeneratorResponse | null>(
		null,
	);
	const [analysisSignature, setAnalysisSignature] = useState<string | null>(
		null,
	);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

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
