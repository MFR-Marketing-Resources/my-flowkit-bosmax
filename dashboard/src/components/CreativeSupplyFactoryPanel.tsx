import {
	AlertTriangle,
	CheckCircle2,
	Factory,
	Pause,
	Play,
	RefreshCw,
	RotateCcw,
	ShieldCheck,
	XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
	controlSupplyRun,
	executeSupplyStep,
	fetchSupplyRun,
	listSupplyRuns,
	reconcileInterruptedSupplyTask,
	requeueUnsubmittedSupplyTask,
	type ReviewCandidate,
	type SupplyRun,
	type SupplyRunStatus,
	retrySupplyTask,
	reviewSupplyComponent,
} from "../api/creativeSupply";

const tone = (value: string) => {
	if (/READY|APPROVED|COMPLETED|VERIFIED/.test(value)) {
		return "border-emerald-500/40 bg-emerald-500/10 text-emerald-200";
	}
	if (/BLOCKED|FAILED|REJECTED|MISSING/.test(value)) {
		return "border-rose-500/40 bg-rose-500/10 text-rose-200";
	}
	return "border-amber-500/40 bg-amber-500/10 text-amber-100";
};

function Badge({ children }: { children: string }) {
	return (
		<span className={`rounded-full border px-2 py-0.5 text-[10px] ${tone(children)}`}>
			{children}
		</span>
	);
}

function Metric({ label, value }: { label: string; value: string | number }) {
	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">
				{label}
			</div>
			<div className="mt-1 text-lg font-semibold text-slate-100">{value}</div>
		</div>
	);
}

