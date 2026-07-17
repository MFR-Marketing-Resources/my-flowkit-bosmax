/**
 * RPA Queue Control — Round E prepare/dry-run panel + Round F one-serial T2V live gate.
 *
 * Round D-API proved the prepare chain end to end, but only from a script:
 *   WEP -> from-execution-package -> WGP -> approve -> enqueue -> DRY RUN -> report
 * No UI ever exposed the WEP -> WGP bridge, so a user could not reach a queue-ready
 * package from the screen. This page is that missing surface.
 *
 * Round F adds exactly ONE live door, and only for T2V:
 *   - T2V is the only mode with no media prerequisite, so it is the only mode that can
 *     reach ready=1 without a Flow upload (the bridge also REJECTS T2V, hence the
 *     dedicated /generation-packages/t2v route).
 *   - The live button needs mode=T2V AND exactly one queued item AND a dry run with
 *     ready=1/blocked=0 AND the exact confirmation phrase AND no prior job id.
 *   - The same conditions are re-checked SERVER-side (live_gate=ONE_SERIAL_T2V); the UI
 *     gate is convenience, the server gate is the control.
 *   - BULK live remains locked and is not reachable from this page.
 *
 * Every control carries a data-testid so an RPA operator can drive it (G0 blocker B8
 * recorded that the queue surface had none).
 */
import {
	AlertTriangle,
	CheckCircle2,
	ChevronRight,
	Flame,
	Lock,
	Loader2,
	PackageCheck,
	Play,
	RefreshCw,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
	approvePackages,
	createProductionRun,
	getProductionRun,
	LIVE_CONFIRM_PHRASE,
	LIVE_GATE_ONE_SERIAL_T2V,
	startProductionRun,
} from "../api/productionQueue";
import {
	createFromExecutionPackage,
	createT2VGenerationPackage,
} from "../api/workspaceGenerationPackages";
import { fetchWorkspaceExecutionPackageHistory } from "../api/workspacePackages";
import type { WorkspaceExecutionPackage } from "../types";

/** The model the queue requires; unknown models FAIL CLOSED server-side. */
const DRY_RUN_MODEL = "Veo 3.1 - Lite";

/** Item states from which no further provider submission will happen. */
const TERMINAL_STATUSES = new Set(["GENERATED", "DOWNLOADED", "FAILED", "CANCELLED"]);
const POLL_MS = 5000;

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

interface RunItem {
	package_id?: string;
	production_status?: string;
	production_job_id?: string | null;
	production_error?: string | null;
	artifact_media_ids?: string[];
	logical_mode?: string;
}

