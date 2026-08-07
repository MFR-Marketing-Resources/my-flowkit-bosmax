import { useCallback, useRef, useState } from "react";
import {
	buildExactSceneOnlyPrompt,
	resolveExactGenerationGate,
} from "../../api/exactProductOutput";
import { pollImgGenerationJob, startImgGeneration } from "../../api/imgFactory";
import {
	approvePosterCopySet,
	composePoster,
	createPosterCopySet,
	forkPosterCopySetFromHistorical,
	generatePosterDirections,
	newPosterCopySetVersion,
	patchPosterCopySet,
	recommendPosterAngles,
	recommendPosterObjectives,
	regeneratePosterField,
	savePosterToLibrary,
} from "../../api/posterCopySets";
import { fetchPosterReadiness } from "../../api/posterReadiness";
import {
	createPosterPromptDraft,
	formatPosterPromptDraftError,
} from "../../api/posterPromptDraft";
import { productSubjectAsset } from "../../utils/productSubjectAsset";
import type { Product } from "../../types";
import {
	POSTER_COPY_APPROVAL_PHRASE,
	type PosterAngleRecommendation,
	type PosterComposeResponse,
	type PosterCopyDirection,
	type PosterCopySet,
	type PosterDeliverableReconstruction,
	type PosterObjectiveRecommendation,
	type PosterQAReport,
} from "../../types/posterCopySet";
import type { PosterReadinessResponse } from "../../types/posterReadiness";
import { GUIDED_STEPS, type GuidedStepId, stepIndex } from "./posterGuided";

// Editable working copy of a poster-native copy set (user-facing field names).
export interface GuidedCopyFields {
	primary_message: string;
	support_message: string;
	proof_points: string[];
	cta: string;
	disclaimer: string;
	tone: string;
	language: string;
}

const EMPTY_FIELDS: GuidedCopyFields = {
	primary_message: "",
	support_message: "",
	proof_points: [],
	cta: "",
	disclaimer: "",
	tone: "",
	language: "ms",
};

function directionToFields(d: PosterCopyDirection): GuidedCopyFields {
	return {
		primary_message: d.primary_message,
		support_message: d.support_message,
		proof_points: [...(d.proof_points ?? [])],
		cta: d.cta,
		disclaimer: d.disclaimer,
		tone: d.tone,
		language: d.language || "ms",
	};
}

function copySetToFields(pcs: PosterCopySet): GuidedCopyFields {
	return {
		primary_message: pcs.primary_message,
		support_message: pcs.support_message,
		proof_points: [...(pcs.proof_points ?? [])],
		cta: pcs.cta,
		disclaimer: pcs.disclaimer,
		tone: pcs.tone,
		language: pcs.language || "ms",
	};
}

function fieldsToPatch(fields: GuidedCopyFields): Record<string, unknown> {
	return {
		primary_message: fields.primary_message,
		support_message: fields.support_message,
		proof_points: fields.proof_points,
		cta: fields.cta,
		disclaimer: fields.disclaimer,
		tone: fields.tone,
		language: fields.language,
	};
}

// User-facing failure text: lead with OUR friendly explanation; append the
// backend reason only when it is short human text (never raw JSON / stacks).
function friendlyError(e: unknown, fallback: string): string {
	const msg = e instanceof Error ? (e.message ?? "").trim() : "";
	const looksRaw =
		!msg ||
		msg.length > 160 ||
		msg.startsWith("{") ||
		msg.startsWith("[") ||
		msg.includes("Traceback") ||
		msg.includes("<html");
	return looksRaw ? fallback : `${fallback} (${msg})`;
}

function normalizeQa(qa: unknown): PosterQAReport {
	const candidate = qa as PosterQAReport | null | undefined;
	if (candidate && Array.isArray(candidate.findings)) return candidate;
	return { ok: false, findings: [], block_count: 0, warn_count: 0 };
}

