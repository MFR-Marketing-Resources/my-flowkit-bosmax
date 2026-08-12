import { Copy, RefreshCcw, Siren } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { fetchAPI } from "../api/client";
import { KpiCard } from "../components/reporting/KpiCard";
import {
	Badge,
	type BadgeTone,
	DataTable,
	type DataTableColumn,
	type DataTableFilter,
	Section,
} from "../components/ui";
import type { TelemetryRequest, TelemetryRequestDetail } from "../types";
import { formatKualaLumpurDateTime } from "../utils/dateTime";
import { buildCsv, downloadFile } from "../utils/exportFiles";
import {
	getTelemetryModeLabel,
	getTelemetryPrimaryRemark,
	getTelemetryRequestLabel,
	getTelemetryStage,
	getTelemetryStatusLabel,
	getTelemetryStatusTone,
	getTelemetryUpdatedAt,
	sortTelemetryByUpdatedAt,
} from "../utils/telemetryReporting";

type QueueFilter = "FAILED_OR_ERROR" | "RUNNING" | "WAITING" | "ALL";

const STATUS_TONE: Record<string, BadgeTone> = {
	waiting: "warn",
	running: "info",
	success: "success",
	failed: "danger",
};
const toneFor = (status: string | null | undefined): BadgeTone =>
	STATUS_TONE[getTelemetryStatusTone(status)] ?? "neutral";

function priorityLabel(trace: TelemetryRequest): string {
	const tone = getTelemetryStatusTone(trace.status);
	if (tone === "failed") return "Critical";
	if (tone === "running") return "Live";
	if (tone === "waiting") return "Queued";
	return "Resolved";
}

function matchesQueueFilter(trace: TelemetryRequest, filter: QueueFilter) {
	const tone = getTelemetryStatusTone(trace.status);
	if (filter === "ALL") return true;
	if (filter === "FAILED_OR_ERROR")
		return trace.status === "FAILED" || Boolean(trace.error_message);
	if (filter === "RUNNING") return tone === "running";
	if (filter === "WAITING") return tone === "waiting";
	return true;
}

function buildIncidentBrief(
	trace: TelemetryRequest | null,
	detail: TelemetryRequestDetail | null,
) {
	if (!trace) return "No failed incident selected.";
	const timeline = detail?.stages?.length
		? detail.stages
				.map(
					(stage) =>
						`- ${formatKualaLumpurDateTime(stage.timestamp)} | ${stage.source} | ${stage.stage} | ${stage.status}${stage.message ? ` | ${stage.message}` : ""}`,
				)
				.join("\n")
		: "- No stage history recorded.";
	return [
		"BOSMAX Troubleshoot Brief",
		`Captured: ${formatKualaLumpurDateTime(getTelemetryUpdatedAt(trace))}`,
		`Request ID: ${trace.request_id}`,
		`Project ID: ${trace.project_id || "N/A"}`,
		`Video ID: ${trace.video_id || "N/A"}`,
		`Scene ID: ${trace.scene_id || "N/A"}`,
		`Mode: ${getTelemetryModeLabel(trace)}`,
		`Request Type: ${getTelemetryRequestLabel(trace)}`,
		`Status: ${getTelemetryStatusLabel(trace.status)}`,
		`Current Stage: ${getTelemetryStage(trace)}`,
		`Primary Remark: ${getTelemetryPrimaryRemark(trace, detail)}`,
		"",
		"Stage Timeline:",
		timeline,
	].join("\n");
}

const BTN =
	"inline-flex items-center rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-300 transition hover:border-blue-400/50 hover:text-blue-200";

