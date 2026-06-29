import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { handleAssetUpload } from "../../api/assets";
import type {
	Orientation,
	UploadedAsset,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
} from "../../types";
import ModelSelect, {
	type VideoModel,
	normalizeModel,
} from "./ModelSelect";
import WorkspaceImageAssetSlot from "./WorkspaceImageAssetSlot";

interface F2VModuleProps {
	onExecute: (data: WorkspaceExecutePayload) => void;
	isExecuting: boolean;
	compact?: boolean;
	workspacePackage?: WorkspaceExecutionPackage | null;
	videoModels: VideoModel[];
}

const F2V_DEFAULT_MODEL = "Veo 3.1 - Lite";

function toUploadedAsset(
	asset:
		| WorkspaceExecutionPackage["resolved_assets"][number]
		| null
		| undefined,
): UploadedAsset | null {
	if (!asset) return null;
	return {
		mediaId: asset.media_id ?? null,
		fileName: asset.file_name,
		label: asset.label,
		previewUrl: asset.preview_url,
		downloadUrl: asset.download_url,
		localFilePath: asset.local_file_path ?? undefined,
		assetId: asset.asset_id,
		assetFingerprint: asset.asset_fingerprint,
		assetSource: asset.asset_source,
		isDefaultPackageAsset: true,
		previewRenderableStatus: asset.preview_renderable_status,
		previewErrorDetail: asset.preview_error_detail ?? null,
		localImagePathPresent: asset.local_image_path_present,
		remoteImageUrlPresent: asset.remote_image_url_present,
	};
}

