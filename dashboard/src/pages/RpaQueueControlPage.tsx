/**
 * RPA Queue Control — Round E user-facing panel.
 *
 * Round D-API proved the prepare chain end to end, but only from a script:
 *   WEP -> from-execution-package -> WGP -> approve -> enqueue -> DRY RUN -> report
 * No UI ever exposed the WEP -> WGP bridge, so a user could not reach a queue-ready
 * package from the screen. This page is that missing surface.
 *
 * Boundary (G0 §16, Round E): this page NEVER starts a live run. `startProductionRun`
 * is called with confirmLiveCreditBurn=false and nothing on this page can pass true —
 * live generation is rendered as LOCKED and gated to Round F. The existing
 * /production-queue page keeps its own operator controls; this page does not replace it.
 *
 * Every control carries a data-testid so an RPA operator can drive it (G0 blocker B8
 * recorded that the queue surface had none).
 */
import {
	AlertTriangle,
	CheckCircle2,
	ChevronRight,
	Lock,
	Loader2,
	PackageCheck,
	Play,
	RefreshCw,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
	approvePackages,
	createProductionRun,
	getProductionRun,
	startProductionRun,
} from "../api/productionQueue";
import { createFromExecutionPackage } from "../api/workspaceGenerationPackages";
import { fetchWorkspaceExecutionPackageHistory } from "../api/workspacePackages";
import type { WorkspaceExecutionPackage } from "../types";

/** The model the queue requires; unknown models FAIL CLOSED server-side. */
const DRY_RUN_MODEL = "Veo 3.1 - Lite";

interface DryRunItem {
	package_id?: string;
	ok?: boolean;
	blockers?: string[];
	reason?: string;
	error?: string;
	model?: string;
	duration_s?: number;
}
interface DryRunReport {
	checked?: number;
	ready?: number;
	blocked?: number;
	items?: DryRunItem[];
	note?: string;
}

type Stage = "IDLE" | "BRIDGED" | "APPROVED" | "ENQUEUED" | "DRY_RUN_DONE";

