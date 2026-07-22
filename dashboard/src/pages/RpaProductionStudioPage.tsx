/**
 * RPA Production Studio — the user-facing T2V generation studio (MVP).
 *
 * RPA Queue Control proved the machinery (bridge/approve/enqueue/dry-run/live gate),
 * but it reads like a debug panel: it starts from an execution-package handle, not a
 * product, and exposes every internal step. This page is the same PROVEN pipeline,
 * re-presented as a studio a normal user can drive: pick a product, configure the
 * selected logical mode, prepare, validate, run one live job, see the result.
 *
 * It REUSES the exact backend contract and safety gates — no new server routes, no
 * weakened guards. ALL FOUR video lanes are one-click wired through their own
 * phrased one-serial gates (T2V / first-frame family F2V+HYBRID / I2V), with
 * mode-exact server authorization; O4 duplicate protection is untouched. Bulk
 * stays locked.
 *
 * Durations beyond the engine's single-shot max run through the PROVEN multi-block
 * EXTEND lane instead of the queue: workspace execution package (per-block canonical
 * 9-section prompts, WPS dialogue budgets from the storyboard planner) → the durable
 * /video-jobs orchestrator (plan → authorize → advance: INITIAL → EXTEND → CONCAT →
 * final media). The queue lane refuses EXTEND packages outright
 * (EXTEND_PACKAGE_SINGLE_SHOT_FORBIDDEN), so a 16s request can never be silently
 * truncated to one 8s clip.
 */
