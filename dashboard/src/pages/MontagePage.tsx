/**
 * Montage — discrete multi-scene operator workspace (V4 language).
 *
 * Hook/Background options come ONLY from creative-lane settings API (same SSOT
 * as Faceless). No local vocabulary arrays.
 *
 * Execution: plan → execute-scenes (workspace packages) → readiness → assemble
 * dry-run. Live credit generate remains locked.
 */
import { useEffect, useMemo, useState } from "react";
import { useCreativeLaneSettings } from "../api/creativeLaneSettings";
import {
	assembleMontageDryRun,
	checkMontageAssemblyReadiness,
	createMontagePlan,
	executeMontageScenes,
	type MontageExecuteResponse,
	type MontagePlanResponse,
	type MontageReadinessResponse,
	type MontageScenePlan,
} from "../api/montage";
import { fetchProductCatalog } from "../api/products";
import {
	OperatorCockpit,
	ResolvedChip,
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
	const [plan, setPlan] = useState<MontagePlanResponse | null>(null);
	const [execution, setExecution] = useState<MontageExecuteResponse | null>(null);
	const [readiness, setReadiness] = useState<MontageReadinessResponse | null>(
		null,
	);
	const [assembleNote, setAssembleNote] = useState<string | null>(null);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [v4Open, setV4Open] = useState<Record<number, boolean>>({});

	useEffect(() => {
		void fetchProductCatalog(250, "GENERATION")
			.then((r) => setProducts(r.items || []))
			.catch(() => setProducts([]));
	}, []);

	const hookLabel = labelOf(settings.hook.options, hookId);
	const backgroundLabel = labelOf(settings.background.options, backgroundId);

	const v4IsOpen = (index: number, status: WorkflowStepStatus) =>
		v4Open[index] ?? status === "active";
	const v4Toggle = (index: number, currentOpen: boolean) =>
		setV4Open((prev) => ({ ...prev, [index]: !currentOpen }));

	const canOperate = Boolean(selectedProduct) && settingsAvailable;

	const sProduct: WorkflowStepStatus = selectedProduct ? "done" : "active";
	const sCreative: WorkflowStepStatus =
		selectedProduct && settingsAvailable ? "done" : selectedProduct ? "active" : "upcoming";
	const sPlan: WorkflowStepStatus = plan
		? "done"
		: canOperate
			? "active"
			: "upcoming";
	const sExec: WorkflowStepStatus = execution
		? execution.ok
			? "done"
			: "active"
		: plan
			? "active"
			: "upcoming";
	const sReady: WorkflowStepStatus = readiness
		? readiness.ok
			? "done"
			: "active"
		: execution
			? "active"
			: "upcoming";

	const handlePlan = async () => {
		if (!selectedProduct || !settingsAvailable) return;
		setBusy(true);
		setError(null);
		setReadiness(null);
		setExecution(null);
		setAssembleNote(null);
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

	const handleExecute = async () => {
		if (!selectedProduct || !settingsAvailable) return;
		setBusy(true);
		setError(null);
		setAssembleNote(null);
		try {
			const next = await executeMontageScenes({
				product_id: selectedProduct.id,
				hook_id: hookId,
				background_id: backgroundId,
				scene_context_override: `Montage strategy hook=${hookId}; environment=${backgroundId}`,
			});
			setExecution(next);
			if (!next.ok) {
				setError(next.detail || "Some scenes failed package prepare");
			}
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Execute scenes failed");
			setExecution(null);
		} finally {
			setBusy(false);
		}
	};

	const handleReadiness = async () => {
		if (!plan && !execution) return;
		setBusy(true);
		setError(null);
		try {
			const baseScenes = plan?.scenes ?? [];
			const jobs = execution?.scenes ?? [];
			const scenes = baseScenes.map((s: MontageScenePlan) => {
				const job = jobs.find((j) => j.scene_id === s.scene_id);
				const clip = job?.video_media_id || null;
				return {
					scene_id: s.scene_id,
					mandatory: true,
					reference_policy: s.reference_policy,
					product_media_id: s.product_media_id,
					reference_media_ids: s.reference_media_ids,
					clip_media_id: clip,
					image_ready: Boolean(job?.image_media_id || clip),
					video_ready: Boolean(clip),
					image_generation_required: s.image_generation_required,
					video_generation_required: s.video_generation_required,
				};
			});
			const report = await checkMontageAssemblyReadiness(scenes);
			setReadiness(report);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Readiness check failed");
		} finally {
			setBusy(false);
		}
	};

	const handleAssembleDryRun = async () => {
		if (!readiness?.ok || !readiness.clip_media_ids?.length) {
			setError("Assembly dry-run requires readiness PASS with clip ids");
			return;
		}
		setBusy(true);
		setError(null);
		try {
			const scenes = (plan?.scenes ?? []).map((s) => ({
				scene_id: s.scene_id,
				mandatory: true,
				reference_policy: s.reference_policy,
				product_media_id: s.product_media_id,
				reference_media_ids: s.reference_media_ids,
				clip_media_id:
					execution?.scenes.find((j) => j.scene_id === s.scene_id)?.video_media_id ||
					null,
				image_ready: true,
				video_ready: true,
				image_generation_required: false,
				video_generation_required: true,
			}));
			const out = await assembleMontageDryRun(scenes);
			setAssembleNote(
				out.ok
					? `Assemble dry-run OK · clips=${out.readiness.clip_media_ids.length}`
					: "Assemble dry-run failed",
			);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Assemble dry-run failed");
		} finally {
			setBusy(false);
		}
	};

	const sceneRows = useMemo(() => plan?.scenes ?? [], [plan]);
	const packagesReady =
		Boolean(execution?.scenes?.length) &&
		(execution?.scenes.every((s) => s.workspace_execution_package_id) ?? false);

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
					Storyboard beats route to existing scene/image/video primitives via
					workspace packages. Assembly is fail-closed. Live credit generate stays
					locked.
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
								setExecution(null);
								setReadiness(null);
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
							<label className="space-y-1">
								<span className={labelClass}>Hook</span>
								<select
									className={selectClass}
									value={hookId}
									onChange={(e) => setHookId(e.target.value)}
									disabled={!settingsAvailable}
									data-testid="montage-hook"
									data-settings-source={settings.source}
								>
									{settings.hook.options.map((o) => (
										<option key={o.id} value={o.id}>
											{o.label}
										</option>
									))}
								</select>
							</label>
							<label className="space-y-1">
								<span className={labelClass}>Background</span>
								<select
									className={selectClass}
									value={backgroundId}
									onChange={(e) => setBackgroundId(e.target.value)}
									disabled={!settingsAvailable}
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
						<div className="mt-3 flex flex-wrap gap-2">
							<ResolvedChip label="Hook" value={hookLabel} auto={hookId === "AUTO"} />
							<ResolvedChip
								label="Background"
								value={backgroundLabel}
								auto={backgroundId === "AUTO"}
							/>
							<ResolvedChip label="Path" value="Discrete montage" />
							<ResolvedChip label="SSOT" value={settings.source} />
						</div>
					</WorkflowStep>

					<WorkflowStep
						index={3}
						title="Scene plan"
						status={sPlan}
						open={v4IsOpen(3, sPlan)}
						onToggleOpen={() => v4Toggle(3, v4IsOpen(3, sPlan))}
						summary={
							plan
								? `${plan.scene_count} scenes · ${plan.assembly_path}`
								: "Build discrete scenes from storyboard beats"
						}
					>
						<button
							type="button"
							disabled={!canOperate || busy}
							onClick={() => void handlePlan()}
							className="rounded-xl border border-v4-accent/40 bg-v4-accent/15 px-4 py-2.5 text-[12px] font-bold text-v4-accent-ink hover:bg-v4-accent/25 disabled:opacity-40"
							data-testid="montage-plan"
						>
							{busy && !plan ? "Planning…" : "Build scene plan"}
						</button>
						{sceneRows.length ? (
							<ul className="mt-3 space-y-2" data-testid="montage-scene-list">
								{sceneRows.map((s) => (
									<li
										key={s.scene_id}
										className="rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-2 text-[12px]"
									>
										<div className="flex flex-wrap items-center justify-between gap-2">
											<span className="font-bold text-slate-100">{s.scene_id}</span>
											<span className="rounded-full border border-slate-700 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-400">
												{s.route} · {s.reference_policy}
											</span>
										</div>
										<div className="mt-1 text-slate-400">
											{s.role || s.beat_id}: {s.objective || s.visual_action || "—"}
										</div>
										<div className="mt-1 font-mono text-[10px] text-slate-500">
											{s.transport_mode}/{s.source_mode}
											{s.image_generation_required ? " · image-first" : ""}
											{s.video_generation_required ? " · video" : " · inherit"}
										</div>
									</li>
								))}
							</ul>
						) : null}
					</WorkflowStep>

					<WorkflowStep
						index={4}
						title="Execute scenes (packages)"
						status={sExec}
						open={v4IsOpen(4, sExec)}
						onToggleOpen={() => v4Toggle(4, v4IsOpen(4, sExec))}
						summary={
							execution
								? `${execution.scenes.filter((s) => s.workspace_execution_package_id).length}/${execution.scene_count} packages`
								: "Create workspace packages via existing factory"
						}
						helper="R2 operational path — no credit auto-fire. Live generate uses /api/flow/generate per package."
					>
						<button
							type="button"
							disabled={!canOperate || busy}
							onClick={() => void handleExecute()}
							className="rounded-xl border border-v4-accent/40 bg-v4-accent/15 px-4 py-2.5 text-[12px] font-bold text-v4-accent-ink hover:bg-v4-accent/25 disabled:opacity-40"
							data-testid="montage-execute"
						>
							{busy ? "Preparing…" : "Prepare scene packages"}
						</button>
						{execution ? (
							<ul className="mt-3 space-y-1 text-[11px] text-slate-300" data-testid="montage-exec-list">
								{execution.scenes.map((s) => (
									<li key={s.scene_id} className="font-mono">
										{s.scene_id}: {s.status}
										{s.workspace_execution_package_id
											? ` · ${s.workspace_execution_package_id}`
											: ""}
										{s.error_code ? ` · ${s.error_code}` : ""}
									</li>
								))}
							</ul>
						) : null}
					</WorkflowStep>

					<WorkflowStep
						index={5}
						title="Assembly readiness + dry-run"
						status={sReady}
						open={v4IsOpen(5, sReady)}
						onToggleOpen={() => v4Toggle(5, v4IsOpen(5, sReady))}
						summary={
							readiness
								? readiness.ok
									? "READY for discrete concat"
									: readiness.code || "BLOCKED"
								: "Check fail-closed gates"
						}
						helper="Incomplete mandatory sets never reach concat (HTTP 409 on /assemble)."
					>
						<div className="flex flex-wrap gap-2">
							<button
								type="button"
								disabled={(!plan && !execution) || busy}
								onClick={() => void handleReadiness()}
								className="rounded-xl border border-slate-700 bg-slate-900 px-4 py-2.5 text-[12px] font-bold text-slate-100 hover:border-slate-500 disabled:opacity-40"
								data-testid="montage-readiness"
							>
								Check assembly readiness
							</button>
							<button
								type="button"
								disabled={!readiness?.ok || busy}
								onClick={() => void handleAssembleDryRun()}
								className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-4 py-2.5 text-[12px] font-bold text-emerald-100 hover:bg-emerald-500/20 disabled:opacity-40"
								data-testid="montage-assemble-dry"
							>
								Assemble dry-run
							</button>
						</div>
						{readiness ? (
							<div
								className={`mt-3 rounded-xl border px-3 py-2 text-[12px] ${
									readiness.ok
										? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
										: "border-amber-500/30 bg-amber-500/10 text-amber-100"
								}`}
								data-testid="montage-readiness-report"
							>
								<div className="font-bold">
									{readiness.ok
										? "Assembly READY"
										: readiness.blocked_incomplete_scene_set ||
											readiness.code ||
											"BLOCKED"}
								</div>
								<div className="mt-1 opacity-90">{readiness.detail}</div>
							</div>
						) : null}
						{assembleNote ? (
							<div className="mt-2 text-[11px] text-emerald-200" data-testid="montage-assemble-note">
								{assembleNote}
							</div>
						) : null}
					</WorkflowStep>

					{error ? (
						<div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[12px] text-rose-100">
							{error}
						</div>
					) : null}
				</div>

				<OperatorCockpit
					laneLabel="Montage"
					status={{
						label: readiness?.ok
							? "Ready"
							: packagesReady
								? "Packaged"
								: plan
									? "Planned"
									: selectedProduct
										? "Online"
										: "Idle",
						state: readiness?.ok
							? "done"
							: plan
								? "online"
								: selectedProduct
									? "online"
									: "idle",
					}}
					product={
						selectedProduct
							? {
									name: selectedProduct.raw_product_title || selectedProduct.id,
									sub: selectedProduct.id,
								}
							: undefined
					}
					plan={[
						{ k: "Lane", v: "Montage", tone: "good" },
						{ k: "Hook", v: hookLabel },
						{ k: "Background", v: backgroundLabel },
						{ k: "SSOT", v: settings.source, mono: true },
						{
							k: "Scenes",
							v: plan ? String(plan.scene_count) : "—",
							mono: true,
						},
						{
							k: "Packages",
							v: execution
								? String(
										execution.scenes.filter((s) => s.workspace_execution_package_id)
											.length,
									)
								: "—",
							mono: true,
						},
						{
							k: "Assembly",
							v: readiness
								? readiness.ok
									? "READY"
									: readiness.code || "BLOCKED"
								: "—",
							tone: readiness?.ok ? "good" : "muted",
						},
						{ k: "Engine", v: "Discrete scenes", mono: true },
					]}
					generate={{
						label: packagesReady
							? "Credit generate locked — use /api/flow/generate per package"
							: "Generate locked until packages + owner credit auth",
						note: "Backend supports plan → execute-scenes → readiness → assemble dry-run. Live concat/generate require owner credit authorization.",
						disabled: true,
					}}
					debug={
						<pre className="overflow-auto text-[10px] text-slate-400">
							{JSON.stringify(
								{
									hookId,
									backgroundId,
									settings_source: settings.source,
									settings_available: settingsAvailable,
									scene_count: plan?.scene_count,
									execution_ok: execution?.ok,
									readiness_ok: readiness?.ok,
									code: readiness?.code,
								},
								null,
								2,
							)}
						</pre>
					}
				/>
			</div>
		</div>
	);
}
