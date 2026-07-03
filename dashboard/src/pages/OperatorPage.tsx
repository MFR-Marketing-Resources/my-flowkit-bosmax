import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchAPI } from "../api/client";
import { fetchProductCatalog } from "../api/products";
import SocialCopyPackagePanel from "../components/SocialCopyPackagePanel";
import {
	createF2VGenerationPackage,
	createI2VGenerationPackage,
} from "../api/workspaceGenerationPackages";
import {
	compileWorkspacePromptPreview,
	createWorkspaceExecutionPackage,
	fetchPromptCompilerRuntimeConfig,
	fetchWorkspacePackageReadiness,
} from "../api/workspacePackages";
import RequestReportPanel from "../components/reporting/RequestReportPanel";
import F2VModule from "../components/workspace/F2VModule";
import I2VModule from "../components/workspace/I2VModule";
import IMGModule from "../components/workspace/IMGModule";
import type { VideoModel } from "../components/workspace/ModelSelect";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import T2VModule from "../components/workspace/T2VModule";
import type {
	Product,
	PromptCameraStyle,
	PromptCharacterPresence,
	PromptCompilerRuntimeConfig,
	PromptGenerationMode,
	PromptTargetLanguage,
	TelemetryRequest,
	TelemetryRequestDetail,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
	WorkspaceGenerationPackage,
	WorkspaceMode,
	WorkspacePackageReadinessItem,
	WorkspacePromptPreviewResult,
} from "../types";

type OperatorNoticeTone = "idle" | "info" | "success" | "warning" | "error";

interface OperatorNotice {
	tone: OperatorNoticeTone;
	title: string;
	detail: string;
	requestId: string | null;
}

const CANONICAL_PROMPT_SECTIONS = [
	"SECTION 1 - ROLE & OBJECTIVE",
	"SECTION 2 - PRODUCT TRUTH LOCK",
	"SECTION 3 - CONTINUITY & STATE LOCK",
	"SECTION 4 - VISUAL STORY",
	"SECTION 5 - SHOT & CAMERA RULES",
	"SECTION 6 - SPOKEN DIALOGUE",
	"SECTION 7 - VOICE & DELIVERY",
	"SECTION 8 - CTA & END FRAME",
	"SECTION 9 - NO_OVERLAY",
] as const;

interface PromptAuditSection {
	heading: string;
	sectionNumber: number | null;
	title: string;
	body: string;
}

interface PromptAuditBlock {
	block_index?: number;
	block_role?: string;
	duration_seconds?: number;
	shot_count?: number;
	dialogue_word_budget?: number;
	engine_prompt_text?: string;
	compiled_prompt_text?: string;
}

function parsePromptSections(text: string): PromptAuditSection[] {
	const normalized = (text ?? "").replace(/\r\n/g, "\n");
	const matches = [...normalized.matchAll(/^SECTION [1-9] - .+$/gm)];
	if (matches.length === 0) {
		return [];
	}

	return matches.map((match, index) => {
		const heading = match[0].trim();
		const start = (match.index ?? 0) + match[0].length;
		const end =
			index + 1 < matches.length
				? (matches[index + 1].index ?? normalized.length)
				: normalized.length;
		const sectionNumberMatch = heading.match(/^SECTION (\d+)/);
		return {
			heading,
			sectionNumber: sectionNumberMatch ? Number(sectionNumberMatch[1]) : null,
			title: heading.replace(/^SECTION \d+ - /, ""),
			body: normalized.slice(start, end).trim(),
		};
	});
}

function PromptAuditCard({
	label,
	block,
	fallbackText,
}: {
	label: string;
	block?: PromptAuditBlock | null;
	fallbackText?: string | null;
}) {
	const [copied, setCopied] = useState(false);
	const promptText =
		block?.engine_prompt_text ??
		block?.compiled_prompt_text ??
		fallbackText ??
		"";
	const sections = parsePromptSections(promptText);
	const presentHeadings = new Set(sections.map((section) => section.heading));
	const missingSections = CANONICAL_PROMPT_SECTIONS.filter(
		(heading) => !presentHeadings.has(heading),
	);
	const handleCopy = useCallback(() => {
		navigator.clipboard.writeText(promptText || "").then(() => {
			setCopied(true);
			window.setTimeout(() => setCopied(false), 2200);
		});
	}, [promptText]);
	const metaChips = [
		block?.block_role ? `Role ${block.block_role}` : null,
		block?.duration_seconds ? `${block.duration_seconds}s` : null,
		block?.shot_count
			? `${block.shot_count} shot${block.shot_count > 1 ? "s" : ""}`
			: null,
		block?.dialogue_word_budget ? `${block.dialogue_word_budget} words` : null,
	].filter(Boolean) as string[];

	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/70 overflow-hidden">
			<div className="flex flex-col gap-3 border-b border-slate-800 px-4 py-3 md:flex-row md:items-start md:justify-between">
				<div className="space-y-2">
					<div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-200">
						{label}
					</div>
					<div className="flex flex-wrap gap-2">
						<span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
							{sections.length}/9 sections
						</span>
						{metaChips.map((chip) => (
							<span
								key={chip}
								className="rounded-full border border-slate-800 bg-slate-900/70 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
							>
								{chip}
							</span>
						))}
						{missingSections.length === 0 ? (
							<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200">
								Canonical 9-section structure
							</span>
						) : (
							<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-200">
								Missing{" "}
								{missingSections
									.map((heading) => heading.replace("SECTION ", "S"))
									.join(", ")}
							</span>
						)}
					</div>
				</div>
				<button
					type="button"
					onClick={handleCopy}
					className={`rounded-lg border px-3 py-2 text-[11px] font-semibold transition-colors ${copied ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-blue-500/30 bg-blue-500/10 text-blue-100 hover:bg-blue-500/20"}`}
				>
					{copied ? "Copied" : "Copy Prompt"}
				</button>
			</div>
			{sections.length > 0 ? (
				<div className="divide-y divide-slate-800">
					{sections.map((section) => (
						<details
							key={section.heading}
							open={
								section.sectionNumber === 4 ||
								section.sectionNumber === 6 ||
								section.sectionNumber === 8
							}
							className="group"
						>
							<summary className="cursor-pointer list-none px-4 py-3">
								<div className="flex items-center justify-between gap-3">
									<div className="flex items-center gap-2">
										<span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
											S{section.sectionNumber ?? "?"}
										</span>
										<span className="text-xs font-semibold text-slate-100">
											{section.title}
										</span>
									</div>
									<span className="text-[10px] uppercase tracking-[0.16em] text-slate-500 group-open:text-slate-300">
										Expand
									</span>
								</div>
							</summary>
							<pre className="border-t border-slate-800 px-4 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
								{section.body || "(empty section)"}
							</pre>
						</details>
					))}
				</div>
			) : (
				<pre className="px-4 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
					{promptText || "(no prompt text)"}
				</pre>
			)}
		</div>
	);
}

function humanizeWorkspaceMode(mode: WorkspaceMode) {
	if (mode === "HYBRID") return "Hybrid";
	if (mode === "F2V") return "Frames";
	if (mode === "I2V") return "Ingredients";
	if (mode === "IMG") return "Image";
	return "Text to Video";
}

function workspaceSurfaceLabel(mode: WorkspaceMode) {
	if (mode === "HYBRID") return "Hybrid (Product + AI Presenter)";
	if (mode === "F2V") return "Frames (Motion Delta)";
	if (mode === "I2V") return "Ingredients";
	if (mode === "IMG") return "Image Generation";
	return "Text to Video";
}

function parseWorkspaceBlocker(error: unknown): string | null {
	const message = error instanceof Error ? error.message : String(error || "");
	const match = message.match(
		/REFERENCE_ONLY_PRODUCT|CLAIM_SAFE_PACKAGE_NOT_READY|PRODUCTION_APPROVAL_REQUIRED|START_FRAME_REQUIRED|SUBJECT_REQUIRED|PRODUCT_ARCHIVED|UNSUPPORTED_MODE/,
	);
	return match?.[0] ?? null;
}