export default function F2VModule({
	onExecute,
	isExecuting,
	compact = false,
	workspacePackage = null,
	videoModels,
}: F2VModuleProps) {
	// --- States ---
	const [manualPrompt, setManualPrompt] = useState("");
	const [isManualOverride, setIsManualOverride] = useState(false);
	const [orientation, setOrientation] = useState<Orientation>("VERTICAL");
	const [model, setModel] = useState(F2V_DEFAULT_MODEL);
	const [count, setCount] = useState(1);
	const [isUploading, setIsUploading] = useState(false);
	const [startPreviewFailed, setStartPreviewFailed] = useState(false);

	// Frame Assets
	const [startAsset, setStartAsset] = useState<UploadedAsset | null>(null);
	const [endAsset, setEndAsset] = useState<UploadedAsset | null>(null);

	// Re-normalize once the SSOT registry arrives — a package may hydrate first, so an
	// unknown/retired model would otherwise stay ghosted and 422 on execute (patch I3b).
	useEffect(() => {
		setModel((m) => normalizeModel(m, videoModels));
	}, [videoModels]);

	useEffect(() => {
		if (!workspacePackage || workspacePackage.mode !== "F2V") return;
		setManualPrompt(workspacePackage.prompt_text);
		setModel(normalizeModel(workspacePackage.model, videoModels));
		setOrientation(
			workspacePackage.aspect_ratio === "16:9" ? "HORIZONTAL" : "VERTICAL",
		);
		setStartAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find(
					(asset) => asset.slot_key === "start_frame",
				),
			),
		);
		setEndAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find(
					(asset) => asset.slot_key === "end_frame",
				),
			),
		);
		setIsManualOverride(false);
		setStartPreviewFailed(false);
	}, [workspacePackage]);

	// --- Handlers ---
	const handleFileChange = async (
		type: "start" | "end",
		e: React.ChangeEvent<HTMLInputElement>,
	) => {
		const file = e.target.files?.[0];
		if (!file) return;

		setIsUploading(true);
		try {
			console.log(`[F2V] Uploading ${type} to agent...`);
			const asset = await handleAssetUpload(file);
			console.log(`[F2V] Upload success:`, asset.mediaId);

			if (type === "start") {
				setStartAsset(asset);
				setStartPreviewFailed(false);
			} else setEndAsset(asset);
			setIsManualOverride(Boolean(workspacePackage));
		} catch (error: unknown) {
			const message = error instanceof Error ? error.message : "Unknown error";
			console.error(`[F2V] ${type} upload failed:`, error);
			alert(`UPLOAD ERROR: ${message}. Check your agent.`);
		} finally {
			setIsUploading(false);
		}
	};

	const handleExecute = () => {
		// Dispatch through the Google Flow V2 runtime lane
		// (GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE): auto-acquire a healthy V2 surface,
		// then Upload media -> Add to Prompt -> Settings -> Prompt and STOP before
		// Generate. The backend still materializes the remote Start image to a local
		// file for the CDP file chooser (lane recognised by flow.py).
		onExecute({
			lane: "GFV2_UPLOAD_SETTINGS_PROMPT_GENERATE",
			gfv2: true,
			prompt: manualPrompt,
			orientation,
			model,
			count,
			// Pass the full asset object (including previewUrl/base64) so extension can use it directly
			startAsset: startAsset,
			endAsset: endAsset,
			product_id: workspacePackage?.product_id,
			prompt_package_snapshot_id: workspacePackage?.prompt_package_snapshot_id,
			workspace_execution_package_id:
				workspacePackage?.workspace_execution_package_id,
			prompt_fingerprint: workspacePackage?.prompt_fingerprint,
			asset_fingerprints:
				workspacePackage?.request_lineage_payload.asset_fingerprints ?? [],
			request_lineage_payload: workspacePackage?.request_lineage_payload,
			mode: "F2V",
		});
	};

	return (
		<div
			className={`space-y-6 ${compact ? "" : "xl:grid xl:grid-cols-[minmax(0,1fr)_18rem] xl:items-start xl:gap-6 xl:space-y-0"}`}
		>
			<div className="space-y-6 pb-12">
				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						1. Visual Assets (F2V Slots)
					</h3>
					<div className="grid gap-3">
						<div className="rounded-xl border border-blue-500/20 bg-blue-500/5 px-3 py-3 text-[11px] text-blue-200/70 space-y-1">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-blue-300/80">
								F2V — Reference Image Logic
							</div>
							<p>
								Every image uploaded here becomes a{" "}
								<strong className="text-blue-200">reference image</strong>. The
								model SEES the image — your prompt describes{" "}
								<strong className="text-blue-200">what happens to it</strong>,
								not what it looks like.
							</p>
							<ul className="list-disc list-inside space-y-0.5 text-blue-300/50 mt-1">
								<li>
									Start = avatar photo → describe action + product details
									on-the-fly (no product ref, so describe size/scale/name)
								</li>
								<li>
									Start = product photo → describe avatar fully on-the-fly
									(appearance, wardrobe) + action
								</li>
								<li>
									Start + End both uploaded → describe the transition/event
									between them
								</li>
							</ul>
						</div>
						{workspacePackage ? (
							<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-[11px] text-emerald-100">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-200/80">
									Auto Asset Baseline
								</div>
								<div className="mt-1">
									Resolved product image loads as the Start Frame reference. End
									Frame is optional.
								</div>
							</div>
						) : (
							<div className="rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-3 text-[11px] text-slate-300">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
									Manual Asset Upload
								</div>
								<div className="mt-1">
									No approved package loaded. Upload your reference image(s)
									manually.
								</div>
							</div>
						)}
					</div>
					<div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
						<WorkspaceImageAssetSlot
							key={
								startAsset?.assetFingerprint ??
								startAsset?.previewUrl ??
								"start-empty"
							}
							title="Start Frame (Reference Image)"
							description={
								workspacePackage
									? "Resolved product image — reference image for this generation"
									: "Upload reference image: avatar photo OR product photo"
							}
							asset={startAsset}
							isUploading={isUploading}
							accentClassName="group-hover:bg-blue-500/10 group-hover:text-blue-400"
							uploadTitle="Upload start frame"
							onFileChange={(e) => handleFileChange("start", e)}
							onPreviewStateChange={setStartPreviewFailed}
						/>
						<WorkspaceImageAssetSlot
							key={
								endAsset?.assetFingerprint ??
								endAsset?.previewUrl ??
								"end-empty"
							}
							title="End Frame (Optional Reference)"
							description="Upload a second reference image — model generates the transition between start and end"
							asset={endAsset}
							isUploading={isUploading}
							accentClassName="group-hover:bg-purple-500/10 group-hover:text-purple-400"
							uploadTitle="Upload end frame"
							onFileChange={(e) => handleFileChange("end", e)}
						/>
					</div>
				</section>

				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						2. Prompt Injection
					</h3>
					<div className="p-4 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
						{workspacePackage ? (
							<div className="grid gap-3">
								<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-[11px] text-emerald-100">
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-200/80">
										Auto Package Baseline
									</div>
									<div className="mt-1">
										Approved package loaded. Start Frame defaults to the cached
										product image; End Frame stays optional.
									</div>
								</div>
								<div
									className={`rounded-xl border px-3 py-3 text-[11px] ${isManualOverride ? "border-amber-500/30 bg-amber-500/10 text-amber-100" : "border-slate-800 bg-slate-950/40 text-slate-300"}`}
								>
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
										Manual Override
									</div>
									<div className="mt-1">
										Editing the prompt below overrides the auto-compiled package
										prompt for this run only.
									</div>
									{isManualOverride ? (
										<div className="mt-2 text-amber-100">
											Manual override active. Start Frame can still fall back to
											the cached product image.
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
						{startPreviewFailed ? (
							<div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-100">
								Image preview failed. Upload a manual Start Frame replacement
								before sending this F2V job.
							</div>
						) : null}
						{/* Multi-block (EXTEND): show each block in its own separate box */}
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
							/* Single block (SINGLE mode): editable prompt */
							<textarea
								className="w-full h-40 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
								placeholder="Describe WHAT HAPPENS to the reference image(s). The model sees the image — don't re-describe it. Instead: action (character holds product, walks into scene), any on-the-fly subject details not in the image (e.g. product size if start frame is avatar), camera movement..."
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
					</div>
				</section>

				<div className="pt-4">
					<button
						type="button"
						onClick={handleExecute}
						disabled={
							isExecuting ||
							isUploading ||
							!manualPrompt ||
							!startAsset ||
							startPreviewFailed
						}
						className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
					>
						{isUploading
							? "Preparing Assets..."
							: isExecuting
								? "Executing Sequence..."
								: "START GENERATION"}
						{!isExecuting && !isUploading && <ArrowRight size={18} />}
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
								{["VERTICAL", "HORIZONTAL"].map((o) => (
									<button
										type="button"
										key={o}
										onClick={() => setOrientation(o as Orientation)}
										className={`py-2 rounded-lg text-[10px] font-bold border transition-all ${orientation === o ? "bg-blue-600/20 border-blue-500 text-blue-400" : "bg-slate-950 border-slate-800 text-slate-500"}`}
									>
										{o === "VERTICAL" ? "9:16 (Vertical)" : "16:9 (Horizontal)"}
									</button>
								))}
							</div>
						</div>
						<ModelSelect
							models={videoModels}
							value={model}
							onChange={setModel}
						/>
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

				<section className="p-6 rounded-2xl border border-blue-500/10 bg-blue-500/5 space-y-3">
					<h4 className="text-[10px] font-bold text-blue-400 uppercase tracking-widest">
						F2V — Prompt Guide
					</h4>
					<div className="text-[10px] text-blue-300/55 leading-relaxed space-y-2">
						<p>
							<strong className="text-blue-300/80">
								Image uploaded = reference.
							</strong>{" "}
							Model sees it — describe the <em>action</em>, not the appearance.
						</p>
						<p>
							<strong className="text-blue-300/80">
								Subject not in any image (on the fly)
							</strong>{" "}
							→ describe fully: look, skin tone, wardrobe, body type.
						</p>
						<p>
							<strong className="text-blue-300/80">Product size</strong> →
							always state scale explicitly (e.g. "lip balm, palm-sized, fits
							between two fingers") — Google Flow struggles with size without a
							verbal anchor.
						</p>
						<p>
							<strong className="text-blue-300/80">Both frames uploaded</strong>{" "}
							→ describe the event/transition between them.
						</p>
					</div>
				</section>
			</div>
		</div>
	);
}
