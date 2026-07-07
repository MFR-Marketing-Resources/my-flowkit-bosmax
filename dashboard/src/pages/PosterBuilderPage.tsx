import { ImageIcon, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchPosterReadiness } from "../api/posterReadiness";
import {
	createPosterPromptDraft,
	draftToPromptRequest,
	formatPosterPromptDraftError,
} from "../api/posterPromptDraft";
import { fetchProductCatalog } from "../api/products";
import PosterBuilderShellForm from "../components/poster/PosterBuilderShellForm";
import PosterPromptPackagePreview from "../components/poster/PosterPromptPackagePreview";
import PosterReadinessStatusCard from "../components/poster/PosterReadinessStatusCard";
import PosterRepairActionCenter from "../components/poster/PosterRepairActionCenter";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import {
	isGenerateButtonDisabled,
	isPromptDraftGenerationEnabled,
	resolveBuilderShellMode,
	resolveGenerateButtonLabel,
	resolvePromptDraftButtonLabel,
	shouldShowHumanReviewPanel,
	shouldShowRepairActionCenter,
} from "../poster/posterBuilderUi";
import type { Product } from "../types";
import type { PosterPromptDraftResponse } from "../types/posterPromptDraft";
import {
	EMPTY_POSTER_DRAFT,
	type PosterBuilderDraft,
	type PosterReadinessResponse,
} from "../types/posterReadiness";

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
	const [promptPackage, setPromptPackage] = useState<PosterPromptDraftResponse | null>(null);
	const [promptError, setPromptError] = useState("");
	const [promptLoading, setPromptLoading] = useState(false);

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
		setPromptPackage(null);
		setPromptError("");
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
	const promptDraftEnabled =
		!!readiness && isPromptDraftGenerationEnabled(readiness);
	const promptDraftLabel = readiness
		? resolvePromptDraftButtonLabel(readiness)
		: "Prompt draft unavailable";
	const imageGenerateLabel = readiness
		? resolveGenerateButtonLabel(readiness)
		: "Generation unavailable";

	const handlePromptDraft = async () => {
		if (!selectedProduct || !readiness) return;
		setPromptLoading(true);
		setPromptError("");
		try {
			const payload = draftToPromptRequest(selectedProduct.id, draft);
			const pkg = await createPosterPromptDraft(payload);
			setPromptPackage(pkg);
		} catch (e) {
			setPromptPackage(null);
			setPromptError(formatPosterPromptDraftError(e));
		} finally {
			setPromptLoading(false);
		}
	};

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
						<>
							<PosterBuilderShellForm
								draft={draft}
								onChange={setDraft}
								mode={shellMode}
								promptDraftEnabled={promptDraftEnabled}
								promptDraftLabel={promptDraftLabel}
								onPromptDraft={handlePromptDraft}
								promptDraftLoading={promptLoading}
								imageGenerateLabel={imageGenerateLabel}
							/>
							<PosterPromptPackagePreview package_={promptPackage} error={promptError} />
						</>
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
										generate_disabled_reason: imageGenerateLabel,
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