function blockerMessage(blocker: string | null, mode: WorkspaceMode) {
	switch (blocker) {
		case "REFERENCE_ONLY_PRODUCT":
			return "FastMoss reference products stay visible for review, but Smart Registration must convert them into product truth before package load.";
		case "CLAIM_SAFE_PACKAGE_NOT_READY":
			return "This product has no approved claim-safe package yet. Complete claim-safe review before loading a generation package.";
		case "PRODUCTION_APPROVAL_REQUIRED":
			return "This product is not production-approved for this mode yet.";
		case "START_FRAME_REQUIRED":
			return "F2V requires a product image as Start Frame.";
		case "SUBJECT_REQUIRED":
			return "This mode requires a product image or subject reference.";
		case "PRODUCT_ARCHIVED":
			return "Archived products cannot be loaded for generation.";
		case "UNSUPPORTED_MODE":
			return `${mode} is not supported by the approved package bridge.`;
		default:
			return "Failed to load approved package.";
	}
}

interface OperatorPageProps {
	mode?: "T2V" | "HYBRID" | "F2V" | "I2V" | "IMG";
}

export default function OperatorPage({ mode: propMode }: OperatorPageProps) {
	const location = useLocation();
	const navigate = useNavigate();
	const statePackage = (
		location.state as {
			workspaceExecutionPackage?: WorkspaceExecutionPackage;
		} | null
	)?.workspaceExecutionPackage;
	const isPortalMode =
		new URLSearchParams(location.search).get("portal") === "side";
	const [isExecuting, setIsExecuting] = useState(false);
	const [isSavingPackage, setIsSavingPackage] = useState(false);
	const [savedGenPackage, setSavedGenPackage] =
		useState<WorkspaceGenerationPackage | null>(null);
	const [savePackageError, setSavePackageError] = useState<string | null>(null);
	const [modeRequests, setModeRequests] = useState<TelemetryRequest[]>([]);
	const [compactPane, setCompactPane] = useState<"workspace" | "jobs">(
		"workspace",
	);
	const [products, setProducts] = useState<Product[]>([]);
	const [productsError, setProductsError] = useState<string | null>(null);
	const [isLoadingProducts, setIsLoadingProducts] = useState(false);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [packageReadiness, setPackageReadiness] = useState<
		Record<string, WorkspacePackageReadinessItem>
	>({});
	const [workspacePackage, setWorkspacePackage] =
		useState<WorkspaceExecutionPackage | null>(statePackage ?? null);
	const [previewPackage, setPreviewPackage] =
		useState<WorkspacePromptPreviewResult | null>(null);
	const [isLoadingPreview, setIsLoadingPreview] = useState(false);
	const [isLoadingPackage, setIsLoadingPackage] = useState(false);
	const [isLoadingReadiness, setIsLoadingReadiness] = useState(false);
	const [isLoadingSelectedReadiness, setIsLoadingSelectedReadiness] =
		useState(false);
	const [promptConfig, setPromptConfig] =
		useState<PromptCompilerRuntimeConfig | null>(null);
	const [generationMode, setGenerationMode] =
		useState<PromptGenerationMode>("SINGLE");
	const [targetLanguage, setTargetLanguage] =
		useState<PromptTargetLanguage>("BM_MS");
	const [cameraStyle, setCameraStyle] =
		useState<PromptCameraStyle>("UGC_IPHONE_RAW");
	const [characterPresence, setCharacterPresence] =
		useState<PromptCharacterPresence>("VISIBLE_CREATOR");
	const [creatorPersona, setCreatorPersona] = useState("DEFAULT_CREATOR");
	const [block1Duration, setBlock1Duration] = useState(8);
	const [block2Duration, setBlock2Duration] = useState(8);
	// WPS chaining opt-in (default OFF). When an engine vendor is selected the
	// preview/generate payload sends engine_duration_target +
	// requested_total_duration_seconds so the backend enforces the WPS Blocking
	// Template. Empty vendor = existing behavior, byte-identical payload.
	const [engineDurationTarget, setEngineDurationTarget] = useState<
		"" | "GROK" | "GOOGLE_FLOW"
	>("");
	// Canonical source-mode (ADR-008): PINNED by the operator surface — HYBRID
	// and FRAMES are separate first-class pages, never an ambiguous toggle.
	const resolveSourceMode = useCallback(
		(m: string): "T2V" | "HYBRID" | "FRAMES" | "INGREDIENTS" | "IMAGES" => {
			if (m === "HYBRID") return "HYBRID";
			if (m === "F2V") return "FRAMES";
			if (m === "I2V") return "INGREDIENTS";
			if (m === "IMG") return "IMAGES";
			return "T2V";
		},
		[],
	);
	const [requestedTotalDuration, setRequestedTotalDuration] = useState<
		number | ""
	>("");
	const [notice, setNotice] = useState<OperatorNotice>({
		tone: "idle",
		title: "Idle",
		detail: "Submit a job to start Google Flow automation.",
		requestId: null,
	});
	// Finished artifact preview — rendered inline the moment a job completes so the
	// operator never has to back-button/reload to find out the video is ready.
	const [completedArtifact, setCompletedArtifact] = useState<{
		mediaId: string;
		url: string;
		kind: "video" | "image";
		sizeMb: string | null;
	} | null>(null);
	// Finished results live in the LIBRARY pages (/library/videos, /library/images)
	// with 48h retention — the workspace page stays a WORKPLACE. Only the
	// just-completed artifact preview (completedArtifact) renders here.
	const pollTimerRef = useRef<number | null>(null);
	// In-flight guard: block a second START GENERATION while one execution is
	// still pending (the button re-enables on fast failures, so without this a
	// quick re-click dispatches a duplicate job to the same editor).
	const executionInFlightRef = useRef(false);

	const pathMode = location.pathname.split("/").pop()?.toUpperCase();
	const mode =
		propMode ||
		(pathMode === "T2V" ||
		pathMode === "HYBRID" ||
		pathMode === "F2V" ||
		pathMode === "I2V" ||
		pathMode === "IMG"
			? pathMode
			: "F2V");
	// API/job boundary mapping (ADR-007): the HYBRID operator surface runs F2V
	// jobs/packages with source_mode="HYBRID". Everything backend-bound uses
	// jobMode; the surface identity stays HYBRID.
	const jobMode: "T2V" | "F2V" | "I2V" | "IMG" =
		mode === "HYBRID" ? "F2V" : mode;
	const selectedReadiness = selectedProduct
		? (packageReadiness[selectedProduct.id] ?? null)
		: null;
	const selectedReadinessLoading = Boolean(
		selectedProduct &&
			!selectedProduct.reference_only &&
			!selectedReadiness &&
			(isLoadingReadiness || isLoadingSelectedReadiness),
	);
	const isLoadingAnyReadiness =
		isLoadingReadiness || isLoadingSelectedReadiness;

	useEffect(() => {
		setIsLoadingProducts(true);
		setProductsError(null);
		void fetchProductCatalog(500)
			.then((response) => setProducts(response.items ?? []))
			.catch((err: unknown) =>
				setProductsError(
					err instanceof Error ? err.message : "Failed to load product catalog",
				),
			)
			.finally(() => setIsLoadingProducts(false));
	}, []);

	useEffect(() => {
		void fetchPromptCompilerRuntimeConfig()
			.then((config) => {
				setPromptConfig(config);
				setGenerationMode(config.defaults.generation_mode);
				setTargetLanguage(config.defaults.target_language);
				setCameraStyle(config.defaults.camera_style);
				setCharacterPresence(config.defaults.character_presence);
				setCreatorPersona(config.defaults.creator_persona);
				setBlock1Duration(config.defaults.block_duration_seconds);
				setBlock2Duration(config.defaults.block_2_duration_seconds);
			})
			.catch(() => {});
	}, []);

	useEffect(() => {
		if (products.length === 0) {
			setPackageReadiness({});
			return;
		}
		setPackageReadiness({});
		setIsLoadingReadiness(true);
		void fetchWorkspacePackageReadiness({
			mode: jobMode as WorkspaceMode,
			product_ids: products.map((item) => item.id),
		})
			.then((response) => {
				const mapped = Object.fromEntries(
					response.items.map((item) => [item.product_id, item]),
				);
				setPackageReadiness((current) => ({ ...current, ...mapped }));
			})
			.catch(() => {})
			.finally(() => setIsLoadingReadiness(false));
	}, [jobMode, products]);

	useEffect(() => {
		if (
			!selectedProduct ||
			selectedProduct.reference_only ||
			packageReadiness[selectedProduct.id]
		) {
			setIsLoadingSelectedReadiness(false);
			return;
		}
		let isActive = true;
		setIsLoadingSelectedReadiness(true);
		void fetchWorkspacePackageReadiness({
			mode: jobMode as WorkspaceMode,
			product_ids: [selectedProduct.id],
		})
			.then((response) => {
				if (!isActive) return;
				const item = response.items[0];
				if (!item) return;
				setPackageReadiness((current) => ({
					...current,
					[item.product_id]: item,
				}));
			})
			.catch(() => {})
			.finally(() => {
				if (isActive) {
					setIsLoadingSelectedReadiness(false);
				}
			});
		return () => {
			isActive = false;
		};
	}, [jobMode, packageReadiness, selectedProduct]);

	useEffect(() => {
		if (!statePackage || statePackage.mode !== mode) return;
		setWorkspacePackage(statePackage);
	}, [mode, statePackage]);

	useEffect(() => {
		if (!workspacePackage || products.length === 0) return;
		const matched = products.find(
			(item) => item.id === workspacePackage.product_id,
		);
		if (matched) setSelectedProduct(matched);
	}, [products, workspacePackage]);

	useEffect(() => {
		if (!workspacePackage) return;
		if (workspacePackage.generation_mode) {
			setGenerationMode(workspacePackage.generation_mode);
		}
		if (workspacePackage.target_language) {
			setTargetLanguage(workspacePackage.target_language);
		}
		if (workspacePackage.camera_style) {
			setCameraStyle(workspacePackage.camera_style);
		}
		if (workspacePackage.character_presence) {
			setCharacterPresence(workspacePackage.character_presence);
		}
		if (workspacePackage.creator_persona) {
			setCreatorPersona(workspacePackage.creator_persona);
		}
		if (workspacePackage.prompt_blocks?.[0]?.duration_seconds) {
			setBlock1Duration(workspacePackage.prompt_blocks[0].duration_seconds);
		}
		if (workspacePackage.prompt_blocks?.[1]?.duration_seconds) {
			setBlock2Duration(workspacePackage.prompt_blocks[1].duration_seconds);
		}
	}, [workspacePackage]);

	useEffect(() => {
		if (selectedProduct || workspacePackage || products.length === 0) return;
		const readyProduct = products.find(
			(item) => packageReadiness[item.id]?.readiness_status === "READY",
		);
		if (readyProduct) {
			setSelectedProduct(readyProduct);
		}
	}, [packageReadiness, products, selectedProduct, workspacePackage]);

	useEffect(() => {
		setCompactPane("workspace");
	}, []);

	useEffect(() => {
		return () => {
			if (pollTimerRef.current != null) {
				window.clearTimeout(pollTimerRef.current);
			}
		};
	}, []);

	const [videoModels, setVideoModels] = useState<VideoModel[]>([]);
	useEffect(() => {
		fetchAPI<{ models: VideoModel[]; default: string }>(
			"/api/flow/video-models",
		)
			.then((r) => setVideoModels(r.models || []))
			.catch(() => {});
	}, []);

	useEffect(() => {
		if (!isPortalMode) {
			setModeRequests([]);
			return;
		}

		let inFlight = false;
		const loadModeRequests = () => {
			if (document.hidden || inFlight) {
				return;
			}
			inFlight = true;
			void fetchAPI<TelemetryRequest[]>(
				`/api/telemetry/requests?limit=60&request_type=MANUAL_FLOW_JOB&mode=${encodeURIComponent(jobMode)}`,
			)
				.then(setModeRequests)
				.catch(() => {})
				.finally(() => {
					inFlight = false;
				});
		};
		const handleVisibilityChange = () => {
			if (!document.hidden) {
				loadModeRequests();
			}
		};

		loadModeRequests();
		document.addEventListener("visibilitychange", handleVisibilityChange);
		const timer = window.setInterval(loadModeRequests, 15000);
		return () => {
			document.removeEventListener("visibilitychange", handleVisibilityChange);
			window.clearInterval(timer);
		};
	}, [isPortalMode, jobMode]);

	// IMG now flows through the SAME unified one-door /generate (mode:"IMG") + pollJob as the
	// video lanes — it saves to disk and returns a job (the legacy /generate-image-oneshot
	// endpoint is kept server-side but no longer called from the dashboard).
	const handleExecute = async (data: WorkspaceExecutePayload) => {
		if (executionInFlightRef.current) {
			console.log("[BOSMAX_DEBUG] DUPLICATE_EXECUTION_BLOCKED");
			return;
		}
		executionInFlightRef.current = true;
		setIsExecuting(true);
		setCompletedArtifact(null);
		console.log(
			"[BOSMAX_DEBUG] OPERATOR_EXECUTE_PAYLOAD",
			JSON.stringify(data, null, 2),
		);
		if (pollTimerRef.current != null) {
			window.clearTimeout(pollTimerRef.current);
			pollTimerRef.current = null;
		}

		const requestId = `manual_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
		setNotice({
			tone: "info",
			title: "Submitting to Flow",
			detail: "Request accepted. Runtime lane selection in progress.",
			requestId,
		});

		const pollJob = async (jobId: string) => {
			try {
				const response = await fetch(`/api/flow/generate-job/${jobId}`);
				if (!response.ok) {
					throw new Error(`Job HTTP ${response.status}`);
				}
				const job = await response.json();
				const status = job.status as string;

				if (status === "DONE") {
					const mediaId = job.media_id ?? job.video_media_id ?? "";
					// Surface the post-approve verification truth (Layer A). Handle BOTH result
					// shapes surgically: the generate-job lane carries the flags on top-level
					// job fields; the negotiate-job dry lane carries them under job.result.*.
					const r = job.result ?? {};
					const unverified = Boolean(
						job.model_unverified ||
							job.duration_unverified ||
							r.model_unverified ||
							r.duration_unverified ||
							job.model_ok === false ||
							job.duration_ok === false ||
							r.model_ok === false ||
							r.duration_ok === false,
					);
					const verifyNote = unverified
						? " — ⚠ verification: model/duration UNVERIFIED"
						: "";
					// IMG artifacts open in a new tab for a quick preview (one-door save still happens).
					if (job.artifact === "image" && job.url) {
						window.open(job.url, "_blank", "noopener");
					}
					if (mediaId) {
						setCompletedArtifact({
							mediaId,
							url: `/api/flow/retrieved/${mediaId}`,
							kind: job.artifact === "image" ? "image" : "video",
							sizeMb: job.size_mb != null ? String(job.size_mb) : null,
						});
					}
					setNotice({
						tone: "success",
						title: `${data.mode} done — saved`,
						detail: `Saved ${job.size_mb ?? "?"}MB → ${job.local_path} (media ${mediaId})${verifyNote}`,
						requestId,
					});
					setIsExecuting(false);
					executionInFlightRef.current = false;
					return;
				}
				if (status === "FAILED") {
					setNotice({
						tone: "error",
						title: `${data.mode} failed`,
						detail: job.error || "Generation failed.",
						requestId,
					});
					setIsExecuting(false);
					executionInFlightRef.current = false;
					return;
				}
				// Terminal: the video was generated in Flow but the local harvest failed. NOT a
				// clean success (no local file) and NOT a plain generation failure — and it must
				// NOT auto-retry. Surface the recovery fields so the user can recover manually.
				if (status === "GENERATED_BUT_UNRETRIEVED") {
					setNotice({
						tone: "warning",
						title: `${data.mode} generated in Flow — local retrieval failed`,
						detail:
							"Generated in Flow, but local retrieval failed. Manual recovery/download required." +
							(job.credit_spent_likely ? " A credit was likely spent." : "") +
							(job.recovery_hint ? ` ${job.recovery_hint}.` : "") +
							(job.original_error ? ` [${job.original_error}]` : ""),
						requestId,
					});
					setIsExecuting(false);
					executionInFlightRef.current = false;
					return;
				}

				setNotice({
					tone: "info",
					title: `${data.mode} running`,
					detail: `Stage: ${job.stage ?? status}`,
					requestId,
				});
				pollTimerRef.current = window.setTimeout(() => {
					void pollJob(jobId);
				}, 3000);
			} catch (error: unknown) {
				const message =
					error instanceof Error ? error.message : "Failed to read job status.";
				setNotice({
					tone: "error",
					title: "Job status unavailable",
					detail: message,
					requestId,
				});
				setIsExecuting(false);
				executionInFlightRef.current = false;
			}
		};

		const pollManualFlowRequest = async (manualRequestId: string) => {
			try {
				const response = await fetch(
					`/api/telemetry/requests/${encodeURIComponent(manualRequestId)}`,
				);
				if (response.status === 404) {
					pollTimerRef.current = window.setTimeout(() => {
						void pollManualFlowRequest(manualRequestId);
					}, 1500);
					return;
				}
				if (!response.ok) {
					throw new Error(`Telemetry HTTP ${response.status}`);
				}
				const detail = (await response.json()) as TelemetryRequestDetail;
				const telemetry = detail.telemetry;
				const stages = Array.isArray(detail.stages) ? detail.stages : [];
				const latestStage = stages.length ? stages[stages.length - 1] : null;
				const status = String(
					telemetry?.status || "WAITING_FLOW",
				).toUpperCase();
				const stageLabel =
					latestStage?.stage ||
					telemetry?.extension_stage ||
					telemetry?.google_flow_stage ||
					status;
				const stageMessage =
					latestStage?.message ||
					telemetry?.error_message ||
					"Waiting for extension telemetry.";

				if (status === "COMPLETED") {
					// The API lane's COMPLETED stage carries "media_id=<uuid> size_mb=<n>" —
					// surface the finished video inline so the operator sees it HERE, now.
					const completedStage = stages.find(
						(s) => String(s?.stage || "") === "COMPLETED",
					);
					const completedMsg = String(
						completedStage?.message || stageMessage || "",
					);
					const mediaMatch = completedMsg.match(
						/media_id=([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})/,
					);
					const sizeMatch = completedMsg.match(/size_mb=([\d.]+)/);
					if (mediaMatch) {
						setCompletedArtifact({
							mediaId: mediaMatch[1],
							url: `/api/flow/retrieved/${mediaMatch[1]}`,
							kind: "video",
							sizeMb: sizeMatch ? sizeMatch[1] : null,
						});
					}
					setNotice({
						tone: "success",
						title: `${data.mode} SIAP ✓ — video ready`,
						detail: `${stageLabel}${stageMessage ? ` — ${stageMessage}` : ""}`,
						requestId: manualRequestId,
					});
					setIsExecuting(false);
					executionInFlightRef.current = false;
					return;
				}

				if (status === "FAILED") {
					setNotice({
						tone: "error",
						title: `${data.mode} failed`,
						detail:
							telemetry?.error_message ||
							stageMessage ||
							"Manual Flow job failed.",
						requestId: manualRequestId,
					});
					setIsExecuting(false);
					executionInFlightRef.current = false;
					return;
				}

				setNotice({
					tone: "info",
					title: `${data.mode} running — video sedang dijana (±3–8 min), biar page ini terbuka`,
					detail: `Stage: ${stageLabel}${stageMessage ? ` — ${stageMessage}` : ""} · Nota: tiada apa akan bergerak dalam tab Google Flow — penjanaan berjalan melalui API dan video muncul di sini bila siap.`,
					requestId: manualRequestId,
				});
				pollTimerRef.current = window.setTimeout(() => {
					void pollManualFlowRequest(manualRequestId);
				}, 3000);
			} catch (error: unknown) {
				const message =
					error instanceof Error
						? error.message
						: "Failed to read manual Flow job status.";
				setNotice({
					tone: "error",
					title: "Manual Flow status unavailable",
					detail: message,
					requestId: manualRequestId,
				});
				setIsExecuting(false);
				executionInFlightRef.current = false;
			}
		};

		// F2V sends the Start/End frame as startAsset/endAsset; I2V/T2V use refs.*. Include ALL
		// of them so the one-door /generate always receives the reference image as
		// image_media_ids — otherwise F2V submits with an empty image and the backend rejects it
		// ("F2V needs a reference image").
		const refs = [
			data.startAsset?.mediaId,
			data.endAsset?.mediaId,
			data.refs?.subjectAsset?.mediaId,
			data.refs?.sceneAsset?.mediaId,
			data.refs?.styleAsset?.mediaId,
		].filter(Boolean) as string[];
		// The modules send `orientation` (VERTICAL/HORIZONTAL), not `aspectRatio`. Honour
		// aspectRatio if present, else fall back to orientation — otherwise HORIZONTAL was
		// silently dropped and every video came out 9:16.
		const aspect =
			data.aspectRatio === "16:9" || data.orientation === "HORIZONTAL"
				? "16:9"
				: "9:16";
		const isGfv2RuntimeLane =
			data.mode === "F2V" &&
			(data.gfv2 === true ||
				data.lane === "GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE" ||
				data.upload_only === true);
		const isWorkspaceRuntimeLane =
			data.lane === "WORKSPACE_FLOW_EDITOR_RUNTIME";

		try {
			if (isGfv2RuntimeLane || isWorkspaceRuntimeLane) {
				const response = await fetch("/api/flow/execute-flow-job", {
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({
						...data,
						request_id: requestId,
						aspectRatio: data.aspectRatio || aspect,
					}),
				});

				if (!response.ok) {
					const err = await response.json().catch(() => ({}));
					throw new Error(err.detail || `HTTP ${response.status}`);
				}

				await response.json();
				setNotice({
					tone: "info",
					title: `${data.mode} accepted`,
					detail: isGfv2RuntimeLane
						? `Manual Flow job ${requestId} submitted via GFV2 runtime lane.`
						: `Manual Flow job ${requestId} submitted via workspace runtime lane.`,
					requestId,
				});
				void pollManualFlowRequest(requestId);
				return;
			}
			// Unified one-door pipeline: agent → render → save (replaces the dead
			// execute-flow-job DOM automation against the retired Video/Frames UI).
			const response = await fetch("/api/flow/generate", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					mode: data.mode,
					prompt: data.prompt,
					image_media_ids: refs,
					aspect,
					model: data.model,
					duration_s: videoModels.find((m) => m.ui_label === data.model)
						?.default_duration_s,
				}),
			});

			if (!response.ok) {
				const err = await response.json().catch(() => ({}));
				throw new Error(err.detail || `HTTP ${response.status}`);
			}

			const result = await response.json();
			if (!result.job_id) {
				throw new Error("no job_id returned");
			}
			setNotice({
				tone: "info",
				title: `${data.mode} accepted`,
				detail: `Job ${result.job_id} started — agent → render → save.`,
				requestId,
			});
			void pollJob(result.job_id);
		} catch (error: unknown) {
			const message =
				error instanceof Error ? error.message : "Execution failed.";
			console.error("Execution error:", error);
			setNotice({
				tone: "error",
				title: "Execution error",
				detail: message,
				requestId,
			});
			setIsExecuting(false);
			executionInFlightRef.current = false;
		}
	};

	const handleSaveGenerationPackage = useCallback(async () => {
		if (!selectedProduct || !workspacePackage) return;
		if (selectedProduct.reference_only) {
			setSavePackageError(
				"REFERENCE_ONLY_PRODUCT — Convert/Register this product via Smart Registration before saving a generation package.",
			);
			return;
		}
		setIsSavingPackage(true);
		setSavePackageError(null);
		setSavedGenPackage(null);
		try {
			let pkg: WorkspaceGenerationPackage;
			if (mode === "HYBRID" || mode === "F2V") {
				pkg = await createF2VGenerationPackage({
					product_id: selectedProduct.id,
					workspace_execution_package_id:
						workspacePackage.workspace_execution_package_id,
					source_mode: resolveSourceMode(mode) as "HYBRID" | "FRAMES",
					generation_mode: generationMode,
					target_language: targetLanguage,
					camera_style: cameraStyle,
					character_presence: characterPresence,
					creator_persona: creatorPersona,
					overlay_enabled: false, // NO_OVERLAY law (ADR-008): default off
					dialogue_enabled: true,
					blocks: [
						{ block_index: 1, duration_seconds: block1Duration },
						...(generationMode === "EXTEND"
							? [{ block_index: 2, duration_seconds: block2Duration }]
							: []),
					],
				});
			} else if (mode === "I2V") {
				pkg = await createI2VGenerationPackage({
					product_id: selectedProduct.id,
					workspace_execution_package_id:
						workspacePackage.workspace_execution_package_id,
					generation_mode: generationMode,
					target_language: targetLanguage,
					camera_style: cameraStyle,
					character_presence: characterPresence,
					creator_persona: creatorPersona,
				});
			} else {
				throw new Error(
					`Generate / Save Package not supported for mode ${mode} yet.`,
				);
			}
			setSavedGenPackage(pkg);
		} catch (e) {
			setSavePackageError(String(e));
		} finally {
			setIsSavingPackage(false);
		}
	}, [
		selectedProduct,
		workspacePackage,
		mode,
		generationMode,
		targetLanguage,
		cameraStyle,
		characterPresence,
		creatorPersona,
		block1Duration,
		block2Duration,
		resolveSourceMode,
	]);

	// Step 3 — Load Package Preview (compile only, no DB save)
	const handleLoadPreview = async () => {
		if (!selectedProduct || selectedReadiness?.readiness_status !== "READY") {
			const blocker =
				selectedReadiness?.blocker ??
				selectedReadiness?.readiness_status ??
				null;
			setNotice({
				tone: "error",
				title: "Package not ready",
				detail: blockerMessage(blocker, mode as WorkspaceMode),
				requestId: null,
			});
			return;
		}
		setIsLoadingPreview(true);
		setPreviewPackage(null);
		setWorkspacePackage(null);
		try {
			const preview = await compileWorkspacePromptPreview({
				product_id: selectedProduct.id,
				mode: jobMode,
				source_mode: resolveSourceMode(mode),
				duration_seconds: block1Duration,
				generation_mode: generationMode,
				target_language: targetLanguage,
				camera_style: cameraStyle,
				character_presence: characterPresence,
				creator_persona: creatorPersona,
				blocks:
					generationMode === "EXTEND"
						? [
								{ block_index: 1, duration_seconds: block1Duration },
								{ block_index: 2, duration_seconds: block2Duration },
							]
						: [],
				...(engineDurationTarget
					? {
							engine_duration_target: engineDurationTarget,
							...(requestedTotalDuration !== ""
								? {
										requested_total_duration_seconds: requestedTotalDuration,
									}
								: {}),
						}
					: {}),
			});
			setPreviewPackage(preview);
			setNotice({
				tone: "success",
				title: `${mode} Package Loaded`,
				detail: `Approved package compiled for ${selectedProduct.product_display_name}. Review the prompt preview then press Generate.`,
				requestId: null,
			});
		} catch (error: unknown) {
			const blocker = parseWorkspaceBlocker(error);
			const message = blocker
				? blockerMessage(blocker, mode as WorkspaceMode)
				: error instanceof Error
					? error.message
					: "Failed to load package.";
			setNotice({
				tone: "error",
				title: "Package load failed",
				detail: message,
				requestId: null,
			});
		} finally {
			setIsLoadingPreview(false);
		}
	};

	// Step 4 — Generate Final Prompt (compile + save to DB)
	const handleGeneratePackage = async () => {
		if (!selectedProduct || !previewPackage) return;
		setIsLoadingPackage(true);
		try {
			const pkg = await createWorkspaceExecutionPackage({
				product_id: selectedProduct.id,
				mode: jobMode,
				source_mode: resolveSourceMode(mode),
				duration_seconds: block1Duration,
				generation_mode: generationMode,
				target_language: targetLanguage,
				camera_style: cameraStyle,
				character_presence: characterPresence,
				creator_persona: creatorPersona,
				blocks:
					generationMode === "EXTEND"
						? [
								{ block_index: 1, duration_seconds: block1Duration },
								{ block_index: 2, duration_seconds: block2Duration },
							]
						: [],
				...(engineDurationTarget
					? {
							engine_duration_target: engineDurationTarget,
							...(requestedTotalDuration !== ""
								? {
										requested_total_duration_seconds: requestedTotalDuration,
									}
								: {}),
						}
					: {}),
			});
			setWorkspacePackage(pkg);
			setPreviewPackage(null);
			setNotice({
				tone: "success",
				title: "Final Prompt Generated",
				detail:
					mode === "F2V"
						? `Workspace now uses compiled ${generationMode} ${mode} prompt from product truth.`
						: `Workspace now uses locked ${mode} payload from product truth.`,
				requestId: pkg.workspace_execution_package_id,
			});
		} catch (error: unknown) {
			const blocker = parseWorkspaceBlocker(error);
			const message = blocker
				? blockerMessage(blocker, mode as WorkspaceMode)
				: error instanceof Error
					? error.message
					: "Failed to generate final prompt.";
			setNotice({
				tone: "error",
				title: "Generation failed",
				detail: message,
				requestId: null,
			});
		} finally {
			setIsLoadingPackage(false);
		}
	};

	const allowedDurations = promptConfig?.allowed_block_durations_seconds ?? [
		6, 8, 10, 12, 15, 20, 25,
	];
	const languageOptions = Object.keys(
		promptConfig?.language_wps_policy ?? {
			BM_MS: {},
			EN_US: {},
		},
	) as PromptTargetLanguage[];
	const shotPolicy1 =
		promptConfig?.shot_count_policy[String(block1Duration)] ?? null;
	const shotPolicy2 =
		promptConfig?.shot_count_policy[String(block2Duration)] ?? null;
	const isExtendMode = generationMode === "EXTEND";
	const packageBridgeFlowLabelByMode: Record<WorkspaceMode, string> = {
		T2V: "Load T2V Package + Generate Final Prompt",
		HYBRID: "Load HYBRID Package + Generate Final Prompt",
		F2V: "Load FRAMES Package + Generate Final Prompt",
		I2V: "Load I2V Package + Generate Final Prompt",
		IMG: "Load IMG Package + Generate Final Prompt",
	};
	const loadPackageLabel = previewPackage
		? `Reload ${mode} Package`
		: `Load ${mode} Package`;
	const generatePromptLabel = workspacePackage
		? "Regenerate Final Prompt"
		: "Generate Final Prompt";

	const renderModule = () => {
		switch (mode) {
			case "HYBRID": // product-image anchor + AI presenter — same module shape as F2V
			case "F2V":
				return (
					<F2VModule
						onExecute={handleExecute}
						isExecuting={isExecuting}
						compact={isPortalMode}
						workspacePackage={workspacePackage}
						videoModels={videoModels}
					/>
				);
			case "T2V":
				return (
					<T2VModule
						onExecute={handleExecute}
						isExecuting={isExecuting}
						compact={isPortalMode}
						workspacePackage={workspacePackage}
						videoModels={videoModels}
					/>
				);
			case "I2V":
				return (
					<I2VModule
						onExecute={handleExecute}
						isExecuting={isExecuting}
						compact={isPortalMode}
						workspacePackage={workspacePackage}
						onWorkspacePackageUpdated={setWorkspacePackage}
						videoModels={videoModels}
					/>
				);
			case "IMG":
				return (
					<IMGModule
						onExecute={handleExecute}
						isExecuting={isExecuting}
						compact={isPortalMode}
						workspacePackage={workspacePackage}
						previewPackage={previewPackage}
						selectedProduct={selectedProduct}
					/>
				);
			default:
				return (
					<div className="p-8 text-slate-400">
						Please select a workspace module from the sidebar.
					</div>
				);
		}
	};

	return (
		<div className="flex h-full flex-col bg-slate-950 px-4 py-4 md:px-8 md:py-8">
			<div className="mb-6 flex flex-col gap-4 lg:mb-8 lg:flex-row lg:items-center lg:justify-between">
				<div>
					<h2 className="text-xl font-bold tracking-tight text-white md:text-2xl">
						{humanizeWorkspaceMode(mode as WorkspaceMode)} Production Workspace
					</h2>
					<p className="text-sm italic text-slate-400">
						Automating Google Flow with BOSMAX V4 precision.
					</p>
				</div>
				<div className="flex items-center gap-3">
					<div className="px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-[10px] font-bold uppercase tracking-widest">
						Mode: {workspaceSurfaceLabel(mode as WorkspaceMode)}
					</div>
				</div>
			</div>

			{isPortalMode && (
				<div className="mb-4 grid grid-cols-2 gap-2 rounded-2xl border border-slate-800 bg-slate-900/40 p-2">
					<button
						type="button"
						onClick={() => setCompactPane("workspace")}
						className={`rounded-xl px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] transition ${compactPane === "workspace" ? "bg-blue-500/15 text-blue-200 shadow-inner shadow-blue-950/30" : "text-slate-400 hover:bg-slate-800/70 hover:text-slate-200"}`}
					>
						Workspace
					</button>
					<button
						type="button"
						onClick={() => setCompactPane("jobs")}
						className={`rounded-xl px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] transition ${compactPane === "jobs" ? "bg-blue-500/15 text-blue-200 shadow-inner shadow-blue-950/30" : "text-slate-400 hover:bg-slate-800/70 hover:text-slate-200"}`}
					>
						Jobs{" "}
						{modeRequests.length > 0
							? `(${Math.min(modeRequests.length, 99)})`
							: ""}
					</button>
				</div>
			)}

			{/* ── STEP 1: UGC Prompt Compiler Controls (video modes only) ── */}
			{mode !== "IMG" && (
				<div className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
						Step 1 — UGC Prompt Compiler Controls
					</div>
					<div className="mb-4 text-[11px] text-slate-400">
						Configure all generation parameters first. These settings are
						compiled into the final prompt when you press Generate.
					</div>
					<div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Generation Mode
							</div>
							<select
								id="operator-generation-mode"
								name="operator_generation_mode"
								title="Generation mode"
								value={generationMode}
								onChange={(e) =>
									setGenerationMode(e.target.value as PromptGenerationMode)
								}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								<option value="SINGLE">Single</option>
								<option value="EXTEND">Extend</option>
							</select>
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Language
							</div>
							<select
								id="operator-target-language"
								name="operator_target_language"
								title="Target language"
								value={targetLanguage}
								onChange={(e) =>
									setTargetLanguage(e.target.value as PromptTargetLanguage)
								}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								{languageOptions.map((language) => (
									<option key={language} value={language}>
										{language}
									</option>
								))}
							</select>
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Block 1 Duration
							</div>
							<select
								id="operator-block-1-duration"
								name="operator_block_1_duration"
								title="Block 1 duration"
								value={String(block1Duration)}
								onChange={(e) => setBlock1Duration(Number(e.target.value))}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								{allowedDurations.map((duration) => (
									<option key={duration} value={duration}>
										{duration}s
									</option>
								))}
							</select>
							<div className="text-[11px] text-slate-400">
								Recommended Shots: {shotPolicy1?.recommended ?? "-"}
							</div>
						</div>
						{isExtendMode ? (
							<div className="space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Block 2 Duration
								</div>
								<select
									id="operator-block-2-duration"
									name="operator_block_2_duration"
									title="Block 2 duration"
									value={String(block2Duration)}
									onChange={(e) => setBlock2Duration(Number(e.target.value))}
									className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
								>
									{allowedDurations.map((duration) => (
										<option key={duration} value={duration}>
											{duration}s
										</option>
									))}
								</select>
								<div className="text-[11px] text-slate-400">
									Recommended Shots: {shotPolicy2?.recommended ?? "-"}
								</div>
							</div>
						) : (
							<div className="space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Block Structure
								</div>
								<div className="rounded-lg border border-dashed border-slate-800 bg-slate-900/60 px-3 py-3 text-xs text-slate-400">
									Single mode compiles one anchor block. Switch Generation Mode
									to Extend to unlock Block 2 duration.
								</div>
							</div>
						)}
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Camera Style
							</div>
							<select
								id="operator-camera-style"
								name="operator_camera_style"
								title="Camera style"
								value={cameraStyle}
								onChange={(e) =>
									setCameraStyle(e.target.value as PromptCameraStyle)
								}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								<option value="UGC_IPHONE_RAW">UGC iPhone Raw</option>
								<option value="CINEMATIC_PRO">Cinematic Pro</option>
							</select>
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Character Presence
							</div>
							<select
								id="operator-character-presence"
								name="operator_character_presence"
								title="Character presence"
								value={characterPresence}
								onChange={(e) =>
									setCharacterPresence(
										e.target.value as PromptCharacterPresence,
									)
								}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								<option value="VISIBLE_CREATOR">Visible Creator</option>
								<option value="FACELESS">Faceless</option>
							</select>
							{characterPresence === "FACELESS" ? (
								<div className="text-[11px] text-amber-200">
									Faceless is explicit-only and disables the visible creator
									default.
								</div>
							) : null}
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Creator Persona
							</div>
							<select
								id="operator-creator-persona"
								name="operator_creator_persona"
								title="Creator persona"
								value={creatorPersona}
								onChange={(e) => setCreatorPersona(e.target.value)}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								{(promptConfig?.persona_registry ?? []).map((persona) => (
									<option key={persona.id} value={persona.id}>
										{persona.label}
									</option>
								))}
							</select>
						</div>
					</div>
					<div className="mt-4 grid gap-3 md:grid-cols-2">
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Source Mode (canonical)
							</div>
							<select
								title="Canonical source mode (fixed by this operator surface)"
								value={resolveSourceMode(mode)}
								disabled
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100 disabled:opacity-60"
							>
								<option value="HYBRID">
									HYBRID — product image anchor + AI presenter
								</option>
								<option value="FRAMES">
									FRAMES — ready frame, motion-delta only
								</option>
								<option value="T2V">T2V — text-driven</option>
								<option value="INGREDIENTS">
									INGREDIENTS — asset role map
								</option>
								<option value="IMAGES">IMAGES — still image</option>
							</select>
							<div className="text-[11px] text-slate-400">
								Fixed by this operator surface: HYBRID and FRAMES are separate
								pages under the canonical compiler contract.
							</div>
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								WPS Engine Vendor (optional)
							</div>
							<select
								title="WPS engine vendor"
								value={engineDurationTarget}
								onChange={(e) =>
									setEngineDurationTarget(
										e.target.value as "" | "GROK" | "GOOGLE_FLOW",
									)
								}
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
							>
								<option value="">None (no WPS chaining)</option>
								<option value="GROK">Grok</option>
								<option value="GOOGLE_FLOW">Google Flow</option>
							</select>
							<div className="text-[11px] text-slate-400">
								Select a vendor to enforce the WPS Blocking Template.
							</div>
						</div>
						<div className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								WPS Total Duration (s)
							</div>
							<input
								type="number"
								min={1}
								title="WPS requested total duration seconds"
								value={
									requestedTotalDuration === ""
										? ""
										: String(requestedTotalDuration)
								}
								onChange={(e) =>
									setRequestedTotalDuration(
										e.target.value === "" ? "" : Number(e.target.value),
									)
								}
								disabled={engineDurationTarget === ""}
								placeholder="e.g. 24"
								className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100 disabled:opacity-40"
							/>
							<div className="text-[11px] text-slate-400">
								Total video seconds; backend resolves the block chain.
							</div>
						</div>
					</div>
					<div className="mt-4 grid gap-3 md:grid-cols-2">
						<div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3 text-[11px] text-slate-300">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Shot Plan
							</div>
							<div className="mt-2">
								Block 1: {shotPolicy1?.recommended ?? "-"} recommended shot(s)
							</div>
							{generationMode === "EXTEND" ? (
								<div className="mt-1">
									Block 2: {shotPolicy2?.recommended ?? "-"} recommended shot(s)
								</div>
							) : null}
						</div>
						<div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3 text-[11px] text-slate-300">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
								Language Policy
							</div>
							<div className="mt-2">
								{targetLanguage} body WPS:{" "}
								{promptConfig?.language_wps_policy[targetLanguage]?.body_wps ??
									"-"}
							</div>
							<div className="mt-1">
								Absolute ceiling:{" "}
								{promptConfig?.language_wps_policy[targetLanguage]
									?.absolute_ceiling_wps ?? "-"}
							</div>
						</div>
					</div>
				</div>
			)}

			{/* ── STEP 2: Select Product ────────────────────────────────── */}
			<div className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
				<div className="mb-3 rounded-xl border border-indigo-500/20 bg-indigo-500/5 px-3 py-3 text-[11px] text-indigo-100">
					<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-indigo-300">
						Approved Package Bridge
					</div>
					<div className="mt-1 text-indigo-100/80">
						{packageBridgeFlowLabelByMode[mode as WorkspaceMode]} stays a
						two-step bridge here so package preview and saved execution payload
						never get conflated.
					</div>
				</div>
				<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
					Step 2 — Select Product
				</div>
				<div className="mb-4 text-[11px] text-slate-400">
					Only READY products can generate a{" "}
					{humanizeWorkspaceMode(mode as WorkspaceMode)} package.
				</div>
				{isLoadingProducts && (
					<div className="mb-3 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-2 text-[11px] text-slate-400">
						Loading products...
					</div>
				)}
				{productsError && !isLoadingProducts && (
					<div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-[11px] text-rose-300">
						Product list failed to load: {productsError}
					</div>
				)}
				<SearchableProductSelect
					products={products}
					selectedProduct={selectedProduct}
					onSelect={setSelectedProduct}
					readinessByProductId={packageReadiness}
					isLoadingReadiness={isLoadingAnyReadiness}
				/>
				{/* Reference-only product blocker */}
				{selectedProduct?.reference_only && !selectedReadiness ? (
					<div className="mt-4 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4">
						<div className="text-[10px] font-bold uppercase tracking-[0.22em] text-amber-400 mb-2">
							Reference-Only Product
						</div>
						<div className="text-xs text-amber-200 mb-3">
							REFERENCE_ONLY_PRODUCT —{" "}
							{selectedProduct.catalog_visibility_reason ||
								"FastMoss reference is visible for review only. Use Smart Registration to convert it into product truth before package load/generation."}
						</div>
						<div className="flex flex-wrap gap-2">
							<button
								type="button"
								onClick={() => navigate("/product-registration?tab=bulk")}
								title="Convert / Register Product"
								className="rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-[11px] font-semibold text-indigo-100"
							>
								Open Bulk FastMoss Convert
							</button>
						</div>
					</div>
				) : selectedReadiness ? (
					<div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
						<div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
							<div>
								<div className="text-[10px] font-bold uppercase tracking-[0.22em] text-slate-500">
									Package Eligibility
								</div>
								<div className="mt-2 flex flex-wrap items-center gap-2">
									<span
										className={`inline-flex rounded-full border px-3 py-1 text-[10px] font-bold uppercase tracking-[0.18em] ${
											selectedReadiness.readiness_status === "READY"
												? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
												: selectedReadiness.readiness_status ===
														"PRODUCT_ARCHIVED"
													? "border-slate-500/30 bg-slate-500/10 text-slate-300"
													: "border-amber-500/30 bg-amber-500/10 text-amber-100"
										}`}
									>
										{selectedReadiness.readiness_status}
									</span>
									<span className="text-xs text-slate-300">
										{selectedReadiness.detail}
									</span>
								</div>
							</div>
							<div className="flex flex-wrap gap-2">
								<button
									type="button"
									onClick={() =>
										navigate(
											selectedReadiness.quick_actions.smart_registration_path,
										)
									}
									className="rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-[11px] font-semibold text-indigo-100"
								>
									Open Smart Registration / Complete Evidence
								</button>
								<button
									type="button"
									onClick={() =>
										navigate(
											selectedReadiness.quick_actions.approved_packages_path,
										)
									}
									className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-[11px] font-semibold text-slate-200"
								>
									Open Approved Packages
								</button>
							</div>
						</div>
						<div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
							{selectedReadiness.checklist.map((entry) => (
								<div
									key={entry.key}
									className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3"
								>
									<div className="flex items-center justify-between gap-3">
										<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
											{entry.label}
										</div>
										<span
											className={`inline-flex rounded-full border px-2 py-0.5 text-[9px] font-bold uppercase tracking-[0.16em] ${
												entry.ready
													? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
													: "border-amber-500/30 bg-amber-500/10 text-amber-100"
											}`}
										>
											{entry.ready ? "READY" : "BLOCKED"}
										</span>
									</div>
									<div className="mt-2 text-[11px] leading-relaxed text-slate-300">
										{entry.detail}
									</div>
								</div>
							))}
						</div>
						{selectedReadiness.readiness_status !== "READY" ? (
							<div className="mt-3 text-[11px] text-amber-200">
								No {humanizeWorkspaceMode(mode as WorkspaceMode)}-ready product
								will load until this checklist is satisfied.
							</div>
						) : null}
					</div>
				) : null}
				{!selectedProduct?.reference_only &&
				!selectedReadiness &&
				!selectedReadinessLoading ? (
					<div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-xs text-slate-400">
						No {humanizeWorkspaceMode(mode as WorkspaceMode)}-ready products are
						auto-selected. Choose a product and review its readiness checklist
						first.
					</div>
				) : null}
			</div>

			{/* ── STEP 3: Load Package (video modes only) ──────────────── */}
			{mode !== "IMG" && (
				<div className="mb-4 rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
						Step 3 — Load {mode} Package
					</div>
					<div className="mb-4 text-[11px] text-slate-400">
						Fetch and compile the approved package for the selected product
						using your configured settings above. Review the prompt preview
						before generating.
					</div>
					<button
						type="button"
						onClick={() => void handleLoadPreview()}
						disabled={
							!selectedProduct ||
							isLoadingPreview ||
							selectedReadinessLoading ||
							selectedReadiness?.readiness_status !== "READY"
						}
						className="w-full rounded-xl border border-slate-600/40 bg-slate-700/30 px-4 py-3 text-sm font-bold text-slate-100 hover:bg-slate-700/50 disabled:opacity-50 disabled:grayscale transition-all"
					>
						{isLoadingPreview ? `Loading ${mode} Package…` : loadPackageLabel}
					</button>
					{/* Preview result */}
					{previewPackage ? (
						<div className="mt-4 space-y-3">
							<div className="grid gap-3 md:grid-cols-3">
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Mode / Duration
									</div>
									<div className="mt-1 text-xs font-semibold text-white">
										{previewPackage.generation_mode} ·{" "}
										{previewPackage.total_duration_seconds}s
									</div>
								</div>
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Prompt Fingerprint
									</div>
									<div className="mt-1 text-xs font-semibold text-white">
										{previewPackage.prompt_fingerprint}
									</div>
								</div>
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Blocks
									</div>
									<div className="mt-1 text-xs font-semibold text-white">
										{previewPackage.prompt_blocks?.length ?? 0} block(s)
										compiled
									</div>
								</div>
							</div>
							{previewPackage.warnings?.length ? (
								<div className="rounded-xl border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
									{previewPackage.warnings.join(" · ")}
								</div>
							) : null}
							{previewPackage.wps_chaining_enforced ? (
								<div className="rounded-xl border border-sky-500/30 bg-sky-500/5 px-3 py-2 text-[11px] text-sky-200">
									<div className="font-semibold">
										WPS enforced ·{" "}
										{previewPackage.engine_duration_target ?? "—"}
									</div>
									<div className="mt-1">
										Chain: [
										{(previewPackage.resolved_block_chain ?? []).join(", ")}] ·
										Budget: [
										{previewPackage.dialogue_word_budget_per_block.join(", ")}]
									</div>
									<div className="mt-1">
										Actual: [
										{(
											previewPackage.actual_dialogue_word_count_per_block ?? []
										).join(", ")}
										] · Status: [
										{(previewPackage.wps_status_per_block ?? []).join(", ")}]
									</div>
								</div>
							) : null}
							<div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-200">
								Package loaded. Review above then press Generate Final Prompt to
								save.
							</div>
							<div className="space-y-3">
								<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
									Compiled Prompt Audit
								</div>
								{(previewPackage.prompt_blocks ?? []).map((block) => (
									<PromptAuditCard
										key={block.block_id ?? block.block_index}
										label={`Preview Block ${block.block_index} — ${block.block_role}`}
										block={block}
									/>
								))}
							</div>
						</div>
					) : null}
				</div>
			)}

			{/* ── STEP 4: Generate Final Prompt (video modes only) ─────── */}
			{mode !== "IMG" && (
				<div className="mb-6 rounded-2xl border border-blue-500/20 bg-slate-900/40 p-4">
					<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
						Step 4 — Generate Final Prompt
					</div>
					<div className="mb-4 text-[11px] text-slate-400">
						After loading the package above, press this button to compile and
						save the final execution prompt to the workspace.
					</div>
					<button
						type="button"
						onClick={() => void handleGeneratePackage()}
						disabled={!previewPackage || isLoadingPackage}
						className="w-full rounded-xl border border-blue-500/40 bg-blue-500/15 px-4 py-3 text-sm font-bold text-blue-100 hover:bg-blue-500/25 disabled:opacity-50 disabled:grayscale transition-all"
					>
						{isLoadingPackage ? "Generating…" : generatePromptLabel}
					</button>
					{workspacePackage ? (
						<div className="mt-4 space-y-3">
							<div className="grid gap-3 md:grid-cols-3">
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Execution Package
									</div>
									<div className="mt-1 text-sm font-semibold text-white">
										{workspacePackage.workspace_execution_package_id}
									</div>
								</div>
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Prompt Fingerprint
									</div>
									<div className="mt-1 text-sm font-semibold text-white">
										{workspacePackage.prompt_fingerprint}
									</div>
								</div>
								<div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-3">
									<div className="text-[10px] uppercase tracking-[0.2em] text-slate-500">
										Manual Fallback
									</div>
									<div className="mt-1 text-sm font-semibold text-white">
										{workspacePackage.manual_fallback.copy_prompt_available
											? "Copy prompt + image ready"
											: "Unavailable"}
									</div>
								</div>
							</div>
							<div className="space-y-3">
								<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
									Final Prompt Audit
								</div>
								{workspacePackage.prompt_blocks?.length ? (
									workspacePackage.prompt_blocks.map((block) => (
										<PromptAuditCard
											key={block.block_id ?? block.block_index}
											label={`Final Block ${block.block_index} — ${block.block_role}`}
											block={block}
										/>
									))
								) : (
									<PromptAuditCard
										label="Final Prompt"
										fallbackText={workspacePackage.prompt_text}
									/>
								)}
							</div>
						</div>
					) : null}
					{/* Generate / Save Package — F2V and I2V */}
					{workspacePackage &&
					(mode === "HYBRID" || mode === "F2V" || mode === "I2V") &&
					!selectedProduct?.reference_only ? (
						<div className="mt-4 rounded-2xl border border-indigo-500/30 bg-indigo-500/5 p-4">
							<div className="text-[10px] font-bold uppercase tracking-[0.22em] text-indigo-400 mb-3">
								Prompt Handoff Bank
							</div>
							<div className="flex flex-wrap items-center gap-3">
								<button
									type="button"
									onClick={() => void handleSaveGenerationPackage()}
									disabled={isSavingPackage}
									className="rounded-xl border border-indigo-500/40 bg-indigo-500/15 px-4 py-2.5 text-sm font-semibold text-indigo-100 hover:bg-indigo-500/25 disabled:opacity-50 transition-colors"
								>
									{isSavingPackage
										? "Saving Package…"
										: "Generate / Save Package"}
								</button>
								{savedGenPackage && (
									<>
										<span className="text-xs text-emerald-300 font-mono">
											✓ Saved: {savedGenPackage.workspace_generation_package_id}
										</span>
										<button
											type="button"
											onClick={() => navigate(`/workspace/generation-packages`)}
											className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-[11px] font-semibold text-slate-200 hover:bg-slate-800 transition-colors"
										>
											Open Prompt Handoff Bank
										</button>
									</>
								)}
								{savePackageError && (
									<span className="text-xs text-red-400">
										{savePackageError}
									</span>
								)}
							</div>
							<p className="mt-2 text-[11px] text-indigo-300/60">
								Saves a durable package with final prompt, selected assets,
								upload order, and DOM scaffold. DOM execution is not triggered.
								package_id is stored in Prompt Handoff Bank.
							</p>
						</div>
					) : null}
				</div>
			)}

			<div
				className={`mb-6 rounded-2xl border px-4 py-3 text-sm ${notice.tone === "error" ? "border-red-500/40 bg-red-500/10 text-red-200" : notice.tone === "success" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200" : notice.tone === "info" ? "border-blue-500/40 bg-blue-500/10 text-blue-200" : notice.tone === "warning" ? "border-amber-500/40 bg-amber-500/10 text-amber-200" : "border-slate-800 bg-slate-900/40 text-slate-300"}`}
			>
				<div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
					<div>
						<div className="font-semibold tracking-wide">{notice.title}</div>
						<div className="text-xs opacity-90 mt-1">{notice.detail}</div>
					</div>
					<div className="text-[10px] uppercase tracking-[0.2em] opacity-70 md:text-right">
						{notice.requestId ? `req ${notice.requestId}` : "no active request"}
					</div>
				</div>
			</div>

			{completedArtifact && (
				<div className="mb-6 rounded-2xl border border-emerald-500/40 bg-emerald-500/10 p-4">
					<div className="mb-3 flex items-center justify-between">
						<div className="font-semibold tracking-wide text-emerald-200">
							{completedArtifact.kind === "video"
								? "🎬 Video siap"
								: "🖼 Imej siap"}
							{completedArtifact.sizeMb
								? ` — ${completedArtifact.sizeMb}MB`
								: ""}
						</div>
						<div className="flex items-center gap-3">
							<a
								href={completedArtifact.url}
								download={`${completedArtifact.mediaId}.${completedArtifact.kind === "video" ? "mp4" : "jpg"}`}
								className="rounded-lg border border-emerald-500/40 px-3 py-1 text-xs text-emerald-200 hover:bg-emerald-500/20"
							>
								Download
							</a>
							<button
								type="button"
								onClick={() => setCompletedArtifact(null)}
								className="text-xs text-emerald-200/70 hover:text-emerald-200"
							>
								Tutup
							</button>
						</div>
					</div>
					{completedArtifact.kind === "video" ? (
						<>
							{/* biome-ignore lint/a11y/useMediaCaption: generated artifact previews do not ship with caption tracks */}
							<video
								src={completedArtifact.url}
								controls
								playsInline
								className="max-h-96 rounded-xl border border-emerald-500/20"
							/>
						</>
					) : (
						<img
							src={completedArtifact.url}
							alt="Generated artifact"
							className="max-h-96 rounded-xl border border-emerald-500/20"
						/>
					)}
					<div className="mt-2 text-[10px] uppercase tracking-[0.2em] text-emerald-200/60">
						media {completedArtifact.mediaId}
					</div>
				</div>
			)}

			{/* Social Copy Package — author platform-specific caption/comment copy
			    for the just-finished artifact; approved copy prefills Postiz. */}
			{completedArtifact && (
				<div className="mb-6">
					<SocialCopyPackagePanel
						mediaId={completedArtifact.mediaId}
						sourceMode={mode}
						productName={selectedProduct?.product_display_name ?? null}
					/>
				</div>
			)}

			<div className="flex flex-1 min-h-0 flex-col gap-6">
				{(!isPortalMode || compactPane === "workspace") && (
					<div className="min-h-0">{renderModule()}</div>
				)}

				{isPortalMode && compactPane === "jobs" && (
					<div className="min-h-0">
						<RequestReportPanel
							requests={modeRequests}
							title="Workspace Jobs"
							description="Portal mode can still inspect current workspace requests here without reopening the unified jobs page."
							emptyMessage="No jobs recorded for this workspace yet. New submissions from this page will appear here automatically."
							maxItems={18}
						/>
					</div>
				)}
			</div>
		</div>
	);
}
