import { ImageIcon, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchPosterReadiness } from "../api/posterReadiness";
import { fetchProductCatalog } from "../api/products";
import PosterBuilderShellForm from "../components/poster/PosterBuilderShellForm";
import PosterReadinessStatusCard from "../components/poster/PosterReadinessStatusCard";
import PosterRepairActionCenter from "../components/poster/PosterRepairActionCenter";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import {
	isGenerateButtonDisabled,
	resolveBuilderShellMode,
	resolveGenerateButtonLabel,
	shouldShowHumanReviewPanel,
	shouldShowRepairActionCenter,
} from "../poster/posterBuilderUi";
import type { Product } from "../types";
import {
	EMPTY_POSTER_DRAFT,
	type PosterBuilderDraft,
	type PosterReadinessResponse,
} from "../types/posterReadiness";

const TARGET_PRESETS: { label: string; id: string }[] = [
	{ label: "Bosmax Oil 10 ML", id: "b460ffbd-7d9d-4f6b-a570-0e9b1056439a" },
	{ label: "Bosmax Herbs 5 ML", id: "90349f8c-9e14-4efe-988e-76ec60ea31f4" },
	{
		label: "Minyak Warisan 25ml",
		id: "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
	},
];

function productThumb(product: Product): string | null {
	return product.image_analysis?.image_url ?? null;
}

export default function PosterBuilderPage() {
	const [searchParams, setSearchParams] = useSearchParams();
	const [products, setProducts] = useState<Product[]>([]);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [readiness, setReadiness] = useState<PosterReadinessResponse | null>(null);
	const [draft, setDraft] = useState<PosterBuilderDraft>(EMPTY_POSTER_DRAFT);
	const [loadingReadiness, setLoadingReadiness] = useState(false);
	const [error, setError] = useState<string>("");
	const [catalogError, setCatalogError] = useState<string>("");

	useEffect(() => {
		void fetchProductCatalog(500)
			.then((response) => setProducts(response.items ?? []))
			.catch((err: Error) =>
				setCatalogError(err.message || "Failed to load product catalog."),
			);
	}, []);

	useEffect(() => {
		const productId = searchParams.get("product_id");
		if (!productId || products.length === 0) return;
		const match = products.find((p) => p.id === productId);
		if (match) setSelectedProduct(match);
	}, [searchParams, products]);

	const loadReadiness = async (product: Product) => {
		setLoadingReadiness(true);
		setError("");
		setReadiness(null);
		try {
			const payload = await fetchPosterReadiness(product.id);
			setReadiness(payload);
		} catch (err) {
			const message =
				err instanceof Error ? err.message : "Failed to load poster readiness.";
			setError(message);
		} finally {
			setLoadingReadiness(false);
		}
	};

	useEffect(() => {
		if (!selectedProduct) {
			setReadiness(null);
			return;
		}
		const current = searchParams.get("product_id");
		if (current !== selectedProduct.id) {
			setSearchParams({ product_id: selectedProduct.id }, { replace: true });
		}
		void loadReadiness(selectedProduct);
		// eslint-disable-next-line react-hooks/exhaustive-deps -- refetch when product id changes only
	}, [selectedProduct?.id]);

	const shellMode = useMemo(
		() => (readiness ? resolveBuilderShellMode(readiness) : "hidden"),
		[readiness],
	);

	const generateLabel = readiness
		? resolveGenerateButtonLabel(readiness)
		: "Select a product";

	return (
		<div className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
			<header className="flex flex-wrap items-start justify-between gap-4">
				<div>
					<div className="flex items-center gap-2 text-blue-300">
						<ImageIcon size={20} />
						<span className="text-[10px] font-bold uppercase tracking-[0.2em]">
							Creative
						</span>
					</div>
					<h1 className="mt-1 text-2xl font-bold text-slate-100">Poster Builder</h1>
					<p className="mt-2 max-w-2xl text-sm text-slate-400">
						Select a product, then readiness is loaded from{" "}
						<code className="text-xs text-slate-300">
							GET /api/products/&#123;id&#125;/poster-readiness
						</code>
						. The UI does not infer readiness locally.
					</p>
				</div>
				{selectedProduct && readiness ? (
					<button
						type="button"
						onClick={() => void loadReadiness(selectedProduct)}
						className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300 hover:border-blue-500/40"
					>
						<RefreshCw size={14} className={loadingReadiness ? "animate-spin" : ""} />
						Recheck readiness
					</button>
				) : null}
			</header>

			{catalogError ? (
				<p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
					{catalogError}
				</p>
			) : null}

			<section className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
				<p className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
					Product
				</p>
				<div className="mt-3 max-w-xl">
					<SearchableProductSelect
						products={products}
						selectedProduct={selectedProduct}
						onSelect={setSelectedProduct}
					/>
				</div>
				{selectedProduct ? (
					<div className="mt-4 flex flex-wrap items-center gap-4 text-xs text-slate-400">
						<span>ID: {selectedProduct.id}</span>
						<span>Category: {selectedProduct.category || "—"}</span>
						<span>
							Source:{" "}
							{selectedProduct.source_label ||
								selectedProduct.source_lane ||
								selectedProduct.source}
						</span>
						{productThumb(selectedProduct) ? (
							<img
								src={productThumb(selectedProduct)!}
								alt=""
								className="h-12 w-12 rounded-lg border border-slate-800 object-cover"
							/>
						) : null}
					</div>
				) : null}
				<div className="mt-4 flex flex-wrap gap-2">
					{TARGET_PRESETS.map((preset) => (
						<button
							key={preset.id}
							type="button"
							onClick={() => {
								const found = products.find((p) => p.id === preset.id);
								if (found) setSelectedProduct(found);
								else
									setError(
										`${preset.label} not in loaded catalog page — search by name.`,
									);
							}}
							className="rounded-lg border border-slate-800 px-2 py-1 text-[10px] text-slate-400 hover:border-slate-600"
						>
							{preset.label}
						</button>
					))}
				</div>
			</section>

			{loadingReadiness ? (
				<p className="text-sm text-slate-400">Loading poster readiness…</p>
			) : null}

			{error ? (
				<p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
					{error}
				</p>
			) : null}

			{readiness ? (
				<>
					<PosterReadinessStatusCard readiness={readiness} />

					{shouldShowHumanReviewPanel(readiness) ? (
						<section className="rounded-2xl border border-rose-500/40 bg-rose-950/30 p-5">
							<h3 className="text-sm font-bold text-rose-100">Human review required</h3>
							<p className="mt-2 text-sm text-rose-100/80">
								Poster builder is hidden until hard blockers are resolved.
							</p>
						</section>
					) : null}

					{shouldShowRepairActionCenter(readiness) ? (
						<PosterRepairActionCenter actions={readiness.repair_actions} />
					) : null}

					{shellMode !== "hidden" ? (
						<PosterBuilderShellForm
							draft={draft}
							onChange={setDraft}
							mode={shellMode}
							generateButtonLabel={generateLabel}
						/>
					) : null}

					<section className="rounded-2xl border border-slate-800 bg-slate-950/40 p-5">
						<h3 className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
							Draft JSON preview
						</h3>
						<pre className="mt-2 max-h-64 overflow-auto text-[10px] text-slate-400">
							{JSON.stringify(
								{
									draft,
									readiness_meta: {
										poster_status: readiness.poster_status,
										generation_allowed: readiness.generation_allowed,
										generate_disabled_reason: generateLabel,
										generate_disabled: isGenerateButtonDisabled(readiness),
									},
								},
								null,
								2,
							)}
						</pre>
					</section>
				</>
			) : null}
		</div>
	);
}