export interface PosterGuidedWorkflow {
	// navigation
	step: GuidedStepId;
	reached: GuidedStepId[];
	goTo: (step: GuidedStepId) => void;
	reach: (step: GuidedStepId) => void;
	canGoTo: (step: GuidedStepId) => boolean;
	// product
	product: Product | null;
	selectProduct: (p: Product | null) => void;
	// readiness
	readiness: PosterReadinessResponse | null;
	readinessLoading: boolean;
	readinessError: string;
	// goal
	objectiveRecs: PosterObjectiveRecommendation[];
	recommendedArchetype: string | null;
	goalsLoading: boolean;
	goalsError: string;
	recommendGoals: () => Promise<void>;
	goalArchetype: string | null;
	goalRecipeId: string | null;
	objectiveText: string;
	selectGoal: (
		archetype: string,
		recipeId?: string,
		objective?: string,
	) => void;
	// angle
	angles: PosterAngleRecommendation[];
	anglesLoading: boolean;
	anglesError: string;
	selectedAngle: string;
	selectAngle: (angle: string) => void;
	loadAngles: () => Promise<void>;
	// copy directions
	directions: PosterCopyDirection[];
	directionsLoading: boolean;
	directionsError: string;
	directionWarnings: string[];
	selectedDirection: number | null;
	loadDirections: () => Promise<void>;
	selectDirection: (index: number) => void;
	fields: GuidedCopyFields;
	updateField: (
		field: keyof GuidedCopyFields,
		value: string | string[],
	) => void;
	regenField: (field: string) => Promise<void>;
	fieldRegenLoading: string;
	fieldRegenError: string;
	// approval lifecycle. `editingCopySetId` is the ALREADY-CREATED draft (a new
	// version or a historical fork) — approve() must patch+approve THAT row, never
	// create a duplicate copy set.
	approvedCopySet: PosterCopySet | null;
	editingCopySetId: string | null;
	approveLoading: boolean;
	approveError: string;
	approve: () => Promise<void>;
	editApproved: () => Promise<void>;
	// reopen (Creative Library round trip)
	historicalCopySet: PosterCopySet | null;
	restoreFromReopen: (
		recon: PosterDeliverableReconstruction,
		product: Product | null,
	) => void;
	reuseSameCopy: () => void;
	duplicatePoster: () => void;
	forkHistorical: () => Promise<void>;
	forkLoading: boolean;
	forkError: string;
	// visual
	recipeId: string | null;
	creativeMode: string;
	setCreativeMode: (mode: string) => void;
	selectRecipe: (recipeId: string) => void;
	// scene
	backgroundMediaId: string;
	setBackgroundMediaId: (id: string) => void;
	sceneGenerationLoading: boolean;
	sceneGenerationStage: string;
	sceneGenerationError: string;
	generatedSceneMediaId: string | null;
	generatedSceneUrl: string | null;
	generateScene: () => Promise<void>;
	// compose
	compose: () => Promise<void>;
	composeLoading: boolean;
	composeError: string;
	deliverable: PosterComposeResponse | null;
	// save
	save: () => Promise<void>;
	saveLoading: boolean;
	saveError: string;
	savedAssetId: string | null;
}

