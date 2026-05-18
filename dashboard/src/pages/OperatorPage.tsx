import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchAPI } from "../api/client";
import { fetchProductCatalog } from "../api/products";
import {
	createWorkspaceExecutionPackage,
	fetchPromptCompilerRuntimeConfig,
	fetchWorkspacePackageReadiness,
} from "../api/workspacePackages";
import RequestReportPanel from "../components/reporting/RequestReportPanel";
import F2VModule from "../components/workspace/F2VModule";
import I2VModule from "../components/workspace/I2VModule";
import IMGModule from "../components/workspace/IMGModule";
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
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
	WorkspaceMode,
	WorkspacePackageReadinessItem,
} from "../types";

type OperatorNoticeTone = "idle" | "info" | "success" | "error";

interface OperatorTelemetryResponse {
	telemetry: {
		request_id: string;
		status: string;
		google_flow_stage: string | null;
		extension_stage: string | null;
		worker_stage: string | null;
		error_message: string | null;
	};
	stages: Array<{
		id: string;
		stage: string;
		status: string;
		message: string | null;
		source: string;
		timestamp: string;
	}>;
}

interface OperatorNotice {
	tone: OperatorNoticeTone;
	title: string;
	detail: string;
	requestId: string | null;
}

const ACTIVE_TELEMETRY_STATUSES = new Set([
	"QUEUED",
	"PROCESSING",
	"WAITING_FLOW",
	"FLOW_RUNNING",
]);

function getNoticeTone(status: string | null | undefined): OperatorNoticeTone {
	if (!status) return "info";
	if (status === "COMPLETED") return "success";
	if (status === "FAILED") return "error";
	return "info";
}

function getLatestStageLabel(payload: OperatorTelemetryResponse | null) {
	if (!payload) return "WAITING_FOR_TELEMETRY";
	return (
		payload.telemetry.google_flow_stage ||
		payload.telemetry.extension_stage ||
		payload.telemetry.worker_stage ||
		payload.stages.at(-1)?.stage ||
		"WAITING_FOR_TELEMETRY"
	);
}

