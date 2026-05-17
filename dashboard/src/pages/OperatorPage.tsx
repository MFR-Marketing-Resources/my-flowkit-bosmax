import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { fetchAPI } from "../api/client";
import { fetchProductCatalog } from "../api/products";
import { createWorkspaceExecutionPackage } from "../api/workspacePackages";
import RequestReportPanel from "../components/reporting/RequestReportPanel";
import F2VModule from "../components/workspace/F2VModule";
import I2VModule from "../components/workspace/I2VModule";
import IMGModule from "../components/workspace/IMGModule";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import T2VModule from "../components/workspace/T2VModule";
import type {
	Product,
	TelemetryRequest,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
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

interface OperatorPageProps {
	mode?: "T2V" | "F2V" | "I2V" | "IMG";
}

export default function OperatorPage({ mode: propMode }: OperatorPageProps) {
	const location = useLocation();
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
	const [workspacePackage, setWorkspacePackage] =
		useState<WorkspaceExecutionPackage | null>(statePackage ?? null);
	const [isLoadingPackage, setIsLoadingPackage] = useState(false);
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

	useEffect(() => {
		void fetchProductCatalog(500)
			.then((response) => setProducts(response.items))
			.catch(() => {});
	}, []);

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
	}, [mode]);

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
		if (!selectedProduct) return;
		setIsLoadingPackage(true);
		try {
			const pkg = await createWorkspaceExecutionPackage({
				product_id: selectedProduct.id,
				mode,
			});
			setWorkspacePackage(pkg);
			setNotice({
				tone: "success",
				title: "Approved package loaded",
				detail: `Workspace now uses locked ${mode} payload from product truth.`,
				requestId: pkg.workspace_execution_package_id,
			});
		} catch (error: unknown) {
			const message =
				error instanceof Error
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
				<div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto]">
					<SearchableProductSelect
						products={products}
						selectedProduct={selectedProduct}
						onSelect={setSelectedProduct}
					/>
					<button
						type="button"
						onClick={() => void handleLoadPackage()}
						disabled={!selectedProduct || isLoadingPackage}
						className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-3 text-sm font-semibold text-blue-100 disabled:opacity-50"
					>
						{isLoadingPackage ? "Loading package..." : `Load ${mode} Package`}
					</button>
				</div>
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

			<div
				className={`${isPortalMode ? "flex-1 min-h-0" : "grid flex-1 min-h-0 gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.95fr)]"}`}
			>
				{(!isPortalMode || compactPane === "workspace") && (
					<div className="min-h-0">{renderModule()}</div>
				)}

				{(!isPortalMode || compactPane === "jobs") && (
					<div className="min-h-0">
						<RequestReportPanel
							requests={modeRequests}
							title={`${mode === "F2V" ? "Frames" : mode === "T2V" ? "Text to Video" : mode === "I2V" ? "Ingredients" : "Image"} Workspace Jobs`}
							description="This is the work list for the current operator page. Use it to confirm whether a run is waiting, processing, completed, or failed, and read the remark before troubleshooting."
							emptyMessage="No jobs recorded for this workspace yet. New submissions from this page will appear here automatically."
							maxItems={18}
						/>
					</div>
				)}
			</div>
		</div>
	);
}
