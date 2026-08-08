/**
 * Montage — discrete multi-scene operator workspace (V4 language).
 *
 * Hook/Background options come ONLY from creative-lane settings API (same SSOT
 * as Faceless). No local vocabulary arrays.
 *
 * Operator: Product → Hook/BG → Model+Duration → Scene Plan → Generate Montage
 * → Progress → Final Video. Backend ledger/authorize/bind/readiness/concat hidden.
 * Credit fire requires explicit count confirm.
 */
import { useEffect, useState } from "react";
import { useCreativeLaneSettings } from "../api/creativeLaneSettings";
import { fetchVideoModels, type VideoModelInfo } from "../api/productionQueue";
import {
	assembleMontageRunDryRun,
	authorizeMontageGeneration,
	checkMontageRunReadiness,
	createMontagePlan,
	createMontageRun,
	fetchMontageGenerationEstimate,
	type MontageAuthorizeGenerationResponse,
	type MontageGenerationEstimate,
	type MontagePlanResponse,
	type MontageReadinessResponse,
	type MontageRunResponse,
} from "../api/montage";
import { fetchProductCatalog } from "../api/products";
import {
	OperatorCockpit,
	WorkflowStep,
	type WorkflowStepStatus,
} from "../components/workflow";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { Product } from "../types";

const selectClass =
	"w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100";
const labelClass = "text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500";

function labelOf(
	opts: ReadonlyArray<{ id: string; label: string }>,
	id: string,
): string {
	return opts.find((o) => o.id === id)?.label ?? id;
}

