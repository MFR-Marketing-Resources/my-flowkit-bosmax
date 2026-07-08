import { ImageIcon, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { pollImgGenerationJob, startImgGeneration } from "../api/imgFactory";
import {
	PRODUCT_REFERENCE_IMAGE_REQUIRED,
	productSubjectAsset,
} from "../utils/productSubjectAsset";
import { usePosterBuilderSettings } from "../api/posterBuilderSettings";
import { fitPosterCopy } from "../api/posterCopyFit";
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
import PosterFlowMirrorSettingsPanel from "../components/poster/PosterFlowMirrorSettingsPanel";
import PosterGuidedModePanel from "../components/poster/PosterGuidedModePanel";
import PosterPromptPackagePreview from "../components/poster/PosterPromptPackagePreview";
import PosterReadinessStatusCard from "../components/poster/PosterReadinessStatusCard";
import PosterRepairActionCenter from "../components/poster/PosterRepairActionCenter";
import PosterWorkingModeSelector from "../components/poster/PosterWorkingModeSelector";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import CopywritingReadinessCard from "../components/copywriting/CopywritingReadinessCard";
import { useCopywritingReadiness } from "../api/copywritingReadiness";
import {
	isGenerateButtonDisabled,
	isPromptDraftGenerationEnabled,
	missingPosterCopyFields,
	overLimitPosterCopyFields,
	resolveBuilderShellMode,
	resolveGenerateButtonLabel,
	resolvePromptDraftButtonLabel,
	shouldShowHumanReviewPanel,
	shouldShowRepairActionCenter,
	summarizePosterCopyFit,
} from "../poster/posterBuilderUi";
import { kitToDraft, POSTER_AUTO_DEFAULT_DRAFT } from "../poster/posterKitToDraft";
import type { Product } from "../types";
import type {
	PosterCopyKit,
	PosterWorkingMode,
} from "../types/posterCopyRecommendations";
import type { PosterPromptDraftResponse } from "../types/posterPromptDraft";
import {
	DEFAULT_POSTER_FLOW_MIRROR_SETTINGS,
	isPosterFlowAspectRatio,
	type PosterFlowMirrorSettings,
} from "../types/posterFlowMirror";
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
	const { readiness: copyReadiness } = useCopywritingReadiness(
		selectedProduct?.id ?? null,
	);
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
	const [fitLoading, setFitLoading] = useState(false);
	const [fitNotice, setFitNotice] = useState("");
	// Poster image generation (gated, credit-spending — reuses the one-door IMG lane).
	const [posterGenConfirm, setPosterGenConfirm] = useState(false);
	const [posterGenLoading, setPosterGenLoading] = useState(false);
	const [posterGenError, setPosterGenError] = useState("");
	const [posterGenResult, setPosterGenResult] = useState<{
		url: string;
		mediaId: string;
		sizeMb: number | null;
	} | null>(null);
	const [flowMirror, setFlowMirror] = useState<PosterFlowMirrorSettings>(
		DEFAULT_POSTER_FLOW_MIRROR_SETTINGS,
	);
	const builderSettings = usePosterBuilderSettings();
	const draftRef = useRef(draft);
	draftRef.current = draft;
	const autoRecLoadedProductRef = useRef<string | null>(null);
	const readinessProductRef = useRef<string | null>(null);

	const applyFlowAspectToDraft = (aspect: string) => {
		if (draftRef.current.frame_ratio === aspect) return;
		setDraft((prev) => ({ ...prev, frame_ratio: aspect }));
	};

	const handleFlowMirrorChange = (next: PosterFlowMirrorSettings) => {
		setFlowMirror(next);
		applyFlowAspectToDraft(next.aspect_ratio);
	};

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
		if (match && match.id !== selectedProduct?.id) {
			setSelectedProduct(match);
		}
	}, [searchParams, products, selectedProduct?.id]);

	const loadReadiness = async (product: Product) => {
		const productChanged = readinessProductRef.current !== product.id;
		readinessProductRef.current = product.id;
		autoRecLoadedProductRef.current = null;
		setLoadingReadiness(true);
		setError("");
		if (productChanged) {
			setReadiness(null);
			setPromptPackage(null);
			setPromptError("");
			setKits([]);
			setRecWarnings([]);
			setRecError("");
			setFitNotice("");
			setPosterGenResult(null);
			setPosterGenError("");
			setPosterGenConfirm(false);
		}
		try {
			const payload = await fetchPosterReadiness(product.id);
			setReadiness(payload);
			setFlowMirror({ ...DEFAULT_POSTER_FLOW_MIRROR_SETTINGS });
			setDraft({
				...POSTER_AUTO_DEFAULT_DRAFT,
				frame_ratio: DEFAULT_POSTER_FLOW_MIRROR_SETTINGS.aspect_ratio,
			});
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
	// Product posters MUST anchor on the real product image. Resolve the product
	// into a Flow subject reference; null = no usable image = fail closed (block
	// generation, never fall back to prompt-only which hallucinates the product).
	const posterProductSubject = productSubjectAsset(selectedProduct);
	const productReferenceReady = posterProductSubject !== null;

	const loadRecommendations = useCallback(
		async (refreshAi = false, draftSnapshot?: PosterBuilderDraft) => {
			if (!selectedProduct || !recommendationsEnabled) return;
			const d = draftSnapshot ?? draftRef.current;
			setRecLoading(true);
			setRecError("");
			try {
				const res = await fetchPosterCopyRecommendations({
					product_id: selectedProduct.id,
					poster_objective: d.poster_objective,
					poster_type: d.poster_type,
					frame_ratio: d.frame_ratio,
					language: d.language,
					visual_route: d.visual_route,
					human_presence_mode: d.human_presence_mode,
					text_density: d.text_density,
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
		[selectedProduct?.id, recommendationsEnabled],
	);

	useEffect(() => {
		if (
			!recommendationsEnabled ||
			workingMode === "manual" ||
			!selectedProduct?.id ||
			recLoading
		) {
			return;
		}
		if (autoRecLoadedProductRef.current === selectedProduct.id) {
			return;
		}
		autoRecLoadedProductRef.current = selectedProduct.id;
		void loadRecommendations(false, draftRef.current);
	}, [
		recommendationsEnabled,
		workingMode,
		selectedProduct?.id,
		recLoading,
		loadRecommendations,
	]);

	const handlePromptDraft = async (draftOverride?: PosterBuilderDraft) => {
		if (!selectedProduct || !readiness) return;
		const activeDraft = draftOverride ?? draft;
		// Guard the required copy fields client-side so the operator gets a clear,
		// actionable message instead of a raw backend "Missing required field" 422.
		const missingCopy = missingPosterCopyFields(activeDraft);
		if (missingCopy.length > 0) {
			setPromptPackage(null);
			setPromptError(
				`Isi dulu medan copy wajib: ${missingCopy.join(", ")}. Taip di bahagian Copy draft, atau guna satu cadangan AI (Apply suggestion).`,
			);
			return;
		}
		const overLimit = overLimitPosterCopyFields(activeDraft);
		if (overLimit.length > 0) {
			setPromptPackage(null);
			setPromptError(
				`Copy terlalu panjang untuk poster: ${overLimit.join(", ")}. Pendekkan ayat supaya muat pada poster.`,
			);
			return;
		}
		setPromptLoading(true);
		setPromptError("");
		try {
			const payload = draftToPromptRequest(selectedProduct.id, activeDraft);
			const pkg = await createPosterPromptDraft(payload);
			setPromptPackage(pkg);
		} catch (e) {
			setPromptPackage(null);
			setPromptError(formatPosterPromptDraftError(e));
		} finally {
			setPromptLoading(false);
		}
	};

	const mergeKitIntoDraft = (kit: PosterCopyKit): PosterBuilderDraft => {
		const ratio = flowMirror.aspect_ratio;
		const next = { ...kitToDraft(kit, draft), frame_ratio: ratio };
		setDraft(next);
		return next;
	};

	const handleSelectKit = (kit: PosterCopyKit) => {
		const ratio = (kit.frame_ratio && isPosterFlowAspectRatio(kit.frame_ratio)
			? kit.frame_ratio
			: flowMirror.aspect_ratio) as PosterFlowMirrorSettings["aspect_ratio"];
		const next = { ...kitToDraft(kit, draft), frame_ratio: ratio };
		setDraft(next);
		setFlowMirror((prev) => ({ ...prev, aspect_ratio: ratio }));
	};

	const handleUseKitForPromptDraft = async (kit: PosterCopyKit) => {
		const nextDraft = mergeKitIntoDraft(kit);
		await handlePromptDraft(nextDraft);
	};

	// Operator-initiated "Fit to poster": AI condenses over-length copy to the
	// poster limits. Suggestion-only — the returned fields are applied to the draft
	// (which the operator can still edit), never persisted or auto-approved.
	const handleFitToPoster = async () => {
		const d = draftRef.current;
		setFitLoading(true);
		setFitNotice("");
		try {
			const res = await fitPosterCopy({
				language: d.language,
				hook: d.hook,
				subhook: d.subhook,
				usp_1: d.usp_1,
				usp_2: d.usp_2,
				usp_3: d.usp_3,
				cta: d.cta,
			});
			if (res.applied) {
				// A shortened line is operator-authored copy now, not the approved Copy
				// Set — mirror the manual-edit provenance reset so governance stays honest.
				setDraft((prev) => ({
					...prev,
					hook: res.fields.hook,
					subhook: res.fields.subhook,
					usp_1: res.fields.usp_1,
					usp_2: res.fields.usp_2,
					usp_3: res.fields.usp_3,
					cta: res.fields.cta,
					copy_source: "manual",
					copy_set_id: "",
					copy_fallback_confirmed: false,
				}));
			}
			setFitNotice(summarizePosterCopyFit(res));
		} catch (e) {
			setFitNotice(
				e instanceof Error ? e.message : "Auto-pendekkan gagal. Cuba lagi.",
			);
		} finally {
			setFitLoading(false);
		}
	};

	// GATED, credit-spending: only ever runs after the explicit confirm modal. Sends
	// the generated poster prompt package through the PROVEN one-door IMG lane
	// (POST /api/flow/generate mode:IMG) + poll, then shows the finished poster image.
	const handleConfirmedGeneratePoster = async () => {
		const pkg = promptPackage;
		if (!pkg?.poster_prompt) return;
		// Fail closed BEFORE any credit spend: a product poster must anchor on the
		// real product image. If the selected product has no usable reference image,
		// block — never fall back to prompt-only generation.
		const subjectAsset = productSubjectAsset(selectedProduct);
		if (!subjectAsset) {
			setPosterGenConfirm(false);
			setPosterGenError(
				`${PRODUCT_REFERENCE_IMAGE_REQUIRED} — produk ini tiada gambar rujukan yang boleh diguna. Poster produk mesti berlabuh pada gambar produk sebenar; penjanaan dihalang.`,
			);
			return;
		}
		setPosterGenConfirm(false);
		setPosterGenLoading(true);
		setPosterGenError("");
		setPosterGenResult(null);
		try {
			const { job_id } = await startImgGeneration({
				prompt: pkg.poster_prompt,
				aspect: flowMirror.aspect_ratio,
				count: flowMirror.count,
				image_model: flowMirror.image_model,
				// Anchor the poster on the real BOSMAX product image (resolved to a Flow
				// reference asset server-side → IMAGE_INPUT_TYPE_REFERENCE).
				refs: { subjectAsset },
			});
			const job = await pollImgGenerationJob(job_id);
			const mediaId = job.media_id ?? "";
			const url = job.url ?? (mediaId ? `/api/flow/retrieved/${mediaId}` : "");
			if ((job.status === "DONE" || job.status === "COMPLETED") && url) {
				setPosterGenResult({
					url,
					mediaId,
					sizeMb: typeof job.size_mb === "number" ? job.size_mb : null,
				});
			} else {
				setPosterGenError(
					job.error || `Penjanaan tamat sebagai ${job.status} tanpa imej.`,
				);
			}
		} catch (e) {
			setPosterGenError(
				e instanceof Error ? e.message : "Penjanaan poster gagal.",
			);
		} finally {
			setPosterGenLoading(false);
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
					<CopywritingReadinessCard
						readiness={copyReadiness}
						onPrepare={() =>
							selectedProduct
								? window.location.assign(
										`/products?product_id=${encodeURIComponent(selectedProduct.id)}`,
									)
								: undefined
						}
						onOpenCopyRegistry={() =>
							selectedProduct
								? window.location.assign(
										`/creative/copy-registry?product_id=${encodeURIComponent(selectedProduct.id)}`,
									)
								: undefined
						}
					/>

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
									settings={builderSettings}
									kits={kits}
									loading={recLoading}
									error={recError}
									warnings={recWarnings}
									onRefresh={() => void loadRecommendations(true, draftRef.current)}
									onSelectKit={handleSelectKit}
									onUseKitForPromptDraft={(kit) => void handleUseKitForPromptDraft(kit)}
									onGeneratePromptDraft={() => void handlePromptDraft(draftRef.current)}
									onFitToPoster={() => void handleFitToPoster()}
									fitLoading={fitLoading}
									fitNotice={fitNotice}
									promptDraftEnabled={promptDraftEnabled}
									promptDraftLabel={promptDraftLabel}
									promptDraftLoading={promptLoading}
								/>
							) : null}

							{workingMode === "guided" ? (
								<PosterGuidedModePanel
									draft={draft}
									kits={kits}
									onDraftChange={(d) => {
										setDraft(d);
										if (d.frame_ratio && d.frame_ratio !== flowMirror.aspect_ratio) {
											setFlowMirror((prev) => ({
												...prev,
												aspect_ratio: d.frame_ratio as PosterFlowMirrorSettings["aspect_ratio"],
											}));
										}
									}}
									onUseForPromptDraft={() => void handlePromptDraft()}
									promptDraftLoading={promptLoading}
								/>
							) : null}

							{workingMode === "manual" ? (
								<PosterBuilderShellForm
									draft={draft}
									onChange={(d) => {
										setDraft(d);
										if (d.frame_ratio !== flowMirror.aspect_ratio) {
											setFlowMirror((prev) => ({
												...prev,
												aspect_ratio: d.frame_ratio as PosterFlowMirrorSettings["aspect_ratio"],
											}));
										}
									}}
									mode={shellMode}
									promptDraftEnabled={promptDraftEnabled}
									promptDraftLabel={promptDraftLabel}
									onPromptDraft={() => void handlePromptDraft()}
									promptDraftLoading={promptLoading}
									imageGenerateLabel={imageGenerateLabel}
									manualExpert
								/>
							) : null}

							<PosterFlowMirrorSettingsPanel
								settings={flowMirror}
								onChange={handleFlowMirrorChange}
								disabled={!recommendationsEnabled}
							/>

							<section
								className="rounded-2xl border border-slate-800 bg-slate-950/40 p-5"
								data-testid="poster-image-handoff"
							>
								<h3 className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
									Poster image generation
								</h3>
								<p
									className="mt-2 text-xs text-slate-500"
									data-testid="flow-handoff-captured"
								>
									Flow handoff settings captured: Aspect Ratio:{" "}
									{flowMirror.aspect_ratio} · Count: {flowMirror.count}x · Image
									Model: {flowMirror.image_model}
								</p>
								{!promptPackage ? (
									<p className="mt-2 text-sm text-slate-400">
										Jana <strong>prompt draft</strong> dulu di atas — poster
										image dijana daripada prompt package itu.
									</p>
								) : promptPackage.prompt_package_status === "PREVIEW_ONLY" ? (
									<p className="mt-2 text-[11px] text-amber-300">
										Nota: copy ini review-only (bukan Copy Set diluluskan).
										Poster tetap boleh dijana untuk semakan.
									</p>
								) : null}
								{!productReferenceReady ? (
									<p
										data-testid="poster-product-ref-required"
										className="mt-2 text-[11px] text-rose-300"
									>
										{PRODUCT_REFERENCE_IMAGE_REQUIRED} — produk ini tiada gambar
										rujukan. Poster produk mesti berlabuh pada gambar produk
										sebenar; set gambar produk dahulu. Penjanaan dihalang.
									</p>
								) : null}
								<button
									type="button"
									data-testid="generate-poster-button"
									disabled={
										!promptPackage ||
										posterGenLoading ||
										!readiness.generation_allowed ||
										!productReferenceReady
									}
									onClick={() => setPosterGenConfirm(true)}
									className="mt-3 rounded-xl border border-rose-500/40 bg-rose-600/20 px-4 py-2 text-xs font-bold uppercase text-rose-100 disabled:opacity-40"
								>
									{posterGenLoading
										? "Menjana poster (live)…"
										: "Jana poster image (live · guna kredit)"}
								</button>
								{posterGenError ? (
									<p
										data-testid="poster-gen-error"
										className="mt-3 text-sm text-rose-200"
									>
										{posterGenError}
									</p>
								) : null}
								{posterGenResult ? (
									<div className="mt-4" data-testid="poster-gen-result">
										<img
											src={posterGenResult.url}
											alt="Poster dijana"
											className="max-h-96 rounded-xl border border-slate-800"
										/>
										<div className="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
											<a
												href={posterGenResult.url}
												target="_blank"
												rel="noopener noreferrer"
												className="rounded-lg border border-slate-700 px-3 py-1.5 font-semibold text-slate-200"
											>
												Buka / Muat turun ↗
											</a>
											{posterGenResult.sizeMb ? (
												<span>{posterGenResult.sizeMb} MB</span>
											) : null}
											{posterGenResult.mediaId ? (
												<span>media: {posterGenResult.mediaId}</span>
											) : null}
										</div>
									</div>
								) : null}
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
									flow_mirror_settings: flowMirror,
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
			{posterGenConfirm ? (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
					<div className="max-w-md space-y-3 rounded-2xl border border-rose-500/40 bg-slate-950 p-5">
						<div className="text-sm font-bold text-rose-100">
							Sahkan penjanaan poster (guna kredit)
						</div>
						<div className="text-[11px] text-slate-300">
							Ini memanggil lane imej live (<code>POST /api/flow/generate</code>{" "}
							mode:IMG) dan <strong>membelanjakan kredit</strong>. Ia tidak akan
							jalan tanpa pengesahan ini.
						</div>
						<div className="flex justify-end gap-2">
							<button
								type="button"
								onClick={() => setPosterGenConfirm(false)}
								className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-slate-300"
							>
								Batal
							</button>
							<button
								type="button"
								data-testid="poster-gen-confirm"
								onClick={() => void handleConfirmedGeneratePoster()}
								className="rounded-lg border border-rose-500/40 bg-rose-500/20 px-3 py-1.5 text-[11px] font-bold text-rose-100"
							>
								Sahkan &amp; Jana (live)
							</button>
						</div>
					</div>
				</div>
			) : null}
		</div>
	);
}