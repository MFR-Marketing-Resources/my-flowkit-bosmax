import { ImageIcon, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchPosterCopyRecommendations } from "../api/posterCopyRecommendations";
import { fetchPosterReadiness } from "../api/posterReadiness";
import {
	createPosterPromptDraft,
	draftToPromptRequest,
	formatPosterPromptDraftError,
} from "../api/posterPromptDraft";
import { fetchProductCatalog } from "../api/products";
import PosterAutoModePanel from "../components/poster/PosterAutoModePanel";
import PosterBuilderShellForm from "../components/poster/PosterBuilderShellForm";
import PosterGuidedModePanel from "../components/poster/PosterGuidedModePanel";
import PosterPromptPackagePreview from "../components/poster/PosterPromptPackagePreview";
import PosterReadinessStatusCard from "../components/poster/PosterReadinessStatusCard";
import PosterRepairActionCenter from "../components/poster/PosterRepairActionCenter";
import PosterWorkingModeSelector from "../components/poster/PosterWorkingModeSelector";
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
import { kitToDraft, POSTER_AUTO_DEFAULT_DRAFT } from "../poster/posterKitToDraft";
import type { Product } from "../types";
import type {
	PosterCopyKit,
	PosterWorkingMode,
} from "../types/posterCopyRecommendations";
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
	const [workingMode, setWorkingMode] = useState<PosterWorkingMode>("auto");
	const [kits, setKits] = useState<PosterCopyKit[]>([]);
	const [recWarnings, setRecWarnings] = useState<string[]>([]);
	const [recError, setRecError] = useState("");
	const [recLoading, setRecLoading] = useState(false);
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
		setKits([]);
		setRecWarnings([]);
		setRecError("");
		try {
			const payload = await fetchPosterReadiness(product.id);
			setReadiness(payload);
			setDraft({ ...POSTER_AUTO_DEFAULT_DRAFT });
			setWorkingMode("auto");
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
	const recommendationsEnabled = shellMode !== "hidden";

	const loadRecommendations = useCallback(
		async (refreshAi = false) => {
			if (!selectedProduct || !recommendationsEnabled) return;
			setRecLoading(true);
			setRecError("");
			try {
				const res = await fetchPosterCopyRecommendations({
					product_id: selectedProduct.id,
					poster_objective: draft.poster_objective,
					poster_type: draft.poster_type,
					frame_ratio: draft.frame_ratio,
					language: draft.language,
					visual_route: draft.visual_route,
					human_presence_mode: draft.human_presence_mode,
					text_density: draft.text_density,
					refresh_ai: refreshAi,
				});
				setKits(res.recommendations ?? []);
				setRecWarnings(res.warnings ?? []);
				if (!res.generation_allowed && res.recommendations.length === 0) {
					setRecError(
						res.blocked_reasons?.join(", ") ||
							"No usable kits for this readiness state.",
					);
				}
			} catch (e) {
				setKits([]);
				setRecError(
					e instanceof Error ? e.message : "Failed to load recommendations.",
				);
			} finally {
				setRecLoading(false);
			}
		},
		[selectedProduct, recommendationsEnabled, draft],
	);

	useEffect(() => {
		if (
			recommendationsEnabled &&
			workingMode !== "manual" &&
			selectedProduct &&
			kits.length === 0 &&
			!recLoading
		) {
			void loadRecommendations(false);
		}
	}, [
		recommendationsEnabled,
		workingMode,
		selectedProduct?.id,
		kits.length,
		recLoading,
		loadRecommendations,
	]);

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

	const handleSelectKit = (kit: PosterCopyKit) => {
		setDraft((prev) => kitToDraft(kit, prev));
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
						Copy bank first, AI assist second, manual override always available.
						Choose a working mode after readiness loads — not a blank form first.
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
							<PosterWorkingModeSelector
								mode={workingMode}
								onChange={setWorkingMode}
								disabled={!recommendationsEnabled}
							/>

							{workingMode === "auto" ? (
								<PosterAutoModePanel
									draft={draft}
									onDraftChange={setDraft}
									kits={kits}
									loading={recLoading}
									error={recError}
									warnings={recWarnings}
									onRefresh={() => void loadRecommendations(true)}
									onSelectKit={handleSelectKit}
									onUseForPromptDraft={() => void handlePromptDraft()}
									promptDraftLoading={promptLoading}
								/>
							) : null}

							{workingMode === "guided" ? (
								<PosterGuidedModePanel
									draft={draft}
									kits={kits}
									onDraftChange={setDraft}
									onUseForPromptDraft={() => void handlePromptDraft()}
									promptDraftLoading={promptLoading}
								/>
							) : null}

							{workingMode === "manual" ? (
								<PosterBuilderShellForm
									draft={draft}
									onChange={setDraft}
									mode={shellMode}
									promptDraftEnabled={promptDraftEnabled}
									promptDraftLabel={promptDraftLabel}
									onPromptDraft={() => void handlePromptDraft()}
									promptDraftLoading={promptLoading}
									imageGenerateLabel={imageGenerateLabel}
									manualExpert
								/>
							) : null}

							<section
								className="rounded-2xl border border-slate-800 bg-slate-950/40 p-5"
								data-testid="poster-image-handoff"
							>
								<h3 className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
									Poster image generation
								</h3>
								<p className="mt-2 text-sm text-slate-400">
									Image generation handoff not enabled for Poster Builder yet.
									Avatar Registry and Scene Registry use{" "}
									<code className="text-xs">/api/ai/generate-image</code> with
									explicit operator action; poster module reuses prompt package only
									until a gated poster image route is approved.
								</p>
								<button
									type="button"
									disabled
									className="mt-3 rounded-xl border border-slate-800 px-4 py-2 text-xs font-bold uppercase text-slate-500"
								>
									{imageGenerateLabel}
								</button>
							</section>

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
									working_mode: workingMode,
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