import {
	AlertTriangle,
	CheckCircle2,
	Flame,
	Image as ImageIcon,
	Layers,
	Loader2,
	Lock,
	PackageCheck,
	Play,
	RefreshCw,
	Search,
	Sparkles,
	Video,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { fetchProductCatalog, searchProducts } from "../api/products";
import {
	approvePackages,
	createProductionRun,
	fetchVideoModels,
	getProductionRun,
	LIVE_BULK_CONFIRM_PHRASE,
	LIVE_CONFIRM_PHRASE,
	LIVE_F2V_CONFIRM_PHRASE,
	LIVE_GATE_BULK_FANOUT,
	LIVE_GATE_ONE_SERIAL_F2V,
	LIVE_GATE_ONE_SERIAL_I2V,
	LIVE_GATE_ONE_SERIAL_T2V,
	LIVE_I2V_CONFIRM_PHRASE,
	startProductionRun,
	type VideoModelInfo,
} from "../api/productionQueue";
import {
	createFromExecutionPackage,
	createI2VGenerationPackage,
	createT2VGenerationPackage,
} from "../api/workspaceGenerationPackages";
import { fetchCreativeAssets } from "../api/creativeAssets";
import { fetchFlowPageState, openFlowNewProject } from "../api/operator";
import type { CreativeAsset } from "../types";
import {
	authorizeVideoJob,
	getVideoJobStatus,
	planVideoJob,
	startVideoJob,
	type VideoJobPlan,
	type VideoJobStatus,
} from "../api/nativeExtend";
import {
	createWorkspaceExecutionPackage,
	bindBulkManualFireResult,
	fetchBulkManualFireHandoff,
	fetchBulkFanoutPlan,
	fetchCopyPoolReadiness,
	prepareBulkFanoutPackages,
	previewQuantityCopyPlans,
	type BulkFanoutPlanResult,
	type BulkManualFireHandoff,
	type BulkPrepareResult,
	type CopyPoolReadinessResult,
	type QuantityPreviewResult,
} from "../api/workspacePackages";
import type { Product, WorkspaceMode } from "../types";

const ASPECTS = ["9:16", "16:9", "1:1"];
// Stage 1 quantity PREVIEW cap. quantity>1 is preview-only (credit-free unique-copy
// planning); live bulk fan-out is Stage 2 and stays blocked. Keep in lockstep with
// the backend QUANTITY_PREVIEW_MAX (workspace_generation_package_service.py).
const QUANTITY_MAX = 5;
const POLL_MS = 5000;
const TERMINAL_STATUSES = new Set(["GENERATED", "DOWNLOADED", "FAILED", "CANCELLED"]);

// ── EXTEND (multi-block) lane ──────────────────────────────────────────────
// Totals beyond the engine's single-shot max run through the PROVEN multi-block
// pipeline: workspace execution package (per-block 9-section canonical prompts,
// dialogue budgets WPS-allocated by the storyboard planner) → the durable
// /video-jobs orchestrator (plan → authorize → advance: INITIAL → EXTEND →
// CONCAT → final media). Nothing here re-implements planning or prompting —
// this page only WIRES the proven lane. The single-shot queue lane refuses
// EXTEND packages outright (EXTEND_PACKAGE_SINGLE_SHOT_FORBIDDEN).
const EXTEND_MULTIPLES = [2, 3]; // 16 s and 24 s on an 8 s engine
/** UI-only latch for the extend fire button; the REAL gate is the server-side
 *  authorize step (plan-fingerprint-bound, expiring token). */
const EXTEND_CONFIRM_PHRASE = "AUTHORIZE_EXTEND_VIDEO_JOB";
const EXTEND_ASPECT_ENUM: Record<string, string> = {
	"9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
	"16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
	"1:1": "VIDEO_ASPECT_RATIO_SQUARE",
};

// All four video lanes are LIVE-PROVEN (first bound artifacts 2026-07-18:
// T2V cb0c8b36 · F2V 0a18ca6a · HYBRID 80afc332 · I2V b7564ded) and one-click
// wired here through their own phrased gates.
type StudioMode = "T2V" | "F2V" | "HYBRID" | "I2V";
type ReferenceKind = "none" | "frame" | "product_anchor" | "ingredients";
type PrepareKind = "t2v" | "image" | "i2v";

/**
 * The Studio's UI authority. Backend transport intentionally remains separate:
 * HYBRID is a logical product-anchor mode that rides the proven F2V transport.
 */
const MODE_PROFILES: Record<StudioMode | "IMG", {
	label: string;
	hint: string;
	icon: typeof Video;
	referenceKind: ReferenceKind;
	prepareKind?: PrepareKind;
	sourceMode?: "T2V" | "FRAMES" | "HYBRID";
	flowDiagnosticMode?: "T2V" | "F2V";
	liveGate?: typeof LIVE_GATE_ONE_SERIAL_T2V | typeof LIVE_GATE_ONE_SERIAL_F2V | typeof LIVE_GATE_ONE_SERIAL_I2V;
	confirmationPhrase?: typeof LIVE_CONFIRM_PHRASE | typeof LIVE_F2V_CONFIRM_PHRASE | typeof LIVE_I2V_CONFIRM_PHRASE;
	liveWarning: string;
}> = {
	T2V: {
		label: "Text → Video", hint: "Text-only. PROVEN (cb0c8b36).", icon: Video,
		referenceKind: "none", prepareKind: "t2v", sourceMode: "T2V", flowDiagnosticMode: "T2V",
		liveGate: LIVE_GATE_ONE_SERIAL_T2V, confirmationPhrase: LIVE_CONFIRM_PHRASE,
		liveWarning: "It calls the real provider and runs exactly one T2V generation. It cannot be undone. After it submits, do not retry unless the system proves no provider submission occurred.",
	},
	F2V: {
		label: "Frames → Video", hint: "Needs an APPROVED 9:16 start frame (make one in the Frame Factory). PROVEN (0a18ca6a).", icon: Layers,
		referenceKind: "frame", prepareKind: "image", sourceMode: "FRAMES", flowDiagnosticMode: "F2V",
		liveGate: LIVE_GATE_ONE_SERIAL_F2V, confirmationPhrase: LIVE_F2V_CONFIRM_PHRASE,
		liveWarning: "It calls the real provider and runs exactly one Frames → Video generation. It cannot be undone. After it submits, do not retry unless the system proves no provider submission occurred.",
	},
	HYBRID: {
		label: "Hybrid", hint: "Product-anchor presenter. Needs an APPROVED 9:16 product reference. PROVEN (80afc332).", icon: Sparkles,
		referenceKind: "product_anchor", prepareKind: "image", sourceMode: "HYBRID", flowDiagnosticMode: "F2V",
		liveGate: LIVE_GATE_ONE_SERIAL_F2V, confirmationPhrase: LIVE_F2V_CONFIRM_PHRASE,
		liveWarning: "It calls the real provider for one HYBRID product-anchor generation. HYBRID uses the proven first-frame transport internally; it cannot be undone. After it submits, do not retry unless the system proves no provider submission occurred.",
	},
	I2V: {
		label: "Ingredients → Video", hint: "Character + scene references. PROVEN (b7564ded).", icon: Video,
		referenceKind: "ingredients", prepareKind: "i2v", flowDiagnosticMode: "F2V",
		liveGate: LIVE_GATE_ONE_SERIAL_I2V, confirmationPhrase: LIVE_I2V_CONFIRM_PHRASE,
		liveWarning: "It calls the real provider and runs exactly one Ingredients → Video generation. It cannot be undone. After it submits, do not retry unless the system proves no provider submission occurred.",
	},
	IMG: {
		label: "Image · Frame Factory", hint: "Opens the proven IMG Fastlane frame factory.", icon: ImageIcon,
		referenceKind: "none", liveWarning: "IMG is prepared in the Fastlane, not submitted from this Studio.",
	},
};

const VIDEO_MODES = (["T2V", "F2V", "HYBRID", "I2V"] as const).map((key) => ({
	key,
	...MODE_PROFILES[key],
}));

interface DryRunItem {
	package_id?: string;
	ok?: boolean;
	blockers?: string[];
	logical_mode?: string;
	model?: string | null;
}
interface DryRunReport {
	checked?: number;
	ready?: number;
	blocked?: number;
	items?: DryRunItem[];
	note?: string;
}
interface RunItem {
	package_id?: string;
	production_status?: string;
	production_job_id?: string | null;
	production_error?: string | null;
	artifact_media_ids?: string[];
}
type Stage = "IDLE" | "PREPARED" | "VALIDATED" | "LIVE_SUBMITTED";

/** Turn a raw backend failure code into a plain sentence a user can act on. */
function explainFailure(raw: string | null | undefined): string {
	const s = String(raw ?? "");
	if (!s) return "The job failed without a reason.";
	if (s.includes("RATE_LIMITED")) return "Google's anti-abuse rate limiter blocked the request before approval. No credits were spent. Wait ~1–2 hours and try again — do not hammer retries.";
	if (s.includes("CAPTCHA_FAILED")) return "The Flow tab is stale/cold, so the extension could not reach the page. Reload the extension and the Flow tab, open the project, then retry. No credits were spent.";
	if (s.includes("NO_OPEN_EDITOR")) return "No Google Flow project editor is open in the controlled tab. Open the target Flow project first.";
	if (s.includes("OUTPUT_IDENTITY_NOT_CAPTURED")) return "The video generated but its identity could not be captured, so it cannot be bound to this job. This is a capture gap, not a lost video.";
	if (s.includes("GENERATED_BUT_UNRETRIEVED")) return "The video generated (credits spent) but could not be retrieved/bound in time. It exists in Flow but is not registered here.";
	if (s.includes("OUTPUT_CORRELATION_UNAVAILABLE") || s.includes("IDENTITY_MISMATCH")) return "A finished video was found but could not be deterministically proven to belong to this job, so it was refused. Nothing was registered.";
	return s;
}

function displayBlocker(raw: string, profile: typeof MODE_PROFILES[StudioMode]): string {
	if (profile.referenceKind === "product_anchor" && raw.includes("SLOT_ASPECT_MISMATCH")) {
		return "Product anchor aspect does not match the selected output aspect. Compose an approved target-aspect product anchor first.";
	}
	return raw;
}

export default function RpaProductionStudioPage() {
	// ── product selection ──
	const [query, setQuery] = useState("");
	const [products, setProducts] = useState<Product[]>([]);
	const [loadingProducts, setLoadingProducts] = useState(true);
	const [productsError, setProductsError] = useState(false);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);

	// ── config ──
	const [models, setModels] = useState<VideoModelInfo[]>([]);
	const [model, setModel] = useState<string>("");
	const [duration, setDuration] = useState<number>(8);
	const [aspect, setAspect] = useState<string>("9:16");
	// ── Stage 1 quantity preview (credit-free; live stays single-serial) ──
	const [quantity, setQuantity] = useState<number>(1);
	const [previewResult, setPreviewResult] = useState<QuantityPreviewResult | null>(null);
	// Approved copy-pool readiness, checked BEFORE every preview so a shortage is
	// reported as an exact number + a seeding action, not as a bare uniqueness block.
	const [poolReadiness, setPoolReadiness] = useState<CopyPoolReadinessResult | null>(null);
	// Stage 2A: the itemized bulk fan-out plan (N separate intents). Planning
	// only — it never enables live; the server gate stops at the credit boundary.
	const [bulkPlan, setBulkPlan] = useState<BulkFanoutPlanResult | null>(null);
	// Stage 2C: the PREPARED itemized batch (N durable packages + one run).
	// Credit-free; live still needs Stage 3 certification.
	const [bulkPrepared, setBulkPrepared] = useState<BulkPrepareResult | null>(null);
	const [bulkDryRun, setBulkDryRun] = useState<DryRunReport | null>(null);
	// System-fired bulk live: the operator types the bulk phrase and the APP fires
	// each prepared item as its own provider job through the existing BULK_FANOUT
	// server gate. The server remains the sole authority (phrase, pinned package
	// ids, pinned dialogue fingerprints, per-item re-derivation, credit boundary).
	const [bulkLivePhrase, setBulkLivePhrase] = useState("");
	const [bulkLiveError, setBulkLiveError] = useState<string | null>(null);
	// B-01: the submit latch is scoped to the RUN it was armed for, never a global
	// boolean. A global flag stayed set after a refusal, so the next prepared batch
	// was permanently locked until a page reload. Holding the run id keeps "no retry
	// one click away" for THIS run while a genuinely new run can be authorized.
	const [bulkLiveSubmittedRunId, setBulkLiveSubmittedRunId] = useState<string | null>(null);
	const [bulkLiveStatus, setBulkLiveStatus] = useState<string | null>(null);
	const [bulkManualHandoff, setBulkManualHandoff] = useState<BulkManualFireHandoff | null>(null);
	const [bulkManualInputs, setBulkManualInputs] = useState<Record<string, { provider_job_id: string; flow_media_id: string; result_url: string; result_file_id: string; notes: string }>>({});
	const [bulkError, setBulkError] = useState<string | null>(null);
	const [previewError, setPreviewError] = useState<string | null>(null);

	// ── pipeline ──
	const [busy, setBusy] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [wgpId, setWgpId] = useState<string | null>(null);
	const [runId, setRunId] = useState<string | null>(null);
	const [report, setReport] = useState<DryRunReport | null>(null);
	const [stage, setStage] = useState<Stage>("IDLE");

	// ── live gate ──
	const [phrase, setPhrase] = useState("");
	const [liveSubmitted, setLiveSubmitted] = useState(false);
	const [liveError, setLiveError] = useState<string | null>(null);
	const [jobItem, setJobItem] = useState<RunItem | null>(null);
	const [runStatus, setRunStatus] = useState<string | null>(null);
	// ── one-click mode (all four video lanes are live-proven) ──
	const [studioMode, setStudioMode] = useState<StudioMode>("T2V");
	// Per-mode reference selections (server re-validates roles/approval on prepare).
	const [startFrameAssetId, setStartFrameAssetId] = useState("");
	const [productRefAssetId, setProductRefAssetId] = useState("");
	const [characterAssetId, setCharacterAssetId] = useState("");
	const [sceneAssetId, setSceneAssetId] = useState("");
	const [frameAssets, setFrameAssets] = useState<CreativeAsset[]>([]);
	const [productRefAssets, setProductRefAssets] = useState<CreativeAsset[]>([]);
	const [characterAssets, setCharacterAssets] = useState<CreativeAsset[]>([]);
	const [sceneAssets, setSceneAssets] = useState<CreativeAsset[]>([]);
	// Flow tab readiness (ADVISORY pre-fire drill — CAPTCHA/build-mismatch lessons).
	const [flowTab, setFlowTab] = useState<{ ready: boolean; buildMatch: boolean } | null>(null);
	// ── EXTEND (multi-block) lane state ──
	const [wepId, setWepId] = useState<string | null>(null);
	const [extendPlan, setExtendPlan] = useState<VideoJobPlan | null>(null);
	const [extendWpsBudgets, setExtendWpsBudgets] = useState<number[] | null>(null);
	const [extendBlockCount, setExtendBlockCount] = useState<number | null>(null);
	const [extendJob, setExtendJob] = useState<VideoJobStatus | null>(null);
	const pollRef = useRef<number | null>(null);

	const loadProducts = useCallback(async (q: string) => {
		setLoadingProducts(true);
		setProductsError(false);
		try {
			const res = q.trim() ? await searchProducts(q.trim(), 25, "GENERATION") : await fetchProductCatalog(40, "GENERATION");
			// A T2V job refuses fastmoss reference-only products server-side; don't offer them.
			setProducts((res.items ?? []).filter((p) => !p.reference_only));
		} catch {
			setProductsError(true);
		} finally {
			setLoadingProducts(false);
		}
	}, []);

	useEffect(() => {
		void loadProducts("");
		void fetchVideoModels()
			.then((r) => {
				setModels(r.models ?? []);
				const def = (r.models ?? []).find((m) => m.key === r.default || m.ui_label === r.default) ?? r.models?.[0];
				if (def) {
					setModel(def.ui_label);
					if (def.default_duration_s) setDuration(def.default_duration_s);
				}
			})
			.catch(() => setModels([]));
	}, [loadProducts]);

	const selectedModelInfo = useMemo(() => models.find((m) => m.ui_label === model), [models, model]);
	const activeProfile = MODE_PROFILES[studioMode];
	const singleDurations = selectedModelInfo?.allowed_durations_s ?? [duration];
	const maxSingle = Math.max(...singleDurations);
	// Multi-block EXTEND totals (N × the engine's single-shot max) — the proven
	// storyboard-planner + orchestrator lane, not N independent clips. EXTEND is
	// wired for the T2V lane only for now.
	const extendTotals = studioMode === "T2V" ? EXTEND_MULTIPLES.map((n) => n * maxSingle) : [];
	const durationOptions = [...singleDurations, ...extendTotals];
	const isExtend = studioMode === "T2V" && duration > maxSingle;
	// Stage 1: quantity>1 is PREVIEW-ONLY. It never enables live submission and never
	// touches the single-serial createProductionRun({count:1}) path — live bulk
	// fan-out is Stage 2 (unbuilt). This flag force-closes the live gates below.
	const bulkPreview = quantity > 1;

	// Per-lane gate identity. F2V + HYBRID share the live-proven first-frame
	// family gate; I2V has its own; T2V unchanged. The server enforces the real
	// phrase — these constants only wire the UI to the right lane.
	const laneGate = activeProfile.liveGate!;
	const lanePhrase = activeProfile.confirmationPhrase!;
	// Per-mode required references (server re-validates on prepare AND at the gate).
	const refsChosen = activeProfile.referenceKind === "none"
		|| (activeProfile.referenceKind === "frame" && Boolean(startFrameAssetId))
		|| (activeProfile.referenceKind === "product_anchor" && Boolean(productRefAssetId))
		|| (activeProfile.referenceKind === "ingredients" && Boolean(characterAssetId && sceneAssetId));

	// B-16: I2V character + scene references have NO product-image auto-seed
	// (unlike F2V frame / HYBRID anchor, which the server seeds from the product
	// image). A ref-less I2V bulk prepare is refused server-side, but only after
	// it has burned the copy-pool ledger for every item and stranded the batch.
	// Block the doomed click here too — scoped to I2V so it never over-blocks the
	// auto-seeding lanes. The server-side BULK_PREPARE_REFUSED:I2V_REFERENCES gate
	// remains the authority; this is just an earlier, clearer stop.
	const i2vBulkRefsMissing = studioMode === "I2V" && !(characterAssetId && sceneAssetId);

	/** Reset the whole pipeline when the product or config changes — a stale run must never be firable. */
	const resetPipeline = useCallback(() => {
		setWgpId(null);
		setRunId(null);
		setReport(null);
		setStage("IDLE");
		setError(null);
		setPhrase("");
		setLiveSubmitted(false);
		setLiveError(null);
		setJobItem(null);
		setRunStatus(null);
		setWepId(null);
		setExtendPlan(null);
		setExtendWpsBudgets(null);
		setExtendBlockCount(null);
		setExtendJob(null);
		setPreviewResult(null);
		setPreviewError(null);
		setPoolReadiness(null);
		setBulkPlan(null);
		setBulkPrepared(null);
		setBulkDryRun(null);
		setBulkError(null);
	}, []);

	/** Stage 1 quantity preview — credit-free plan of N unique-copy variants.
	 *  NEVER fires, approves, enqueues, or spends credit; the single-serial live
	 *  path (createProductionRun count:1) is not touched. HYBRID rides the F2V
	 *  transport (mode F2V + source_mode HYBRID), matching the live lane.
	 *
	 *  Copy-pool readiness runs FIRST. A pool that cannot supply `quantity` unique
	 *  approved dialogues stops here with an exact shortage + a seeding action,
	 *  instead of spending the compile and returning a bare uniqueness block. Both
	 *  calls are credit-free and read-only. */
	const handlePreviewQuantity = async () => {
		if (!selectedProduct) return;
		const previewMode = (studioMode === "HYBRID" ? "F2V" : studioMode) as WorkspaceMode;
		const copyPoolInput = {
			product_id: selectedProduct.id,
			mode: previewMode,
			source_mode: activeProfile.sourceMode ?? null,
			generation_mode: isExtend ? ("EXTEND" as const) : ("SINGLE" as const),
			duration_seconds: isExtend ? maxSingle : duration,
			requested_total_duration_seconds: isExtend ? duration : null,
			quantity,
			target_language: "BM_MS" as const,
		};
		setBusy("preview");
		setPreviewError(null);
		setPreviewResult(null);
		setPoolReadiness(null);
		setBulkPlan(null);
		setBulkPrepared(null);
		setBulkDryRun(null);
		setBulkError(null);
		try {
			const readiness = await fetchCopyPoolReadiness(copyPoolInput);
			setPoolReadiness(readiness);
			// Fail-closed: never preview against a pool that cannot supply N unique
			// dialogues. The operator seeds + approves copy first.
			if (readiness.readiness_status !== "READY") return;
			const result = await previewQuantityCopyPlans(copyPoolInput);
			setPreviewResult(result);
			// Stage 2A: only a UNIQUE preview earns an itemized fan-out plan. Still
			// credit-free, and still not a live authorization.
			if (quantity > 1 && result.preview_ready) {
				setBulkPlan(await fetchBulkFanoutPlan(copyPoolInput));
			}
		} catch (e) {
			setPreviewError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(null);
		}
	};

	/** Stage 2C — create + approve + enqueue N durable packages, then dry-run all
	 *  of them. Entirely credit-free: the run is created dry_run=1 and nothing
	 *  fires. Live bulk still requires Stage 3 certification, so this NEVER
	 *  opens the live gate. */
	const handleBulkPrepare = async () => {
		if (!selectedProduct || !bulkPlan?.bulk_authorizable) return;
		const previewMode = (studioMode === "HYBRID" ? "F2V" : studioMode) as WorkspaceMode;
		setBusy("bulk-prepare");
		setBulkError(null);
		setBulkDryRun(null);
		setBulkManualHandoff(null);
		// B-01: a new prepared batch must not inherit the previous run's live-fire
		// verdict or a pre-typed phrase — each run is authorized independently. The
		// latch itself is keyed by run id, so a REUSED batch (same production_run_id)
		// correctly stays latched.
		setBulkLiveError(null);
		setBulkLiveStatus(null);
		setBulkLivePhrase("");
		try {
			const prepared = await prepareBulkFanoutPackages({
				product_id: selectedProduct.id,
				mode: previewMode,
				source_mode: activeProfile.sourceMode ?? null,
				generation_mode: isExtend ? "EXTEND" : "SINGLE",
				duration_seconds: isExtend ? maxSingle : duration,
				requested_total_duration_seconds: isExtend ? duration : null,
				quantity,
				target_language: "BM_MS",
				model,
				aspect,
				// Pin the plan the operator saw — the server refuses a stale preview.
				expect_bulk_plan_fingerprint: bulkPlan.bulk_plan_fingerprint,
				start_frame_asset_id: startFrameAssetId || null,
				product_reference_asset_id: productRefAssetId || null,
				character_reference_asset_id: characterAssetId || null,
				scene_context_reference_asset_id: sceneAssetId || null,
			});
			setBulkPrepared(prepared);
			// Dry-run validates EVERY queued item. No credit, nothing fires.
			if (prepared.production_run_id) {
				const res = await startProductionRun(prepared.production_run_id, false);
				setBulkDryRun(res.report ?? null);
				if (res.report?.blocked === 0 && res.report?.ready === prepared.prepared_package_count) {
					setBulkManualHandoff(await fetchBulkManualFireHandoff(prepared.production_run_id));
				}
			}
		} catch (e) {
			setBulkError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(null);
		}
	};

	const handleBulkManualResult = async (item: NonNullable<BulkManualFireHandoff>["items"][number]) => {
		if (!bulkManualHandoff) return;
		const input = bulkManualInputs[item.workspace_generation_package_id] ?? { provider_job_id: "", flow_media_id: "", result_url: "", result_file_id: "", notes: "" };
		setBusy(`manual-result-${item.workspace_generation_package_id}`);
		setBulkError(null);
		try {
			await bindBulkManualFireResult(bulkManualHandoff.production_run_id, {
				workspace_generation_package_id: item.workspace_generation_package_id,
				copy_variant_id: item.copy_variant_id,
				dialogue_fingerprint: item.dialogue_fingerprint,
				...input,
			});
			setBulkManualHandoff(await fetchBulkManualFireHandoff(bulkManualHandoff.production_run_id));
		} catch (err) {
			setBulkError(err instanceof Error ? err.message : "Manual result binding failed.");
		} finally {
			setBusy(null);
		}
	};

	const pickProduct = (p: Product) => {
		setSelectedProduct(p);
		resetPipeline();
	};

	const pickMode = (m: StudioMode) => {
		setStudioMode(m);
		setStartFrameAssetId("");
		setProductRefAssetId("");
		setCharacterAssetId("");
		setSceneAssetId("");
		setDuration(8);
		resetPipeline();
	};

	// Load the reference libraries the selected mode needs. APPROVED only — the
	// backend gates re-validate role + approval, this just keeps the picker honest.
	useEffect(() => {
		if (activeProfile.referenceKind === "none") return;
		const approved = (items: CreativeAsset[]) =>
			items.filter((a) => a.review_status === "APPROVED");
		if (activeProfile.referenceKind === "frame" && selectedProduct) {
			void fetchCreativeAssets({
				semantic_role: "COMPOSITE_FRAME_REFERENCE", status: "ACTIVE",
				product_id: selectedProduct.id, limit: 100,
			}).then((r) => setFrameAssets(approved(r.items))).catch(() => setFrameAssets([]));
		}
		if (activeProfile.referenceKind === "product_anchor" && selectedProduct) {
			void fetchCreativeAssets({
				semantic_role: "PRODUCT_REFERENCE", status: "ACTIVE",
				product_id: selectedProduct.id, limit: 100,
			}).then((r) => setProductRefAssets(approved(r.items))).catch(() => setProductRefAssets([]));
		}
		if (activeProfile.referenceKind === "ingredients") {
			void fetchCreativeAssets({
				semantic_role: "CHARACTER_REFERENCE", status: "ACTIVE", limit: 100,
			}).then((r) => setCharacterAssets(approved(r.items))).catch(() => setCharacterAssets([]));
			void fetchCreativeAssets({
				semantic_role: "SCENE_CONTEXT_REFERENCE", status: "ACTIVE", limit: 100,
			}).then((r) => setSceneAssets(approved(r.items))).catch(() => setSceneAssets([]));
		}
	}, [activeProfile.referenceKind, selectedProduct]);

	// ADVISORY Flow-tab readiness (never gates the button — both failure modes are
	// proven 0-credit + retryable; this just surfaces the drill before the click).
	const refreshFlowTab = useCallback(async () => {
		try {
			const d = await fetchFlowPageState(activeProfile.flowDiagnosticMode ?? "F2V");
			setFlowTab({
				ready: Boolean(d.editor_capability_ready) && String(d.flow_url ?? "").includes("/project/"),
				buildMatch: d.build_match !== false,
			});
		} catch {
			setFlowTab(null);
		}
	}, [activeProfile.flowDiagnosticMode]);

	useEffect(() => {
		if (stage === "PREPARED" || stage === "VALIDATED") void refreshFlowTab();
	}, [stage, refreshFlowTab]);

	/** EXTEND prepare = create the PROVEN multi-block execution package (per-block
	 *  9-section canonical prompts with WPS-allocated dialogue budgets), then ask the
	 *  durable orchestrator for its ONE reviewed plan. Both steps spend nothing; an
	 *  incomplete/invalid plan is a structured 422 — fail-closed, nothing firable. */
	const handlePrepareExtend = async () => {
		if (!selectedProduct) return;
		setBusy("prepare");
		setError(null);
		try {
			const wep = await createWorkspaceExecutionPackage({
				product_id: selectedProduct.id,
				mode: "T2V",
				source_mode: "T2V",
				generation_mode: "EXTEND",
				requested_total_duration_seconds: duration,
				duration_seconds: maxSingle,
				aspect_ratio: aspect,
				model,
				dialogue_enabled: true,
				// Explicit-Fallback-Confirmation V1: the operator's Prepare click is the
				// explicit confirmation when no approved Copy Set is bound (backend still
				// fails closed on every other contract violation).
				copy_fallback_confirmed: true,
			});
			const wepIdNew = (wep as { workspace_execution_package_id?: string })
				.workspace_execution_package_id;
			if (!wepIdNew) throw new Error("execution package returned no id");
			// Surface the WPS truth: per-block dialogue word budgets + block count from
			// the canonical compiler lineage (each block is a full 9-section prompt).
			let lineage = (wep as { request_lineage_payload?: unknown }).request_lineage_payload;
			if (typeof lineage === "string") { try { lineage = JSON.parse(lineage); } catch { lineage = null; } }
			const compilerInfo = (lineage as { compiler?: Record<string, unknown> } | null)?.compiler;
			const budgets = compilerInfo?.dialogue_word_budget_per_block;
			const blocks = compilerInfo?.prompt_blocks;
			setExtendWpsBudgets(Array.isArray(budgets) ? budgets.map((b) => Number(b)) : null);
			setExtendBlockCount(Array.isArray(blocks) ? blocks.length : null);

			const plan = await planVideoJob({
				product_id: selectedProduct.id,
				execution_package_id: wepIdNew,
				requested_total_duration_seconds: duration,
				model,
				aspect_ratio: EXTEND_ASPECT_ENUM[aspect] ?? "VIDEO_ASPECT_RATIO_PORTRAIT",
			});
			setWepId(wepIdNew);
			setExtendPlan(plan);
			// The orchestrator plan IS the server-side validation (422 fail-closed),
			// so a returned plan means the lane is reviewed and ready to authorize.
			setStage("VALIDATED");
		} catch (e) {
			const msg = e instanceof Error ? e.message : String(e);
			setError(`Extend prepare failed (nothing firable, no credit): ${msg}`);
		} finally {
			setBusy(null);
		}
	};

	/** EXTEND fire = authorize the reviewed plan fingerprint, then start the durable
	 *  job. The server gate is the plan-fingerprint-bound expiring token — a changed
	 *  plan is rejected. This is the ONE credit-spending door of the extend lane. */
	const handleGoLiveExtend = async () => {
		if (!extendPlan || !extendGateOpen) return;
		setLiveSubmitted(true);
		setLiveError(null);
		setBusy("live");
		try {
			await authorizeVideoJob(extendPlan.job_id, extendPlan.plan_fingerprint);
			const status = await startVideoJob(extendPlan.job_id);
			setExtendJob(status);
			setStage("LIVE_SUBMITTED");
		} catch (e) {
			setLiveError(e instanceof Error ? e.message : String(e));
			setLiveSubmitted(false);
		} finally {
			setBusy(null);
		}
	};

	/** Shared tail: approve the package + enqueue a 1-item run. All no-credit. */
	const approveAndEnqueue = async (wgp: string) => {
		const approve = await approvePackages([wgp]);
		if (!approve.results?.[0]?.ok) {
			throw new Error(`Could not approve the package: ${approve.results?.[0]?.error ?? "unknown"}`);
		}
		const run = await createProductionRun({ package_ids: [wgp], model, aspect, count: 1 });
		setWgpId(wgp);
		setRunId(run.production_run_id);
		setStage("PREPARED");
	};

	/** F2V / HYBRID prepare — the PROVEN chain: execution package (server-validated
	 *  reference roles) → bridge (preserves the resolved assets) → approve → enqueue. */
	const handlePrepareImageMode = async () => {
		if (!selectedProduct || !refsChosen) return;
		setBusy("prepare");
		setError(null);
		try {
			const wep = await createWorkspaceExecutionPackage({
				product_id: selectedProduct.id,
				mode: "F2V",
				source_mode: activeProfile.sourceMode,
				generation_mode: "SINGLE",
				duration_seconds: 8,
				aspect_ratio: aspect,
				model,
				dialogue_enabled: true,
				copy_fallback_confirmed: true,
				...(activeProfile.referenceKind === "frame"
					? { start_frame_asset_id: startFrameAssetId }
					: { product_reference_asset_id: productRefAssetId }),
			});
			const wepIdNew = (wep as { workspace_execution_package_id?: string })
				.workspace_execution_package_id;
			if (!wepIdNew) throw new Error("execution package returned no id");
			const pkg = await createFromExecutionPackage(wepIdNew, "F2V");
			await approveAndEnqueue(pkg.workspace_generation_package_id);
		} catch (e) {
			setError(`Prepare failed (nothing firable, no credit): ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			setBusy(null);
		}
	};

	/** I2V prepare — direct package create with role-validated references. */
	const handlePrepareI2V = async () => {
		if (!selectedProduct || !refsChosen) return;
		setBusy("prepare");
		setError(null);
		try {
			const pkg = await createI2VGenerationPackage({
				product_id: selectedProduct.id,
				character_reference_asset_id: characterAssetId,
				scene_context_reference_asset_id: sceneAssetId,
			});
			await approveAndEnqueue(pkg.workspace_generation_package_id);
		} catch (e) {
			setError(`I2V prepare failed (nothing firable, no credit): ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			setBusy(null);
		}
	};

	/** Prepare = create the package for the selected mode, approve it, enqueue it. */
	const handlePrepare = async () => {
		if (!selectedProduct) return;
		if (activeProfile.prepareKind === "image") return handlePrepareImageMode();
		if (activeProfile.prepareKind === "i2v") return handlePrepareI2V();
		if (isExtend) return handlePrepareExtend();
		setBusy("prepare");
		setError(null);
		try {
			const pkg = await createT2VGenerationPackage({
				product_id: selectedProduct.id,
				generation_mode: "SINGLE",
				duration_seconds: duration,
			});
			const wgp = pkg.workspace_generation_package_id;
			const approve = await approvePackages([wgp]);
			if (!approve.results?.[0]?.ok) {
				setError(`Could not approve the package: ${approve.results?.[0]?.error ?? "unknown"}`);
				return;
			}
			const run = await createProductionRun({ package_ids: [wgp], model, aspect, count: 1 });
			setWgpId(wgp);
			setRunId(run.production_run_id);
			setStage("PREPARED");
		} catch (e) {
			const msg = e instanceof Error ? e.message : String(e);
			setError(
				/approved|package/i.test(msg)
					? `This product has no approved T2V package yet, so a T2V job cannot be prepared. Approve a product package first. (${msg})`
					: `Prepare failed: ${msg}`,
			);
		} finally {
			setBusy(null);
		}
	};

	/** Dry run — hard-coded false; no code path here can pass true, so no credit can burn from validation. */
	const handleValidate = async () => {
		if (!runId) return;
		setBusy("validate");
		setError(null);
		try {
			const res = await startProductionRun(runId, false);
			setReport(res.report ?? null);
			setStage("VALIDATED");
			await refresh(runId, true);
		} catch (e) {
			setError(`Validation failed: ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			setBusy(null);
		}
	};

	const refresh = useCallback(async (id?: string, silent = false) => {
		const target = id ?? runId;
		if (!target) return;
		if (!silent) setBusy("refresh");
		try {
			const detail = await getProductionRun(target);
			const run = (detail as unknown as { run?: Record<string, unknown> }).run ?? detail;
			setRunStatus(String((run as Record<string, unknown>).status ?? ""));
			let cfg = (run as Record<string, unknown>).config_json as unknown;
			if (typeof cfg === "string") { try { cfg = JSON.parse(cfg); } catch { cfg = {}; } }
			const persisted = (cfg as { last_dry_run_report?: DryRunReport })?.last_dry_run_report;
			if (persisted) setReport(persisted);
			const items = (detail as unknown as { items?: RunItem[] }).items;
			if (Array.isArray(items) && items.length > 0) setJobItem(items[0]);
		} catch (e) {
			if (!silent) setError(`Refresh failed: ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			if (!silent) setBusy(null);
		}
	}, [runId]);

	/** The one live door. Latches before the await; the server re-checks every gate condition. */
	const handleGoLive = async () => {
		if (!runId || !wgpId || !liveGateOpen) return;
		setLiveSubmitted(true);
		setLiveError(null);
		setBusy("live");
		try {
			const res = await startProductionRun(runId, true, {
				// The lane's own gate + the operator-typed phrase; the server enforces
				// the exact phrase and re-derives readiness (mode-exact authorization).
				live_gate: laneGate,
				confirm_phrase: phrase,
				expect_package_id: wgpId,
			});
			setRunStatus(res.status ?? "RUNNING");
			setStage("LIVE_SUBMITTED");
			await refresh(runId, true);
		} catch (e) {
			setLiveError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(null);
		}
	};

	/** SYSTEM-FIRED BULK LIVE. Fires the prepared batch through the existing
	 *  BULK_FANOUT server gate: the queue loop then submits EACH item as its own
	 *  provider job (never count:N), serially, with its own job id and evidence.
	 *  Every safety check stays server-side — this only hands over the pins the
	 *  server itself issued at prepare time. Latches before the await so a double
	 *  click cannot double-submit. */
	const handleBulkGoLive = async () => {
		if (!bulkPrepared?.production_run_id || !bulkLiveGateOpen) return;
		// Latch THIS run before the await: a double click cannot double-submit, and
		// a refusal keeps this run latched (no one-click retry after a possible
		// provider submission). A different prepared run is unaffected.
		setBulkLiveSubmittedRunId(bulkPrepared.production_run_id);
		setBulkLiveError(null);
		setBusy("bulk-live");
		try {
			const res = await startProductionRun(bulkPrepared.production_run_id, true, {
				live_gate: LIVE_GATE_BULK_FANOUT,
				confirm_phrase: bulkLivePhrase,
				// Pin the EXACT itemized set the server issued at prepare time; the
				// server re-derives and refuses on any drift.
				expect_package_ids: bulkPrepared.package_ids,
				expect_dialogue_fingerprints: bulkPrepared.expect_dialogue_fingerprints,
			});
			setBulkLiveStatus(res.status ?? "RUNNING");
		} catch (e) {
			// A refusal (e.g. BULK_LIVE_EXECUTION_NOT_CERTIFIED) is surfaced verbatim.
			// Do NOT clear the submitted latch: if the server may already have
			// submitted, a retry must never be one click away.
			setBulkLiveError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(null);
		}
	};

	// ── system-fired bulk live gate ──
	// UI SAFETY ONLY. The server re-checks every condition in _assert_bulk_fanout_live
	// (phrase, pinned ids, pinned fingerprints, per-item re-derived readiness, one
	// logical mode, prior-provider-job refusal, then the credit boundary). Note the
	// prepare snapshot carries no provider job id, so "already fired" is NOT
	// client-detectable — the server owns that refusal; the submit latch below only
	// stops a double click.
	const bulkPreparedCount = bulkPrepared?.prepared_package_count ?? 0;
	const bulkDryRunGreen = bulkPreparedCount > 0
		&& (bulkDryRun?.checked ?? -1) === bulkPreparedCount
		&& (bulkDryRun?.ready ?? -1) === bulkPreparedCount
		&& (bulkDryRun?.blocked ?? -1) === 0;
	const bulkPinsComplete = bulkPreparedCount > 0
		&& (bulkPrepared?.package_ids.length ?? 0) === bulkPreparedCount
		&& (bulkPrepared?.expect_dialogue_fingerprints.length ?? 0) === bulkPreparedCount
		&& (bulkPrepared?.expect_dialogue_fingerprints ?? []).every((fp) => Boolean(fp));
	const bulkPhraseOk = bulkLivePhrase === LIVE_BULK_CONFIRM_PHRASE;
	// Latched only for the run it was armed for (B-01) — a new prepared run starts clean.
	const bulkLiveAlreadySubmitted = Boolean(bulkPrepared?.production_run_id)
		&& bulkLiveSubmittedRunId === bulkPrepared?.production_run_id;
	const bulkLiveGateOpen = Boolean(bulkPrepared?.production_run_id) && bulkDryRunGreen
		&& bulkPinsComplete && bulkPhraseOk && !bulkLiveAlreadySubmitted && busy === null;

	// ── live gate conditions (identical semantics to Queue Control) ──
	const dryRunGreen = stage !== "IDLE" && report?.checked === 1 && report?.ready === 1 && report?.blocked === 0;
	const oneItemOnly = (report?.items?.length ?? 0) === 1;
	const noPriorJob = !jobItem?.production_job_id;
	const phraseOk = phrase === lanePhrase;
	const liveGateOpen = !bulkPreview && !isExtend && Boolean(selectedProduct) && dryRunGreen && oneItemOnly && noPriorJob && phraseOk && !liveSubmitted && busy === null;

	// ── EXTEND gate: a reviewed orchestrator plan + the extend phrase. The server
	//    re-gates with the fingerprint-bound authorize token — this is UI safety only.
	const extendPlanReady = Boolean(extendPlan?.plan_fingerprint);
	const extendPhraseOk = phrase === EXTEND_CONFIRM_PHRASE;
	const extendGateOpen = !bulkPreview && isExtend && Boolean(selectedProduct) && extendPlanReady && extendPhraseOk && !liveSubmitted && busy === null;

	const jobTerminal = TERMINAL_STATUSES.has(jobItem?.production_status ?? "");
	const jobArtifacts = jobItem?.artifact_media_ids ?? [];
	const registered = jobTerminal && jobArtifacts.length > 0;
	// The video exists in Flow (credits spent) but is not bound — status GENERATED/DOWNLOADED
	// or the GENERATED_BUT_UNRETRIEVED marker, with no artifact. This is an honest amber
	// state, NOT a red failure: something WAS generated.
	const generatedNotRegistered = !registered && jobArtifacts.length === 0 &&
		(jobItem?.production_status === "GENERATED" || jobItem?.production_status === "DOWNLOADED" ||
		 String(jobItem?.production_error ?? "").includes("GENERATED_BUT_UNRETRIEVED"));
	// A plain failure: FAILED/CANCELLED with no generated video behind it.
	const plainFailure = Boolean(jobItem?.production_error) && !registered && !generatedNotRegistered;

	useEffect(() => {
		if (stage !== "LIVE_SUBMITTED" || !runId || jobTerminal || isExtend) {
			if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
			return;
		}
		pollRef.current = window.setInterval(() => { void refresh(runId, true); }, POLL_MS);
		return () => { if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; } };
	}, [stage, runId, jobTerminal, refresh, isExtend]);

	// EXTEND job polling — reads the durable orchestrator status (resumable server
	// job; polling never re-submits anything).
	useEffect(() => {
		if (!isExtend || stage !== "LIVE_SUBMITTED" || !extendPlan || extendJob?.complete) return;
		const t = window.setInterval(() => {
			void getVideoJobStatus(extendPlan.job_id).then(setExtendJob).catch(() => undefined);
		}, POLL_MS);
		return () => window.clearInterval(t);
	}, [isExtend, stage, extendPlan, extendJob?.complete]);

	const chip = (label: string, value: string | null, testid: string) => (
		<div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2" data-testid={testid}>
			<div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
			<div className="font-mono text-[11px] text-slate-200 break-all">{value ?? "—"}</div>
		</div>
	);

	return (
		<div className="p-6 max-w-5xl" data-testid="rpa-production-studio" data-stage={stage}>
			<div className="mb-6">
				<h1 className="flex items-center gap-2 text-xl font-bold text-slate-100">
					<Video size={20} className="text-blue-400" /> RPA Production Studio
				</h1>
				<p className="mt-1 text-xs text-slate-400">
					Pick a product, configure the selected generation mode, validate it with a free dry run,
					then run <strong className="text-slate-200">one</strong> live job and see the result.
				</p>
			</div>

			<div className="mb-6 flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3" data-testid="studio-bulk-locked" data-locked="true">
				<Lock size={16} className="text-amber-300 shrink-0" />
				<div className="text-[11px] text-amber-100">
					<strong>MVP scope: one serial output / one queued item only.</strong> Bulk generation is locked;
					the selected mode can only prepare and submit one job at a time.
				</div>
			</div>

			{/* ── 1 · Product ── */}
			<section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
				<h2 className="mb-3 text-sm font-semibold text-slate-200">1 · Choose a product</h2>
				<div className="mb-3 flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2">
					<Search size={14} className="text-slate-500" />
					<input
						data-testid="studio-product-search"
						value={query}
						onChange={(e) => setQuery(e.target.value)}
						onKeyDown={(e) => { if (e.key === "Enter") void loadProducts(query); }}
						placeholder="Search products by name…"
						className="w-full bg-transparent text-[12px] text-slate-100 placeholder:text-slate-600 focus:outline-none"
					/>
					<button type="button" data-testid="studio-product-search-btn" onClick={() => void loadProducts(query)} disabled={loadingProducts}
						className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800 disabled:opacity-40">Search</button>
				</div>

				{productsError && <div className="text-[11px] text-red-300" data-testid="studio-products-error">Could not load products.</div>}
				{loadingProducts && <div className="text-[11px] text-slate-500" data-testid="studio-products-loading">Loading products…</div>}
				{!loadingProducts && !productsError && products.length === 0 && <div className="text-[11px] text-slate-500" data-testid="studio-products-empty">No products found.</div>}

				<div className="max-h-56 space-y-1.5 overflow-y-auto">
					{products.map((p) => (
						<button
							type="button"
							key={p.id}
							data-testid="studio-product-option"
							data-product-id={p.id}
							data-selected={selectedProduct?.id === p.id ? "true" : "false"}
							onClick={() => pickProduct(p)}
							className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors ${selectedProduct?.id === p.id ? "border-blue-500/60 bg-blue-500/10" : "border-slate-800 hover:bg-slate-800/50"}`}
						>
							<span className="min-w-0">
								<span className="block truncate text-[11px] text-slate-200">{p.product_display_name || p.product_short_name || p.id}</span>
								<span className="block font-mono text-[10px] text-slate-500">{p.id}{p.category ? ` · ${p.category}` : ""}</span>
							</span>
							{selectedProduct?.id === p.id && <CheckCircle2 size={14} className="shrink-0 text-blue-400" />}
						</button>
					))}
				</div>
			</section>

			{/* ── 2 · Mode ── */}
			<section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
				<h2 className="mb-3 text-sm font-semibold text-slate-200">2 · Choose a mode</h2>
				<div className="grid grid-cols-2 gap-2 md:grid-cols-5">
					{VIDEO_MODES.map((m) => {
						const Icon = m.icon;
						const selected = studioMode === m.key;
						return (
							<button key={m.key} type="button"
								data-testid={`studio-mode-${m.key.toLowerCase()}`}
								data-enabled="true" data-selected={selected ? "true" : "false"}
								onClick={() => pickMode(m.key)}
								title={m.hint}
								className={`rounded-lg border p-3 text-left ${selected
									? "border-emerald-500/50 bg-emerald-500/10"
									: "border-slate-700 bg-slate-950/60 hover:bg-slate-900"}`}>
								<Icon size={16} className={`mb-1 ${selected ? "text-emerald-300" : "text-slate-400"}`} />
								<div className={`text-[11px] font-semibold ${selected ? "text-emerald-200" : "text-slate-300"}`}>{m.label}</div>
								<div className={`text-[9px] ${selected ? "text-emerald-300/80" : "text-slate-500"}`}>{m.key}{selected ? " · selected" : ""}</div>
							</button>
						);
					})}
					{/* IMG = the FRAME FACTORY, wired as a deep-link into the proven IMG
					    Fastlane flow (compile preview → generate → truth-gated save). It
					    lands there with THIS studio's product pre-selected. Deliberately a
					    link, not a rebuilt flow — the fastlane already owns the truth/save
					    gates and rebuilding them here would be duplication that drifts. */}
					<button type="button" data-testid="studio-mode-img" data-enabled="true"
						onClick={() => {
							const q = selectedProduct ? `?product_id=${encodeURIComponent(selectedProduct.id)}` : "";
							window.location.assign(`/assets/img-fastlane${q}`);
						}}
						title={MODE_PROFILES.IMG.hint}
						className="rounded-lg border border-sky-500/50 bg-sky-500/10 p-3 text-left hover:bg-sky-500/20">
						<ImageIcon size={16} className="mb-1 text-sky-300" />
						<div className="text-[11px] font-semibold text-sky-200">{MODE_PROFILES.IMG.label}</div>
						<div className="text-[9px] text-sky-300/80">IMG · opens Fastlane{selectedProduct ? " with this product" : ""}</div>
					</button>
				</div>
				<p className="mt-2 text-[10px] text-slate-500" data-testid="studio-locked-reason">
					The selected video mode uses its own logical contract and one-serial gate. IMG opens the proven Fastlane frame factory.
				</p>
			</section>

			{/* ── 3 · Configure ── */}
			<section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
				<h2 className="mb-3 text-sm font-semibold text-slate-200">3 · Configure</h2>
				<div className="grid grid-cols-2 gap-3 md:grid-cols-4">
					<label className="block">
						<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Model</span>
						<select data-testid="studio-model" value={model} onChange={(e) => { setModel(e.target.value); resetPipeline(); }}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none">
							{models.length === 0 && <option value="">—</option>}
							{models.map((m) => <option key={m.key} value={m.ui_label}>{m.ui_label}</option>)}
						</select>
					</label>
					<label className="block">
						<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Duration (s)</span>
						<select data-testid="studio-duration" value={duration} onChange={(e) => { setDuration(Number(e.target.value)); resetPipeline(); }}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none">
							{durationOptions.map((d) => (
								<option key={d} value={d}>
									{d > maxSingle ? `${d} — EXTEND multi-block (${d / maxSingle}×${maxSingle}s)` : d}
								</option>
							))}
						</select>
						{isExtend && (
							<span className="mt-0.5 block text-[9px] text-sky-300" data-testid="studio-extend-note">
								Multi-block EXTEND — per-block 9-section prompts, WPS dialogue budgets, seam handoff + final concat.
							</span>
						)}
					</label>
					<label className="block">
						<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Aspect</span>
						<select data-testid="studio-aspect" value={aspect} onChange={(e) => { setAspect(e.target.value); resetPipeline(); }}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none">
							{ASPECTS.map((a) => <option key={a} value={a}>{a}</option>)}
						</select>
					</label>
					<div data-testid="studio-quantity-status" className="block">
						<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Quantity (preview)</span>
						<input type="number" data-testid="studio-quantity-input" min={1} max={QUANTITY_MAX} value={quantity}
							onChange={(e) => {
								const n = Math.max(1, Math.min(QUANTITY_MAX, Math.floor(Number(e.target.value) || 1)));
								setQuantity(n);
								resetPipeline();
							}}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none" />
						<div className="mt-1 text-[9px] text-slate-500" data-testid="studio-quantity-note">
							{bulkPreview
								? `1–${QUANTITY_MAX}. Quantity > 1 is preview-only — live bulk fan-out is Stage 2.`
								: "1 = single live run. Raise for a credit-free unique-copy preview."}
						</div>
					</div>
				</div>

				{/* Per-mode reference pickers (APPROVED assets only; server re-validates). */}
				{activeProfile.referenceKind === "frame" && (
					<div className="mt-3" data-testid="studio-refs-f2v">
						<label className="block">
							<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Start frame (approved 9:16 composite)</span>
							<select data-testid="studio-ref-start-frame" value={startFrameAssetId}
								onChange={(e) => { setStartFrameAssetId(e.target.value); resetPipeline(); }}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none">
								<option value="">— choose a start frame —</option>
								{frameAssets.map((a) => <option key={a.asset_id} value={a.asset_id}>{a.display_name}</option>)}
							</select>
						</label>
						{frameAssets.length === 0 && (
							<p className="mt-1 text-[10px] text-amber-300" data-testid="studio-refs-f2v-empty">
								No approved 9:16 frames for this product yet — make one with the <strong>Image · Frame Factory</strong> card, approve it, then come back.
							</p>
						)}
					</div>
				)}
				{activeProfile.referenceKind === "product_anchor" && (
					<div className="mt-3" data-testid="studio-refs-hybrid">
						<label className="block">
							<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Product anchor (approved, 9:16)</span>
							<select data-testid="studio-ref-product" value={productRefAssetId}
								onChange={(e) => { setProductRefAssetId(e.target.value); resetPipeline(); }}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none">
								<option value="">— choose a product anchor —</option>
								{productRefAssets.map((a) => <option key={a.asset_id} value={a.asset_id}>{a.display_name}</option>)}
							</select>
						</label>
					</div>
				)}
				{activeProfile.referenceKind === "ingredients" && (
					<div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2" data-testid="studio-refs-i2v">
						<label className="block">
							<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Character reference</span>
							<select data-testid="studio-ref-character" value={characterAssetId}
								onChange={(e) => { setCharacterAssetId(e.target.value); resetPipeline(); }}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none">
								<option value="">— choose a character —</option>
								{characterAssets.map((a) => <option key={a.asset_id} value={a.asset_id}>{a.display_name}</option>)}
							</select>
						</label>
						<label className="block">
							<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Scene reference</span>
							<select data-testid="studio-ref-scene" value={sceneAssetId}
								onChange={(e) => { setSceneAssetId(e.target.value); resetPipeline(); }}
								className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none">
								<option value="">— choose a scene —</option>
								{sceneAssets.map((a) => <option key={a.asset_id} value={a.asset_id}>{a.display_name}</option>)}
							</select>
						</label>
					</div>
				)}
			</section>

			{error && (
				<div className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200" data-testid="studio-error">
					<AlertTriangle size={14} className="mt-0.5 shrink-0" /><span>{error}</span>
				</div>
			)}

			{/* ── 4 · Prepare & validate ── */}
			<section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4" data-testid="studio-prepare-panel">
				<h2 className="mb-3 text-sm font-semibold text-slate-200">4 · Prepare &amp; validate (no credits)</h2>
				<div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-4">
					{chip("Product", selectedProduct?.id ?? null, "studio-status-product")}
					{isExtend
						? chip("WEP id", wepId, "studio-status-wep")
						: chip("WGP id", wgpId, "studio-status-wgp")}
					{isExtend
						? chip("Video job", extendPlan?.job_id ?? null, "studio-status-videojob")
						: chip("Run id", runId, "studio-status-run")}
					{isExtend
						? chip("Reviewed plan", extendPlan ? `${extendPlan.plan.segment_count} segments · fp ${extendPlan.plan_fingerprint.slice(0, 10)}…` : null, "studio-status-extend-plan")
						: chip("Dry-run ready", report ? `${report.ready ?? 0}/${report.checked ?? 0} · blocked ${report.blocked ?? 0}` : null, "studio-status-dryrun")}
				</div>
				<div className="flex flex-wrap gap-2">
					<button type="button" data-testid="studio-action-prepare" onClick={() => void handlePrepare()}
						disabled={!selectedProduct || !refsChosen || busy !== null || stage !== "IDLE" || bulkPreview}
						className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/50 bg-blue-500/15 px-3 py-2 text-[11px] font-semibold text-blue-100 hover:bg-blue-500/25 disabled:cursor-not-allowed disabled:opacity-40">
						{busy === "prepare" ? <Loader2 size={12} className="animate-spin" /> : <PackageCheck size={12} />}
						{isExtend ? "Prepare EXTEND package + reviewed plan" : "Prepare package"}
					</button>
					{!isExtend && (
						<button type="button" data-testid="studio-action-validate" onClick={() => void handleValidate()}
							disabled={!runId || busy !== null || stage !== "PREPARED"}
							className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/50 bg-emerald-500/15 px-3 py-2 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40">
							{busy === "validate" ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Run validation (dry run)
						</button>
					)}
					<button type="button" data-testid="studio-action-preview" onClick={() => void handlePreviewQuantity()}
						disabled={!selectedProduct || busy !== null}
						className="inline-flex items-center gap-1.5 rounded-lg border border-violet-500/50 bg-violet-500/15 px-3 py-2 text-[11px] font-semibold text-violet-100 hover:bg-violet-500/25 disabled:cursor-not-allowed disabled:opacity-40">
						{busy === "preview" ? <Loader2 size={12} className="animate-spin" /> : <PackageCheck size={12} />}
						{bulkPreview ? `Preview ${quantity} unique copy plans (no credit)` : "Preview copy plan (no credit)"}
					</button>
				</div>

				{isExtend && extendPlan && (
					<div className="mt-3 rounded-lg border border-sky-500/30 bg-sky-500/5 p-3" data-testid="studio-extend-plan"
						data-segments={String(extendPlan.plan.segment_count)} data-fingerprint={extendPlan.plan_fingerprint}>
						<div className="text-[11px] text-sky-200">
							Reviewed multi-block plan · <strong>{extendPlan.plan.requested_seconds}s</strong> total ·{" "}
							<strong>{extendPlan.plan.segment_count}</strong> segments ·{" "}
							{extendPlan.plan.operation_counts.initial_generation} initial + {extendPlan.plan.operation_counts.extend} extend + {extendPlan.plan.operation_counts.final_render} concat
							<span className="ml-2 text-sky-300/70">· plan only — no provider call, no credit</span>
						</div>
						{extendBlockCount != null && (
							<div className="mt-1 text-[10px] text-sky-300/90" data-testid="studio-extend-blocks">
								{extendBlockCount} canonical 9-section block prompt{extendBlockCount === 1 ? "" : "s"} compiled (ADR-008 — the final prompt of every block).
							</div>
						)}
						{extendWpsBudgets && extendWpsBudgets.length > 0 && (
							<div className="mt-1 flex flex-wrap gap-1.5" data-testid="studio-extend-wps">
								{extendWpsBudgets.map((b, i) => (
									<span key={`${i}-${b}`} data-testid="studio-extend-wps-block"
										className="rounded border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-[9px] text-sky-200">
										Block {i + 1}: ≤{b} dialogue words (WPS budget)
									</span>
								))}
							</div>
						)}
					</div>
				)}

				{report && (
					<div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3" data-testid="studio-dryrun-report" data-ready={String(report.ready ?? 0)} data-blocked={String(report.blocked ?? 0)}>
						<div className="text-[11px] text-slate-300">
							Checked <strong>{report.checked ?? 0}</strong> · Ready <strong className="text-emerald-300">{report.ready ?? 0}</strong> · Blocked <strong className={report.blocked ? "text-red-300" : "text-slate-300"}>{report.blocked ?? 0}</strong>
							<span className="ml-2 text-emerald-300/80">· no provider call, no credit</span>
						</div>
						{(report.items ?? []).map((it) => it.ok === false && (
							<ul key={it.package_id} className="mt-1 pl-4" data-testid="studio-dryrun-blockers">
								{(it.blockers ?? []).map((b) => <li key={b} data-testid="studio-blocker" className="list-disc text-[10px] text-red-300">{displayBlocker(b, activeProfile)}</li>)}
							</ul>
						))}
					</div>
				)}
			</section>

			<section className="mb-6 rounded-xl border border-violet-500/30 bg-violet-500/5 p-4" data-testid="studio-quantity-preview-section">
				<h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-violet-200"><Sparkles size={14} /> 4b · Quantity preview (credit-free · Stage 1)</h2>
				{poolReadiness && (
					<div
						className={`mb-2 rounded-lg border p-3 text-[11px] ${
							poolReadiness.readiness_status === "READY"
								? "border-emerald-500/40 bg-emerald-500/10 text-emerald-100"
								: "border-amber-500/40 bg-amber-500/10 text-amber-100"
						}`}
						data-testid="studio-copy-pool-readiness"
						data-readiness={poolReadiness.readiness_status}
						data-approved={String(poolReadiness.approved_copy_count)}
						data-unique={String(poolReadiness.unique_dialogue_count)}
						data-shortage={String(poolReadiness.shortage_count)}
					>
						<div>
							Approved copy pool — approved <strong>{poolReadiness.approved_copy_count}</strong> ·
							unique dialogue <strong data-testid="studio-copy-pool-unique">{poolReadiness.unique_dialogue_count}</strong> ·
							needed <strong>{poolReadiness.quantity_requested}</strong>
						</div>
						{poolReadiness.readiness_status !== "READY" && (
							<div className="mt-1" data-testid="studio-copy-pool-shortage">
								<strong>
									{poolReadiness.readiness_status === "NO_APPROVED_COPY_AVAILABLE"
										? "No approved copy for this product yet."
										: `Short by ${poolReadiness.shortage_count} unique dialogue${poolReadiness.shortage_count === 1 ? "" : "s"}.`}
								</strong>{" "}
								Preview is blocked until the pool can supply {poolReadiness.quantity_requested} unique
								approved dialogues. Generate candidates and approve them, then preview again —
								no credit is spent either way.
								<div className="mt-1.5">
									<Link
										to={`/creative/copy-registry?product_id=${encodeURIComponent(poolReadiness.product_id)}`}
										className="inline-block rounded-md border border-amber-400/50 bg-amber-500/20 px-2 py-1 font-semibold text-amber-50 hover:bg-amber-500/30"
										data-testid="studio-copy-pool-seed-cta"
									>
										Open Copy Registry to generate + approve copy →
									</Link>
								</div>
							</div>
						)}
						{poolReadiness.pool_scan_capped && (
							<div className="mt-1 text-[10px] opacity-80" data-testid="studio-copy-pool-capped">
								Scanned the first {poolReadiness.scanned_copy_set_count} approved sets of{" "}
								{poolReadiness.approved_copy_count}; deeper duplicates were not scanned.
							</div>
						)}
					</div>
				)}
				{previewError && (
					<div className="mb-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200" data-testid="studio-quantity-preview-error">
						Preview failed — nothing fired, no credit: {previewError}
					</div>
				)}
				{previewResult ? (
					<div data-testid="studio-quantity-preview" data-uniqueness={previewResult.dialogue_uniqueness_status} data-ready={String(previewResult.preview_ready)} data-count={String(previewResult.planned_item_count)}>
						<div className="text-[11px] text-violet-200">
							Quantity <strong>{previewResult.quantity_requested}</strong> · planned <strong>{previewResult.planned_item_count}</strong> · dialogue uniqueness{" "}
							<strong data-testid="studio-preview-uniqueness" className={previewResult.dialogue_uniqueness_status === "UNIQUE" ? "text-emerald-300" : "text-red-300"}>{previewResult.dialogue_uniqueness_status}</strong>
							<span className="ml-2 text-emerald-300/80">· no provider call, no credit</span>
						</div>
						<div className="mt-1 text-[10px] text-amber-300" data-testid="studio-preview-live-status">
							{previewResult.live_bulk_status} ({previewResult.live_bulk_stage})
						</div>
						{previewResult.blockers.length > 0 && (
							<ul className="mt-2 pl-4" data-testid="studio-preview-blockers">
								{previewResult.blockers.map((b) => <li key={b} data-testid="studio-preview-blocker" className="list-disc text-[10px] text-red-300">{b}</li>)}
							</ul>
						)}
						<div className="mt-2 space-y-1.5">
							{previewResult.items.map((it) => (
								<div key={it.item_index} data-testid="studio-preview-item" data-index={String(it.item_index)}
									className="rounded border border-slate-800 bg-slate-950/60 px-2 py-1.5">
									<div className="flex items-center justify-between text-[10px] text-slate-400">
										<span>#{it.item_index + 1} · variant {it.copy_variant_id ?? "—"} · {it.variation_salt}</span>
										<span className="font-mono text-slate-500">fp {it.dialogue_fingerprint ? it.dialogue_fingerprint.slice(0, 8) : "—"}</span>
									</div>
									<div className="mt-0.5 text-[10px] text-slate-200" data-testid="studio-preview-dialogue">
										{it.compile_error ? <span className="text-red-300">compile error: {it.compile_error}</span> : (it.dialogue_summary || "(no dialogue)")}
									</div>
									{it.seam_voice && (
										<div className="mt-0.5 text-[9px] text-sky-300/80" data-testid="studio-preview-seam-voice">
											seam/voice lock: {String((it.seam_voice as Record<string, unknown>).voice_profile_lock ?? "—")} · out {String((it.seam_voice as Record<string, unknown>).outgoing_dialogue_deadline_s ?? "—")}s · in-floor {String((it.seam_voice as Record<string, unknown>).incoming_new_dialogue_onset_floor_s ?? "—")}s
										</div>
									)}
								</div>
							))}
						</div>
					</div>
				) : (
					<div className="text-[11px] text-slate-500" data-testid="studio-preview-empty">
						Set a quantity and click <strong>Preview</strong> to plan N unique-copy variants credit-free. Live bulk fan-out is Stage 2 (not enabled yet).
					</div>
				)}
			</section>
			{bulkPlan && (
				<section
					className="mb-6 rounded-xl border border-sky-500/30 bg-sky-500/5 p-4"
					data-testid="studio-bulk-fanout-section"
					data-authorizable={String(bulkPlan.bulk_authorizable)}
					data-intent-count={String(bulkPlan.planned_intent_count)}
					data-stage={bulkPlan.live_bulk_stage}
				>
					<h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-sky-200">
						<Layers size={14} /> 4c · Itemized bulk fan-out (credit-free plan · Stage 2A)
					</h2>
					<div className="mb-2 text-[11px] text-sky-200">
						<strong>{bulkPlan.planned_intent_count}</strong> separate production intents —
						not one <code>count:N</code> submission. Each item is its own credit event.
					</div>
					{bulkPlan.blockers.length > 0 && (
						<ul className="mb-2 space-y-1" data-testid="studio-bulk-blockers">
							{bulkPlan.blockers.map((b) => (
								<li key={b} className="rounded border border-red-500/40 bg-red-500/10 px-2 py-1 text-[11px] text-red-200" data-testid="studio-bulk-blocker">{b}</li>
							))}
						</ul>
					)}
					<div className="mb-2 space-y-1.5">
						{bulkPlan.intents.map((it) => (
							<div
								key={`${it.item_index}-${it.dialogue_fingerprint}`}
								className="rounded-lg border border-slate-700 bg-slate-900/50 p-2 text-[10px] text-slate-300"
								data-testid="studio-bulk-intent"
								data-index={String(it.item_index)}
								data-status={it.item_status}
								data-credit={it.credit_state}
								data-variant={it.copy_variant_id ?? ""}
								data-fingerprint={it.dialogue_fingerprint ?? ""}
							>
								<div className="flex flex-wrap gap-x-3 gap-y-0.5 text-slate-400">
									<span>#{(it.item_index ?? 0) + 1}</span>
									<span>salt {it.variation_salt ?? "—"}</span>
									<span>copy {it.copy_variant_id ?? "—"}</span>
									<span>fp {(it.dialogue_fingerprint ?? "").slice(0, 8) || "—"}</span>
									<span>{it.logical_mode}/{it.generation_mode}</span>
									<span className="text-amber-300">{it.credit_state}</span>
								</div>
								{it.dialogue_summary && <div className="mt-0.5 text-slate-300">{it.dialogue_summary}</div>}
							</div>
						))}
					</div>
					<div className="mb-2 flex flex-wrap items-center gap-2">
						<button
							type="button"
							data-testid="studio-action-bulk-prepare"
							onClick={() => void handleBulkPrepare()}
							disabled={!bulkPlan.bulk_authorizable || busy !== null || Boolean(bulkPrepared) || i2vBulkRefsMissing}
							className="rounded-lg bg-sky-600 px-3 py-1.5 text-[11px] font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
						>
							{busy === "bulk-prepare"
								? "Preparing…"
								: `Prepare ${bulkPlan.planned_intent_count} packages (no credit)`}
						</button>
						<span className="text-[10px] text-slate-400">
							Creates + approves + queues {bulkPlan.planned_intent_count} separate packages, then dry-runs every item. Nothing fires.
						</span>
					</div>
					{i2vBulkRefsMissing && (
						<div className="mb-2 text-[10px] text-amber-300" data-testid="studio-bulk-i2v-refs-missing">
							Select a character reference and a scene-context reference before bulk prepare — I2V references are not auto-seeded.
						</div>
					)}
					{bulkError && (
						<div className="mb-2 rounded-lg border border-red-500/40 bg-red-500/10 p-2 text-[11px] text-red-200" data-testid="studio-bulk-prepare-error">
							Bulk prepare refused — nothing created, no credit: {bulkError}
						</div>
					)}
					{bulkPrepared && (
						<div
							className="mb-2 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-2 text-[11px] text-emerald-100"
							data-testid="studio-bulk-prepared"
							data-stage={bulkPrepared.stage}
							data-package-count={String(bulkPrepared.prepared_package_count)}
							data-run={bulkPrepared.production_run_id ?? ""}
							data-reused={String(bulkPrepared.reused_existing_batch)}
						>
							<div>
								<strong>{bulkPrepared.prepared_package_count}</strong> packages prepared and queued
								{bulkPrepared.production_run_id ? <> in run <code>{bulkPrepared.production_run_id}</code></> : null}.
								{bulkPrepared.reused_existing_batch ? " (existing batch reused — no duplicates created)" : ""}
							</div>
							<div className="mt-1 space-y-0.5">
								{bulkPrepared.items.map((it) => (
									<div key={it.workspace_generation_package_id}
										className="text-[10px] text-slate-300"
										data-testid="studio-bulk-package"
										data-index={String(it.item_index)}
										data-package={it.workspace_generation_package_id}
										data-variant={it.copy_variant_id ?? ""}
										data-fingerprint={it.dialogue_fingerprint ?? ""}
										data-status={it.item_status}>
										#{(it.item_index ?? 0) + 1} · <code>{it.workspace_generation_package_id}</code> · copy {it.copy_variant_id ?? "—"} · fp {(it.dialogue_fingerprint ?? "").slice(0, 8)} · {it.item_status}
									</div>
								))}
							</div>
							{bulkDryRun && (
								<div className="mt-1.5 rounded border border-slate-600 bg-slate-900/50 px-2 py-1 text-[10px] text-slate-300"
									data-testid="studio-bulk-dryrun"
									data-checked={String(bulkDryRun.checked ?? 0)}
									data-ready={String(bulkDryRun.ready ?? 0)}
									data-blocked={String(bulkDryRun.blocked ?? 0)}>
									<div>Dry run — checked {bulkDryRun.checked ?? 0} · ready {bulkDryRun.ready ?? 0} · blocked {bulkDryRun.blocked ?? 0} (no credit)</div>
									{/* A bare "blocked 2" is unactionable. The server already returns the
									    exact per-item reasons in report.items[].blockers — surface them,
									    translated to the operator's next action where we know it. */}
									{(bulkDryRun.items ?? []).filter((it) => it.ok === false).length > 0 && (
										<div className="mt-1 space-y-1" data-testid="studio-bulk-dryrun-blocked">
											{(bulkDryRun.items ?? []).filter((it) => it.ok === false).map((it, i) => (
												<div key={it.package_id ?? i}
													className="rounded border border-red-500/40 bg-red-500/10 px-1.5 py-1"
													data-testid="studio-bulk-dryrun-blocked-item"
													data-package={it.package_id ?? ""}
													data-ok="false">
													<div className="text-[10px] text-red-200">
														BLOCKED · <code>{it.package_id ?? "—"}</code>
													</div>
													<ul className="mt-0.5 pl-4">
														{(it.blockers ?? []).map((b) => (
															<li key={b} data-testid="studio-bulk-dryrun-blocker"
																className="list-disc text-[10px] text-red-300">
																{displayBlocker(b, activeProfile)}
															</li>
														))}
													</ul>
												</div>
											))}
										</div>
									)}
								</div>
							)}
						</div>
					)}
					{bulkManualHandoff && (
						<section className="mb-2 rounded-lg border border-cyan-500/40 bg-cyan-500/5 p-3" data-testid="studio-bulk-manual-handoff" data-automation="disabled">
							<h3 className="text-[11px] font-semibold text-cyan-100">Manual Fire Handoff — operator action outside this app</h3>
							<p className="mt-1 text-[10px] text-cyan-100/80">Every item passed the credit-free dry run. Automated bulk live remains disabled; copy each exact package instruction into Google Flow, fire manually, then capture the returned identity here.</p>
							<div className="mt-2 space-y-3">
								{bulkManualHandoff.items.map((item) => {
									const input = bulkManualInputs[item.workspace_generation_package_id] ?? { provider_job_id: "", flow_media_id: "", result_url: "", result_file_id: "", notes: "" };
									const resultBound = Boolean(item.result);
									return <div key={item.workspace_generation_package_id} className="rounded border border-slate-700 bg-slate-950/60 p-2" data-testid="studio-manual-handoff-item" data-package={item.workspace_generation_package_id} data-complete={String(resultBound)}>
										<div className="text-[10px] text-slate-200">#{item.item_index + 1} · <code>{item.workspace_generation_package_id}</code> · {item.mode}/{item.source_mode ?? "—"}</div>
										<div className="mt-0.5 text-[9px] text-slate-400">copy {item.copy_variant_id} · fp {item.dialogue_fingerprint.slice(0, 12)} · {item.expected.aspect ?? "aspect —"} · {item.expected.duration_seconds ?? "duration —"}s · {item.expected.model ?? "model —"}</div>
										<div className="mt-1 text-[9px] text-slate-400">Upload order: {item.upload_order.join(", ") || "none"}</div>
										<textarea readOnly value={item.prompt} data-testid="studio-manual-handoff-prompt" className="mt-1 min-h-20 w-full rounded border border-slate-700 bg-slate-900 p-1.5 font-mono text-[9px] text-slate-200" aria-label={`Manual prompt for ${item.workspace_generation_package_id}`} />
										{resultBound ? <div className="mt-1 text-[10px] text-emerald-300" data-testid="studio-manual-result-bound">Manual result recorded: {item.result?.provider_job_id ?? item.result?.flow_media_id}</div> : <>
											<div className="mt-2 grid grid-cols-1 gap-1 md:grid-cols-2">
												{(["provider_job_id", "flow_media_id", "result_url", "result_file_id", "notes"] as const).map((field) => <input key={field} data-testid={`studio-manual-result-${field}`} value={input[field]} onChange={(event) => setBulkManualInputs((current) => ({ ...current, [item.workspace_generation_package_id]: { ...input, [field]: event.target.value } }))} placeholder={field.replaceAll("_", " ")} className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[10px] text-slate-100" />)}
											</div>
											<button type="button" data-testid="studio-action-bind-manual-result" onClick={() => void handleBulkManualResult(item)} disabled={busy !== null || (!input.provider_job_id.trim() && !input.flow_media_id.trim())} className="mt-2 rounded bg-cyan-700 px-2 py-1 text-[10px] font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-700">{busy === `manual-result-${item.workspace_generation_package_id}` ? "Binding…" : "Bind manual result"}</button>
										</>}
									</div>;
								})}
							</div>
						</section>
					)}
					<div
						className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100"
						data-testid="studio-bulk-live-gate-state"
						data-live-blocked={bulkLiveGateOpen ? "false" : "true"}
						data-dryrun-green={String(bulkDryRunGreen)}
						data-pins-complete={String(bulkPinsComplete)}
						data-phrase-ok={String(bulkPhraseOk)}
					>
						<strong>{bulkPlan.live_bulk_status} — {bulkPlan.live_bulk_stage}.</strong>{" "}
						This plan spends no credit and does not authorize a live run. Bulk live
						additionally requires the server <code>BULK_FANOUT</code> gate with the phrase{" "}
						<code>{bulkPlan.required_confirm_phrase}</code>. The server refuses at the
						credit boundary until bulk live is runtime-certified.
					</div>
					{/* ── System-fired bulk live: the APP submits each item as its own
					     provider job through the BULK_FANOUT gate. Manual handoff above
					     stays available as the fallback, not a replacement. ── */}
					{bulkPrepared?.production_run_id && (
						<section
							className="mt-2 rounded-lg border border-red-500/40 bg-red-500/5 p-3"
							data-testid="studio-bulk-live-fire"
							data-gate-open={bulkLiveGateOpen ? "true" : "false"}
							data-run={bulkPrepared.production_run_id}
							data-item-count={String(bulkPreparedCount)}
						>
							<h3 className="text-[11px] font-semibold text-red-200">
								Automated bulk live — system fires {bulkPreparedCount} separate provider jobs
							</h3>
							<p className="mt-1 text-[10px] text-red-100/90">
								<strong>This spends real credits.</strong> Each item is submitted as its
								own provider job (never one job with count={bulkPreparedCount}), serially,
								with per-item identity and evidence. After submission, do not retry unless
								the system proves no provider submission occurred.
							</p>
							<div className="mt-2 flex flex-wrap items-center gap-2">
								<input
									data-testid="studio-bulk-live-phrase"
									value={bulkLivePhrase}
									onChange={(e) => setBulkLivePhrase(e.target.value)}
									placeholder={LIVE_BULK_CONFIRM_PHRASE}
									aria-label="Bulk live confirmation phrase"
									className="w-72 rounded border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[10px] text-slate-100"
								/>
								<button
									type="button"
									data-testid="studio-action-bulk-go-live"
									onClick={() => void handleBulkGoLive()}
									disabled={!bulkLiveGateOpen}
									className="rounded-lg bg-red-600 px-3 py-1.5 text-[11px] font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
								>
									{busy === "bulk-live"
										? "Firing…"
										: `Fire ${bulkPreparedCount} live jobs`}
								</button>
							</div>
							{!bulkLiveGateOpen && !bulkLiveAlreadySubmitted && (
								<div className="mt-1.5 text-[10px] text-amber-300" data-testid="studio-bulk-live-blockers">
									{!bulkDryRunGreen && <div>Needs a green dry run: ready={bulkPreparedCount} blocked=0.</div>}
									{!bulkPinsComplete && <div>Needs complete pinned package ids + dialogue fingerprints.</div>}
									{!bulkPhraseOk && <div>Type the exact phrase <code>{LIVE_BULK_CONFIRM_PHRASE}</code>.</div>}
								</div>
							)}
							{bulkLiveStatus && (
								<div className="mt-1.5 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-100" data-testid="studio-bulk-live-submitted" data-status={bulkLiveStatus}>
									Bulk live submitted — run status <code>{bulkLiveStatus}</code>. Items fire serially; watch per-item evidence.
								</div>
							)}
							{bulkLiveError && (
								<div className="mt-1.5 rounded border border-red-500/40 bg-red-500/10 px-2 py-1 text-[10px] text-red-200" data-testid="studio-bulk-live-error">
									Bulk live refused by the server: {bulkLiveError}
								</div>
							)}
						</section>
					)}
				</section>
			)}
			{/* ── 5 · One live T2V ── */}
			<section className="mb-6 rounded-xl border border-red-500/40 bg-red-500/5 p-4" data-testid="studio-live-gate" data-gate-open={(isExtend ? extendGateOpen : liveGateOpen) ? "true" : "false"} data-lane={isExtend ? "EXTEND" : "SINGLE"}>
				<h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-red-200"><Flame size={14} /> 5 · {isExtend ? `Run one live EXTEND job (${duration}s multi-block)` : `Run one live ${studioMode}`}</h2>
				{bulkPreview && (
					<div className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-100" data-testid="studio-live-bulk-blocked" data-blocked="true">
						<strong>Bulk live fan-out not enabled yet — Stage 2 required.</strong> Quantity {quantity} is preview-only: no live submission, no provider call, no credit. Set quantity to 1 to run one live item.
					</div>
				)}
				<div className="mb-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-[11px] text-red-100" data-testid="studio-live-warning">
					<strong>This spends real credits.</strong>{" "}
					{isExtend
						? `It authorizes the reviewed plan fingerprint and runs the full durable job: 1 initial + ${extendPlan?.plan.operation_counts.extend ?? "N"} extend + final concat. The server re-gates every stage with the plan-bound token.`
						: activeProfile.liveWarning}
				</div>
				<div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-3" data-testid="studio-live-checks">
					{(isExtend
						? [
							{ id: "product", label: "Product selected", ok: Boolean(selectedProduct) },
							{ id: "extend-plan", label: "Reviewed orchestrator plan", ok: extendPlanReady },
							{ id: "phrase", label: "Confirmation phrase", ok: extendPhraseOk },
							{ id: "not-submitted", label: "Not already submitted", ok: !liveSubmitted },
						]
						: [
							{ id: "product", label: "Product selected", ok: Boolean(selectedProduct) },
							{ id: "dryrun", label: "Dry run ready=1 blocked=0", ok: Boolean(dryRunGreen) },
							{ id: "one-item", label: "Exactly 1 item", ok: oneItemOnly },
							{ id: "no-prior-job", label: "No prior provider job", ok: noPriorJob },
							{ id: "phrase", label: "Confirmation phrase", ok: phraseOk },
							{ id: "not-submitted", label: "Not already submitted", ok: !liveSubmitted },
						]).map((c) => (
						<div key={c.id} data-testid={`studio-check-${c.id}`} data-ok={c.ok ? "true" : "false"}
							className={`rounded-lg border px-2 py-1.5 text-[10px] ${c.ok ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-200" : "border-slate-700 bg-slate-900/60 text-slate-500"}`}>
							{c.ok ? "✓" : "○"} {c.label}
						</div>
					))}
				</div>
				{/* Flow tab readiness — ADVISORY (both failure modes are proven 0-credit +
					    retryable): pre-flight/runtime status only. It never replaces the
					    server's credit and phrase gates, and does not block this button. */}
				<div className="mb-3 flex flex-wrap items-center gap-2" data-testid="studio-flowtab-row">
					<span className={`rounded border px-2 py-1 text-[10px] ${flowTab?.ready ? "border-emerald-500/40 text-emerald-200" : "border-amber-500/40 text-amber-200"}`}
						data-testid="studio-flowtab-ready" data-ok={flowTab?.ready ? "true" : "false"}>
						{flowTab == null ? "Flow tab: unknown" : flowTab.ready ? "Flow editor open ✓" : "Flow editor NOT ready"}
					</span>
					<span className={`rounded border px-2 py-1 text-[10px] ${flowTab?.buildMatch ? "border-emerald-500/40 text-emerald-200" : "border-amber-500/40 text-amber-200"}`}
						data-testid="studio-flowtab-build" data-ok={flowTab?.buildMatch ? "true" : "false"}>
						{flowTab == null ? "build: unknown" : flowTab.buildMatch ? "content script fresh ✓" : "content script STALE — reload the Flow tab"}
					</span>
					<button type="button" data-testid="studio-flowtab-open"
						onClick={() => { void openFlowNewProject(activeProfile.flowDiagnosticMode ?? "F2V").then(() => window.setTimeout(() => void refreshFlowTab(), 6000)); }}
						disabled={busy !== null}
						className="rounded-lg border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800 disabled:opacity-40">
						Open fresh Flow project
					</button>
					<button type="button" data-testid="studio-flowtab-refresh"
						onClick={() => void refreshFlowTab()} disabled={busy !== null}
						className="rounded-lg border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800 disabled:opacity-40">
						Re-check
					</button>
					<span className="text-[9px] text-slate-500">Pre-flight/runtime status only. Fire into a fresh clean project; after opening, wait ~40s (warm-up) before firing.</span>
				</div>
				<label className="mb-1 block text-[10px] uppercase tracking-wider text-slate-400" htmlFor="studio-phrase">
					Type <code className="text-red-300">{isExtend ? EXTEND_CONFIRM_PHRASE : lanePhrase}</code> to authorize {isExtend ? "the EXTEND plan" : activeProfile.referenceKind === "product_anchor" ? "one HYBRID product-anchor run" : `one ${activeProfile.label} run`}
				</label>
				<input id="studio-phrase" data-testid="studio-phrase-input" type="text" value={phrase} disabled={liveSubmitted}
					onChange={(e) => setPhrase(e.target.value)} placeholder={isExtend ? EXTEND_CONFIRM_PHRASE : lanePhrase} autoComplete="off" spellCheck={false}
					className="mb-3 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-[11px] text-slate-100 placeholder:text-slate-700 focus:border-red-500/60 focus:outline-none disabled:opacity-40" />
				<button type="button" data-testid="studio-action-go-live" data-enabled={(isExtend ? extendGateOpen : liveGateOpen) ? "true" : "false"}
					onClick={() => void (isExtend ? handleGoLiveExtend() : handleGoLive())} disabled={isExtend ? !extendGateOpen : !liveGateOpen}
					className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/60 bg-red-500/20 px-3 py-2 text-[11px] font-semibold text-red-100 hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-40">
					{busy === "live" ? <Loader2 size={12} className="animate-spin" /> : <Flame size={12} />}
					{liveSubmitted
						? "Live run submitted"
						: isExtend
							? `Run ONE live EXTEND job — ${duration}s multi-block (burns credits)`
							: `Run ONE live ${studioMode} (burns credits)`}
				</button>
				{liveError && (
					<div className="mt-3 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200" data-testid="studio-live-refused">
						<AlertTriangle size={14} className="mt-0.5 shrink-0" />
						<span><strong>Live run refused — nothing fired.</strong> {explainFailure(liveError)}</span>
					</div>
				)}
			</section>

			{/* ── 6 · Result ── */}
			<section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4" data-testid="studio-result-panel">
				<div className="mb-3 flex items-center justify-between">
					<h2 className="text-sm font-semibold text-slate-200">6 · Result</h2>
					{stage === "LIVE_SUBMITTED" && (
						<button type="button" data-testid="studio-action-refresh" onClick={() => void refresh()} disabled={busy !== null}
							className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] text-slate-300 hover:bg-slate-800 disabled:opacity-40">
							<RefreshCw size={12} className={busy === "refresh" ? "animate-spin" : ""} /> Refresh
						</button>
					)}
				</div>

				{stage !== "LIVE_SUBMITTED" && <div className="text-[11px] text-slate-500" data-testid="studio-result-empty">No live job yet. The result appears here after you run one.</div>}

				{stage === "LIVE_SUBMITTED" && isExtend && (
					<div data-testid="studio-extend-result" data-job-status={extendJob?.status ?? ""} data-complete={extendJob?.complete ? "true" : "false"}>
						<div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-3">
							{chip("Video job", extendPlan?.job_id ?? null, "studio-extend-result-job")}
							{chip("Status", extendJob?.status ?? null, "studio-extend-result-status")}
							{chip("Stage", extendJob?.human_stage ?? null, "studio-extend-result-stage")}
							{chip("Credits", extendJob?.credit_summary ?? null, "studio-extend-result-credits")}
							{chip("Final duration", extendJob?.final_duration_s != null ? `${extendJob.final_duration_s}s` : null, "studio-extend-result-duration")}
						</div>
						{!extendJob?.complete && (
							<div className="flex items-center gap-2 text-[11px] text-slate-400" data-testid="studio-extend-result-inflight">
								<Loader2 size={12} className="animate-spin" /> Durable job advancing — polling every {POLL_MS / 1000}s. Polling never re-submits.
							</div>
						)}
						{extendJob?.error_code && (
							<div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200" data-testid="studio-extend-result-error">
								<strong>Job error.</strong> {explainFailure(extendJob.error_code)}
							</div>
						)}
						{extendJob?.complete && extendJob?.final_media_id && (
							<div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-[11px] text-emerald-200" data-testid="studio-extend-result-success">
								<strong>Complete ✓ — final concatenated video.</strong>{" "}
								<a data-testid="studio-extend-result-final" data-media-id={extendJob.final_media_id}
									href={`/api/flow/retrieved/${encodeURIComponent(extendJob.final_media_id)}`}
									target="_blank" rel="noreferrer" className="font-mono underline hover:text-emerald-100">
									{extendJob.final_media_id}
								</a>
							</div>
						)}
					</div>
				)}

				{stage === "LIVE_SUBMITTED" && !isExtend && (
					<div data-testid="studio-result" data-job-status={jobItem?.production_status ?? ""} data-terminal={jobTerminal ? "true" : "false"} data-registered={registered ? "true" : "false"}>
						<div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-3">
							{chip("Run id", runId, "studio-result-run")}
							{chip("WGP id", wgpId, "studio-result-wgp")}
							{chip("Provider job id", jobItem?.production_job_id ?? null, "studio-result-job")}
							{chip("Item status", jobItem?.production_status ?? null, "studio-result-status")}
							{chip("Run status", runStatus, "studio-result-runstatus")}
						</div>

						{!jobTerminal && (
							<div className="flex items-center gap-2 text-[11px] text-slate-400" data-testid="studio-result-inflight">
								<Loader2 size={12} className="animate-spin" /> Generating — polling every {POLL_MS / 1000}s. No further submission is made.
							</div>
						)}

						{plainFailure && (
							<div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200" data-testid="studio-result-failure">
								<strong>Job failed.</strong> {explainFailure(jobItem?.production_error)}
							</div>
						)}

						{registered && (
							<div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-[11px] text-emerald-200" data-testid="studio-result-success">
								<strong>Registered ✓ — {jobItem?.production_status}.</strong> Artifact{jobArtifacts.length > 1 ? "s" : ""}:{" "}
								{jobArtifacts.map((m) => (
									<a key={m} data-testid="studio-result-artifact" data-media-id={m} href={`/api/flow/retrieved/${encodeURIComponent(m)}`} target="_blank" rel="noreferrer" className="mr-2 font-mono underline hover:text-emerald-100">{m}</a>
								))}
							</div>
						)}

						{generatedNotRegistered && (
							<div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-[11px] text-amber-100" data-testid="studio-result-generated-not-registered">
								<strong>Generated but not registered.</strong> The video generated (credits spent) but could
								not be deterministically bound to this job, so it is not in the library. This is not a success — it is an honest fail-closed state.
							</div>
						)}
					</div>
				)}
			</section>
		</div>
	);
}