export default function CreativeSupplyFactoryPanel() {
	const [runs, setRuns] = useState<SupplyRun[]>([]);
	const [runId, setRunId] = useState("");
	const [status, setStatus] = useState<SupplyRunStatus | null>(null);
	const [busy, setBusy] = useState("");
	const [error, setError] = useState("");
	const [reviewReasons, setReviewReasons] = useState<Record<string, string>>({});

	const refresh = useCallback(async (preferredRunId?: string) => {
		const listed = await listSupplyRuns();
		setRuns(listed.runs);
		const next = preferredRunId || listed.runs[0]?.run_id || "";
		setRunId(next);
		setStatus(next ? await fetchSupplyRun(next) : null);
	}, []);

	useEffect(() => {
		void refresh().catch((reason) =>
			setError(reason instanceof Error ? reason.message : String(reason)),
		);
	}, [refresh]);

	const execute = async (
		name: string,
		action: () => Promise<SupplyRunStatus | { run: SupplyRunStatus }>,
	) => {
		setBusy(name);
		setError("");
		try {
			const result = await action();
			setStatus("products" in result ? result : result.run);
			const listed = await listSupplyRuns();
			setRuns(listed.runs);
		} catch (reason) {
			setError(reason instanceof Error ? reason.message : String(reason));
		} finally {
			setBusy("");
		}
	};

	const run = status?.run;
	const pendingReview = useMemo(
		() =>
			status?.review_queue.reduce(
				(total, task) =>
					total +
					task.candidates.filter(
						(candidate) => candidate.status === "COMPONENT_REVIEW_REQUIRED",
					).length,
				0,
			) ?? 0,
		[status],
	);

	const decide = async (
		taskId: string,
		candidate: ReviewCandidate,
		decision: "APPROVED" | "REJECTED",
	) => {
		const reason = (reviewReasons[candidate.component_id] || "").trim();
		if (!reason) {
			setError(
				"Review reason required. Confirm relevance, angle/type fit, Product Truth, claim safety, BM quality, dedupe, and provenance.",
			);
			return;
		}
		await execute(`review:${candidate.component_id}`, () =>
			reviewSupplyComponent(runId, {
				task_id: taskId,
				component_id: candidate.component_id,
				decision,
				reviewed_content_sha256: candidate.content_sha256,
				reasons: [reason],
				reviewer_id: run?.reviewer_id || "codex-p7-reviewer",
			}),
		);
		setReviewReasons((current) => {
			const next = { ...current };
			delete next[candidate.component_id];
			return next;
		});
	};

	return (
		<section
			data-testid="p7-creative-supply-factory"
			className="rounded-2xl border border-violet-500/30 bg-gradient-to-br from-slate-950 via-slate-950 to-violet-950/30 p-4"
		>
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-violet-300">
						<Factory size={15} />
						P7 · Creative Supply Factory
					</div>
					<h2 className="mt-1 text-lg font-semibold">Top-10 governed supply activation</h2>
					<p className="mt-1 max-w-3xl text-xs text-slate-400">
						One measured deficit per call, durable pause/resume, SHA-bound review,
						deterministic capacity, then handoff to the existing P6 execution gates.
					</p>
				</div>
				<div className="flex items-center gap-2">
					<select
						aria-label="Creative supply run"
						value={runId}
						onChange={(event) => {
							const next = event.target.value;
							setRunId(next);
							void refresh(next).catch((reason) => setError(String(reason)));
						}}
						className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs"
					>
						{runs.length === 0 && <option value="">No P7 run</option>}
						{runs.map((item) => (
							<option key={item.run_id} value={item.run_id}>
								{item.mission_id} · {item.state}
							</option>
						))}
					</select>
					<button
						type="button"
						aria-label="Refresh creative supply"
						onClick={() => void refresh(runId)}
						className="rounded-lg border border-slate-700 p-2 text-slate-300"
					>
						<RefreshCw size={15} />
					</button>
				</div>
			</div>

			{error && (
				<div
					role="alert"
					data-testid="p7-supply-error"
					className="mt-3 flex gap-2 rounded-lg border border-rose-500/40 bg-rose-950/40 p-3 text-xs text-rose-200"
				>
					<XCircle size={15} className="shrink-0" />
					<span className="break-all">{error}</span>
				</div>
			)}

			{!status ? (
				<div
					data-testid="p7-empty-run"
					className="mt-4 rounded-xl border border-dashed border-slate-700 p-5 text-sm text-slate-400"
				>
					No frozen P7 run is registered. The mission rehearsal creates the
					authority-bound run after roster and angle evidence are imported.
				</div>
			) : (
				<>
					<div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
						<Metric label="Run state" value={run?.state || "—"} />
						<Metric
							label="Text calls"
							value={`${status.provider_budget.used}/${status.provider_budget.maximum}`}
						/>
						<Metric label="Calls remaining" value={status.provider_budget.remaining} />
						<Metric
							label="Planned slot calls"
							value={status.provider_budget.pending_or_retry_calls}
						/>
						<Metric label="Review queue" value={pendingReview} />
						<Metric label="Products" value={status.products.length} />
					</div>

					<div className="mt-3 flex flex-wrap items-center gap-2">
						<Badge>{run?.state || "UNKNOWN"}</Badge>
						<Badge>
							{status.provider_budget.within_ceiling
								? "BUDGET_WITHIN_CEILING"
								: "BUDGET_BLOCKED"}
						</Badge>
						<span className="font-mono text-[10px] text-slate-500">
							roster {run?.roster_sha256.slice(0, 16)}… · cohort{" "}
							{run?.cohort_sha256.slice(0, 16)}…
						</span>
						<button
							type="button"
							data-testid="p7-author-next-slot"
							disabled={
								Boolean(busy) ||
								!run ||
								!["READY", "RUNNING"].includes(run.state) ||
								status.provider_budget.pending_or_retry_calls === 0
							}
							onClick={() =>
								void execute("step", () => executeSupplyStep(runId))
							}
							className="ml-auto inline-flex items-center gap-1 rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold disabled:opacity-40"
						>
							<Play size={14} />
							Author next missing slot
						</button>
						{run?.state === "PAUSED" ? (
							<button
								type="button"
								data-testid="p7-resume-run"
								disabled={Boolean(busy)}
								onClick={() =>
									void execute("resume", () =>
										controlSupplyRun(runId, "RESUME"),
									)
								}
								className="inline-flex items-center gap-1 rounded-lg border border-emerald-500/40 px-3 py-2 text-xs text-emerald-200"
							>
								<Play size={14} /> Resume
							</button>
						) : (
							<button
								type="button"
								data-testid="p7-pause-run"
								disabled={Boolean(busy) || !run}
								onClick={() =>
									void execute("pause", () =>
										controlSupplyRun(
											runId,
											"PAUSE",
											"Operator paused at a durable task boundary.",
										),
									)
								}
								className="inline-flex items-center gap-1 rounded-lg border border-amber-500/40 px-3 py-2 text-xs text-amber-200"
							>
								<Pause size={14} /> Pause
							</button>
						)}
					</div>

					<div className="mt-4 overflow-x-auto rounded-xl border border-slate-800">
						<table className="min-w-full text-left text-xs">
							<thead className="bg-slate-900/80 text-slate-400">
								<tr>
									{[
										"Rank / product",
										"Truth",
										"Angles",
										"Components",
										"Capacity",
										"Visual / P6 readiness",
										"Next action",
									].map((label) => (
										<th key={label} className="px-3 py-2 font-medium">
											{label}
										</th>
									))}
								</tr>
							</thead>
							<tbody>
								{status.products.map((product) => (
									<tr
										key={product.product_id}
										data-testid={`p7-product-${product.product_id}`}
										className="border-t border-slate-800 align-top"
									>
										<td className="px-3 py-3">
											<div className="font-semibold text-slate-200">
												#{product.rank} · {product.product_name}
											</div>
											<div className="mt-1 font-mono text-[10px] text-slate-600">
												{product.product_id}
											</div>
											<Badge>{product.role}</Badge>
										</td>
										<td className="space-y-1 px-3 py-3">
											<div>
												<Badge>{product.approved_snapshot_status}</Badge>
											</div>
											<div>
												<Badge>{product.claim_gate}</Badge>
											</div>
										</td>
										<td className="px-3 py-3">{product.angle_count}</td>
										<td className="px-3 py-3">
											<div>{product.approved_count} approved</div>
											<div className="text-amber-300">
												{product.review_required_count} review
											</div>
											<div className="text-rose-300">
												{product.rejected_count} rejected
											</div>
											<div className="text-slate-500">
												{product.deficits.length} deficit slots
											</div>
										</td>
										<td className="px-3 py-3">
											{product.composable_capacity}/{product.capacity_target}
										</td>
										<td className="space-y-1 px-3 py-3">
											<div>
												avatar <Badge>{product.avatar_readiness}</Badge>
											</div>
											<div>
												scene <Badge>{product.scene_readiness}</Badge>
											</div>
											<div>
												poster <Badge>{product.poster_image_readiness}</Badge>
											</div>
											<div className="text-[10px] text-slate-500">
												{product.blockers.join(" · ") || "No blocker"}
											</div>
										</td>
										<td className="px-3 py-3 font-mono text-[10px] text-violet-200">
											{product.next_best_supply_action}
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>

					{status.review_queue.length > 0 && (
						<div className="mt-4 space-y-3" data-testid="p7-review-queue">
							<div className="flex items-center gap-2">
								<ShieldCheck size={15} className="text-violet-300" />
								<h3 className="text-sm font-semibold">SHA-bound candidate review</h3>
								<span className="text-[10px] text-slate-500">
									No bulk approval control exists.
								</span>
							</div>
							{status.review_queue.map((task) => (
								<div
									key={task.task_id}
									className="rounded-xl border border-slate-800 bg-slate-950/70 p-3"
								>
									<div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
										<Badge>{task.component_type}</Badge>
										<span>{task.angle_label}</span>
										<span className="font-mono text-[10px] text-slate-600">
											{task.task_kind} · round {task.deficit_round} ·{" "}
											{task.task_id}
										</span>
									</div>
									<div className="grid gap-2 xl:grid-cols-2">
										{task.candidates.map((candidate) => (
											<div
												key={candidate.component_id}
												data-testid={`p7-review-${candidate.component_id}`}
												className="rounded-lg border border-slate-800 bg-slate-900/70 p-3"
											>
												<p className="whitespace-pre-wrap text-sm text-slate-200">
													{candidate.content}
												</p>
												<div className="mt-2 font-mono text-[9px] text-slate-600">
													SHA {candidate.content_sha256}
												</div>
												<input
													aria-label={`Review reason ${candidate.component_id}`}
													value={reviewReasons[candidate.component_id] || ""}
													onChange={(event) =>
														setReviewReasons({
															...reviewReasons,
															[candidate.component_id]: event.target.value,
														})
													}
													placeholder="Evidence-based approval or rejection reason"
													className="mt-2 w-full rounded border border-slate-700 bg-slate-950 px-2 py-2 text-xs"
												/>
												<div className="mt-2 flex gap-2">
													<button
														type="button"
														disabled={
															Boolean(busy) ||
															candidate.status !== "COMPONENT_REVIEW_REQUIRED"
														}
														onClick={() =>
															void decide(task.task_id, candidate, "APPROVED")
														}
														className="inline-flex items-center gap-1 rounded bg-emerald-700 px-2 py-1 text-xs disabled:opacity-40"
													>
														<CheckCircle2 size={13} /> Approve reviewed
													</button>
													<button
														type="button"
														disabled={
															Boolean(busy) ||
															candidate.status !== "COMPONENT_REVIEW_REQUIRED"
														}
														onClick={() =>
															void decide(task.task_id, candidate, "REJECTED")
														}
														className="inline-flex items-center gap-1 rounded bg-rose-800 px-2 py-1 text-xs disabled:opacity-40"
													>
														<XCircle size={13} /> Reject
													</button>
												</div>
											</div>
										))}
									</div>
								</div>
							))}
						</div>
					)}

					{status.tasks.some((task) => task.state === "RETRY_ELIGIBLE") && (
						<div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-950/20 p-3">
							<div className="flex items-center gap-2 text-xs text-amber-200">
								<AlertTriangle size={14} />
								Explicit transient retry authority
							</div>
							{status.tasks
								.filter((task) => task.state === "RETRY_ELIGIBLE")
								.map((task) => (
									<button
										type="button"
										key={task.task_id}
										onClick={() =>
											void execute(`retry:${task.task_id}`, () =>
												retrySupplyTask(runId, task.task_id),
											)
										}
										className="mt-2 mr-2 inline-flex items-center gap-1 rounded border border-amber-500/40 px-2 py-1 text-xs"
									>
										<RotateCcw size={13} />
										Retry once · {task.product_id} · {task.component_type}
									</button>
								))}
						</div>
					)}

					{status.tasks.some(
						(task) =>
							task.state === "FAILED" &&
							task.provider_call_count === 0 &&
							/AICopyProviderNotConfigured/.test(task.last_error || ""),
					) && (
						<div className="mt-4 rounded-xl border border-sky-500/30 bg-sky-950/20 p-3">
							<div className="text-xs text-sky-200">
								Provider configuration blocked before submission. Once the
								canonical lane is restored, requeueing spends no retry allowance.
							</div>
							{status.tasks
								.filter(
									(task) =>
										task.state === "FAILED" &&
										task.provider_call_count === 0 &&
										/AICopyProviderNotConfigured/.test(task.last_error || ""),
								)
								.map((task) => (
									<button
										type="button"
										key={task.task_id}
										onClick={() =>
											void execute(`requeue:${task.task_id}`, () =>
												requeueUnsubmittedSupplyTask(runId, task.task_id),
											)
										}
										className="mt-2 mr-2 inline-flex items-center gap-1 rounded border border-sky-500/40 px-2 py-1 text-xs"
									>
										<RotateCcw size={13} />
										Requeue unsubmitted · {task.product_id} ·{" "}
										{task.component_type}
									</button>
								))}
						</div>
					)}

					{status.tasks.some((task) => task.state === "RUNNING") && (
						<div className="mt-4 rounded-xl border border-rose-500/30 bg-rose-950/20 p-3">
							<div className="text-xs text-rose-200">
								A RUNNING task survived its worker process. Reconciliation
								conservatively charges one possible provider call and creates a
								new deficit round; it never rewrites the original task.
							</div>
							{status.tasks
								.filter((task) => task.state === "RUNNING")
								.map((task) => (
									<button
										type="button"
										key={task.task_id}
										onClick={() =>
											void execute(`reconcile:${task.task_id}`, () =>
												reconcileInterruptedSupplyTask(
													runId,
													task.task_id,
													"Operator confirmed worker process interruption after RUNNING transition.",
												),
											)
										}
										className="mt-2 mr-2 inline-flex items-center gap-1 rounded border border-rose-500/40 px-2 py-1 text-xs"
									>
										<AlertTriangle size={13} />
										Reconcile interrupted · {task.product_id} ·{" "}
										{task.component_type}
									</button>
								))}
						</div>
					)}

					<div className="mt-4 rounded-xl border border-cyan-500/20 bg-cyan-950/20 p-3 text-xs text-cyan-100">
						<strong>Production activation remains P6-governed.</strong> Use the
						plan, dry-run, verified-lane, exact live confirmation, attempt,
						retrieval, artifact registration, and QA controls below. This factory
						contains no media execution endpoint.
					</div>
				</>
			)}
		</section>
	);
}
