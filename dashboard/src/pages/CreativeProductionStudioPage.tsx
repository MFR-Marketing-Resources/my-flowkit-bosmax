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
import { useCallback, useEffect, useMemo, useState } from "react";
import {
	approveProductionPlan,
	assignProductionWaves,
	type CapacityPreflight,
	type CohortAuthority,
	compileProductionPlan,
	controlProductionPlan,
	createProductionPlan,
	decideItemQa,
	dryRunProductionPlan,
	type ExecutionLane,
	fetchCohortAuthority,
	fetchGovernedPoolAuthority,
	fetchProductionPlan,
	type GenerationAttempt,
	type GovernedPoolAuthority,
	listExecutionLanes,
	listProductionPlans,
	materializeContentMatrix,
	P6_LIVE_CONFIRMATION,
	type PlanDetail,
	type ProductionPlan,
	type ProductVideoAllocation,
	preflightProductionPlan,
	reconcileAttempt,
	retryAttempt,
	startProductionPlan,
} from "../api/creativeProduction";
import { fetchVideoModels, type VideoModelInfo } from "../api/productionQueue";
import CreativeSupplyFactoryPanel from "../components/CreativeSupplyFactoryPanel";
import ProductAllocationPicker from "../components/production-studio/ProductAllocationPicker";

const splitValues = (value: string) =>
	value
		.split(/[\n,]/)
		.map((item) => item.trim())
		.filter(Boolean);

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
		return "An approved scene strategy or scene asset is required. Open Scene Registry to resolve it.";
	}
	if (/CAPACITY/.test(code)) {
		return "This product does not have enough unique approved material for the requested quantity. Reduce quantity or add approved supply.";
	}
	if (/MODEL|DURATION/.test(code)) {
		return "The selected model and duration are not a governed combination. Choose an available duration.";
	}
	return "This product needs additional governed production authority before it can proceed.";
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
	{ id: 1, label: "Products", desc: "Select & quantity" },
	{ id: 2, label: "Video Setup", desc: "Mode & duration" },
	{ id: 3, label: "Preflight", desc: "Capacity check" },
	{ id: 4, label: "Matrix & Compile", desc: "0 credits" },
	{ id: 5, label: "Waves & Dry Run", desc: "0 credits" },
	{ id: 6, label: "Generate", desc: "Spends credits" },
];

