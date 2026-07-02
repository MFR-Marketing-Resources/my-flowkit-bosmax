import {
	AlertTriangle,
	Archive,
	CheckCircle,
	CheckSquare,
	ChevronDown,
	ChevronRight,
	ClipboardCopy,
	Download,
	ExternalLink,
	FileDown,
	Filter,
	Layers,
	RefreshCw,
	Search,
	Send,
	Square,
	Trash2,
	XCircle,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { VideoModelInfo } from "../api/productionQueue";
import {
	approvePackages,
	createProductionRun,
	fetchVideoModels,
} from "../api/productionQueue";
import {
	deleteWorkspaceGenerationPackage,
	getWorkspaceGenerationPackage,
	listWorkspaceGenerationPackages,
	patchWorkspaceGenerationPackage,
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
		ARCHIVED: "border-amber-500/40 bg-amber-500/10 text-amber-300",
	};
	return (
		<span
			className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-widest ${map[status] ?? "border-slate-700 bg-slate-800 text-slate-400"}`}
		>
			{status}
		</span>
	);
}

// ─── Mode config ──────────────────────────────────────────────

const MODE_LABELS: Record<string, string> = {
	T2V: "Text to Video",
	HYBRID: "Hybrid (Product + AI Presenter)",
	F2V: "Frames (Motion Delta)",
	I2V: "Image to Video (Ingredients)",
	IMG: "Image Generation",
};

const MODE_COLORS: Record<string, string> = {
	T2V: "border-blue-500/40 bg-blue-500/5",
	HYBRID: "border-cyan-500/40 bg-cyan-500/5",
	F2V: "border-purple-500/40 bg-purple-500/5",
	I2V: "border-amber-500/40 bg-amber-500/5",
	IMG: "border-emerald-500/40 bg-emerald-500/5",
};

const MODE_TAB_HINT: Record<string, string> = {
	T2V: "Google Flow → Tab: Text to Video",
	HYBRID: "Google Flow → Tab: Video / Frames (HYBRID surface)",
	F2V: "Google Flow → Tab: Video / Frames (FRAMES surface)",
	I2V: "Google Flow → Tab: Ingredients (Image to Video)",
	IMG: "Google Flow → Tab: Image Generation (Nano Banana 2)",
};

const SURFACE_FILTERS = [
	{ id: "ALL", label: "ALL" },
	{ id: "HYBRID", label: "HYBRID" },
	{ id: "F2V", label: "FRAMES" },
	{ id: "I2V", label: "I2V" },
	{ id: "T2V", label: "T2V" },
	{ id: "IMG", label: "IMG" },
] as const;

const MODE_OPERATOR_ROUTE: Record<string, string> = {
	HYBRID: "/operator/hybrid",
	T2V: "/operator/t2v",
	F2V: "/operator/f2v",
	I2V: "/operator/i2v",
	IMG: "/operator/img",
};

function getOperatorSurfaceMode(pkg: WorkspaceGenerationPackage): string {
	if (pkg.mode === "F2V" && pkg.source_lane === "HYBRID") {
		return "HYBRID";
	}
	return pkg.mode ?? "F2V";
}

function getOperatorSurfaceLabel(pkg: WorkspaceGenerationPackage): string {
	const surfaceMode = getOperatorSurfaceMode(pkg);
	if (surfaceMode === "HYBRID") return "Hybrid (Product + AI Presenter)";
	return MODE_LABELS[surfaceMode] ?? surfaceMode;
}

function getOperatorSurfaceRoute(pkg: WorkspaceGenerationPackage): string | null {
	return MODE_OPERATOR_ROUTE[getOperatorSurfaceMode(pkg)] ?? null;
}

// ─── Prompt Queue / Production separation helpers ─────────────

function getLogicalModeBadge(pkg: WorkspaceGenerationPackage): string {
	if (pkg.logical_mode) return pkg.logical_mode;
	return getOperatorSurfaceMode(pkg);
}

function getAntiRedundancyCount(pkg: WorkspaceGenerationPackage): number {
	const raw = pkg.anti_redundancy_json;
	if (!raw) return 0;
	let parsed: unknown = raw;
	if (typeof raw === "string") {
		try {
			parsed = JSON.parse(raw);
		} catch {
			return 0;
		}
	}
	if (typeof parsed !== "object" || parsed === null) return 0;
	const obj = parsed as { hard_blocks?: unknown; warnings?: unknown };
	const hard = Array.isArray(obj.hard_blocks) ? obj.hard_blocks.length : 0;
	const warn = Array.isArray(obj.warnings) ? obj.warnings.length : 0;
	return hard + warn;
}

const LOGICAL_MODE_BADGE_COLORS: Record<string, string> = {
	T2V: "border-blue-500/40 bg-blue-500/10 text-blue-300",
	HYBRID: "border-cyan-500/40 bg-cyan-500/10 text-cyan-300",
	F2V: "border-purple-500/40 bg-purple-500/10 text-purple-300",
	I2V: "border-amber-500/40 bg-amber-500/10 text-amber-300",
	IMG: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
};

const PRODUCTION_STATUS_COLORS: Record<string, string> = {
	APPROVED: "border-blue-500/40 bg-blue-500/15 text-blue-300",
	QUEUED: "border-indigo-500/40 bg-indigo-500/15 text-indigo-300",
	RUNNING: "border-emerald-500/40 bg-emerald-500/15 text-emerald-300",
	GENERATED: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
	DOWNLOADED: "border-cyan-500/40 bg-cyan-500/15 text-cyan-300",
	FAILED: "border-red-500/40 bg-red-500/15 text-red-300",
	CANCELLED: "border-slate-600 bg-slate-800 text-slate-400",
};

function ProductionStatusBadge({ status }: { status: string }) {
	return (
		<span
			className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-widest whitespace-nowrap ${PRODUCTION_STATUS_COLORS[status] ?? "border-slate-700 bg-slate-800 text-slate-400"}`}
		>
			{status}
		</span>
	);
}

