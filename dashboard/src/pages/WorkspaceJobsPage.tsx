import {
	AlertTriangle,
	CheckCircle2,
	Clock3,
	LoaderCircle,
	RefreshCcw,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DataTable } from "../components/ui";
import { fetchAPI } from "../api/client";
import { fetchProductCatalog } from "../api/products";
import type {
	Product,
	TelemetryRequest,
	TelemetryRequestDetail,
	WorkspaceMode,
} from "../types";
import {
	buildTelemetryHandoffTimeline,
	classifyTelemetryExecution,
	formatExactDateTime,
	formatRelativeTime,
	getTelemetryCurrentOwner,
	getTelemetryMode,
	getTelemetryModeLabel,
	getTelemetryPrimaryRemark,
	getTelemetryRequestLabel,
	getTelemetryStage,
	getTelemetryStatusLabel,
	getTelemetryStatusTone,
	getTelemetryStuckRemark,
	getTelemetryUpdatedAt,
	sortTelemetryByUpdatedAt,
} from "../utils/telemetryReporting";

type StatusFilter = "ALL" | "WAITING" | "RUNNING" | "COMPLETED" | "FAILED";
type ModeFilter = "ALL" | WorkspaceMode;


const MODE_FILTERS: Array<{ id: ModeFilter; label: string }> = [
	{ id: "ALL", label: "All" },
	{ id: "T2V", label: "T2V" },
	{ id: "F2V", label: "F2V / HYBRID" },
	{ id: "I2V", label: "I2V" },
	{ id: "IMG", label: "IMG" },
];

const STATUS_FILTERS: Array<{ id: StatusFilter; label: string }> = [
	{ id: "ALL", label: "All" },
	{ id: "WAITING", label: "Waiting" },
	{ id: "RUNNING", label: "Running" },
	{ id: "COMPLETED", label: "Completed" },
	{ id: "FAILED", label: "Failed" },
];

