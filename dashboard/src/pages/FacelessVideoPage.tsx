/**
 * Faceless Video operator lane (V4 language).
 *
 * Hybrid product path WITHOUT avatar / visible face.
 * Operator: Product → Copy Authority → Opening Strategy → Background →
 * Single|Extend → Model → Duration → Prepare → Generate
 * Internal: F2V + HYBRID product-anchor. Native-extend after base for EXTEND.
 * Never auto-fires credit-bearing generation.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { FinalPromptApprovalModal } from "../components/execution-approval/FinalPromptApprovalModal";
import type { ReviewEnvelope } from "../api/executionApproval";
import {
	prepareFacelessPackage,
	useCreativeLaneSettings,
	type ResolvedLaneSetting,
} from "../api/creativeLaneSettings";
import {
	fetchVideoModels,
	type VideoModelInfo,
} from "../api/productionQueue";
import {
	ResolvedChip,
	WorkflowStep,
	type WorkflowStepStatus,
} from "../components/workflow";
import ResultsSidebar, { type SessionResult } from "../components/workspace/ResultsSidebar";
import NativeExtendPanel from "../components/NativeExtendPanel";
import StaffIdentityBar from "../components/StaffIdentityBar";
import CopyArchitectureV2LaneCard from "../components/copywriting/CopyArchitectureV2LaneCard";
import CopywritingSourceSelector from "../components/copywriting/CopywritingSourceSelector";
import BenefitCopySourceSection, {
	type BenefitCopyExecutionContext,
} from "../components/copywriting/BenefitCopySourceSection";
import { benefitCopyRequestContext } from "../utils/benefitCopyRequestContext";
import CanonicalReferenceBindingControls, {
	EMPTY_BINDING,
	type CanonicalReferenceBinding,
} from "../components/workspace/CanonicalReferenceBindingControls";
import { useProductCatalog } from "../hooks/useProductCatalog";
import { useStaffIdentity } from "../hooks/useStaffIdentity";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { Product, WorkspaceExecutionPackage } from "../types";
import {
	buildFacelessGenerateBody,
	FACELESS_EXACT_ROUTE,
	FACELESS_VISUAL_LAW,
	facelessExactRoute,
	facelessExactRouteBlocker,
	facelessPrepareBlockers,
	optionLabel,
	type FacelessSceneMode,
} from "../faceless/facelessLane";
import {
	defaultEngine,
	getEngine,
	modelsForSingle,
	resolveDurationChange,
	resolveSingleSelection,
	singleDurations,
	type VideoCapabilityMatrix,
} from "../utils/videoCapability";
import { forgetGenerationJob, rememberGenerationJob } from "../utils/videoSessionResults";

type NoticeTone = "info" | "success" | "warning" | "error";

interface Notice {
	tone: NoticeTone;
	title: string;
	detail: string;
	requestId: string | null;
}

const selectClass =
	"w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100";
const labelClass = "text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500";

export default function FacelessVideoPage() {
	const { products, isLoadingProducts, productsError } = useProductCatalog(
		50,
		"GENERATION",
	);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const {
		settings,
		loading: settingsLoading,
		error: settingsError,
		available: settingsAvailable,
		reload: reloadSettings,
	} = useCreativeLaneSettings(selectedProduct?.id);
	const [resolvedHook, setResolvedHook] = useState<ResolvedLaneSetting | null>(null);
	const [resolvedBackground, setResolvedBackground] = useState<ResolvedLaneSetting | null>(
		null,
	);
	const [actorProfile, setActorProfile] = useState("AUTO");
	const [resolvedActorProfile, setResolvedActorProfile] = useState<Record<string, unknown> | null>(
		null,
	);
	const [hookId, setHookId] = useState("AUTO");
	const [backgroundId, setBackgroundId] = useState("AUTO");
	const [showAdvancedRef, setShowAdvancedRef] = useState(false);
	const [sessionResults, setSessionResults] = useState<SessionResult[]>([]);
	const [binding, setBinding] = useState<CanonicalReferenceBinding>(EMPTY_BINDING);

	const [sceneMode, setSceneMode] = useState<FacelessSceneMode>("SINGLE");
	const [capability, setCapability] = useState<VideoCapabilityMatrix | null>(null);
	const [capabilityError, setCapabilityError] = useState<string | null>(null);
	const [videoModels, setVideoModels] = useState<VideoModelInfo[]>([]);
	const [videoModel, setVideoModel] = useState("");
	const [durationSec, setDurationSec] = useState<number>(0);
	const [extendTotalSec, setExtendTotalSec] = useState<number | null>(null);

	const [workspacePackage, setWorkspacePackage] =
		useState<WorkspaceExecutionPackage | null>(null);
	const [v2CopyReady, setV2CopyReady] = useState(false);
	// Round 2: neutral copy-source selection (Faceless lane). BENEFIT_RENDER copy
	// readiness comes from a finalized rendered selection, never from v2CopyReady.
	const [selectedCopySource, setSelectedCopySource] = useState<"BENEFIT_RENDER" | "COPY_V2">("BENEFIT_RENDER");
	// Request-scoped Benefit On-Demand execution identity (BENEFIT_COPY_RENDER_V1).
	const [selectedBenefitCopy, setSelectedBenefitCopy] = useState<BenefitCopyExecutionContext | null>(null);
	const [benefitRenderReady, setBenefitRenderReady] = useState(false);
	const [isPreparing, setIsPreparing] = useState(false);
	const [isExecuting, setIsExecuting] = useState(false);
	const staffIdentity = useStaffIdentity();
	const [notice, setNotice] = useState<Notice | null>(null);
	const [completedUrl, setCompletedUrl] = useState<string | null>(null);
	const [v4Open, setV4Open] = useState<Record<number, boolean>>({});
	const executionInFlightRef = useRef(false);
	const pollTimerRef = useRef<number | null>(null);

	useEffect(() => {
		void fetch("/api/flow/video-capability-matrix")
			.then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
			.then((m: VideoCapabilityMatrix) => {
				setCapability(m);
				setCapabilityError(null);
			})
			.catch((err: unknown) => {
				setCapability(null);
				setCapabilityError(
					err instanceof Error
						? err.message
						: "Video capability authority unavailable",
				);
			});
		void fetchVideoModels()
			.then((res) => setVideoModels(res.models || []))
			.catch(() => setVideoModels([]));
	}, []);

	useEffect(() => {
		return () => {
			if (pollTimerRef.current != null) window.clearTimeout(pollTimerRef.current);
		};
	}, []);

	const engine = useMemo(() => {
		return getEngine(capability, "GOOGLE_FLOW") || defaultEngine(capability);
	}, [capability]);

	// SINGLE: keep model/duration valid via capability authority
	useEffect(() => {
		if (sceneMode !== "SINGLE" || !engine) return;
		const sel = resolveSingleSelection(engine, videoModel, durationSec);
		if (!sel) return;
		if (sel.model !== videoModel) setVideoModel(sel.model);
		if (sel.durationSeconds !== durationSec) setDurationSec(sel.durationSeconds);
	}, [sceneMode, engine]); // eslint-disable-line react-hooks/exhaustive-deps

	const singleDurationOptions = useMemo(
		() => singleDurations(engine),
		[engine],
	);
	const modelsAtDuration = useMemo(
		() => modelsForSingle(engine, durationSec),
		[engine, durationSec],
	);

	const selectedRegistryModel = useMemo(
		() => videoModels.find((m) => m.ui_label === videoModel) || null,
		[videoModels, videoModel],
	);
	const extendBaseDurationSec = selectedRegistryModel?.extend_block_duration_s ?? null;

	const extendTotals = useMemo(() => {
		const t = selectedRegistryModel?.extend_totals_s;
		return Array.isArray(t) ? [...t].filter((n) => n > 0).sort((a, b) => a - b) : [];
	}, [selectedRegistryModel]);

	const extendBlockedReason = useMemo(() => {
		if (sceneMode !== "EXTEND") return null;
		if (!videoModel) return "Select a model first.";
		if (extendTotals.length === 0) {
			return `${videoModel} has no proven Extend totals in the model authority. Choose another model or use Single.`;
		}
		if (!extendBaseDurationSec || extendBaseDurationSec <= 0) {
			return `${videoModel} has no proven Extend block duration in the model authority.`;
		}
		return null;
	}, [sceneMode, videoModel, extendTotals, extendBaseDurationSec]);

	useEffect(() => {
		if (sceneMode !== "EXTEND") return;
		if (extendTotals.length === 0) {
			setExtendTotalSec(null);
			return;
		}
		if (extendTotalSec == null || !extendTotals.includes(extendTotalSec)) {
			setExtendTotalSec(extendTotals[0]);
		}
	}, [sceneMode, extendTotals, extendTotalSec]);

	const referenceOverride = showAdvancedRef && Boolean(binding.startFrameAssetId);

	const blockers = useMemo(() => {
		const base = facelessPrepareBlockers({
			productId: selectedProduct?.id,
			model: videoModel,
			sceneMode,
			durationSeconds: sceneMode === "SINGLE" ? durationSec : extendBaseDurationSec,
			extendTotalSeconds: extendTotalSec,
			startFrameAssetId: binding.startFrameAssetId,
			referenceOverride: showAdvancedRef && !binding.startFrameAssetId ? true : referenceOverride && showAdvancedRef,
		});
		// Only require start frame when advanced open AND user turned on override path with empty binding
		const cleaned = base.filter((b) => {
			if (!showAdvancedRef && /Advanced override/i.test(b)) return false;
			return true;
		});
		// When advanced open but no frame selected, override is optional — strip advanced blocker unless they bound nothing while claiming override
		// Advanced is optional: never block product-first when advanced closed
		const advancedOnly = showAdvancedRef
			? facelessPrepareBlockers({
					productId: selectedProduct?.id,
					model: videoModel,
					sceneMode,
					durationSeconds: sceneMode === "SINGLE" ? durationSec : extendBaseDurationSec,
					extendTotalSeconds: extendTotalSec,
					// optional — do not require frame
			  })
			: cleaned;
		const out = showAdvancedRef ? advancedOnly : cleaned.filter((b) => !/Advanced/i.test(b));
		// rebuild clean product-first blockers
		const core = facelessPrepareBlockers({
			productId: selectedProduct?.id,
			model: videoModel,
			sceneMode,
			durationSeconds: sceneMode === "SINGLE" ? durationSec : extendBaseDurationSec,
			extendTotalSeconds: extendTotalSec,
		});
		const result = [...core];
		if (!settingsAvailable) {
			result.unshift("Opening Strategy/Background settings unavailable — retry when API is up");
		}
		if (!capability || !engine) {
			result.unshift(
				`Video capability authority unavailable${capabilityError ? `: ${capabilityError}` : ""} — no local model/duration fallback is allowed`,
			);
		}
		if (sceneMode === "SINGLE" && !modelsAtDuration.length) {
			result.unshift("No valid SINGLE model/duration tuple is available from the capability authority.");
		}
		if (extendBlockedReason) result.push(extendBlockedReason);
		if (selectedProduct && !v2CopyReady) {
			result.push("Copy Register V2 binding is not production-ready for Faceless.");
		}
		const exactBlocker = facelessExactRouteBlocker(workspacePackage);
		if (exactBlocker) result.push(`Exact product route blocked: ${exactBlocker}`);
		if (showAdvancedRef && binding.startFrameAssetId === "" && false) {
			/* advanced optional */
		}
		void out;
		return result;
	}, [
		selectedProduct?.id,
		videoModel,
		sceneMode,
		durationSec,
		extendBaseDurationSec,
		extendTotalSec,
		binding.startFrameAssetId,
		showAdvancedRef,
		referenceOverride,
		settingsAvailable,
		capability,
		capabilityError,
		engine,
		modelsAtDuration,
		extendBlockedReason,
		v2CopyReady,
		workspacePackage,
	]);

	const openingStrategyOptions =
		settings.opening_strategy?.options?.length
			? settings.opening_strategy.options
			: settings.hook.options;
	const hookLabel = optionLabel(openingStrategyOptions, hookId);
	const backgroundLabel = optionLabel(settings.background.options, backgroundId);
	const actorProfileOptions =
		settings.actor_profile?.options?.length
			? settings.actor_profile.options
			: [{ id: "AUTO", label: settings.auto.label }];
	const actorProfileLabel = optionLabel(actorProfileOptions, actorProfile);

	useEffect(() => {
		if (!settings.background.options.length) return;
		const validIds = new Set(settings.background.options.map((option) => option.id));
		if (!validIds.has(backgroundId)) {
			setBackgroundId("AUTO");
			setWorkspacePackage(null);
		}
	}, [settings.background.options, backgroundId]);

	useEffect(() => {
		if (!actorProfileOptions.length) return;
		const validIds = new Set(actorProfileOptions.map((option) => option.id));
		if (!validIds.has(actorProfile)) {
			setActorProfile("AUTO");
			setResolvedActorProfile(null);
			setWorkspacePackage(null);
		}
	}, [actorProfileOptions, actorProfile]);

	const durationLabel =
		sceneMode === "EXTEND"
			? extendTotalSec != null
				? `${extendTotalSec}s total`
				: "—"
			: durationSec > 0
				? `${durationSec}s`
				: "—";

	const v4IsOpen = (index: number, status: WorkflowStepStatus) =>
		v4Open[index] ?? status === "active";
	const v4Toggle = (index: number, currentOpen: boolean) =>
		setV4Open((prev) => ({ ...prev, [index]: !currentOpen }));

	const sProduct: WorkflowStepStatus = selectedProduct ? "done" : "active";
	const sCopy: WorkflowStepStatus = !selectedProduct ? "upcoming" : v2CopyReady ? "done" : "active";
	const sCreative: WorkflowStepStatus = selectedProduct
		? settingsAvailable
			? "done"
			: "active"
		: "upcoming";
	const sSettings: WorkflowStepStatus = !selectedProduct
		? "upcoming"
		: blockers.some((b) => /model|duration|Extend/i.test(b))
			? "active"
			: "done";
	const sPrepare: WorkflowStepStatus = workspacePackage
		? "done"
		: blockers.length === 0
			? "active"
			: "upcoming";
	const sGenerate: WorkflowStepStatus = workspacePackage ? "active" : "upcoming";

	const handlePrepare = async () => {
		if (!staffIdentity.hasStaff) {
			setNotice({
				tone: "warning",
				title: "Select staff before production",
				detail: "An active Staff Profile is required before preparing this production.",
				requestId: null,
			});
			return;
		}
		if (!selectedProduct || blockers.length) {
			setNotice({
				tone: "error",
				title: "Cannot prepare",
				detail: blockers[0] || "Missing required inputs",
				requestId: null,
			});
			return;
		}
		setIsPreparing(true);
		setNotice({
			tone: "info",
			title: "Preparing faceless package",
			detail: "Compiling through the shared workspace execution package path…",
			requestId: null,
		});
		try {
			const prepared = await prepareFacelessPackage({
				product_id: selectedProduct.id,
				hook_id: hookId,
				background_id: backgroundId,
				model: videoModel,
				generation_mode: sceneMode,
				duration_seconds:
					sceneMode === "SINGLE" ? durationSec : extendBaseDurationSec,
				total_duration_seconds: sceneMode === "EXTEND" ? extendTotalSec : null,
				start_frame_asset_id:
					showAdvancedRef && binding.startFrameAssetId
						? binding.startFrameAssetId
						: null,
				end_frame_asset_id:
					showAdvancedRef && binding.endFrameAssetId
						? binding.endFrameAssetId
						: null,
				copy_fallback_confirmed: false,
				copy_v2_context: benefitCopyRequestContext(selectedCopySource, selectedBenefitCopy) ?? { lane: "FACELESS" },
				actor_profile: actorProfile,
				staff_id: staffIdentity.staffId,
			});
			const pkg = (prepared.package || {}) as unknown as WorkspaceExecutionPackage;
			if (!pkg.workspace_execution_package_id || !pkg.prompt_text) {
				throw new Error("Prepare returned incomplete package");
			}
			setWorkspacePackage(pkg);
			setResolvedHook(prepared.resolution?.hook ?? null);
			setResolvedBackground(prepared.resolution?.background ?? null);
			setResolvedActorProfile(prepared.actor_profile ?? null);
			const h = prepared.resolution?.hook;
			const b = prepared.resolution?.background;
			setNotice({
				tone: "success",
				title: "Faceless package ready",
				detail:
					`${sceneMode} · ${videoModel} · ${durationLabel} · Opening Strategy ${h?.setting_id || hookId} · Background ${b?.setting_id || backgroundId}` +
					(facelessExactRoute(pkg) === FACELESS_EXACT_ROUTE
						? " · Product fidelity Exact product · Exact deterministic composite"
						: ""),
				requestId: pkg.workspace_execution_package_id,
			});
		} catch (err: unknown) {
			const detail = err instanceof Error ? err.message : "Failed to prepare package";
			const fidelityBlocked = /ERR_PRODUCT_FIDELITY_ROUTE_NOT_PROVEN|ERR_PRODUCT_VISUAL_CUSTODY_REQUIRED|ERR_OFFICIAL_PRODUCT_VISUAL/i.test(detail);
			setNotice({
				tone: "error",
				title: fidelityBlocked ? "BLOCKED: product fidelity route not proven" : "Prepare failed",
				detail,
				requestId: null,
			});
		} finally {
			setIsPreparing(false);
		}
	};

	const pollJob = async (jobId: string, requestId: string) => {
		try {
			const response = await fetch(`/api/flow/generate-job/${jobId}`);
			if (!response.ok) throw new Error(`Job HTTP ${response.status}`);
			const job = await response.json();
			const status = job.status as string;
			if (status === "DONE") {
				const mediaId = job.media_id ?? job.video_media_id ?? "";
				forgetGenerationJob(jobId);
				if (mediaId) setCompletedUrl(`/api/flow/retrieved/${mediaId}`);
				if (mediaId)
					setSessionResults((prev) => [{ media_id: mediaId, kind: "video" }, ...prev]);
				setNotice({
					tone: "success",
					title:
						sceneMode === "EXTEND"
							? "Base clip done — continue via native-extend for total duration"
							: "Faceless clip done",
					detail: `Saved ${job.size_mb ?? "?"}MB · media ${mediaId}`,
					requestId,
				});
				setIsExecuting(false);
				executionInFlightRef.current = false;
				return;
			}
			if (
				[
					"FAILED",
					"REJECTED",
					"PRODUCT_FIDELITY_REVIEW_REQUIRED",
					"GENERATED_BUT_UNRETRIEVED",
					"RENDER_NOT_MATERIALIZED",
					"STALE_OR_FOREIGN_CANDIDATES_ONLY",
				].includes(status)
			) {
				forgetGenerationJob(jobId);
				setNotice({
					tone: "error",
					title: "Faceless generation failed",
					detail: job.error || job.original_error || status,
					requestId,
				});
				setIsExecuting(false);
				executionInFlightRef.current = false;
				return;
			}
			pollTimerRef.current = window.setTimeout(() => {
				void pollJob(jobId, requestId);
			}, 2500);
		} catch (err: unknown) {
			setNotice({
				tone: "error",
				title: "Poll failed",
				detail: err instanceof Error ? err.message : "Job poll error",
				requestId,
			});
			setIsExecuting(false);
			executionInFlightRef.current = false;
		}
	};

	const [pendingApproval, setPendingApproval] = useState<ReviewEnvelope | null>(null);

	const handleGenerate = async (approved = false, approvedPrompt?: string) => {
		if (!staffIdentity.hasStaff) {
			setNotice({
				tone: "warning",
				title: "Select staff before production",
				detail: "An active Staff Profile is required before generating this production.",
				requestId: null,
			});
			return;
		}
		if (sceneMode === "EXTEND") {
			setNotice({
				tone: "info",
				title: "Use the full-video plan",
				detail: "Faceless Extend is owned by the durable video-job lifecycle below.",
				requestId: null,
			});
			return;
		}
		if (executionInFlightRef.current) return;
		if (!workspacePackage?.prompt_text) {
			setNotice({
				tone: "warning",
				title: "Prepare first",
				detail: "Prepare the faceless package before generating.",
				requestId: null,
			});
			return;
		}
		if (blockers.length) {
			setNotice({
				tone: "error",
				title: "Blocked",
				detail: blockers[0],
				requestId: null,
			});
			return;
		}
		executionInFlightRef.current = true;
		setIsExecuting(true);
		setCompletedUrl(null);
		const requestId = `faceless_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
		setNotice({
			tone: "info",
			title: "Submitting faceless clip",
			detail: "One-door generate — spends credits. Needs open Flow editor.",
			requestId,
		});
		try {
			const generateBody = buildFacelessGenerateBody({
				prompt: approvedPrompt ?? workspacePackage.prompt_text,
				productId: selectedProduct?.id ?? workspacePackage.product_id,
				workspacePackage,
				startFrameAssetId:
					showAdvancedRef && binding.startFrameAssetId
						? binding.startFrameAssetId
						: null,
				endFrameAssetId:
					showAdvancedRef && binding.endFrameAssetId
						? binding.endFrameAssetId
						: null,
				model: videoModel,
				durationSeconds: durationSec,
				sceneMode,
				extendTotalSeconds: extendTotalSec,
			});
			const attributedGenerateBody = {
				...generateBody,
				staff_id: staffIdentity.staffId,
				production_recipe: "FACELESS" as const,
			};
			if (!approved) {
				// Final Prompt Approval Gate: review the EXACT provider-ready body
				// before spending a credit. The envelope is built from generateBody so
				// the dispatch envelope matches the approval. On approve, re-fire with
				// the approved (possibly edited) prompt.
				executionInFlightRef.current = false;
				setIsExecuting(false);
				const gb = attributedGenerateBody as {
					mode?: string;
					prompt?: string;
					aspect?: string;
					product_id?: string | null;
					source_mode?: string;
					model?: string;
					duration_s?: number;
					image_media_ids?: string[];
					execution_identity?: Record<string, unknown> | null;
				};
				setPendingApproval({
					surface: "faceless",
					logical_mode: String(
						gb.mode ??
							(facelessExactRoute(workspacePackage) === FACELESS_EXACT_ROUTE
								? "T2V"
								: "F2V"),
					),
					final_prompt_text: String(gb.prompt ?? ""),
					product_id: gb.product_id ?? null,
					source_mode: gb.source_mode ?? null,
					model: gb.model ?? null,
					aspect: gb.aspect ?? null,
					duration_s: gb.duration_s ?? null,
					count: 1,
					asset_media_ids: gb.image_media_ids ?? [],
					execution_identity: gb.execution_identity ?? null,
				});
				return;
			}
			const response = await fetch("/api/flow/generate", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ ...attributedGenerateBody, request_id: requestId }),
			});
			if (!response.ok) {
				const err = await response.json().catch(() => ({}));
				if (
					response.status === 409 &&
					err.detail === "VIDEO_JOB_IN_FLIGHT" &&
					err.active_job
				) {
					setNotice({
						tone: "info",
						title: "Existing video job resumed",
						detail: `The shared Flow lane is already running ${err.active_job}. Faceless is following that job instead of submitting another paid generation.`,
						requestId,
					});
					void pollJob(String(err.active_job), requestId);
					return;
				}
				throw new Error(
					typeof err.detail === "string"
						? err.detail
						: err.error || `HTTP ${response.status}`,
				);
			}
			const data = await response.json();
			const jobId = data.job_id || data.id;
			if (!jobId) throw new Error("No job_id returned");
			rememberGenerationJob({
				job_id: String(jobId),
				request_id: data.request_id ?? requestId,
				mode: String(generateBody.mode || "F2V"),
			});
			void pollJob(String(jobId), requestId);
		} catch (err: unknown) {
			setNotice({
				tone: "error",
				title: "Generate failed",
				detail: err instanceof Error ? err.message : "Generate request failed",
				requestId,
			});
			setIsExecuting(false);
			executionInFlightRef.current = false;
		}
	};

	const noticeToneClass =
		notice?.tone === "success"
			? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
			: notice?.tone === "error"
				? "border-rose-500/30 bg-rose-500/10 text-rose-100"
				: notice?.tone === "warning"
					? "border-amber-500/30 bg-amber-500/10 text-amber-100"
					: "border-sky-500/30 bg-sky-500/10 text-sky-100";

	const genLabel = isExecuting
				? "Generating…"
				: `▶ Generate 1 faceless clip · ${durationSec}s`;

	return (
		<div
			className="flex h-full min-h-0 flex-col gap-4 p-4 md:p-6"
			data-testid="faceless-workflow"
			data-variant="v4"
			data-mode="FACELESS"
		>
			{pendingApproval && (
				<FinalPromptApprovalModal
					envelope={pendingApproval}
					approvedBy={staffIdentity.selectedStaff?.display_name ?? ""}
					onApproved={(snap) => {
						setPendingApproval(null);
						void handleGenerate(true, snap.final_prompt_text);
					}}
					onCancel={() => setPendingApproval(null)}
				/>
			)}
			<header className="flex flex-wrap items-end justify-between gap-3">
				<div>
					<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-v4-accent">
						Faceless Video
					</div>
					<h1 className="text-xl font-bold text-slate-100">
						Product clip — hands / body, no face
					</h1>
					<p className="mt-1 max-w-2xl text-[12px] text-slate-400">
						Same path as Hybrid without an AI avatar. Product image anchors the
						clip automatically. Credits spent only when you press Generate.
					</p>
				</div>
			{settingsLoading ? (
					<span className="text-[11px] text-slate-500">Loading settings…</span>
				) : null}
			</header>
			<StaffIdentityBar identity={staffIdentity} surface="FACELESS" />

			<div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
				<div className="min-h-0 space-y-3 overflow-y-auto pr-1">
					<WorkflowStep
						index={1}
						title="Product"
						status={sProduct}
						open={v4IsOpen(1, sProduct)}
						onToggleOpen={() => v4Toggle(1, v4IsOpen(1, sProduct))}
						summary={
							selectedProduct
								? selectedProduct.raw_product_title || selectedProduct.id
								: "Select a product"
						}
					>
						<SearchableProductSelect
							products={products}
							selectedProduct={selectedProduct}
							isLoadingProducts={isLoadingProducts}
							productsError={productsError}
							onSelect={(p) => {
								setSelectedProduct(p);
								setWorkspacePackage(null);
								setV2CopyReady(false);
								setPendingApproval(null);
								setHookId("AUTO");
								setBackgroundId("AUTO");
								setActorProfile("AUTO");
								setResolvedHook(null);
								setResolvedBackground(null);
								setResolvedActorProfile(null);
								setCompletedUrl(null);
							}}
						/>
						<p className="mt-2 text-[11px] text-slate-500">
							Product image is the automatic visual anchor — no Creative Library
							frame pick required.
						</p>
					</WorkflowStep>

					<WorkflowStep
						index={2}
						title="Copywriting"
						status={sCopy}
						open={v4IsOpen(2, sCopy)}
						onToggleOpen={() => v4Toggle(2, v4IsOpen(2, sCopy))}
						summary={(selectedCopySource === "BENEFIT_RENDER" ? benefitRenderReady : v2CopyReady) ? "Copy selected" : "Copywriting required"}
						helper="Generate benefit-driven scripts on demand, or use existing approved Copy Register copy."
					>
						<div className="space-y-3">
							<div className="flex items-center gap-2" data-testid="copy-source-toggle">
								<button
									type="button"
									data-testid="copy-source-benefit-render"
									onClick={() => setSelectedCopySource("BENEFIT_RENDER")}
									className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${selectedCopySource === "BENEFIT_RENDER" ? "border border-emerald-500/40 bg-emerald-600/20 text-emerald-100" : "border border-slate-800 bg-slate-950 text-slate-400 hover:text-slate-200"}`}
								>
									Benefit On-Demand Copy
								</button>
								<button
									type="button"
									data-testid="copy-source-existing-v2"
									onClick={() => { setSelectedCopySource("COPY_V2"); setSelectedBenefitCopy(null); }}
									className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${selectedCopySource === "COPY_V2" ? "border border-blue-500/40 bg-blue-600/20 text-blue-100" : "border border-slate-800 bg-slate-950 text-slate-400 hover:text-slate-200"}`}
								>
									Existing Approved Copy V2
								</button>
							</div>
							{selectedCopySource === "BENEFIT_RENDER" ? (
								<BenefitCopySourceSection
									productId={selectedProduct?.id}
									lane="FACELESS"
									durationSeconds={durationSec}
									onReadyChange={(ready) => { setBenefitRenderReady(ready); if (ready) setWorkspacePackage(null); }}
									onSelectedCopyChange={(ctx) => { setSelectedBenefitCopy(ctx); setWorkspacePackage(null); }}
								/>
							) : (
								<>
									<CopywritingSourceSelector
										productId={selectedProduct?.id}
										productName={selectedProduct?.raw_product_title}
										lane="FACELESS"
										onCopySelected={() => {
											setWorkspacePackage(null);
											setV2CopyReady(false);
										}}
									/>
									<CopyArchitectureV2LaneCard
										key={selectedProduct?.id ?? "none"}
										lane="FACELESS"
										productId={selectedProduct?.id}
										execution={workspacePackage?.copy_architecture_v2}
										onReadyChange={setV2CopyReady}
									/>
								</>
							)}
						</div>
					</WorkflowStep>

					<WorkflowStep
						index={3}
						title="Opening Strategy"
						status={sCreative}
						open={v4IsOpen(3, sCreative)}
						onToggleOpen={() => v4Toggle(3, v4IsOpen(3, sCreative))}
						summary={hookLabel}
						helper="Creative opening direction only. Approved Hook / Body / CTA remain in Copy Register."
					>
						{!settingsAvailable ? (
							<div
								className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-200"
								data-testid="faceless-settings-unavailable"
							>
								Settings unavailable{settingsError ? `: ${settingsError}` : ""}.{" "}
								<button
									type="button"
									className="underline"
									onClick={() => reloadSettings()}
									data-testid="faceless-settings-retry"
								>
									Retry
								</button>
							</div>
						) : null}
						<label className="space-y-1">
							<span className={labelClass}>Opening Strategy</span>
							<select
								className={selectClass}
								value={hookId}
								onChange={(e) => {
									setHookId(e.target.value);
									setWorkspacePackage(null);
								}}
								data-testid="faceless-opening-strategy"
								data-wire-field="hook_id"
								disabled={!settingsAvailable}
							>
								{openingStrategyOptions.map((o) => (
									<option key={o.id} value={o.id}>
										{o.label}
									</option>
								))}
							</select>
						</label>
						<div className="mt-3 flex flex-wrap gap-2">
							<ResolvedChip
								label="Opening Strategy"
								value={
									resolvedHook
										? `${resolvedHook.setting_id} · ${resolvedHook.display_label}`
										: hookLabel
								}
								auto={hookId === "AUTO"}
							/>
						</div>
					</WorkflowStep>

					<WorkflowStep
						index={4}
						title="Background"
						status={sCreative}
						open={v4IsOpen(4, sCreative)}
						onToggleOpen={() => v4Toggle(4, v4IsOpen(4, sCreative))}
						summary={backgroundLabel}
						helper="Only backgrounds compatible with the resolved Scene Choreography context are offered."
					>
						<label className="space-y-1">
							<span className={labelClass}>Background</span>
							<select
								className={selectClass}
								value={backgroundId}
								onChange={(e) => {
									setBackgroundId(e.target.value);
									setWorkspacePackage(null);
								}}
								data-testid="faceless-background"
								disabled={!settingsAvailable}
							>
								{settings.background.options.map((o) => (
									<option key={o.id} value={o.id}>
										{o.label}
									</option>
								))}
							</select>
						</label>
						<label className="mt-3 block space-y-1">
							<span className={labelClass}>Actor profile</span>
							<select
								className={selectClass}
								value={actorProfile}
								onChange={(e) => {
									setActorProfile(e.target.value);
									setResolvedActorProfile(null);
									setWorkspacePackage(null);
								}}
								data-testid="faceless-actor-profile"
								disabled={!settingsAvailable}
							>
								{actorProfileOptions.map((o) => (
									<option key={o.id} value={o.id}>
										{o.label}
									</option>
								))}
							</select>
						</label>
						<div className="mt-3 flex flex-wrap gap-2">
							<ResolvedChip
								label="Background"
								value={
									resolvedBackground
										? `${resolvedBackground.setting_id} · ${resolvedBackground.display_label}`
										: backgroundLabel
								}
								auto={backgroundId === "AUTO"}
							/>
							<ResolvedChip label="Presence" value="Faceless" />
							<ResolvedChip
								label="Actor profile"
								value={
									resolvedActorProfile
										? String(
												resolvedActorProfile.display_label ||
													resolvedActorProfile.resolved_profile ||
													actorProfileLabel,
										  )
										: actorProfileLabel
								}
								auto={actorProfile === "AUTO"}
							/>
						</div>
					</WorkflowStep>

					<WorkflowStep
						index={5}
						title="Video settings"
						status={sSettings}
						open={v4IsOpen(5, sSettings)}
						onToggleOpen={() => v4Toggle(5, v4IsOpen(5, sSettings))}
						summary={`${sceneMode === "EXTEND" ? "Extend" : "Single"} · ${videoModel} · ${durationLabel}`}
						helper="Same capability / model authority as Hybrid. No hardcoded 8s table."
					>
						<div className="grid gap-3 sm:grid-cols-3">
							<label className="space-y-1">
								<span className={labelClass}>Generation mode</span>
								<select
									className={selectClass}
									value={sceneMode}
									onChange={(e) => {
										setSceneMode(e.target.value as FacelessSceneMode);
										setWorkspacePackage(null);
									}}
									data-testid="faceless-scene-mode"
								>
									<option value="SINGLE">Single</option>
									<option value="EXTEND">Extend</option>
								</select>
							</label>
							<label className="space-y-1">
								<span className={labelClass}>Video model</span>
								<select
									className={selectClass}
									value={videoModel}
									disabled={!capability || !(sceneMode === "SINGLE" ? modelsAtDuration : videoModels).length}
									onChange={(e) => {
										const next = e.target.value;
										setVideoModel(next);
										setWorkspacePackage(null);
										if (sceneMode === "SINGLE" && engine) {
											const still = modelsForSingle(engine, durationSec).some(
												(m) => m.ui_label === next,
											);
											if (!still) {
												const sel = resolveSingleSelection(engine, next, durationSec);
												if (sel) setDurationSec(sel.durationSeconds);
											}
										}
									}}
									data-testid="faceless-model"
								>
									{(sceneMode === "SINGLE"
										? modelsAtDuration.map((m) => m.ui_label)
										: videoModels.map((m) => m.ui_label)
									)
										.filter((v, i, a) => a.indexOf(v) === i)
										.map((label) => (
											<option key={label} value={label}>
												{label}
											</option>
										))}
								</select>
							</label>
							<label className="space-y-1">
								<span className={labelClass}>
									{sceneMode === "EXTEND" ? "Total duration" : "Duration"}
								</span>
								{sceneMode === "SINGLE" ? (
									<select
										className={selectClass}
										value={durationSec}
										disabled={!capability || !singleDurationOptions.length}
										onChange={(e) => {
											const next = Number(e.target.value);
											setDurationSec(next);
											setWorkspacePackage(null);
											if (engine) {
												const sel = resolveDurationChange(engine, videoModel, next);
												if (sel?.model) setVideoModel(sel.model);
											}
										}}
										data-testid="faceless-duration"
									>
										{singleDurationOptions.map((d) => (
											<option key={d} value={d}>
												{d}s
											</option>
										))}
									</select>
								) : (
									<select
										className={selectClass}
										value={extendTotalSec ?? ""}
										onChange={(e) => {
											setExtendTotalSec(Number(e.target.value));
											setWorkspacePackage(null);
										}}
										disabled={Boolean(extendBlockedReason)}
										data-testid="faceless-extend-total"
									>
										{extendBlockedReason ? (
											<option value="">Unavailable</option>
										) : null}
										{extendTotals.map((t) => (
											<option key={t} value={t}>
												{t}s total
											</option>
										))}
									</select>
								)}
							</label>
						</div>
						{extendBlockedReason ? (
							<p
								className="mt-2 text-[11px] text-amber-200"
								data-testid="faceless-extend-blocked"
							>
								{extendBlockedReason}
							</p>
						) : null}
						{sceneMode === "EXTEND" && !extendBlockedReason ? (
							<p className="mt-2 text-[11px] text-slate-500">
								Extend uses native-extend after an 8s base clip — not a multi-block
								single generate call.
							</p>
						) : null}
					</WorkflowStep>

					<details className="rounded-xl border border-slate-800 bg-slate-900/40 px-3 py-2">
						<summary
							className="cursor-pointer text-[11px] font-bold uppercase tracking-wide text-slate-500"
							data-testid="faceless-advanced-toggle"
							onClick={() => setShowAdvancedRef((v) => !v)}
						>
							Advanced · optional reference override
						</summary>
						{showAdvancedRef ? (
							<div className="mt-3">
								<p className="mb-2 text-[11px] text-slate-500">
									Optional. Default path uses the product image automatically.
								</p>
								<CanonicalReferenceBindingControls
									mode="F2V"
									productId={selectedProduct?.id ?? null}
									binding={binding}
									onChange={(next) => {
										setBinding(next);
										setWorkspacePackage(null);
									}}
								/>
							</div>
						) : null}
					</details>

					<WorkflowStep
						index={6}
						title="Review & prepare"
						status={sPrepare}
						open={v4IsOpen(6, sPrepare)}
						onToggleOpen={() => v4Toggle(6, v4IsOpen(6, sPrepare))}
						summary={
							workspacePackage
								? "Package ready"
								: blockers.length
									? "Blocked"
									: "Compile final prompt"
						}
						helper="Credit-free prepare. Product image anchors the package."
					>
						<p className="mb-2 text-[11px] text-slate-400" data-testid="faceless-visual-law">
							{FACELESS_VISUAL_LAW}
						</p>
						{facelessExactRoute(workspacePackage) === FACELESS_EXACT_ROUTE ? (
							<div
								className="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-100"
								data-testid="faceless-exact-route"
							>
								<div className="font-bold">Product fidelity: Exact product</div>
								<div>Execution: Exact deterministic composite · provider scene scaffold only</div>
							</div>
						) : null}
						{blockers.length ? (
							<ul className="mb-3 list-disc space-y-1 pl-4 text-[12px] text-amber-100">
								{blockers.map((b) => (
									<li key={b}>{b}</li>
								))}
							</ul>
						) : null}
						<button
							type="button"
							disabled={
								Boolean(blockers.length) ||
								isPreparing ||
								!selectedProduct ||
								!staffIdentity.hasStaff
							}
							onClick={() => void handlePrepare()}
							className="rounded-xl border border-v4-accent/40 bg-v4-accent/15 px-4 py-2.5 text-[12px] font-bold text-v4-accent-ink hover:bg-v4-accent/25 disabled:cursor-not-allowed disabled:opacity-40"
							data-testid="faceless-prepare"
						>
							{isPreparing ? "Preparing…" : "Prepare final prompt"}
						</button>
						{workspacePackage?.prompt_text ? (
							<pre className="mt-3 max-h-40 overflow-auto rounded-lg border border-slate-800 bg-slate-950/80 p-3 text-[11px] text-slate-300 whitespace-pre-wrap">
								{workspacePackage.prompt_text}
							</pre>
						) : null}
					</WorkflowStep>

					<WorkflowStep
						index={7}
						title="Generate video"
						status={sGenerate}
						open={v4IsOpen(7, sGenerate)}
						onToggleOpen={() => v4Toggle(7, v4IsOpen(7, sGenerate))}
						summary={
							isExecuting ? "Generating…" : completedUrl ? "Done" : "Operator gate"
						}
						helper="Credits are spent only here. Never auto-fired."
						collapsible={false}
					>
						{sceneMode === "EXTEND" ? (
							<NativeExtendPanel
								surfaceLane="FACELESS"
								productId={selectedProduct?.id}
								productName={
									selectedProduct?.raw_product_title || selectedProduct?.id
								}
								executionPackageId={
									workspacePackage?.workspace_execution_package_id
								}
								approvedAssetSha256={
									workspacePackage?.resolved_assets?.find(
										(asset) => asset.slot_key === "start_frame",
									)?.asset_fingerprint
								}
								totalDurationSeconds={extendTotalSec}
								aspectRatio="VIDEO_ASPECT_RATIO_PORTRAIT"
							/>
						) : (
							<>
								<button
									type="button"
									disabled={
										!workspacePackage?.prompt_text ||
										isExecuting ||
										blockers.length > 0 ||
										!staffIdentity.hasStaff
									}
									onClick={() => void handleGenerate()}
									className="w-full rounded-xl bg-gradient-to-br from-v4-accent to-v4-auto px-4 py-3 text-[13px] font-bold text-slate-950 shadow-lg shadow-v4-accent/20 transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
									data-testid="faceless-generate"
								>
									{genLabel}
								</button>
								<p className="mt-2 text-[11px] text-slate-500">
									Uses the shared one-door generate path. Needs an open, warmed-up Flow
									editor tab.
								</p>
							</>
						)}
						{completedUrl ? (
							<video
								className="mt-3 max-h-64 w-full rounded-xl border border-slate-800 bg-black"
								src={completedUrl}
								controls
								data-testid="faceless-result-video"
							/>
						) : null}
					</WorkflowStep>

					{notice ? (
						<div
							className={`rounded-xl border px-3 py-2 text-[12px] ${noticeToneClass}`}
							data-testid="faceless-notice"
						>
							<div className="font-bold">{notice.title}</div>
							<div className="opacity-90">{notice.detail}</div>
						</div>
					) : null}
				</div>

				<ResultsSidebar
					results={sessionResults}
					generating={isExecuting}
					mediaKind="video"
					libraryHref="/library/videos"
					staffId={staffIdentity.staffId}
					surfaceLane="FACELESS"
					requestId={notice?.requestId ?? null}
					onRemoved={(mediaId) =>
						setSessionResults((prev) => prev.filter((r) => r.media_id !== mediaId))
					}
				/>
			</div>
		</div>
	);
}
