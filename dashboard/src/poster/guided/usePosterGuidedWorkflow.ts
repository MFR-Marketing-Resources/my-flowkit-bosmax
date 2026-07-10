import { useCallback, useState } from "react";
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
	selectRecipe: (recipeId: string) => void;
	// scene
	backgroundMediaId: string;
	setBackgroundMediaId: (id: string) => void;
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
	const [backgroundMediaId, setBackgroundMediaId] = useState("");

	const [deliverable, setDeliverable] = useState<PosterComposeResponse | null>(
		null,
	);
	const [composeLoading, setComposeLoading] = useState(false);
	const [composeError, setComposeError] = useState("");

	const [savedAssetId, setSavedAssetId] = useState<string | null>(null);
	const [saveLoading, setSaveLoading] = useState(false);
	const [saveError, setSaveError] = useState("");

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
		setBackgroundMediaId("");
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
	}, []);

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
				refresh_ai: true,
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
			setReached((prev) => {
				const keep = prev.filter((s) => stepIndex(s) <= stepIndex("goal"));
				return keep.includes("angle") ? keep : [...keep, "angle"];
			});
			setStep("angle");
		},
		[],
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
	}, []);

	const selectDirection = useCallback(
		(index: number) => {
			const d = directions[index];
			if (!d) return;
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
		[directions],
	);

	const updateField = useCallback(
		(field: keyof GuidedCopyFields, value: string | string[]) => {
			setFields((prev) => ({ ...prev, [field]: value }));
			// Editing invalidates a prior approval (but NOT the editing draft id —
			// the whole point of the version draft is to receive these edits).
			setApprovedCopySet(null);
		},
		[],
	);

	const regenField = useCallback(
		async (field: string) => {
			if (!product || !goalArchetype) return;
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
		[product, goalArchetype, selectedAngle, fields],
	);

	const approve = useCallback(async () => {
		if (!product || !goalArchetype) return;
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
	]);

	// Editing approved copy uses the immutable new-version lifecycle. The created
	// draft id is KEPT so approve() patches it instead of creating a duplicate.
	const editApproved = useCallback(async () => {
		if (!approvedCopySet) return;
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
	}, [approvedCopySet]);

	// ── Creative Library reopen ────────────────────────────────────────────────

	const restoreFromReopen = useCallback(
		(recon: PosterDeliverableReconstruction, p: Product | null) => {
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
			setBackgroundMediaId(recon.deliverable.background_media_id ?? "");
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
	}, [historicalCopySet]);

	const selectRecipe = useCallback((recipe: string) => {
		setRecipeId(recipe);
		setDeliverable(null);
		setSavedAssetId(null);
		setReached((prev) => (prev.includes("scene") ? prev : [...prev, "scene"]));
		setStep("scene");
	}, []);

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
	}, [product, approvedCopySet, recipeId, backgroundMediaId]);

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
		selectRecipe,
		backgroundMediaId,
		setBackgroundMediaId,
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