function StatusBadge({ status }: { status: string }) {
	const tone = getTelemetryStatusTone(status);
	const palette =
		tone === "failed"
			? "border-red-500/40 bg-red-500/10 text-red-200"
			: tone === "success"
				? "border-emerald-500/40 bg-emerald-500/10 text-emerald-200"
				: tone === "running"
					? "border-blue-500/40 bg-blue-500/10 text-blue-200"
					: tone === "waiting"
						? "border-amber-500/40 bg-amber-500/10 text-amber-200"
						: "border-slate-700 bg-slate-900 text-slate-300";

	return (
		<span
			className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] ${palette}`}
		>
			{getTelemetryStatusLabel(status)}
		</span>
	);
}

function StatusIcon({ status }: { status: string }) {
	const tone = getTelemetryStatusTone(status);
	if (tone === "failed") {
		return <AlertTriangle size={16} className="text-red-300" />;
	}
	if (tone === "success") {
		return <CheckCircle2 size={16} className="text-emerald-300" />;
	}
	if (tone === "running") {
		return <LoaderCircle size={16} className="animate-spin text-blue-300" />;
	}
	return <Clock3 size={16} className="text-amber-300" />;
}

function matchesStatusFilter(trace: TelemetryRequest, filter: StatusFilter) {
	const tone = getTelemetryStatusTone(trace.status);
	if (filter === "ALL") return true;
	if (filter === "WAITING") return tone === "waiting";
	if (filter === "RUNNING") return tone === "running";
	if (filter === "COMPLETED") return tone === "success";
	if (filter === "FAILED") return tone === "failed";
	return true;
}

function resolveProductLabel(
	trace: TelemetryRequest,
	productById: Record<string, Product>,
) {
	if (!trace.product_id) return "No linked product";
	const product = productById[trace.product_id];
	if (!product) return trace.product_id;
	return (
		product.product_display_name ||
		product.product_short_name ||
		product.raw_product_title ||
		trace.product_id
	);
}

function resolveProductMeta(
	trace: TelemetryRequest,
	productById: Record<string, Product>,
) {
	if (!trace.product_id) return "Package metadata unavailable";
	const product = productById[trace.product_id];
	if (!product) return `Product ID ${trace.product_id}`;
	return `${product.source} • Product ID ${trace.product_id}`;
}

function getWorkspaceJobModeLabel(trace: TelemetryRequest) {
	const mode = getTelemetryMode(trace);
	if (mode === "F2V") return "F2V / HYBRID";
	return getTelemetryModeLabel(trace);
}

export default function WorkspaceJobsPage() {
	const [requests, setRequests] = useState<TelemetryRequest[]>([]);
	const [products, setProducts] = useState<Record<string, Product>>({});
	const [productsError, setProductsError] = useState<string | null>(null);
	const [search, setSearch] = useState("");
	const [modeFilter, setModeFilter] = useState<ModeFilter>("ALL");
	const [statusFilter, setStatusFilter] = useState<StatusFilter>("ALL");
	const [selectedRequestId, setSelectedRequestId] = useState<string | null>(
		null,
	);
	const [detail, setDetail] = useState<TelemetryRequestDetail | null>(null);
	const [detailLoading, setDetailLoading] = useState(false);
	const [detailError, setDetailError] = useState("");

	const loadTelemetry = useCallback(() => {
		fetchAPI<TelemetryRequest[]>("/api/telemetry/requests?limit=200")
			.then((items) =>
				setRequests(
					items.filter((trace) => trace.request_type !== "TELEMETRY_SELF_TEST"),
				),
			)
			.catch(() => {});
	}, []);

	useEffect(() => {
		let inFlight = false;
		const runLoadTelemetry = () => {
			if (document.hidden || inFlight) {
				return;
			}
			inFlight = true;
			void Promise.resolve(loadTelemetry()).finally(() => {
				inFlight = false;
			});
		};
		const handleVisibilityChange = () => {
			if (!document.hidden) {
				runLoadTelemetry();
			}
		};

		runLoadTelemetry();
		document.addEventListener("visibilitychange", handleVisibilityChange);
		const timer = window.setInterval(runLoadTelemetry, 10000);
		return () => {
			document.removeEventListener("visibilitychange", handleVisibilityChange);
			window.clearInterval(timer);
		};
	}, [loadTelemetry]);

	useEffect(() => {
		void fetchProductCatalog(500)
			.then((response) => {
				setProducts(
					Object.fromEntries(
						(response.items ?? []).map((product) => [product.id, product]),
					),
				);
			})
			.catch((err: unknown) => {
				setProducts({});
				setProductsError(
					err instanceof Error ? err.message : "Failed to load product catalog",
				);
			});
	}, []);

	const filteredRequests = useMemo(() => {
		const query = search.trim().toLowerCase();
		return sortTelemetryByUpdatedAt(requests).filter((trace) => {
			const resolvedMode = getTelemetryMode(trace);
			if (modeFilter !== "ALL" && resolvedMode !== modeFilter) {
				return false;
			}
			if (!matchesStatusFilter(trace, statusFilter)) {
				return false;
			}
			if (!query) return true;

			const haystack = [
				trace.request_id,
				getTelemetryRequestLabel(trace),
				getWorkspaceJobModeLabel(trace),
				getTelemetryStage(trace),
				getTelemetryPrimaryRemark(trace),
				resolveProductLabel(trace, products),
				trace.product_id || "",
			]
				.join(" ")
				.toLowerCase();
			return haystack.includes(query);
		});
	}, [modeFilter, products, requests, search, statusFilter]);


	useEffect(() => {
		if (!selectedRequestId && filteredRequests.length > 0) {
			setSelectedRequestId(filteredRequests[0].request_id);
			return;
		}
		if (
			selectedRequestId &&
			!filteredRequests.some((trace) => trace.request_id === selectedRequestId)
		) {
			setSelectedRequestId(filteredRequests[0]?.request_id || null);
		}
	}, [filteredRequests, selectedRequestId]);

	useEffect(() => {
		if (!selectedRequestId) {
			setDetail(null);
			setDetailError("");
			return;
		}

		let disposed = false;
		setDetailLoading(true);
		setDetailError("");

		void fetchAPI<TelemetryRequestDetail>(
			`/api/telemetry/requests/${selectedRequestId}`,
		)
			.then((payload) => {
				if (disposed) return;
				setDetail(payload);
			})
			.catch((error: Error) => {
				if (disposed) return;
				setDetail(null);
				setDetailError(error.message || "Failed to load request detail.");
			})
			.finally(() => {
				if (disposed) return;
				setDetailLoading(false);
			});

		return () => {
			disposed = true;
		};
	}, [selectedRequestId]);


	const selectedTrace =
		filteredRequests.find((trace) => trace.request_id === selectedRequestId) ||
		null;
	const selectedTelemetry = detail?.telemetry || selectedTrace;
	const diagnosis = selectedTelemetry
		? classifyTelemetryExecution(selectedTelemetry, detail)
		: null;
	const currentOwner = selectedTelemetry
		? getTelemetryCurrentOwner(selectedTelemetry, detail)
		: "Unknown";
	const handoffTimeline = selectedTelemetry
		? buildTelemetryHandoffTimeline(selectedTelemetry, detail)
		: [];
	const selectedRemark = selectedTelemetry
		? getTelemetryPrimaryRemark(selectedTelemetry, detail)
		: "Select a job to inspect its stage history and operator remark.";
	const stuckRemark = selectedTelemetry
		? getTelemetryStuckRemark(selectedTelemetry, detail)
		: null;

	const summary = useMemo(() => {
		return filteredRequests.reduce(
			(acc, trace) => {
				const tone = getTelemetryStatusTone(trace.status);
				acc.total += 1;
				if (tone === "waiting") acc.waiting += 1;
				if (tone === "running") acc.running += 1;
				if (tone === "success") acc.completed += 1;
				if (tone === "failed") acc.failed += 1;
				return acc;
			},
			{ total: 0, waiting: 0, running: 0, completed: 0, failed: 0 },
		);
	}, [filteredRequests]);

	return (
		<div className="min-h-full space-y-6 bg-slate-950 px-4 py-4 md:px-8 md:py-8">
			{productsError && (
				<div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2 text-[11px] text-rose-300">
					Product list failed to load: {productsError}
				</div>
			)}
			<div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
				<div>
					<h2 className="text-xl font-bold tracking-tight text-white md:text-2xl">
						Workspace Jobs
					</h2>
					<p className="mt-2 max-w-3xl text-sm text-slate-400">
						Unified read-only workspace reporting for Text to Video, Frames,
						Ingredients, and Image authoring. Use this page to inspect request
						status, latest stage, remarks, and recorded telemetry history
						without cluttering authoring surfaces.
					</p>
				</div>
				<button
					type="button"
					onClick={loadTelemetry}
					className="inline-flex items-center gap-2 rounded-full border border-slate-700 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200"
				>
					<RefreshCcw size={14} />
					Refresh Jobs
				</button>
			</div>

			<div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
				{[
					{
						label: "Total",
						value: summary.total,
						tone: "border-slate-700 bg-slate-900/60 text-slate-100",
					},
					{
						label: "Waiting",
						value: summary.waiting,
						tone: "border-amber-500/30 bg-amber-500/10 text-amber-100",
					},
					{
						label: "Running",
						value: summary.running,
						tone: "border-blue-500/30 bg-blue-500/10 text-blue-100",
					},
					{
						label: "Completed",
						value: summary.completed,
						tone: "border-emerald-500/30 bg-emerald-500/10 text-emerald-100",
					},
					{
						label: "Failed",
						value: summary.failed,
						tone: "border-red-500/30 bg-red-500/10 text-red-100",
					},
				].map((card) => (
					<div
						key={card.label}
						className={`rounded-2xl border px-4 py-4 ${card.tone}`}
					>
						<div className="text-[10px] font-semibold uppercase tracking-[0.18em] opacity-80">
							{card.label}
						</div>
						<div className="mt-3 text-3xl font-semibold">{card.value}</div>
					</div>
				))}
			</div>

			<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
				<div className="grid gap-4 xl:grid-cols-[auto_auto_minmax(0,1fr)] xl:items-end">
					<div>
						<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
							Mode
						</div>
						<div className="mt-2 flex flex-wrap gap-2">
							{MODE_FILTERS.map((filter) => (
								<button
									key={filter.id}
									type="button"
									onClick={() => setModeFilter(filter.id)}
									className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] ${modeFilter === filter.id ? "border-blue-400/60 bg-blue-500/10 text-blue-200" : "border-slate-700 bg-slate-950 text-slate-400 hover:text-slate-200"}`}
								>
									{filter.label}
								</button>
							))}
						</div>
					</div>
					<div>
						<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
							Status
						</div>
						<div className="mt-2 flex flex-wrap gap-2">
							{STATUS_FILTERS.map((filter) => (
								<button
									key={filter.id}
									type="button"
									onClick={() => setStatusFilter(filter.id)}
									className={`rounded-full border px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] ${statusFilter === filter.id ? "border-blue-400/60 bg-blue-500/10 text-blue-200" : "border-slate-700 bg-slate-950 text-slate-400 hover:text-slate-200"}`}
								>
									{filter.label}
								</button>
							))}
						</div>
					</div>
					<div>
						<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
							Search
						</div>
						<input
							value={search}
							onChange={(event) => setSearch(event.target.value)}
							placeholder="Search request ID, mode, stage, error, product..."
							className="mt-2 w-full rounded-full border border-slate-700 bg-slate-950 px-4 py-2 text-xs text-slate-200 outline-none placeholder:text-slate-500 focus:border-blue-400/50"
						/>
					</div>
				</div>
				<div className="mt-3 text-[11px] text-slate-400">
					Showing {filteredRequests.length} request(s), newest first.
				</div>
				<div className="mt-1 text-[11px] text-slate-500">
					Telemetry is still job-mode authoritative here, so HYBRID activity is
					reported inside the F2V lineage.
				</div>
			</div>

			<div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.45fr)_minmax(360px,0.95fr)]">
				<div className="overflow-hidden rounded-3xl border border-slate-800 bg-slate-950/80">
					<div className="p-3">
						<DataTable
							rows={filteredRequests}
							getRowId={(t) => t.request_id}
							pageSize={20}
							selectedRowId={selectedRequestId}
							emptyLabel="No workspace jobs match the current filters."
							minWidthClassName="min-w-[1040px]"
							initialSort={{ key: "created", dir: "desc" }}
							columns={[
								{
									key: "request_id",
									header: "Request ID",
									sortValue: (t) => t.request_id,
									render: (t) => <div className="font-mono text-xs text-slate-100">{t.request_id}</div>,
								},
								{
									key: "type",
									header: "Job Type / Mode",
									render: (t) => (
										<div>
											<div className="flex items-center gap-2 font-semibold text-slate-100">
												<StatusIcon status={t.status} />
												<span>{getTelemetryRequestLabel(t)}</span>
											</div>
											<div className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-500">
												{getWorkspaceJobModeLabel(t)}
											</div>
										</div>
									),
								},
								{
									key: "product",
									header: "Product / Package",
									render: (t) => (
										<div>
											<div className="font-medium text-slate-100">{resolveProductLabel(t, products)}</div>
											<div className="mt-1 text-xs text-slate-500">{resolveProductMeta(t, products)}</div>
										</div>
									),
								},
								{
									key: "status",
									header: "Status",
									sortValue: (t) => t.status,
									render: (t) => <StatusBadge status={t.status} />,
								},
								{
									key: "stage",
									header: "Latest Stage",
									render: (t) => <span className="text-xs text-slate-300">{getTelemetryStage(t)}</span>,
								},
								{
									key: "created",
									header: "Created / Updated",
									sortValue: (t) => t.created_at,
									render: (t) => (
										<div className="text-xs text-slate-300">
											<div>Created {formatExactDateTime(t.created_at)}</div>
											<div className="mt-1 text-slate-500">
												Updated {formatRelativeTime(getTelemetryUpdatedAt(t))}
											</div>
										</div>
									),
								},
								{
									key: "remark",
									header: "Error / Remark",
									render: (t) => <span className="text-xs text-slate-300">{getTelemetryPrimaryRemark(t)}</span>,
								},
							]}
							rowActions={(t) => (
								<button
									type="button"
									onClick={() => setSelectedRequestId(t.request_id)}
									className={`rounded-full border px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] ${t.request_id === selectedRequestId ? "border-blue-400/60 bg-blue-500/10 text-blue-200" : "border-slate-700 bg-slate-950 text-slate-300 hover:border-blue-400/50 hover:text-blue-200"}`}
								>
									View Details
								</button>
							)}
						/>
					</div>
				</div>

				<div className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5 xl:sticky xl:top-4">
					{!selectedTelemetry ? (
						<div className="text-sm text-slate-400">
							Select a job to inspect its request metadata, stage history, and
							operator remark.
						</div>
					) : (
						<div className="grid gap-4">
							<div className="flex flex-wrap items-start justify-between gap-3">
								<div>
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
										Selected Job
									</div>
									<div className="mt-2 text-lg font-semibold text-slate-100">
										{getTelemetryRequestLabel(selectedTelemetry)}
									</div>
									<div className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-500">
										{getWorkspaceJobModeLabel(selectedTelemetry)} •{" "}
										{selectedTelemetry.request_id}
									</div>
								</div>
								<StatusBadge status={selectedTelemetry.status} />
							</div>

							<div className="grid gap-3 md:grid-cols-2">
								<div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-3">
									<div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
										Request ID
									</div>
									<div className="mt-1 break-all font-mono text-sm text-slate-100">
										{selectedTelemetry.request_id}
									</div>
								</div>
								<div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-3">
									<div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
										Current Owner
									</div>
									<div className="mt-1 text-sm text-slate-100">
										{currentOwner}
									</div>
								</div>
								<div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-3">
									<div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
										Product / Package
									</div>
									<div className="mt-1 text-sm text-slate-100">
										{resolveProductLabel(selectedTelemetry, products)}
									</div>
									<div className="mt-1 text-xs text-slate-500">
										{resolveProductMeta(selectedTelemetry, products)}
									</div>
								</div>
								<div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-3">
									<div className="text-[10px] uppercase tracking-[0.18em] text-slate-500">
										Created / Updated
									</div>
									<div className="mt-1 text-sm text-slate-100">
										{formatExactDateTime(selectedTelemetry.created_at)}
									</div>
									<div className="mt-1 text-xs text-slate-500">
										Updated{" "}
										{formatExactDateTime(
											getTelemetryUpdatedAt(selectedTelemetry),
										)}
									</div>
								</div>
							</div>

							{diagnosis ? (
								<div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
									<div className="flex flex-wrap items-start justify-between gap-3">
										<div>
											<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
												Execution Diagnosis
											</div>
											<div className="mt-2 text-base font-semibold text-slate-100">
												{diagnosis.label}
											</div>
											<div className="mt-1 text-sm text-slate-300">
												{diagnosis.summary}
											</div>
										</div>
										<StatusBadge status={selectedTelemetry.status} />
									</div>
									<div className="mt-3 text-sm text-slate-300">
										{diagnosis.detail}
									</div>
									{stuckRemark ? (
										<div className="mt-3 text-xs text-red-200">
											{stuckRemark}
										</div>
									) : null}
								</div>
							) : null}

							<div className="rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Operator Remark
								</div>
								<div className="mt-2 text-sm text-slate-200">
									{selectedRemark}
								</div>
							</div>

							<div>
								<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Handoff Trail
								</div>
								<div className="grid gap-2">
									{handoffTimeline.map((step) => (
										<div
											key={step.id}
											className="rounded-2xl border border-slate-800 bg-slate-900/60 p-3"
										>
											<div className="flex items-start justify-between gap-3">
												<div>
													<div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-200">
														{step.label}
													</div>
													<div className="mt-1 text-[11px] text-slate-500">
														{step.timestamp
															? formatExactDateTime(step.timestamp)
															: "No timestamp yet"}
													</div>
												</div>
												<div className="rounded-full border border-slate-700 bg-slate-950 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-300">
													{step.state}
												</div>
											</div>
											<div className="mt-2 text-xs text-slate-300">
												{step.detail}
											</div>
										</div>
									))}
								</div>
							</div>

							<div>
								<div className="mb-2 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									Recorded Stage History
								</div>
								{detailLoading ? (
									<div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">
										Loading stage detail...
									</div>
								) : detailError ? (
									<div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
										{detailError}
									</div>
								) : detail?.stages?.length ? (
									<div className="grid gap-2">
										{detail.stages.map((stage) => (
											<div
												key={stage.id}
												className="rounded-2xl border border-slate-800 bg-slate-900/60 p-3"
											>
												<div className="flex items-start justify-between gap-3">
													<div>
														<div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-200">
															{stage.stage}
														</div>
														<div className="mt-1 text-[11px] text-slate-500">
															{stage.source} •{" "}
															{formatExactDateTime(stage.timestamp)}
														</div>
													</div>
													<StatusBadge status={stage.status} />
												</div>
												<div className="mt-2 text-xs text-slate-300">
													{stage.message || "No remark for this stage."}
												</div>
											</div>
										))}
									</div>
								) : (
									<div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 text-sm text-slate-400">
										No recorded stage history for this request yet.
									</div>
								)}
							</div>
						</div>
					)}
				</div>
			</div>
		</div>
	);
}
