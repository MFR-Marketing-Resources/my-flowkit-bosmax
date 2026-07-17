/**
 * RPA Production Studio — the user-facing T2V generation studio (MVP).
 *
 * RPA Queue Control proved the machinery (bridge/approve/enqueue/dry-run/live gate),
 * but it reads like a debug panel: it starts from an execution-package handle, not a
 * product, and exposes every internal step. This page is the same PROVEN pipeline,
 * re-presented as a studio a normal user can drive: pick a product, configure T2V,
 * prepare, validate, run one live job, see the result.
 *
 * It REUSES the exact backend contract and safety gates — no new server routes, no
 * weakened guards. In particular the live door is the same one-serial T2V gate
 * (live_gate=ONE_SERIAL_T2V + confirmation phrase), and O4 duplicate protection is
 * untouched. T2V is the only wired lane; F2V/I2V/Hybrid/IMG and bulk are rendered as
 * explicitly locked with the reason.
 */
import {
	AlertTriangle,
	CheckCircle2,
	Flame,
	Image as ImageIcon,
	Layers,
	Loader2,
	Lock,
	PackageCheck,
	Play,
	RefreshCw,
	Search,
	Sparkles,
	Video,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchProductCatalog, searchProducts } from "../api/products";
import {
	approvePackages,
	createProductionRun,
	fetchVideoModels,
	getProductionRun,
	LIVE_CONFIRM_PHRASE,
	LIVE_GATE_ONE_SERIAL_T2V,
	startProductionRun,
	type VideoModelInfo,
} from "../api/productionQueue";
import { createT2VGenerationPackage } from "../api/workspaceGenerationPackages";
import type { Product } from "../types";

const ASPECTS = ["9:16", "16:9", "1:1"];
const POLL_MS = 5000;
const TERMINAL_STATUSES = new Set(["GENERATED", "DOWNLOADED", "FAILED", "CANCELLED"]);

/** Future lanes — rendered, never wired. The reason is shown so a user is not left guessing. */
const LOCKED_MODES = [
	{ key: "F2V", label: "Frames → Video", icon: Layers,
	  reason: "Needs a product image uploaded to Google Flow first — that upload path is not yet wired into this studio." },
	{ key: "I2V", label: "Image → Video", icon: Video,
	  reason: "Needs uploaded Flow reference media; the RPA upload chain is not proven yet." },
	{ key: "HYBRID", label: "Hybrid", icon: Sparkles,
	  reason: "Runs on the F2V engine, so it inherits the same media-upload requirement." },
	{ key: "IMG", label: "Image / Poster", icon: ImageIcon,
	  reason: "A separate image lane, not part of the T2V video studio MVP." },
];

interface DryRunItem {
	package_id?: string;
	ok?: boolean;
	blockers?: string[];
	logical_mode?: string;
	model?: string | null;
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
}
type Stage = "IDLE" | "PREPARED" | "VALIDATED" | "LIVE_SUBMITTED";

/** Turn a raw backend failure code into a plain sentence a user can act on. */
function explainFailure(raw: string | null | undefined): string {
	const s = String(raw ?? "");
	if (!s) return "The job failed without a reason.";
	if (s.includes("RATE_LIMITED")) return "Google's anti-abuse rate limiter blocked the request before approval. No credits were spent. Wait ~1–2 hours and try again — do not hammer retries.";
	if (s.includes("CAPTCHA_FAILED")) return "The Flow tab is stale/cold, so the extension could not reach the page. Reload the extension and the Flow tab, open the project, then retry. No credits were spent.";
	if (s.includes("NO_OPEN_EDITOR")) return "No Google Flow project editor is open in the controlled tab. Open the target Flow project first.";
	if (s.includes("OUTPUT_IDENTITY_NOT_CAPTURED")) return "The video generated but its identity could not be captured, so it cannot be bound to this job. This is a capture gap, not a lost video.";
	if (s.includes("GENERATED_BUT_UNRETRIEVED")) return "The video generated (credits spent) but could not be retrieved/bound in time. It exists in Flow but is not registered here.";
	if (s.includes("OUTPUT_CORRELATION_UNAVAILABLE") || s.includes("IDENTITY_MISMATCH")) return "A finished video was found but could not be deterministically proven to belong to this job, so it was refused. Nothing was registered.";
	return s;
}