function humanizeWorkspaceMode(mode: WorkspaceMode) {
	if (mode === "F2V") return "Frames";
	if (mode === "I2V") return "Ingredients";
	if (mode === "IMG") return "Image";
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
	mode?: "T2V" | "F2V" | "I2V" | "IMG";
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
	const [modeRequests, setModeRequests] = useState<TelemetryRequest[]>([]);
	const [compactPane, setCompactPane] = useState<"workspace" | "jobs">(
		"workspace",
	);
	const [products, setProducts] = useState<Product[]>([]);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [packageReadiness, setPackageReadiness] = useState<
		Record<string, WorkspacePackageReadinessItem>
	>({});
	const [workspacePackage, setWorkspacePackage] =
		useState<WorkspaceExecutionPackage | null>(statePackage ?? null);
	const [isLoadingPackage, setIsLoadingPackage] = useState(false);
	const [isLoadingReadiness, setIsLoadingReadiness] = useState(false);
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
	const [notice, setNotice] = useState<OperatorNotice>({
		tone: "idle",
		title: "Idle",
		detail: "Submit a job to start Google Flow automation.",
		requestId: null,
	});
	const pollTimerRef = useRef<number | null>(null);

	const pathMode = location.pathname.split("/").pop()?.toUpperCase();
	const mode =
		propMode ||
		(pathMode === "T2V" ||
		pathMode === "F2V" ||
		pathMode === "I2V" ||
		pathMode === "IMG"
			? pathMode
			: "F2V");
	const selectedReadiness = selectedProduct
		? (packageReadiness[selectedProduct.id] ?? null)
		: null;

	useEffect(() => {
		void fetchProductCatalog(500)
			.then((response) => setProducts(response.items))
			.catch(() => {});
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
		setIsLoadingReadiness(true);
		void fetchWorkspacePackageReadiness({
			mode: mode as WorkspaceMode,
			product_ids: products.map((item) => item.id),
		})
			.then((response) => {
				const mapped = Object.fromEntries(
					response.items.map((item) => [item.product_id, item]),
				);
				setPackageReadiness(mapped);
			})
			.catch(() => {
				setPackageReadiness({});
			})
			.finally(() => setIsLoadingReadiness(false));
	}, [mode, products]);

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

	useEffect(() => {
		if (!isPortalMode) {
			setModeRequests([]);
			return;
		}

		const loadModeRequests = () => {
			fetchAPI<TelemetryRequest[]>("/api/telemetry/requests?limit=120")
				.then((items) => {
					const filtered = items.filter(
						(trace) =>
							trace.request_type === "MANUAL_FLOW_JOB" && trace.mode === mode,
					);
					setModeRequests(filtered);
				})
				.catch(() => {});
		};

		loadModeRequests();
		const timer = window.setInterval(loadModeRequests, 4000);
		return () => window.clearInterval(timer);
	}, [isPortalMode, mode]);

	const handleExecute = async (data: WorkspaceExecutePayload) => {
		setIsExecuting(true);
		console.log("Operator executing:", data);
		if (pollTimerRef.current != null) {
			window.clearTimeout(pollTimerRef.current);
			pollTimerRef.current = null;
		}

		const requestId = `manual_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
		setNotice({
			tone: "info",
			title: "Submitting to Flow",
			detail:
				"Bridge request accepted locally. Waiting for telemetry from the extension.",
			requestId,
		});

		const pollTelemetry = async (targetRequestId: string) => {
			try {
				const response = await fetch(
					`/api/telemetry/requests/${targetRequestId}`,
				);
				if (response.status === 404) {
					pollTimerRef.current = window.setTimeout(() => {
						void pollTelemetry(targetRequestId);
					}, 1200);
					return;
				}

				if (!response.ok) {
					throw new Error(`Telemetry HTTP ${response.status}`);
				}

				const payload = (await response.json()) as OperatorTelemetryResponse;
				const stageLabel = getLatestStageLabel(payload);
				const status = payload.telemetry.status;
				const errorMessage =
					payload.telemetry.error_message ||
					payload.stages.at(-1)?.message ||
					null;

				setNotice({
					tone: getNoticeTone(status),
					title:
						status === "COMPLETED"
							? "Generation started"
							: status === "FAILED"
								? "Generation failed"
								: "Flow job running",
					detail: errorMessage
						? `${stageLabel}: ${errorMessage}`
						: `Latest stage: ${stageLabel}`,
					requestId: targetRequestId,
				});

				if (status === "FAILED") {
					setIsExecuting(false);
					return;
				}

				if (status === "COMPLETED" || !ACTIVE_TELEMETRY_STATUSES.has(status)) {
					setIsExecuting(false);
					return;
				}

				pollTimerRef.current = window.setTimeout(() => {
					void pollTelemetry(targetRequestId);
				}, 1500);
			} catch (error: unknown) {
				const message =
					error instanceof Error
						? error.message
						: "Failed to read live Flow telemetry.";
				setNotice({
					tone: "error",
					title: "Telemetry unavailable",
					detail: message,
					requestId: targetRequestId,
				});
				setIsExecuting(false);
			}
		};

		try {
			const response = await fetch("/api/flow/execute-flow-job", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					...data,
					request_id: requestId,
					product_id: workspacePackage?.product_id ?? data.product_id ?? null,
					prompt_package_snapshot_id:
						workspacePackage?.prompt_package_snapshot_id ??
						data.prompt_package_snapshot_id ??
						null,
					workspace_execution_package_id:
						workspacePackage?.workspace_execution_package_id ??
						data.workspace_execution_package_id ??
						null,
					prompt_fingerprint:
						workspacePackage?.prompt_fingerprint ??
						data.prompt_fingerprint ??
						null,
					asset_fingerprints:
						workspacePackage?.request_lineage_payload?.asset_fingerprints ??
						data.asset_fingerprints ??
						[],
					request_lineage_payload:
						workspacePackage?.request_lineage_payload ??
						data.request_lineage_payload ??
						{},
				}),
			});

			if (!response.ok) {
				const err = await response.json();
				throw new Error(err.detail || "Execution failed");
			}

			const result = await response.json();
			console.log("Execution result:", result);
			setNotice({
				tone: "info",
				title: "Flow job accepted",
				detail:
					"Automation bridge accepted the request. Tracking stage updates now.",
				requestId,
			});
			void pollTelemetry(requestId);
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
			alert(`Execution Error: ${message}`);
			setIsExecuting(false);
		}
	};

	const handleLoadPackage = async () => {
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
		setIsLoadingPackage(true);
		try {
			const pkg = await createWorkspaceExecutionPackage({
				product_id: selectedProduct.id,
				mode,
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
			});
			setWorkspacePackage(pkg);
			setNotice({
				tone: "success",
				title: workspacePackage
					? "Final prompt regenerated"
					: "Approved package loaded",
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
					: "Failed to load approved package.";
			setNotice({
				tone: "error",
				title: "Package load failed",
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
	const compilerControlsVisible = mode === "F2V";
	const compilerButtonLabel =
		workspacePackage && compilerControlsVisible
			? "Regenerate Final Prompt"
			: compilerControlsVisible
				? "Load F2V Package + Generate Final Prompt"
				: `Load ${mode} Package`;

	const renderModule = () => {
		switch (mode) {
			case "F2V":
				return (
					<F2VModule
						onExecute={handleExecute}
						isExecuting={isExecuting}
						compact={isPortalMode}
						workspacePackage={workspacePackage}
					/>
				);
			case "T2V":
				return (
					<T2VModule
						onExecute={handleExecute}
						isExecuting={isExecuting}
						compact={isPortalMode}
						workspacePackage={workspacePackage}
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
					/>
				);
			case "IMG":
				return (
					<IMGModule
						onExecute={handleExecute}
						isExecuting={isExecuting}
						compact={isPortalMode}
						workspacePackage={workspacePackage}
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
						{mode} Production Workspace
					</h2>
					<p className="text-sm italic text-slate-400">
						Automating Google Flow with BOSMAX V4 precision.
					</p>
				</div>
				<div className="flex items-center gap-3">
					<div className="px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-[10px] font-bold uppercase tracking-widest">
						Mode: {mode === "F2V" ? "Frames to Video" : mode}
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

			<div className="mb-6 rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
				<div className="mb-3 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
					Approved Package Bridge
				</div>
				<div className="mb-4 text-[11px] text-slate-400">
					Workspace selector is hardened by mode readiness. Only READY products
					can load {humanizeWorkspaceMode(mode as WorkspaceMode)} packages.
				</div>
				<div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto]">
					<SearchableProductSelect
						products={products}
						selectedProduct={selectedProduct}
						onSelect={setSelectedProduct}
						readinessByProductId={packageReadiness}
					/>
					<button
						type="button"
						onClick={() => void handleLoadPackage()}
						disabled={
							!selectedProduct ||
							isLoadingPackage ||
							isLoadingReadiness ||
							selectedReadiness?.readiness_status !== "READY"
						}
						className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm font-semibold text-blue-100 disabled:opacity-50"
					>
						{isLoadingPackage ? "Loading package..." : compilerButtonLabel}
					</button>
				</div>
				{compilerControlsVisible ? (
					<div className="mt-4 rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
						<div className="text-[10px] font-bold uppercase tracking-[0.22em] text-slate-500">
							UGC Prompt Compiler Controls
						</div>
						<div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
							<div className="space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Generation Mode
								</div>
								<select
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
										Single mode compiles one anchor block. Switch Generation
										Mode to Extend to unlock Block 2 duration.
									</div>
								</div>
							)}
							<div className="space-y-2">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Camera Style
								</div>
								<select
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
							<div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3 text-[11px] text-slate-300">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Shot Plan
								</div>
								<div className="mt-2">
									Block 1: {shotPolicy1?.recommended ?? "-"} recommended shot(s)
								</div>
								{generationMode === "EXTEND" ? (
									<div className="mt-1">
										Block 2: {shotPolicy2?.recommended ?? "-"} recommended
										shot(s)
									</div>
								) : null}
							</div>
							<div className="rounded-xl border border-slate-800 bg-slate-900/70 px-3 py-3 text-[11px] text-slate-300">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Language Policy
								</div>
								<div className="mt-2">
									{targetLanguage} body WPS:{" "}
									{promptConfig?.language_wps_policy[targetLanguage]
										?.body_wps ?? "-"}
								</div>
								<div className="mt-1">
									Absolute ceiling:{" "}
									{promptConfig?.language_wps_policy[targetLanguage]
										?.absolute_ceiling_wps ?? "-"}
								</div>
							</div>
						</div>
					</div>
				) : null}
				{selectedReadiness ? (
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
				) : !isLoadingReadiness ? (
					<div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-xs text-slate-400">
						No {humanizeWorkspaceMode(mode as WorkspaceMode)}-ready products are
						auto-selected. Choose a product and review its readiness checklist
						first.
					</div>
				) : null}
				{workspacePackage ? (
					<div className="mt-4 grid gap-3 md:grid-cols-3">
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
				) : null}
			</div>

			<div
				className={`mb-6 rounded-2xl border px-4 py-3 text-sm ${notice.tone === "error" ? "border-red-500/40 bg-red-500/10 text-red-200" : notice.tone === "success" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200" : notice.tone === "info" ? "border-blue-500/40 bg-blue-500/10 text-blue-200" : "border-slate-800 bg-slate-900/40 text-slate-300"}`}
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