interface PromptBlock {
	block_index: number;
	block_role: string;
	duration_seconds: number;
	shot_count: number;
	engine_prompt_text: string;
}

const CANONICAL_PROMPT_SECTIONS = [
	"SECTION 1 - ROLE & OBJECTIVE",
	"SECTION 2 - PRODUCT TRUTH LOCK",
	"SECTION 3 - CONTINUITY & STATE LOCK",
	"SECTION 4 - VISUAL STORY",
	"SECTION 5 - SHOT & CAMERA RULES",
	"SECTION 6 - SPOKEN DIALOGUE",
	"SECTION 7 - VOICE & DELIVERY",
	"SECTION 8 - CTA & END FRAME",
	"SECTION 9 - NO_OVERLAY",
] as const;

interface PromptSection {
	heading: string;
	sectionNumber: number | null;
	title: string;
	body: string;
}

function parsePromptSections(text: string): PromptSection[] {
	const normalized = (text ?? "").replace(/\r\n/g, "\n");
	const matches = [...normalized.matchAll(/^SECTION [1-9] - .+$/gm)];
	if (matches.length === 0) {
		return [];
	}

	return matches.map((match, index) => {
		const heading = match[0].trim();
		const start = (match.index ?? 0) + match[0].length;
		const end =
			index + 1 < matches.length
				? (matches[index + 1].index ?? normalized.length)
				: normalized.length;
		const sectionNumberMatch = heading.match(/^SECTION (\d+)/);
		return {
			heading,
			sectionNumber: sectionNumberMatch ? Number(sectionNumberMatch[1]) : null,
			title: heading.replace(/^SECTION \d+ - /, ""),
			body: normalized.slice(start, end).trim(),
		};
	});
}

// ─── Asset card ───────────────────────────────────────────────

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
				<img
					src={asset.preview_url}
					alt={asset.label || asset.slot_key}
					className="w-full max-h-48 object-contain bg-slate-950"
					onError={(e) => {
						(e.target as HTMLImageElement).style.display = "none";
					}}
				/>
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
	const sections = parsePromptSections(text);
	const presentHeadings = new Set(sections.map((section) => section.heading));
	const missingSections = CANONICAL_PROMPT_SECTIONS.filter(
		(heading) => !presentHeadings.has(heading),
	);
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
			<div className="border-b border-slate-700/50 bg-slate-950/40 px-3 py-3">
				<div className="flex flex-wrap gap-2">
					<span className="rounded-full border border-slate-700 bg-slate-950 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
						{sections.length}/9 sections detected
					</span>
					{missingSections.length === 0 ? (
						<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200">
							Canonical 9-section structure
						</span>
					) : (
						<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-200">
							Missing {missingSections.map((heading) => heading.replace("SECTION ", "S")).join(", ")}
						</span>
					)}
				</div>
			</div>
			{sections.length > 0 ? (
				<div className="divide-y divide-slate-800 bg-slate-950/80">
					{sections.map((section) => (
						<details
							key={section.heading}
							open={
								section.sectionNumber === 4 ||
								section.sectionNumber === 6 ||
								section.sectionNumber === 8
							}
							className="group"
						>
							<summary className="cursor-pointer list-none px-3 py-2.5">
								<div className="flex items-center justify-between gap-3">
									<div className="flex items-center gap-2">
										<span className="rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
											S{section.sectionNumber ?? "?"}
										</span>
										<span className="text-xs font-semibold text-slate-100">
											{section.title}
										</span>
									</div>
									<span className="text-[10px] uppercase tracking-[0.16em] text-slate-500 group-open:text-slate-300">
										Expand
									</span>
								</div>
							</summary>
							<pre className="border-t border-slate-800 px-3 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
								{section.body || "(empty section)"}
							</pre>
						</details>
					))}
				</div>
			) : (
				<pre className="p-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed max-h-48 overflow-y-auto bg-slate-950/80">
					{text || "(no prompt text)"}
				</pre>
			)}
		</div>
	);
}

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

