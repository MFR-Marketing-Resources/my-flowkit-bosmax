/**
 * Montage — discrete multi-scene operator workspace (V4 language).
 *
 * Hook/Background options come ONLY from creative-lane settings API (same SSOT
 * as Faceless). No local vocabulary arrays.
 *
 * Operator: Product → Hook/BG → Model+Duration → Scene Plan → Generate Montage
 * → Progress → Final Video. Raw backend ledger/authorize/bind/readiness controls
 * are hidden; the gated final-video action remains visible.
 * Credit fire requires explicit count confirm.
 */
import { useEffect, useMemo, useState } from "react";
import { useCreativeLaneSettings } from "../api/creativeLaneSettings";
import {
	assembleMontageRun,
	assembleMontageRunDryRun,
	authorizeMontageGeneration,
	checkMontageRunReadiness,
	createMontagePlan,
	createMontageRun,
	fetchMontageVideoCapability,
	fetchMontageGenerationEstimate,
	type MontageAuthorizeGenerationResponse,
	type MontageAssembleResponse,
	type MontageGenerationEstimate,
	type MontagePlanResponse,
	type MontageReadinessResponse,
	type MontageRunResponse,
} from "../api/montage";
import { fetchProductCatalog } from "../api/products";
import {
	WorkflowStep,
	type WorkflowStepStatus,
} from "../components/workflow";
import ResultsSidebar from "../components/workspace/ResultsSidebar";
import CopyArchitectureV2LaneCard from "../components/copywriting/CopyArchitectureV2LaneCard";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { Product } from "../types";
import {
	defaultEngine,
	modelsForSingle,
	resolveDurationChange,
	resolveSingleSelection,
	singleDurations,
	type VideoCapabilityMatrix,
} from "../utils/videoCapability";
import { collectMontageSessionResults } from "../utils/videoSessionResults";

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
	const [capabilityMatrix, setCapabilityMatrix] =
		useState<VideoCapabilityMatrix | null>(null);
	const [capabilityError, setCapabilityError] = useState<string | null>(null);
	const [videoModel, setVideoModel] = useState<string | null>(null);
	const [clipDuration, setClipDuration] = useState<number | null>(null);
	const [plan, setPlan] = useState<MontagePlanResponse | null>(null);
	const [run, setRun] = useState<MontageRunResponse | null>(null);
	const [readiness, setReadiness] = useState<MontageReadinessResponse | null>(
		null,
	);
	const [assembleNote, setAssembleNote] = useState<string | null>(null);
	const [assembleResult, setAssembleResult] =
		useState<MontageAssembleResponse | null>(null);
	const [finalCreditConfirm, setFinalCreditConfirm] = useState(false);
	const [estimate, setEstimate] = useState<MontageGenerationEstimate | null>(null);
	const [authNote, setAuthNote] = useState<string | null>(null);
	const [creditConfirm, setCreditConfirm] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [v4Open, setV4Open] = useState<Record<number, boolean>>({});
	const [v2CopyReady, setV2CopyReady] = useState(false);
	const sessionResults = useMemo(
		() => collectMontageSessionResults(run, assembleResult),
		[run, assembleResult],
	);

	useEffect(() => {
		void fetchProductCatalog(250, "GENERATION")
			.then((r) => setProducts(r.items || []))
			.catch(() => setProducts([]));
		void fetchMontageVideoCapability()
			.then((matrix) => {
				setCapabilityMatrix(matrix);
				setCapabilityError(null);
				const selection = resolveSingleSelection(
					defaultEngine(matrix),
					null,
					null,
				);
				setVideoModel(selection?.model ?? null);
				setClipDuration(selection?.durationSeconds ?? null);
			})
			.catch((err: unknown) => {
				setCapabilityMatrix(null);
				setVideoModel(null);
				setClipDuration(null);
				setCapabilityError(
					err instanceof Error
						? err.message
						: "Video capability authority unavailable",
				);
			});
	}, []);

	const hookLabel = labelOf(settings.hook.options, hookId);
	const backgroundLabel = labelOf(settings.background.options, backgroundId);

	const v4IsOpen = (index: number, status: WorkflowStepStatus) =>
		v4Open[index] ?? status === "active";
	const v4Toggle = (index: number, currentOpen: boolean) =>
		setV4Open((prev) => ({ ...prev, [index]: !currentOpen }));

	const engine = defaultEngine(capabilityMatrix);
	const durationOptions = singleDurations(engine);
	const modelOptions = modelsForSingle(engine, clipDuration ?? 0);
	const validSelection = resolveSingleSelection(
		engine,
		videoModel,
		clipDuration,
	);
	const canOperate =
		Boolean(selectedProduct) &&
		settingsAvailable &&
		Boolean(validSelection) &&
		v2CopyReady;
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
		setAssembleResult(null);
		setFinalCreditConfirm(false);
		setEstimate(null);
		setAuthNote(null);
		setCreditConfirm(false);
		try {
			if (!selectedProduct || !validSelection) return;
			const next = await createMontagePlan({
				product_id: selectedProduct.id,
				hook_id: hookId,
				background_id: backgroundId,
				product_media_id: selectedProduct.media_id ?? null,
				model: validSelection.model,
				duration_seconds: validSelection.durationSeconds,
				copy_v2_context: { lane: "MONTAGE" },
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
		setAssembleResult(null);
		setFinalCreditConfirm(false);
		setReadiness(null);
		setEstimate(null);
		setAuthNote(null);
		setCreditConfirm(false);
		try {
			if (!selectedProduct || !validSelection) return;
			const res = await createMontageRun({
				product_id: selectedProduct.id,
				hook_id: hookId,
				background_id: backgroundId,
				product_media_id: selectedProduct.media_id ?? null,
				model: validSelection.model,
				duration_seconds: validSelection.durationSeconds,
				copy_v2_context: { lane: "MONTAGE" },
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

	const handleGenerateMontage = () => {
		if (!run) {
			void handleStartRun();
			return;
		}
		if (!estimate) {
			void handleRefreshEstimate();
			return;
		}
		if (!creditConfirm) {
			setError("Confirm the current provider-operation count before generating.");
			return;
		}
		void handleAuthorize(false);
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
					expected_provider_operations:
						estimate.expected_provider_operations ??
						estimate.expected_video_generations,
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

	const handleAssemble = async (dryRun: boolean) => {
		if (!run?.montage_run_id) return;
		if (!dryRun && !finalCreditConfirm) {
			setError("Confirm the single final-concat provider operation before building.");
			return;
		}
		setBusy(true);
		setError(null);
		setAssembleNote(null);
		setAssembleResult(null);
		setFinalCreditConfirm(false);
		try {
			let effectiveReadiness = readiness;
			if (!dryRun && !effectiveReadiness) {
				effectiveReadiness = await checkMontageRunReadiness(run.montage_run_id);
				setReadiness(effectiveReadiness);
			}
			if (!dryRun && !effectiveReadiness?.ok) {
				throw new Error(
					effectiveReadiness?.detail ||
						"Final Montage video is blocked until every mandatory scene clip is ready.",
				);
			}
			const res = dryRun
				? await assembleMontageRunDryRun(run.montage_run_id)
				: await assembleMontageRun(run.montage_run_id, {
						dry_run: false,
						confirm_live_credit_burn: true,
					});
			setAssembleResult(res);
			setAssembleNote(
				res.ok
					? dryRun
						? `Final-timeline dry-run OK — clips: ${(res.readiness?.clip_media_ids || []).join(", ") || "none"}`
						: "Final Montage video completed and persisted."
					: "Assemble dry-run returned not-ok",
			);
			if (!dryRun) setFinalCreditConfirm(false);
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

			<CopyArchitectureV2LaneCard
				lane="MONTAGE"
				productId={selectedProduct?.id}
				execution={
					run?.config?.copy_architecture_v2 as
					| Record<string, unknown>
					| undefined
				}
				onReadyChange={setV2CopyReady}
			/>

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
								setAssembleResult(null);
								setFinalCreditConfirm(false);
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
						summary={
							validSelection
								? `${validSelection.model} · ${validSelection.durationSeconds}s / scene`
								: "Load the canonical video capability authority"
						}
						helper="Discrete SINGLE clips only — final length = N × clip duration (concat)."
					>
						{capabilityError ? (
							<div
								className="mb-2 text-[11px] text-rose-300"
								data-testid="montage-capability-unavailable"
							>
								Video capability authority unavailable — no local model/duration
								fallback is offered. {capabilityError}
							</div>
						) : null}
						<div className="grid gap-3 sm:grid-cols-2">
							<label className="space-y-1">
								<span className={labelClass}>Video model</span>
								<select
									className={selectClass}
									value={videoModel ?? ""}
									disabled={!engine || !modelOptions.length}
									onChange={(e) => setVideoModel(e.target.value)}
									data-testid="montage-model"
								>
									{modelOptions.map((modelOption) => (
										<option key={modelOption.ui_label} value={modelOption.ui_label}>
											{modelOption.ui_label}
										</option>
									))}
								</select>
							</label>
							<label className="space-y-1">
								<span className={labelClass}>Clip duration</span>
								<select
									className={selectClass}
									value={clipDuration ?? ""}
									disabled={!engine || !durationOptions.length}
									onChange={(e) => {
										const next = resolveDurationChange(
											engine,
											videoModel,
											Number(e.target.value),
										);
										setClipDuration(next?.durationSeconds ?? null);
										setVideoModel(next?.model ?? null);
									}}
									data-testid="montage-duration"
								>
									{durationOptions.map((d) => (
										<option key={d} value={d}>
											{d}s
										</option>
									))}
								</select>
							</label>
						</div>
</WorkflowStep>

					<WorkflowStep
						index={4}
						title="Plan scenes"
						status={sPlan}
						open={v4IsOpen(4, sPlan)}
						onToggleOpen={() => v4Toggle(4, v4IsOpen(4, sPlan))}
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
						index={5}
						title="Generate Montage"
						status={sExec}
						open={v4IsOpen(5, sExec)}
						onToggleOpen={() => v4Toggle(5, v4IsOpen(5, sExec))}
						summary={
							run
								? `${run.total_scenes} scene(s) · ${estimate?.summary || "operation estimate loading"}`
								: "Prepare the durable scene run, then confirm provider operations"
						}
						helper="One owner action starts the durable Montage pipeline. No provider call occurs until the explicit operation confirmation is checked."
					>
						<button
							type="button"
							disabled={!canOperate || busy}
							onClick={handleGenerateMontage}
							className="rounded-xl border border-v4-accent/40 bg-v4-accent/15 px-4 py-2.5 text-[12px] font-bold text-v4-accent-ink hover:bg-v4-accent/25 disabled:opacity-40"
							data-testid="montage-generate"
						>
							{busy
								? "Working…"
								: run && creditConfirm
									? "Generate Montage (credits)"
									: run
										? "Refresh operation estimate"
										: "Generate Montage"}
						</button>
						{estimate ? (
							<label className="mt-3 flex items-start gap-2 text-[11px] text-slate-200">
								<input
									type="checkbox"
									checked={creditConfirm}
									onChange={(e) => setCreditConfirm(e.target.checked)}
									data-testid="montage-credit-confirm-normal"
									className="mt-0.5"
								/>
								<span>
									Confirm {estimate.expected_provider_operations ?? estimate.expected_video_generations} provider operation(s): {estimate.expected_image_operations ?? 0} image + {estimate.expected_video_generations} video.
								</span>
							</label>
						) : null}
						{run ? (
							<ul className="mt-3 space-y-1 text-[11px] text-slate-300" data-testid="montage-scene-progress">
								{run.scenes.map((scene) => (
									<li key={scene.scene_id} className="rounded border border-slate-800 px-2 py-1">
										<span className="font-semibold text-slate-100">{scene.scene_id}</span>{" · "}{scene.status}
										{scene.video_media_id ? " · clip ready" : ""}
									</li>
								))}
							</ul>
						) : null}
					</WorkflowStep>

					<details className="rounded-xl border border-slate-800 bg-slate-950/50 p-3" data-testid="montage-debug">
						<summary className="cursor-pointer text-[11px] font-bold uppercase tracking-[0.16em] text-slate-500">
							Debug / Advanced lifecycle
						</summary>
						<div className="mt-3 space-y-3">
					<WorkflowStep
						index={6}
						title="Scene plan & prepare"
						status={sExec}
						open={v4IsOpen(6, sExec)}
						onToggleOpen={() => v4Toggle(6, v4IsOpen(6, sExec))}
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
						index={7}
						title="Authorize scene generation"
						status={sAuth}
						open={v4IsOpen(7, sAuth)}
						onToggleOpen={() => v4Toggle(7, v4IsOpen(7, sAuth))}
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
										<strong>
											{estimate.expected_provider_operations ?? estimate.expected_video_generations}
										</strong>{" "}
										provider operation(s): {estimate.expected_image_operations ?? 0} image +{" "}
										{estimate.expected_video_generations} video.
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
						index={8}
						title="Assembly readiness"
						status={sReady}
						open={v4IsOpen(8, sReady)}
						onToggleOpen={() => v4Toggle(8, v4IsOpen(8, sReady))}
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

						</div>
					</details>

					<WorkflowStep
						index={9}
						title="Final video"
						status={sAssemble}
						open={v4IsOpen(9, sAssemble)}
						onToggleOpen={() => v4Toggle(9, v4IsOpen(9, sAssemble))}
						summary={assembleNote || "Gated concat boundary — incomplete set never calls concat"}
						helper="All mandatory scene clips are checked immediately before the existing final-timeline concat path."
					>
						<button
							type="button"
							disabled={busy || !run}
							onClick={() => void handleAssemble(true)}
							className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2.5 text-[12px] font-bold text-slate-100 hover:bg-slate-800 disabled:opacity-40"
							data-testid="montage-assemble-preview"
						>
							Preview final timeline (no spend)
						</button>
						<label className="mt-3 flex items-start gap-2 text-[11px] text-slate-200">
							<input
								type="checkbox"
								checked={finalCreditConfirm}
								onChange={(e) => setFinalCreditConfirm(e.target.checked)}
								data-testid="montage-final-credit-confirm"
								className="mt-0.5"
							/>
							<span>
								Confirm one final-concat provider operation after the mandatory scene set is ready.
						</span>
						</label>
						<button
							type="button"
							disabled={busy || !run || !finalCreditConfirm}
							onClick={() => void handleAssemble(false)}
							className="mt-2 rounded-xl border border-rose-700/50 bg-rose-950/40 px-4 py-2.5 text-[12px] font-bold text-rose-100 hover:bg-rose-900/40 disabled:opacity-40"
							data-testid="montage-assemble-live"
							title="Runs the existing final-timeline concat, polls to terminal, retrieves and persists the final video"
						>
							Build final video (credits)
						</button>
						{assembleNote ? (
							<p className="mt-2 text-[11px] text-emerald-300" data-testid="montage-assemble-note">
								{assembleNote}
							</p>
						) : null}
						{typeof assembleResult?.concat?.final_media_id === "string" ? (
							<a
								href={`/api/flow/retrieved/${encodeURIComponent(String(assembleResult.concat.final_media_id))}`}
								className="mt-3 inline-flex rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-[12px] font-bold text-emerald-200"
								data-testid="montage-final-video"
							>
								Open final Montage video
							</a>
						) : null}
						{typeof assembleResult?.concat?.local_path === "string" ? (
							<p className="mt-2 text-[11px] text-slate-400">
								Saved artifact: {String(assembleResult.concat.local_path)}
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
					<ResultsSidebar
						results={sessionResults}
						generating={busy}
						mediaKind="video"
						libraryHref="/library/videos"
					/>
				</aside>
			</div>
		</div>
	);
}