type Stage = "IDLE" | "BRIDGED" | "APPROVED" | "ENQUEUED" | "DRY_RUN_DONE" | "LIVE_SUBMITTED";

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

	// ── Round F live gate state ──
	const [phrase, setPhrase] = useState("");
	/** Set the instant the live button is clicked and NEVER cleared — a second
	 *  submission from this page is impossible without a reload. */
	const [liveSubmitted, setLiveSubmitted] = useState(false);
	const [liveError, setLiveError] = useState<string | null>(null);
	const [jobItem, setJobItem] = useState<RunItem | null>(null);
	const pollRef = useRef<number | null>(null);

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
		setPhrase("");
		setLiveSubmitted(false);
		setLiveError(null);
		setJobItem(null);
	};

	/**
	 * Step 1 — reach the queue's unit of work (a WGP).
	 *
	 * T2V takes the dedicated /t2v route: the from-execution-package bridge rejects
	 * T2V outright, so routing it through the bridge would 4xx. F2V/I2V keep the
	 * Round E bridge path unchanged.
	 */
	const handleBridge = async () => {
		if (!selectedWep) return;
		setBusy("bridge");
		setError(null);
		try {
			const wgp =
				selectedWep.mode === "T2V"
					? await createT2VGenerationPackage({
							product_id: selectedWep.product_id,
							workspace_execution_package_id:
								selectedWep.workspace_execution_package_id,
							generation_mode: "SINGLE",
							duration_seconds: selectedWep.duration_seconds ?? 8,
						})
					: await createFromExecutionPackage(
							selectedWep.workspace_execution_package_id,
							selectedWep.mode === "I2V" ? "I2V" : "F2V",
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

	/** Re-read the persisted run + last_dry_run_report + the live item's job state. */
	const handleRefreshReport = useCallback(
		async (id?: string, silent = false) => {
			const target = id ?? runId;
			if (!target) return;
			if (!silent) setBusy("refresh");
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
				const persisted = (cfg as { last_dry_run_report?: DryRunReport })
					?.last_dry_run_report;
				if (persisted) setReport(persisted);

				const items = (detail as unknown as { items?: RunItem[] }).items;
				if (Array.isArray(items) && items.length > 0) setJobItem(items[0]);
			} catch (e) {
				if (!silent) setError(`Refresh failed: ${e instanceof Error ? e.message : String(e)}`);
			} finally {
				if (!silent) setBusy(null);
			}
		},
		[runId],
	);

	/**
	 * Round F — the ONE live door. Fires exactly one provider submission.
	 *
	 * setLiveSubmitted(true) happens BEFORE the await so a double click cannot
	 * produce a second request, and it is never reset — re-firing needs a reload.
	 * The server re-checks every condition under live_gate=ONE_SERIAL_T2V, so a
	 * bypassed UI gate still cannot fan out or fire a non-T2V item.
	 */
	const handleGoLive = async () => {
		if (!runId || !wgpId || !liveGateOpen) return;
		setLiveSubmitted(true);
		setLiveError(null);
		setBusy("live");
		try {
			const res = await startProductionRun(runId, true, {
				live_gate: LIVE_GATE_ONE_SERIAL_T2V,
				confirm_phrase: phrase,
				expect_package_id: wgpId,
			});
			setRunDryRun(Number(res.dry_run));
			setRunStatus(res.status ?? "RUNNING");
			setStage("LIVE_SUBMITTED");
			await handleRefreshReport(runId, true);
		} catch (e) {
			// The server refused. It raises BEFORE any state change, so nothing fired.
			setLiveError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(null);
		}
	};

	// ── Round F gate conditions. Every one must hold; each is surfaced in the UI
	//    so a blocked gate explains itself instead of just being greyed out. ──
	const isT2V = selectedWep?.mode === "T2V";
	const dryRunGreen =
		stage === "DRY_RUN_DONE" &&
		report?.checked === 1 &&
		report?.ready === 1 &&
		report?.blocked === 0;
	const oneItemOnly = (report?.items?.length ?? 0) === 1;
	const noPriorJob = !jobItem?.production_job_id;
	const phraseOk = phrase === LIVE_CONFIRM_PHRASE;
	const liveGateOpen =
		Boolean(isT2V) &&
		dryRunGreen &&
		oneItemOnly &&
		noPriorJob &&
		phraseOk &&
		!liveSubmitted &&
		busy === null;

	const jobTerminal = TERMINAL_STATUSES.has(jobItem?.production_status ?? "");

	/** Poll the run while the live item is still in flight. Read-only: this never
	 *  starts anything, so polling cannot cause a second submission. */
	useEffect(() => {
		if (stage !== "LIVE_SUBMITTED" || !runId || jobTerminal) {
			if (pollRef.current) {
				window.clearInterval(pollRef.current);
				pollRef.current = null;
			}
			return;
		}
		pollRef.current = window.setInterval(() => {
			void handleRefreshReport(runId, true);
		}, POLL_MS);
		return () => {
			if (pollRef.current) {
				window.clearInterval(pollRef.current);
				pollRef.current = null;
			}
		};
	}, [stage, runId, jobTerminal, handleRefreshReport]);

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

			{/* Bulk live remains locked — Round F authorizes ONE serial T2V job only. */}
			<div
				className="mb-6 flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3"
				data-testid="bulk-live-locked"
				data-locked="true"
			>
				<Lock size={16} className="text-amber-300 shrink-0" />
				<div className="text-[11px] text-amber-100">
					<strong>Bulk live generation is locked.</strong> This panel can start{" "}
					<strong>one serial T2V job only</strong>, and only through the gate below. Multi-item
					and non-T2V live runs are refused by the server and remain future-only.
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

			{/* ── 4 · One T2V Live Test — the only live door on this page ── */}
			<section
				className="mt-6 rounded-xl border border-red-500/40 bg-red-500/5 p-4"
				data-testid="live-gate-panel"
				data-gate-open={liveGateOpen ? "true" : "false"}
			>
				<h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-red-200">
					<Flame size={14} /> 4 · One T2V Live Test
				</h2>

				<div
					className="mb-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-[11px] text-red-100"
					data-testid="live-gate-warning"
				>
					<strong>This spends real credits.</strong> It calls the real provider and starts{" "}
					<strong>exactly one</strong> serial T2V generation job. It is not a dry run and it
					cannot be undone. Bulk and non-T2V live runs are refused server-side.
				</div>

				{/* Why the gate is shut — each condition is individually readable. */}
				<div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-3" data-testid="live-gate-checks">
					{[
						{ id: "mode-t2v", label: "Mode is T2V", ok: Boolean(isT2V) },
						{ id: "dry-run-ready", label: "Dry run ready=1 blocked=0", ok: dryRunGreen },
						{ id: "one-item", label: "Exactly 1 queued item", ok: oneItemOnly },
						{ id: "no-prior-job", label: "No prior provider job", ok: noPriorJob },
						{ id: "phrase", label: "Confirmation phrase", ok: phraseOk },
						{ id: "not-submitted", label: "Not already submitted", ok: !liveSubmitted },
					].map((c) => (
						<div
							key={c.id}
							data-testid={`live-gate-check-${c.id}`}
							data-ok={c.ok ? "true" : "false"}
							className={`rounded-lg border px-2 py-1.5 text-[10px] ${
								c.ok
									? "border-emerald-500/40 bg-emerald-500/5 text-emerald-200"
									: "border-slate-700 bg-slate-900/60 text-slate-500"
							}`}
						>
							{c.ok ? "✓" : "○"} {c.label}
						</div>
					))}
				</div>

				<label
					className="mb-1 block text-[10px] uppercase tracking-wider text-slate-400"
					htmlFor="live-confirm-phrase"
				>
					Type <code className="text-red-300">{LIVE_CONFIRM_PHRASE}</code> to authorize
				</label>
				<input
					id="live-confirm-phrase"
					data-testid="live-confirm-phrase-input"
					type="text"
					value={phrase}
					disabled={liveSubmitted}
					onChange={(e) => setPhrase(e.target.value)}
					placeholder={LIVE_CONFIRM_PHRASE}
					autoComplete="off"
					spellCheck={false}
					className="mb-3 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-[11px] text-slate-100 placeholder:text-slate-700 focus:border-red-500/60 focus:outline-none disabled:opacity-40"
				/>

				<button
					type="button"
					data-testid="action-start-one-t2v-live"
					data-enabled={liveGateOpen ? "true" : "false"}
					onClick={() => void handleGoLive()}
					disabled={!liveGateOpen}
					className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/60 bg-red-500/20 px-3 py-2 text-[11px] font-semibold text-red-100 hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-40"
				>
					{busy === "live" ? <Loader2 size={12} className="animate-spin" /> : <Flame size={12} />}
					{liveSubmitted ? "Live run submitted" : "Start ONE live T2V job (burns credits)"}
				</button>

				{liveError && (
					<div
						className="mt-3 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200"
						data-testid="live-gate-refused"
					>
						<AlertTriangle size={14} className="mt-0.5 shrink-0" />
						<span>
							<strong>Live run refused — nothing fired.</strong> {liveError}
						</span>
					</div>
				)}
			</section>

			{/* ── 5 · Result ── */}
			<section
				className="mt-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4"
				data-testid="live-result-panel"
			>
				<div className="mb-3 flex items-center justify-between">
					<h2 className="text-sm font-semibold text-slate-200">5 · Live job result</h2>
					{stage === "LIVE_SUBMITTED" && (
						<button
							type="button"
							data-testid="action-refresh-job"
							onClick={() => void handleRefreshReport()}
							disabled={busy !== null}
							className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] text-slate-300 hover:bg-slate-800 disabled:opacity-40"
						>
							<RefreshCw size={12} className={busy === "refresh" ? "animate-spin" : ""} />{" "}
							Refresh
						</button>
					)}
				</div>

				{stage !== "LIVE_SUBMITTED" && (
					<div className="text-[11px] text-slate-500" data-testid="live-result-empty">
						No live job started. Results appear here after a live T2V run.
					</div>
				)}

				{stage === "LIVE_SUBMITTED" && (
					<div
						data-testid="live-result"
						data-job-status={jobItem?.production_status ?? ""}
						data-terminal={jobTerminal ? "true" : "false"}
						data-polling={jobTerminal ? "false" : "true"}
					>
						<div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-3">
							{chip("Run id", runId, "result-run-id")}
							{chip("WGP id", wgpId, "result-wgp-id")}
							{chip("Provider job id", jobItem?.production_job_id ?? null, "result-job-id")}
							{chip("Item status", jobItem?.production_status ?? null, "result-job-status")}
							{chip("Run status", runStatus, "result-run-status")}
							{chip("dry_run", String(runDryRun ?? ""), "result-dry-run-flag")}
						</div>

						<div
							className="mb-3 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-[11px] text-slate-300"
							data-testid="result-duplicate-protection"
						>
							Duplicate protection: this page submitted once and is now locked. The server
							also refuses a second submission of this package (O4{" "}
							<code>DUPLICATE_SUBMISSION_BLOCKED</code>) unless it is explicitly retried.
						</div>

						{!jobTerminal && (
							<div
								className="flex items-center gap-2 text-[11px] text-slate-400"
								data-testid="result-in-flight"
							>
								<Loader2 size={12} className="animate-spin" /> Job in flight — polling every{" "}
								{POLL_MS / 1000}s. No further submission will be made.
							</div>
						)}

						{jobItem?.production_error && (
							<div
								className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200"
								data-testid="result-failure"
							>
								<strong>Job failed.</strong> {jobItem.production_error}
							</div>
						)}

						{jobTerminal && !jobItem?.production_error && (
							<div
								className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-[11px] text-emerald-200"
								data-testid="result-success"
							>
								<strong>Job {jobItem?.production_status}.</strong>{" "}
								{(jobItem?.artifact_media_ids?.length ?? 0) > 0 ? (
									<>
										Artifacts:{" "}
										{(jobItem?.artifact_media_ids ?? []).map((m) => (
											<a
												key={m}
												data-testid="result-artifact"
												data-media-id={m}
												href={`/api/flow/retrieved/${encodeURIComponent(m)}`}
												target="_blank"
												rel="noreferrer"
												className="mr-2 font-mono underline hover:text-emerald-100"
											>
												{m}
											</a>
										))}
									</>
								) : (
									<span data-testid="result-no-artifact">
										No artifact media id recorded on the item.
									</span>
								)}
							</div>
						)}
					</div>
				)}
			</section>
		</div>
	);
}
