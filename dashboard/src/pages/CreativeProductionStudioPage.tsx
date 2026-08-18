import {
	Activity,
	AlertTriangle,
	CheckCircle2,
	Clock3,
	Database,
	GitBranch,
	Layers3,
	LockKeyhole,
	Pause,
	Play,
	RefreshCw,
	RotateCcw,
	ShieldCheck,
	Square,
	WandSparkles,
	XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
	approveProductionPlan,
	assignProductionWaves,
	type CapacityPreflight,
	type CohortAuthority,
	type CohortProduct,
	type CreativeTreatmentFormatPreference,
	compileProductionPlan,
	controlProductionPlan,
	createProductionPlan,
	decideItemQa,
	dryRunProductionPlan,
	type ExecutionLane,
	fetchCohortAuthority,
	fetchGovernedPoolAuthority,
	fetchProductionPlan,
	fetchTreatmentAvailability,
	type GenerationAttempt,
	type GovernedPoolAuthority,
	listExecutionLanes,
	listProductionPlans,
	materializeContentMatrix,
	P6_LIVE_CONFIRMATION,
	type PlanDetail,
	type ProductionPlan,
	type ProductionPlanCanonicalSnapshot,
	type ProductVideoAllocation,
	preflightProductionPlan,
	reconcileAttempt,
	retryAttempt,
	startProductionPlan,
	type TreatmentAvailability,
} from "../api/creativeProduction";
import { fetchVideoModels, type VideoModelInfo } from "../api/productionQueue";
import ProductAllocationPicker from "../components/production-studio/ProductAllocationPicker";
import {
	WorkflowStep,
} from "../components/workflow";
import ResultsSidebar from "../components/workspace/ResultsSidebar";
import CopyArchitectureV2LaneCard from "../components/copywriting/CopyArchitectureV2LaneCard";
import CopySupplyPanel, {
	type CopySupplyProduct,
} from "../components/production-studio/CopySupplyPanel";
import { collectProductionSessionResults } from "../utils/videoSessionResults";

const splitValues = (value: string) =>
	value
		.split(/[\n,]/)
		.map((item) => item.trim())
		.filter(Boolean);

function assertPlanDetailBound(planId: string, detail: PlanDetail): void {
	const itemIds = new Set(detail.items.map((item) => item.item_id));
	const planIdMismatch =
		detail.plan.plan_id !== planId ||
		detail.snapshot.plan_id !== planId ||
		detail.waves.some((row) => row.plan_id !== planId) ||
		detail.batches.some((row) => row.plan_id !== planId) ||
		detail.items.some((item) => item.plan_id !== planId) ||
		detail.audit_events.some((row) => row.plan_id !== planId) ||
		detail.attempts.some((attempt) => !itemIds.has(attempt.item_id)) ||
		detail.qa.some((row) => !itemIds.has(String(row.item_id ?? "")));
	if (planIdMismatch) {
		throw new Error(
			"Selected plan response is internally inconsistent. No plan data was rendered.",
		);
	}
}

const blockerMessage = (code: string) => {
	if (/PRODUCT_REFERENCE|PRODUCT_ASSET|PRODUCT_IMAGE/.test(code)) {
		return "No approved product image is available. Open Product Assets to add or approve one.";
	}
	if (/COPY/.test(code)) {
		return "Approved production copy is missing or has reached its safe reuse limit. Open Copy Registry to resolve it.";
	}
	if (/AVATAR|CHARACTER/.test(code)) {
		return "An approved product-linked creator is required. Open Avatar Registry to review the linkage.";
	}
	if (/SCENE/.test(code)) {
		return "An approved scene strategy or scene asset is required for this product before production can proceed.";
	}
	if (/CAPACITY/.test(code)) {
		return "This product does not have enough unique approved material for the requested quantity. Reduce quantity or add approved supply.";
	}
	if (/MODEL|DURATION/.test(code)) {
		return "The selected model and duration cannot be used together. Choose an available duration.";
	}
	return "This product needs more approved production material before it can proceed.";
};

const technicalCode = (blocker: Record<string, unknown>) =>
	String(blocker.code ?? "UNKNOWN_BLOCKER");

const statusTone = (status: string) => {
	if (/APPROVED|READY|COMPLETED|REGISTERED|HEALTHY/.test(status)) {
		return "border-emerald-500/40 bg-emerald-500/10 text-emerald-200";
	}
	if (/BLOCKED|FAILED|REJECTED|CANCELLED|UNAVAILABLE/.test(status)) {
		return "border-rose-500/40 bg-rose-500/10 text-rose-200";
	}
	if (/RUNNING|SUBMITTED|GENERATING|RETRIEVING/.test(status)) {
		return "border-sky-500/40 bg-sky-500/10 text-sky-200";
	}
	return "border-amber-500/40 bg-amber-500/10 text-amber-100";
};