export function usePosterGuidedWorkflow(): PosterGuidedWorkflow {
	const [step, setStep] = useState<GuidedStepId>("product");
	const [reached, setReached] = useState<GuidedStepId[]>(["product"]);
	const [product, setProduct] = useState<Product | null>(null);

	const [readiness, setReadiness] = useState<PosterReadinessResponse | null>(
		null,
	);
	const [readinessLoading, setReadinessLoading] = useState(false);
	const [readinessError, setReadinessError] = useState("");

	const [objectiveRecs, setObjectiveRecs] = useState<
		PosterObjectiveRecommendation[]
	>([]);
	const [recommendedArchetype, setRecommendedArchetype] = useState<
		string | null
	>(null);
	const [goalsLoading, setGoalsLoading] = useState(false);
	const [goalsError, setGoalsError] = useState("");
	const [goalArchetype, setGoalArchetype] = useState<string | null>(null);
	const [goalRecipeId, setGoalRecipeId] = useState<string | null>(null);
	const [objectiveText, setObjectiveText] = useState("");

	const [angles, setAngles] = useState<PosterAngleRecommendation[]>([]);
	const [anglesLoading, setAnglesLoading] = useState(false);
	const [anglesError, setAnglesError] = useState("");
	const [selectedAngle, setSelectedAngle] = useState("");

	const [directions, setDirections] = useState<PosterCopyDirection[]>([]);
	const [directionsLoading, setDirectionsLoading] = useState(false);
	const [directionsError, setDirectionsError] = useState("");
	const [directionWarnings, setDirectionWarnings] = useState<string[]>([]);
	const [selectedDirection, setSelectedDirection] = useState<number | null>(
		null,
	);
	const [fields, setFields] = useState<GuidedCopyFields>(EMPTY_FIELDS);

	const [fieldRegenLoading, setFieldRegenLoading] = useState("");
	const [fieldRegenError, setFieldRegenError] = useState("");

	const [approvedCopySet, setApprovedCopySet] = useState<PosterCopySet | null>(
		null,
	);
	const [editingCopySetId, setEditingCopySetId] = useState<string | null>(null);
	const [approveLoading, setApproveLoading] = useState(false);
	const [approveError, setApproveError] = useState("");

	const [historicalCopySet, setHistoricalCopySet] =
		useState<PosterCopySet | null>(null);
	const [forkLoading, setForkLoading] = useState(false);
	const [forkError, setForkError] = useState("");

	const [recipeId, setRecipeId] = useState<string | null>(null);
	const [creativeMode, setCreativeModeState] = useState("");
	const [backgroundMediaId, setBackgroundMediaIdState] = useState("");
	const [sceneGenerationLoading, setSceneGenerationLoading] = useState(false);
	const [sceneGenerationStage, setSceneGenerationStage] = useState("");
	const [sceneGenerationError, setSceneGenerationError] = useState("");
	const [generatedSceneMediaId, setGeneratedSceneMediaId] = useState<
		string | null
	>(null);
	const [generatedSceneUrl, setGeneratedSceneUrl] = useState<string | null>(
		null,
	);
	const sceneGenerationTokenRef = useRef(0);

	const [deliverable, setDeliverable] = useState<PosterComposeResponse | null>(
		null,
	);
	const [composeLoading, setComposeLoading] = useState(false);
	const [composeError, setComposeError] = useState("");

	const [savedAssetId, setSavedAssetId] = useState<string | null>(null);
	const [saveLoading, setSaveLoading] = useState(false);
	const [saveError, setSaveError] = useState("");

	const invalidateScene = useCallback(() => {
		sceneGenerationTokenRef.current += 1;
		setBackgroundMediaIdState("");
		setSceneGenerationError("");
		setSceneGenerationStage("");
		setGeneratedSceneMediaId(null);
		setGeneratedSceneUrl(null);
	}, []);

	const setCreativeMode = useCallback(
		(mode: string) => {
			if (mode !== creativeMode) invalidateScene();
			setCreativeModeState(mode);
		},
		[creativeMode, invalidateScene],
	);

	const setBackgroundMediaId = useCallback(
		(id: string) => {
			setBackgroundMediaIdState(id);
			if (id !== generatedSceneMediaId) {
				setGeneratedSceneMediaId(null);
				setGeneratedSceneUrl(null);
			}
		},
		[generatedSceneMediaId],
	);

	const reach = useCallback((target: GuidedStepId) => {
		setReached((prev) => (prev.includes(target) ? prev : [...prev, target]));
		setStep(target);
	}, []);

	const canGoTo = useCallback(
		(target: GuidedStepId) => reached.includes(target),
		[reached],
	);
	const goTo = useCallback(
		(target: GuidedStepId) => {
			if (reached.includes(target)) setStep(target);
		},
		[reached],
	);

	// Selecting a product invalidates EVERYTHING downstream.
	const selectProduct = useCallback((p: Product | null) => {
		invalidateScene();
		setProduct(p);
		setReadiness(null);
		setReadinessError("");
		setObjectiveRecs([]);
		setRecommendedArchetype(null);
		setGoalsError("");
		setGoalArchetype(null);
		setGoalRecipeId(null);
		setObjectiveText("");
		setAngles([]);
		setSelectedAngle("");
		setDirections([]);
		setSelectedDirection(null);
		setFields(EMPTY_FIELDS);
		setApprovedCopySet(null);
		setEditingCopySetId(null);
		setHistoricalCopySet(null);
		setForkError("");
		setRecipeId(null);
		setDeliverable(null);
		setSavedAssetId(null);
		setReached(p ? ["product", "goal"] : ["product"]);
		setStep(p ? "goal" : "product");
		if (!p) return;
		setReadinessLoading(true);
		void fetchPosterReadiness(p.id)
			.then((r) => setReadiness(r))
			.catch((e) =>
				setReadinessError(friendlyError(e, "Gagal menyemak kesediaan produk.")),
			)
			.finally(() => setReadinessLoading(false));
	}, [invalidateScene]);

	const recommendGoals = useCallback(async () => {
		if (!product) return;
		setGoalsLoading(true);
		setGoalsError("");
		try {
			const res = await recommendPosterObjectives({
				product_id: product.id,
				refresh_ai: true,
			});
			setObjectiveRecs(res.recommendations ?? []);
			setRecommendedArchetype(res.recommendations?.[0]?.archetype ?? null);
		} catch (e) {
			setRecommendedArchetype(null);
			setGoalsError(
				friendlyError(
					e,
					"Gagal mendapatkan cadangan tujuan. Anda masih boleh memilih sendiri di bawah.",
				),
			);
		} finally {
			setGoalsLoading(false);
		}
	}, [product]);

	const loadAngles = useCallback(async () => {
		if (!product || !goalArchetype) return;
		setAnglesLoading(true);
		setAnglesError("");
		try {
			const res = await recommendPosterAngles({
				product_id: product.id,
				archetype: goalArchetype,
				// The guided path must remain immediately usable with the curated,
				// deterministic recipe angles. AI enrichment is optional and can
				// otherwise hold this zero-spend step open on provider latency.
				refresh_ai: false,
			});
			setAngles(res.angles ?? []);
		} catch (e) {
			setAnglesError(
				friendlyError(e, "Gagal menjana sudut jualan. Cuba lagi."),
			);
		} finally {
			setAnglesLoading(false);
		}
	}, [product, goalArchetype]);

	// Selecting a goal invalidates angle + copy downstream.
	const selectGoal = useCallback(
		(archetype: string, recipe?: string, objective?: string) => {
			invalidateScene();
			setGoalArchetype(archetype);
			setGoalRecipeId(recipe ?? null);
			setObjectiveText(objective ?? "");
			setAngles([]);
			setSelectedAngle("");
			setDirections([]);
			setSelectedDirection(null);
			setFields(EMPTY_FIELDS);
			setApprovedCopySet(null);
			setEditingCopySetId(null);
			setHistoricalCopySet(null);
			setRecipeId(null);
			setDeliverable(null);
			setReached((prev) => {
				const keep = prev.filter((s) => stepIndex(s) <= stepIndex("goal"));
				return keep.includes("angle") ? keep : [...keep, "angle"];
			});
			setStep("angle");
		},
		[invalidateScene],
	);

	const loadDirections = useCallback(async () => {
		if (!product || !goalArchetype || !selectedAngle) return;
		setDirectionsLoading(true);
		setDirectionsError("");
		try {
			const res = await generatePosterDirections({
				product_id: product.id,
				archetype: goalArchetype,
				angle: selectedAngle,
				language: "ms",
				count: 3,
			});
			setDirections(res.directions ?? []);
			setDirectionWarnings(res.warnings ?? []);
		} catch (e) {
			setDirectionsError(
				friendlyError(e, "Gagal menjana arah teks. Cuba lagi."),
			);
		} finally {
			setDirectionsLoading(false);
		}
	}, [product, goalArchetype, selectedAngle]);

	// Selecting an angle invalidates copy downstream and advances to copy.
	const selectAngle = useCallback((angle: string) => {
		invalidateScene();
		setSelectedAngle(angle);
		setDirections([]);
		setSelectedDirection(null);
		setFields(EMPTY_FIELDS);
		setApprovedCopySet(null);
		setEditingCopySetId(null);
		setHistoricalCopySet(null);
		setReached((prev) => {
			const keep = prev.filter((s) => stepIndex(s) <= stepIndex("angle"));
			return keep.includes("copy") ? keep : [...keep, "copy"];
		});
		setStep("copy");
	}, [invalidateScene]);

	const selectDirection = useCallback(
		(index: number) => {
			const d = directions[index];
			if (!d) return;
			invalidateScene();
			setSelectedDirection(index);
			setFields(directionToFields(d));
			// Choosing a fresh AI direction is a BRAND-NEW copy flow — abandon any
			// in-flight version draft so approve() creates rather than patches.
			setEditingCopySetId(null);
			setHistoricalCopySet(null);
			setApprovedCopySet(null);
			setReached((prev) =>
				prev.includes("approve") ? prev : [...prev, "approve"],
			);
		},
		[directions, invalidateScene],
	);

	const updateField = useCallback(
		(field: keyof GuidedCopyFields, value: string | string[]) => {
			invalidateScene();
			setFields((prev) => ({ ...prev, [field]: value }));
			// Editing invalidates a prior approval (but NOT the editing draft id —
			// the whole point of the version draft is to receive these edits).
			setApprovedCopySet(null);
		},
		[invalidateScene],
	);

	const regenField = useCallback(
		async (field: string) => {
			if (!product || !goalArchetype) return;
			invalidateScene();
			setFieldRegenLoading(field);
			setFieldRegenError("");
			try {
				const res = await regeneratePosterField({
					product_id: product.id,
					archetype: goalArchetype,
					angle: selectedAngle,
					field,
					language: fields.language,
					fields: { ...fields },
				});
				setFields(
					(prev) => ({ ...prev, [field]: res.value }) as GuidedCopyFields,
				);
				setApprovedCopySet(null);
			} catch (e) {
				setFieldRegenError(
					friendlyError(
						e,
						"Gagal menjana semula medan ini. Teks asal dikekalkan — cuba lagi.",
					),
				);
			} finally {
				setFieldRegenLoading("");
			}
		},
		[product, goalArchetype, selectedAngle, fields, invalidateScene],
	);

	const approve = useCallback(async () => {
		if (!product || !goalArchetype) return;
		invalidateScene();
		setApproveLoading(true);
		setApproveError("");
		try {
			let draftId = editingCopySetId;
			if (draftId) {
				// Version-draft path: reuse the EXISTING draft row (parent lineage
				// already recorded by new-version/fork) — never create a duplicate.
				await patchPosterCopySet(draftId, fieldsToPatch(fields));
			} else {
				const draft = await createPosterCopySet({
					product_id: product.id,
					objective: objectiveText || "Poster",
					archetype: goalArchetype,
					angle: selectedAngle,
					...fieldsToPatch(fields),
				});
				draftId = draft.poster_copy_set_id;
			}
			const approved = await approvePosterCopySet(
				draftId,
				POSTER_COPY_APPROVAL_PHRASE,
			);
			setApprovedCopySet(approved);
			setEditingCopySetId(null);
			// Stay on the approve step to show the read-only approved state; the
			// operator continues to the visual step explicitly.
			setReached((prev) =>
				prev.includes("visual") ? prev : [...prev, "visual"],
			);
		} catch (e) {
			setApproveError(
				friendlyError(e, "Teks tidak lulus semakan. Perbaiki dan cuba lagi."),
			);
		} finally {
			setApproveLoading(false);
		}
	}, [
		product,
		goalArchetype,
		selectedAngle,
		objectiveText,
		fields,
		editingCopySetId,
		invalidateScene,
	]);

	// Editing approved copy uses the immutable new-version lifecycle. The created
	// draft id is KEPT so approve() patches it instead of creating a duplicate.
	const editApproved = useCallback(async () => {
		if (!approvedCopySet) return;
		invalidateScene();
		setApproveLoading(true);
		setApproveError("");
		try {
			const draft = await newPosterCopySetVersion(
				approvedCopySet.poster_copy_set_id,
				{},
			);
			setEditingCopySetId(draft.poster_copy_set_id);
			setApprovedCopySet(null);
			setFields(copySetToFields(draft));
			setReached((prev) => (prev.includes("copy") ? prev : [...prev, "copy"]));
			setStep("copy");
		} catch (e) {
			setApproveError(friendlyError(e, "Gagal membuka versi baharu."));
		} finally {
			setApproveLoading(false);
		}
	}, [approvedCopySet, invalidateScene]);

	// ── Creative Library reopen ────────────────────────────────────────────────

	const restoreFromReopen = useCallback(
		(recon: PosterDeliverableReconstruction, p: Product | null) => {
			sceneGenerationTokenRef.current += 1;
			const pcs = recon.poster_copy_set;
			const historical =
				!!recon.poster_copy_set_historical ||
				pcs?.status === "POSTER_COPY_SUPERSEDED";
			setProduct(p);
			setReadiness(null);
			setReadinessError("");
			if (p) {
				setReadinessLoading(true);
				void fetchPosterReadiness(p.id)
					.then((r) => setReadiness(r))
					.catch((e) =>
						setReadinessError(
							friendlyError(e, "Gagal menyemak kesediaan produk."),
						),
					)
					.finally(() => setReadinessLoading(false));
			}
			setGoalArchetype(pcs?.archetype ?? null);
			setGoalRecipeId(recon.deliverable.recipe_id ?? null);
			setObjectiveText(pcs?.objective ?? "");
			setAngles([]);
			setSelectedAngle(pcs?.angle ?? "");
			setDirections([]);
			setSelectedDirection(null);
			setFields(pcs ? copySetToFields(pcs) : EMPTY_FIELDS);
			setApprovedCopySet(
				!historical && pcs?.status === "POSTER_COPY_APPROVED" ? pcs : null,
			);
			setHistoricalCopySet(historical ? pcs : null);
			setEditingCopySetId(null);
			setForkError("");
			setRecipeId(recon.deliverable.recipe_id ?? null);
			setCreativeModeState(
				String(
					(
						recon.render_manifest?.provenance as
							| { creative_mode?: string }
							| undefined
					)?.creative_mode ?? "",
				),
			);
			setBackgroundMediaIdState(recon.deliverable.background_media_id ?? "");
			setSceneGenerationLoading(false);
			setSceneGenerationStage("");
			setSceneGenerationError("");
			setGeneratedSceneMediaId(null);
			setGeneratedSceneUrl(null);
			setDeliverable({
				deliverable: recon.deliverable,
				render_report: {},
				qa_report: normalizeQa(recon.qa_report),
			});
			setSavedAssetId(recon.deliverable.creative_asset_id || null);
			// The whole journey is restored — every step is navigable and the user
			// lands on the saved poster, not an empty product wizard.
			setReached(GUIDED_STEPS.map((s) => s.id));
			setStep("save");
		},
		[],
	);

	// Reopen action: keep the SAME approved copy and go straight to visual choice.
	const reuseSameCopy = useCallback(() => {
		if (!approvedCopySet) return;
		setDeliverable(null);
		setSavedAssetId(null);
		setStep("visual");
	}, [approvedCopySet]);

	// Reopen action: same copy + same visual/scene, fresh compose (the original
	// deliverable and saved asset are never touched).
	const duplicatePoster = useCallback(() => {
		setDeliverable(null);
		setSavedAssetId(null);
		setReached((prev) =>
			prev.includes("compose") ? prev : [...prev, "compose"],
		);
		setStep("compose");
	}, []);

	// Historical (superseded) copy stays read-only; forking creates an editable
	// DRAFT lineage-linked to the historical row, preserving the original record.
	const forkHistorical = useCallback(async () => {
		if (!historicalCopySet) return;
		invalidateScene();
		setForkLoading(true);
		setForkError("");
		try {
			const draft = await forkPosterCopySetFromHistorical(
				historicalCopySet.poster_copy_set_id,
			);
			setEditingCopySetId(draft.poster_copy_set_id);
			setHistoricalCopySet(null);
			setApprovedCopySet(null);
			setFields(copySetToFields(draft));
			setReached((prev) => (prev.includes("copy") ? prev : [...prev, "copy"]));
			setStep("copy");
		} catch (e) {
			setForkError(
				friendlyError(
					e,
					"Gagal mencipta salinan boleh-edit daripada versi sejarah.",
				),
			);
		} finally {
			setForkLoading(false);
		}
	}, [historicalCopySet, invalidateScene]);

	const selectRecipe = useCallback((recipe: string) => {
		invalidateScene();
		setRecipeId(recipe);
		setDeliverable(null);
		setSavedAssetId(null);
		setReached((prev) => (prev.includes("scene") ? prev : [...prev, "scene"]));
		setStep("scene");
	}, [invalidateScene]);

	const generateScene = useCallback(async () => {
		if (!product || !approvedCopySet || !recipeId) {
			setSceneGenerationError(
				"Lengkapkan produk, teks yang disahkan dan gaya visual dahulu.",
			);
			return;
		}

		const token = ++sceneGenerationTokenRef.current;
		setSceneGenerationLoading(true);
		setSceneGenerationStage("building_prompt");
		setSceneGenerationError("");
		setBackgroundMediaIdState("");
		setGeneratedSceneMediaId(null);
		setGeneratedSceneUrl(null);

		try {
			const promptPackage = await createPosterPromptDraft({
				product_id: product.id,
				poster_objective:
					objectiveText || approvedCopySet.objective || "Poster",
				poster_type: goalArchetype || approvedCopySet.archetype || "PRODUCT_HERO",
				visual_route: selectedAngle || recipeId,
				human_presence_mode: "",
				frame_ratio: "9:16",
				language: fields.language || approvedCopySet.language || "ms",
				text_density: "medium",
				hook: fields.primary_message,
				subhook: fields.support_message,
				usp_1: fields.proof_points[0] || "",
				usp_2: fields.proof_points[1] || "",
				usp_3: fields.proof_points[2] || "",
				cta: fields.cta,
				operator_notes: selectedAngle
					? `Guided poster angle: ${selectedAngle}`
					: "Guided Poster Builder",
				creative_mode: creativeMode || undefined,
				copy_source: "APPROVED_POSTER_COPY_SET",
				poster_recipe_id: recipeId,
				poster_copy_set_id: approvedCopySet.poster_copy_set_id,
			});
			if (token !== sceneGenerationTokenRef.current) return;
			if (!promptPackage.generation_allowed || !promptPackage.poster_prompt) {
				throw new Error(
					promptPackage.blocked_reasons?.[0] ||
						"Produk belum dibenarkan untuk jana visual poster.",
				);
			}

			setSceneGenerationStage("validating_product");
			const gate = await resolveExactGenerationGate(product.id, undefined, {
				laneId: "POSTER_BUILDER",
				isPoster: true,
			});
			if (token !== sceneGenerationTokenRef.current) return;
			if (gate.mode === "blocked") throw new Error(gate.message);

			const exactComposite = gate.mode === "exact";
			const subjectAsset = productSubjectAsset(product);
			if (!exactComposite && !subjectAsset) {
				throw new Error(
					"PRODUCT_REFERENCE_IMAGE_REQUIRED — produk ini tiada gambar rujukan yang boleh digunakan.",
				);
			}

			let prompt = promptPackage.poster_prompt;
			if (exactComposite) {
				setSceneGenerationStage("preparing_exact_scene");
				const sceneOnly = await buildExactSceneOnlyPrompt(product.id, prompt);
				if (token !== sceneGenerationTokenRef.current) return;
				prompt = sceneOnly.prompt;
			}

			setSceneGenerationStage("generating_scene");
			const { job_id: jobId } = await startImgGeneration({
				product_id: product.id,
				visual_lane_id: "POSTER_BUILDER",
				prompt,
				aspect: "9:16",
				count: 1,
				...(subjectAsset && !exactComposite
					? { refs: { subjectAsset } }
					: {}),
			});
			if (token !== sceneGenerationTokenRef.current) return;

			setSceneGenerationStage("waiting_for_scene");
			const job = await pollImgGenerationJob(jobId);
			if (token !== sceneGenerationTokenRef.current) return;
			const status = String(job.status || "").toUpperCase();
			if (!(status === "DONE" || status === "COMPLETED") || !job.media_id) {
				throw new Error(
					job.error ||
						`Penjanaan visual tamat sebagai ${job.status || "UNKNOWN"} tanpa imej.`,
				);
			}

			// Compose owns the exact-product insertion. The generated artifact stays a
			// raw scene plate and is never treated as the final product-truth output.
			const mediaId = job.media_id;
			const url = job.url || `/api/flow/retrieved/${encodeURIComponent(mediaId)}`;
			setBackgroundMediaIdState(mediaId);
			setGeneratedSceneMediaId(mediaId);
			setGeneratedSceneUrl(url);
		} catch (e) {
			if (token !== sceneGenerationTokenRef.current) return;
			const promptError = formatPosterPromptDraftError(e);
			setSceneGenerationError(
				friendlyError(
					promptError === "Prompt draft failed" ? e : new Error(promptError),
					"Gagal menyediakan visual poster. Tiada poster dikompos sehingga visual berjaya.",
				),
			);
		} finally {
			if (token === sceneGenerationTokenRef.current) {
				setSceneGenerationLoading(false);
				setSceneGenerationStage("");
			}
		}
	}, [
		product,
		approvedCopySet,
		recipeId,
		objectiveText,
		goalArchetype,
		selectedAngle,
		fields,
		creativeMode,
	]);

	const compose = useCallback(async () => {
		if (!product || !approvedCopySet || !recipeId) return;
		setComposeLoading(true);
		setComposeError("");
		try {
			const res = await composePoster({
				product_id: product.id,
				poster_copy_set_id: approvedCopySet.poster_copy_set_id,
				recipe_id: recipeId,
				background_media_id: backgroundMediaId || undefined,
				creative_mode: creativeMode || undefined,
			});
			setDeliverable(res);
			setSavedAssetId(null);
			setReached((prev) => (prev.includes("save") ? prev : [...prev, "save"]));
		} catch (e) {
			setComposeError(
				friendlyError(
					e,
					"Gagal menghasilkan poster. Semak latar/aset dan cuba lagi.",
				),
			);
		} finally {
			setComposeLoading(false);
		}
	}, [product, approvedCopySet, recipeId, backgroundMediaId, creativeMode]);

	const save = useCallback(async () => {
		if (!deliverable) return;
		setSaveLoading(true);
		setSaveError("");
		try {
			const res = await savePosterToLibrary(
				deliverable.deliverable.poster_deliverable_id,
			);
			setSavedAssetId(res.creative_asset_id);
			setStep("save");
		} catch (e) {
			setSaveError(friendlyError(e, "Gagal menyimpan ke Creative Library."));
		} finally {
			setSaveLoading(false);
		}
	}, [deliverable]);

	return {
		step,
		reached,
		goTo,
		reach,
		canGoTo,
		product,
		selectProduct,
		readiness,
		readinessLoading,
		readinessError,
		objectiveRecs,
		recommendedArchetype,
		goalsLoading,
		goalsError,
		recommendGoals,
		goalArchetype,
		goalRecipeId,
		objectiveText,
		selectGoal,
		angles,
		anglesLoading,
		anglesError,
		selectedAngle,
		selectAngle,
		loadAngles,
		directions,
		directionsLoading,
		directionsError,
		directionWarnings,
		selectedDirection,
		loadDirections,
		selectDirection,
		fields,
		updateField,
		regenField,
		fieldRegenLoading,
		fieldRegenError,
		approvedCopySet,
		editingCopySetId,
		approveLoading,
		approveError,
		approve,
		editApproved,
		historicalCopySet,
		restoreFromReopen,
		reuseSameCopy,
		duplicatePoster,
		forkHistorical,
		forkLoading,
		forkError,
		recipeId,
		creativeMode,
		setCreativeMode,
		selectRecipe,
		backgroundMediaId,
		setBackgroundMediaId,
		sceneGenerationLoading,
		sceneGenerationStage,
		sceneGenerationError,
		generatedSceneMediaId,
		generatedSceneUrl,
		generateScene,
		compose,
		composeLoading,
		composeError,
		deliverable,
		save,
		saveLoading,
		saveError,
		savedAssetId,
	};
}