export default function MontagePage() {
	const {
		settings,
		loading: settingsLoading,
		error: settingsError,
		available: settingsAvailable,
		reload: reloadSettings,
	} = useCreativeLaneSettings();
	const [products, setProducts] = useState<Product[]>([]);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [hookId, setHookId] = useState("AUTO");
	const [backgroundId, setBackgroundId] = useState("AUTO");
	const [videoModels, setVideoModels] = useState<VideoModelInfo[]>([]);
	const [videoModel, setVideoModel] = useState("Veo 3.1 - Lite");
	const [clipDuration, setClipDuration] = useState(8);
	const [plan, setPlan] = useState<MontagePlanResponse | null>(null);
	const [run, setRun] = useState<MontageRunResponse | null>(null);
	const [readiness, setReadiness] = useState<MontageReadinessResponse | null>(
		null,
	);
	const [assembleNote, setAssembleNote] = useState<string | null>(null);
	const [estimate, setEstimate] = useState<MontageGenerationEstimate | null>(null);
	const [authNote, setAuthNote] = useState<string | null>(null);
	const [creditConfirm, setCreditConfirm] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [v4Open, setV4Open] = useState<Record<number, boolean>>({});

	useEffect(() => {
		void fetchProductCatalog(250, "GENERATION")
			.then((r) => setProducts(r.items || []))
			.catch(() => setProducts([]));
		void fetchVideoModels()
			.then((r) => {
				setVideoModels(r.models || []);
				if (r.default) setVideoModel(String(r.default));
			})
			.catch(() => setVideoModels([]));
	}, []);

	const hookLabel = labelOf(settings.hook.options, hookId);
	const backgroundLabel = labelOf(settings.background.options, backgroundId);

	const v4IsOpen = (index: number, status: WorkflowStepStatus) =>
		v4Open[index] ?? status === "active";
	const v4Toggle = (index: number, currentOpen: boolean) =>
		setV4Open((prev) => ({ ...prev, [index]: !currentOpen }));

	const canOperate = Boolean(selectedProduct) && settingsAvailable;
	const packagesReady = Boolean(
		run?.scenes?.some((s) => s.workspace_execution_package_id),
	);
	const packageCount =
		run?.scenes?.filter((s) => s.workspace_execution_package_id).length ?? 0;

	const sProduct: WorkflowStepStatus = selectedProduct ? "done" : "active";
	const sCreative: WorkflowStepStatus =
		selectedProduct && settingsAvailable
			? "done"
			: selectedProduct
				? "active"
				: "upcoming";
	const sPlan: WorkflowStepStatus = plan
		? "done"
		: canOperate
			? "active"
			: "upcoming";
	const sExec: WorkflowStepStatus = run
		? run.ok === false
			? "active"
			: "done"
		: plan
			? "active"
			: "upcoming";
	const sAuth: WorkflowStepStatus = authNote
		? "done"
		: run
			? "active"
			: "upcoming";
	const sReady: WorkflowStepStatus = readiness
		? readiness.ok
			? "done"
			: "active"
		: authNote
			? "active"
			: "upcoming";
	const sAssemble: WorkflowStepStatus = assembleNote
		? "done"
		: readiness?.ok
			? "active"
			: "upcoming";

	const handlePlan = async () => {
		if (!selectedProduct || !settingsAvailable) return;
		setBusy(true);
		setError(null);
		setReadiness(null);
		setRun(null);
		setAssembleNote(null);
		setEstimate(null);
		setAuthNote(null);
		setCreditConfirm(false);
		try {
			const next = await createMontagePlan({
				product_id: selectedProduct.id,
				hook_id: hookId,
				background_id: backgroundId,
			});
			setPlan(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Plan failed");
			setPlan(null);
		} finally {
			setBusy(false);
		}
	};

	const handleStartRun = async () => {
		if (!selectedProduct || !settingsAvailable) return;
		setBusy(true);
		setError(null);
		setAssembleNote(null);
		setReadiness(null);
		setEstimate(null);
		setAuthNote(null);
		setCreditConfirm(false);
		try {
			const res = await createMontageRun({
				product_id: selectedProduct.id,
				hook_id: hookId,
				background_id: backgroundId,
				product_media_id: null,
				model: videoModel,
				duration_seconds: clipDuration,
			});
			setRun(res);
			try {
				const est = await fetchMontageGenerationEstimate(res.montage_run_id);
				setEstimate(est);
			} catch {
				/* estimate is best-effort after create */
			}
		} catch (e) {
			setError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(false);
		}
	};


	const handleRefreshEstimate = async () => {
		if (!run?.montage_run_id) return;
		setBusy(true);
		setError(null);
		try {
			const est = await fetchMontageGenerationEstimate(run.montage_run_id);
			setEstimate(est);
		} catch (e) {
			setError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(false);
		}
	};

	const handleAuthorize = async (dryRun: boolean) => {
		if (!run?.montage_run_id || !estimate) return;
		if (!creditConfirm) {
			setError("Confirm credit count before authorize (checkbox).");
			return;
		}
		setBusy(true);
		setError(null);
		try {
			const res: MontageAuthorizeGenerationResponse =
				await authorizeMontageGeneration(run.montage_run_id, {
					confirm_credit_burn: true,
					expected_video_generations: estimate.expected_video_generations,
					dry_run: dryRun,
				});
			setAuthNote(
				res.detail ||
					(dryRun
						? `Authorized dry-run: ${res.summary}`
						: `Dispatched ${res.dispatched?.length ?? 0} generation(s)`),
			);
			if (res.run) setRun(res.run);
			// refresh estimate after dispatch
			const est = await fetchMontageGenerationEstimate(run.montage_run_id);
			setEstimate(est);
			if (!dryRun && res.run) {
				// auto-check readiness after bind
				try {
					const ready = await checkMontageRunReadiness(run.montage_run_id);
					setReadiness(ready);
				} catch {
					/* optional */
				}
			}
		} catch (e) {
			setError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(false);
		}
	};

	const handleRunReadiness = async () => {
		if (!run?.montage_run_id) return;
		setBusy(true);
		setError(null);
		try {
			const res = await checkMontageRunReadiness(run.montage_run_id);
			setReadiness(res);
		} catch (e) {
			setError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(false);
		}
	};

	const handleAssemble = async () => {
		if (!run?.montage_run_id) return;
		setBusy(true);
		setError(null);
		setAssembleNote(null);
		try {
			const res = await assembleMontageRunDryRun(run.montage_run_id);
			setAssembleNote(
				res.ok
					? `Assemble dry-run OK — clips: ${(res.readiness?.clip_media_ids || []).join(", ") || "none"}`
					: "Assemble dry-run returned not-ok",
			);
		} catch (e) {
			setError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(false);
		}
	};

	return (
		<div
			className="flex h-full min-h-0 flex-col gap-4 p-4 md:p-6"
			data-testid="montage-workflow"
			data-variant="v4"
			data-mode="MONTAGE"
			data-settings-source={settings.source}
		>
			<header>
				<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-v4-accent">
					Montage
				</div>
				<h1 className="text-xl font-bold text-slate-100">
					One product → N discrete scenes → one finished video
				</h1>
				<p className="mt-1 max-w-2xl text-[12px] text-slate-400">
					One product, N short clips, one finished video. Choose product, hook,
					background, model and clip duration — then Generate Montage. Credits
					only after you confirm the operation count.
				</p>
			</header>

			<div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
				<div className="min-h-0 space-y-3 overflow-y-auto pr-1">
					<WorkflowStep
						index={1}
						title="Product"
						status={sProduct}
						open={v4IsOpen(1, sProduct)}
						onToggleOpen={() => v4Toggle(1, v4IsOpen(1, sProduct))}
						summary={
							selectedProduct
								? selectedProduct.raw_product_title || selectedProduct.id
								: "Select a product"
						}
					>
						<SearchableProductSelect
							products={products}
							selectedProduct={selectedProduct}
							onSelect={(p) => {
								setSelectedProduct(p);
								setPlan(null);
								setRun(null);
								setReadiness(null);
								setAssembleNote(null);
							}}
						/>
					</WorkflowStep>

					<WorkflowStep
						index={2}
						title="Hook & background"
						status={sCreative}
						open={v4IsOpen(2, sCreative)}
						onToggleOpen={() => v4Toggle(2, v4IsOpen(2, sCreative))}
						summary={`${hookLabel} · ${backgroundLabel}`}
						helper="Options from GET /api/creative-lane-settings only (no local SSOT copy)."
					>
						{!settingsAvailable ? (
							<div
								className="mb-2 text-[11px] text-rose-300"
								data-testid="montage-settings-unavailable"
							>
								{settingsLoading
									? "Loading settings…"
									: `Settings unavailable${settingsError ? `: ${settingsError}` : ""}.`}{" "}
								<button
									type="button"
									className="underline"
									onClick={() => reloadSettings()}
									data-testid="montage-settings-retry"
								>
									Retry
								</button>
							</div>
						) : null}
						<div className="grid gap-3 sm:grid-cols-2">
							<label className="block">
								<span className={labelClass}>Hook</span>
								<select
									className={selectClass}
									value={hookId}
									disabled={!settingsAvailable}
									onChange={(e) => setHookId(e.target.value)}
									data-testid="montage-hook"
								>
									{settings.hook.options.map((o) => (
										<option key={o.id} value={o.id}>
											{o.label}
										</option>
									))}
								</select>
							</label>
							<label className="block">
								<span className={labelClass}>Background</span>
								<select
									className={selectClass}
									value={backgroundId}
									disabled={!settingsAvailable}
									onChange={(e) => setBackgroundId(e.target.value)}
									data-testid="montage-background"
								>
									{settings.background.options.map((o) => (
										<option key={o.id} value={o.id}>
											{o.label}
										</option>
									))}
								</select>
							</label>
						</div>

					</WorkflowStep>

					<WorkflowStep
						index={3}
						title="Video settings"
						status={canOperate ? "done" : "upcoming"}
						open={v4IsOpen(3, canOperate ? "done" : "upcoming")}
						onToggleOpen={() => v4Toggle(3, v4IsOpen(3, canOperate ? "done" : "upcoming"))}
						summary={`${videoModel} · ${clipDuration}s / scene`}
						helper="Discrete SINGLE clips only — final length = N × clip duration (concat)."
					>
						<div className="grid gap-3 sm:grid-cols-2">
							<label className="space-y-1">
								<span className={labelClass}>Video model</span>
								<select
									className={selectClass}
									value={videoModel}
									onChange={(e) => setVideoModel(e.target.value)}
									data-testid="montage-model"
								>
									{(videoModels.length
										? videoModels.map((m) => m.ui_label)
										: [videoModel]
									).map((label) => (
										<option key={label} value={label}>
											{label}
										</option>
									))}
								</select>
							</label>
							<label className="space-y-1">
								<span className={labelClass}>Clip duration</span>
								<select
									className={selectClass}
									value={clipDuration}
									onChange={(e) => setClipDuration(Number(e.target.value))}
									data-testid="montage-duration"
								>
									{[4, 6, 8].map((d) => (
										<option key={d} value={d}>
											{d}s
										</option>
									))}
								</select>
							</label>
						</div>
</WorkflowStep>

					<WorkflowStep
						index={3}
						title="Plan scenes"
						status={sPlan}
						open={v4IsOpen(3, sPlan)}
						onToggleOpen={() => v4Toggle(3, v4IsOpen(3, sPlan))}
						summary={
							plan
								? `${plan.scene_count} scenes · ${plan.assembly_path}`
								: "Expand beats into discrete scene plans"
						}
					>
						<button
							type="button"
							disabled={!canOperate || busy}
							onClick={() => void handlePlan()}
							className="rounded-xl border border-v4-accent/40 bg-v4-accent/15 px-4 py-2.5 text-[12px] font-bold text-v4-accent-ink hover:bg-v4-accent/25 disabled:opacity-40"
							data-testid="montage-plan"
						>
							{busy ? "Planning…" : "Plan scenes"}
						</button>
						{plan ? (
							<ul
								className="mt-3 space-y-1 text-[11px] text-slate-300"
								data-testid="montage-plan-list"
							>
								{plan.scenes.map((s) => (
									<li key={s.scene_id} className="rounded border border-slate-800 px-2 py-1">
										<span className="font-semibold text-slate-100">{s.scene_id}</span>
										{" · "}
										{s.route} · {s.transport_mode}/{s.source_mode} ·{" "}
										{s.reference_policy}
									</li>
								))}
							</ul>
						) : null}
					</WorkflowStep>

					<WorkflowStep
						index={4}
						title="Scene plan & prepare"
						status={sExec}
						open={v4IsOpen(4, sExec)}
						onToggleOpen={() => v4Toggle(4, v4IsOpen(4, sExec))}
						summary={
							run
								? `${packageCount}/${run.total_scenes} packages · run ${run.montage_run_id.slice(0, 8)}`
								: "Persist scene job ledger + workspace packages"
						}
						helper="M-02 durable path on bulk_generation_run kind=MONTAGE_DISCRETE. No credit auto-fire."
					>
						<button
							type="button"
							disabled={!canOperate || busy}
							onClick={() => void handleStartRun()}
							className="rounded-xl border border-v4-accent/40 bg-v4-accent/15 px-4 py-2.5 text-[12px] font-bold text-v4-accent-ink hover:bg-v4-accent/25 disabled:opacity-40"
							data-testid="montage-execute"
						>
							{busy ? "Preparing…" : "Prepare scene packages"}
						</button>
						{run ? (
							<ul
								className="mt-3 space-y-1 text-[11px] text-slate-300"
								data-testid="montage-exec-list"
							>
								{run.scenes.map((s) => (
									<li key={s.scene_id} className="rounded border border-slate-800 px-2 py-1">
										<span className="font-semibold text-slate-100">{s.scene_id}</span>
										{" · "}
										{s.status}
										{s.workspace_execution_package_id
											? ` · ${s.workspace_execution_package_id}`
											: ""}
										{s.video_media_id ? ` · clip=${s.video_media_id}` : ""}
										{s.error_code ? ` · ${s.error_code}` : ""}
									</li>
								))}
							</ul>
						) : null}
					</WorkflowStep>


					<WorkflowStep
						index={5}
						title="Authorize scene generation"
						status={sAuth}
						open={v4IsOpen(5, sAuth)}
						onToggleOpen={() => v4Toggle(5, v4IsOpen(5, sAuth))}
						summary={
							estimate
								? estimate.summary
								: "Load credit estimate after durable run"
						}
						helper="M-04: operator must confirm N scenes → N video generations before any multi-scene fire. Dry-run validates counts only."
					>
						<button
							type="button"
							disabled={busy || !run}
							onClick={() => void handleRefreshEstimate()}
							className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2.5 text-[12px] font-bold text-slate-100 hover:bg-slate-800 disabled:opacity-40"
							data-testid="montage-estimate"
						>
							Refresh operation estimate
						</button>
						{estimate ? (
							<div
								className="mt-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[12px] text-amber-50"
								data-testid="montage-estimate-summary"
							>
								<div className="font-bold tracking-wide text-amber-100">
									{estimate.summary}
								</div>
								<div className="mt-1 text-[11px] opacity-90">
									Pending scenes:{" "}
									{(estimate.pending_scene_ids || []).join(", ") || "none"}
								</div>
								<label className="mt-3 flex items-start gap-2 text-[11px] text-slate-200">
									<input
										type="checkbox"
										checked={creditConfirm}
										onChange={(e) => setCreditConfirm(e.target.checked)}
										data-testid="montage-credit-confirm"
										className="mt-0.5"
									/>
									<span>
										I authorize{" "}
										<strong>{estimate.expected_video_generations}</strong> video
										generation(s) for this Montage run (explicit credit control).
									</span>
								</label>
								<div className="mt-3 flex flex-wrap gap-2">
									<button
										type="button"
										disabled={busy || !creditConfirm}
										onClick={() => void handleAuthorize(true)}
										className="rounded-xl border border-v4-accent/40 bg-v4-accent/15 px-4 py-2 text-[12px] font-bold text-v4-accent-ink hover:bg-v4-accent/25 disabled:opacity-40"
										data-testid="montage-authorize-dry"
									>
										Confirm ops (no spend)
									</button>
									<button
										type="button"
										disabled={busy || !creditConfirm || estimate.expected_video_generations === 0}
										onClick={() => void handleAuthorize(false)}
										className="rounded-xl border border-rose-700/50 bg-rose-950/40 px-4 py-2 text-[12px] font-bold text-rose-100 hover:bg-rose-900/40 disabled:opacity-40"
										data-testid="montage-authorize-live"
										title="Calls /api/flow/generate per pending scene with startAsset — spends credits"
									>
										Authorize + dispatch (credits)
									</button>
								</div>
							</div>
						) : null}
						{authNote ? (
							<p
								className="mt-2 text-[11px] text-emerald-300"
								data-testid="montage-auth-note"
							>
								{authNote}
							</p>
						) : null}
					</WorkflowStep>

					<WorkflowStep
						index={6}
						title="Assembly readiness"
						status={sReady}
						open={v4IsOpen(6, sReady)}
						onToggleOpen={() => v4Toggle(6, v4IsOpen(6, sReady))}
						summary={
							readiness
								? readiness.ok
									? `Ready · ${readiness.clip_media_ids.length} clips`
									: `Blocked · ${readiness.blockers?.length ?? 0}`
								: "Check durable run before concat"
						}
					>
						<button
							type="button"
							disabled={busy || !run}
							onClick={() => void handleRunReadiness()}
							className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2.5 text-[12px] font-bold text-slate-100 hover:bg-slate-800 disabled:opacity-40"
							data-testid="montage-readiness"
						>
							Check run readiness
						</button>
						{readiness ? (
							<pre
								className="mt-2 max-h-40 overflow-auto rounded border border-slate-800 bg-slate-950 p-2 text-[10px] text-slate-300"
								data-testid="montage-readiness-json"
							>
								{JSON.stringify(
									{
										ok: readiness.ok,
										code: readiness.code,
										detail: readiness.detail,
										blockers: readiness.blockers,
										clip_media_ids: readiness.clip_media_ids,
									},
									null,
									2,
								)}
							</pre>
						) : null}
					</WorkflowStep>

					<WorkflowStep
						index={7}
						title="Final video"
						status={sAssemble}
						open={v4IsOpen(7, sAssemble)}
						onToggleOpen={() => v4Toggle(7, v4IsOpen(7, sAssemble))}
						summary={assembleNote || "Gated concat boundary — incomplete set never calls concat"}
						helper="M-03: readiness enforced before concat. Live credit concat remains locked."
					>
						<button
							type="button"
							disabled={busy || !run}
							onClick={() => void handleAssemble()}
							className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2.5 text-[12px] font-bold text-slate-100 hover:bg-slate-800 disabled:opacity-40"
							data-testid="montage-assemble"
						>
							Build final video (dry-run gate)
						</button>
						{assembleNote ? (
							<p className="mt-2 text-[11px] text-emerald-300" data-testid="montage-assemble-note">
								{assembleNote}
							</p>
						) : null}
					</WorkflowStep>

					{error ? (
						<div
							className="rounded-lg border border-rose-800 bg-rose-950/40 px-3 py-2 text-[12px] text-rose-200"
							data-testid="montage-error"
						>
							{error}
						</div>
					) : null}
				</div>

				<aside className="min-h-0">
					<OperatorCockpit
						laneLabel="Montage · discrete"
						status={{
							label: busy ? "Working" : run ? "Run ready" : "Idle",
							state: busy ? "running" : run ? "online" : "idle",
						}}
						product={
							selectedProduct
								? {
										name:
											selectedProduct.product_short_name ||
											selectedProduct.raw_product_title ||
											selectedProduct.id,
										sub: selectedProduct.id,
								  }
								: undefined
						}
						planTitle="Discrete plan"
						plan={[
							{ k: "Hook", v: hookLabel, mono: true },
							{ k: "Background", v: backgroundLabel, mono: true },
							{
								k: "Run",
								v: run?.montage_run_id?.slice(0, 8) || "—",
								mono: true,
							},
							{
								k: "Packages",
								v: packagesReady ? String(packageCount) : "0",
								tone: packagesReady ? "good" : "muted",
							},
							{
								k: "Readiness",
								v: readiness ? (readiness.ok ? "READY" : "BLOCKED") : "—",
								tone: readiness?.ok ? "good" : "default",
							},
							{
								k: "Gen estimate",
								v: estimate?.summary || "—",
								mono: true,
							},
							{ k: "Path", v: "DISCRETE_MONTAGE", mono: true },
							{
								k: "Credit",
								v: creditConfirm
									? `CONFIRM ${estimate?.expected_video_generations ?? 0}`
									: "locked until confirm",
								tone: creditConfirm ? "default" : "good",
							},
						]}
						queueTitle="Execution state"
						generate={{
							label: estimate
								? "Confirm ops (no spend)"
								: run
									? "Refresh estimate"
									: "Start discrete path",
							disabled: !canOperate || busy,
							loading: busy,
							onClick: () => {
								if (!run) void handleStartRun();
								else if (estimate && creditConfirm) void handleAuthorize(true);
								else void handleRefreshEstimate();
							},
							note: "M-04: multi-scene live fire is a separate red CTA after checkbox confirm. Cockpit never auto-burns.",
						}}
						debug={
							<pre className="max-h-40 overflow-auto text-[10px] text-slate-400">
								{JSON.stringify(
									{
										settings_source: settings.source,
										run_id: run?.montage_run_id,
										run_ok: run?.ok,
										readiness_ok: readiness?.ok,
										packages_ready: packagesReady,
										estimate: estimate?.summary,
										credit_confirm: creditConfirm,
									},
									null,
									2,
								)}
							</pre>
						}

					/>
				</aside>
			</div>
		</div>
	);
}
