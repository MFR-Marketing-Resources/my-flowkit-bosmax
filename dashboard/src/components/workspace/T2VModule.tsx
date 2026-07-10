import { ArrowRight, Info } from "lucide-react";
import { useEffect, useState } from "react";
import type {
	Orientation,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
} from "../../types";
import CopyBindingGate from "../copywriting/CopyBindingGate";

interface T2VModuleProps {
	onExecute: (data: WorkspaceExecutePayload) => void;
	isExecuting: boolean;
	compact?: boolean;
	workspacePackage?: WorkspaceExecutionPackage | null;
	copyReady?: boolean;
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

type PromptAuditBlock = NonNullable<
	WorkspaceExecutionPackage["prompt_blocks"]
>[number];

interface PromptAuditSection {
	heading: string;
	sectionNumber: number | null;
	title: string;
	body: string;
}

function parsePromptSections(text: string): PromptAuditSection[] {
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

function PromptAuditCard({
	label,
	text,
	block,
}: {
	label: string;
	text: string;
	block?: PromptAuditBlock;
}) {
	const [copied, setCopied] = useState(false);
	const sections = parsePromptSections(text);
	const presentHeadings = new Set(sections.map((section) => section.heading));
	const missingSections = CANONICAL_PROMPT_SECTIONS.filter(
		(heading) => !presentHeadings.has(heading),
	);
	const metaChips = [
		block?.block_role ? `Role ${block.block_role}` : null,
		block?.duration_seconds ? `${block.duration_seconds}s` : null,
		block?.shot_count
			? `${block.shot_count} shot${block.shot_count > 1 ? "s" : ""}`
			: null,
	].filter(Boolean) as string[];

	const handleCopy = () => {
		navigator.clipboard.writeText(text || "").then(() => {
			setCopied(true);
			window.setTimeout(() => setCopied(false), 2200);
		});
	};

	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/70 overflow-hidden">
			<div className="flex flex-col gap-3 border-b border-slate-800 px-4 py-3 md:flex-row md:items-start md:justify-between">
				<div className="space-y-2">
					<div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-200">
						{label}
					</div>
					<div className="flex flex-wrap gap-2">
						<span className="rounded-full border border-slate-700 bg-slate-900 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-300">
							{sections.length}/9 sections
						</span>
						{metaChips.map((chip) => (
							<span
								key={chip}
								className="rounded-full border border-slate-800 bg-slate-900/70 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400"
							>
								{chip}
							</span>
						))}
						{missingSections.length === 0 ? (
							<span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-200">
								Canonical 9-section structure
							</span>
						) : (
							<span className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-200">
								Missing{" "}
								{missingSections
									.map((heading) => heading.replace("SECTION ", "S"))
									.join(", ")}
							</span>
						)}
					</div>
				</div>
				<button
					type="button"
					onClick={handleCopy}
					className={`rounded-lg border px-3 py-2 text-[11px] font-semibold transition-colors ${copied ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200" : "border-blue-500/30 bg-blue-500/10 text-blue-100 hover:bg-blue-500/20"}`}
				>
					{copied ? "Copied" : "Copy Prompt"}
				</button>
			</div>
			{sections.length > 0 ? (
				<div className="divide-y divide-slate-800">
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
							<summary className="cursor-pointer list-none px-4 py-3">
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
							<pre className="border-t border-slate-800 px-4 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
								{section.body || "(empty section)"}
							</pre>
						</details>
					))}
				</div>
			) : (
				<pre className="px-4 py-3 text-xs text-slate-300 font-mono whitespace-pre-wrap leading-relaxed">
					{text || "(no prompt text)"}
				</pre>
			)}
		</div>
	);
}