function PackageDetailPanel({
	pkg,
	onUpdate,
}: {
	pkg: WorkspaceGenerationPackage;
	onUpdate: (updated: WorkspaceGenerationPackage) => void;
}) {
	const [showDebug, setShowDebug] = useState(false);
	const [notes, setNotes] = useState(pkg.operator_notes ?? "");
	const [notesSaving, setNotesSaving] = useState(false);
	const [notesSaved, setNotesSaved] = useState(false);

	const handoff = pkg.manual_handoff_json;
	const domScaffold = pkg.dom_handoff_payload_json;
	const uploadOrder: string[] = handoff?.upload_order ?? [];
	const blockers: string[] = pkg.blockers_json ?? [];
	const warnings: string[] = pkg.warnings_json ?? [];
	const imageAssets = pkg.image_assets_json ?? {};
	const domReady: boolean = domScaffold?.readiness?.dom_handoff_ready ?? false;

	const orderedAssets: WorkspaceGenerationPackageAsset[] = uploadOrder
		.map((slot) => imageAssets[slot])
		.filter(Boolean) as WorkspaceGenerationPackageAsset[];
	const extraAssets = Object.entries(imageAssets)
		.filter(([k, v]) => v && !uploadOrder.includes(k))
		.map(([, v]) => v as WorkspaceGenerationPackageAsset);
	const allDisplayAssets = [...orderedAssets, ...extraAssets];

	const mode = pkg.mode ?? "F2V";
	const surfaceMode = getOperatorSurfaceMode(pkg);
	const isExtend = pkg.generation_mode === "EXTEND";
	const blocks = (pkg.prompt_blocks_json ?? []) as PromptBlock[];
	const imageStepStart = 2;
	const promptStep = imageStepStart + allDisplayAssets.length;
	const generateStep = promptStep + (isExtend ? blocks.length : 1);
	const modeModelHint: Record<string, string> = {
		T2V: "Veo 3.1 - Pro (or match your Workspace setting)",
		HYBRID: "Veo 3.1 - Lite (locked for HYBRID / FRAMES lane)",
		F2V: "Veo 3.1 - Lite (locked for F2V lane)",
		I2V: "Veo 3.1 - Pro (or match your Workspace setting)",
		IMG: "Nano Banana 2 (Image Generation)",
	};
	const scaffoldSettings = (domScaffold?.settings ?? {}) as Record<string, unknown>;
	const durationSec = scaffoldSettings.duration_seconds as number | undefined;

	const saveNotes = async () => {
		setNotesSaving(true);
		try {
			const updated = await patchWorkspaceGenerationPackage(
				pkg.workspace_generation_package_id,
				{ operator_notes: notes },
			);
			onUpdate(updated);
			setNotesSaved(true);
			setTimeout(() => setNotesSaved(false), 2000);
		} finally {
			setNotesSaving(false);
		}
	};

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

			{/* Operator Notes */}
			<div className="rounded-xl border border-slate-700 bg-slate-900/50 p-3">
				<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500 mb-2">Operator Notes</div>
				<textarea
					value={notes}
					onChange={(e) => setNotes(e.target.value)}
					rows={3}
					placeholder="Add notes for this package…"
					className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 placeholder:text-slate-600 resize-none outline-none focus:border-slate-500"
				/>
				<button
					type="button"
					onClick={() => void saveNotes()}
					disabled={notesSaving}
					className={`mt-2 px-3 py-1.5 rounded-lg border text-[11px] font-semibold transition-all ${notesSaved ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-slate-600 bg-slate-800 text-slate-300 hover:bg-slate-700"}`}
				>
					{notesSaving ? "Saving…" : notesSaved ? "Saved!" : "Save Notes"}
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

			{/* Google Flow Setup Guide */}
			<div className={`rounded-2xl border p-4 space-y-4 ${MODE_COLORS[surfaceMode] ?? MODE_COLORS[mode] ?? "border-slate-700 bg-slate-900/40"}`}>
				<div>
					<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400 mb-1">Google Flow Setup Guide</div>
					<div className="text-base font-bold text-slate-100">{getOperatorSurfaceLabel(pkg)}</div>
					{durationSec && (
						<div className="text-xs text-slate-400 mt-0.5">Duration: {durationSec}s · Mode: {pkg.generation_mode}</div>
					)}
				</div>

				<div className="space-y-1">
					<div className="rounded-lg border border-slate-700/60 bg-slate-900/60 px-3 py-2">
						<StepLabel
							n={1}
							text={MODE_TAB_HINT[surfaceMode] ?? MODE_TAB_HINT[mode] ?? "Open Google Flow"}
						/>
					</div>

					{uploadOrder.length > 0 && (
						<div className="pt-1 text-[11px] text-slate-400">
							Upload order: {uploadOrder.join(" → ")}
						</div>
					)}
					{allDisplayAssets.length > 0 && (
						<div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
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
					)}

					<div className="rounded-lg border border-slate-700/60 bg-slate-900/60 px-3 py-2 space-y-1">
						<StepLabel n={imageStepStart + allDisplayAssets.length} text="Set orientation — match your Workspace setting (9:16 Vertical or 16:9 Horizontal)" />
						<StepLabel n={imageStepStart + allDisplayAssets.length + 1} text={`Select model: ${modeModelHint[surfaceMode] ?? modeModelHint[mode] ?? "match your Workspace setting"}`} />
					</div>

					{isExtend && blocks.length > 0 ? (
						<div className="space-y-3">
							<div className="rounded-lg border border-amber-500/30 bg-amber-500/8 px-3 py-2 text-xs text-amber-200">
								EXTEND mode — {blocks.length} blocks. Copy and generate Block 1 first, then continue with Block 2.
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
						<PromptCopyBox text={pkg.final_prompt_text} stepNumber={promptStep} />
					)}

					<div className="rounded-lg border border-emerald-500/30 bg-emerald-500/8 px-3 py-2">
						<StepLabel n={generateStep} text="Click Generate in Google Flow" />
					</div>
				</div>
			</div>

			{/* Debug */}
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
							<div><span className="text-slate-600">surface:</span> {surfaceMode}</div>
							<div><span className="text-slate-600">job mode:</span> {pkg.mode} / {pkg.source_lane}</div>
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
	isChecked,
	onSelect,
	onCheck,
	onArchiveToggle,
	onDelete,
}: {
	pkg: WorkspaceGenerationPackage;
	isSelected: boolean;
	isChecked: boolean;
	onSelect: () => void;
	onCheck: (checked: boolean) => void;
	onArchiveToggle: () => void;
	onDelete: () => void;
}) {
	const [showActions, setShowActions] = useState(false);
	const isArchived = pkg.status === "ARCHIVED";

	return (
		<tr
			className={`cursor-pointer border-b border-slate-800 transition-colors group ${isSelected ? "bg-blue-500/8" : "hover:bg-slate-800/50"}`}
			onClick={onSelect}
			onMouseEnter={() => setShowActions(true)}
			onMouseLeave={() => setShowActions(false)}
		>
			<td className="py-2 px-2 w-8" onClick={(e) => { e.stopPropagation(); onCheck(!isChecked); }}>
				{isChecked ? (
					<CheckSquare size={14} className="text-blue-400" />
				) : (
					<Square size={14} className="text-slate-600 group-hover:text-slate-400 transition-colors" />
				)}
			</td>
			<td className="py-2 px-2 w-6">
				{isSelected ? (
					<ChevronDown size={14} className="text-blue-400" />
				) : (
					<ChevronRight size={14} className="text-slate-500" />
				)}
			</td>
			<td className="py-2 px-3 font-mono text-xs text-slate-400 max-w-[180px]">
				<div className="truncate">{pkg.workspace_generation_package_id}</div>
				{pkg.prompt_fingerprint && (
					<div className="text-[9px] text-slate-600 truncate">
						fp:{pkg.prompt_fingerprint.slice(0, 8)}
					</div>
				)}
			</td>
			<td className="py-2 px-3 text-xs font-bold text-slate-200">
				<div className="flex flex-wrap items-center gap-1.5">
					<span
						className={`px-1.5 py-0.5 rounded border text-[9px] font-bold uppercase tracking-widest ${LOGICAL_MODE_BADGE_COLORS[getLogicalModeBadge(pkg)] ?? "border-slate-700 bg-slate-800 text-slate-400"}`}
					>
						{getLogicalModeBadge(pkg)}
					</span>
					<span>{getOperatorSurfaceLabel(pkg)}</span>
					{getAntiRedundancyCount(pkg) > 0 && (
						<span
							title="Anti-redundancy findings (hard blocks + warnings)"
							className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-300 text-[9px] font-bold"
						>
							<AlertTriangle size={9} />
							{getAntiRedundancyCount(pkg)}
						</span>
					)}
				</div>
			</td>
			<td className="py-2 px-3 text-xs text-slate-300 max-w-[150px] truncate">
				{pkg.product_name_snapshot || pkg.product_id}
			</td>
			<td className="py-2 px-3">
				<div className="flex flex-wrap items-center gap-1">
					<StatusBadge status={pkg.status} />
					{pkg.production_status && pkg.production_status !== "NONE" && (
						<ProductionStatusBadge status={pkg.production_status} />
					)}
				</div>
			</td>
			<td className="py-2 px-3 text-xs text-slate-500">
				{pkg.created_at?.slice(0, 16).replace("T", " ")}
			</td>
			<td className="py-2 px-3 w-20">
				{showActions && (
					<div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
						<button
							type="button"
							title={isArchived ? "Unarchive" : "Archive"}
							onClick={onArchiveToggle}
							className={`p-1.5 rounded-lg border transition-colors ${isArchived ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20" : "border-amber-500/30 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20"}`}
						>
							<Archive size={12} />
						</button>
						<button
							type="button"
							title="Delete"
							onClick={onDelete}
							className="p-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
						>
							<Trash2 size={12} />
						</button>
					</div>
				)}
			</td>
		</tr>
	);
}

