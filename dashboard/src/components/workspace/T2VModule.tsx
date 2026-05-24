import { ArrowRight, Info } from "lucide-react";
import { useEffect, useState } from "react";
import type {
	Orientation,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
} from "../../types";

interface T2VModuleProps {
	onExecute: (data: WorkspaceExecutePayload) => void;
	isExecuting: boolean;
	compact?: boolean;
	workspacePackage?: WorkspaceExecutionPackage | null;
}

export default function T2VModule({
	onExecute,
	isExecuting,
	compact = false,
	workspacePackage = null,
}: T2VModuleProps) {
	// --- States ---
	const [manualPrompt, setManualPrompt] = useState("");
	const [isManualOverride, setIsManualOverride] = useState(false);

	// Mirror States
	const [orientation, setOrientation] = useState<Orientation>("VERTICAL");
	const [model, setModel] = useState("Veo 3.1 - Pro");
	const [count, setCount] = useState(1);

	useEffect(() => {
		if (!workspacePackage || workspacePackage.mode !== "T2V") return;
		setManualPrompt(workspacePackage.prompt_text);
		setModel(workspacePackage.model || "Veo 3.1 - Pro");
		setOrientation(
			workspacePackage.aspect_ratio === "16:9" ? "HORIZONTAL" : "VERTICAL",
		);
		setIsManualOverride(false);
	}, [workspacePackage]);

	// --- Handlers ---
	const handleExecute = () => {
		onExecute({
			prompt: manualPrompt,
			orientation,
			model,
			count,
			product_id: workspacePackage?.product_id,
			prompt_package_snapshot_id: workspacePackage?.prompt_package_snapshot_id,
			workspace_execution_package_id:
				workspacePackage?.workspace_execution_package_id,
			prompt_fingerprint: workspacePackage?.prompt_fingerprint,
			asset_fingerprints:
				workspacePackage?.request_lineage_payload.asset_fingerprints ?? [],
			request_lineage_payload: workspacePackage?.request_lineage_payload,
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
									<div key={block.block_index} className="space-y-1">
										<div className="flex items-center gap-2">
											<span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
												Block {block.block_index} — {block.block_role}
											</span>
											<span className="text-[10px] text-slate-500">
												{block.duration_seconds}s · {block.shot_count} shot(s)
											</span>
										</div>
										<textarea
											className="w-full h-48 bg-slate-950 border border-slate-700 rounded-xl p-4 text-sm text-slate-300 font-mono outline-none transition-all resize-none"
											readOnly
											value={block.engine_prompt_text}
											onClick={(e) =>
												(e.target as HTMLTextAreaElement).select()
											}
										/>
									</div>
								))}
								<div className="rounded-xl border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
									EXTEND mode — copy each block separately into the video
									engine. Do NOT paste both blocks into one generation.
								</div>
							</div>
						) : (
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

				<div className="pt-4">
					<button
						type="button"
						onClick={handleExecute}
						disabled={isExecuting || !manualPrompt}
						className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
					>
						{isExecuting ? "Executing T2V Sequence..." : "START GENERATION"}
						{!isExecuting && <ArrowRight size={18} />}
					</button>
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
							<p className="text-xs font-bold text-slate-400">
								Generation Model
							</p>
							<select
								title="Select generation model"
								value={model}
								onChange={(e) => setModel(e.target.value)}
								className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-[10px] font-bold text-slate-300 outline-none"
							>
								<option>Veo 3.1 - Pro</option>
								<option>Veo 3.1 - Lite</option>
								<option>Nano Banana 2</option>
							</select>
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
						No images are uploaded. Google Flow has <strong className="text-blue-300">nothing to look at</strong> — every visual detail must come from the prompt text.
					</p>
					<p className="text-[10px] font-bold text-blue-300/80 uppercase tracking-[0.12em]">Prompt must include:</p>
					<ul className="text-[10px] text-blue-300/55 leading-relaxed space-y-1 list-disc list-inside">
						<li>Character — appearance, skin tone, body type, posture, wardrobe (detailed)</li>
						<li>Product — name, size &amp; scale description (e.g. "lip balm, palm-sized, fits between two fingers")</li>
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