export default function T2VModule({
	onExecute,
	isExecuting,
	compact = false,
	workspacePackage = null,
	copyReady = false,
}: T2VModuleProps) {
	// --- States ---
	const [manualPrompt, setManualPrompt] = useState("");
	const [isManualOverride, setIsManualOverride] = useState(false);
	const [copyFallbackConfirmed, setCopyFallbackConfirmed] = useState(false);

	// Mirror States
	const [orientation, setOrientation] = useState<Orientation>("VERTICAL");
	const [count, setCount] = useState(1);
	const packagePromptText =
		workspacePackage?.prompt_blocks?.[0]?.engine_prompt_text ??
		workspacePackage?.prompt_text ??
		"";

	useEffect(() => {
		if (workspacePackage?.mode !== "T2V") return;
		setManualPrompt(workspacePackage.prompt_text);
		setOrientation(
			workspacePackage.aspect_ratio === "16:9" ? "HORIZONTAL" : "VERTICAL",
		);
		setIsManualOverride(false);
	}, [workspacePackage]);

	// --- Copywriting binding gate (Phase B enforcement) ---
	// T2V does not rebuild on execute, so the run is copy-bound ONLY when the loaded
	// package was compiled from an approved Copy Set (copy_binding.copy_source ===
	// "selected_copy_set"). A merely-selected-but-uncompiled Copy Set is NOT bound.
	// Otherwise SEND stays blocked until the operator explicitly confirms fallback.
	const boundCopySetId =
		workspacePackage?.copy_binding?.copy_source === "selected_copy_set"
			? (workspacePackage?.copy_binding?.copy_set_id ?? null)
			: null;
	const copyBound = Boolean(boundCopySetId);
	const copyGateBlocked = !copyBound && !copyFallbackConfirmed;

	// --- Handlers ---
	const handleExecute = () => {
		if (copyGateBlocked) return;
		onExecute({
			lane: "WORKSPACE_FLOW_EDITOR_RUNTIME",
			stop_after_stage: "PROMPT_EDITABLE_AFTER_INSERT",
			prompt: manualPrompt,
			orientation,
			count,
			product_id: workspacePackage?.product_id,
			prompt_package_snapshot_id: workspacePackage?.prompt_package_snapshot_id,
			workspace_execution_package_id:
				workspacePackage?.workspace_execution_package_id,
			prompt_fingerprint: workspacePackage?.prompt_fingerprint,
			asset_fingerprints:
				workspacePackage?.request_lineage_payload.asset_fingerprints ?? [],
			copy_set_id: copyBound ? boundCopySetId : null,
			copy_fallback_confirmed: copyBound ? false : copyFallbackConfirmed,
			request_lineage_payload: {
				...(workspacePackage?.request_lineage_payload ?? {}),
				copy_binding_gate: copyBound
					? { copy_bound: true, copy_set_id: boundCopySetId }
					: {
							copy_bound: false,
							copy_fallback_confirmed: true,
							copy_source: "operator_confirmed_fallback",
						},
			},
			mode: "T2V",
		});
	};

	return (
		<div
			className={`space-y-6 ${compact ? "" : "xl:grid xl:grid-cols-[minmax(0,1fr)_18rem] xl:items-start xl:gap-6 xl:space-y-0"}`}
		>
			<div className="space-y-6 pb-12">
				{/* 1. Prompt Injection - Mirroring Google Flow */}
				<section className="space-y-4">
					<div className="flex items-center justify-between">
						<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
							1. Prompt Injection
						</h3>
					</div>
					<div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
						{workspacePackage ? (
							<div className="grid gap-3">
								<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-[11px] text-emerald-100">
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-200/80">
										Auto Package Baseline
									</div>
									<div className="mt-1">
										Approved product package loaded. This prompt is locked by
										default until you override it.
									</div>
								</div>
								<div
									className={`rounded-xl border px-3 py-3 text-[11px] ${isManualOverride ? "border-amber-500/30 bg-amber-500/10 text-amber-100" : "border-slate-800 bg-slate-950/40 text-slate-300"}`}
								>
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
										Manual Override
									</div>
									<div className="mt-1">
										Editing the prompt below overrides the approved package for
										this run only.
									</div>
									{isManualOverride ? (
										<div className="mt-2 text-amber-100">
											Manual override active. Approved package remains the
											source-of-truth baseline.
										</div>
									) : null}
								</div>
							</div>
						) : (
							<div className="rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-3 text-[11px] text-slate-300">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
									Manual Prompt Injection
								</div>
								<div className="mt-1">
									No approved package is loaded. The prompt below is 100%
									manual.
								</div>
							</div>
						)}
						{workspacePackage?.prompt_blocks &&
						workspacePackage.prompt_blocks.length > 1 ? (
							<div className="space-y-4">
								{workspacePackage.prompt_blocks.map((block) => (
									<PromptAuditCard
										key={block.block_index}
										label={`Block ${block.block_index} Audit`}
										text={block.engine_prompt_text}
										block={block}
									/>
								))}
								<div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
									EXTEND mode — copy each block separately into the video
									engine. Do NOT paste both blocks into one generation.
								</div>
							</div>
						) : (
							<div className="space-y-3">
								{workspacePackage && packagePromptText ? (
									<PromptAuditCard
										label="Approved Package Baseline"
										text={packagePromptText}
									/>
								) : null}
								<textarea
									className="w-full h-80 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
									placeholder="No reference images — describe EVERYTHING: character appearance, skin tone, body type, wardrobe, posture · product name + size/scale (e.g. 'lip balm, fits in palm, finger-sized') · action (character holding product, demonstrating it) · camera angle/shot type · audio/dialogue script..."
									value={manualPrompt}
									onChange={(e) => {
										const next = e.target.value;
										setManualPrompt(next);
										setIsManualOverride(
											Boolean(workspacePackage?.prompt_text) &&
												next !== workspacePackage?.prompt_text,
										);
									}}
								/>
							</div>
						)}
						<div className="flex items-center gap-2 text-[10px] text-slate-500 italic">
							<Info size={12} />
							<span>
								BOSMAX Studio will inject this prompt directly into Google
								Flow's T2V composer.
							</span>
						</div>
					</div>
				</section>

				<div className="pt-4 space-y-3">
					<CopyBindingGate
						copyBound={copyBound}
						ready={copyReady}
						fallbackConfirmed={copyFallbackConfirmed}
						onToggleFallback={setCopyFallbackConfirmed}
					/>
					<button
						type="button"
						onClick={handleExecute}
						disabled={isExecuting || !manualPrompt || copyGateBlocked}
						className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
					>
						{isExecuting ? "Sending to Flow Editor..." : "SEND TO FLOW EDITOR"}
						{!isExecuting && <ArrowRight size={18} />}
					</button>
					<p className="mt-2 text-center text-xs text-slate-400">
						Inserts the prompt into the Flow editor and stops — does not
						auto-generate, poll, or download.
					</p>
				</div>
			</div>

			<div
				className={`${compact ? "space-y-6" : "space-y-6 xl:sticky xl:top-4"}`}
			>
				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						Flow Mirror Settings
					</h3>
					<div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-6">
						<div className="space-y-3">
							<p className="text-xs font-bold text-slate-400">Aspect Ratio</p>
							<div className="grid grid-cols-2 gap-2">
								<button
									type="button"
									onClick={() => setOrientation("VERTICAL")}
									className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${orientation === "VERTICAL" ? "bg-blue-600/20 border-blue-500 text-blue-400" : "bg-slate-950 border-slate-800 text-slate-500"}`}
								>
									9:16 (Vertical)
								</button>
								<button
									type="button"
									onClick={() => setOrientation("HORIZONTAL")}
									className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${orientation === "HORIZONTAL" ? "bg-blue-600/20 border-blue-500 text-blue-400" : "bg-slate-950 border-slate-800 text-slate-500"}`}
								>
									16:9 (Horizontal)
								</button>
							</div>
						</div>

						<div className="space-y-3">
							<p className="text-xs font-bold text-slate-400">Count</p>
							<div className="grid grid-cols-4 gap-2">
								{[1, 2, 3, 4].map((v) => (
									<button
										type="button"
										key={v}
										onClick={() => setCount(v)}
										className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${count === v ? "bg-purple-600/20 border-purple-500 text-purple-400" : "bg-slate-950 border-slate-800 text-slate-500"}`}
									>
										{v}x
									</button>
								))}
							</div>
						</div>
					</div>
				</section>

				<section className="p-6 rounded-2xl border border-blue-500/20 bg-blue-500/5 space-y-3">
					<h4 className="text-[10px] font-bold text-blue-400 uppercase tracking-widest">
						T2V — No Reference Images
					</h4>
					<p className="text-[10px] text-blue-300/70 leading-relaxed">
						No images are uploaded. Google Flow has{" "}
						<strong className="text-blue-300">nothing to look at</strong> —
						every visual detail must come from the prompt text.
					</p>
					<p className="text-[10px] font-bold text-blue-300/80 uppercase tracking-[0.12em]">
						Prompt must include:
					</p>
					<ul className="text-[10px] text-blue-300/55 leading-relaxed space-y-1 list-disc list-inside">
						<li>
							Character — appearance, skin tone, body type, posture, wardrobe
							(detailed)
						</li>
						<li>
							Product — name, size &amp; scale description (e.g. "lip balm,
							palm-sized, fits between two fingers")
						</li>
						<li>Action — what character does with the product</li>
						<li>Camera — shot type, angle, movement</li>
						<li>Audio — dialogue or voiceover script</li>
					</ul>
					<p className="text-[10px] text-blue-300/30 italic">
						Google Flow cannot infer what it cannot see. Specificity = quality.
					</p>
				</section>
			</div>
		</div>
	);
}