const PAGE_SIZE = 20;

// ─── Main page ────────────────────────────────────────────────

export default function WorkspaceGenerationPackagesPage() {
	const navigate = useNavigate();
	const [packages, setPackages] = useState<WorkspaceGenerationPackage[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [selectedId, setSelectedId] = useState<string | null>(null);
	const [detailPkg, setDetailPkg] = useState<WorkspaceGenerationPackage | null>(null);
	const [detailLoading, setDetailLoading] = useState(false);
	const [currentPage, setCurrentPage] = useState(1);

	// P5B: Bulk selection
	const [checkedIds, setCheckedIds] = useState<Set<string>>(new Set());
	const [bulkLoading, setBulkLoading] = useState(false);

	// Approve + send-to-production handoff
	const [sendConfigOpen, setSendConfigOpen] = useState(false);
	const [sendConfig, setSendConfig] = useState({
		interval_min_seconds: 45,
		interval_max_seconds: 120,
		cooldown_after_n_jobs: 5,
		cooldown_seconds: 300,
		// REQUIRED — no preselected engine model; operator must choose.
		model: "",
	});
	const [videoModels, setVideoModels] = useState<VideoModelInfo[]>([]);

	// Load the engine model standard when the send-to-production config opens
	useEffect(() => {
		if (!sendConfigOpen || videoModels.length > 0) return;
		let cancelled = false;
		fetchVideoModels()
			.then((resp) => {
				if (!cancelled) setVideoModels(resp.models ?? []);
			})
			.catch(() => {});
		return () => {
			cancelled = true;
		};
	}, [sendConfigOpen, videoModels.length]);

	const [modeFilter, setModeFilter] = useState("");
	const [statusFilter, setStatusFilter] = useState("");
	const [search, setSearch] = useState("");

	const loadPackages = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const apiModeFilter =
				modeFilter === "HYBRID" || modeFilter === "F2V"
					? "F2V"
					: modeFilter || undefined;
			const resp = await listWorkspaceGenerationPackages({
				mode: apiModeFilter,
				status: statusFilter || undefined,
				limit: 100,
			});
			setPackages(resp.packages ?? []);
		} catch (e) {
			setError(String(e));
		} finally {
			setLoading(false);
		}
	}, [modeFilter, statusFilter]);

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
				const full = await getWorkspaceGenerationPackage(pkg.workspace_generation_package_id);
				setDetailPkg(full);
			} catch {
				// keep inline data
			} finally {
				setDetailLoading(false);
			}
		},
		[selectedId],
	);

	const handleArchiveToggle = useCallback(
		async (pkg: WorkspaceGenerationPackage) => {
			const nextStatus = pkg.status === "ARCHIVED" ? "DRAFT" : "ARCHIVED";
			try {
				const updated = await patchWorkspaceGenerationPackage(
					pkg.workspace_generation_package_id,
					{ status: nextStatus },
				);
				setPackages((prev) =>
					prev.map((p) => (p.workspace_generation_package_id === updated.workspace_generation_package_id ? updated : p)),
				);
				if (detailPkg?.workspace_generation_package_id === pkg.workspace_generation_package_id) {
					setDetailPkg(updated);
				}
			} catch (e) {
				setError(String(e));
			}
		},
		[detailPkg],
	);

	const handleDelete = useCallback(
		async (pkg: WorkspaceGenerationPackage) => {
			if (!window.confirm(`Delete package "${pkg.workspace_generation_package_id}"?\n\nThis cannot be undone.`)) return;
			try {
				await deleteWorkspaceGenerationPackage(pkg.workspace_generation_package_id);
				setPackages((prev) => prev.filter((p) => p.workspace_generation_package_id !== pkg.workspace_generation_package_id));
				if (selectedId === pkg.workspace_generation_package_id) {
					setSelectedId(null);
					setDetailPkg(null);
				}
			} catch (e) {
				setError(String(e));
			}
		},
		[selectedId],
	);

	const handleDetailUpdate = useCallback((updated: WorkspaceGenerationPackage) => {
		setDetailPkg(updated);
		setPackages((prev) =>
			prev.map((p) => (p.workspace_generation_package_id === updated.workspace_generation_package_id ? updated : p)),
		);
	}, []);

	// P5B: Checkbox toggle (no dependency on filtered — safe before filtered)
	const toggleCheck = useCallback((id: string, checked: boolean) => {
		setCheckedIds((prev) => {
			const next = new Set(prev);
			checked ? next.add(id) : next.delete(id);
			return next;
		});
	}, []);

	const filtered = packages.filter((p) => {
		if (modeFilter && getOperatorSurfaceMode(p) !== modeFilter) {
			return false;
		}
		if (!search) return true;
		const q = search.toLowerCase();
		return (
			p.workspace_generation_package_id.toLowerCase().includes(q) ||
			(p.product_name_snapshot || "").toLowerCase().includes(q) ||
			p.product_id.toLowerCase().includes(q)
		);
	});

	const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
	const safePage = Math.min(currentPage, totalPages);
	const paginated = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

	// P5B: Bulk handlers (defined after filtered so toggleSelectAll can reference it)
	const toggleSelectAll = () => {
		setCheckedIds((prev) =>
			prev.size === filtered.length && filtered.length > 0
				? new Set()
				: new Set(filtered.map((p) => p.workspace_generation_package_id)),
		);
	};

	const handleBulkArchive = async () => {
		if (!checkedIds.size) return;
		setBulkLoading(true);
		setError(null);
		try {
			await Promise.all(
				[...checkedIds].map((id) =>
					patchWorkspaceGenerationPackage(id, { status: "ARCHIVED" }),
				),
			);
			setPackages((prev) =>
				prev.map((p) =>
					checkedIds.has(p.workspace_generation_package_id) ? { ...p, status: "ARCHIVED" } : p,
				),
			);
			setCheckedIds(new Set());
		} catch (e) {
			setError(String(e));
		} finally {
			setBulkLoading(false);
		}
	};

	const handleApproveSelected = async () => {
		if (!checkedIds.size) return;
		setBulkLoading(true);
		setError(null);
		try {
			const resp = await approvePackages([...checkedIds]);
			const byId = new Map(resp.results.map((r) => [r.package_id, r]));
			setPackages((prev) =>
				prev.map((p) => {
					const r = byId.get(p.workspace_generation_package_id);
					return r?.ok
						? { ...p, production_status: r.production_status ?? "APPROVED" }
						: p;
				}),
			);
			const failed = resp.results.filter((r) => !r.ok);
			if (failed.length) {
				setError(
					`Approved ${resp.approved}; ${failed.length} failed: ${failed
						.map((f) => `${f.package_id}: ${f.error ?? "unknown error"}`)
						.join("; ")}`,
				);
			}
		} catch (e) {
			setError(String(e));
		} finally {
			setBulkLoading(false);
		}
	};

	const handleSendToProduction = async () => {
		const approvedIds = packages
			.filter(
				(p) =>
					checkedIds.has(p.workspace_generation_package_id) &&
					p.production_status === "APPROVED",
			)
			.map((p) => p.workspace_generation_package_id);
		if (!approvedIds.length) {
			setError(
				"No APPROVED packages in the selection — approve packages first, then send to production.",
			);
			return;
		}
		if (!sendConfig.model) {
			setError("Select an engine model before queueing the production run.");
			return;
		}
		setBulkLoading(true);
		setError(null);
		try {
			await createProductionRun({
				package_ids: approvedIds,
				interval_min_seconds: sendConfig.interval_min_seconds,
				interval_max_seconds: sendConfig.interval_max_seconds,
				cooldown_after_n_jobs: sendConfig.cooldown_after_n_jobs,
				cooldown_seconds: sendConfig.cooldown_seconds,
				model: sendConfig.model,
			});
			navigate("/production-queue");
		} catch (e) {
			setError(String(e));
			setBulkLoading(false);
		}
	};

	const handleBulkDelete = async () => {
		if (!checkedIds.size) return;
		if (!window.confirm(`Delete ${checkedIds.size} package(s)? This cannot be undone.`)) return;
		setBulkLoading(true);
		setError(null);
		try {
			await Promise.all(
				[...checkedIds].map((id) => deleteWorkspaceGenerationPackage(id)),
			);
			setPackages((prev) =>
				prev.filter((p) => !checkedIds.has(p.workspace_generation_package_id)),
			);
			if (selectedId && checkedIds.has(selectedId)) {
				setSelectedId(null);
				setDetailPkg(null);
			}
			setCheckedIds(new Set());
		} catch (e) {
			setError(String(e));
		} finally {
			setBulkLoading(false);
		}
	};

	const handleExportJSON = () => {
		const selected = packages.filter((p) => checkedIds.has(p.workspace_generation_package_id));
		const blob = new Blob([JSON.stringify(selected, null, 2)], { type: "application/json" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `phb-packages-${Date.now()}.json`;
		a.click();
		URL.revokeObjectURL(url);
	};

	return (
		<div className="flex min-w-0 flex-col gap-6 p-4 md:p-6">
			{/* Header with sub-tab switcher */}
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5">
				<div className="mb-4 flex items-center justify-between gap-3">
					<div>
						<div className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-100">
							Prompt Handoff Bank
						</div>
						<div className="mt-1 text-xs text-slate-400">
							{loading ? "Loading…" : `${filtered.length} package${filtered.length !== 1 ? "s" : ""}`}
						</div>
					</div>
					{detailPkg && getOperatorSurfaceRoute(detailPkg) && (
						<button
							type="button"
							onClick={() => navigate(getOperatorSurfaceRoute(detailPkg) ?? "/operator/f2v")}
							className="rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-2.5 text-sm font-semibold text-blue-100 hover:bg-blue-500/20"
						>
							→ Open {getOperatorSurfaceLabel(detailPkg)} Workspace
						</button>
					)}
				</div>
				<div className="flex gap-1 rounded-xl border border-slate-800 bg-slate-950 p-1">
					<button
						type="button"
						className="flex-1 rounded-lg bg-slate-800 py-2 text-[11px] font-bold uppercase tracking-[0.16em] text-slate-100 shadow-sm"
					>
						Prompt Handoff Bank
					</button>
						{(["T2V", "HYBRID", "F2V", "I2V", "IMG"] as const).map((m) => (
						<button
							key={m}
							type="button"
							onClick={() => navigate(MODE_OPERATOR_ROUTE[m])}
							className="flex-1 rounded-lg py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500 hover:bg-slate-800/60 hover:text-slate-200 transition-colors"
						>
							{m === "F2V" ? "FRAMES" : m}
						</button>
					))}
				</div>
				{error && (
					<div className="mt-4 rounded-xl border border-red-500/20 bg-red-500/10 px-3 py-2 text-[11px] text-red-200">
						{error}
					</div>
				)}
			</section>

			{/* Filters */}
			<section className="rounded-3xl border border-slate-800 bg-slate-950/80 p-5 space-y-3">
				<div className="flex flex-wrap items-center justify-between gap-2">
					<div className="flex items-center gap-1.5">
						<Filter size={13} className="text-slate-500" />
						<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">Mode</span>
					</div>
					<div className="flex flex-wrap gap-1.5">
						{SURFACE_FILTERS.map((filter) => {
							const active = (modeFilter || "ALL") === filter.id;
							return (
								<button
									key={filter.id}
									type="button"
									onClick={() => { setModeFilter(filter.id === "ALL" ? "" : filter.id); setCurrentPage(1); }}
									className={`px-3 py-1.5 rounded-full border text-[10px] font-bold uppercase tracking-[0.16em] transition-all ${active ? "border-blue-400/60 bg-blue-500/10 text-blue-200" : "border-slate-700 bg-slate-950 text-slate-400 hover:text-slate-200"}`}
								>
									{filter.label}
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
						{["ALL", "READY_MANUAL", "BLOCKED", "DRAFT", "ARCHIVED"].map((s) => {
							const active = (statusFilter || "ALL") === s;
							return (
								<button
									key={s}
									type="button"
									onClick={() => { setStatusFilter(s === "ALL" ? "" : s); setCurrentPage(1); }}
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
							onChange={(e) => { setSearch(e.target.value); setCurrentPage(1); }}
							placeholder="Search by product name or package ID…"
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
			</section>

			<div className="grid grid-cols-1 xl:grid-cols-2 gap-6 items-start">
				{/* Package list */}
				<div className="space-y-2">
					{loading ? (
						<div className="rounded-2xl border border-slate-800 bg-slate-900/40 py-12 text-center text-sm text-slate-500">
							Loading packages…
						</div>
					) : filtered.length === 0 ? (
						<div className="rounded-2xl border border-slate-800 bg-slate-900/40 py-12 text-center text-sm text-slate-500">
							No packages found. Generate a package from the Workspace (HYBRID, FRAMES, I2V, T2V or IMG tab).
						</div>
					) : (
						<div className="rounded-2xl border border-slate-800 bg-slate-950/80 overflow-hidden">
							{/* P5B: Bulk action toolbar */}
							{checkedIds.size > 0 && (
								<>
								<div className="flex flex-wrap items-center gap-2 px-3 py-2.5 bg-blue-500/8 border-b border-blue-500/20">
									<span className="text-[11px] font-bold text-blue-300 flex-1">
										{checkedIds.size} selected
									</span>
									<button
										type="button"
										disabled={bulkLoading}
										onClick={() => void handleApproveSelected()}
										className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 text-[11px] font-semibold hover:bg-emerald-500/20 transition-colors disabled:opacity-40"
									>
										<CheckCircle size={12} />
										Approve Selected ({checkedIds.size})
									</button>
									<button
										type="button"
										disabled={bulkLoading}
										onClick={() => setSendConfigOpen((v) => !v)}
										className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-indigo-500/30 bg-indigo-500/10 text-indigo-300 text-[11px] font-semibold hover:bg-indigo-500/20 transition-colors disabled:opacity-40"
									>
										<Send size={12} />
										Send Selected to Production
									</button>
									<button
										type="button"
										disabled={bulkLoading}
										onClick={() => void handleBulkArchive()}
										className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-300 text-[11px] font-semibold hover:bg-amber-500/20 transition-colors disabled:opacity-40"
									>
										<Archive size={12} />
										Archive ({checkedIds.size})
									</button>
									<button
										type="button"
										disabled={bulkLoading}
										onClick={() => void handleBulkDelete()}
										className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-red-300 text-[11px] font-semibold hover:bg-red-500/20 transition-colors disabled:opacity-40"
									>
										<Trash2 size={12} />
										Delete ({checkedIds.size})
									</button>
									<button
										type="button"
										onClick={handleExportJSON}
										className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-600 bg-slate-800 text-slate-300 text-[11px] font-semibold hover:bg-slate-700 transition-colors"
									>
										<FileDown size={12} />
										Export JSON
									</button>
									<button
										type="button"
										onClick={() => setCheckedIds(new Set())}
										className="text-[11px] text-slate-500 hover:text-slate-300 transition-colors px-1"
									>
										Clear
									</button>
								</div>
								{sendConfigOpen && (
									<div className="px-3 py-3 bg-indigo-500/5 border-b border-indigo-500/20 space-y-2">
										<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-indigo-300">
											Production Run Config — only APPROVED packages in the selection are queued
										</div>
										<div className="flex flex-wrap items-end gap-3">
											<label className="flex flex-col gap-1 text-[10px] text-slate-400">
												Interval min (s)
												<input
													type="number"
													min={0}
													value={sendConfig.interval_min_seconds}
													onChange={(e) =>
														setSendConfig((c) => ({ ...c, interval_min_seconds: Number(e.target.value) || 0 }))
													}
													className="w-24 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-indigo-400/50"
												/>
											</label>
											<label className="flex flex-col gap-1 text-[10px] text-slate-400">
												Interval max (s)
												<input
													type="number"
													min={0}
													value={sendConfig.interval_max_seconds}
													onChange={(e) =>
														setSendConfig((c) => ({ ...c, interval_max_seconds: Number(e.target.value) || 0 }))
													}
													className="w-24 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-indigo-400/50"
												/>
											</label>
											<label className="flex flex-col gap-1 text-[10px] text-slate-400">
												Cooldown after N jobs
												<input
													type="number"
													min={1}
													value={sendConfig.cooldown_after_n_jobs}
													onChange={(e) =>
														setSendConfig((c) => ({ ...c, cooldown_after_n_jobs: Number(e.target.value) || 1 }))
													}
													className="w-24 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-indigo-400/50"
												/>
											</label>
											<label className="flex flex-col gap-1 text-[10px] text-slate-400">
												Cooldown (s)
												<input
													type="number"
													min={0}
													value={sendConfig.cooldown_seconds}
													onChange={(e) =>
														setSendConfig((c) => ({ ...c, cooldown_seconds: Number(e.target.value) || 0 }))
													}
													className="w-24 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-indigo-400/50"
												/>
											</label>
											<label className="flex flex-col gap-1 text-[10px] text-slate-400">
												Engine model (required)
												<select
													value={sendConfig.model}
													onChange={(e) =>
														setSendConfig((c) => ({ ...c, model: e.target.value }))
													}
													className="w-52 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-indigo-400/50"
												>
													<option value="" disabled>
														Select engine model
													</option>
													{videoModels.map((m) => (
														<option key={m.key} value={m.ui_label}>
															{m.ui_label}
														</option>
													))}
												</select>
											</label>
											<button
												type="button"
												disabled={bulkLoading || !sendConfig.model}
												onClick={() => void handleSendToProduction()}
												className="flex items-center gap-1 px-4 py-2 rounded-lg border border-indigo-500/40 bg-indigo-500/15 text-indigo-200 text-[11px] font-bold hover:bg-indigo-500/25 transition-colors disabled:opacity-40"
											>
												<Send size={12} />
												Queue Production Run
											</button>
										</div>
										<div className="text-[10px] text-slate-500">
											Creating a run does NOT burn credits — execution starts fail-closed (dry-run) from the Production Queue page.
										</div>
									</div>
								)}
								</>
							)}
							<table className="w-full">
								<thead className="border-b border-slate-800">
									<tr className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-500">
										<th
											className="py-3 px-2 w-8 cursor-pointer"
											onClick={toggleSelectAll}
											title={checkedIds.size === filtered.length && filtered.length > 0 ? "Deselect all" : "Select all"}
										>
											{checkedIds.size === filtered.length && filtered.length > 0 ? (
												<CheckSquare size={14} className="text-blue-400" />
											) : (
												<Square size={14} className="text-slate-600" />
											)}
										</th>
										<th className="py-3 px-2 w-6"></th>
										<th className="py-3 px-3 text-left">Package ID</th>
										<th className="py-3 px-3 text-left">Mode</th>
										<th className="py-3 px-3 text-left">Product</th>
										<th className="py-3 px-3 text-left">Status</th>
										<th className="py-3 px-3 text-left">Created</th>
										<th className="py-3 px-3 w-20"></th>
									</tr>
								</thead>
								<tbody>
									{paginated.map((pkg) => (
										<PackageRow
											key={pkg.workspace_generation_package_id}
											pkg={pkg}
											isSelected={selectedId === pkg.workspace_generation_package_id}
											isChecked={checkedIds.has(pkg.workspace_generation_package_id)}
											onSelect={() => void handleSelect(pkg)}
											onCheck={(checked) => toggleCheck(pkg.workspace_generation_package_id, checked)}
											onArchiveToggle={() => void handleArchiveToggle(pkg)}
											onDelete={() => void handleDelete(pkg)}
										/>
									))}
								</tbody>
							</table>
						</div>
					)}
					{totalPages > 1 && (
						<div className="mt-3 flex items-center justify-between">
							<span className="text-[11px] text-slate-500">
								{(safePage - 1) * PAGE_SIZE + 1}–{Math.min(safePage * PAGE_SIZE, filtered.length)} of {filtered.length} packages
							</span>
							<div className="flex items-center gap-1">
								<button
									type="button"
									disabled={safePage <= 1}
									onClick={() => setCurrentPage((p) => p - 1)}
									className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-slate-300 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
								>
									← Prev
								</button>
								{Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
									<button
										key={n}
										type="button"
										onClick={() => setCurrentPage(n)}
										className={`min-w-[32px] rounded-lg border px-2 py-1.5 text-[11px] font-semibold transition-colors ${n === safePage ? "border-blue-500/40 bg-blue-500/15 text-blue-200" : "border-slate-700 bg-slate-900 text-slate-400 hover:bg-slate-800"}`}
									>
										{n}
									</button>
								))}
								<button
									type="button"
									disabled={safePage >= totalPages}
									onClick={() => setCurrentPage((p) => p + 1)}
									className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-[11px] font-semibold text-slate-300 transition-colors hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
								>
									Next →
								</button>
							</div>
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
							<div className="flex items-center gap-2">
								<StatusBadge status={detailPkg.status} />
								<button
									type="button"
									title={detailPkg.status === "ARCHIVED" ? "Unarchive" : "Archive"}
									onClick={() => void handleArchiveToggle(detailPkg)}
									className={`p-1.5 rounded-lg border transition-colors ${detailPkg.status === "ARCHIVED" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20" : "border-amber-500/30 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20"}`}
								>
									<Archive size={13} />
								</button>
								<button
									type="button"
									title="Delete"
									onClick={() => void handleDelete(detailPkg)}
									className="p-1.5 rounded-lg border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
								>
									<Trash2 size={13} />
								</button>
							</div>
						</div>
						{detailLoading ? (
							<div className="py-8 text-center text-sm text-slate-500">
								Loading detail…
							</div>
						) : (
							<PackageDetailPanel pkg={detailPkg} onUpdate={handleDetailUpdate} />
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
