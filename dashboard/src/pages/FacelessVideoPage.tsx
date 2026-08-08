/**
 * Faceless Video operator lane (V4 language).
 *
 * Separate UI, shared engine: product + scene/product image → F2V single clip
 * via POST /api/flow/generate. Never auto-fires credit-bearing generation.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
	prepareFacelessPackage,
	useCreativeLaneSettings,
	type ResolvedLaneSetting,
} from "../api/creativeLaneSettings";
import { fetchProductCatalog } from "../api/products";
import {
	OperatorCockpit,
	ResolvedChip,
	WorkflowStep,
	type WorkflowStepStatus,
} from "../components/workflow";
import CanonicalReferenceBindingControls, {
	EMPTY_BINDING,
	type CanonicalReferenceBinding,
} from "../components/workspace/CanonicalReferenceBindingControls";
import SearchableProductSelect from "../components/workspace/SearchableProductSelect";
import type { Product, WorkspaceExecutionPackage } from "../types";
import {
	buildFacelessGenerateBody,
	facelessPrepareBlockers,
	optionLabel,
} from "../faceless/facelessLane";

type NoticeTone = "info" | "success" | "warning" | "error";

interface Notice {
	tone: NoticeTone;
	title: string;
	detail: string;
	requestId: string | null;
}

const selectClass =
	"w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100";
const labelClass = "text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500";

export default function FacelessVideoPage() {
	const { settings, loading: settingsLoading, error: settingsError, available: settingsAvailable, reload: reloadSettings } = useCreativeLaneSettings();
	const [resolvedHook, setResolvedHook] = useState<ResolvedLaneSetting | null>(null);
	const [resolvedBackground, setResolvedBackground] = useState<ResolvedLaneSetting | null>(null);
	const [products, setProducts] = useState<Product[]>([]);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
	const [hookId, setHookId] = useState("AUTO");
	const [backgroundId, setBackgroundId] = useState("AUTO");
	const [binding, setBinding] = useState<CanonicalReferenceBinding>(EMPTY_BINDING);
	const [workspacePackage, setWorkspacePackage] =
		useState<WorkspaceExecutionPackage | null>(null);
	const [isPreparing, setIsPreparing] = useState(false);
	const [isExecuting, setIsExecuting] = useState(false);
	const [notice, setNotice] = useState<Notice | null>(null);
	const [completedUrl, setCompletedUrl] = useState<string | null>(null);
	const [v4Open, setV4Open] = useState<Record<number, boolean>>({});
	const executionInFlightRef = useRef(false);
	const pollTimerRef = useRef<number | null>(null);

	useEffect(() => {
		void fetchProductCatalog(250, "GENERATION")
			.then((res) => setProducts(res.items || []))
			.catch(() => setProducts([]));
	}, []);

	useEffect(() => {
		return () => {
			if (pollTimerRef.current != null) window.clearTimeout(pollTimerRef.current);
		};
	}, []);

	const blockers = useMemo(() => {
		const base = facelessPrepareBlockers({
			productId: selectedProduct?.id,
			startFrameAssetId: binding.startFrameAssetId,
		});
		if (!settingsAvailable) {
			return [
				"Hook/Background settings unavailable — retry when API is up",
				...base,
			];
		}
		return base;
	}, [selectedProduct?.id, binding.startFrameAssetId, settingsAvailable]);

	const hookLabel = optionLabel(settings.hook.options, hookId);
	const backgroundLabel = optionLabel(settings.background.options, backgroundId);

	const v4IsOpen = (index: number, status: WorkflowStepStatus) =>
		v4Open[index] ?? status === "active";
	const v4Toggle = (index: number, currentOpen: boolean) =>
		setV4Open((prev) => ({ ...prev, [index]: !currentOpen }));

	const sProduct: WorkflowStepStatus = selectedProduct ? "done" : "active";
	const sCreative: WorkflowStepStatus = selectedProduct
		? blockers.length === 0
			? "done"
			: "active"
		: "upcoming";
	const sImage: WorkflowStepStatus = !selectedProduct
		? "upcoming"
		: binding.startFrameAssetId
			? "done"
			: "active";
	const sPrepare: WorkflowStepStatus = workspacePackage
		? "done"
		: blockers.length === 0
			? "active"
			: "upcoming";
	const sGenerate: WorkflowStepStatus = workspacePackage ? "active" : "upcoming";

	const handlePrepare = async () => {
		if (!selectedProduct || blockers.length) {
			setNotice({
				tone: "error",
				title: "Cannot prepare",
				detail: blockers[0] || "Missing required inputs",
				requestId: null,
			});
			return;
		}
		setIsPreparing(true);
		setNotice({
			tone: "info",
			title: "Preparing faceless package",
			detail: "Compiling through the shared workspace execution package path…",
			requestId: null,
		});
		try {
			const prepared = await prepareFacelessPackage({
				product_id: selectedProduct.id,
				start_frame_asset_id: binding.startFrameAssetId || "",
				end_frame_asset_id: binding.endFrameAssetId,
				hook_id: hookId,
				background_id: backgroundId,
				duration_seconds: 8,
				copy_fallback_confirmed: true,
			});
			const pkg = (prepared.package || {}) as unknown as WorkspaceExecutionPackage;
			if (!pkg.workspace_execution_package_id || !pkg.prompt_text) {
				throw new Error("Prepare returned incomplete package");
			}
			setWorkspacePackage(pkg);
			setResolvedHook(prepared.resolution?.hook ?? null);
			setResolvedBackground(prepared.resolution?.background ?? null);
			const h = prepared.resolution?.hook;
			const b = prepared.resolution?.background;
			setNotice({
				tone: "success",
				title: "Faceless package ready",
				detail: `Package ${pkg.workspace_execution_package_id} · Hook ${h?.setting_id || hookId} (${h?.resolution || "?"}) · BG ${b?.setting_id || backgroundId}`,
				requestId: pkg.workspace_execution_package_id,
			});
		} catch (err: unknown) {
			setNotice({
				tone: "error",
				title: "Prepare failed",
				detail: err instanceof Error ? err.message : "Failed to prepare package",
				requestId: null,
			});
		} finally {
			setIsPreparing(false);
		}
	};

	const pollJob = async (jobId: string, requestId: string) => {
		try {
			const response = await fetch(`/api/flow/generate-job/${jobId}`);
			if (!response.ok) throw new Error(`Job HTTP ${response.status}`);
			const job = await response.json();
			const status = job.status as string;
			if (status === "DONE") {
				const mediaId = job.media_id ?? job.video_media_id ?? "";
				if (mediaId) setCompletedUrl(`/api/flow/retrieved/${mediaId}`);
				setNotice({
					tone: "success",
					title: "Faceless clip done",
					detail: `Saved ${job.size_mb ?? "?"}MB · media ${mediaId}`,
					requestId,
				});
				setIsExecuting(false);
				executionInFlightRef.current = false;
				return;
			}
			if (status === "FAILED" || status === "GENERATED_BUT_UNRETRIEVED") {
				setNotice({
					tone: "error",
					title: "Faceless generation failed",
					detail: job.error || status,
					requestId,
				});
				setIsExecuting(false);
				executionInFlightRef.current = false;
				return;
			}
			pollTimerRef.current = window.setTimeout(() => {
				void pollJob(jobId, requestId);
			}, 2500);
		} catch (err: unknown) {
			setNotice({
				tone: "error",
				title: "Poll failed",
				detail: err instanceof Error ? err.message : "Job poll error",
				requestId,
			});
			setIsExecuting(false);
			executionInFlightRef.current = false;
		}
	};

	const handleGenerate = async () => {
		if (executionInFlightRef.current) return;
		if (!workspacePackage?.prompt_text) {
			setNotice({
				tone: "warning",
				title: "Prepare first",
				detail: "Prepare the faceless package before generating.",
				requestId: null,
			});
			return;
		}
		if (blockers.length) {
			setNotice({
				tone: "error",
				title: "Blocked",
				detail: blockers[0],
				requestId: null,
			});
			return;
		}
		executionInFlightRef.current = true;
		setIsExecuting(true);
		setCompletedUrl(null);
		const requestId = `faceless_${crypto.randomUUID().replace(/-/g, "").slice(0, 8)}`;
		setNotice({
			tone: "info",
			title: "Submitting faceless clip",
			detail: "One-door F2V generate — spends credits. Needs open Flow editor.",
			requestId,
		});
		try {
			// F-05: one-door GenerateRequest resolves refs via startAsset / image_media_ids
			// — package id alone does NOT carry the operator-selected frame.
			const generateBody = buildFacelessGenerateBody({
				prompt: workspacePackage.prompt_text,
				productId: selectedProduct?.id ?? workspacePackage.product_id,
				workspacePackage,
				startFrameAssetId: binding.startFrameAssetId,
				endFrameAssetId: binding.endFrameAssetId,
			});
			const response = await fetch("/api/flow/generate", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(generateBody),
			});
			if (!response.ok) {
				const text = await response.text();
				throw new Error(text || `HTTP ${response.status}`);
			}
			const data = await response.json();
			const jobId = data.job_id || data.id;
			if (!jobId) throw new Error("No job_id returned");
			void pollJob(String(jobId), requestId);
		} catch (err: unknown) {
			setNotice({
				tone: "error",
				title: "Generate failed",
				detail: err instanceof Error ? err.message : "Generate request failed",
				requestId,
			});
			setIsExecuting(false);
			executionInFlightRef.current = false;
		}
	};

	const noticeToneClass =
		notice?.tone === "success"
			? "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"
			: notice?.tone === "error"
				? "border-rose-500/30 bg-rose-500/10 text-rose-100"
				: notice?.tone === "warning"
					? "border-amber-500/30 bg-amber-500/10 text-amber-100"
					: "border-sky-500/30 bg-sky-500/10 text-sky-100";

	return (
		<div
			className="flex h-full min-h-0 flex-col gap-4 p-4 md:p-6"
			data-testid="faceless-workflow"
			data-variant="v4"
			data-mode="FACELESS"
		>
			<header className="flex flex-wrap items-end justify-between gap-3">
				<div>
					<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-v4-accent">
						Faceless Video
					</div>
					<h1 className="text-xl font-bold text-slate-100">
						Product image → one short clip
					</h1>
					<p className="mt-1 max-w-2xl text-[12px] text-slate-400">
						True faceless (no presenter). Reuses the canonical F2V one-door —
						no duplicate engine. Credits spent only when you press Generate.
					</p>
				</div>
				{settingsLoading ? (
					<span className="text-[11px] text-slate-500">Loading settings…</span>
				) : null}
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
								setWorkspacePackage(null);
								setCompletedUrl(null);
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
						helper="Controlled settings only. Hook is strategy — not a claim license. Background is environment only."
					>
						<div className="grid gap-3 sm:grid-cols-2">
							{!settingsAvailable ? (
							<div
								className="sm:col-span-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-200"
								data-testid="faceless-settings-unavailable"
							>
								Settings unavailable
								{settingsError ? `: ${settingsError}` : ""}.{" "}
								<button
									type="button"
									className="underline"
									onClick={() => reloadSettings()}
									data-testid="faceless-settings-retry"
								>
									Retry
								</button>
							</div>
						) : null}
						<label className="space-y-1">
							<span className={labelClass}>Hook</span>
							<select
								className={selectClass}
								value={hookId}
								onChange={(e) => {
									setHookId(e.target.value);
									setWorkspacePackage(null);
								}}
								data-testid="faceless-hook"
								disabled={!settingsAvailable}
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
									onChange={(e) => {
										setBackgroundId(e.target.value);
										setWorkspacePackage(null);
									}}
									data-testid="faceless-background"
									disabled={!settingsAvailable}
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
							<ResolvedChip
								label="Hook"
								value={
									resolvedHook
										? `${resolvedHook.setting_id} · ${resolvedHook.display_label}`
										: hookLabel
								}
								auto={hookId === "AUTO"}
							/>
							<ResolvedChip
								label="Background"
								value={
									resolvedBackground
										? `${resolvedBackground.setting_id} · ${resolvedBackground.display_label}`
										: backgroundLabel
								}
								auto={backgroundId === "AUTO"}
							/>
							<ResolvedChip label="Presence" value="Faceless" />
							<ResolvedChip label="Transport" value="F2V · FRAMES" />
						</div>
					</WorkflowStep>

					<WorkflowStep
						index={3}
						title="Product / scene image"
						status={sImage}
						open={v4IsOpen(3, sImage)}
						onToggleOpen={() => v4Toggle(3, v4IsOpen(3, sImage))}
						summary={
							binding.startFrameAssetId
								? "Start frame bound"
								: "Start frame required"
						}
						helper="Image-first: bind the plate that will be animated into one clip."
					>
						<CanonicalReferenceBindingControls
							mode="F2V"
							productId={selectedProduct?.id ?? null}
							binding={binding}
							onChange={(next) => {
								setBinding(next);
								setWorkspacePackage(null);
							}}
						/>
					</WorkflowStep>

					<WorkflowStep
						index={4}
						title="Prepare"
						status={sPrepare}
						open={v4IsOpen(4, sPrepare)}
						onToggleOpen={() => v4Toggle(4, v4IsOpen(4, sPrepare))}
						summary={
							workspacePackage
								? "Package ready"
								: blockers.length
									? "Blocked"
									: "Compile final prompt"
						}
						helper="Credit-free prepare through the shared execution package path."
					>
						{blockers.length ? (
							<ul className="mb-3 list-disc space-y-1 pl-4 text-[12px] text-amber-100">
								{blockers.map((b) => (
									<li key={b}>{b}</li>
								))}
							</ul>
						) : null}
						<button
							type="button"
							disabled={Boolean(blockers.length) || isPreparing || !selectedProduct}
							onClick={() => void handlePrepare()}
							className="rounded-xl border border-v4-accent/40 bg-v4-accent/15 px-4 py-2.5 text-[12px] font-bold text-v4-accent-ink hover:bg-v4-accent/25 disabled:cursor-not-allowed disabled:opacity-40"
							data-testid="faceless-prepare"
						>
							{isPreparing ? "Preparing…" : "Prepare final prompt"}
						</button>
						{workspacePackage?.prompt_text ? (
							<pre className="mt-3 max-h-40 overflow-auto rounded-lg border border-slate-800 bg-slate-950/80 p-3 text-[11px] text-slate-300 whitespace-pre-wrap">
								{workspacePackage.prompt_text}
							</pre>
						) : null}
					</WorkflowStep>

					<WorkflowStep
						index={5}
						title="Generate video"
						status={sGenerate}
						open={v4IsOpen(5, sGenerate)}
						onToggleOpen={() => v4Toggle(5, v4IsOpen(5, sGenerate))}
						summary={isExecuting ? "Generating…" : completedUrl ? "Done" : "Operator gate"}
						helper="Credits are spent only here. Never auto-fired."
						collapsible={false}
					>
						<button
							type="button"
							disabled={!workspacePackage?.prompt_text || isExecuting || blockers.length > 0}
							onClick={() => void handleGenerate()}
							className="w-full rounded-xl bg-gradient-to-br from-v4-accent to-v4-auto px-4 py-3 text-[13px] font-bold text-slate-950 shadow-lg shadow-v4-accent/20 transition-opacity hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
							data-testid="faceless-generate"
						>
							{isExecuting
								? "Generating…"
								: "▶ Generate 1 faceless clip · 8s"}
						</button>
						<p className="mt-2 text-[11px] text-slate-500">
							Fires one video through Google Flow (F2V start-frame path). Needs
							an open, warmed-up Flow editor tab.
						</p>
						{completedUrl ? (
							<video
								className="mt-3 max-h-64 w-full rounded-xl border border-slate-800 bg-black"
								src={completedUrl}
								controls
								data-testid="faceless-result-video"
							/>
						) : null}
					</WorkflowStep>

					{notice ? (
						<div
							className={`rounded-xl border px-3 py-2 text-[12px] ${noticeToneClass}`}
							data-testid="faceless-notice"
						>
							<div className="font-bold">{notice.title}</div>
							<div className="opacity-90">{notice.detail}</div>
						</div>
					) : null}
				</div>

				<OperatorCockpit
					laneLabel="Faceless Video"
					status={{
						label: isExecuting
							? "Running"
							: completedUrl
								? "Done"
								: selectedProduct
									? "Online"
									: "Idle",
						state: isExecuting
							? "running"
							: completedUrl
								? "done"
								: selectedProduct
									? "online"
									: "idle",
					}}
					product={
						selectedProduct
							? {
									name:
										selectedProduct.raw_product_title || selectedProduct.id,
									sub: selectedProduct.id,
								}
							: undefined
					}
					plan={[
						{ k: "Lane", v: "Faceless", tone: "good" },
						{ k: "Hook", v: hookLabel, mono: hookId !== "AUTO" },
						{ k: "Background", v: backgroundLabel },
						{
							k: "Image",
							v: binding.startFrameAssetId ? "Bound" : "Required",
							tone: binding.startFrameAssetId ? "good" : "muted",
						},
						{
							k: "Package",
							v: workspacePackage ? "Ready" : "—",
							tone: workspacePackage ? "good" : "muted",
						},
						{ k: "Engine", v: "F2V one-door", mono: true },
					]}
					generate={{
						label: isExecuting
							? "Generating…"
							: "▶ Generate 1 faceless clip",
						note: "Credits only on Generate. Prepare is free.",
						disabled:
							!workspacePackage?.prompt_text ||
							isExecuting ||
							blockers.length > 0,
						loading: isExecuting,
						onClick: () => void handleGenerate(),
					}}
					debug={
						<pre className="overflow-auto text-[10px] text-slate-400">
							{JSON.stringify(
								{
									hookId,
									backgroundId,
									startFrame: binding.startFrameAssetId,
									packageId: workspacePackage?.workspace_execution_package_id,
									settingsSource: settings.source,
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
