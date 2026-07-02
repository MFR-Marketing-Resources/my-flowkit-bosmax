import {
	AlertTriangle,
	ChevronDown,
	ChevronRight,
	Flame,
	Pause,
	RefreshCw,
	RotateCcw,
	ShieldCheck,
	XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type {
	ProductionDryRunReport,
	ProductionRun,
	ProductionRunDetail,
} from "../api/productionQueue";
import {
	cancelProductionRun,
	getProductionRun,
	listProductionRuns,
	pauseProductionRun,
	retryProductionRun,
	startProductionRun,
} from "../api/productionQueue";

// PRODUCTION QUEUE — the ONLY place where approved prompt packages are
// executed against Google Flow. Fail-closed: every run starts as a
// dry-run validation; live execution burns Google Flow credits and
// requires an explicit confirmation checkbox.

const RUN_STATUS_COLORS: Record<string, string> = {
	PENDING: "border-slate-700 bg-slate-800 text-slate-400",
	QUEUED: "border-blue-500/40 bg-blue-500/15 text-blue-300",
	RUNNING: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
	PAUSED: "border-amber-500/40 bg-amber-500/15 text-amber-300",
	COMPLETED: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
	FAILED: "border-red-500/40 bg-red-500/15 text-red-300",
	CANCELLED: "border-slate-600 bg-slate-800 text-slate-400",
};

const ITEM_STATUS_COLORS: Record<string, string> = {
	APPROVED: "border-blue-500/40 bg-blue-500/15 text-blue-300",
	QUEUED: "border-indigo-500/40 bg-indigo-500/15 text-indigo-300",
	RUNNING: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
	GENERATED: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
	DOWNLOADED: "border-cyan-500/40 bg-cyan-500/15 text-cyan-300",
	FAILED: "border-red-500/40 bg-red-500/15 text-red-300",
	CANCELLED: "border-slate-600 bg-slate-800 text-slate-400",
};

function RunStatusBadge({
	status,
	colors,
}: {
	status: string;
	colors: Record<string, string>;
}) {
	return (
		<span
			className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-widest whitespace-nowrap ${colors[status] ?? "border-slate-700 bg-slate-800 text-slate-400"}`}
		>
			{status}
		</span>
	);
}

// Resolve the run's engine model ui_label — prefer the flat `model`
// field, then fall back to parsing the run's config_json string.
function getRunModel(run: ProductionRun): string | null {
	if (typeof run.model === "string" && run.model) return run.model;
	const raw = run.config_json;
	if (typeof raw !== "string" || !raw) return null;
	try {
		const parsed = JSON.parse(raw) as { model?: unknown };
		return typeof parsed.model === "string" && parsed.model
			? parsed.model
			: null;
	} catch {
		return null;
	}
}

const LOGICAL_MODE_COLORS: Record<string, string> = {
	T2V: "border-blue-500/40 bg-blue-500/10 text-blue-300",
	HYBRID: "border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
	F2V: "border-purple-500/40 bg-purple-500/10 text-purple-300",
	I2V: "border-amber-500/40 bg-amber-500/10 text-amber-300",
};

export default function ProductionQueuePage() {
	const [runs, setRuns] = useState<ProductionRun[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
	const [detail, setDetail] = useState<ProductionRunDetail | null>(null);
	const [detailLoading, setDetailLoading] = useState(false);
	const [dryRunReports, setDryRunReports] = useState<
		Record<string, ProductionDryRunReport>
	>({});
	const [confirmLive, setConfirmLive] = useState<Record<string, boolean>>({});
	const [actionBusy, setActionBusy] = useState<string | null>(null);

	const loadRuns = useCallback(async () => {
		try {
			const resp = await listProductionRuns();
			setRuns(resp.runs ?? []);
			setError(null);
		} catch (e) {
			setError(String(e));
		} finally {
			setLoading(false);
		}
	}, []);

	const loadDetail = useCallback(async (runId: string) => {
		try {
			const full = await getProductionRun(runId);
			setDetail(full);
		} catch (e) {
			setError(String(e));
		} finally {
			setDetailLoading(false);
		}
	}, []);

	useEffect(() => {
		void loadRuns();
	}, [loadRuns]);

	// Poll every 3s while any run is RUNNING
	const anyRunning = runs.some((r) => r.status === "RUNNING");
	useEffect(() => {
		if (!anyRunning) return;
		const timer = window.setInterval(() => {
			void loadRuns();
			if (selectedRunId) void loadDetail(selectedRunId);
		}, 3000);
		return () => window.clearInterval(timer);
	}, [anyRunning, loadRuns, loadDetail, selectedRunId]);

	const handleSelect = useCallback(
		(run: ProductionRun) => {
			if (selectedRunId === run.production_run_id) {
				setSelectedRunId(null);
				setDetail(null);
				return;
			}
			setSelectedRunId(run.production_run_id);
			setDetail(null);
			setDetailLoading(true);
			void loadDetail(run.production_run_id);
		},
		[selectedRunId, loadDetail],
	);

	const refreshAfterAction = useCallback(
		async (runId: string) => {
			await loadRuns();
			if (selectedRunId === runId) {
				await loadDetail(runId);
			}
		},
		[loadRuns, loadDetail, selectedRunId],
	);

	const handleDryRunValidate = async (runId: string) => {
		setActionBusy(runId);
		setError(null);
		try {
			const resp = await startProductionRun(runId, false);
			if (resp.report) {
				setDryRunReports((prev) => ({ ...prev, [runId]: resp.report as ProductionDryRunReport }));
			}
			await refreshAfterAction(runId);
		} catch (e) {
			setError(String(e));
		} finally {
			setActionBusy(null);
		}
	};

	const handleRunLive = async (runId: string) => {
		if (!confirmLive[runId]) return;
		setActionBusy(runId);
		setError(null);
		try {
			await startProductionRun(runId, true);
			setConfirmLive((prev) => ({ ...prev, [runId]: false }));
			await refreshAfterAction(runId);
		} catch (e) {
			setError(String(e));
		} finally {
			setActionBusy(null);
		}
	};

	const handleRunAction = async (
		runId: string,
		action: (id: string) => Promise<ProductionRun>,
	) => {
		setActionBusy(runId);
		setError(null);
		try {
			await action(runId);
			await refreshAfterAction(runId);
		} catch (e) {
			setError(String(e));
		} finally {
			setActionBusy(null);
		}
	};

	const renderControls = (run: ProductionRun) => {
		const runId = run.production_run_id;
		const busy = actionBusy === runId;
		return (
			<div className="space-y-3">
				<div className="flex flex-wrap items-center gap-2">
					<button
						type="button"
						disabled={busy}
						onClick={() => void handleDryRunValidate(runId)}
						className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-[11px] font-semibold text-blue-200 hover:bg-blue-500/20 transition-colors disabled:opacity-40"
					>
						<ShieldCheck size={12} />
						Dry-Run Validate (no credits)
					</button>
					{run.status === "RUNNING" && (
						<button
							type="button"
							disabled={busy}
							onClick={() => void handleRunAction(runId, pauseProductionRun)}
							className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] font-semibold text-amber-200 hover:bg-amber-500/20 transition-colors disabled:opacity-40"
						>
							<Pause size={12} />
							Pause
						</button>
					)}
					<button
						type="button"
						disabled={busy}
						onClick={() => void handleRunAction(runId, cancelProductionRun)}
						className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-[11px] font-semibold text-red-200 hover:bg-red-500/20 transition-colors disabled:opacity-40"
					>
						<XCircle size={12} />
						Cancel
					</button>
					<button
						type="button"
						disabled={busy}
						onClick={() => void handleRunAction(runId, retryProductionRun)}
						className="inline-flex items-center gap-1.5 rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 text-[11px] font-semibold text-slate-300 hover:bg-slate-700 transition-colors disabled:opacity-40"
					>
						<RotateCcw size={12} />
						Retry Failed
					</button>
				</div>

				<div className="rounded-xl border border-red-500/30 bg-red-500/5 p-3 space-y-2">
					<label className="flex items-center gap-2 cursor-pointer">
						<input
							type="checkbox"
							checked={Boolean(confirmLive[runId])}
							onChange={(e) =>
								setConfirmLive((prev) => ({
									...prev,
									[runId]: e.target.checked,
								}))
							}
							className="accent-red-500"
						/>
						<span className="text-xs text-red-200">
							I confirm live credit burn
						</span>
					</label>
					<button
						type="button"
						disabled={busy || !confirmLive[runId]}
						onClick={() => void handleRunLive(runId)}
						className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/50 bg-red-500/20 px-4 py-2 text-[11px] font-bold text-red-100 hover:bg-red-500/30 transition-colors disabled:cursor-not-allowed disabled:opacity-40"
					>
						<Flame size={12} />
						Run LIVE (burns credits)
					</button>
				</div>
			</div>
		);
	};

	const report = selectedRunId ? dryRunReports[selectedRunId] : undefined;

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
			{/* Header */}
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="flex items-center justify-between gap-3">
					<div>
						<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
							Production Queue
						</div>
						<div className="mt-1 text-xs text-slate-400">
							Fail-closed execution of approved prompt packages. Every run
							defaults to a dry-run validation — live execution burns Google
							Flow credits and requires the explicit confirmation checkbox.
						</div>
					</div>
					<button
						type="button"
						onClick={() => void loadRuns()}
						className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200 transition-colors"
					>
						<RefreshCw size={13} />
						Refresh
					</button>
				</div>
				{error && (
					<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						{error}
					</div>
				)}
			</section>

			{/* Runs table */}
			<section className="rounded-2xl border border-slate-800 bg-slate-950/80 overflow-hidden">
				{loading ? (
					<div className="py-12 text-center text-sm text-slate-500">
						Loading production runs…
					</div>
				) : runs.length === 0 ? (
					<div className="py-12 text-center text-sm text-slate-500">
						No production runs yet. Approve packages in the Prompt Handoff Bank
						and send them to production.
					</div>
				) : (
					<div className="overflow-x-auto">
						<table className="w-full">
							<thead className="border-b border-slate-800">
								<tr className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
									<th className="py-3 px-2 w-6"></th>
									<th className="py-3 px-3 text-left">Run ID</th>
									<th className="py-3 px-3 text-left">Status</th>
									<th className="py-3 px-3 text-left">Dry Run</th>
									<th className="py-3 px-3 text-left">Progress</th>
									<th className="py-3 px-3 text-left">Interval</th>
									<th className="py-3 px-3 text-left">Cooldown</th>
									<th className="py-3 px-3 text-left">Created</th>
								</tr>
							</thead>
							<tbody>
								{runs.map((run) => {
									const isSelected = selectedRunId === run.production_run_id;
									return (
										<tr
											key={run.production_run_id}
											onClick={() => handleSelect(run)}
											className={`cursor-pointer border-b border-slate-800 transition-colors ${isSelected ? "bg-blue-500/8" : "hover:bg-slate-800/50"}`}
										>
											<td className="py-2 px-2">
												{isSelected ? (
													<ChevronDown size={14} className="text-blue-400" />
												) : (
													<ChevronRight size={14} className="text-slate-500" />
												)}
											</td>
											<td className="py-2 px-3 font-mono text-xs text-slate-400 max-w-[180px] truncate">
												{run.production_run_id}
											</td>
											<td className="py-2 px-3">
												<RunStatusBadge
													status={run.status}
													colors={RUN_STATUS_COLORS}
												/>
											</td>
											<td className="py-2 px-3 text-xs">
												{run.dry_run ? (
													<span className="text-blue-300 font-semibold">
														DRY
													</span>
												) : (
													<span className="text-red-300 font-semibold">
														LIVE
													</span>
												)}
											</td>
											<td className="py-2 px-3 text-xs text-slate-300">
												{run.total_completed ?? 0} done ·{" "}
												{run.total_failed ?? 0} failed / {run.total_expected}
											</td>
											<td className="py-2 px-3 text-xs text-slate-400">
												{run.interval_min_seconds ?? "—"}–
												{run.interval_max_seconds ?? "—"}s
											</td>
											<td className="py-2 px-3 text-xs text-slate-400">
												every {run.cooldown_after_n_jobs ?? "—"} jobs ·{" "}
												{run.cooldown_seconds ?? "—"}s
											</td>
											<td className="py-2 px-3 text-xs text-slate-500">
												{run.created_at?.slice(0, 16).replace("T", " ") ?? "—"}
											</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					</div>
				)}
			</section>

			{/* Run detail */}
			{selectedRunId && (
				<section className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 space-y-4">
					<div className="flex items-center justify-between gap-3">
						<div>
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500 mb-1">
								Selected Run
							</div>
							<div className="text-sm font-bold text-slate-100 font-mono">
								{selectedRunId}
							</div>
							{detail && (
								<div className="mt-1 text-xs text-slate-400">
									Model:{" "}
									<span className="font-mono text-slate-200">
										{getRunModel(detail) ?? "—"}
									</span>
								</div>
							)}
						</div>
						{detail && (
							<RunStatusBadge
								status={detail.status}
								colors={RUN_STATUS_COLORS}
							/>
						)}
					</div>

					{detail && renderControls(detail)}

					{/* Dry-run report */}
					{report && (
						<div className="rounded-xl border border-blue-500/30 bg-blue-500/5 p-3 space-y-2">
							<div className="flex items-center gap-2">
								<ShieldCheck size={13} className="text-blue-300" />
								<span className="text-xs font-bold text-blue-200 uppercase tracking-widest">
									Dry-Run Report — {report.ready} ready · {report.blocked}{" "}
									blocked · {report.checked} checked
								</span>
							</div>
							{report.note && (
								<div className="text-[11px] text-blue-200/80">
									{report.note}
								</div>
							)}
							<ul className="space-y-1">
								{report.items.map((item, i) => {
									const blocked = item.blocked === true || item.ready === false;
									return (
										<li
											key={item.package_id ?? i}
											className={`text-[11px] font-mono flex items-start gap-2 ${blocked ? "text-red-300" : "text-emerald-300"}`}
										>
											<span>{blocked ? "✗" : "✓"}</span>
											<span className="min-w-0">
												{item.package_id ?? `item ${i + 1}`}
												{item.model != null && (
													<span className="text-slate-400">
														{" "}
														· model={String(item.model)}
													</span>
												)}
												{item.duration_s != null && (
													<span className="text-slate-400">
														{" "}
														· duration_s={String(item.duration_s)}
													</span>
												)}
												{blocked && (
													<span className="text-red-200/80">
														{" "}
														— {String(item.reason ?? item.error ?? "blocked")}
													</span>
												)}
											</span>
										</li>
									);
								})}
							</ul>
						</div>
					)}

					{/* Items table */}
					{detailLoading ? (
						<div className="py-8 text-center text-sm text-slate-500">
							Loading run items…
						</div>
					) : detail ? (
						<div className="overflow-x-auto rounded-xl border border-slate-800">
							<table className="w-full">
								<thead className="border-b border-slate-800 bg-slate-950/60">
									<tr className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
										<th className="py-2.5 px-3 text-left">Package</th>
										<th className="py-2.5 px-3 text-left">Product</th>
										<th className="py-2.5 px-3 text-left">Mode</th>
										<th className="py-2.5 px-3 text-left">Status</th>
										<th className="py-2.5 px-3 text-left">Error</th>
										<th className="py-2.5 px-3 text-left">Artifacts</th>
									</tr>
								</thead>
								<tbody>
									{(detail.items ?? []).map((item) => (
										<tr
											key={item.package_id}
											className="border-b border-slate-800 last:border-0"
										>
											<td className="py-2 px-3 font-mono text-xs text-slate-400 max-w-[160px] truncate">
												{item.package_id}
											</td>
											<td className="py-2 px-3 text-xs text-slate-300 max-w-[140px] truncate">
												{item.product_name_snapshot || item.product_id}
											</td>
											<td className="py-2 px-3">
												<span
													className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-widest ${LOGICAL_MODE_COLORS[item.logical_mode] ?? "border-slate-700 bg-slate-800 text-slate-400"}`}
												>
													{item.logical_mode}
												</span>
											</td>
											<td className="py-2 px-3">
												<RunStatusBadge
													status={item.production_status}
													colors={ITEM_STATUS_COLORS}
												/>
											</td>
											<td className="py-2 px-3 text-[11px] text-red-300 max-w-[220px] truncate">
												{item.production_error || "—"}
											</td>
											<td className="py-2 px-3 font-mono text-[10px] text-slate-500 max-w-[180px] truncate">
												{(item.artifact_media_ids ?? []).length > 0
													? item.artifact_media_ids.join(", ")
													: "—"}
											</td>
										</tr>
									))}
								</tbody>
							</table>
							{(detail.items ?? []).length === 0 && (
								<div className="py-8 text-center text-sm text-slate-500">
									No items in this run.
								</div>
							)}
						</div>
					) : null}

					<div className="flex items-center gap-2 text-[11px] text-slate-500">
						<AlertTriangle size={12} className="text-amber-400" />
						Dry-run is the default. Live execution spends real Google Flow
						credits — validate first.
					</div>
				</section>
			)}
		</div>
	);
}
