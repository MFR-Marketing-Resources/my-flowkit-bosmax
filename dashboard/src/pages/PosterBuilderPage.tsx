import { ImageIcon, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import PosterGuidedShell from "../components/poster/guided/PosterGuidedShell";
import { pollImgGenerationJob, startImgGeneration } from "../api/imgFactory";
import {
	buildExactSceneOnlyPrompt,
	composeExactFromPlate,
	fetchExactProductPolicy,
	resolveExactGenerationGate,
	type ExactProductPolicy,
} from "../api/exactProductOutput";
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
import { usePosterRecipes } from "../api/posterRecipes";
import PosterRecipeSelector from "../components/poster/PosterRecipeSelector";
import PosterAngleCopyStep from "../components/poster/PosterAngleCopyStep";
import PosterComposePanel from "../components/poster/PosterComposePanel";
import {
	approvePosterCopySet,
	composePoster,
	fetchPosterDeliverableByAsset,
	forkPosterCopySetFromHistorical,
	newPosterCopySetVersion,
	patchPosterCopySet,
	posterDeliverableOutputUrl,
	recommendPosterObjectives,
} from "../api/posterCopySets";
import {
	POSTER_COPY_APPROVAL_PHRASE,
	type PosterCopySet,
	type PosterDeliverableReconstruction,
	type PosterObjectiveRecommendation,
} from "../types/posterCopySet";
import PosterControlledSettings from "../components/poster/PosterControlledSettings";
import PosterRecipeSlotEditor from "../components/poster/PosterRecipeSlotEditor";
import PosterSpecPreview from "../components/poster/PosterSpecPreview";
import PosterCopyQualityPanel from "../components/poster/PosterCopyQualityPanel";
import { fetchPosterCopyQuality } from "../api/posterCopyQuality";
import type { PosterCopyQualityReport } from "../types/posterCopyQuality";
import PosterAutoModePanel from "../components/poster/PosterAutoModePanel";
import PosterBuilderShellForm from "../components/poster/PosterBuilderShellForm";
import PosterFlowMirrorSettingsPanel from "../components/poster/PosterFlowMirrorSettingsPanel";
import PosterGuidedModePanel from "../components/poster/PosterGuidedModePanel";
import PosterPromptPackagePreview from "../components/poster/PosterPromptPackagePreview";
import PosterReadinessStatusCard from "../components/poster/PosterReadinessStatusCard";
import PosterRepairActionCenter from "../components/poster/PosterRepairActionCenter";
import PosterWorkingModeSelector from "../components/poster/PosterWorkingModeSelector";
import {
	WorkflowStep,
} from "../components/workflow";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import ResultsSidebar, { type SessionResult } from "../components/workspace/ResultsSidebar";
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

// The original full-control Poster Builder. Preserved verbatim as the ADVANCED
// / LEGACY COMPATIBILITY surface — every proven behavior (readiness matrix,
// working modes, recipe slot editor, controlled settings, live generate, reopen)
// stays available for troubleshooting, but it is no longer the default journey.
export function PosterBuilderLegacyPanel() {
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
	const [posterQuality, setPosterQuality] = useState<PosterCopyQualityReport | null>(null);
	const [posterQualityLoading, setPosterQualityLoading] = useState(false);
	// Signature of the copy the quality guard last ran against. If ANY copy field
	// changes after a check the signature diverges → the report is stale → the
	// generate gate re-arms (mandatory recheck before generation).
	const [posterQualityKey, setPosterQualityKey] = useState<string | null>(null);
	// Poster image generation (gated, credit-spending — reuses the one-door IMG lane).
	const [posterGenConfirm, setPosterGenConfirm] = useState(false);
	const [posterGenLoading, setPosterGenLoading] = useState(false);
	const [posterGenStage, setPosterGenStage] = useState<string>("");
	const [exactPolicy, setExactPolicy] = useState<ExactProductPolicy | null>(null);
	const exactPolicyActive = Boolean(
		exactPolicy?.exact_product_composite_required,
	);
	const [posterGenError, setPosterGenError] = useState("");
	const [posterGenResult, setPosterGenResult] = useState<{
		url: string;
		mediaId: string;
		sizeMb: number | null;
	} | null>(null);
	// POSTER_BUILDER_V2: approved poster-native copy set + AI objective ranking.
	const [approvedCopySet, setApprovedCopySet] = useState<PosterCopySet | null>(null);
	const [editingCopySet, setEditingCopySet] = useState<PosterCopySet | null>(null);
	const [copyVersionLoading, setCopyVersionLoading] = useState<
		"" | "create" | "approve" | "fork"
	>("");
	const [copyVersionError, setCopyVersionError] = useState("");
	const [objectiveRecs, setObjectiveRecs] = useState<PosterObjectiveRecommendation[]>([]);
	const [objectiveRecsLoading, setObjectiveRecsLoading] = useState(false);
	const [flowMirror, setFlowMirror] = useState<PosterFlowMirrorSettings>(
		DEFAULT_POSTER_FLOW_MIRROR_SETTINGS,
	);
	// Creative Library round trip: ?reopen_asset=<creative_asset_id> restores a
	// saved poster's configuration (product, recipe, approved copy set) and shows
	// the ORIGINAL saved output. Recompose creates a NEW deliverable; the saved
	// bytes are never overwritten.
	const [reopened, setReopened] = useState<PosterDeliverableReconstruction | null>(null);
	const [reopenError, setReopenError] = useState("");
	const reopenAppliedRef = useRef(false);
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

	// Reopen step 1: fetch the saved deliverable and point product_id at it.
	useEffect(() => {
		const reopenAsset = searchParams.get("reopen_asset");
		if (!reopenAsset || reopened || reopenAppliedRef.current) return;
		void fetchPosterDeliverableByAsset(reopenAsset)
			.then((data) => {
				setReopened(data);
				setReopenError("");
				const pid = data.deliverable.product_id;
				if (pid && searchParams.get("product_id") !== pid) {
					setSearchParams(
						{ product_id: pid, reopen_asset: reopenAsset },
						{ replace: true },
					);
				}
			})
			.catch((err: Error) =>
				setReopenError(
					err.message || "Failed to reopen poster from Creative Library.",
				),
			);
		// eslint-disable-next-line react-hooks/exhaustive-deps -- fetch once per reopen id
	}, [searchParams]);


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
			setApprovedCopySet(null);
			setObjectiveRecs([]);
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

	useEffect(() => {
		if (!selectedProduct?.id) {
			setExactPolicy(null);
			return;
		}
		let cancelled = false;
		void fetchExactProductPolicy(selectedProduct.id)
			.then((pol) => {
				if (!cancelled) setExactPolicy(pol);
			})
			.catch(() => {
				if (!cancelled) setExactPolicy(null);
			});
		return () => {
			cancelled = true;
		};
	}, [selectedProduct?.id]);

	// Recipe-first: the operator picks a poster archetype BEFORE copy. The selected
	// recipe drives controlled settings, slot editing, and the composer path.
	const { recipes, error: recipesError } = usePosterRecipes();
	const selectedRecipe =
		recipes.find((r) => r.recipe_id === draft.poster_recipe_id) ?? null;
	// POSTER-native copy signature (headline/support/chips/cta in draft terms).
	const posterCopySignature = (d: PosterBuilderDraft): string =>
		[d.hook, d.subhook, d.usp_1, d.usp_2, d.usp_3, d.cta]
			.map((s) => (s ?? "").trim())
			.join("\u0001");
	const handleSelectRecipe = (recipeId: string) => {
		setPosterQuality(null);
		setPosterQualityKey(null);
		// A different archetype invalidates the approved poster copy set binding.
		setApprovedCopySet(null);
		setDraft((prev) => ({ ...prev, poster_copy_set_id: "" }));
		setDraft((prev) => {
			const r = recipes.find((x) => x.recipe_id === recipeId) ?? null;
			let text_density = prev.text_density;
			if (
				r &&
				r.allowed_text_density.length > 0 &&
				!r.allowed_text_density.includes(text_density)
			) {
				text_density = r.allowed_text_density[0];
			}
			return { ...prev, poster_recipe_id: recipeId, text_density };
		});
	};
	// Expert poster copy quality check (credit-free). Maps the draft's legacy
	// video-style fields into POSTER-native copy (headline/support/chips/cta).
	const handleCheckPosterQuality = async () => {
		const d = draftRef.current;
		setPosterQualityLoading(true);
		try {
			const report = await fetchPosterCopyQuality({
				archetype: selectedRecipe?.archetype ?? "",
				language: d.language,
				max_chips: selectedRecipe?.max_chips ?? 3,
				poster_headline: d.hook,
				poster_support_line: d.subhook,
				poster_chips: [d.usp_1, d.usp_2, d.usp_3].filter((c) => c.trim()),
				poster_cta: d.cta,
			});
			setPosterQuality(report);
			setPosterQualityKey(posterCopySignature(d));
		} catch {
			setPosterQuality(null);
			setPosterQualityKey(null);
		} finally {
			setPosterQualityLoading(false);
		}
	};
	const missingCopy = missingPosterCopyFields(draft);
	const overLimitCopy = overLimitPosterCopyFields(draft);
	// Mandatory quality gate: generation is allowed only after the CURRENT copy
	// passed the expert guard with zero BLOCK findings. A stale report (copy
	// edited since the check) counts as "needs recheck", never as a pass.
	const posterQualityFresh =
		posterQuality !== null && posterQualityKey === posterCopySignature(draft);
	const posterQualityStale = posterQuality !== null && !posterQualityFresh;
	const posterQualityBlocked =
		posterQualityFresh && (posterQuality?.block_count ?? 0) > 0;
	const posterQualityNeedsCheck = !posterQualityFresh;

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

	// "Cadangkan untuk saya" — AI (grounded) or deterministic archetype ranking.
	const handleRecommendObjectives = async () => {
		if (!selectedProduct) return;
		setObjectiveRecsLoading(true);
		try {
			const res = await recommendPosterObjectives({
				product_id: selectedProduct.id,
				refresh_ai: true,
			});
			setObjectiveRecs(res.recommendations ?? []);
		} catch {
			setObjectiveRecs([]);
		} finally {
			setObjectiveRecsLoading(false);
		}
	};

	const projectPosterCopySetToDraft = (
		pcs: PosterCopySet,
		copySource: "APPROVED_POSTER_COPY_SET" | "DRAFT_POSTER_COPY_SET",
	) => {
		const points = [...pcs.proof_points, "", "", ""];
		setDraft((prev) => ({
			...prev,
			hook: pcs.primary_message,
			subhook: pcs.support_message,
			usp_1: points[0],
			usp_2: points[1],
			usp_3: points[2],
			cta: pcs.cta,
			language: pcs.language || prev.language,
			copy_source: copySource,
			copy_set_id: "",
			copy_fallback_confirmed: false,
			poster_copy_set_id: pcs.poster_copy_set_id,
		}));
	};

	// Approved Poster Copy Set → project fields into the draft, bind the set id,
	// and immediately re-run the mandatory quality check (fresh gate).
	const handleApprovedCopySet = (pcs: PosterCopySet) => {
		setEditingCopySet(null);
		setApprovedCopySet(pcs);
		setCopyVersionError("");
		projectPosterCopySetToDraft(pcs, "APPROVED_POSTER_COPY_SET");
		window.setTimeout(() => void handleCheckPosterQuality(), 0);
	};

	const handleCreateCopyVersion = async () => {
		if (!approvedCopySet) return;
		setCopyVersionLoading("create");
		setCopyVersionError("");
		try {
			const draftVersion = await newPosterCopySetVersion(
				approvedCopySet.poster_copy_set_id,
				{},
			);
			setApprovedCopySet(null);
			setEditingCopySet(draftVersion);
			projectPosterCopySetToDraft(draftVersion, "DRAFT_POSTER_COPY_SET");
			setPosterQuality(null);
			setPosterQualityKey(null);
		} catch (err) {
			setCopyVersionError(
				err instanceof Error ? err.message : "Failed to open the new version for editing.",
			);
		} finally {
			setCopyVersionLoading("");
		}
	};

	const handleForkHistorical = async () => {
		const historical = reopened?.poster_copy_set;
		if (!historical) return;
		setCopyVersionLoading("fork");
		setCopyVersionError("");
		try {
			// Clone the SUPERSEDED historical copy into a fresh editable DRAFT —
			// the historical record and the saved poster's provenance are untouched.
			const draftVersion = await forkPosterCopySetFromHistorical(
				historical.poster_copy_set_id,
				{},
			);
			setApprovedCopySet(null);
			setEditingCopySet(draftVersion);
			projectPosterCopySetToDraft(draftVersion, "DRAFT_POSTER_COPY_SET");
			setPosterQuality(null);
			setPosterQualityKey(null);
			setReopened((prev) =>
				prev
					? {
							...prev,
							poster_copy_set: draftVersion,
							poster_copy_set_status: draftVersion.status,
							poster_copy_set_historical: false,
						}
					: prev,
			);
		} catch (err) {
			setCopyVersionError(
				err instanceof Error
					? err.message
					: "Failed to open a new draft from the history version.",
			);
		} finally {
			setCopyVersionLoading("");
		}
	};

	const handleApproveCopyVersion = async () => {
		if (!editingCopySet) return;
		setCopyVersionLoading("approve");
		setCopyVersionError("");
		try {
			const patched = await patchPosterCopySet(editingCopySet.poster_copy_set_id, {
				primary_message: draft.hook,
				support_message: draft.subhook,
				proof_points: [draft.usp_1, draft.usp_2, draft.usp_3].filter(Boolean),
				cta: draft.cta,
				disclaimer: editingCopySet.disclaimer,
			});
			const approved = await approvePosterCopySet(
				patched.poster_copy_set_id,
				POSTER_COPY_APPROVAL_PHRASE,
			);
			handleApprovedCopySet(approved);
		} catch (err) {
			setCopyVersionError(
				err instanceof Error ? err.message : "Failed to save the new Poster Copy Set version.",
			);
		} finally {
			setCopyVersionLoading("");
		}
	};

	// Reopen step 2: once readiness + recipes are in for the SAME product,
	// restore recipe + approved copy set exactly once.
	useEffect(() => {
		if (!reopened || reopenAppliedRef.current) return;
		if (!readiness || !selectedProduct) return;
		if (selectedProduct.id !== reopened.deliverable.product_id) return;
		if (recipes.length === 0) return;
		reopenAppliedRef.current = true;
		const recipeId = reopened.deliverable.recipe_id;
		if (recipeId && recipes.some((r) => r.recipe_id === recipeId)) {
			handleSelectRecipe(recipeId);
		}
		const pcs = reopened.poster_copy_set;
		if (pcs && pcs.status === "POSTER_COPY_APPROVED") {
			handleApprovedCopySet(pcs);
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot restore
	}, [reopened, readiness, selectedProduct?.id, recipes]);

	// Any manual copy edit after approval invalidates the binding (the backend
	// would otherwise re-project the approved fields over the edits).
	useEffect(() => {
		if (!approvedCopySet || !draft.poster_copy_set_id) return;
		const points = [...approvedCopySet.proof_points, "", "", ""];
		const projected = [
			approvedCopySet.primary_message,
			approvedCopySet.support_message,
			points[0],
			points[1],
			points[2],
			approvedCopySet.cta,
		]
			.map((s) => (s ?? "").trim())
			.join("");
		if (posterCopySignature(draft) !== projected) {
			setApprovedCopySet(null);
			setDraft((prev) => ({
				...prev,
				poster_copy_set_id: "",
				copy_source: "manual",
			}));
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps -- signature comparison only
	}, [draft.hook, draft.subhook, draft.usp_1, draft.usp_2, draft.usp_3, draft.cta]);

	const handlePromptDraft = async (draftOverride?: PosterBuilderDraft) => {
		if (!selectedProduct || !readiness) return;
		const activeDraft = draftOverride ?? draft;
		// Guard the required copy fields client-side so the operator gets a clear,
		// actionable message instead of a raw backend "Missing required field" 422.
		const missingCopy = missingPosterCopyFields(activeDraft);
		if (missingCopy.length > 0) {
			setPromptPackage(null);
			setPromptError(
				`Fill the required copy fields first: ${missingCopy.join(", ")}. Type them in the Copy draft area, or use one AI suggestion (Apply suggestion).`,
			);
			return;
		}
		const overLimit = overLimitPosterCopyFields(activeDraft);
		if (overLimit.length > 0) {
			setPromptPackage(null);
			setPromptError(
				`Copy too long for the poster: ${overLimit.join(", ")}. Shorten the sentences to fit the poster.`,
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
				e instanceof Error ? e.message : "Auto-shorten failed. Try again.",
			);
		} finally {
			setFitLoading(false);
		}
	};

	// GATED, credit-spending: only after explicit confirm.
	// Exact-policy products: scene-only Flow plate + deterministic cutout composite.
	// Non-exact: reference-conditioned one-door IMG path (unchanged).
	const handleConfirmedGeneratePoster = async () => {
		const pkg = promptPackage;
		if (!pkg?.poster_prompt) return;
		const subjectAsset = productSubjectAsset(selectedProduct);
		const productId = selectedProduct?.id ?? "";
		// Fail-closed: never assume non-exact when policy cannot be resolved.
		const gate = await resolveExactGenerationGate(productId);
		if (gate.mode === "blocked") {
			setPosterGenConfirm(false);
			setPosterGenError(gate.message);
			return;
		}
		if (gate.mode === "exact" || gate.mode === "standard") {
			setExactPolicy(gate.policy);
		}
		const exact = gate.mode === "exact";
		if (!exact && !subjectAsset) {
			setPosterGenConfirm(false);
			setPosterGenError(
				`${PRODUCT_REFERENCE_IMAGE_REQUIRED} — this product has no usable reference image. A product poster must anchor on the real product image; generation is blocked.`,
			);
			return;
		}
		setPosterGenConfirm(false);
		setPosterGenLoading(true);
		setPosterGenError("");
		setPosterGenResult(null);
		setPosterGenStage(exact ? "validating_canonical" : "generating");
		try {
			let prompt = pkg.poster_prompt;
			const refs = subjectAsset ? { subjectAsset } : undefined;
			const isFixedHero = Boolean(
				(subjectAsset as { isFixedHero?: boolean })?.isFixedHero ||
				(subjectAsset as { semanticRole?: string })?.semanticRole === "FIXED_HERO"
			);

			// Strategy C: FIXED_HERO_POSTER (Hero visual stays 100% fixed and unchanged when a complete hero visual is provided)
			if (isFixedHero && productId && subjectAsset) {
				setPosterGenStage("composing_fixed_hero");
				try {
					const result = await composePoster({
						product_id: productId,
						poster_copy_set_id: approvedCopySet?.poster_copy_set_id || "",
						recipe_id: draft.poster_recipe_id || "",
						background_media_id: subjectAsset.mediaId || "",
					});
					setPosterGenStage("final_ready");
					const deliv = result.deliverable;
					const deliverableId =
						deliv?.poster_deliverable_id || subjectAsset.mediaId || "";
					setPosterGenResult({
						url: posterDeliverableOutputUrl(deliverableId),
						mediaId: deliverableId,
						sizeMb: null,
					});
					return;
				} catch (err) {
					setPosterGenError(
						`FIXED_HERO_POSTER_RENDERER_UNAVAILABLE: ${err instanceof Error ? err.message : String(err)}`
					);
					return;
				}
			}

			const useExactComposite = gate.mode === "exact" && Boolean(productId);

			if (useExactComposite && productId) {
				setPosterGenStage("generating_scene");
				const scene = await buildExactSceneOnlyPrompt(productId, prompt);
				prompt = scene.prompt;
			}

			const { job_id } = await startImgGeneration({
				prompt,
				aspect: flowMirror.aspect_ratio,
				count: flowMirror.count,
				image_model: flowMirror.image_model,
				...(refs && !useExactComposite ? { refs } : {}),
			});
			const job = await pollImgGenerationJob(job_id);
			const plateMediaId = job.media_id ?? "";
			if (
				!(job.status === "DONE" || job.status === "COMPLETED") ||
				!plateMediaId
			) {
				setPosterGenError(
					job.error || `Generation ended as ${job.status} with no image.`,
				);
				return;
			}
			if (useExactComposite && productId) {
				setPosterGenStage("inserting_canonical_product");
				const finalOut = await composeExactFromPlate({
					product_id: productId,
					background_media_id: plateMediaId,
					lane: "poster",
					job_id,
				});
				setPosterGenStage("final_ready");
				setPosterGenResult({
					url: finalOut.url,
					mediaId: finalOut.media_id,
					sizeMb: typeof finalOut.size_mb === "number" ? finalOut.size_mb : null,
				});
			} else {
				const url = job.url ?? `/api/flow/retrieved/${plateMediaId}`;
				setPosterGenResult({
					url,
					mediaId: plateMediaId,
					sizeMb: typeof job.size_mb === "number" ? job.size_mb : null,
				});
			}
		} catch (e) {
			setPosterGenError(
				e instanceof Error ? e.message : "Poster generation failed.",
			);
		} finally {
			setPosterGenLoading(false);
			setPosterGenStage("");
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
						{exactPolicyActive
						? "Exact-product mode: scene plate + canonical cutout composite. "
						: ""}Recipe-first: pick a poster archetype, confirm the product image, set controlled
						options, then fill the recipe's copy slots. Manual Expert stays available as an advanced/legacy mode.
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

			{reopenError ? (
				<p
					className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100"
					data-testid="poster-reopen-error"
				>
					{reopenError}
				</p>
			) : null}

			{reopened ? (
				<section
					className="rounded-2xl border border-emerald-700/50 bg-emerald-950/20 p-5"
					data-testid="poster-reopen-panel"
				>
					<p className="text-[10px] font-bold uppercase tracking-[0.16em] text-emerald-400">
						Reopened from Creative Library
					</p>
					<div className="mt-3 flex flex-wrap gap-5">
						{reopened.output_available ? (
							<img
								src={posterDeliverableOutputUrl(
									reopened.deliverable.poster_deliverable_id,
								)}
								alt="Original saved poster"
								className="h-56 rounded-lg border border-slate-800 object-contain"
								data-testid="poster-reopen-original-output"
							/>
						) : (
							<p className="text-xs text-amber-300">
								The original output file is not on this runtime — config is
								preserved; compose again to produce a new output.
							</p>
						)}
						<dl className="space-y-1 text-xs text-slate-300">
							<div>
								<dt className="inline font-semibold">Deliverable:</dt>{" "}
								<dd className="inline">
									{reopened.deliverable.poster_deliverable_id}
								</dd>
							</div>
							<div>
								<dt className="inline font-semibold">Recipe:</dt>{" "}
								<dd className="inline">{reopened.deliverable.recipe_id}</dd>
							</div>
							<div>
								<dt className="inline font-semibold">Copy set:</dt>{" "}
								<dd className="inline">
									{reopened.poster_copy_set
										? `${reopened.poster_copy_set.poster_copy_set_id} v${reopened.poster_copy_set.version} (${reopened.poster_copy_set.status})`
										: "—"}
								</dd>
							</div>
							<div>
								<dt className="inline font-semibold">Product strategy:</dt>{" "}
								<dd className="inline">
									{reopened.deliverable.composition_strategy} — identiti/label/
									product scale in the generated scene needs human review.
								</dd>
							</div>
							<div>
								<dt className="inline font-semibold">Sumber output:</dt>{" "}
								<dd className="inline" data-testid="poster-reopen-output-source">
									{reopened.output_available
										? reopened.output_source === "CREATIVE_LIBRARY"
											? "Salinan Creative Library (durable)"
											: "Fail deliverable asal"
										: "None — both copies lost"}
								</dd>
							</div>
						</dl>
					</div>
					{reopened.poster_copy_set &&
					(reopened.poster_copy_set_historical ||
						reopened.poster_copy_set.status === "POSTER_COPY_SUPERSEDED") ? (
						<div
							className="mt-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3"
							data-testid="poster-reopen-historical"
						>
							<p className="text-[11px] text-amber-100">
								<span className="font-bold uppercase tracking-wide">
									History version (superseded)
								</span>{" "}
								— this copy is shown read-only. The saved poster keeps a copy
								of its original copy; the history record is unchanged.
							</p>
							<button
								type="button"
								data-testid="poster-reopen-fork-historical"
								onClick={() => void handleForkHistorical()}
								disabled={copyVersionLoading === "fork"}
								className="mt-2 rounded-lg border border-amber-400/60 bg-amber-500/20 px-3 py-1.5 text-xs font-semibold text-amber-50 disabled:opacity-50"
							>
								{copyVersionLoading === "fork"
									? "Membuka draf…"
									: "Create a new draft from this history version"}
							</button>
							{copyVersionError ? (
								<p
									className="mt-2 text-[11px] text-rose-200"
									data-testid="poster-reopen-fork-error"
								>
									{copyVersionError}
								</p>
							) : null}
						</div>
					) : null}
					<p className="mt-3 text-[11px] text-slate-400">
						Config (product, recipe, copy set) has been restored below.
						Editing approved copy creates a NEW VERSION; composing again
						creates a new deliverable — the original output is not overwritten.
					</p>
				</section>
			) : null}

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
							<section
								className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4"
								data-testid="poster-objective-recommender"
							>
								<div className="flex flex-wrap items-center justify-between gap-2">
									<p className="text-xs text-slate-400">
										Tak pasti objektif / jenis poster?
									</p>
									<button
										type="button"
										data-testid="poster-recommend-objectives"
										disabled={objectiveRecsLoading}
										onClick={() => void handleRecommendObjectives()}
										className="rounded-xl border border-blue-500/40 bg-blue-600/10 px-3 py-1.5 text-[11px] font-bold text-blue-200 disabled:opacity-40"
									>
										{objectiveRecsLoading ? "Analyzing…" : "Suggest for me ✦"}
									</button>
								</div>
								{objectiveRecs.length > 0 ? (
									<ol className="mt-3 space-y-1" data-testid="poster-objective-recs">
										{objectiveRecs.slice(0, 3).map((r, i) => (
											<li key={r.recipe_id}>
												<button
													type="button"
													onClick={() => handleSelectRecipe(r.recipe_id)}
													className={`w-full rounded-lg border px-3 py-2 text-left text-[11px] ${
														draft.poster_recipe_id === r.recipe_id
															? "border-blue-400 bg-blue-500/15 text-blue-100"
															: "border-slate-700 text-slate-300 hover:border-blue-500/40"
													}`}
												>
													<span className="font-bold">
														{i + 1}. {r.objective}
													</span>{" "}
													<span className="text-slate-400">— {r.reason}</span>
													{r.source === "AI" ? " ✦" : ""}
												</button>
											</li>
										))}
									</ol>
								) : null}
							</section>
							<PosterRecipeSelector
								recipes={recipes}
								selectedRecipeId={draft.poster_recipe_id}
								onSelect={handleSelectRecipe}
								error={recipesError}
							/>
							<section
								className="rounded-2xl border border-slate-800 bg-slate-950/60 p-4"
								data-testid="poster-product-ref-banner"
							>
								{productReferenceReady ? (
									<p
										data-testid="poster-product-ref-confirmed"
										className="text-[11px] text-emerald-300"
									>
										✓ Product reference image confirmed — the poster will anchor
										on the real product image.
									</p>
								) : (
									<p className="text-[11px] text-rose-300">
										{PRODUCT_REFERENCE_IMAGE_REQUIRED} — this product has no reference image;
										set the product image first (generation is blocked).
									</p>
								)}
							</section>
							{draft.poster_recipe_id && selectedRecipe ? (
								<>
									<PosterControlledSettings
										draft={draft}
										onDraftChange={setDraft}
										settings={builderSettings}
										recipe={selectedRecipe}
									/>
									<PosterAngleCopyStep
										productId={selectedProduct?.id ?? ""}
										archetype={selectedRecipe.archetype}
										recipeId={selectedRecipe.recipe_id}
										language={draft.language}
										onApproved={handleApprovedCopySet}
									/>
									{approvedCopySet ? (
										<div
											data-testid="poster-approved-copy-note"
											className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-[11px] text-emerald-200"
										>
											<span>
												✓ Copy approved (Poster Copy Set v{approvedCopySet.version}).
												To edit, open a new version — the original set stays immutable.
											</span>
											<button
												type="button"
												data-testid="poster-copy-create-new-version"
												disabled={copyVersionLoading !== ""}
												onClick={() => void handleCreateCopyVersion()}
												className="rounded-lg border border-emerald-400/40 px-3 py-1.5 font-semibold text-emerald-100 disabled:opacity-40"
											>
												{copyVersionLoading === "create"
													? "Membuka versi…"
													: "Open a new version to edit"}
											</button>
										</div>
									) : null}
									{editingCopySet ? (
										<div
											data-testid="poster-copy-version-draft"
											className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-[11px] text-amber-100"
										>
											<span>
												New version v{editingCopySet.version} is being edited. Save &
												approve to bind this copy back into the compositor.
											</span>
											<button
												type="button"
												data-testid="poster-copy-save-new-version"
												disabled={copyVersionLoading !== "" || !draft.hook || !draft.cta}
												onClick={() => void handleApproveCopyVersion()}
												className="rounded-lg border border-amber-300/50 px-3 py-1.5 font-semibold text-amber-50 disabled:opacity-40"
											>
												{copyVersionLoading === "approve"
													? "Menyimpan…"
													: "Save & approve the new version"}
											</button>
										</div>
									) : null}
									{copyVersionError ? (
										<p data-testid="poster-copy-version-error" className="text-[11px] text-rose-300">
											{copyVersionError}
										</p>
									) : null}
									<PosterRecipeSlotEditor
										recipe={selectedRecipe}
										draft={draft}
										onDraftChange={setDraft}
										copyLocked={approvedCopySet !== null}
									/>
									<PosterCopyQualityPanel
										report={posterQualityFresh ? posterQuality : null}
										stale={posterQualityStale}
										loading={posterQualityLoading}
										onCheck={() => void handleCheckPosterQuality()}
									/>
									<section
										className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5"
										data-testid="poster-recipe-generate"
									>
										<h3 className="text-sm font-bold text-slate-100">
											5. Generate poster prompt package
										</h3>
										{missingCopy.length > 0 ? (
											<p className="mt-2 text-[11px] text-amber-300">
												Isi dulu: <strong>{missingCopy.join(", ")}</strong>.
											</p>
										) : null}
										{overLimitCopy.length > 0 ? (
											<p className="mt-2 text-[11px] text-rose-300">
												Terlalu panjang: <strong>{overLimitCopy.join(", ")}</strong>.
											</p>
										) : null}
										{posterQualityBlocked ? (
											<p
												data-testid="poster-quality-block-note"
												className="mt-2 text-[11px] text-rose-300"
											>
												Poster quality failed ({posterQuality?.block_count} issues) — fix the copy before generating.
											</p>
										) : missingCopy.length === 0 &&
											overLimitCopy.length === 0 &&
											posterQualityNeedsCheck ? (
											<p
												data-testid="poster-quality-needscheck-note"
												className="mt-2 text-[11px] text-amber-300"
											>
												{posterQualityStale
													? "Copy changed after review — recheck poster quality before generating."
													: "Check poster quality first — generation is blocked until it passes."}
											</p>
										) : null}
										<button
											type="button"
											data-testid="recipe-generate-prompt-draft"
											disabled={
												!promptDraftEnabled ||
												promptLoading ||
												missingCopy.length > 0 ||
												overLimitCopy.length > 0 ||
												posterQualityNeedsCheck ||
												posterQualityBlocked
											}
											onClick={() => void handlePromptDraft(draftRef.current)}
											className="mt-3 rounded-xl border border-blue-500/50 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40"
										>
											{promptLoading ? "Generating…" : promptDraftLabel}
										</button>
									</section>
								</>
							) : (
								<p
									data-testid="poster-recipe-required-hint"
									className="text-sm text-slate-400"
								>
									Pick a poster recipe above to continue to settings + copy slots.
								</p>
							)}
							<details
								className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4"
								data-testid="poster-advanced-legacy"
							>
								<summary className="cursor-pointer text-xs font-bold uppercase tracking-[0.14em] text-slate-400">
									Advanced / legacy modes (Auto · Guided · Manual Expert)
								</summary>
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
									settings={builderSettings}
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

							</details>
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
									Poster scene generation
								</h3>
								<p className="mt-1 text-[11px] text-slate-500">
									The Recipe path generates a <strong>clean scene</strong> (product +
									background, no marketing text) — the final text is drawn by
									the compositor afterwards, so spelling is always exact.
								</p>
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
										Generate a <strong>prompt draft</strong> above first — the poster
										image is generated from that prompt package.
									</p>
								) : promptPackage.prompt_package_status === "PREVIEW_ONLY" ? (
									<p className="mt-2 text-[11px] text-amber-300">
										Note: this copy is review-only (not an approved Copy Set).
										The poster can still be generated for review.
									</p>
								) : null}
								{!productReferenceReady ? (
									<p
										data-testid="poster-product-ref-required"
										className="mt-2 text-[11px] text-rose-300"
									>
										{PRODUCT_REFERENCE_IMAGE_REQUIRED} — this product has no
										reference image. A product poster must anchor on the real
										product image; set the product image first. Generation is blocked.
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
										? posterGenStage === "inserting_canonical_product"
											? "Inserting canonical product…"
											: posterGenStage === "generating_scene"
												? "Generating scene…"
												: "Generating poster…"
										: "Generate poster image"}
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
											alt="Generated poster"
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

							<PosterComposePanel
								productId={selectedProduct?.id ?? ""}
								recipeId={draft.poster_recipe_id}
								copySet={approvedCopySet}
								backgroundMediaId={posterGenResult?.mediaId ?? ""}
							/>
							<PosterSpecPreview
								posterSpec={promptPackage?.poster_spec}
								overlaySpec={promptPackage?.overlay_spec}
							/>
							<PosterPromptPackagePreview package_={promptPackage} error={promptError} />
						</>
					) : null}

					<details className="rounded-2xl border border-slate-800 bg-slate-950/40 p-5">
						<summary className="cursor-pointer text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500 hover:text-slate-300">
							Draft JSON preview (technical)
						</summary>
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
					</details>
				</>
			) : null}
			{posterGenConfirm ? (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
					<div className="max-w-md space-y-3 rounded-2xl border border-rose-500/40 bg-slate-950 p-5">
						<div className="text-sm font-bold text-rose-100">
							Confirm poster generation (credit-free)
						</div>
						<div className="text-[11px] text-slate-300">
							This calls the live image lane (<code>POST /api/flow/generate</code>{" "}
							mode:IMG). Image generation is <strong>credit-free</strong> (only
							video costs credits). It will not run without this confirmation.
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
								Confirm &amp; Generate (live)
							</button>
						</div>
					</div>
				</div>
			) : null}
		</div>
	);
}