export default function RpaQueueControlPage() {
	const [weps, setWeps] = useState<WorkspaceExecutionPackage[]>([]);
	const [loading, setLoading] = useState(true);
	const [apiDown, setApiDown] = useState(false);
	const [busy, setBusy] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);

	const [selectedWep, setSelectedWep] = useState<WorkspaceExecutionPackage | null>(null);
	const [wgpId, setWgpId] = useState<string | null>(null);
	const [wgpStatus, setWgpStatus] = useState<string | null>(null);
	const [productionStatus, setProductionStatus] = useState<string | null>(null);
	const [runId, setRunId] = useState<string | null>(null);
	const [runDryRun, setRunDryRun] = useState<number | null>(null);
	const [runStatus, setRunStatus] = useState<string | null>(null);
	const [report, setReport] = useState<DryRunReport | null>(null);
	const [stage, setStage] = useState<Stage>("IDLE");

	const loadWeps = useCallback(async () => {
		setLoading(true);
		setApiDown(false);
		try {
			const rows = await fetchWorkspaceExecutionPackageHistory(undefined, undefined, 20);
			setWeps(Array.isArray(rows) ? rows : []);
		} catch {
			setApiDown(true);
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void loadWeps();
	}, [loadWeps]);

	const reset = (wep: WorkspaceExecutionPackage) => {
		setSelectedWep(wep);
		setWgpId(null);
		setWgpStatus(null);
		setProductionStatus(null);
		setRunId(null);
		setRunDryRun(null);
		setRunStatus(null);
		setReport(null);
		setStage("IDLE");
		setError(null);
	};

	/** Step 1 — bridge the execution package into the queue's unit of work. */
	const handleBridge = async () => {
		if (!selectedWep) return;
		setBusy("bridge");
		setError(null);
		try {
			const mode = selectedWep.mode === "I2V" ? "I2V" : "F2V";
			const wgp = await createFromExecutionPackage(
				selectedWep.workspace_execution_package_id,
				mode,
			);
			setWgpId(wgp.workspace_generation_package_id);
			setWgpStatus(wgp.status ?? null);
			setProductionStatus(wgp.production_status ?? "NONE");
			setStage("BRIDGED");
		} catch (e) {
			setError(`Bridge failed: ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			setBusy(null);
		}
	};

	/** Step 2 — prompt-side approval. No execution. */
	const handleApprove = async () => {
		if (!wgpId) return;
		setBusy("approve");
		setError(null);
		try {
			const res = await approvePackages([wgpId]);
			const row = res.results?.[0];
			if (!row?.ok) {
				setError(`Approve refused: ${row?.error ?? "unknown"}`);
				return;
			}
			setProductionStatus("APPROVED");
			setStage("APPROVED");
		} catch (e) {
			setError(`Approve failed: ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			setBusy(null);
		}
	};

	/** Step 3 — enqueue. The run is always born dry_run=1; nothing fires here. */
	const handleEnqueue = async () => {
		if (!wgpId) return;
		setBusy("enqueue");
		setError(null);
		try {
			const run = await createProductionRun({
				package_ids: [wgpId],
				model: DRY_RUN_MODEL,
				aspect: "9:16",
				count: 1,
			});
			setRunId(run.production_run_id);
			setRunDryRun(Number(run.dry_run));
			setRunStatus(run.status ?? null);
			setProductionStatus("QUEUED");
			setStage("ENQUEUED");
		} catch (e) {
			setError(`Enqueue failed: ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			setBusy(null);
		}
	};

	/**
	 * Step 4 — DRY RUN ONLY. confirmLiveCreditBurn is hard-coded false here; there is no
	 * code path on this page that can pass true, so no credit can burn from Round E.
	 */
	const handleDryRun = async () => {
		if (!runId) return;
		setBusy("dryrun");
		setError(null);
		try {
			const res = await startProductionRun(runId, false);
			setReport((res as unknown as { report?: DryRunReport }).report ?? null);
			setStage("DRY_RUN_DONE");
			await handleRefreshReport(runId);
		} catch (e) {
			setError(`Dry run failed: ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			setBusy(null);
		}
	};

	/** Re-read the persisted run + last_dry_run_report. */
	const handleRefreshReport = async (id?: string) => {
		const target = id ?? runId;
		if (!target) return;
		setBusy("refresh");
		try {
			const detail = await getProductionRun(target);
			const run = (detail as unknown as { run?: Record<string, unknown> }).run ?? detail;
			setRunDryRun(Number((run as Record<string, unknown>).dry_run));
			setRunStatus(String((run as Record<string, unknown>).status ?? ""));
			let cfg = (run as Record<string, unknown>).config_json as unknown;
			if (typeof cfg === "string") {
				try {
					cfg = JSON.parse(cfg);
				} catch {
					cfg = {};
				}
			}
			const persisted = (cfg as { last_dry_run_report?: DryRunReport })?.last_dry_run_report;
			if (persisted) setReport(persisted);
		} catch (e) {
			setError(`Refresh failed: ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			setBusy(null);
		}
	};

	const chip = (label: string, value: string | null, testid: string) => (
		<div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2" data-testid={testid}>
			<div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
			<div className="font-mono text-[11px] text-slate-200 break-all">{value ?? "—"}</div>
		</div>
	);

	return (
		<div className="p-6" data-testid="rpa-queue-control" data-stage={stage}>
			<div className="mb-6">
				<h1 className="text-xl font-bold text-slate-100">RPA Queue Control</h1>
				<p className="mt-1 text-xs text-slate-400">
					Prepare an execution package into a queue-ready item and validate it with a{" "}
					<strong className="text-slate-200">dry run</strong>. No provider is called and no
					credits are spent on this page.
				</p>
			</div>

			{/* Live lock — Round F gate. Rendered, never clickable. */}
			<div
				className="mb-6 flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3"
				data-testid="live-generation-locked"
				data-locked="true"
			>
				<Lock size={16} className="text-amber-300 shrink-0" />
				<div className="text-[11px] text-amber-100">
					<strong>Live generation is locked.</strong> Round E is dry-run only — this panel
					never starts a live run and cannot burn credits. Live execution is gated to Round F
					and requires explicit owner authorization.
				</div>
			</div>

			{error && (
				<div
					className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200"
					data-testid="rpa-queue-error"
				>
					<AlertTriangle size={14} className="mt-0.5 shrink-0" />
					<span>{error}</span>
				</div>
			)}

			{/* ── Package picker ── */}
			<section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
				<div className="mb-3 flex items-center justify-between">
					<h2 className="text-sm font-semibold text-slate-200">1 · Choose an execution package</h2>
					<button
						type="button"
						data-testid="action-refresh-packages"
						onClick={() => void loadWeps()}
						disabled={loading}
						className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] text-slate-300 hover:bg-slate-800 disabled:opacity-40"
					>
						<RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh
					</button>
				</div>

				{apiDown && (
					<div className="text-[11px] text-red-300" data-testid="rpa-queue-api-unavailable">
						API unavailable — could not load execution packages.
					</div>
				)}
				{!apiDown && loading && (
					<div className="text-[11px] text-slate-500" data-testid="rpa-queue-loading">
						Loading…
					</div>
				)}
				{!apiDown && !loading && weps.length === 0 && (
					<div className="text-[11px] text-slate-500" data-testid="rpa-queue-empty">
						No execution packages yet. Generate a Final Prompt (Step 4) on the Operator page first.
					</div>
				)}

				<div className="space-y-1.5">
					{weps.map((w) => (
						<button
							type="button"
							key={w.workspace_execution_package_id}
							data-testid="wep-option"
							data-wep-id={w.workspace_execution_package_id}
							data-selected={
								selectedWep?.workspace_execution_package_id === w.workspace_execution_package_id
									? "true"
									: "false"
							}
							onClick={() => reset(w)}
							className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors ${
								selectedWep?.workspace_execution_package_id === w.workspace_execution_package_id
									? "border-blue-500/60 bg-blue-500/10"
									: "border-slate-800 hover:bg-slate-800/50"
							}`}
						>
							<span className="min-w-0">
								<span className="block truncate text-[11px] text-slate-200">
									{w.product_name ?? w.product_id}
								</span>
								<span className="block font-mono text-[10px] text-slate-500">
									{w.workspace_execution_package_id} · {w.mode}
								</span>
							</span>
							<ChevronRight size={14} className="shrink-0 text-slate-600" />
						</button>
					))}
				</div>
			</section>

			{/* ── Prepare chain ── */}
			<section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4" data-testid="rpa-prepare-panel">
				<h2 className="mb-3 text-sm font-semibold text-slate-200">2 · Prepare and dry-run</h2>

				<div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-3">
					{chip("WEP id", selectedWep?.workspace_execution_package_id ?? null, "status-wep-id")}
					{chip("Mode", selectedWep?.mode ?? null, "status-mode")}
					{chip("WGP id", wgpId, "status-wgp-id")}
					{chip("WGP status", wgpStatus, "status-wgp-status")}
					{chip("Production status", productionStatus, "status-production-status")}
					{chip("Run id", runId, "status-run-id")}
				</div>

				<div className="flex flex-wrap gap-2">
					<button
						type="button"
						data-testid="action-bridge-wep-to-wgp"
						onClick={() => void handleBridge()}
						disabled={!selectedWep || busy !== null || stage !== "IDLE"}
						className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/50 bg-blue-500/15 px-3 py-2 text-[11px] font-semibold text-blue-100 hover:bg-blue-500/25 disabled:cursor-not-allowed disabled:opacity-40"
					>
						{busy === "bridge" ? <Loader2 size={12} className="animate-spin" /> : <PackageCheck size={12} />}
						Prepare Package (bridge WEP → WGP)
					</button>

					<button
						type="button"
						data-testid="action-approve-package"
						onClick={() => void handleApprove()}
						disabled={!wgpId || busy !== null || stage !== "BRIDGED"}
						className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-[11px] font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
					>
						{busy === "approve" ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
						Approve Package for Queue
					</button>

					<button
						type="button"
						data-testid="action-enqueue-dry-run"
						onClick={() => void handleEnqueue()}
						disabled={!wgpId || busy !== null || stage !== "APPROVED"}
						className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-[11px] font-semibold text-slate-200 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
					>
						{busy === "enqueue" ? <Loader2 size={12} className="animate-spin" /> : <PackageCheck size={12} />}
						Enqueue Dry Run
					</button>

					<button
						type="button"
						data-testid="action-run-dry-run"
						onClick={() => void handleDryRun()}
						disabled={!runId || busy !== null || stage !== "ENQUEUED"}
						className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/50 bg-emerald-500/15 px-3 py-2 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40"
					>
						{busy === "dryrun" ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
						Run Dry Run (no credits)
					</button>

					<button
						type="button"
						data-testid="action-refresh-report"
						onClick={() => void handleRefreshReport()}
						disabled={!runId || busy !== null}
						className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-2 text-[11px] text-slate-300 hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
					>
						<RefreshCw size={12} className={busy === "refresh" ? "animate-spin" : ""} /> Refresh Report
					</button>
				</div>
			</section>

			{/* ── Dry-run report ── */}
			<section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4" data-testid="dry-run-report-panel">
				<h2 className="mb-3 text-sm font-semibold text-slate-200">3 · Dry-run report</h2>

				{!report && (
					<div className="text-[11px] text-slate-500" data-testid="dry-run-report-empty">
						No dry-run report yet. Prepare a package and run a dry run to see readiness.
					</div>
				)}

				{report && (
					<div data-testid="dry-run-report" data-dry-run={String(runDryRun ?? "")} data-run-status={runStatus ?? ""}>
						<div className="mb-3 flex flex-wrap gap-2">
							{chip("Checked", String(report.checked ?? 0), "report-checked")}
							{chip("Ready", String(report.ready ?? 0), "report-ready")}
							{chip("Blocked", String(report.blocked ?? 0), "report-blocked")}
							{chip("dry_run", String(runDryRun ?? ""), "report-dry-run-flag")}
							{chip("Run status", runStatus, "report-run-status")}
						</div>

						<div
							className="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-200"
							data-testid="report-no-credit-notice"
						>
							No provider call · No credit burn — {report.note ?? "dry run only"}
						</div>

						<div className="space-y-1.5">
							{(report.items ?? []).map((item, i) => {
								const blocked = item.ok === false;
								return (
									<div
										key={item.package_id ?? i}
										data-testid="dry-run-item"
										data-package-id={item.package_id ?? ""}
										data-blocked={blocked ? "true" : "false"}
										className={`rounded-lg border px-3 py-2 ${blocked ? "border-red-500/40 bg-red-500/5" : "border-emerald-500/40 bg-emerald-500/5"}`}
									>
										<div className="flex items-center gap-2 font-mono text-[11px]">
											<span className={blocked ? "text-red-300" : "text-emerald-300"}>
												{blocked ? "✗" : "✓"}
											</span>
											<span className="text-slate-300">{item.package_id}</span>
											{item.model && <span className="text-slate-500">· {item.model}</span>}
										</div>
										{blocked && (
											<ul className="mt-1 pl-6" data-testid="dry-run-item-blockers">
												{(item.blockers ?? [String(item.reason ?? item.error ?? "blocked")]).map(
													(b) => (
														<li
															key={b}
															data-testid="dry-run-blocker"
															data-blocker-code={b}
															className="list-disc text-[11px] text-red-300"
														>
															{b}
														</li>
													),
												)}
											</ul>
										)}
									</div>
								);
							})}
						</div>
					</div>
				)}
			</section>
		</div>
	);
}
