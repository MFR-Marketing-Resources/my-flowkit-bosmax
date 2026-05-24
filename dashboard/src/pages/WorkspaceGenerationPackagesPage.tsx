/**
 * WorkspaceGenerationPackagesPage — Prompt Handoff Bank
 *
 * Central page listing all saved workspace generation packages (F2V and I2V).
 * Manual handoff actions: Copy Prompt, Open Image, Download Image, Upload Order.
 * DOM handoff: stored scaffold only — dom_handoff_ready remains FALSE.
 * "Send to Google Flow" button is visible but disabled with an explanation.
 */
import {
	AlertTriangle,
	CheckCircle,
	ChevronDown,
	ChevronRight,
	ClipboardCopy,
	Download,
	ExternalLink,
	Filter,
	Layers,
	RefreshCw,
	Search,
	XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
	getWorkspaceGenerationPackage,
	listWorkspaceGenerationPackages,
} from "../api/workspaceGenerationPackages";
import type {
	WorkspaceGenerationPackage,
	WorkspaceGenerationPackageAsset,
} from "../types";

// ─── Status badge ─────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
	const map: Record<string, string> = {
		READY_MANUAL: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
		READY_DOM_STAGED: "border-blue-500/40 bg-blue-500/15 text-blue-300",
		BLOCKED: "border-red-500/40 bg-red-500/15 text-red-300",
		DRAFT: "border-slate-700 bg-slate-800 text-slate-400",
	};
	return (
		<span
			className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-widest ${map[status] ?? "border-slate-700 bg-slate-800 text-slate-400"}`}
		>
			{status}
		</span>
	);
}

// ─── Mode step guide config ───────────────────────────────────

const MODE_LABELS: Record<string, string> = {
	T2V: "Text to Video",
	F2V: "Frames to Video",
	I2V: "Image to Video (Ingredients)",
	IMG: "Image Generation",
};

const MODE_COLORS: Record<string, string> = {
	T2V: "border-blue-500/40 bg-blue-500/5",
	F2V: "border-purple-500/40 bg-purple-500/5",
	I2V: "border-amber-500/40 bg-amber-500/5",
	IMG: "border-emerald-500/40 bg-emerald-500/5",
};

const MODE_TAB_HINT: Record<string, string> = {
	T2V: "Google Flow → Tab: Text to Video",
	F2V: "Google Flow → Tab: Video / Frames",
	I2V: "Google Flow → Tab: Ingredients (Image to Video)",
	IMG: "Google Flow → Tab: Image Generation (Nano Banana 2)",
};

interface PromptBlock {
	block_index: number;
	block_role: string;
	duration_seconds: number;
	shot_count: number;
	engine_prompt_text: string;
}

// ─── Asset thumbnail card ─────────────────────────────────────

function AssetCard({
	asset,
	stepNumber,
	optional,
}: {
	asset: WorkspaceGenerationPackageAsset;
	stepNumber: number;
	optional?: boolean;
}) {
	return (
		<div className="rounded-xl border border-slate-700 bg-slate-900/60 overflow-hidden">
			<div className="flex items-center gap-2 px-3 py-2 border-b border-slate-700/50">
				<span className="w-5 h-5 rounded-full bg-slate-700 text-slate-300 text-[10px] font-bold flex items-center justify-center flex-shrink-0">
					{stepNumber}
				</span>
				<span className="text-xs font-bold text-slate-200 flex-1">
					{asset.label || asset.slot_key}
					{optional && (
						<span className="ml-1 text-[10px] font-normal text-slate-500">(optional)</span>
					)}
				</span>
			</div>
			{asset.preview_url ? (
				<div className="relative">
					<img
						src={asset.preview_url}
						alt={asset.label || asset.slot_key}
						className="w-full max-h-48 object-contain bg-slate-950"
						onError={(e) => {
							(e.target as HTMLImageElement).style.display = "none";
						}}
					/>
				</div>
			) : (
				<div className="h-24 bg-slate-950 flex items-center justify-center text-xs text-slate-500 italic">
					No preview available
				</div>
			)}
			<div className="flex gap-2 p-2">
				{asset.preview_url && (
					<a
						href={asset.preview_url}
						target="_blank"
						rel="noopener noreferrer"
						className="flex-1 flex items-center justify-center gap-1 text-[11px] font-semibold text-blue-400 border border-blue-500/30 bg-blue-500/10 rounded-lg py-1.5 hover:bg-blue-500/20 transition-colors"
					>
						<ExternalLink size={11} />
						Open
					</a>
				)}
				{asset.download_url && (
					<a
						href={asset.download_url}
						download
						className="flex-1 flex items-center justify-center gap-1 text-[11px] font-semibold text-indigo-400 border border-indigo-500/30 bg-indigo-500/10 rounded-lg py-1.5 hover:bg-indigo-500/20 transition-colors"
					>
						<Download size={11} />
						Download
					</a>
				)}
			</div>
			<div className="px-3 pb-2 text-[10px] text-slate-500 font-mono">
				After downloading → upload this image to Google Flow
			</div>
		</div>
	);
}

// ─── Prompt copy box ──────────────────────────────────────────

function PromptCopyBox({
	text,
	label,
	stepNumber,
}: {
	text: string;
	label?: string;
	stepNumber: number;
}) {
	const [copied, setCopied] = useState(false);
	const handleCopy = useCallback(() => {
		navigator.clipboard.writeText(text || "").then(() => {
			setCopied(true);
			setTimeout(() => setCopied(false), 2200);
		});
	}, [text]);

	return (
		<div className="rounded-xl border border-slate-700 bg-slate-900/60 overflow-hidden">
			<div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-slate-700/50">
				<div className="flex items-center gap-2">
					<span className="w-5 h-5 rounded-full bg-slate-700 text-slate-300 text-[10px] font-bold flex items-center justify-center flex-shrink-0">
						{stepNumber}
					</span>
					<span className="text-xs font-bold text-slate-200">
						{label ?? "Paste This Prompt into Google Flow"}
					</span>
				</div>
				<button
					type="button"
					onClick={handleCopy}
					className={`flex items-center gap-1.5 text-[11px] font-bold px-3 py-1.5 rounded-lg border transition-all ${copied ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-indigo-500/40 bg-indigo-500/15 text-indigo-300 hover:bg-indigo-500/25"}`}
				>
					<ClipboardCopy size={11} />
					{copied ? "Copied!" : "Copy Final Prompt"}
				</button>
			</div>
			<pre className="p-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto bg-slate-950/80">
				{text || "(no prompt text)"}
			</pre>
		</div>
	);
}