// Default Poster Builder = the clean guided journey. The full legacy control
// panel is relocated under a collapsed "Advanced Diagnostics / Legacy
// Compatibility" disclosure and only mounts when the operator expands it (so its
// data-fetching effects never run in the normal flow).
export default function PosterBuilderPage() {
	const [advancedOpen, setAdvancedOpen] = useState(false);
	const [sessionResults, setSessionResults] = useState<SessionResult[]>([]);
	const [searchParams] = useSearchParams();
	const useV4 = searchParams.get("classic") !== "1";
	const advancedDiagnostics = (
		<details
			className="rounded-2xl border border-slate-800 bg-slate-950/40 p-4"
			data-testid="poster-advanced-diagnostics"
			onToggle={(e) => setAdvancedOpen((e.currentTarget as HTMLDetailsElement).open)}
		>
			<summary className="cursor-pointer text-xs font-bold uppercase tracking-[0.14em] text-slate-400">
				Advanced Diagnostics / Legacy Compatibility
			</summary>
			<p className="mt-2 text-[11px] text-amber-300/80">
				For troubleshooting and advanced controls only — not needed for
				normal poster creation.
			</p>
			<div className="mt-4 border-t border-slate-800 pt-4">
				{advancedOpen ? <PosterBuilderLegacyPanel /> : null}
			</div>
		</details>
	);

	if (useV4) {
		return (
			<div
				data-testid="poster-builder-v4-shell"
				data-variant="v4"
				className="min-h-full bg-slate-950 px-4 py-4 text-slate-100 md:px-8 md:py-6"
			>
				<header className="mb-5 flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-violet-500/30 bg-gradient-to-br from-slate-950 via-slate-950 to-violet-950/30 p-5 shadow-2xl">
					<div>
						<div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.2em] text-violet-300">
							<ImageIcon size={15} /> Creative · V4
						</div>
						<h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-100">
							Poster Builder
						</h1>
						<p className="mt-2 max-w-3xl text-sm text-slate-400">
							Bespoke poster orchestration with the existing guided journey and
							advanced Auto, Guided, and Controlled modes preserved.
						</p>
					</div>
					<nav className="flex flex-wrap items-center gap-2 text-[11px] font-semibold">
						<a
							href="/assets/img-cockpit"
							className="rounded-lg border border-v4-accent/30 bg-v4-accent/10 px-3 py-1.5 text-v4-accent-ink"
						>
							IMG Cockpit ↗
						</a>
						<a
							href="/creative/copy-registry"
							className="rounded-lg border border-slate-700 px-3 py-1.5 text-slate-300"
						>
							Copy Registry ↗
						</a>
						<a
							href="/creative/poster-builder?classic=1"
							className="rounded-lg border border-slate-700 px-3 py-1.5 text-slate-400"
						>
							Switch to classic view
						</a>
					</nav>
				</header>

				<div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_20rem]">
					<main className="min-w-0 space-y-4">
						<WorkflowStep
							index={1}
							title="Poster production workspace"
							status="active"
							helper="The poster-native journey remains multi-step; this V4 frame does not collapse its creative modes into a single-shot lane."
							collapsible={false}
						>
							<PosterGuidedShell
								onResult={(r) =>
									setSessionResults((prev) =>
										prev.some((x) => x.media_id === r.media_id)
											? prev
											: [{ ...r, deletable: false }, ...prev],
									)
								}
							/>
						</WorkflowStep>
						{advancedDiagnostics}
					</main>

					<aside className="w-full xl:w-80 xl:flex-none xl:min-h-0 xl:overflow-y-auto">
						<ResultsSidebar
							results={sessionResults}
							onRemoved={(mediaId) =>
								setSessionResults((prev) =>
									prev.filter((r) => r.media_id !== mediaId),
								)
							}
						/>
					</aside>
				</div>
			</div>
		);
	}

	return (
		<div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6" data-testid="poster-builder-page">
			<PosterGuidedShell />
			{advancedDiagnostics}
		</div>
	);
}
