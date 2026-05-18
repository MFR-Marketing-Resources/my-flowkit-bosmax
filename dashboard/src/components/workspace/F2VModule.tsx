import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { handleAssetUpload } from "../../api/assets";
import type {
	Orientation,
	UploadedAsset,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
} from "../../types";
import WorkspaceImageAssetSlot from "./WorkspaceImageAssetSlot";

interface F2VModuleProps {
	onExecute: (data: WorkspaceExecutePayload) => void;
	isExecuting: boolean;
	compact?: boolean;
	workspacePackage?: WorkspaceExecutionPackage | null;
}

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
}: F2VModuleProps) {
	// --- States ---
	const [manualPrompt, setManualPrompt] = useState("");
	const [isManualOverride, setIsManualOverride] = useState(false);
	const [orientation, setOrientation] = useState<Orientation>("VERTICAL");
	const [model, setModel] = useState("Veo 3.1 - Lite");
	const [count, setCount] = useState(1);
	const [isUploading, setIsUploading] = useState(false);
	const [startPreviewFailed, setStartPreviewFailed] = useState(false);

	// Frame Assets
	const [startAsset, setStartAsset] = useState<UploadedAsset | null>(null);
	const [endAsset, setEndAsset] = useState<UploadedAsset | null>(null);

	useEffect(() => {
		if (!workspacePackage || workspacePackage.mode !== "F2V") return;
		setManualPrompt(workspacePackage.prompt_text);
		setModel(workspacePackage.model || "Veo 3.1 - Lite");
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
		onExecute({
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
			className={`flex h-full gap-6 ${compact ? "flex-col" : "max-[1280px]:flex-col"}`}
		>
			<div
				className={`flex-1 space-y-6 overflow-y-auto pb-12 ${compact ? "pr-0" : "pr-2"}`}
			>
				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						1. Visual Assets (F2V Slots)
					</h3>
					<div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
						<WorkspaceImageAssetSlot
							key={
								startAsset?.assetFingerprint ??
								startAsset?.previewUrl ??
								"start-empty"
							}
							title="Start Frame"
							description={
								workspacePackage
									? "Resolved product image loads by default"
									: "Click upload to attach a Start Frame"
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
							title="End Frame (Optional)"
							description="Click upload to attach an ending frame"
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
							<div
								className={`rounded-xl border px-3 py-2 text-[11px] ${isManualOverride ? "border-amber-500/30 bg-amber-500/10 text-amber-100" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-100"}`}
							>
								{isManualOverride
									? "Manual override active. Start Frame can still fall back to the cached product image."
									: "Approved package loaded. Start Frame defaults to the cached product image; End Frame stays optional."}
							</div>
						) : null}
						{startPreviewFailed ? (
							<div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-100">
								Image preview failed. Upload a manual Start Frame replacement
								before sending this F2V job.
							</div>
						) : null}
						<textarea
							className="w-full h-40 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
							placeholder="Describe the golden transition..."
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
				className={`${compact ? "w-full" : "w-72 max-[1280px]:w-full"} flex-shrink-0 flex flex-col gap-6 overflow-y-auto pb-12`}
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
								<option>Veo 3.1 - Lite</option>
								<option>Veo 3.1 - Pro</option>
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
			</div>
		</div>
	);
}