export default function TroubleshootPage() {
	const [requests, setRequests] = useState<TelemetryRequest[]>([]);
	const [selectedRequestId, setSelectedRequestId] = useState<string | null>(
		null,
	);
	const [detail, setDetail] = useState<TelemetryRequestDetail | null>(null);
	const [detailError, setDetailError] = useState("");
	const [copied, setCopied] = useState(false);
	const [queueFilter, setQueueFilter] =
		useState<QueueFilter>("FAILED_OR_ERROR");

	useEffect(() => {
		const load = () => {
			fetchAPI<TelemetryRequest[]>("/api/telemetry/requests?limit=200")
				.then(setRequests)
				.catch(() => {});
		};
		load();
		const timer = window.setInterval(load, 4000);
		return () => window.clearInterval(timer);
	}, []);

	const modeOptions = useMemo(
		() =>
			Array.from(new Set(requests.map((t) => getTelemetryModeLabel(t)))).sort(),
		[requests],
	);

	const queueItems = useMemo(
		() =>
			sortTelemetryByUpdatedAt(
				requests.filter((trace) => matchesQueueFilter(trace, queueFilter)),
			),
		[queueFilter, requests],
	);

	const summary = useMemo(() => {
		return requests.reduce(
			(acc, trace) => {
				const tone = getTelemetryStatusTone(trace.status);
				if (tone === "waiting") acc.waiting += 1;
				if (tone === "running") acc.running += 1;
				if (tone === "success") acc.completed += 1;
				if (tone === "failed") acc.failed += 1;
				return acc;
			},
			{ waiting: 0, running: 0, completed: 0, failed: 0 },
		);
	}, [requests]);

	useEffect(() => {
		if (!selectedRequestId && queueItems.length > 0) {
			setSelectedRequestId(queueItems[0].request_id);
			return;
		}
		if (
			selectedRequestId &&
			!queueItems.some((trace) => trace.request_id === selectedRequestId)
		) {
			setSelectedRequestId(queueItems[0]?.request_id || null);
		}
	}, [queueItems, selectedRequestId]);

	useEffect(() => {
		if (!selectedRequestId) {
			setDetail(null);
			setDetailError("");
			return;
		}
		let disposed = false;
		fetchAPI<TelemetryRequestDetail>(
			`/api/telemetry/requests/${selectedRequestId}`,
		)
			.then((payload) => {
				if (disposed) return;
				setDetail(payload);
				setDetailError("");
			})
			.catch((error) => {
				if (disposed) return;
				setDetail(null);
				setDetailError(error.message || "Failed to load incident detail.");
			});
		return () => {
			disposed = true;
		};
	}, [selectedRequestId]);

	const selectedTrace =
		queueItems.find((trace) => trace.request_id === selectedRequestId) || null;
	const incidentBrief = useMemo(
		() => buildIncidentBrief(selectedTrace, detail),
		[detail, selectedTrace],
	);

	const handleCopy = async () => {
		try {
			await navigator.clipboard.writeText(incidentBrief);
			setCopied(true);
			window.setTimeout(() => setCopied(false), 1800);
		} catch {
			setCopied(false);
		}
	};

	const exportRow = (t: TelemetryRequest) => ({
		request_id: t.request_id,
		project_id: t.project_id || "",
		video_id: t.video_id || "",
		scene_id: t.scene_id || "",
		mode: getTelemetryModeLabel(t),
		request_type: getTelemetryRequestLabel(t),
		status: getTelemetryStatusLabel(t.status),
		priority: priorityLabel(t),
		remark: getTelemetryPrimaryRemark(t),
		updated_at_myt: formatKualaLumpurDateTime(getTelemetryUpdatedAt(t)),
	});

	const handleExportQueueJson = () => {
		downloadFile(
			"bosmax-troubleshoot-queue.json",
			JSON.stringify(queueItems.map(exportRow), null, 2),
			"application/json;charset=utf-8",
		);
	};

	const handleExportQueueCsv = () => {
		const cols = [
			"request_id",
			"project_id",
			"video_id",
			"scene_id",
			"mode",
			"request_type",
			"status",
			"priority",
			"remark",
			"updated_at_myt",
		] as const;
		const csv = buildCsv(
			[...cols],
			queueItems.map((t) => {
				const r = exportRow(t);
				return cols.map((c) => r[c]);
			}),
		);
		downloadFile("bosmax-troubleshoot-queue.csv", csv, "text/csv;charset=utf-8");
	};

	const handleExportBrief = () => {
		downloadFile(
			`bosmax-incident-${selectedTrace?.request_id || "empty"}.txt`,
			incidentBrief,
		);
	};

	const columns: DataTableColumn<TelemetryRequest>[] = [
		{
			key: "incident",
			header: "Incident",
			render: (t) => (
				<div className="min-w-0">
					<div className="truncate font-medium text-slate-100">
						{getTelemetryRequestLabel(t)}
					</div>
					<div className="mt-0.5 truncate text-[10px] uppercase tracking-[0.14em] text-slate-500">
						{getTelemetryModeLabel(t)}
					</div>
				</div>
			),
			sortValue: (t) => getTelemetryRequestLabel(t),
		},
		{
			key: "remark",
			header: "Remark",
			render: (t) => (
				<span className="line-clamp-2 text-xs text-slate-400">
					{getTelemetryPrimaryRemark(t)}
				</span>
			),
		},
		{
			key: "status",
			header: "Status",
			render: (t) => (
				<Badge tone={toneFor(t.status)}>
					{getTelemetryStatusLabel(t.status)}
				</Badge>
			),
			sortValue: (t) => getTelemetryStatusLabel(t.status),
		},
		{
			key: "priority",
			header: "Priority",
			render: (t) => <Badge tone={toneFor(t.status)}>{priorityLabel(t)}</Badge>,
		},
		{
			key: "updated",
			header: "Updated",
			render: (t) => (
				<span className="whitespace-nowrap text-[11px] text-slate-500">
					{formatKualaLumpurDateTime(getTelemetryUpdatedAt(t))}
				</span>
			),
			sortValue: (t) => getTelemetryUpdatedAt(t),
		},
	];

	const modeFilterDef: DataTableFilter<TelemetryRequest> = {
		key: "mode",
		label: "Mode",
		options: modeOptions.map((m) => ({ value: m, label: m })),
		value: (t) => getTelemetryModeLabel(t),
	};

	return (
		<div className="mx-auto flex h-full max-w-[1400px] flex-col gap-6 p-4 md:p-6">
			<header>
				<div className="flex items-center gap-2 text-blue-300">
					<Siren size={20} />
					<span className="text-[10px] font-bold uppercase tracking-[0.2em]">
						Operations
					</span>
				</div>
				<h1 className="mt-1 text-2xl font-bold text-slate-100">Troubleshoot</h1>
				<p className="mt-2 max-w-3xl text-sm text-slate-400">
					Live incident desk — failed, running and waiting jobs with a
					copy-ready brief for AI. Refreshes automatically; times are Malaysia
					time.
				</p>
			</header>

			<div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
				<KpiCard label="Pending" value={summary.waiting} tone="warn" />
				<KpiCard label="Processing" value={summary.running} tone="info" />
				<KpiCard label="Success" value={summary.completed} tone="success" />
				<KpiCard label="Failed" value={summary.failed} tone="danger" />
			</div>

			<div className="grid gap-6 xl:grid-cols-[minmax(360px,0.95fr)_minmax(0,1.3fr)]">
				<Section
					title="Incident queue"
					helper="Failed items lead; switch the status filter to inspect running or waiting work."
					action={
						<div className="flex gap-2">
							<button
								type="button"
								onClick={handleExportQueueCsv}
								className={BTN}
							>
								Export CSV
							</button>
							<button
								type="button"
								onClick={handleExportQueueJson}
								className={BTN}
							>
								Export JSON
							</button>
						</div>
					}
				>
					<div className="mb-3 flex flex-wrap items-center gap-1.5">
						{(
							["FAILED_OR_ERROR", "RUNNING", "WAITING", "ALL"] as QueueFilter[]
						).map((option) => (
							<button
								key={option}
								type="button"
								onClick={() => setQueueFilter(option)}
								className={`rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${
									queueFilter === option
										? "border-blue-400/60 bg-blue-500/10 text-blue-200"
										: "border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200"
								}`}
							>
								{option === "FAILED_OR_ERROR" ? "Failed / Error" : option}
							</button>
						))}
					</div>
					<DataTable<TelemetryRequest>
						rows={queueItems}
						columns={columns}
						getRowId={(t) => t.request_id}
						onRowClick={(t) => setSelectedRequestId(t.request_id)}
						selectedRowId={selectedRequestId}
						searchText={(t) =>
							`${getTelemetryRequestLabel(t)} ${getTelemetryModeLabel(t)} ${getTelemetryPrimaryRemark(t)}`
						}
						searchPlaceholder="Search incidents…"
						filters={[modeFilterDef]}
						pageSize={12}
						initialSort={{ key: "updated", dir: "desc" }}
						emptyLabel="No incidents match the current filters."
					/>
				</Section>

				<Section
					title="AI incident brief"
					helper="Exact failure context — copy or export to send to AI without piecing together timestamps and stages."
					action={
						<div className="flex gap-2">
							<button type="button" onClick={handleCopy} className={BTN}>
								<Copy size={12} className="mr-1" />{" "}
								{copied ? "Copied" : "Copy brief"}
							</button>
							<button
								type="button"
								onClick={handleExportBrief}
								className={BTN}
								disabled={!selectedTrace}
							>
								Export brief
							</button>
						</div>
					}
				>
					{!selectedTrace ? (
						<div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-6 text-center text-sm text-slate-400">
							Select an incident from the queue to build an AI-ready brief.
						</div>
					) : (
						<div className="space-y-4">
							<div className="flex flex-wrap items-start justify-between gap-3">
								<div>
									<div className="text-lg font-semibold text-slate-100">
										{getTelemetryRequestLabel(selectedTrace)}
									</div>
									<div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
										<span className="uppercase tracking-[0.14em]">
											{getTelemetryModeLabel(selectedTrace)}
										</span>
										<Badge tone={toneFor(selectedTrace.status)}>
											{getTelemetryStatusLabel(selectedTrace.status)}
										</Badge>
									</div>
								</div>
								<button
									type="button"
									onClick={() => setSelectedRequestId(selectedTrace.request_id)}
									className={BTN}
								>
									<RefreshCcw size={12} className="mr-1" /> Refresh
								</button>
							</div>

							<div className="grid gap-3 md:grid-cols-2">
								<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm text-slate-200">
									<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
										Primary remark
									</div>
									<div className="mt-2">
										{getTelemetryPrimaryRemark(selectedTrace, detail)}
									</div>
								</div>
								<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-3 text-sm text-slate-200">
									<div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
										Last known stage
									</div>
									<div className="mt-2">{getTelemetryStage(selectedTrace)}</div>
									<div className="mt-2 text-xs text-slate-500">
										{formatKualaLumpurDateTime(getTelemetryUpdatedAt(selectedTrace))}
									</div>
								</div>
							</div>

							{detailError ? (
								<div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
									{detailError}
								</div>
							) : detail?.stages?.length ? (
								<div className="grid gap-2">
									{detail.stages.map((stage) => (
										<div
											key={stage.id}
											className="rounded-xl border border-slate-800 bg-slate-900/50 p-3"
										>
											<div className="flex items-start justify-between gap-3">
												<div>
													<div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-200">
														{stage.stage}
													</div>
													<div className="mt-1 text-[11px] text-slate-500">
														{stage.source} •{" "}
														{formatKualaLumpurDateTime(stage.timestamp)}
													</div>
												</div>
												<Badge tone={stage.status === "FAILED" ? "danger" : "neutral"}>
													{stage.status}
												</Badge>
											</div>
											<div className="mt-2 text-xs text-slate-300">
												{stage.message || "No stage note recorded."}
											</div>
										</div>
									))}
								</div>
							) : null}

							<details className="rounded-xl border border-slate-800 bg-slate-950/40 p-3 text-xs">
								<summary className="cursor-pointer select-none font-semibold text-slate-300">
									Technical detail — IDs &amp; raw brief
								</summary>
								<dl className="mt-3 grid gap-1 text-[11px] text-slate-400 sm:grid-cols-2">
									<div>
										<dt className="inline text-slate-500">Request ID: </dt>
										<dd className="inline font-mono">{selectedTrace.request_id}</dd>
									</div>
									<div>
										<dt className="inline text-slate-500">Project ID: </dt>
										<dd className="inline font-mono">
											{selectedTrace.project_id || "N/A"}
										</dd>
									</div>
									<div>
										<dt className="inline text-slate-500">Video ID: </dt>
										<dd className="inline font-mono">
											{selectedTrace.video_id || "N/A"}
										</dd>
									</div>
									<div>
										<dt className="inline text-slate-500">Scene ID: </dt>
										<dd className="inline font-mono">
											{selectedTrace.scene_id || "N/A"}
										</dd>
									</div>
								</dl>
								<textarea
									readOnly
									title="AI incident brief"
									value={incidentBrief}
									className="mt-3 min-h-[220px] w-full rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-[11px] leading-6 text-slate-300 outline-none"
								/>
							</details>
						</div>
					)}
				</Section>
			</div>
		</div>
	);
}