export default function RpaProductionStudioPage() {
	// ── product selection ──
	const [query, setQuery] = useState("");
	const [products, setProducts] = useState<Product[]>([]);
	const [loadingProducts, setLoadingProducts] = useState(true);
	const [productsError, setProductsError] = useState(false);
	const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);

	// ── config ──
	const [models, setModels] = useState<VideoModelInfo[]>([]);
	const [model, setModel] = useState<string>("");
	const [duration, setDuration] = useState<number>(8);
	const [aspect, setAspect] = useState<string>("9:16");

	// ── pipeline ──
	const [busy, setBusy] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [wgpId, setWgpId] = useState<string | null>(null);
	const [runId, setRunId] = useState<string | null>(null);
	const [report, setReport] = useState<DryRunReport | null>(null);
	const [stage, setStage] = useState<Stage>("IDLE");

	// ── live gate ──
	const [phrase, setPhrase] = useState("");
	const [liveSubmitted, setLiveSubmitted] = useState(false);
	const [liveError, setLiveError] = useState<string | null>(null);
	const [jobItem, setJobItem] = useState<RunItem | null>(null);
	const [runStatus, setRunStatus] = useState<string | null>(null);
	const pollRef = useRef<number | null>(null);

	const loadProducts = useCallback(async (q: string) => {
		setLoadingProducts(true);
		setProductsError(false);
		try {
			const res = q.trim() ? await searchProducts(q.trim(), 25, "GENERATION") : await fetchProductCatalog(40, "GENERATION");
			// A T2V job refuses fastmoss reference-only products server-side; don't offer them.
			setProducts((res.items ?? []).filter((p) => !p.reference_only));
		} catch {
			setProductsError(true);
		} finally {
			setLoadingProducts(false);
		}
	}, []);

	useEffect(() => {
		void loadProducts("");
		void fetchVideoModels()
			.then((r) => {
				setModels(r.models ?? []);
				const def = (r.models ?? []).find((m) => m.key === r.default || m.ui_label === r.default) ?? r.models?.[0];
				if (def) {
					setModel(def.ui_label);
					if (def.default_duration_s) setDuration(def.default_duration_s);
				}
			})
			.catch(() => setModels([]));
	}, [loadProducts]);

	const selectedModelInfo = useMemo(() => models.find((m) => m.ui_label === model), [models, model]);
	const durationOptions = selectedModelInfo?.allowed_durations_s ?? [duration];

	/** Reset the whole pipeline when the product or config changes — a stale run must never be firable. */
	const resetPipeline = useCallback(() => {
		setWgpId(null);
		setRunId(null);
		setReport(null);
		setStage("IDLE");
		setError(null);
		setPhrase("");
		setLiveSubmitted(false);
		setLiveError(null);
		setJobItem(null);
		setRunStatus(null);
	}, []);

	const pickProduct = (p: Product) => {
		setSelectedProduct(p);
		resetPipeline();
	};

	/** Prepare = create the T2V package, approve it, enqueue it. All no-credit. */
	const handlePrepare = async () => {
		if (!selectedProduct) return;
		setBusy("prepare");
		setError(null);
		try {
			const pkg = await createT2VGenerationPackage({
				product_id: selectedProduct.id,
				generation_mode: "SINGLE",
				duration_seconds: duration,
			});
			const wgp = pkg.workspace_generation_package_id;
			const approve = await approvePackages([wgp]);
			if (!approve.results?.[0]?.ok) {
				setError(`Could not approve the package: ${approve.results?.[0]?.error ?? "unknown"}`);
				return;
			}
			const run = await createProductionRun({ package_ids: [wgp], model, aspect, count: 1 });
			setWgpId(wgp);
			setRunId(run.production_run_id);
			setStage("PREPARED");
		} catch (e) {
			const msg = e instanceof Error ? e.message : String(e);
			setError(
				/approved|package/i.test(msg)
					? `This product has no approved T2V package yet, so a T2V job cannot be prepared. Approve a product package first. (${msg})`
					: `Prepare failed: ${msg}`,
			);
		} finally {
			setBusy(null);
		}
	};

	/** Dry run — hard-coded false; no code path here can pass true, so no credit can burn from validation. */
	const handleValidate = async () => {
		if (!runId) return;
		setBusy("validate");
		setError(null);
		try {
			const res = await startProductionRun(runId, false);
			setReport(res.report ?? null);
			setStage("VALIDATED");
			await refresh(runId, true);
		} catch (e) {
			setError(`Validation failed: ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			setBusy(null);
		}
	};

	const refresh = useCallback(async (id?: string, silent = false) => {
		const target = id ?? runId;
		if (!target) return;
		if (!silent) setBusy("refresh");
		try {
			const detail = await getProductionRun(target);
			const run = (detail as unknown as { run?: Record<string, unknown> }).run ?? detail;
			setRunStatus(String((run as Record<string, unknown>).status ?? ""));
			let cfg = (run as Record<string, unknown>).config_json as unknown;
			if (typeof cfg === "string") { try { cfg = JSON.parse(cfg); } catch { cfg = {}; } }
			const persisted = (cfg as { last_dry_run_report?: DryRunReport })?.last_dry_run_report;
			if (persisted) setReport(persisted);
			const items = (detail as unknown as { items?: RunItem[] }).items;
			if (Array.isArray(items) && items.length > 0) setJobItem(items[0]);
		} catch (e) {
			if (!silent) setError(`Refresh failed: ${e instanceof Error ? e.message : String(e)}`);
		} finally {
			if (!silent) setBusy(null);
		}
	}, [runId]);

	/** The one live door. Latches before the await; the server re-checks every gate condition. */
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
			setRunStatus(res.status ?? "RUNNING");
			setStage("LIVE_SUBMITTED");
			await refresh(runId, true);
		} catch (e) {
			setLiveError(e instanceof Error ? e.message : String(e));
		} finally {
			setBusy(null);
		}
	};

	// ── live gate conditions (identical semantics to Queue Control) ──
	const dryRunGreen = stage !== "IDLE" && report?.checked === 1 && report?.ready === 1 && report?.blocked === 0;
	const oneItemOnly = (report?.items?.length ?? 0) === 1;
	const noPriorJob = !jobItem?.production_job_id;
	const phraseOk = phrase === LIVE_CONFIRM_PHRASE;
	const liveGateOpen = Boolean(selectedProduct) && dryRunGreen && oneItemOnly && noPriorJob && phraseOk && !liveSubmitted && busy === null;

	const jobTerminal = TERMINAL_STATUSES.has(jobItem?.production_status ?? "");
	const jobArtifacts = jobItem?.artifact_media_ids ?? [];
	const registered = jobTerminal && jobArtifacts.length > 0;
	// The video exists in Flow (credits spent) but is not bound — status GENERATED/DOWNLOADED
	// or the GENERATED_BUT_UNRETRIEVED marker, with no artifact. This is an honest amber
	// state, NOT a red failure: something WAS generated.
	const generatedNotRegistered = !registered && jobArtifacts.length === 0 &&
		(jobItem?.production_status === "GENERATED" || jobItem?.production_status === "DOWNLOADED" ||
		 String(jobItem?.production_error ?? "").includes("GENERATED_BUT_UNRETRIEVED"));
	// A plain failure: FAILED/CANCELLED with no generated video behind it.
	const plainFailure = Boolean(jobItem?.production_error) && !registered && !generatedNotRegistered;

	useEffect(() => {
		if (stage !== "LIVE_SUBMITTED" || !runId || jobTerminal) {
			if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
			return;
		}
		pollRef.current = window.setInterval(() => { void refresh(runId, true); }, POLL_MS);
		return () => { if (pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; } };
	}, [stage, runId, jobTerminal, refresh]);

	const chip = (label: string, value: string | null, testid: string) => (
		<div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2" data-testid={testid}>
			<div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
			<div className="font-mono text-[11px] text-slate-200 break-all">{value ?? "—"}</div>
		</div>
	);

	return (
		<div className="p-6 max-w-5xl" data-testid="rpa-production-studio" data-stage={stage}>
			<div className="mb-6">
				<h1 className="flex items-center gap-2 text-xl font-bold text-slate-100">
					<Video size={20} className="text-blue-400" /> RPA Production Studio
				</h1>
				<p className="mt-1 text-xs text-slate-400">
					Pick a product, configure a text-to-video generation, validate it with a free dry run,
					then run <strong className="text-slate-200">one</strong> live T2V job and see the result.
				</p>
			</div>

			<div className="mb-6 flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3" data-testid="studio-bulk-locked" data-locked="true">
				<Lock size={16} className="text-amber-300 shrink-0" />
				<div className="text-[11px] text-amber-100">
					<strong>MVP scope: one serial T2V job only.</strong> Bulk generation and the F2V / I2V /
					Hybrid / Image modes are locked below — this studio runs a single text-to-video job at a time.
				</div>
			</div>

			{/* ── 1 · Product ── */}
			<section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
				<h2 className="mb-3 text-sm font-semibold text-slate-200">1 · Choose a product</h2>
				<div className="mb-3 flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2">
					<Search size={14} className="text-slate-500" />
					<input
						data-testid="studio-product-search"
						value={query}
						onChange={(e) => setQuery(e.target.value)}
						onKeyDown={(e) => { if (e.key === "Enter") void loadProducts(query); }}
						placeholder="Search products by name…"
						className="w-full bg-transparent text-[12px] text-slate-100 placeholder:text-slate-600 focus:outline-none"
					/>
					<button type="button" data-testid="studio-product-search-btn" onClick={() => void loadProducts(query)} disabled={loadingProducts}
						className="rounded border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800 disabled:opacity-40">Search</button>
				</div>

				{productsError && <div className="text-[11px] text-red-300" data-testid="studio-products-error">Could not load products.</div>}
				{loadingProducts && <div className="text-[11px] text-slate-500" data-testid="studio-products-loading">Loading products…</div>}
				{!loadingProducts && !productsError && products.length === 0 && <div className="text-[11px] text-slate-500" data-testid="studio-products-empty">No products found.</div>}

				<div className="max-h-56 space-y-1.5 overflow-y-auto">
					{products.map((p) => (
						<button
							type="button"
							key={p.id}
							data-testid="studio-product-option"
							data-product-id={p.id}
							data-selected={selectedProduct?.id === p.id ? "true" : "false"}
							onClick={() => pickProduct(p)}
							className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors ${selectedProduct?.id === p.id ? "border-blue-500/60 bg-blue-500/10" : "border-slate-800 hover:bg-slate-800/50"}`}
						>
							<span className="min-w-0">
								<span className="block truncate text-[11px] text-slate-200">{p.product_display_name || p.product_short_name || p.id}</span>
								<span className="block font-mono text-[10px] text-slate-500">{p.id}{p.category ? ` · ${p.category}` : ""}</span>
							</span>
							{selectedProduct?.id === p.id && <CheckCircle2 size={14} className="shrink-0 text-blue-400" />}
						</button>
					))}
				</div>
			</section>

			{/* ── 2 · Mode ── */}
			<section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
				<h2 className="mb-3 text-sm font-semibold text-slate-200">2 · Choose a mode</h2>
				<div className="grid grid-cols-2 gap-2 md:grid-cols-5">
					<div className="rounded-lg border border-emerald-500/50 bg-emerald-500/10 p-3" data-testid="studio-mode-t2v" data-enabled="true">
						<Video size={16} className="mb-1 text-emerald-300" />
						<div className="text-[11px] font-semibold text-emerald-200">Text → Video</div>
						<div className="text-[9px] text-emerald-300/80">T2V · enabled</div>
					</div>
					{LOCKED_MODES.map((m) => {
						const Icon = m.icon;
						return (
							<div key={m.key} className="rounded-lg border border-slate-800 bg-slate-950/60 p-3 opacity-70" data-testid={`studio-mode-${m.key.toLowerCase()}`} data-enabled="false" data-locked="true" title={m.reason}>
								<div className="mb-1 flex items-center gap-1"><Icon size={16} className="text-slate-600" /><Lock size={10} className="text-slate-600" /></div>
								<div className="text-[11px] font-semibold text-slate-400">{m.label}</div>
								<div className="text-[9px] text-slate-600">{m.key} · locked</div>
							</div>
						);
					})}
				</div>
				<p className="mt-2 text-[10px] text-slate-500" data-testid="studio-locked-reason">
					Locked modes need an image uploaded to Google Flow (or are a separate lane) — not yet wired into this studio.
				</p>
			</section>

			{/* ── 3 · Configure ── */}
			<section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
				<h2 className="mb-3 text-sm font-semibold text-slate-200">3 · Configure</h2>
				<div className="grid grid-cols-2 gap-3 md:grid-cols-4">
					<label className="block">
						<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Model</span>
						<select data-testid="studio-model" value={model} onChange={(e) => { setModel(e.target.value); resetPipeline(); }}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none">
							{models.length === 0 && <option value="">—</option>}
							{models.map((m) => <option key={m.key} value={m.ui_label}>{m.ui_label}</option>)}
						</select>
					</label>
					<label className="block">
						<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Duration (s)</span>
						<select data-testid="studio-duration" value={duration} onChange={(e) => { setDuration(Number(e.target.value)); resetPipeline(); }}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none">
							{durationOptions.map((d) => <option key={d} value={d}>{d}</option>)}
						</select>
					</label>
					<label className="block">
						<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Aspect</span>
						<select data-testid="studio-aspect" value={aspect} onChange={(e) => { setAspect(e.target.value); resetPipeline(); }}
							className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-[11px] text-slate-100 focus:outline-none">
							{ASPECTS.map((a) => <option key={a} value={a}>{a}</option>)}
						</select>
					</label>
					<label className="block">
						<span className="mb-1 block text-[10px] uppercase tracking-wider text-slate-500">Quantity</span>
						<input data-testid="studio-quantity" value="1" disabled readOnly
							className="w-full rounded-lg border border-slate-800 bg-slate-900 px-2 py-1.5 text-[11px] text-slate-400" />
						<span className="mt-0.5 block text-[9px] text-slate-600">Fixed to 1 for the MVP</span>
					</label>
				</div>
			</section>

			{error && (
				<div className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200" data-testid="studio-error">
					<AlertTriangle size={14} className="mt-0.5 shrink-0" /><span>{error}</span>
				</div>
			)}

			{/* ── 4 · Prepare & validate ── */}
			<section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4" data-testid="studio-prepare-panel">
				<h2 className="mb-3 text-sm font-semibold text-slate-200">4 · Prepare &amp; validate (no credits)</h2>
				<div className="mb-4 grid grid-cols-2 gap-2 md:grid-cols-4">
					{chip("Product", selectedProduct?.id ?? null, "studio-status-product")}
					{chip("WGP id", wgpId, "studio-status-wgp")}
					{chip("Run id", runId, "studio-status-run")}
					{chip("Dry-run ready", report ? `${report.ready ?? 0}/${report.checked ?? 0} · blocked ${report.blocked ?? 0}` : null, "studio-status-dryrun")}
				</div>
				<div className="flex flex-wrap gap-2">
					<button type="button" data-testid="studio-action-prepare" onClick={() => void handlePrepare()}
						disabled={!selectedProduct || busy !== null || stage !== "IDLE"}
						className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/50 bg-blue-500/15 px-3 py-2 text-[11px] font-semibold text-blue-100 hover:bg-blue-500/25 disabled:cursor-not-allowed disabled:opacity-40">
						{busy === "prepare" ? <Loader2 size={12} className="animate-spin" /> : <PackageCheck size={12} />} Prepare package
					</button>
					<button type="button" data-testid="studio-action-validate" onClick={() => void handleValidate()}
						disabled={!runId || busy !== null || stage !== "PREPARED"}
						className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/50 bg-emerald-500/15 px-3 py-2 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40">
						{busy === "validate" ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />} Run validation (dry run)
					</button>
				</div>

				{report && (
					<div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/60 p-3" data-testid="studio-dryrun-report" data-ready={String(report.ready ?? 0)} data-blocked={String(report.blocked ?? 0)}>
						<div className="text-[11px] text-slate-300">
							Checked <strong>{report.checked ?? 0}</strong> · Ready <strong className="text-emerald-300">{report.ready ?? 0}</strong> · Blocked <strong className={report.blocked ? "text-red-300" : "text-slate-300"}>{report.blocked ?? 0}</strong>
							<span className="ml-2 text-emerald-300/80">· no provider call, no credit</span>
						</div>
						{(report.items ?? []).map((it) => it.ok === false && (
							<ul key={it.package_id} className="mt-1 pl-4" data-testid="studio-dryrun-blockers">
								{(it.blockers ?? []).map((b) => <li key={b} data-testid="studio-blocker" className="list-disc text-[10px] text-red-300">{b}</li>)}
							</ul>
						))}
					</div>
				)}
			</section>

			{/* ── 5 · One live T2V ── */}
			<section className="mb-6 rounded-xl border border-red-500/40 bg-red-500/5 p-4" data-testid="studio-live-gate" data-gate-open={liveGateOpen ? "true" : "false"}>
				<h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-red-200"><Flame size={14} /> 5 · Run one live T2V</h2>
				<div className="mb-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-[11px] text-red-100" data-testid="studio-live-warning">
					<strong>This spends real credits.</strong> It calls the real provider and runs exactly one T2V
					generation. It cannot be undone. After it submits, do <strong>not</strong> retry unless the
					system proves no provider submission occurred.
				</div>
				<div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-3" data-testid="studio-live-checks">
					{[
						{ id: "product", label: "Product selected", ok: Boolean(selectedProduct) },
						{ id: "dryrun", label: "Dry run ready=1 blocked=0", ok: Boolean(dryRunGreen) },
						{ id: "one-item", label: "Exactly 1 item", ok: oneItemOnly },
						{ id: "no-prior-job", label: "No prior provider job", ok: noPriorJob },
						{ id: "phrase", label: "Confirmation phrase", ok: phraseOk },
						{ id: "not-submitted", label: "Not already submitted", ok: !liveSubmitted },
					].map((c) => (
						<div key={c.id} data-testid={`studio-check-${c.id}`} data-ok={c.ok ? "true" : "false"}
							className={`rounded-lg border px-2 py-1.5 text-[10px] ${c.ok ? "border-emerald-500/40 bg-emerald-500/5 text-emerald-200" : "border-slate-700 bg-slate-900/60 text-slate-500"}`}>
							{c.ok ? "✓" : "○"} {c.label}
						</div>
					))}
				</div>
				<label className="mb-1 block text-[10px] uppercase tracking-wider text-slate-400" htmlFor="studio-phrase">
					Type <code className="text-red-300">{LIVE_CONFIRM_PHRASE}</code> to authorize
				</label>
				<input id="studio-phrase" data-testid="studio-phrase-input" type="text" value={phrase} disabled={liveSubmitted}
					onChange={(e) => setPhrase(e.target.value)} placeholder={LIVE_CONFIRM_PHRASE} autoComplete="off" spellCheck={false}
					className="mb-3 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-[11px] text-slate-100 placeholder:text-slate-700 focus:border-red-500/60 focus:outline-none disabled:opacity-40" />
				<button type="button" data-testid="studio-action-go-live" data-enabled={liveGateOpen ? "true" : "false"}
					onClick={() => void handleGoLive()} disabled={!liveGateOpen}
					className="inline-flex items-center gap-1.5 rounded-lg border border-red-500/60 bg-red-500/20 px-3 py-2 text-[11px] font-semibold text-red-100 hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-40">
					{busy === "live" ? <Loader2 size={12} className="animate-spin" /> : <Flame size={12} />}
					{liveSubmitted ? "Live run submitted" : "Run ONE live T2V (burns credits)"}
				</button>
				{liveError && (
					<div className="mt-3 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200" data-testid="studio-live-refused">
						<AlertTriangle size={14} className="mt-0.5 shrink-0" />
						<span><strong>Live run refused — nothing fired.</strong> {explainFailure(liveError)}</span>
					</div>
				)}
			</section>

			{/* ── 6 · Result ── */}
			<section className="rounded-xl border border-slate-800 bg-slate-900/40 p-4" data-testid="studio-result-panel">
				<div className="mb-3 flex items-center justify-between">
					<h2 className="text-sm font-semibold text-slate-200">6 · Result</h2>
					{stage === "LIVE_SUBMITTED" && (
						<button type="button" data-testid="studio-action-refresh" onClick={() => void refresh()} disabled={busy !== null}
							className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] text-slate-300 hover:bg-slate-800 disabled:opacity-40">
							<RefreshCw size={12} className={busy === "refresh" ? "animate-spin" : ""} /> Refresh
						</button>
					)}
				</div>

				{stage !== "LIVE_SUBMITTED" && <div className="text-[11px] text-slate-500" data-testid="studio-result-empty">No live job yet. The result appears here after you run one.</div>}

				{stage === "LIVE_SUBMITTED" && (
					<div data-testid="studio-result" data-job-status={jobItem?.production_status ?? ""} data-terminal={jobTerminal ? "true" : "false"} data-registered={registered ? "true" : "false"}>
						<div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-3">
							{chip("Run id", runId, "studio-result-run")}
							{chip("WGP id", wgpId, "studio-result-wgp")}
							{chip("Provider job id", jobItem?.production_job_id ?? null, "studio-result-job")}
							{chip("Item status", jobItem?.production_status ?? null, "studio-result-status")}
							{chip("Run status", runStatus, "studio-result-runstatus")}
						</div>

						{!jobTerminal && (
							<div className="flex items-center gap-2 text-[11px] text-slate-400" data-testid="studio-result-inflight">
								<Loader2 size={12} className="animate-spin" /> Generating — polling every {POLL_MS / 1000}s. No further submission is made.
							</div>
						)}

						{plainFailure && (
							<div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-200" data-testid="studio-result-failure">
								<strong>Job failed.</strong> {explainFailure(jobItem?.production_error)}
							</div>
						)}

						{registered && (
							<div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-[11px] text-emerald-200" data-testid="studio-result-success">
								<strong>Registered ✓ — {jobItem?.production_status}.</strong> Artifact{jobArtifacts.length > 1 ? "s" : ""}:{" "}
								{jobArtifacts.map((m) => (
									<a key={m} data-testid="studio-result-artifact" data-media-id={m} href={`/api/flow/retrieved/${encodeURIComponent(m)}`} target="_blank" rel="noreferrer" className="mr-2 font-mono underline hover:text-emerald-100">{m}</a>
								))}
							</div>
						)}

						{generatedNotRegistered && (
							<div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-[11px] text-amber-100" data-testid="studio-result-generated-not-registered">
								<strong>Generated but not registered.</strong> The video generated (credits spent) but could
								not be deterministically bound to this job, so it is not in the library. This is not a success — it is an honest fail-closed state.
							</div>
						)}
					</div>
				)}
			</section>
		</div>
	);
}