function StatusBadge({ status, testId }: { status: string; testId?: string }) {
	return (
		<span
			data-testid={testId}
			className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold tracking-wide ${statusTone(status)}`}
		>
			{status}
		</span>
	);
}

function Metric({
	label,
	value,
	tone = "text-slate-100",
}: {
	label: string;
	value: string | number;
	tone?: string;
}) {
	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
				{label}
			</div>
			<div className={`mt-1 text-lg font-semibold ${tone}`}>{value}</div>
		</div>
	);
}

const WORKFLOW_STEPS = [
	{ id: 1, label: "Pick products", desc: "Choose & quantity" },
	{ id: 2, label: "Choose recipe", desc: "Mode & duration" },
	{ id: 3, label: "Check readiness", desc: "Capacity + supply" },
	{ id: 4, label: "Compile", desc: "0 credits" },
	{ id: 5, label: "Dry run", desc: "Review before live" },
	{ id: 6, label: "Generate", desc: "Explicit credit gate" },
];

const GUIDED_RECIPES = [
	{
		id: "single-8",
		seconds: 8,
		mode: "SINGLE",
		title: "Single 8s",
		detail: "1 engine block · one finished clip",
	},
	{
		id: "extend-16",
		seconds: 16,
		mode: "EXTEND",
		title: "Extend 16s",
		detail: "2 × 8s blocks · one joined clip",
	},
	{
		id: "extend-24",
		seconds: 24,
		mode: "EXTEND",
		title: "Extend 24s",
		detail: "3 × 8s blocks · one joined clip",
	},
] as const;

type StudioMode =
	| "NEW_DRAFT"
	| "ACTIVE_PLAN"
	| "UNSAVED_DRAFT_FROM_ACTIVE_PLAN"
	| "LOADING_PLAN"
	| "LEGACY_INCOMPLETE_PLAN";

const P6_COHORT_PAGE_SIZE = 50;

export default function CreativeProductionStudioPage() {
	const searchParams = new URLSearchParams(window.location.search);
	// V4 cockpit is the DEFAULT (matches the T2V lane convention); `?classic=1`
	// opts back into the legacy surface. Operators no longer need a magic `?v4=1`.
	const useV4 = searchParams.get("classic") !== "1";
	const [cohort, setCohort] = useState<CohortAuthority | null>(null);
	const [knownCohortProducts, setKnownCohortProducts] = useState<
		Record<string, CohortProduct>
	>({});
	const [cohortSearchInput, setCohortSearchInput] = useState("");
	const [cohortSearch, setCohortSearch] = useState("");
	const [cohortOffset, setCohortOffset] = useState(0);
	const [cohortRefreshToken, setCohortRefreshToken] = useState(0);
	const [cohortLoading, setCohortLoading] = useState(true);
	const [cohortError, setCohortError] = useState("");
	const cohortRequestSequence = useRef(0);
	const [plans, setPlans] = useState<ProductionPlan[]>([]);
	const [selectedPlanId, setSelectedPlanId] = useState("");
	const [studioMode, setStudioMode] = useState<StudioMode>("NEW_DRAFT");
	const [draftSourceSnapshot, setDraftSourceSnapshot] =
		useState<ProductionPlanCanonicalSnapshot | null>(null);
	const [detail, setDetail] = useState<PlanDetail | null>(null);
	const [lanes, setLanes] = useState<ExecutionLane[]>([]);
	const [liveExecutionCertified, setLiveExecutionCertified] = useState(false);
	const [poolAuthority, setPoolAuthority] =
		useState<GovernedPoolAuthority | null>(null);
	const [poolAuthorityLoading, setPoolAuthorityLoading] = useState(false);
	const [treatmentAvailability, setTreatmentAvailability] =
		useState<TreatmentAvailability | null>(null);
	const [treatmentAvailabilityLoading, setTreatmentAvailabilityLoading] =
		useState(false);
	const [treatmentAvailabilityError, setTreatmentAvailabilityError] =
		useState("");
	const [preflight, setPreflight] = useState<CapacityPreflight | null>(null);
	const [busy, setBusy] = useState("");
	const [error, setError] = useState("");
	const [lastEvidence, setLastEvidence] = useState("");
	const [livePhrase, setLivePhrase] = useState("");
	const [operatorId, setOperatorId] = useState("p6-production-operator");
	const [allocations, setAllocations] = useState<ProductVideoAllocation[]>([]);
	const [videoModels, setVideoModels] = useState<VideoModelInfo[]>([]);
	const [modelRegistryError, setModelRegistryError] = useState("");
	const [historySearch, setHistorySearch] = useState("");
	const [historyStatus, setHistoryStatus] = useState("ACTIVE");
	const [advancedWorkspaceOpen, setAdvancedWorkspaceOpen] = useState(false);
	const [v2CopyReadyByProduct, setV2CopyReadyByProduct] = useState<
		Record<string, boolean>
	>({});
	const planRequestSequence = useRef(0);
	const treatmentAvailabilitySequence = useRef(0);
	const [activeView, setActiveView] = useState<"matrix" | "attempts" | "qa">(
		"matrix",
	);
	const [form, setForm] = useState({
		name: "New production plan",
		campaignKey: "",
		imageCount: 0,
		posterCount: 0,
		windowHours: 12,
		logicalMode: "T2V" as "T2V" | "HYBRID" | "F2V" | "I2V",
		modelKey: "",
		durationSeconds: 8,
		creativeFormat: "AUTO" as CreativeTreatmentFormatPreference,
		treatmentIds: "",
		aspect: "9:16" as "9:16" | "16:9",
		avatarCodes: "",
		productReferenceAssetIds: "",
		finishedFrameAssetIds: "",
		characterAssetIds: "",
		sceneAssetIds: "",
		styleAssetIds: "",
		layoutIds: "",
		controlledReuseReason: "",
		controlledReuseMaxPerDna: 1,
	});
	const approvedAvatarOptions = useMemo(() => {
		const seen = new Set<string>();
		return (poolAuthority?.avatar_profiles ?? []).filter((profile) => {
			const code = String(profile.avatar_code || "").trim();
			if (!code || seen.has(code)) return false;
			seen.add(code);
			return true;
		});
	}, [poolAuthority]);
	const sessionResults = useMemo(
		() => collectProductionSessionResults(detail),
		[detail],
	);

	const loadCohortPage = useCallback(async (query: string, offset: number) => {
		const requestSequence = ++cohortRequestSequence.current;
		setCohortLoading(true);
		setCohortError("");
		try {
			const result = await fetchCohortAuthority({
				q: query.trim() || undefined,
				limit: P6_COHORT_PAGE_SIZE,
				offset,
			});
			if (requestSequence !== cohortRequestSequence.current) return;
			setKnownCohortProducts((current) => {
				const next = { ...current };
				let changed = false;
				for (const product of result.products) {
					if (next[product.product_id] !== product) {
						next[product.product_id] = product;
						changed = true;
					}
				}
				return changed ? next : current;
			});
			setCohort(result);
		} catch (reason) {
			if (requestSequence !== cohortRequestSequence.current) return;
			setCohortError(reason instanceof Error ? reason.message : String(reason));
		} finally {
			if (requestSequence === cohortRequestSequence.current) {
				setCohortLoading(false);
			}
		}
	}, []);

	useEffect(() => {
		const timer = window.setTimeout(() => {
			setCohortSearch(cohortSearchInput);
			setCohortOffset(0);
		}, 250);
		return () => window.clearTimeout(timer);
	}, [cohortSearchInput]);

	useEffect(() => {
		void loadCohortPage(cohortSearch, cohortOffset);
	}, [cohortOffset, cohortRefreshToken, cohortSearch, loadCohortPage]);

	const handleCohortSearchChange = useCallback((query: string) => {
		setCohortSearchInput(query);
	}, []);

	const handleCohortPageChange = useCallback((offset: number) => {
		setCohortOffset(Math.max(0, offset));
	}, []);

	const loadPlan = useCallback(async (planId: string) => {
		const requestSequence = ++planRequestSequence.current;
		setSelectedPlanId(planId);
		setStudioMode("LOADING_PLAN");
		setDetail(null);
		setPreflight(null);
		setLivePhrase("");
		setLastEvidence("");
		setActiveView("matrix");
		setAdvancedWorkspaceOpen(false);
		try {
			const fetchedDetail = await fetchProductionPlan(planId);
			if (requestSequence !== planRequestSequence.current) return null;
			assertPlanDetailBound(planId, fetchedDetail);
			setDetail(fetchedDetail);
			setStudioMode(
				fetchedDetail.snapshot.completeness === "COMPLETE"
					? "ACTIVE_PLAN"
					: "LEGACY_INCOMPLETE_PLAN",
			);
			return fetchedDetail;
		} catch (reason) {
			if (requestSequence !== planRequestSequence.current) return null;
			setSelectedPlanId("");
			setDetail(null);
			setStudioMode("NEW_DRAFT");
			throw reason;
		}
	}, []);

	const refresh = useCallback(
		async (preferredPlanId?: string) => {
			setCohortRefreshToken((current) => current + 1);
			const [planList, laneList] = await Promise.all([
				listProductionPlans(),
				listExecutionLanes(),
			]);
			setPlans(planList.plans);
			setLanes(laneList.lanes);
			setLiveExecutionCertified(laneList.live_execution_certified);
			if (preferredPlanId) {
				await loadPlan(preferredPlanId);
			}
		},
		[loadPlan],
	);

	useEffect(() => {
		void refresh().catch((reason) => setError(String(reason)));
	}, [refresh]);

	useEffect(() => {
		if (!selectedPlanId || detail?.plan.status !== "RUNNING") return;
		let active = true;
		let inFlight = false;
		const requestSequence = planRequestSequence.current;
		const poll = async () => {
			if (inFlight) return;
			inFlight = true;
			try {
				const fetchedDetail = await fetchProductionPlan(selectedPlanId);
				if (
					!active ||
					requestSequence !== planRequestSequence.current
				)
					return;
				assertPlanDetailBound(selectedPlanId, fetchedDetail);
				setDetail(fetchedDetail);
				setPlans((current) =>
					current.map((plan) =>
						plan.plan_id === selectedPlanId ? fetchedDetail.plan : plan,
					),
				);
			} catch (reason) {
				if (
					active &&
					requestSequence === planRequestSequence.current
				) {
					setError(
						reason instanceof Error ? reason.message : String(reason),
					);
				}
			} finally {
				inFlight = false;
			}
		};
		void poll();
		const timer = window.setInterval(() => void poll(), 5000);
		return () => {
			active = false;
			window.clearInterval(timer);
		};
	}, [detail?.plan.status, selectedPlanId]);

	useEffect(() => {
		void fetchVideoModels()
			.then((response) => {
				const models = response.models ?? [];
				setVideoModels(models);
				const preferred =
					models.find(
						(model) =>
							model.key === response.default ||
							model.ui_label === response.default,
					) ?? models[0];
				if (preferred) {
					setForm((current) => ({
						...current,
						modelKey: current.modelKey || preferred.key,
						durationSeconds:
							current.modelKey && current.durationSeconds
								? current.durationSeconds
								: (preferred.default_duration_s ?? 8),
					}));
				}
				setModelRegistryError("");
			})
			.catch((reason) => {
				setVideoModels([]);
				setModelRegistryError(
					reason instanceof Error
						? reason.message
						: "Video model list unavailable.",
				);
			});
	}, []);

	const poolAuthorityProductKey = useMemo(
		() =>
			allocations
				.map((allocation) => allocation.product_id)
				.sort()
				.join("\u001f"),
		[allocations],
	);

	useEffect(() => {
		const productIds = poolAuthorityProductKey.split("\u001f").filter(Boolean);
		if (!productIds.length) {
			setPoolAuthority(null);
			setPoolAuthorityLoading(false);
			return;
		}
		let active = true;
		setPoolAuthority(null);
		setPoolAuthorityLoading(true);
		void fetchGovernedPoolAuthority(productIds, form.logicalMode)
			.then((authority) => {
				if (!active) return;
				setPoolAuthority(authority);
				setPoolAuthorityLoading(false);
			})
			.catch((reason) => {
				if (!active) return;
				setPoolAuthority(null);
				setPoolAuthorityLoading(false);
				setError(String(reason));
			});
		return () => {
			active = false;
		};
	}, [poolAuthorityProductKey, form.logicalMode]);

	useEffect(() => {
		if (!poolAuthority) return;
		const availableCodes = approvedAvatarOptions.map((profile) =>
			String(profile.avatar_code || "").trim(),
		);
		const allowed = new Set(availableCodes);
		setForm((current) => {
			const retained = splitValues(current.avatarCodes).filter((code) =>
				allowed.has(code),
			);
			const nextCodes = retained.length ? retained : availableCodes;
			const nextValue = nextCodes.join(",");
			if (nextValue === current.avatarCodes) return current;
			return { ...current, avatarCodes: nextValue };
		});
	}, [approvedAvatarOptions, poolAuthority]);

	useEffect(() => {
		const requestSequence = ++treatmentAvailabilitySequence.current;
		if (!allocations.length || !form.modelKey || !form.durationSeconds) {
			setTreatmentAvailability(null);
			setTreatmentAvailabilityLoading(false);
			setTreatmentAvailabilityError("");
			return;
		}
		setTreatmentAvailability(null);
		setTreatmentAvailabilityLoading(true);
		setTreatmentAvailabilityError("");
		void fetchTreatmentAvailability({
			product_video_allocations: allocations,
			logical_mode: form.logicalMode,
			model_key: form.modelKey,
			duration_seconds: form.durationSeconds,
			creative_format: form.creativeFormat,
			treatment_ids: splitValues(form.treatmentIds),
		})
			.then((availability) => {
				if (requestSequence !== treatmentAvailabilitySequence.current) return;
				setTreatmentAvailability(availability);
				setTreatmentAvailabilityLoading(false);
			})
			.catch((reason) => {
				if (requestSequence !== treatmentAvailabilitySequence.current) return;
				setTreatmentAvailability(null);
				setTreatmentAvailabilityLoading(false);
				setTreatmentAvailabilityError(
					reason instanceof Error ? reason.message : String(reason),
				);
			});
	}, [
		allocations,
		form.creativeFormat,
		form.durationSeconds,
		form.logicalMode,
		form.modelKey,
		form.treatmentIds,
	]);

	const selectedModel = videoModels.find(
		(model) =>
			model.key === form.modelKey ||
			model.ui_label === form.modelKey ||
			model.key.toLowerCase().replace(/[^a-z0-9]/g, "") ===
				form.modelKey.toLowerCase().replace(/[^a-z0-9]/g, "") ||
			model.ui_label.toLowerCase().replace(/[^a-z0-9]/g, "") ===
				form.modelKey.toLowerCase().replace(/[^a-z0-9]/g, ""),
	);
	const durationOptions = useMemo(() => {
		if (!selectedModel) return [];
		const singles = (selectedModel.allowed_durations_s ?? []).map(
			(seconds) => ({
				seconds,
				generationMode: "SINGLE" as const,
				blockSeconds: seconds,
				segments: 1,
			}),
		);
		const blockSeconds = selectedModel.extend_block_duration_s ?? 0;
		const extensions = (selectedModel.extend_totals_s ?? []).map((seconds) => ({
			seconds,
			generationMode: "EXTEND" as const,
			blockSeconds,
			segments: seconds / blockSeconds,
		}));
		return [...singles, ...extensions];
	}, [selectedModel]);
	const selectedDurationOption = durationOptions.find(
		(option) => option.seconds === form.durationSeconds,
	);
	const selectedDuration = form.durationSeconds;
	const totalVideoCount = allocations.reduce(
		(total, allocation) => total + allocation.video_count,
		0,
	);
	const invalidAllocation = allocations.some(
		(allocation) =>
			!Number.isInteger(allocation.video_count) ||
			allocation.video_count < 1 ||
			allocation.video_count > 200,
	);
	const treatmentShortage = treatmentAvailability?.product_results.find(
		(product) => !product.ready,
	);
	const v2CopyReady =
		allocations.length > 0 &&
		allocations.every(
			(allocation) => v2CopyReadyByProduct[allocation.product_id] === true,
		);
	const treatmentDisabledReason = treatmentAvailabilityLoading
		? "Checking approved Creative Treatment capacity..."
		: treatmentAvailabilityError
			? "Creative Treatment capacity is unavailable."
			: treatmentShortage
				? `Creative Treatment shortage for ${
						cohort?.products.find(
							(product) => product.product_id === treatmentShortage.product_id,
						)?.product_name ?? treatmentShortage.product_id
					}: ${treatmentShortage.selected_count}/${treatmentShortage.requested} eligible.`
				: treatmentAvailability && !treatmentAvailability.ready
					? "The selected Creative Treatment configuration is not ready."
					: "";
	const supportsTreatmentConfiguration = (
		modelKey: string,
		durationSeconds: number,
		format: CreativeTreatmentFormatPreference,
	) => {
		const configurations = treatmentAvailability?.supported_configurations ?? [];
		if (!configurations.length) return true;
		return configurations.some((configuration) => {
			const modelKeys = Array.isArray(configuration.model_keys)
				? configuration.model_keys.map(String)
				: [];
			return (
				String(configuration.logical_mode ?? "") === form.logicalMode &&
				modelKeys.includes(modelKey) &&
				Number(configuration.duration_seconds) === durationSeconds &&
				(format === "AUTO" || String(configuration.format ?? "") === format)
			);
		});
	};
	const treatmentCreateBlocked =
		treatmentAvailabilityLoading ||
		Boolean(treatmentAvailabilityError) ||
		!treatmentAvailability ||
		!treatmentAvailability.ready;
	const blockersByProduct = useMemo(() => {
		const result: Record<string, string> = {};
		for (const blocker of poolAuthority?.blockers ?? []) {
			const productId = String(blocker.product_id ?? "");
			if (productId && !result[productId]) {
				result[productId] = blockerMessage(technicalCode(blocker));
			}
		}
		for (const product of treatmentAvailability?.product_results ?? []) {
			if (!product.ready) {
				result[product.product_id] =
					`Creative Treatment shortage: ${product.selected_count}/${product.requested} ` +
					`eligible (${product.shortage} more approval${product.shortage === 1 ? "" : "s"} required).`;
			}
		}
		return result;
	}, [poolAuthority, treatmentAvailability]);
	const productNameById = useMemo(
		() =>
			new Map(
				(cohort?.products ?? []).map((product) => [
					product.product_id,
					product.product_name,
				]),
			),
		[cohort],
	);

	// Copy Supply focuses on whatever products are in context: the draft
	// allocations while editing, or the selected plan's products when viewing one.
	const copySupplyProducts = useMemo<CopySupplyProduct[]>(() => {
		if (allocations.length) {
			return allocations.map((allocation) => ({
				id: allocation.product_id,
				name: productNameById.get(allocation.product_id) ?? allocation.product_id,
				target: allocation.video_count,
			}));
		}
		return (detail?.snapshot?.product_allocations ?? []).map((allocation) => ({
			id: allocation.product_id,
			name:
				allocation.product_name ??
				productNameById.get(allocation.product_id) ??
				allocation.product_id,
			target: allocation.video_count,
		}));
	}, [allocations, detail, productNameById]);

	const chooseModel = (modelKey: string) => {
		const model = videoModels.find((candidate) => candidate.key === modelKey);
		const choices = [
			...(model?.allowed_durations_s ?? []),
			...(model?.extend_totals_s ?? []),
		];
		setForm((current) => ({
			...current,
			modelKey,
			durationSeconds: model?.default_duration_s ?? choices[0] ?? 8,
		}));
	};

	const execute = async (name: string, action: () => Promise<unknown>) => {
		setBusy(name);
		setError("");
		try {
			const evidence = await action();
			await refresh(selectedPlanId);
			setLastEvidence(JSON.stringify(evidence, null, 2));
		} catch (reason) {
			setError(reason instanceof Error ? reason.message : String(reason));
		} finally {
			setBusy("");
		}
	};

	const create = async () => {
		if (!v2CopyReady) {
			throw new Error(
				"Copy Register V2 binding must be READY before a P6 production plan can be created.",
			);
		}
		const created = await createProductionPlan({
			request_id: crypto.randomUUID(),
			operator_id: operatorId,
			name: form.name,
			campaign_key: form.campaignKey,
			product_ids: allocations.map((allocation) => allocation.product_id),
			product_video_allocations: allocations,
			target_video_count: totalVideoCount,
			target_image_count: form.imageCount,
			target_poster_count: form.posterCount,
			operating_window_hours: form.windowHours,
			allocation_strategy: "ROUND_ROBIN",
			variation_strategy: "SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS",
			logical_mode: form.logicalMode,
			model_keys: [selectedModel?.key || form.modelKey],
			duration_seconds: [form.durationSeconds],
			creative_format: form.creativeFormat,
			pools: {
				treatment_ids: splitValues(form.treatmentIds),
				avatar_codes: splitValues(form.avatarCodes),
				// Product visuals are never a P6 pool dimension. Each item resolves
				// the product's saved Product Registration Official Product Visual.
				product_reference_asset_ids: [],
				finished_frame_asset_ids: splitValues(form.finishedFrameAssetIds),
				character_asset_ids: splitValues(form.characterAssetIds),
				scene_asset_ids: splitValues(form.sceneAssetIds),
				style_asset_ids: splitValues(form.styleAssetIds),
				layout_ids: splitValues(form.layoutIds),
			},
			controlled_reuse_reason: form.controlledReuseReason || null,
			controlled_reuse_max_per_dna: form.controlledReuseMaxPerDna,
			execution_policy: {
				aspect: form.aspect,
				credit_policy: "EXPLICIT_CONFIRMATION_REQUIRED",
				near_duplicate_threshold: 0.8,
				copy_reuse_cap: 15,
				capacity_objective_not_sla: true,
			},
		});
		setSelectedPlanId(created.plan_id);
		await refresh(created.plan_id);
		return created;
	};

	const duplicateActivePlan = useCallback(() => {
		if (!detail) return;
		const snapshot = detail.snapshot;
		const configuration = snapshot.video_configurations[0];
		const pool = snapshot.pool_snapshot;
		const poolValues = (key: string) =>
			Array.isArray(pool[key]) ? (pool[key] as string[]).join("\n") : "";
		planRequestSequence.current += 1;
		setDraftSourceSnapshot(snapshot);
		setAllocations(
			snapshot.product_allocations.map(({ product_id, video_count }) => ({
				product_id,
				video_count,
			})),
		);
		setForm((current) => ({
			...current,
			name: `${snapshot.plan_name} copy`,
			campaignKey: snapshot.purpose ?? "",
			imageCount: snapshot.target_image_count,
			posterCount: snapshot.target_poster_count,
			windowHours: snapshot.operating_window_hours,
			logicalMode: snapshot.logical_mode,
			modelKey: configuration?.model_key ?? current.modelKey,
			durationSeconds:
				configuration?.requested_total_duration_seconds ??
				current.durationSeconds,
			aspect: snapshot.aspect_ratio,
			creativeFormat: String(
				pool.creative_format ?? "AUTO",
			) as CreativeTreatmentFormatPreference,
			treatmentIds: poolValues("treatment_ids"),
			avatarCodes: poolValues("avatar_codes"),
			productReferenceAssetIds: poolValues("product_reference_asset_ids"),
			finishedFrameAssetIds: poolValues("finished_frame_asset_ids"),
			characterAssetIds: poolValues("character_asset_ids"),
			sceneAssetIds: poolValues("scene_asset_ids"),
			styleAssetIds: poolValues("style_asset_ids"),
			layoutIds: poolValues("layout_ids"),
			controlledReuseReason: String(pool.controlled_reuse_reason ?? ""),
			controlledReuseMaxPerDna: Number(pool.controlled_reuse_max_per_dna ?? 1),
		}));
		setSelectedPlanId("");
		setDetail(null);
		setPreflight(null);
		setLivePhrase("");
		setLastEvidence("");
		setActiveView("matrix");
		setAdvancedWorkspaceOpen(false);
		setStudioMode("UNSAVED_DRAFT_FROM_ACTIVE_PLAN");
	}, [detail]);

	const switchToNewDraft = useCallback(() => {
		planRequestSequence.current += 1;
		setSelectedPlanId("");
		setDetail(null);
		setPreflight(null);
		setLivePhrase("");
		setLastEvidence("");
		setActiveView("matrix");
		setAdvancedWorkspaceOpen(false);
		setDraftSourceSnapshot(null);
		setAllocations([]);
		setForm((current) => ({
			...current,
			name: "New production plan",
			campaignKey: "",
			imageCount: 0,
			posterCount: 0,
			windowHours: 12,
			logicalMode: "T2V",
			aspect: "9:16",
			creativeFormat: "AUTO",
			treatmentIds: "",
			avatarCodes: "",
			productReferenceAssetIds: "",
			finishedFrameAssetIds: "",
			characterAssetIds: "",
			sceneAssetIds: "",
			styleAssetIds: "",
			layoutIds: "",
			controlledReuseReason: "",
			controlledReuseMaxPerDna: 1,
		}));
		setStudioMode("NEW_DRAFT");
	}, []);

	const selectedPlan = detail?.plan;
	const selectedSnapshot = detail?.snapshot;
	const selectedTreatmentIds = Array.isArray(
		selectedSnapshot?.pool_snapshot.treatment_ids,
	)
		? (selectedSnapshot.pool_snapshot.treatment_ids as string[])
		: [];
	const verifiedVideoLane = lanes.find(
		(lane) =>
			lane.enabled &&
			lane.health_status === "HEALTHY" &&
			lane.runtime_proof_status === "VERIFIED" &&
			lane.eligible_media_types.includes("VIDEO"),
	);
	const hasDryRunProof = Boolean(
		detail?.attempts.some(
			(attempt) =>
				!attempt.credit_spend_intended &&
				attempt.attempt_state === "NOT_SUBMITTED",
		),
	);
	const actionDisabled =
		studioMode !== "ACTIVE_PLAN" ||
		!selectedPlan ||
		selectedSnapshot?.completeness !== "COMPLETE" ||
		Boolean(busy);
	const liveEnabled =
		liveExecutionCertified &&
		studioMode === "ACTIVE_PLAN" &&
		selectedPlan?.status === "SCHEDULED" &&
		selectedSnapshot?.completeness === "COMPLETE" &&
		selectedSnapshot.plan_id === selectedPlan.plan_id &&
		Boolean(verifiedVideoLane) &&
		hasDryRunProof &&
		livePhrase === P6_LIVE_CONFIRMATION &&
		!busy;

	const liveDisabledReason = useMemo(() => {
		if (studioMode === "UNSAVED_DRAFT_FROM_ACTIVE_PLAN") {
			return "Create the new plan before starting production.";
		}
		if (!selectedPlan || !selectedSnapshot) {
			return "Select an existing plan before starting production.";
		}
		if (selectedSnapshot.completeness !== "COMPLETE") {
			return `This legacy plan is missing: ${selectedSnapshot.missing_fields.join(", ")}.`;
		}
		if (studioMode !== "ACTIVE_PLAN") {
			return "Select an existing plan before starting production.";
		}
		if (!liveExecutionCertified) {
			return "Runtime live-execution certification is absent.";
		}
		if (!verifiedVideoLane) {
			return "No verified healthy video lane is available.";
		}
		if (selectedPlan?.status !== "SCHEDULED") {
			return `Plan must be in SCHEDULED status before live execution (current status: ${selectedPlan?.status || "NONE"}).`;
		}
		if (!hasDryRunProof) {
			return "A matching zero-credit dry run is required.";
		}
		if (livePhrase !== P6_LIVE_CONFIRMATION) {
			return `Confirmation phrase does not match. Type exact phrase: ${P6_LIVE_CONFIRMATION}`;
		}
		if (busy) {
			return "Action in progress...";
		}
		return "All safety gates must pass before live dispatch.";
	}, [
		studioMode,
		selectedPlan,
		selectedSnapshot,
		liveExecutionCertified,
		verifiedVideoLane,
		hasDryRunProof,
		livePhrase,
		busy,
	]);

	const preflightSnapshot =
		(preflight ??
			(selectedPlan?.capacity_snapshot as unknown as CapacityPreflight)) ||
		null;
	const blockers = useMemo(
		() =>
			preflight?.blockers ??
			((selectedPlan?.blockers || []) as Array<Record<string, unknown>>),
		[preflight, selectedPlan],
	);

	const activeStep = useMemo(() => {
		if (!detail?.plan) return 1;
		const status = detail.plan.status;
		if (status === "DRAFT" || status === "PREFLIGHT_BLOCKED") return 3;
		if (status === "PREFLIGHT_READY") return 4;
		if (status === "PENDING_APPROVAL" || status === "APPROVED") return 5;
		if (status === "SCHEDULED") return 6;
		return 3;
	}, [detail]);

	const primaryActionConfig = (() => {
		if (studioMode === "LEGACY_INCOMPLETE_PLAN" && selectedSnapshot) {
			return {
				step: activeStep,
				title: "Legacy plan — incomplete snapshot",
				subtitle: `Missing plan data: ${selectedSnapshot.missing_fields.join(", ")}.`,
				buttonLabel: "Production unavailable",
				buttonTestId: "p6-primary-action",
				actionName: "legacy-incomplete",
				executeAction: async () => {},
				disabled: true,
				disabledReason:
					"This plan remains inspectable but cannot start production.",
				isCreditSpend: false,
			};
		}

		if (!detail?.plan) {
			const isUnsaved = studioMode === "UNSAVED_DRAFT_FROM_ACTIVE_PLAN";
			return {
				step: 1,
				title: isUnsaved ? "Unsaved new plan" : "New production plan",
				subtitle:
					"Choose products and exact quantities, then save this production plan.",
				buttonLabel:
					busy === "create"
						? "Creating plan…"
						: isUnsaved
							? "Create new production plan"
							: "Create production plan",
				buttonTestId: "p6-primary-action",
				actionName: "create",
				executeAction: () => create(),
				disabled:
					Boolean(busy) ||
					!cohort?.matches_frozen_authority ||
					!allocations.length ||
					invalidAllocation ||
					poolAuthorityLoading ||
					!poolAuthority ||
					treatmentCreateBlocked ||
					!form.modelKey ||
					!selectedDuration ||
					Boolean(modelRegistryError) ||
					!operatorId.trim() ||
					Boolean(poolAuthority?.blockers.length) ||
					!form.name,
				disabledReason: !cohort?.matches_frozen_authority
					? "Product list check required"
					: !allocations.length
						? "Select at least one product"
						: invalidAllocation
							? "Product quantities must be between 1 and 200"
							: poolAuthorityLoading
								? "Loading approved supply..."
								: poolAuthority?.blockers.length
									? "Approved supply blockers must be resolved"
									: treatmentDisabledReason
										? treatmentDisabledReason
										: !form.name
											? "Enter a plan name"
											: "Fill in all required fields",
				isCreditSpend: false,
			};
		}

		const planId = detail.plan.plan_id;
		const status = detail.plan.status;

		if (status === "DRAFT" || status === "PREFLIGHT_BLOCKED") {
			return {
				step: 3,
				title: "Run Preflight Inspection",
				subtitle:
					"Verify unique supply capacity against requested video quantity.",
				buttonLabel:
					busy === "Preflight"
						? "Inspecting capacity…"
						: "Run preflight inspection",
				buttonTestId: "p6-primary-action",
				actionName: "Preflight",
				executeAction: () =>
					preflightProductionPlan(planId, operatorId).then((result) => {
						setPreflight(result);
						return result;
					}),
				disabled: actionDisabled,
				disabledReason: busy
					? "Action in progress..."
					: "Select or resume plan",
				isCreditSpend: false,
			};
		}

		if (status === "PREFLIGHT_READY") {
			return {
				step: 4,
				title: "Build Content Matrix & Compile Prompts",
				subtitle:
					"Generate creative DNA items and compile execution prompts (0 credits).",
				buttonLabel:
					busy === "Build matrix"
						? "Materializing matrix…"
						: busy === "Compile · 0 credit"
							? "Compiling prompts…"
							: "Build matrix & compile (0 credits)",
				buttonTestId: "p6-primary-action",
				actionName: "Build matrix",
				executeAction: async () => {
					await materializeContentMatrix(planId, operatorId);
					return compileProductionPlan(planId, operatorId);
				},
				disabled: actionDisabled,
				disabledReason: busy
					? "Action in progress..."
					: "Select or resume plan",
				isCreditSpend: false,
			};
		}

		if (status === "PENDING_APPROVAL") {
			return {
				step: 5,
				title: "Approve Production Items & Assign Waves",
				subtitle:
					"Approve compiled creative items and assign parallel execution waves.",
				buttonLabel:
					busy === "Bulk approve"
						? "Approving items…"
						: "Approve items & assign waves",
				buttonTestId: "p6-primary-action",
				actionName: "Bulk approve",
				executeAction: async () => {
					await approveProductionPlan(planId, operatorId);
					return assignProductionWaves(planId, operatorId, 2, 25);
				},
				disabled: actionDisabled,
				disabledReason: busy
					? "Action in progress..."
					: "Select or resume plan",
				isCreditSpend: false,
			};
		}

		if (status === "APPROVED") {
			return {
				step: 5,
				title: "Run Dry-Run Verification · 0 Credits",
				subtitle:
					"Perform full dry-run simulation to verify provider readiness without spending credits.",
				buttonLabel:
					busy === "Dry run · 0 credit"
						? "Executing dry run…"
						: "Run dry-run verification (0 credits)",
				buttonTestId: "p6-primary-action",
				actionName: "Dry run · 0 credit",
				executeAction: () =>
					dryRunProductionPlan(
						planId,
						operatorId,
						detail.snapshot.aspect_ratio,
					),
				disabled: actionDisabled,
				disabledReason: busy
					? "Action in progress..."
					: "Select or resume plan",
				isCreditSpend: false,
			};
		}

		if (status === "SCHEDULED") {
			const videoCount = detail.snapshot.target_video_count;
			return {
				step: 6,
				title: `Start production for ${detail.snapshot.plan_name}`,
				subtitle: `This sends the next queued item now and authorizes the scheduler to continue this ${videoCount}-video plan. This action spends media credits.`,
				buttonLabel:
					busy === "live" ? "Starting production…" : "Start production",
				buttonTestId: "p6-primary-action",
				actionName: "live",
				executeAction: () =>
					startProductionPlan(
						planId,
						operatorId,
						livePhrase,
						detail.snapshot.aspect_ratio,
					),
				disabled: !liveEnabled,
				disabledReason: !liveExecutionCertified
					? "Runtime live-execution certification is absent"
					: livePhrase !== P6_LIVE_CONFIRMATION
						? `Type exact confirmation phrase "${P6_LIVE_CONFIRMATION}" below to authorize`
						: busy
							? "Dispatching..."
							: "All gates must pass",
				isCreditSpend: true,
			};
		}

		return {
			step: 3,
			title: `Plan ${String(status)}`,
			subtitle: `Current plan status is ${String(status)}`,
			buttonLabel: String(status),
			buttonTestId: "p6-primary-action",
			actionName: String(status),
			executeAction: async () => {},
			disabled: true,
			disabledReason: `Plan is in state (${String(status)})`,
			isCreditSpend: false,
		};
	})();

	const primaryPlans = useMemo(
		() =>
			plans.filter((plan) =>
				[
					"DRAFT",
					"PREFLIGHT_BLOCKED",
					"PREFLIGHT_READY",
					"PENDING_APPROVAL",
					"APPROVED",
					"SCHEDULED",
					"RUNNING",
					"PAUSED",
				].includes(plan.status),
			),
		[plans],
	);
	const filteredHistory = useMemo(() => {
		const query = historySearch.trim().toLocaleLowerCase();
		return plans.filter((plan) => {
			const statusMatches =
				historyStatus === "ALL" ||
				(historyStatus === "ACTIVE"
					? primaryPlans.some((candidate) => candidate.plan_id === plan.plan_id)
					: historyStatus === "COMPLETED"
						? ["COMPLETED", "COMPLETED_WITH_FAILURES"].includes(plan.status)
						: historyStatus === "CANCELLED_FAILED"
							? ["CANCELLED", "FAILED"].includes(plan.status)
							: plan.status === historyStatus);
			const allocationNames =
				plan.snapshot_summary?.product_allocations
					.map((allocation) => allocation.product_name)
					.join(" ") ?? "";
			return (
				statusMatches &&
				(!query ||
					`${plan.name} ${plan.plan_id} ${allocationNames}`
						.toLocaleLowerCase()
						.includes(query))
			);
		});
	}, [plans, primaryPlans, historySearch, historyStatus]);
	const p6V4ProductCount =
		selectedSnapshot?.product_allocations.length ?? allocations.length;
	const p6V4TargetCount = selectedSnapshot?.target_video_count ?? totalVideoCount;
	const p6V4PlanStatus = selectedPlan?.status ?? (studioMode === "NEW_DRAFT" ? "DRAFT" : studioMode);
	const guidedRecipe = selectedSnapshot?.video_configurations?.[0]
		? `${selectedSnapshot.video_configurations[0].requested_total_duration_seconds}s ${selectedSnapshot.video_configurations[0].generation_mode}`
		: selectedDurationOption
			? `${selectedDurationOption.seconds}s ${selectedDurationOption.generationMode}`
			: "Choose a recipe";
	const guidedNextAction = primaryActionConfig.isCreditSpend
		? null
		: primaryActionConfig;
	const guidedAuthorityReady = cohort?.matches_frozen_authority === true;
	const p6V4Surface = (surface: ReactNode) =>
		useV4 ? (
			<WorkflowStep
				index={1}
				title="P6 batch production workspace"
				status={selectedPlan ? "done" : allocations.length ? "active" : "upcoming"}
				summary={`${p6V4TargetCount} video${p6V4TargetCount === 1 ? "" : "s"} · ${p6V4PlanStatus}`}
				helper="Batch, matrix, waves, QA, and live confirmation remain the P6 IA; this frame only adds the V4 visual language."
				collapsible={false}
			>
				<div data-testid="p6-guided-flow" className="space-y-4">
										<div className="rounded-2xl border border-cyan-500/30 bg-gradient-to-br from-cyan-950/30 via-slate-950 to-violet-950/20 p-4">
						<div className="flex flex-wrap items-start justify-between gap-4">
							<div className="max-w-2xl">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-cyan-300">Guided production flow</div>
								<h2 className="mt-1 text-xl font-semibold text-slate-100">Build a video pack, step by step</h2>
								<p className="mt-1 text-xs leading-5 text-slate-400">Open each step in order — nothing runs until you reach Compile &amp; generate. Compile and dry-run are free; live dispatch stays a separate, explicit credit action.</p>
							</div>
							<div className="grid min-w-[230px] grid-cols-3 gap-2">
								<Metric label="Products" value={p6V4ProductCount} />
								<Metric label="Videos" value={p6V4TargetCount} />
								<Metric label="Before live" value="0 credits" tone="text-emerald-200" />
							</div>
						</div>
						<div data-testid="p6-nine-pack-guidance" className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-violet-500/30 bg-violet-950/20 p-3 text-xs">
							<div>
								<div className="font-semibold text-violet-100">9-video validation pack</div>
								<div className="mt-1 text-[10px] text-violet-200/70">Prepare three separate plans: 8s × 3, 16s × 3, and 24s × 3. No media credits are used until live confirmation.</div>
							</div>
							<StatusBadge status="ONE RECIPE PER PLAN" />
						</div>
					</div>

										<WorkflowStep
						index={1}
						title="Products"
						status={allocations.length ? "done" : "active"}
						summary={`${p6V4ProductCount} product${p6V4ProductCount === 1 ? "" : "s"} · ${p6V4TargetCount} video${p6V4TargetCount === 1 ? "" : "s"}`}
						helper="Choose which products this plan produces and how many videos each."
					>
						<div className="space-y-3">
							<p className="text-xs text-slate-400">Products and quantities are set in the production workspace. Open it to add products and set counts, then come back to pick a recipe.</p>
							<button type="button" onClick={() => setAdvancedWorkspaceOpen(true)} data-testid="p6-open-advanced-workspace" className="rounded-lg border border-cyan-500/50 bg-cyan-500/10 px-3 py-2 text-[11px] font-semibold text-cyan-100 hover:border-cyan-400">Choose / manage products</button>
						</div>
					</WorkflowStep>

										<WorkflowStep
						index={2}
						title="Recipe & length"
						status={form.durationSeconds && allocations.length ? "done" : allocations.length ? "active" : "upcoming"}
						summary={guidedRecipe}
						helper="Pick one recipe per plan: a single clip, or an extended (chained) clip."
					>
						<div className="grid gap-2 md:grid-cols-3">
							{GUIDED_RECIPES.map((recipe) => {
							const available = durationOptions.some(
							(option) => option.seconds === recipe.seconds,
							);
							const selected = form.durationSeconds === recipe.seconds;
							return (
							<button
							key={recipe.id}
							type="button"
							disabled={!available || Boolean(busy)}
							onClick={() =>
							setForm((current) => ({
							...current,
							durationSeconds: recipe.seconds,
							}))
							}
							data-testid={`p6-recipe-${recipe.id}`}
							className={`rounded-xl border p-3 text-left transition-colors ${
							selected
							? "border-violet-400/70 bg-violet-500/15 text-violet-100"
							: "border-slate-700 bg-slate-950/60 text-slate-300 hover:border-cyan-400/50"
							}`}
							>
							<div className="flex items-center justify-between gap-2">
							<strong>{recipe.title}</strong>
							{selected ? <StatusBadge status="SELECTED" /> : null}
							</div>
							<div className="mt-1 text-[10px] text-slate-500">
							{available ? recipe.detail : "Unavailable for this model"}
							</div>
							</button>
							);
							})}
						</div>
					</WorkflowStep>

										<WorkflowStep
						index={3}
						title="Readiness"
						status={guidedAuthorityReady ? "done" : allocations.length ? "active" : "upcoming"}
						summary={guidedAuthorityReady ? "Authority reconciled" : "Needs reconciliation"}
						helper="Product authority and capacity must be reconciled before a plan can be created."
					>
						{guidedAuthorityReady ? (
							<div className="rounded-lg border border-emerald-500/30 bg-emerald-950/20 px-3 py-2 text-[11px] text-emerald-200">Product authority is reconciled — you can create a plan.</div>
						) : (
							<span data-testid="p6-guided-authority-blocker" className="block rounded-lg border border-rose-500/30 bg-rose-950/30 px-3 py-2 text-[10px] text-rose-200">Product authority needs reconciliation before a new plan can be created.</span>
						)}
					</WorkflowStep>

										<WorkflowStep
						index={4}
						title="Compile & generate"
						status={selectedPlan ? "done" : allocations.length && guidedAuthorityReady ? "active" : "upcoming"}
						summary={p6V4PlanStatus}
						helper="Compile and dry-run are free. Live dispatch is a separate, explicit credit action."
					>
						<div className="space-y-3">
							<div className="flex flex-wrap items-center justify-between gap-3">
								<div className="text-xs text-slate-400"><span className="font-semibold text-slate-200">Current:</span>{" "}{guidedRecipe} · {p6V4PlanStatus}</div>
								{guidedNextAction ? (
									<button type="button" disabled={guidedNextAction.disabled} onClick={() => void execute(guidedNextAction.actionName, guidedNextAction.executeAction)} data-testid="p6-guided-next-action" className="rounded-lg bg-cyan-400 px-3 py-2 text-[10px] font-bold text-slate-950 disabled:cursor-not-allowed disabled:opacity-40">{guidedNextAction.buttonLabel}</button>
								) : null}
							</div>
							<p className="text-[10px] text-slate-500">The full factory, matrix, waves, QA and live confirmation live in the Advanced workspace below.</p>
						</div>
					</WorkflowStep>

					<details
						data-testid="p6-advanced-workspace"
						open={advancedWorkspaceOpen}
						onToggle={(event) =>
							setAdvancedWorkspaceOpen(event.currentTarget.open)
						}
						className="rounded-2xl border border-slate-800 bg-slate-950/70 p-3"
					>
						<summary className="cursor-pointer list-none text-xs font-semibold text-slate-300">
							Advanced workspace · factory, matrix, history and diagnostics
						</summary>
						<div className="mt-4">{surface}</div>
					</details>
				</div>
			</WorkflowStep>
		) : (
			surface
		);

	return (
		<div
			data-testid={useV4 ? "p6-v4-shell" : undefined}
			data-variant={useV4 ? "v4" : undefined}
			className={
				useV4
					? "min-h-full bg-slate-950 p-4 text-slate-100 md:p-6"
					: "mx-auto max-w-[1680px] p-4 text-slate-100"
			}
		>
			{useV4 ? (
				<header
					data-testid="p6-v4-header"
					className="mb-5 flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-cyan-500/30 bg-gradient-to-br from-slate-950 via-slate-950 to-violet-950/30 p-5 shadow-2xl"
				>
					<div>
						<div className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.2em] text-cyan-300">
							<ShieldCheck size={15} /> Production Studio · P6 · V4
						</div>
						<h1 className="mt-2 text-2xl font-bold tracking-tight text-slate-100">
							Batch production control plane
						</h1>
						<p className="mt-2 max-w-3xl text-sm text-slate-400">
							The bespoke batch and matrix orchestration stays intact; the V4
							frame adds guided visual hierarchy and a live results rail.
						</p>
					</div>
					<nav className="flex flex-wrap items-center gap-2 text-[11px] font-semibold">
						<a
							href="/operator/hybrid"
							className="rounded-lg border border-v4-accent/30 bg-v4-accent/10 px-3 py-1.5 text-v4-accent-ink"
						>
							Hybrid workspace ↗
						</a>
						<a
							href="/assets/creative-library"
							className="rounded-lg border border-slate-700 px-3 py-1.5 text-slate-300"
						>
							Creative Library ↗
						</a>
						<a
							href="/production-studio?classic=1"
							className="rounded-lg border border-slate-700 px-3 py-1.5 text-slate-400"
						>
							Switch to classic view
						</a>
					</nav>
				</header>
			) : null}

			<div className="space-y-2" data-testid="p6-v2-copy-authority-list">
				{allocations.length ? (
					allocations.map((allocation) => (
						<CopyArchitectureV2LaneCard
							key={allocation.product_id}
							lane="PRODUCTION_STUDIO_P6"
							productId={allocation.product_id}
							execution={
								(detail?.snapshot?.pool_snapshot?.copy_architecture_v2 as
									| Record<string, unknown>
									| undefined) ?? null
							}
							onReadyChange={(ready) =>
								setV2CopyReadyByProduct((current) =>
									current[allocation.product_id] === ready
										? current
										: { ...current, [allocation.product_id]: ready },
								)
							}
						/>
					))
				) : (
					<CopyArchitectureV2LaneCard lane="PRODUCTION_STUDIO_P6" productId={null} />
				)}
			</div>

			<CopySupplyPanel
				products={copySupplyProducts}
				defaultDurationSeconds={form.durationSeconds}
				campaignKey={form.campaignKey}
				productionPlanId={selectedPlanId || null}
			/>

			<div className={useV4 ? "grid gap-5 2xl:grid-cols-[minmax(0,1fr)_20rem]" : "contents"}>
				<div className={useV4 ? "min-w-0" : "contents"}>
					{p6V4Surface(
						<div className="mx-auto max-w-[1680px] space-y-4 p-4 text-slate-100">
			<header className="rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-950 via-slate-950 to-cyan-950/30 p-5 shadow-2xl">
				<div className="flex flex-wrap items-start justify-between gap-4">
					<div>
						<div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
							<ShieldCheck size={15} />
							Production Studio
						</div>
						<h1 className="text-2xl font-bold tracking-tight">
							Production plans
						</h1>
						<p className="mt-2 max-w-3xl text-sm text-slate-400">
							Choose products, review capacity, prepare the content matrix, run
							a zero-credit check, then start production only with explicit
							confirmation.
						</p>
					</div>
					<div className="grid min-w-[320px] grid-cols-2 gap-2">
						<Metric
							label="Available products"
							value={cohort?.cohort_count ?? "…"}
							tone={
								cohort?.matches_frozen_authority
									? "text-emerald-300"
									: "text-rose-300"
							}
						/>
						<Metric label="Live credits" value="LOCKED" tone="text-rose-300" />
					</div>
				</div>
				<div className="mt-4 flex flex-wrap items-center gap-2 text-[11px]">
					<StatusBadge
						status={
							cohort?.matches_frozen_authority
								? "PRODUCT LIST READY"
								: "PRODUCT LIST CHECK REQUIRED"
						}
						testId="p6-cohort-authority"
					/>
					<span
						data-testid="p6-zero-credit-boundary"
						className="rounded border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-cyan-200"
					>
						Compile + dry run = 0 media credits
					</span>
					<details className="rounded border border-slate-800 bg-slate-900 px-2 py-1 text-slate-500">
						<summary className="cursor-pointer">Technical details</summary>
						<div className="mt-2 font-mono">
							Cohort SHA: {cohort?.cohort_sha256 ?? "loading"}
						</div>
					</details>
				</div>
			</header>

			{error && (
				<div
					role="alert"
					data-testid="p6-error-state"
					className="rounded-xl border border-rose-500/40 bg-rose-950/50 p-3 text-sm text-rose-200"
				>
					<div className="flex items-start gap-2">
						<XCircle className="mt-0.5 shrink-0" size={16} />
						<div>
							<strong>
								Production Studio stopped before an unsafe action.
							</strong>
							<div className="mt-1 text-xs">
								Review the selected product readiness and governed controls,
								then retry.
							</div>
							<details className="mt-2 text-[10px]">
								<summary className="cursor-pointer">Technical details</summary>
								<div className="mt-1 break-all font-mono">{error}</div>
							</details>
						</div>
					</div>
				</div>
			)}

			<section
				data-testid="p6-plan-selector-bar"
				className="rounded-2xl border border-cyan-500/30 bg-cyan-950/20 p-4"
			>
				<div className="flex flex-wrap items-center justify-between gap-3">
					<div className="flex items-center gap-2">
						<Layers3 className="text-cyan-400" size={18} />
						<span className="text-xs font-bold uppercase tracking-wider text-cyan-200">
							Select existing plan
						</span>
					</div>
					<div className="flex items-center gap-2 min-w-0 flex-1 justify-end">
						<select
							aria-label="Select production plan"
							data-testid="p6-plan-select"
							value={selectedPlanId}
							onChange={(e) => {
								const nextId = e.target.value;
								if (!nextId) {
									switchToNewDraft();
								} else {
									void loadPlan(nextId).catch((reason) =>
										setError(String(reason)),
									);
								}
							}}
							className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-white outline-none focus:border-cyan-500 max-w-xs truncate"
						>
							<option value="">New production plan</option>
							{primaryPlans.map((p) => (
								<option key={p.plan_id} value={p.plan_id}>
									{p.name} ({p.status} · {p.target_video_count} videos)
								</option>
							))}
						</select>
						<button
							type="button"
							onClick={switchToNewDraft}
							className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 shrink-0"
						>
							Return to new plan
						</button>
					</div>
				</div>

				{studioMode === "LOADING_PLAN" ? (
					<div
						data-testid="p6-plan-loading"
						className="mt-2 text-xs text-cyan-200"
					>
						Loading the selected plan…
					</div>
				) : selectedPlan && selectedSnapshot ? (
					<div className="mt-3 border-t border-cyan-500/20 pt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
						<div>
							<span className="font-bold text-white">
								{selectedSnapshot.plan_name}
							</span>{" "}
							<span className="font-mono text-[10px] text-slate-400">
								({selectedSnapshot.plan_id})
							</span>
							<div className="mt-0.5 text-[11px] text-cyan-300">
								{selectedSnapshot.target_video_count} video
								{selectedSnapshot.target_video_count === 1 ? "" : "s"} across{" "}
								{selectedSnapshot.product_allocations.length} product
								{selectedSnapshot.product_allocations.length === 1 ? "" : "s"} ·{" "}
								{selectedSnapshot.logical_mode} ·{" "}
								{selectedSnapshot.video_configurations
									.map(
										(configuration) =>
											`${configuration.model_label} · ${configuration.requested_total_duration_seconds}s ${configuration.generation_mode}`,
									)
									.join(" / ")}{" "}
								· {selectedSnapshot.aspect_ratio}
							</div>
						</div>
						<div className="flex items-center gap-2">
							<StatusBadge status={selectedPlan.status} />
							<button
								type="button"
								onClick={duplicateActivePlan}
								className="rounded bg-cyan-600/30 hover:bg-cyan-600/50 border border-cyan-500/50 px-2.5 py-1 text-[11px] font-semibold text-cyan-100"
							>
								Duplicate as new plan
							</button>
						</div>
					</div>
				) : (
					<div className="mt-2 text-xs text-slate-400">
						{studioMode === "UNSAVED_DRAFT_FROM_ACTIVE_PLAN"
							? "UNSAVED NEW PLAN — the selected historical plan remains read-only."
							: "NEW PRODUCTION PLAN — no existing plan is selected."}
					</div>
				)}
			</section>

			<div className="grid gap-6 2xl:grid-cols-[420px_minmax(0,1fr)]">
				<aside className="space-y-4">
					{studioMode === "UNSAVED_DRAFT_FROM_ACTIVE_PLAN" &&
					draftSourceSnapshot ? (
						<div
							data-testid="p6-unsaved-draft-warning"
							className="rounded-2xl border border-amber-500/50 bg-amber-950/40 p-4 text-xs text-amber-200 space-y-2.5"
						>
							<div className="flex items-center gap-2 font-bold text-amber-300 text-sm">
								<AlertTriangle size={17} className="shrink-0 text-amber-400" />
								UNSAVED NEW PLAN
							</div>
							<p className="text-[11px] leading-relaxed text-amber-200/80">
								This draft was copied from {draftSourceSnapshot.plan_name}. Its
								matrix, attempts, QA and live controls are not attached to this
								draft.
							</p>
							<details className="text-[10px] text-amber-100/70">
								<summary>Source plan technical details</summary>
								<div className="mt-1 font-mono">
									{draftSourceSnapshot.plan_id}
								</div>
							</details>
						</div>
					) : null}

					{studioMode === "NEW_DRAFT" ||
					studioMode === "UNSAVED_DRAFT_FROM_ACTIVE_PLAN" ? (
						<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
							<div className="mb-3 flex items-center gap-2">
								<WandSparkles size={16} className="text-cyan-300" />
								<h2 className="font-semibold">New production plan</h2>
							</div>
							<div className="grid gap-3">
								<label className="text-xs text-slate-400">
									Plan name
									<input
										aria-label="Plan name"
										value={form.name}
										onChange={(event) =>
											setForm({ ...form, name: event.target.value })
										}
										className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
									/>
								</label>
								<div>
									<div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan-300">
										A. Choose products
									</div>
									<ProductAllocationPicker
										products={cohort?.products ?? []}
										knownProducts={Object.values(knownCohortProducts)}
										allocations={allocations}
										onChange={setAllocations}
										onSearchChange={handleCohortSearchChange}
										onPageChange={handleCohortPageChange}
										page={{
											offset: cohortOffset,
											limit: P6_COHORT_PAGE_SIZE,
											total: cohort?.total_count ?? cohort?.cohort_count ?? 0,
										}}
										blockersByProduct={blockersByProduct}
										loading={cohortLoading}
										error={cohortError}
									/>
								</div>
								<label className="text-xs text-slate-400">
									Operator identity
									<input
										aria-label="P6 operator identity"
										value={operatorId}
										onChange={(event) => setOperatorId(event.target.value)}
										className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white"
									/>
								</label>
								<div className="grid grid-cols-3 gap-2">
									<div className="rounded-lg border border-cyan-500/30 bg-cyan-950/20 p-2">
										<div className="text-[10px] text-slate-400">Videos</div>
										<div className="mt-1 text-lg font-semibold text-cyan-200">
											{totalVideoCount}
										</div>
										<div className="text-[9px] text-slate-500">
											From product quantities
										</div>
									</div>
									{(
										[
											["imageCount", "Images"],
											["posterCount", "Posters"],
										] as const
									).map(([key, label]) => (
										<label key={key} className="text-xs text-slate-400">
											{label}
											<input
												aria-label={label}
												type="number"
												min={0}
												max={200}
												value={form[key]}
												onChange={(event) =>
													setForm({
														...form,
														[key]: Number(event.target.value),
													})
												}
												className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-white"
											/>
										</label>
									))}
								</div>
								<div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan-300">
									B. Configure video
								</div>
								<div className="grid grid-cols-2 gap-2">
									<label className="text-xs text-slate-400">
										Video mode
										<select
											aria-label="Video logical mode"
											value={form.logicalMode}
											onChange={(event) =>
												setForm({
													...form,
													logicalMode: event.target
														.value as typeof form.logicalMode,
												})
											}
											className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-white"
										>
											{["T2V", "HYBRID", "F2V", "I2V"].map((mode) => (
												<option key={mode}>{mode}</option>
											))}
										</select>
									</label>
									<label className="text-xs text-slate-400">
										Model
										<select
											aria-label="Governed video model"
											value={form.modelKey}
											onChange={(event) => chooseModel(event.target.value)}
											disabled={!videoModels.length}
											className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-white"
										>
											{videoModels.map((model) => (
												<option
													key={model.key}
													value={model.key}
													disabled={
														model.key !== form.modelKey &&
														!supportsTreatmentConfiguration(
															model.key,
															form.durationSeconds,
															form.creativeFormat,
														)
													}
												>
													{model.ui_label}
												</option>
											))}
										</select>
									</label>
									<label className="text-xs text-slate-400">
										Duration
										<select
											aria-label="Governed video duration"
											value={form.durationSeconds}
											onChange={(event) =>
												setForm({
													...form,
													durationSeconds: Number(event.target.value),
												})
											}
											className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-white"
										>
											{durationOptions.map((option) => (
												<option
													key={option.seconds}
													value={option.seconds}
													disabled={
														option.seconds !== form.durationSeconds &&
														!supportsTreatmentConfiguration(
															selectedModel?.key ?? form.modelKey,
															option.seconds,
															form.creativeFormat,
														)
													}
												>
													{option.seconds}s —{" "}
													{option.generationMode === "SINGLE"
														? "Single"
														: `Extend · ${option.segments} × ${option.blockSeconds}s`}
												</option>
											))}
										</select>
									</label>
									<label className="text-xs text-slate-400">
										Aspect ratio
										<select
											aria-label="Video aspect ratio"
											value={form.aspect}
											onChange={(event) =>
												setForm({
													...form,
													aspect: event.target.value as typeof form.aspect,
												})
											}
											className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-white"
										>
											<option value="9:16">9:16 · Portrait</option>
											<option value="16:9">16:9 · Landscape</option>
										</select>
									</label>
								</div>
								{form.logicalMode === "HYBRID" ? (
									<div
										data-testid="p6-hybrid-anchor-note"
										className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-2 text-xs text-emerald-100"
									>
										Hybrid anchor is automatic: every product in this bulk run uses
										its own Official Product Visual (approved cutout → source image)
										saved in Smart Product Registration as the anchor. No start-frame
										picker or Creative Library selection is needed here.
									</div>
								) : null}
								<label className="text-xs text-slate-400">
									Creative Treatment format
									<select
										aria-label="Creative Treatment format"
										value={form.creativeFormat}
										onChange={(event) =>
											setForm({
												...form,
												creativeFormat: event.target
													.value as CreativeTreatmentFormatPreference,
											})
										}
										className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-white"
									>
										{["AUTO", "UGC", "PGC", "CINEMATIC"].map((format) => (
											<option
												key={format}
												value={format}
												disabled={
													format !== "AUTO" &&
													Boolean(treatmentAvailability?.supported_formats.length) &&
													!treatmentAvailability?.supported_formats.includes(
														format as "UGC" | "PGC" | "CINEMATIC",
													)
												}
											>
												{format === "AUTO"
													? "Auto-select approved format"
													: format}
											</option>
										))}
									</select>
								</label>
								<div
									data-testid="p6-treatment-availability"
									className={`rounded-xl border p-3 text-xs ${
										treatmentAvailability?.ready
											? "border-emerald-500/30 bg-emerald-950/30 text-emerald-100"
											: "border-amber-500/40 bg-amber-950/30 text-amber-100"
									}`}
								>
									<div className="flex items-center justify-between gap-2">
										<strong>Creative Treatment capacity</strong>
										<StatusBadge
											status={
												treatmentAvailabilityLoading
													? "CHECKING"
													: treatmentAvailability?.ready
														? "READY"
														: "BLOCKED"
											}
										/>
									</div>
									<div className="mt-2">
										{treatmentDisabledReason ||
											`${treatmentAvailability?.selected_treatment_ids.length ?? 0}/${totalVideoCount} unique approved visual treatments allocated. Copy text always comes from Copy Register V2.`}
									</div>
									{treatmentAvailability?.product_results.map((product) => (
										<div key={product.product_id} className="mt-1 text-[10px] opacity-80">
											{productNameById.get(product.product_id) ?? product.product_id}: {product.selected_count}/{product.requested}
										</div>
									))}
								</div>
								{selectedDurationOption ? (
									<div
										data-testid="p6-orchestration-summary"
										className={`rounded-xl border p-3 text-xs ${
											selectedDurationOption.generationMode === "EXTEND"
												? "border-violet-500/40 bg-violet-950/30 text-violet-100"
												: "border-emerald-500/30 bg-emerald-950/30 text-emerald-100"
										}`}
									>
										<strong>
											{selectedDurationOption.generationMode === "EXTEND"
												? `Extend · ${selectedDurationOption.segments} continuous ${selectedDurationOption.blockSeconds}-second segments`
												: "Single-shot"}
										</strong>
										<div className="mt-1 text-[10px] opacity-80">
											{selectedDurationOption.generationMode === "EXTEND"
												? "Compile prepares a reviewed multi-part video. Joining happens only after separate live confirmation."
												: "One video starts only after separate live confirmation."}
										</div>
									</div>
								) : null}
								{modelRegistryError ? (
									<div className="rounded-lg border border-rose-500/30 bg-rose-950/30 p-2 text-xs text-rose-200">
										The video model list is unavailable. Plan creation is
										locked.
									</div>
								) : null}
								<div className="grid grid-cols-2 gap-2">
									<label className="text-xs text-slate-400">
										Operating window
										<select
											aria-label="Operating window hours"
											value={form.windowHours}
											onChange={(event) =>
												setForm({
													...form,
													windowHours: Number(event.target.value),
												})
											}
											className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-white"
										>
											{[8, 12, 24].map((hours) => (
												<option key={hours} value={hours}>
													{hours} hours
												</option>
											))}
										</select>
									</label>
								</div>
								<details className="rounded-xl border border-slate-800 bg-slate-900/40 p-3">
									<summary className="cursor-pointer text-xs font-semibold text-slate-300">
										Advanced approved pools and reuse controls
									</summary>
									<div className="mt-3 grid gap-3">
										<div
											data-testid="p6-official-product-visual-note"
											className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-2 text-xs text-emerald-100"
										>
											Product images are not selected from Creative Library here. Every P6
											IMG, Hybrid, I2V, and Poster item uses the Official Product Visual
											saved in Smart Product Registration.
										</div>
										{poolAuthorityLoading ? (
											<div
												data-testid="p6-pool-authority-loading"
												className="rounded-lg border border-sky-500/30 bg-sky-950/20 p-2 text-xs text-sky-100"
											>
												Loading governed supply for the selected products…
											</div>
										) : null}
										{[
											{
												key: "avatarCodes",
												label: "Product-first approved avatars",
												options: approvedAvatarOptions,
												valueKey: "avatar_code",
												labelKeys: ["character_name", "variant"],
											},
											{
												key: "finishedFrameAssetIds",
												label: "Finished composite frames",
												options: poolAuthority?.finished_frame_assets ?? [],
												valueKey: "asset_id",
												labelKeys: ["name", "semantic_role"],
											},
											{
												key: "characterAssetIds",
												label: "Character reference assets",
												options: poolAuthority?.character_assets ?? [],
												valueKey: "asset_id",
												labelKeys: ["name", "semantic_role"],
											},
											{
												key: "sceneAssetIds",
												label: "Scene context assets",
												options: poolAuthority?.scene_assets ?? [],
												valueKey: "asset_id",
												labelKeys: ["name", "semantic_role"],
											},
											{
												key: "styleAssetIds",
												label: "Style reference assets",
												options: poolAuthority?.style_assets ?? [],
												valueKey: "asset_id",
												labelKeys: ["name", "semantic_role"],
											},
											{
												key: "layoutIds",
												label: "Authoritative poster recipes",
												options: poolAuthority?.poster_recipes ?? [],
												valueKey: "recipe_id",
												labelKeys: ["name", "layout_family"],
											},
									].map(({ key, label, options, valueKey, labelKeys }) => {
										if (key === "avatarCodes") {
											const selectedCodes = new Set(
												splitValues(form.avatarCodes),
											);
											return (
												<fieldset
													key={key}
													className="rounded-lg border border-slate-700 bg-slate-900/60 p-3 text-xs text-slate-300"
													data-testid="p6-avatar-pool"
												>
													<legend className="px-1 text-slate-400">{label}</legend>
													<div className="mt-1 grid gap-2 sm:grid-cols-2">
														{options.length ? (
															options.map((option) => {
																const value = String(option[valueKey] ?? "").trim();
																const descriptor = labelKeys
																	.map((labelKey) =>
																		String(option[labelKey] ?? "").trim(),
																	)
																	.filter(Boolean)
																	.join(" · ");
																const optionLabel = `${descriptor || value} — ${value}`;
																return (
																	<label
																		key={value}
																		className="flex items-start gap-2 rounded border border-slate-700 bg-slate-950/70 px-2 py-2"
																	>
																		<input
																			type="checkbox"
																			aria-label={optionLabel}
																			checked={selectedCodes.has(value)}
																			onChange={(event) => {
																				const checked = event.currentTarget.checked;
																				setForm((current) => {
																					const next = new Set(
																						splitValues(current.avatarCodes),
																					);
																					if (checked) next.add(value);
																					else next.delete(value);
																					return {
																						...current,
																						avatarCodes: Array.from(next).join(","),
																					};
																				});
																			}}
																		/>
																		<span>{optionLabel}</span>
																	</label>
																);
															})
														) : (
															<span className="text-amber-300">
																No product-approved avatar is available for this selection.
															</span>
														)}
													</div>
													<p className="mt-2 text-[10px] text-slate-500">
														Product-approved avatars are included by default. Clear a checkbox
														only when you intentionally want to remove that presenter.
													</p>
												</fieldset>
											);
										}
										return (
											<label key={key} className="text-xs text-slate-400">
												{label}
												<select
													multiple
													aria-label={label}
													value={splitValues(
														form[key as keyof typeof form] as string,
													)}
													onChange={(event) =>
														setForm({
															...form,
															[key]: Array.from(
																event.currentTarget.selectedOptions,
																(option) => option.value,
															).join(","),
														})
													}
													className="mt-1 min-h-20 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white"
												>
													{options.map((option) => {
														const value = String(option[valueKey] ?? "");
														const descriptor = labelKeys
															.map((labelKey) => String(option[labelKey] ?? ""))
															.filter(Boolean)
															.join(" · ");
														return (
															<option key={value} value={value}>
																{descriptor || value}
															</option>
														);
													})}
												</select>
											</label>
										);
									})}
										<label className="text-xs text-slate-400">
											Approved Creative Treatment IDs (optional visual override)
											<textarea
												aria-label="Approved Creative Treatment IDs"
												value={form.treatmentIds}
												onChange={(event) =>
													setForm({ ...form, treatmentIds: event.target.value })
												}
												placeholder="Leave empty for deterministic visual-treatment allocation; one ID per line"
												className="mt-1 min-h-20 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs text-white"
											/>
											<span className="mt-1 block text-[10px] text-slate-500">
												Only visual/shot authority is inherited. Dialogue and copy lineage are always resolved from the approved V2 binding.
											</span>
										</label>
										{poolAuthority?.blockers.length ? (
											<div
												data-testid="p6-pool-authority-blockers"
												className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-2 text-xs text-amber-100"
											>
												{poolAuthority.blockers.length} governed pool
												blocker(s). The server will fail closed until they are
												resolved.
											</div>
										) : null}
										<label className="text-xs text-slate-400">
											Controlled reuse reason (optional and explicit)
											<input
												aria-label="Controlled reuse reason"
												value={form.controlledReuseReason}
												onChange={(event) =>
													setForm({
														...form,
														controlledReuseReason: event.target.value,
													})
												}
												className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white"
											/>
										</label>
										<label className="text-xs text-slate-400">
											Maximum exact DNA reuse (1–3)
											<select
												aria-label="Maximum exact DNA reuse"
												value={form.controlledReuseMaxPerDna}
												onChange={(event) =>
													setForm({
														...form,
														controlledReuseMaxPerDna: Number(
															event.target.value,
														),
													})
												}
												className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-white"
											>
												{[1, 2, 3].map((value) => (
													<option key={value} value={value}>
														{value}
													</option>
												))}
											</select>
										</label>
									</div>
								</details>
								<button
									type="button"
									data-testid="p6-create-plan"
									disabled={
										Boolean(busy) ||
										!cohort?.matches_frozen_authority ||
										!allocations.length ||
										invalidAllocation ||
										poolAuthorityLoading ||
										!poolAuthority ||
										treatmentCreateBlocked ||
										!form.modelKey ||
										!selectedDuration ||
										Boolean(modelRegistryError) ||
										!operatorId.trim() ||
										Boolean(poolAuthority?.blockers.length) ||
										!v2CopyReady ||
										!form.name
									}
									onClick={() => void execute("create", create)}
									className="rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-700"
								>
									{busy === "create"
										? "Creating plan…"
										: studioMode === "UNSAVED_DRAFT_FROM_ACTIVE_PLAN"
											? "Create new production plan"
											: "Create production plan"}
								</button>
							</div>
						</section>
					) : selectedSnapshot ? (
						<section
							data-testid="p6-readonly-plan-snapshot"
							className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4"
						>
							<h2 className="font-semibold">Selected plan</h2>
							<p className="mt-1 text-xs text-slate-400">
								Read-only plan snapshot
							</p>
							<div className="mt-3 space-y-2 text-xs">
								{selectedSnapshot.product_allocations.map((allocation) => (
									<div
										key={allocation.product_id}
										className="flex justify-between rounded border border-slate-800 p-2"
									>
										<span>{allocation.product_name}</span>
										<span>
											{allocation.video_count} video
											{allocation.video_count === 1 ? "" : "s"}
										</span>
									</div>
								))}
								<div>
									{selectedSnapshot.video_configurations.map(
										(configuration) => (
											<div
												key={`${configuration.model_key}-${configuration.requested_total_duration_seconds}`}
											>
												{configuration.model_label} ·{" "}
												{configuration.requested_total_duration_seconds}s{" "}
												{configuration.generation_mode} ·{" "}
												{configuration.segment_count} segment
												{configuration.segment_count === 1 ? "" : "s"}
											</div>
										),
									)}
								</div>
								<div>Aspect ratio: {selectedSnapshot.aspect_ratio}</div>
								<div>
									Operating window: {selectedSnapshot.operating_window_hours}{" "}
									hours
								</div>
								<div data-testid="p6-selected-treatment-authority">
									Creative Treatments: {selectedTreatmentIds.length} immutable visual approval{selectedTreatmentIds.length === 1 ? "" : "s"}
									{selectedTreatmentIds.length ? ` · ${selectedTreatmentIds.join(", ")}` : " · no governed treatment authority"}
									{" · "}Copy authority: COPY_REGISTER_V2_ONLY
								</div>
							</div>
							<button
								type="button"
								onClick={duplicateActivePlan}
								className="mt-3 w-full rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white"
							>
								Duplicate as new plan
							</button>
						</section>
					) : null}

					<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
						<div className="mb-3 flex items-center justify-between">
							<h2 className="font-semibold">Production history</h2>
							<button
								type="button"
								aria-label="Refresh production plans"
								onClick={() => void execute("refresh", () => refresh())}
								className="rounded border border-slate-700 p-1.5 text-slate-300 hover:bg-slate-800"
							>
								<RefreshCw size={14} />
							</button>
						</div>
						<div className="mb-3 grid grid-cols-2 gap-2">
							<input
								aria-label="Search production history"
								value={historySearch}
								onChange={(event) => setHistorySearch(event.target.value)}
								placeholder="Search plans or products"
								className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-white"
							/>
							<select
								aria-label="Filter production history by status"
								value={historyStatus}
								onChange={(event) => setHistoryStatus(event.target.value)}
								className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-white"
							>
								<option value="ACTIVE">Active and drafts</option>
								<option value="COMPLETED">Completed</option>
								<option value="CANCELLED_FAILED">Cancelled / failed</option>
								<option value="ALL">All history</option>
							</select>
						</div>
						<div className="max-h-72 space-y-2 overflow-auto">
							{filteredHistory.length === 0 && (
								<div
									data-testid="p6-empty-plans"
									className="rounded-lg border border-dashed border-slate-700 p-4 text-center text-xs text-slate-500"
								>
									No plans match this filter.
								</div>
							)}
							{filteredHistory.map((plan) => {
								const configuration =
									plan.snapshot_summary?.video_configurations[0];
								const productCount =
									plan.snapshot_summary?.product_allocations.length ?? 0;
								return (
									<button
										key={plan.plan_id}
										type="button"
										onClick={() =>
											void loadPlan(plan.plan_id).catch((reason) =>
												setError(String(reason)),
											)
										}
										className={`w-full rounded-xl border p-3 text-left ${
											selectedPlanId === plan.plan_id
												? "border-cyan-500/60 bg-cyan-950/30"
												: "border-slate-800 bg-slate-900/70"
										}`}
									>
										<div className="flex items-start justify-between gap-2">
											<div className="text-sm font-medium">{plan.name}</div>
											<StatusBadge status={plan.status} />
										</div>
										<div className="mt-1 text-[10px] text-slate-400">
											{productCount} product{productCount === 1 ? "" : "s"} ·{" "}
											{plan.target_video_count} video
											{plan.target_video_count === 1 ? "" : "s"} ·{" "}
											{plan.logical_mode}
											{configuration
												? ` · ${configuration.requested_total_duration_seconds}s ${configuration.generation_mode}`
												: " · Incomplete snapshot"}{" "}
											· Updated {new Date(plan.updated_at).toLocaleString()}
										</div>
									</button>
								);
							})}
						</div>
						<details className="mt-3 text-[10px] text-slate-500">
							<summary>History classification details</summary>
							<p className="mt-1">
								Status filters are authoritative. Test and UAT plans are not
								classified by name because no reliable provenance marker exists.
							</p>
						</details>
					</section>
				</aside>

				<main className="min-w-0 space-y-4">
					{!detail ? (
						<div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/60 p-12 text-center text-slate-500">
							<Database className="mx-auto mb-3" />
							{studioMode === "LOADING_PLAN"
								? "Loading the selected plan…"
								: "Create a new production plan or select an existing plan."}
						</div>
					) : (
						<>
							<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
								<div className="flex flex-wrap items-start justify-between gap-3">
									<div>
										<div className="flex items-center gap-2">
											<h2 className="text-lg font-semibold">
												{detail.plan.name}
											</h2>
											<StatusBadge
												status={detail.plan.status}
												testId="p6-plan-status"
											/>
										</div>
									</div>
									<div className="flex flex-wrap gap-2">
										<button
											type="button"
											disabled={actionDisabled}
											onClick={() =>
												void execute("pause", () =>
													controlProductionPlan(
														detail.plan.plan_id,
														"pause",
														operatorId,
													),
												)
											}
											className="rounded border border-amber-500/40 px-2 py-1 text-xs text-amber-200 disabled:opacity-40"
										>
											<Pause className="mr-1 inline" size={12} />
											Pause
										</button>
										<button
											type="button"
											disabled={actionDisabled}
											onClick={() =>
												void execute("resume", () =>
													controlProductionPlan(
														detail.plan.plan_id,
														"resume",
														operatorId,
													),
												)
											}
											className="rounded border border-sky-500/40 px-2 py-1 text-xs text-sky-200 disabled:opacity-40"
										>
											<Play className="mr-1 inline" size={12} />
											Resume
										</button>
										<button
											type="button"
											disabled={actionDisabled}
											onClick={() =>
												void execute("cancel", () =>
													controlProductionPlan(
														detail.plan.plan_id,
														"cancel",
														operatorId,
													),
												)
											}
											className="rounded border border-rose-500/40 px-2 py-1 text-xs text-rose-200 disabled:opacity-40"
										>
											<Square className="mr-1 inline" size={12} />
											Cancel
										</button>
									</div>
								</div>
								<div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
									<Metric
										label="Video"
										value={detail.plan.target_video_count}
									/>
									<Metric
										label="Image"
										value={detail.plan.target_image_count}
									/>
									<Metric
										label="Poster"
										value={detail.plan.target_poster_count}
									/>
									<Metric label="Items" value={detail.progress.total} />
									<Metric
										label="Progress"
										value={`${detail.progress.percent}%`}
									/>
									<Metric
										label="Window"
										value={`${detail.plan.operating_window_hours}h`}
									/>
								</div>
							</section>

							<section className="rounded-2xl border border-slate-800 bg-slate-950/90 p-4 shadow-xl">
								<div className="mb-3 flex items-center justify-between">
									<div className="flex items-center gap-2">
										<GitBranch size={16} className="text-cyan-300" />
										<h2 className="font-semibold text-slate-100">
											Production Stepper & Next Action
										</h2>
									</div>
									<span className="text-[11px] font-semibold text-cyan-300">
										STEP {activeStep} OF 6
									</span>
								</div>

								<div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
									{WORKFLOW_STEPS.map((step) => {
										const isCurrent = step.id === activeStep;
										const isDone = step.id < activeStep;
										return (
											<div
												key={step.id}
												className={`flex flex-col justify-between rounded-xl border p-2.5 transition ${
													isCurrent
														? "border-cyan-500/80 bg-cyan-950/40 ring-1 ring-cyan-500/50"
														: isDone
															? "border-emerald-500/40 bg-emerald-950/20 text-slate-300"
															: "border-slate-800 bg-slate-900/40 text-slate-500"
												}`}
											>
												<div className="flex items-center justify-between">
													<span
														className={`text-[10px] font-bold ${
															isCurrent
																? "text-cyan-300"
																: isDone
																	? "text-emerald-400"
																	: "text-slate-500"
														}`}
													>
														STEP {step.id}
													</span>
													{isDone ? (
														<CheckCircle2
															size={13}
															className="text-emerald-400"
														/>
													) : null}
												</div>
												<div className="mt-1.5 text-xs font-semibold text-white">
													{step.label}
												</div>
												<div className="mt-0.5 text-[9px] text-slate-400">
													{step.desc}
												</div>
											</div>
										);
									})}
								</div>

								<div className="mt-4 rounded-xl border border-slate-700 bg-gradient-to-r from-slate-900 via-slate-900 to-slate-950 p-4">
									<div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
										<div>
											<div className="flex items-center gap-2">
												<span className="text-[10px] font-bold uppercase tracking-wider text-cyan-400">
													Current Primary Action
												</span>
												{primaryActionConfig.isCreditSpend ? (
													<span className="rounded border border-rose-500/40 bg-rose-500/20 px-2 py-0.5 text-[10px] font-bold text-rose-300">
														Spends Media Credits
													</span>
												) : (
													<span className="rounded border border-emerald-500/40 bg-emerald-500/20 px-2 py-0.5 text-[10px] font-bold text-emerald-300">
														0 Media Credits
													</span>
												)}
											</div>
											<h3 className="mt-1 text-base font-bold text-white">
												{primaryActionConfig.title}
											</h3>
											<p className="mt-0.5 text-xs text-slate-400">
												{primaryActionConfig.subtitle}
											</p>
											{primaryActionConfig.disabled &&
											primaryActionConfig.disabledReason ? (
												<div className="mt-2 flex items-center gap-1.5 text-[11px] text-amber-300">
													<AlertTriangle size={13} className="shrink-0" />
													<span>{primaryActionConfig.disabledReason}</span>
												</div>
											) : null}
										</div>

										<button
											type="button"
											data-testid={primaryActionConfig.buttonTestId}
											disabled={primaryActionConfig.disabled}
											onClick={() =>
												void execute(
													primaryActionConfig.actionName,
													primaryActionConfig.executeAction,
												)
											}
											className={`shrink-0 rounded-xl px-5 py-3 text-xs font-bold transition shadow-lg disabled:cursor-not-allowed disabled:opacity-40 ${
												primaryActionConfig.isCreditSpend
													? "bg-rose-600 hover:bg-rose-500 text-white disabled:bg-slate-700"
													: "bg-cyan-600 hover:bg-cyan-500 text-white disabled:bg-slate-700"
											}`}
										>
											{primaryActionConfig.buttonLabel}
										</button>
									</div>
								</div>
							</section>

							<details className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
								<summary className="cursor-pointer text-xs font-semibold text-slate-300">
									Advanced workflow controls (individual gates)
								</summary>
								<div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
									{[
										[
											"Preflight",
											() =>
												preflightProductionPlan(
													detail.plan.plan_id,
													operatorId,
												).then((result) => {
													setPreflight(result);
													return result;
												}),
											"p6-action-preflight",
										],
										[
											"Build matrix",
											() =>
												materializeContentMatrix(
													detail.plan.plan_id,
													operatorId,
												),
											"p6-action-matrix",
										],
										[
											"Compile · 0 credit",
											() =>
												compileProductionPlan(detail.plan.plan_id, operatorId),
											"p6-action-compile",
										],
										[
											"Bulk approve",
											() =>
												approveProductionPlan(detail.plan.plan_id, operatorId),
											"p6-action-approve",
										],
										[
											"Assign waves",
											() =>
												assignProductionWaves(
													detail.plan.plan_id,
													operatorId,
													2,
													25,
												),
											"p6-action-waves",
										],
										[
											"Dry run · 0 credit",
											() =>
												dryRunProductionPlan(
													detail.plan.plan_id,
													operatorId,
													detail.snapshot.aspect_ratio,
												),
											"p6-action-dry-run",
										],
									].map(([label, action, testId]) => (
										<button
											key={label as string}
											type="button"
											data-testid={testId as string}
											disabled={actionDisabled}
											onClick={() =>
												void execute(
													label as string,
													action as () => Promise<unknown>,
												)
											}
											className="rounded-lg border border-cyan-500/30 bg-cyan-950/20 px-2 py-2 text-xs font-semibold text-cyan-100 disabled:opacity-40"
										>
											{label as string}
										</button>
									))}
								</div>
							</details>

							<details
								data-testid="p6-capacity-report"
								className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4"
							>
								<summary className="cursor-pointer list-none">
									<div className="flex items-center justify-between gap-3">
										<div className="flex items-center gap-2">
											<Layers3 size={16} className="text-violet-300" />
											<h2 className="font-semibold">Plan readiness</h2>
										</div>
										<span className="text-xs text-slate-400">
											{blockers.length
												? `${blockers.length} action${blockers.length === 1 ? "" : "s"} required`
												: "No current blocker"}
										</span>
									</div>
								</summary>
								<div className="mt-4">
									<div className="grid gap-2 sm:grid-cols-3">
										{["VIDEO", "IMAGE", "POSTER"].map((mediaType) => (
											<div
												key={mediaType}
												className="rounded-xl border border-slate-800 bg-slate-900/60 p-3"
											>
												<div className="text-xs font-semibold text-slate-300">
													{mediaType}
												</div>
												<div className="mt-2 flex justify-between text-xs text-slate-400">
													<span>Requested</span>
													<strong className="text-white">
														{preflightSnapshot?.requested?.[mediaType] ?? "—"}
													</strong>
												</div>
												<div className="mt-1 flex justify-between text-xs text-slate-400">
													<span>Safe unique</span>
													<strong className="text-emerald-300">
														{preflightSnapshot?.safe_capacity?.[mediaType] ??
															"—"}
													</strong>
												</div>
											</div>
										))}
									</div>
									{blockers.length === 0 ? (
										<div className="mt-3 flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-950/30 p-3 text-xs text-emerald-200">
											<CheckCircle2 size={15} />
											No current preflight blocker.
										</div>
									) : (
										<div className="mt-3 space-y-2">
											{blockers.map((blocker) => (
												<div
													key={JSON.stringify(blocker)}
													className="rounded-lg border border-rose-500/30 bg-rose-950/30 p-3 text-xs text-rose-100"
												>
													{blockerMessage(technicalCode(blocker))}
													<details className="mt-2 text-[10px] text-rose-200/70">
														<summary className="cursor-pointer">
															Technical details
														</summary>
														<code className="mt-1 block break-all">
															{JSON.stringify(blocker)}
														</code>
													</details>
												</div>
											))}
										</div>
									)}
								</div>
							</details>

							<details className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
								<summary className="cursor-pointer list-none">
									<div className="flex items-center gap-2">
										<Activity size={16} className="text-sky-300" />
										<h2 className="font-semibold">
											Technical execution-lane status
										</h2>
									</div>
								</summary>
								<div className="mt-3">
									<div className="mb-3 text-[10px] text-slate-500">
										Unverified lanes receive no live work.
									</div>
									<div className="grid gap-2 lg:grid-cols-2">
										{lanes.map((lane) => (
											<div
												key={lane.lane_id}
												data-testid={`p6-lane-${lane.lane_id}`}
												className="rounded-xl border border-slate-800 bg-slate-900/60 p-3"
											>
												<div className="flex items-start justify-between gap-2">
													<div>
														<div className="text-sm font-medium">
															{lane.lane_id}
														</div>
														<div className="mt-1 text-[10px] text-slate-500">
															{lane.provider} · {lane.engine}
														</div>
													</div>
													<StatusBadge status={lane.runtime_proof_status} />
												</div>
												<div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
													<div>
														<div className="text-slate-500">Health</div>
														<div className="mt-1">{lane.health_status}</div>
													</div>
													<div>
														<div className="text-slate-500">Max inflight</div>
														<div className="mt-1">
															{lane.verified_max_inflight}
														</div>
													</div>
													<div>
														<div className="text-slate-500">Leases</div>
														<div className="mt-1">
															{lane.active_lease_count}
														</div>
													</div>
												</div>
											</div>
										))}
									</div>
								</div>
							</details>

							<section className="rounded-2xl border border-rose-500/30 bg-rose-950/20 p-4">
								<div className="flex items-start gap-3">
									<LockKeyhole className="mt-0.5 shrink-0 text-rose-300" />
									<div className="min-w-0 flex-1">
										<div className="flex items-center justify-between gap-2">
											<h2 className="font-semibold text-rose-100">
												Start production for {detail.snapshot.plan_name}
											</h2>
											<span className="rounded border border-rose-500/40 bg-rose-500/20 px-2 py-0.5 text-[10px] font-bold text-rose-300 shrink-0">
												Spends Media Credits
											</span>
										</div>
										<p
											className="mt-1 text-xs text-rose-200/70"
											data-testid="p6-live-certification-truth"
										>
											{liveExecutionCertified
												? `${detail.snapshot.product_allocations.length} product${detail.snapshot.product_allocations.length === 1 ? "" : "s"} · ${detail.snapshot.target_video_count} video${detail.snapshot.target_video_count === 1 ? "" : "s"} · ${detail.snapshot.video_configurations.map((configuration) => `${configuration.model_label} · ${configuration.requested_total_duration_seconds}s ${configuration.generation_mode}`).join(" / ")}. This sends the next queued item now and authorizes the scheduler to continue the same plan.`
												: "Production is unavailable because the runtime certification is absent."}
										</p>
										<details className="mt-2 text-[10px] text-rose-200/60">
											<summary>Technical details</summary>
											<div className="mt-1 font-mono">
												Plan: {detail.snapshot.plan_id}
												<br />
												Lane: {verifiedVideoLane?.lane_id ?? "NOT VERIFIED"}
												<br />
												Aspect: {detail.snapshot.aspect_ratio}
											</div>
										</details>

										{!liveEnabled && liveDisabledReason ? (
											<div
												data-testid="p6-live-disabled-reason"
												className="mt-2.5 flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-950/30 p-2.5 text-xs text-amber-200 font-medium"
											>
												<AlertTriangle
													size={15}
													className="shrink-0 text-amber-400"
												/>
												<span>{liveDisabledReason}</span>
											</div>
										) : null}

										<div className="mt-3 flex flex-col gap-2 sm:flex-row">
											<input
												aria-label="P6 live credit confirmation"
												data-testid="p6-live-confirmation"
												value={livePhrase}
												onChange={(event) => setLivePhrase(event.target.value)}
												placeholder={P6_LIVE_CONFIRMATION}
												className="min-w-0 flex-1 rounded-lg border border-rose-500/40 bg-slate-950 px-3 py-2 font-mono text-xs text-white"
											/>
											<button
												type="button"
												data-testid="p6-action-live-start"
												disabled={!liveEnabled}
												onClick={() =>
													void execute("live", () =>
														startProductionPlan(
															detail.plan.plan_id,
															operatorId,
															livePhrase,
															detail.snapshot.aspect_ratio,
														),
													)
												}
												className="rounded-lg bg-rose-600 px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-700 hover:bg-rose-500 transition"
											>
												{liveEnabled
													? "Start production"
													: "Production unavailable"}
											</button>
										</div>
									</div>
								</div>
							</section>

							<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
								<div className="mb-3 flex flex-wrap gap-2">
									{(["matrix", "attempts", "qa"] as const).map((view) => (
										<button
											key={view}
											type="button"
											onClick={() => setActiveView(view)}
											className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
												activeView === view
													? "bg-cyan-600 text-white"
													: "bg-slate-900 text-slate-400"
											}`}
										>
											{view === "matrix"
												? `Content matrix (${detail.items.length})`
												: view === "attempts"
													? `Attempts (${detail.attempts.length})`
													: `Output QA (${detail.qa.length})`}
										</button>
									))}
								</div>
								{activeView === "matrix" && (
									<div
										data-testid="p6-content-matrix"
										className="overflow-x-auto"
									>
										<table className="w-full min-w-[900px] text-left text-xs">
											<thead className="text-[10px] uppercase tracking-wide text-slate-500">
												<tr>
													<th className="p-2"># / type</th>
													<th className="p-2">Product</th>
													<th className="p-2">Orchestration</th>
													<th className="p-2">Dimensions</th>
													<th className="p-2">State</th>
													<th className="p-2">QA</th>
												</tr>
											</thead>
											<tbody>
												{detail.items.map((item) => (
													<tr
														key={item.item_id}
														className="border-t border-slate-800"
													>
														<td className="p-2">
															<div className="font-semibold">
																{item.item_ordinal + 1} · {item.media_type}
															</div>
														</td>
														<td className="p-2 text-xs">
															{productNameById.get(item.product_id) ||
																"Governed product"}
														</td>
														<td className="p-2 text-[10px] text-violet-200">
															{item.creative_dimensions.generation_mode ||
																"SINGLE"}
															{" · "}
															{item.creative_dimensions.duration_seconds || "—"}
															s
															{item.controlled_reuse_reason && (
																<div className="mt-1 text-amber-300">
																	controlled reuse
																</div>
															)}
															<details className="mt-1 text-slate-500">
																<summary className="cursor-pointer">
																	Technical details
																</summary>
																<div className="mt-1 break-all font-mono">
																	Item: {item.item_id}
																	<br />
																	DNA: {item.creative_dna_sha256}
																</div>
															</details>
														</td>
														<td className="p-2">
															{[
																item.creative_dimensions.angle,
																item.creative_dimensions.hook,
																item.creative_dimensions.layout_id,
															]
																.filter(Boolean)
																.join(" · ") || "—"}
														</td>
														<td className="p-2">
															<StatusBadge status={item.status} />
														</td>
														<td className="p-2">
															{item.status === "QA_PENDING" ? (
																<div className="flex gap-1">
																	<button
																		type="button"
																		onClick={() =>
																			void execute("qa-approve", () =>
																				decideItemQa(
																					item.item_id,
																					operatorId,
																					"QA_APPROVED",
																					false,
																					"Approved in Production Studio.",
																				),
																			)
																		}
																		className="rounded bg-emerald-700 px-2 py-1 text-[10px]"
																	>
																		Approve
																	</button>
																	<button
																		type="button"
																		onClick={() =>
																			void execute("qa-replace", () =>
																				decideItemQa(
																					item.item_id,
																					operatorId,
																					"QA_REJECTED",
																					true,
																					"Replacement requested in Production Studio.",
																				),
																			)
																		}
																		className="rounded bg-rose-700 px-2 py-1 text-[10px]"
																	>
																		Reject + replace
																	</button>
																</div>
															) : (
																<span className="text-slate-600">—</span>
															)}
														</td>
													</tr>
												))}
											</tbody>
										</table>
									</div>
								)}
								{activeView === "attempts" && (
									<div data-testid="p6-attempt-list" className="space-y-2">
										{detail.attempts.length === 0 && (
											<div className="rounded border border-dashed border-slate-700 p-5 text-center text-xs text-slate-500">
												No attempt yet. Dry run records a zero-credit check
												without starting production.
											</div>
										)}
										{detail.attempts.map((attempt: GenerationAttempt) => (
											<div
												key={attempt.attempt_id}
												className="rounded-xl border border-slate-800 bg-slate-900/60 p-3"
											>
												<div className="flex flex-wrap items-start justify-between gap-2">
													<div>
														<div className="text-xs font-semibold">
															Generation attempt {attempt.attempt_number}
														</div>
														<details className="mt-1 text-[10px] text-slate-500">
															<summary className="cursor-pointer">
																Technical details
															</summary>
															<div className="mt-1 break-all font-mono">
																Attempt: {attempt.attempt_id}
																<br />
																Item: {attempt.item_id}
																<br />
																Payload: {attempt.payload_sha256}
															</div>
														</details>
													</div>
													<StatusBadge status={attempt.attempt_state} />
												</div>
												<div className="mt-3 flex flex-wrap gap-2">
													<button
														type="button"
														onClick={() =>
															void execute("reconcile", () =>
																reconcileAttempt(attempt.attempt_id),
															)
														}
														className="rounded border border-sky-500/40 px-2 py-1 text-[10px] text-sky-200"
													>
														<RefreshCw className="mr-1 inline" size={10} />
														Reconcile
													</button>
													<button
														type="button"
														onClick={() =>
															void execute("retry", () =>
																retryAttempt(attempt.attempt_id, operatorId),
															)
														}
														className="rounded border border-amber-500/40 px-2 py-1 text-[10px] text-amber-200"
													>
														<RotateCcw className="mr-1 inline" size={10} />
														Classified retry
													</button>
													<span className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-400">
														credit intent:{" "}
														{attempt.credit_spend_intended ? "LIVE" : "NONE"}
													</span>
												</div>
											</div>
										))}
									</div>
								)}
								{activeView === "qa" && (
									<div data-testid="p6-qa-list" className="space-y-2">
										{detail.qa.length === 0 ? (
											<div className="rounded border border-dashed border-slate-700 p-5 text-center text-xs text-slate-500">
												No registered output awaits QA.
											</div>
										) : (
											detail.qa.map((row, index) => (
												<details
													key={String(row.qa_id ?? index)}
													className="rounded border border-slate-800 bg-slate-900 text-[10px] text-slate-300"
												>
													<summary className="cursor-pointer px-3 py-2 font-mono text-slate-400 hover:text-slate-200">
														QA {String(row.qa_id ?? index)}
													</summary>
													<pre className="overflow-auto px-3 pb-3 text-slate-300">
														{JSON.stringify(row, null, 2)}
													</pre>
												</details>
											))
										)}
									</div>
								)}
							</section>

							{lastEvidence && (
								<details className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
									<summary className="cursor-pointer text-xs font-semibold text-slate-300">
										Last API evidence
									</summary>
									<pre className="mt-3 max-h-80 overflow-auto rounded bg-black/40 p-3 text-[10px] text-slate-400">
										{lastEvidence}
									</pre>
								</details>
							)}
						</>
					)}

					<div className="flex items-start gap-2 rounded-xl border border-amber-500/20 bg-amber-950/20 p-3 text-xs text-amber-200/80">
						<AlertTriangle className="mt-0.5 shrink-0" size={15} />
						<div>
							Older Batch Prompt Builder, Production Queue and RPA Studio
							records remain available for history. Use Production Studio for
							current plans.
						</div>
					</div>
					<div className="flex items-center gap-2 text-[10px] text-slate-600">
						<Clock3 size={11} />
						Capacity is an estimate, not a guarantee. One verified video lane
						handles one job at a time.
					</div>
					</main>
				</div>
				</div>,
					)}
				</div>

				{useV4 ? (
					<aside className="w-full 2xl:w-80 2xl:flex-none">
						<div className="2xl:sticky 2xl:top-4">
							<ResultsSidebar
								results={sessionResults}
								generating={
									Boolean(busy) || detail?.plan.status === "RUNNING"
								}
								mediaKind="video"
								libraryHref="/library/videos"
							/>
						</div>
					</aside>
				) : null}
			</div>
		</div>
	);
}