// ─── Step label row ───────────────────────────────────────────

function StepLabel({ n, text }: { n: number; text: string }) {
	return (
		<div className="flex items-center gap-2 py-1">
			<span className="w-5 h-5 rounded-full bg-slate-700 text-slate-300 text-[10px] font-bold flex items-center justify-center flex-shrink-0">
				{n}
			</span>
			<span className="text-xs text-slate-300">{text}</span>
		</div>
	);
}

// ─── Detail panel ─────────────────────────────────────────────

function PackageDetailPanel({ pkg }: { pkg: WorkspaceGenerationPackage }) {
	const [showDebug, setShowDebug] = useState(false);

	const handoff = pkg.manual_handoff_json;
	const domScaffold = pkg.dom_handoff_payload_json;
	const uploadOrder: string[] = handoff?.upload_order ?? [];
	const blockers: string[] = pkg.blockers_json ?? [];
	const warnings: string[] = pkg.warnings_json ?? [];
	const imageAssets = pkg.image_assets_json ?? {};
	const domReady: boolean = domScaffold?.readiness?.dom_handoff_ready ?? false;

	// Build ordered asset list from upload order
	const orderedAssets: WorkspaceGenerationPackageAsset[] = uploadOrder
		.map((slot) => imageAssets[slot])
		.filter(Boolean) as WorkspaceGenerationPackageAsset[];

	// Also include any assets not in upload order
	const extraAssets = Object.entries(imageAssets)
		.filter(([k, v]) => v && !uploadOrder.includes(k))
		.map(([, v]) => v as WorkspaceGenerationPackageAsset);

	const allDisplayAssets = [...orderedAssets, ...extraAssets];

	const mode = pkg.mode ?? "F2V";
	const isExtend = pkg.generation_mode === "EXTEND";
	const blocks = (pkg.prompt_blocks_json ?? []) as PromptBlock[];

	// Build mode-specific step list
	const imageStepStart = 2; // step 1 = open Flow tab
	const promptStep = imageStepStart + allDisplayAssets.length;
	const generateStep = promptStep + (isExtend ? blocks.length : 1);

	const modeModelHint: Record<string, string> = {
		T2V: "Veo 3.1 - Pro (or match your Workspace setting)",
		F2V: "Veo 3.1 - Lite (locked for F2V lane)",
		I2V: "Veo 3.1 - Pro (or match your Workspace setting)",
		IMG: "Nano Banana 2 (Image Generation)",
	};

	// Orientation info from dom scaffold settings
	const scaffoldSettings = (domScaffold?.settings ?? {}) as Record<string, unknown>;
	const durationSec = scaffoldSettings.duration_seconds as number | undefined;

	return (
		<div className="space-y-4">
			{/* Blockers */}
			{blockers.length > 0 && (
				<div className="rounded-xl border border-red-500/40 bg-red-500/10 p-3">
					<div className="flex items-center gap-2 mb-2">
						<XCircle size={14} className="text-red-400" />
						<span className="text-xs font-bold text-red-300 uppercase tracking-widest">Blockers — Fix Before Using</span>
					</div>
					<ul className="space-y-1">
						{blockers.map((b) => (
							<li key={b} className="text-xs text-red-300">• {b}</li>
						))}
					</ul>
				</div>
			)}

			{/* Warnings */}
			{warnings.length > 0 && (
				<div className="rounded-xl border border-amber-500/30 bg-amber-500/8 p-3">
					<div className="flex items-center gap-2 mb-1">
						<AlertTriangle size={13} className="text-amber-400" />
						<span className="text-xs font-bold text-amber-300 uppercase tracking-widest">Warnings</span>
					</div>
					<ul className="space-y-1">
						{warnings.map((w) => (
							<li key={w} className="text-xs text-amber-200">• {w}</li>
						))}
					</ul>
				</div>
			)}

			{/* ── Google Flow Setup Guide ── */}
			<div className={`rounded-2xl border p-4 space-y-4 ${MODE_COLORS[mode] ?? "border-slate-700 bg-slate-900/40"}`}>
				<div>
					<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400 mb-1">Google Flow Setup Guide</div>
					<div className="text-base font-bold text-slate-100">{MODE_LABELS[mode] ?? mode}</div>
					{durationSec && (
						<div className="text-xs text-slate-400 mt-0.5">Duration: {durationSec}s · Mode: {pkg.generation_mode}</div>
					)}
				</div>

				<div className="space-y-1">
					{/* Step 1 — Open Flow */}
					<div className="rounded-lg border border-slate-700/60 bg-slate-900/60 px-3 py-2">
						<StepLabel n={1} text={MODE_TAB_HINT[mode] ?? "Open Google Flow"} />
					</div>

					{/* Steps 2..N — Image slots */}
					{allDisplayAssets.length > 0 && (
						<div className="pt-1 space-y-1.5">
							<div className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
								Upload order
							</div>
							<div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
								{allDisplayAssets.map((asset, i) => {
									const isOptional = asset.slot_key === "end_frame" || asset.slot_key === "scene" || asset.slot_key === "style";
									return (
										<AssetCard
											key={asset.slot_key}
											asset={asset}
											stepNumber={imageStepStart + i}
											optional={isOptional}
										/>
									);
								})}
							</div>
						</div>
					)}

					{/* Orientation + Model reminder */}
					<div className="rounded-lg border border-slate-700/60 bg-slate-900/60 px-3 py-2 space-y-1">
						<StepLabel n={imageStepStart + allDisplayAssets.length} text={`Set orientation — match your Workspace setting (9:16 Vertical or 16:9 Horizontal)`} />
						<StepLabel n={imageStepStart + allDisplayAssets.length + 1} text={`Select model: ${modeModelHint[mode] ?? "match your Workspace setting"}`} />
					</div>

					{/* Prompt step(s) */}
					{isExtend && blocks.length > 0 ? (
						<div className="space-y-3">
							<div className="rounded-lg border border-amber-500/30 bg-amber-500/8 px-3 py-2 text-xs text-amber-200">
								EXTEND mode — {blocks.length} blocks. Copy and generate Block 1 first, then continue with Block 2. Do NOT paste both into one generation.
							</div>
							{blocks.map((block, i) => (
								<PromptCopyBox
									key={block.block_index}
									text={block.engine_prompt_text}
									label={`Block ${block.block_index} — ${block.block_role} (${block.duration_seconds}s · ${block.shot_count} shot)`}
									stepNumber={promptStep + i}
								/>
							))}
						</div>
					) : (
						<PromptCopyBox
							text={pkg.final_prompt_text}
							stepNumber={promptStep}
						/>
					)}

					{/* Final step — Generate */}
					<div className="rounded-lg border border-emerald-500/30 bg-emerald-500/8 px-3 py-2">
						<StepLabel n={generateStep} text="Click Generate in Google Flow" />
					</div>
				</div>
			</div>

			{/* ── Technical Debug (collapsed by default) ── */}
			<div>
				<button
					type="button"
					onClick={() => setShowDebug((v) => !v)}
					className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-slate-500 hover:text-slate-300 transition-colors"
				>
					{showDebug ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
					Debug / Lineage
				</button>
				{showDebug && (
					<div className="mt-3 space-y-3">
						<div className="bg-slate-950 rounded-lg p-3 space-y-1 text-[10px] font-mono text-slate-500">
							<div><span className="text-slate-600">package_id:</span> {pkg.workspace_generation_package_id}</div>
							<div><span className="text-slate-600">product_id:</span> {pkg.product_id}</div>
							<div><span className="text-slate-600">mode:</span> {pkg.mode} / {pkg.source_lane}</div>
							<div><span className="text-slate-600">generation_mode:</span> {pkg.generation_mode}</div>
							<div><span className="text-slate-600">snapshot_id:</span> {pkg.prompt_package_snapshot_id || "—"}</div>
							<div><span className="text-slate-600">execution_pkg_id:</span> {pkg.workspace_execution_package_id || "—"}</div>
							<div><span className="text-slate-600">created_at:</span> {pkg.created_at}</div>
						</div>
						<div className="bg-slate-950 rounded-lg p-3">
							<div className="flex items-center gap-2 mb-2">
								<Layers size={12} className="text-slate-500" />
								<span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">DOM Handoff Scaffold</span>
							</div>
							<div className="flex items-center gap-2">
								<CheckCircle size={11} className="text-emerald-500" />
								<span className="text-[10px] text-slate-500">manual_handoff_ready: {String(domScaffold?.readiness?.manual_handoff_ready ?? blockers.length === 0)}</span>
							</div>
							<div className="flex items-center gap-2 mt-1">
								<XCircle size={11} className="text-red-500/50" />
								<span className="text-[10px] text-slate-500">dom_handoff_ready: {String(domReady)} (locked — not enabled in this wave)</span>
							</div>
							<button type="button" disabled className="mt-2 w-full text-[10px] bg-slate-800 text-slate-600 px-3 py-2 rounded cursor-not-allowed">
								Send to Google Flow (DOM handoff not enabled in this wave)
							</button>
						</div>
					</div>
				)}
			</div>
		</div>
	);

	// legacy allDisplayAssets variable kept above — unused after refactor but kept for reference
}

// ─── Package row ──────────────────────────────────────────────

function PackageRow({
	pkg,
	isSelected,
	onSelect,
}: {
	pkg: WorkspaceGenerationPackage;
	isSelected: boolean;
	onSelect: () => void;
}) {
	return (
		<tr
			className={`cursor-pointer border-b border-slate-800 transition-colors ${isSelected ? "bg-blue-500/8" : "hover:bg-slate-800/50"}`}
			onClick={onSelect}
		>
			<td className="py-2 px-3">
				{isSelected ? (
					<ChevronDown size={14} className="text-blue-400" />
				) : (
					<ChevronRight size={14} className="text-slate-500" />
				)}
			</td>
			<td className="py-2 px-3 font-mono text-xs text-slate-400 max-w-[200px] truncate">
				{pkg.workspace_generation_package_id}
			</td>
			<td className="py-2 px-3 text-xs font-bold text-slate-200">
				{pkg.mode}
			</td>
			<td className="py-2 px-3 text-xs text-slate-300 max-w-[160px] truncate">
				{pkg.product_name_snapshot || pkg.product_id}
			</td>
			<td className="py-2 px-3">
				<StatusBadge status={pkg.status} />
			</td>
			<td className="py-2 px-3 text-xs text-slate-500">
				{pkg.created_at?.slice(0, 16).replace("T", " ")}
			</td>
		</tr>
	);
}

// ─── Main page ────────────────────────────────────────────────

export default function WorkspaceGenerationPackagesPage() {
	const [packages, setPackages] = useState<WorkspaceGenerationPackage[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [detailPkg, setDetailPkg] = useState<WorkspaceGenerationPackage | null>(
		null,
	);
	const [detailLoading, setDetailLoading] = useState(false);

	// Filters
	const [modeFilter, setModeFilter] = useState("");
	const [statusFilter, setStatusFilter] = useState("");
	const [productFilter] = useState("");
	const [search, setSearch] = useState("");

	const loadPackages = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const resp = await listWorkspaceGenerationPackages({
				mode: modeFilter || undefined,
				status: statusFilter || undefined,
				product_id: productFilter || undefined,
				limit: 100,
			});
			setPackages(resp.packages ?? []);
		} catch (e) {
			setError(String(e));
		} finally {
			setLoading(false);
		}
	}, [modeFilter, statusFilter, productFilter]);

	useEffect(() => {
		void loadPackages();
	}, [loadPackages]);

	const handleSelect = useCallback(
		async (pkg: WorkspaceGenerationPackage) => {
			if (selectedId === pkg.workspace_generation_package_id) {
				setSelectedId(null);
				setDetailPkg(null);
				return;
			}
			setSelectedId(pkg.workspace_generation_package_id);
			setDetailPkg(pkg);
			setDetailLoading(true);
			try {
				const full = await getWorkspaceGenerationPackage(
					pkg.workspace_generation_package_id,
				);
				setDetailPkg(full);
			} catch {
				// keep inline data
			} finally {
				setDetailLoading(false);
			}
		},
		[selectedId],
	);

	// Client-side search filter
	const filtered = packages.filter((p) => {
		if (!search) return true;
		const q = search.toLowerCase();
		return (
			p.workspace_generation_package_id.toLowerCase().includes(q) ||
			(p.product_name_snapshot || "").toLowerCase().includes(q) ||
			p.product_id.toLowerCase().includes(q)
		);
	});

	return (
		<div className="p-6 max-w-7xl mx-auto space-y-6">
			{/* Header */}
			<div>
				<h1 className="text-2xl font-bold text-slate-100">
					Prompt Handoff Bank
				</h1>
				<p className="text-sm text-slate-500 mt-1">
					Google Flow setup guide for each generated package. Click a package to see step-by-step instructions, images, and prompt copy.
				</p>
			</div>

			{/* Filters */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4 space-y-3">
				<div className="flex flex-wrap items-center justify-between gap-2">
					<div className="flex items-center gap-1.5">
						<Filter size={13} className="text-slate-500" />
						<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">Mode</span>
					</div>
					<div className="flex flex-wrap gap-1.5">
						{["ALL", "F2V", "I2V", "T2V", "IMG"].map((m) => {
							const active = (modeFilter || "ALL") === m;
							return (
								<button
									key={m}
									type="button"
									onClick={() => setModeFilter(m === "ALL" ? "" : m)}
									className={`px-3 py-1.5 rounded-full border text-[10px] font-bold uppercase tracking-[0.16em] transition-all ${active ? "border-blue-400/60 bg-blue-500/10 text-blue-200" : "border-slate-700 bg-slate-950 text-slate-400 hover:text-slate-200"}`}
								>
									{m}
								</button>
							);
						})}
					</div>
				</div>
				<div className="flex flex-wrap items-center justify-between gap-2">
					<div className="flex items-center gap-1.5">
						<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">Status</span>
					</div>
					<div className="flex flex-wrap gap-1.5">
						{["ALL", "READY_MANUAL", "BLOCKED", "DRAFT"].map((s) => {
							const active = (statusFilter || "ALL") === s;
							return (
								<button
									key={s}
									type="button"
									onClick={() => setStatusFilter(s === "ALL" ? "" : s)}
									className={`px-3 py-1.5 rounded-full border text-[10px] font-bold uppercase tracking-[0.16em] transition-all ${active ? "border-blue-400/60 bg-blue-500/10 text-blue-200" : "border-slate-700 bg-slate-950 text-slate-400 hover:text-slate-200"}`}
								>
									{s}
								</button>
							);
						})}
					</div>
				</div>
				<div className="flex gap-2">
					<div className="relative flex-1">
						<Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
						<input
							type="text"
							value={search}
							onChange={(e) => setSearch(e.target.value)}
							placeholder="Search by product name or package ID..."
							className="w-full rounded-full border border-slate-700 bg-slate-950 pl-8 pr-4 py-2 text-xs text-slate-200 placeholder:text-slate-500 outline-none focus:border-blue-400/50"
						/>
					</div>
					<button
						type="button"
						onClick={() => void loadPackages()}
						className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200 transition-colors"
					>
						<RefreshCw size={13} />
						Refresh
					</button>
				</div>
			</div>

			{error && (
				<div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
					{error}
				</div>
			)}

			<div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
				{/* Package list */}
				<div className="space-y-2">
					{loading ? (
						<div className="rounded-2xl border border-slate-800 bg-slate-900/40 py-12 text-center text-sm text-slate-500">
							Loading packages…
						</div>
					) : filtered.length === 0 ? (
						<div className="rounded-2xl border border-slate-800 bg-slate-900/40 py-12 text-center text-sm text-slate-500">
							No packages found. Generate a package from the Workspace (F2V, I2V, T2V or IMG tab).
						</div>
					) : (
						<div className="rounded-2xl border border-slate-800 bg-slate-950/80 overflow-hidden">
							<table className="w-full">
								<thead className="border-b border-slate-800">
									<tr className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
										<th className="py-3 px-3 w-8"></th>
										<th className="py-3 px-3 text-left">Package ID</th>
										<th className="py-3 px-3 text-left">Mode</th>
										<th className="py-3 px-3 text-left">Product</th>
										<th className="py-3 px-3 text-left">Status</th>
										<th className="py-3 px-3 text-left">Created</th>
									</tr>
								</thead>
								<tbody>
									{filtered.map((pkg) => (
										<PackageRow
											key={pkg.workspace_generation_package_id}
											pkg={pkg}
											isSelected={
												selectedId === pkg.workspace_generation_package_id
											}
											onSelect={() => void handleSelect(pkg)}
										/>
									))}
								</tbody>
							</table>
						</div>
					)}
					<p className="text-[11px] text-slate-600 pl-1">
						{filtered.length} package(s) shown
					</p>
				</div>

				{/* Detail panel */}
				{detailPkg ? (
					<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-5 xl:sticky xl:top-4">
						<div className="flex items-center justify-between mb-4">
							<div>
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500 mb-1">Selected Package</div>
								<div className="text-sm font-bold text-slate-100">{detailPkg.product_name_snapshot || detailPkg.product_id}</div>
								<div className="text-[11px] text-slate-500 mt-0.5 font-mono">{detailPkg.mode} · {detailPkg.generation_mode}</div>
							</div>
							<StatusBadge status={detailPkg.status} />
						</div>
						{detailLoading ? (
							<div className="py-8 text-center text-sm text-slate-500">
								Loading detail…
							</div>
						) : (
							<PackageDetailPanel pkg={detailPkg} />
						)}
					</div>
				) : (
					<div className="rounded-2xl border border-slate-800 bg-slate-900/40 py-12 text-center text-sm text-slate-500 xl:sticky xl:top-4">
						Click a package to see the Google Flow setup guide.
					</div>
				)}
			</div>
		</div>
	);
}