export default function CreativeProductionStudioPage() {
	const [cohort, setCohort] = useState<CohortAuthority | null>(null);
	const [plans, setPlans] = useState<ProductionPlan[]>([]);
	const [selectedPlanId, setSelectedPlanId] = useState("");
	const [detail, setDetail] = useState<PlanDetail | null>(null);
	const [lanes, setLanes] = useState<ExecutionLane[]>([]);
	const [liveExecutionCertified, setLiveExecutionCertified] = useState(false);
	const [poolAuthority, setPoolAuthority] =
		useState<GovernedPoolAuthority | null>(null);
	const [poolAuthorityLoading, setPoolAuthorityLoading] = useState(false);
	const [preflight, setPreflight] = useState<CapacityPreflight | null>(null);
	const [busy, setBusy] = useState("");
	const [error, setError] = useState("");
	const [lastEvidence, setLastEvidence] = useState("");
	const [livePhrase, setLivePhrase] = useState("");
	const [operatorId, setOperatorId] = useState("p6-production-operator");
	const [allocations, setAllocations] = useState<ProductVideoAllocation[]>([]);
	const [videoModels, setVideoModels] = useState<VideoModelInfo[]>([]);
	const [modelRegistryError, setModelRegistryError] = useState("");
	const [activeView, setActiveView] = useState<"matrix" | "attempts" | "qa">(
		"matrix",
	);
	const [form, setForm] = useState({
		name: "Daily governed creative plan",
		campaignKey: "",
		imageCount: 0,
		posterCount: 0,
		windowHours: 12,
		logicalMode: "T2V" as "T2V" | "HYBRID" | "F2V" | "I2V",
		modelKey: "",
		durationSeconds: 8,
		aspect: "9:16" as "9:16" | "16:9",
		copySetIds: "",
		posterCopySetIds: "",
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

	const refresh = useCallback(
		async (preferredPlanId?: string) => {
			const [authority, planList, laneList] = await Promise.all([
				fetchCohortAuthority(),
				listProductionPlans(),
				listExecutionLanes(),
			]);
			setCohort(authority);
			setPlans(planList.plans);
			setLanes(laneList.lanes);
			setLiveExecutionCertified(laneList.live_execution_certified);
			const nextPlanId =
				preferredPlanId || selectedPlanId || planList.plans[0]?.plan_id || "";
			if (nextPlanId) {
				setSelectedPlanId(nextPlanId);
				const fetchedDetail = await fetchProductionPlan(nextPlanId);
				setDetail(fetchedDetail);
				if (fetchedDetail?.plan) {
					const plan = fetchedDetail.plan;
					const planModelKey =
						plan.model_key ||
						(Array.isArray((plan as unknown as Record<string, unknown>).model_keys)
							? (plan as unknown as { model_keys: string[] }).model_keys[0]
							: "") ||
						"";
					const planDuration =
						typeof plan.duration_seconds === "number"
							? plan.duration_seconds
							: Array.isArray(
										(plan as unknown as Record<string, unknown>).duration_seconds,
									)
								? (plan as unknown as { duration_seconds: number[] }).duration_seconds[0]
								: 8;

					const planAllocations =
						Array.isArray(plan.allocations) && plan.allocations.length > 0
							? plan.allocations
							: Array.isArray(plan.product_scope) && plan.product_scope.length > 0
								? plan.product_scope.map((id) => ({
										product_id: id,
										video_count: Math.max(
											1,
											Math.floor(
												(plan.target_video_count || plan.product_scope.length) /
													plan.product_scope.length,
											),
										),
									}))
								: [];

					setAllocations(planAllocations);
					setForm((current) => ({
						...current,
						name: plan.name,
						logicalMode: (plan.logical_mode as "T2V" | "HYBRID" | "F2V" | "I2V") || "T2V",
						modelKey: planModelKey || current.modelKey,
						durationSeconds: planDuration || current.durationSeconds,
						aspect: ((plan.aspect_ratio || (plan.execution_policy?.aspect as string)) as "9:16" | "16:9") || "9:16",
					}));
				}
			} else {
				setDetail(null);
			}
		},
		[selectedPlanId],
	);

	useEffect(() => {
		void refresh().catch((reason) => setError(String(reason)));
	}, [refresh]);

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
						: "Canonical model registry unavailable.",
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
	const blockersByProduct = useMemo(() => {
		const result: Record<string, string> = {};
		for (const blocker of poolAuthority?.blockers ?? []) {
			const productId = String(blocker.product_id ?? "");
			if (productId && !result[productId]) {
				result[productId] = blockerMessage(technicalCode(blocker));
			}
		}
		return result;
	}, [poolAuthority]);
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
			setLastEvidence(JSON.stringify(evidence, null, 2));
			await refresh(selectedPlanId);
		} catch (reason) {
			setError(reason instanceof Error ? reason.message : String(reason));
		} finally {
			setBusy("");
		}
	};

	const create = async () => {
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
			pools: {
				copy_set_ids: splitValues(form.copySetIds),
				poster_copy_set_ids: splitValues(form.posterCopySetIds),
				avatar_codes: splitValues(form.avatarCodes),
				product_reference_asset_ids: splitValues(form.productReferenceAssetIds),
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

	const getPlanAllocations = useCallback(
		(planObj: Record<string, unknown>): ProductVideoAllocation[] => {
			if (Array.isArray(planObj.allocations) && planObj.allocations.length > 0) {
				return planObj.allocations as ProductVideoAllocation[];
			}
			if (
				Array.isArray(planObj.product_scope) &&
				planObj.product_scope.length > 0
			) {
				const scope = planObj.product_scope as string[];
				const totalVids = (planObj.target_video_count as number) || scope.length;
				const perProd = Math.max(1, Math.floor(totalVids / scope.length));
				return scope.map((id) => ({
					product_id: id,
					video_count: perProd,
				}));
			}
			return [];
		},
		[],
	);

	const isDraftMismatched = useMemo(() => {
		if (!detail?.plan) return false;
		const plan = detail.plan;
		const formProdCount = allocations.length;
		const planAllocations = getPlanAllocations(
			plan as unknown as Record<string, unknown>,
		);
		if (formProdCount !== planAllocations.length) return true;

		const formProductIds = allocations
			.map((a) => a.product_id)
			.sort()
			.join(",");
		const planProductIds = planAllocations
			.map((a) => a.product_id)
			.sort()
			.join(",");
		if (formProductIds !== planProductIds) return true;

		const formTotalVideos = allocations.reduce(
			(sum, a) => sum + a.video_count,
			0,
		);
		const planTotalVideos =
			planAllocations.reduce((sum, a) => sum + a.video_count, 0) ||
			plan.target_video_count;
		if (formTotalVideos !== planTotalVideos) return true;

		if (form.logicalMode !== plan.logical_mode) return true;

		const planModelKey =
			plan.model_key ||
			(Array.isArray((plan as unknown as Record<string, unknown>).model_keys)
				? (plan as unknown as { model_keys: string[] }).model_keys[0]
				: "") ||
			"";
		const normalizeKey = (k: string) => k.toLowerCase().replace(/[^a-z0-9]/g, "");
		if (planModelKey && normalizeKey(form.modelKey) !== normalizeKey(planModelKey))
			return true;

		const planDuration =
			typeof plan.duration_seconds === "number"
				? plan.duration_seconds
				: Array.isArray(
							(plan as unknown as Record<string, unknown>).duration_seconds,
						)
					? (plan as unknown as { duration_seconds: number[] }).duration_seconds[0]
					: 8;
		if (planDuration && Number(selectedDuration) !== planDuration) return true;

		return false;
	}, [
		detail,
		allocations,
		form.logicalMode,
		form.modelKey,
		selectedDuration,
		getPlanAllocations,
	]);

	const syncFormToActivePlan = useCallback(() => {
		if (!detail?.plan) return;
		const plan = detail.plan;
		const planModelKey =
			plan.model_key ||
			(Array.isArray((plan as unknown as Record<string, unknown>).model_keys)
				? (plan as unknown as { model_keys: string[] }).model_keys[0]
				: "") ||
			"";
		const planDuration =
			typeof plan.duration_seconds === "number"
				? plan.duration_seconds
				: Array.isArray(
							(plan as unknown as Record<string, unknown>).duration_seconds,
						)
					? (plan as unknown as { duration_seconds: number[] }).duration_seconds[0]
					: 8;

		setAllocations(
			getPlanAllocations(plan as unknown as Record<string, unknown>),
		);
		setForm((current) => ({
			...current,
			name: plan.name,
			logicalMode: (plan.logical_mode as "T2V" | "HYBRID" | "F2V" | "I2V") || "T2V",
			modelKey: planModelKey || current.modelKey,
			durationSeconds: planDuration || current.durationSeconds,
			aspect: ((plan.aspect_ratio || (plan.execution_policy?.aspect as string)) as "9:16" | "16:9") || "9:16",
		}));
	}, [detail, getPlanAllocations]);

	const switchToNewDraft = useCallback(() => {
		setSelectedPlanId("");
		setDetail(null);
		setPreflight(null);
	}, []);

	const selectedPlan = detail?.plan;
	const actionDisabled = !selectedPlan || Boolean(busy) || isDraftMismatched;
	const liveEnabled =
		liveExecutionCertified &&
		selectedPlan?.status === "SCHEDULED" &&
		livePhrase === P6_LIVE_CONFIRMATION &&
		!busy &&
		!isDraftMismatched;

	const liveDisabledReason = useMemo(() => {
		if (isDraftMismatched) {
			return "Form draft differs from active plan snapshot. Sync form or start new draft to authorize.";
		}
		if (!liveExecutionCertified) {
			return "Runtime live-execution certification is absent.";
		}
		if (selectedPlan?.status !== "SCHEDULED") {
			return `Plan must be in SCHEDULED status before live execution (current status: ${selectedPlan?.status || "NONE"}).`;
		}
		if (livePhrase !== P6_LIVE_CONFIRMATION) {
			return `Confirmation phrase does not match. Type exact phrase: ${P6_LIVE_CONFIRMATION}`;
		}
		if (busy) {
			return "Action in progress...";
		}
		return "All safety gates must pass before live dispatch.";
	}, [isDraftMismatched, liveExecutionCertified, selectedPlan, livePhrase, busy]);

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

	const primaryActionConfig = useMemo(() => {
		if (isDraftMismatched && selectedPlan) {
			return {
				step: activeStep,
				title: "Draft Configuration Mismatch",
				subtitle: `Current form draft differs from active selected plan (${selectedPlan.name}).`,
				buttonLabel: "Form Mismatched",
				buttonTestId: "p6-primary-action",
				actionName: "mismatch",
				executeAction: async () => {},
				disabled: true,
				disabledReason:
					"Form draft differs from active plan snapshot. Sync form to plan or create a new plan draft.",
				isCreditSpend: false,
			};
		}

		if (!detail?.plan) {
			return {
				step: 1,
				title: "Create Production Plan",
				subtitle:
					"Persist durable plan configuration and product allocations.",
				buttonLabel:
					busy === "create" ? "Persisting plan…" : "Create durable plan",
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
					!form.modelKey ||
					!selectedDuration ||
					Boolean(modelRegistryError) ||
					!operatorId.trim() ||
					Boolean(poolAuthority?.blockers.length) ||
					!form.name,
				disabledReason: !cohort?.matches_frozen_authority
					? "Cohort authority check required"
					: !allocations.length
						? "Select at least one product"
						: invalidAllocation
							? "Product quantities must be between 1 and 200"
							: poolAuthorityLoading
								? "Loading governed supply..."
								: poolAuthority?.blockers.length
									? "Governed pool blockers must be resolved"
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
				disabledReason: busy ? "Action in progress..." : "Select or resume plan",
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
				disabledReason: busy ? "Action in progress..." : "Select or resume plan",
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
				disabledReason: busy ? "Action in progress..." : "Select or resume plan",
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
				executeAction: () => dryRunProductionPlan(planId, operatorId),
				disabled: actionDisabled,
				disabledReason: busy ? "Action in progress..." : "Select or resume plan",
				isCreditSpend: false,
			};
		}

		if (status === "SCHEDULED") {
			const videoCount = detail.plan.target_video_count || totalVideoCount || 1;
			return {
				step: 6,
				title: `Authorize and Generate ${videoCount} Video${videoCount === 1 ? "" : "s"}`,
				subtitle:
					"Separately authorized live generation action. This action WILL spend media credits.",
				buttonLabel:
					busy === "live"
						? "Dispatching live job…"
						: `Authorize & generate ${videoCount} video${videoCount === 1 ? "" : "s"}`,
				buttonTestId: "p6-primary-action",
				actionName: "live",
				executeAction: () =>
					startProductionPlan(planId, operatorId, livePhrase),
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
	}, [
		detail,
		busy,
		cohort,
		allocations,
		invalidAllocation,
		poolAuthorityLoading,
		poolAuthority,
		form,
		selectedDuration,
		modelRegistryError,
		operatorId,
		totalVideoCount,
		actionDisabled,
		liveEnabled,
		liveExecutionCertified,
		livePhrase,
		create,
		isDraftMismatched,
		selectedPlan,
		activeStep,
	]);

	return (
		<div className="mx-auto max-w-[1680px] space-y-4 p-4 text-slate-100">
			<header className="rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-950 via-slate-950 to-cyan-950/30 p-5 shadow-2xl">
				<div className="flex flex-wrap items-start justify-between gap-4">
					<div>
						<div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-300">
							<ShieldCheck size={15} />
							P6 · Sovereign production control plane
						</div>
						<h1 className="text-2xl font-bold tracking-tight">
							Batch Creative Production Orchestrator
						</h1>
						<p className="mt-2 max-w-3xl text-sm text-slate-400">
							Durable plan → capacity → DNA matrix → compile → approve → waves →
							dry-run → separately authorized execution → QA. Planning never
							spends media credits.
						</p>
					</div>
					<div className="grid min-w-[320px] grid-cols-2 gap-2">
						<Metric
							label="Frozen P5.8 cohort"
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
								? "PRODUCT AUTHORITY READY"
								: "PRODUCT AUTHORITY CHECK REQUIRED"
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
						<summary className="cursor-pointer">Technical authority</summary>
						<div className="mt-2 font-mono">
							Cohort SHA: {cohort?.cohort_sha256 ?? "loading"}
						</div>
					</details>
				</div>
			</header>

			<details
				data-testid="p7-compact-summary"
				className="rounded-2xl border border-violet-500/30 bg-slate-950/80 p-4"
			>
				<summary className="cursor-pointer list-none">
					<div className="flex items-center justify-between gap-3">
						<div>
							<div className="text-xs font-semibold uppercase tracking-[0.16em] text-violet-300">
								Creative supply
							</div>
							<div className="mt-1 text-sm text-slate-300">
								P7 governed supply remains available when more approved variants
								are needed.
							</div>
						</div>
						<span className="shrink-0 text-xs font-semibold text-violet-200">
							View details
						</span>
					</div>
				</summary>
				<div className="mt-4">
					<CreativeSupplyFactoryPanel />
				</div>
			</details>

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
							Active Production Plan Selection
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
									setSelectedPlanId(nextId);
									void refresh(nextId);
								}
							}}
							className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-white outline-none focus:border-cyan-500 max-w-xs truncate"
						>
							<option value="">+ Create New Production Plan Draft</option>
							{plans.map((p) => (
								<option key={p.plan_id} value={p.plan_id}>
									{p.name} ({p.status} · {p.target_video_count} vids)
								</option>
							))}
						</select>
						<button
							type="button"
							onClick={switchToNewDraft}
							className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 shrink-0"
						>
							New Draft
						</button>
					</div>
				</div>

				{selectedPlan ? (
					<div className="mt-3 border-t border-cyan-500/20 pt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
						<div>
							<span className="font-bold text-white">{selectedPlan.name}</span>{" "}
							<span className="font-mono text-[10px] text-slate-400">
								({selectedPlan.plan_id})
							</span>
							<div className="mt-0.5 text-[11px] text-cyan-300">
								Active Plan Snapshot: {selectedPlan.target_video_count} video
								{selectedPlan.target_video_count === 1 ? "" : "s"} across{" "}
								{getPlanAllocations(selectedPlan as unknown as Record<string, unknown>).length} product
								{getPlanAllocations(selectedPlan as unknown as Record<string, unknown>).length === 1 ? "" : "s"} ·{" "}
								{selectedPlan.logical_mode} · {selectedPlan.model_key || selectedPlan.model_keys?.[0] || ""} ·{" "}
								{typeof selectedPlan.duration_seconds === "number"
									? selectedPlan.duration_seconds
									: (selectedPlan.duration_seconds?.[0] ?? 8)}s (
								{(typeof selectedPlan.duration_seconds === "number"
									? selectedPlan.duration_seconds
									: (selectedPlan.duration_seconds?.[0] ?? 8)) > 10
									? "EXTEND"
									: "SINGLE"}) ·{" "}
								{selectedPlan.aspect_ratio || (selectedPlan.execution_policy?.aspect as string) || "9:16"}
							</div>
						</div>
						<div className="flex items-center gap-2">
							<StatusBadge status={selectedPlan.status} />
							{isDraftMismatched ? (
								<button
									type="button"
									onClick={syncFormToActivePlan}
									className="rounded bg-cyan-600/30 hover:bg-cyan-600/50 border border-cyan-500/50 px-2.5 py-1 text-[11px] font-semibold text-cyan-100"
								>
									Sync Form to Active Plan
								</button>
							) : null}
						</div>
					</div>
				) : (
					<div className="mt-2 text-xs text-slate-400">
						Editing a new plan draft. Configure products, video settings, and
						click "Create durable plan" below.
					</div>
				)}
			</section>

			<div className="grid gap-6 2xl:grid-cols-[420px_minmax(0,1fr)]">
				<aside className="space-y-4">
					{isDraftMismatched && selectedPlan ? (
						<div
							data-testid="p6-draft-mismatch-warning"
							className="rounded-2xl border border-amber-500/50 bg-amber-950/40 p-4 text-xs text-amber-200 space-y-2.5"
						>
							<div className="flex items-center gap-2 font-bold text-amber-300 text-sm">
								<AlertTriangle size={17} className="shrink-0 text-amber-400" />
								Form draft differs from active plan ({selectedPlan.name})
							</div>
							<p className="text-[11px] leading-relaxed text-amber-200/80">
								Form edits do not modify the active plan snapshot. Workflow actions and live dispatch are disabled to prevent state mismatch.
							</p>
							<div className="flex flex-wrap gap-2 pt-1">
								<button
									type="button"
									onClick={syncFormToActivePlan}
									className="rounded-lg bg-amber-500/30 hover:bg-amber-500/50 border border-amber-500/50 px-3 py-1.5 text-xs font-semibold text-amber-100 transition"
								>
									Sync Form to Active Plan
								</button>
								<button
									type="button"
									onClick={switchToNewDraft}
									className="rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 px-3 py-1.5 text-xs font-semibold text-slate-200 transition"
								>
									Start New Plan Draft
								</button>
							</div>
						</div>
					) : null}

					<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
						<div className="mb-3 flex items-center gap-2">
							<WandSparkles size={16} className="text-cyan-300" />
							<h2 className="font-semibold">Create governed plan</h2>
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
									allocations={allocations}
									onChange={setAllocations}
									blockersByProduct={blockersByProduct}
									loading={!cohort}
									error={
										cohort || !error
											? ""
											: "Governed product authority unavailable."
									}
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
											<option key={model.key} value={model.key}>
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
											<option key={option.seconds} value={option.seconds}>
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
											? "Compile creates a reviewed multi-block plan and durable /video-jobs identity. Final concat occurs only after separate live authorization."
											: "One governed provider job after separate live authorization."}
									</div>
								</div>
							) : null}
							{modelRegistryError ? (
								<div className="rounded-lg border border-rose-500/30 bg-rose-950/30 p-2 text-xs text-rose-200">
									The canonical model registry is unavailable. Plan creation is
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
											key: "copySetIds",
											label: "COPY_APPROVED Copy Sets",
											options: poolAuthority?.copy_sets ?? [],
											valueKey: "copy_set_id",
											labelKeys: ["angle", "hook"],
										},
										{
											key: "posterCopySetIds",
											label: "POSTER_COPY_APPROVED Copy Sets",
											options: poolAuthority?.poster_copy_sets ?? [],
											valueKey: "poster_copy_set_id",
											labelKeys: ["headline", "cta"],
										},
										{
											key: "avatarCodes",
											label: "Product-first approved avatars",
											options: poolAuthority?.avatar_profiles ?? [],
											valueKey: "avatar_code",
											labelKeys: ["character_name", "variant"],
										},
										{
											key: "productReferenceAssetIds",
											label: "Product reference assets",
											options: poolAuthority?.product_reference_assets ?? [],
											valueKey: "asset_id",
											labelKeys: ["name", "semantic_role"],
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
									].map(({ key, label, options, valueKey, labelKeys }) => (
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
									))}
									{poolAuthority?.blockers.length ? (
										<div
											data-testid="p6-pool-authority-blockers"
											className="rounded-lg border border-amber-500/30 bg-amber-950/20 p-2 text-xs text-amber-100"
										>
											{poolAuthority.blockers.length} governed pool blocker(s).
											The server will fail closed until they are resolved.
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
													controlledReuseMaxPerDna: Number(event.target.value),
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
									!form.modelKey ||
									!selectedDuration ||
									Boolean(modelRegistryError) ||
									!operatorId.trim() ||
									Boolean(poolAuthority?.blockers.length) ||
									!form.name
								}
								onClick={() => void execute("create", create)}
								className="rounded-lg bg-cyan-600 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-700"
							>
								{busy === "create" ? "Persisting…" : "Create durable plan"}
							</button>
						</div>
					</section>

					<section className="rounded-2xl border border-slate-800 bg-slate-950/80 p-4">
						<div className="mb-3 flex items-center justify-between">
							<h2 className="font-semibold">Production plans</h2>
							<button
								type="button"
								aria-label="Refresh production plans"
								onClick={() => void execute("refresh", () => refresh())}
								className="rounded border border-slate-700 p-1.5 text-slate-300 hover:bg-slate-800"
							>
								<RefreshCw size={14} />
							</button>
						</div>
						<div className="max-h-72 space-y-2 overflow-auto">
							{plans.length === 0 && (
								<div
									data-testid="p6-empty-plans"
									className="rounded-lg border border-dashed border-slate-700 p-4 text-center text-xs text-slate-500"
								>
									No P6 plan yet.
								</div>
							)}
							{plans.map((plan) => (
								<button
									key={plan.plan_id}
									type="button"
									onClick={() =>
										void execute("select", async () => {
											setSelectedPlanId(plan.plan_id);
											setDetail(await fetchProductionPlan(plan.plan_id));
										})
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
								</button>
							))}
						</div>
					</section>
				</aside>

				<main className="min-w-0 space-y-4">
					{!detail ? (
						<div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/60 p-12 text-center text-slate-500">
							<Database className="mx-auto mb-3" />
							Create or select a durable P6 production plan.
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
												dryRunProductionPlan(detail.plan.plan_id, operatorId),
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
												Live execution — separately authorized boundary
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
												? "Runtime live-execution certification is present. Dispatch still requires a scheduled plan, the exact confirmation phrase, a matching dry-run proof, and a verified lane. Entering the phrase and requesting dispatch explicitly authorizes credit-spending media generation."
												: "Runtime live-execution certification is absent. The exact confirmation phrase cannot bypass the server gate."}
										</p>

										{!liveEnabled && liveDisabledReason ? (
											<div
												data-testid="p6-live-disabled-reason"
												className="mt-2.5 flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-950/30 p-2.5 text-xs text-amber-200 font-medium"
											>
												<AlertTriangle size={15} className="shrink-0 text-amber-400" />
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
														),
													)
												}
												className="rounded-lg bg-rose-600 px-4 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-700 hover:bg-rose-500 transition"
											>
												{liveEnabled
													? `Authorize & Start Production — ${selectedPlan?.target_video_count || totalVideoCount} Videos`
													: "Request live production dispatch"}
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
												No attempt yet. Dry run creates a durable NOT_SUBMITTED
												attempt without spending credits.
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
												<pre
													key={String(row.qa_id ?? index)}
													className="overflow-auto rounded border border-slate-800 bg-slate-900 p-3 text-[10px] text-slate-300"
												>
													{JSON.stringify(row, null, 2)}
												</pre>
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
							Legacy Batch Prompt Builder, Production Queue and RPA Studio
							remain compatibility surfaces only. The unified P6 plan is the new
							operator authority; legacy schema is not deleted in this patch.
						</div>
					</div>
					<div className="flex items-center gap-2 text-[10px] text-slate-600">
						<Clock3 size={11} />
						Capacity is a measured objective, never an SLA. One verified video
						lane defaults to one inflight job.
					</div>
				</main>
			</div>
		</div>
	);
}
