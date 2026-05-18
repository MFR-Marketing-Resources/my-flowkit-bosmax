import { ArrowRight } from "lucide-react";
import { useEffect, useState } from "react";
import { handleAssetUpload } from "../../api/assets";
import type {
	UploadedAsset,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
} from "../../types";
import WorkspaceImageAssetSlot from "./WorkspaceImageAssetSlot";

interface IMGModuleProps {
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

export default function IMGModule({
	onExecute,
	isExecuting,
	compact = false,
	workspacePackage = null,
}: IMGModuleProps) {
	// --- States ---
	const [manualPrompt, setManualPrompt] = useState("");
	const [isManualOverride, setIsManualOverride] = useState(false);
	const [aspectRatio, setAspectRatio] = useState("9:16");
	const [model] = useState("Nano Banana 2");
	const [count, setCount] = useState(1);
	const [isUploading, setIsUploading] = useState(false);

	// Image Assets
	const [subjectAsset, setSubjectAsset] = useState<UploadedAsset | null>(null);
	const [sceneAsset, setSceneAsset] = useState<UploadedAsset | null>(null);
	const [styleAsset, setStyleAsset] = useState<UploadedAsset | null>(null);

	useEffect(() => {
		if (!workspacePackage || workspacePackage.mode !== "IMG") return;
		setManualPrompt(workspacePackage.prompt_text);
		setAspectRatio(workspacePackage.aspect_ratio || "9:16");
		setSubjectAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find(
					(asset) => asset.slot_key === "subject",
				),
			),
		);
		setSceneAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find(
					(asset) => asset.slot_key === "scene",
				),
			),
		);
		setStyleAsset(
			toUploadedAsset(
				workspacePackage.resolved_assets.find(
					(asset) => asset.slot_key === "style",
				),
			),
		);
		setIsManualOverride(false);
	}, [workspacePackage]);

	// --- Handlers ---
	const handleFileChange = async (
		type: "subject" | "scene" | "style",
		e: React.ChangeEvent<HTMLInputElement>,
	) => {
		const file = e.target.files?.[0];
		if (!file) return;

		setIsUploading(true);
		try {
			const asset = await handleAssetUpload(file);
			if (type === "subject") setSubjectAsset(asset);
			else if (type === "scene") setSceneAsset(asset);
			else setStyleAsset(asset);
			setIsManualOverride(Boolean(workspacePackage));
		} catch (error) {
			console.error("Upload failed:", error);
			alert("Upload failed. Check if local agent is running.");
		} finally {
			setIsUploading(false);
		}
	};

	const handleExecute = () => {
		onExecute({
			prompt: manualPrompt,
			aspectRatio,
			model,
			count,
			refs: {
				subjectAsset: subjectAsset,
				sceneAsset: sceneAsset,
				styleAsset: styleAsset,
			},
			product_id: workspacePackage?.product_id,
			prompt_package_snapshot_id: workspacePackage?.prompt_package_snapshot_id,
			workspace_execution_package_id:
				workspacePackage?.workspace_execution_package_id,
			prompt_fingerprint: workspacePackage?.prompt_fingerprint,
			asset_fingerprints:
				workspacePackage?.request_lineage_payload.asset_fingerprints ?? [],
			request_lineage_payload: workspacePackage?.request_lineage_payload,
			mode: "IMG",
		});
	};

	return (
		<div
			className={`space-y-6 ${compact ? "" : "xl:grid xl:grid-cols-[minmax(0,1fr)_18rem] xl:items-start xl:gap-6 xl:space-y-0"}`}
		>
			<div className="space-y-6 pb-12">
				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						1. Visual Assets (Subject / Scene / Style)
					</h3>
					<div className="grid gap-3">
						{workspacePackage ? (
							<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-3 text-[11px] text-emerald-100">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-200/80">
									Auto Asset Baseline
								</div>
								<div className="mt-1">
									Resolved product image is the default subject. Scene and Style
									remain optional manual references.
								</div>
							</div>
						) : (
							<div className="rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-3 text-[11px] text-slate-300">
								<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
									Manual Asset Upload
								</div>
								<div className="mt-1">
									No approved package is loaded. Subject, Scene, and Style are
									manual references.
								</div>
							</div>
						)}
					</div>
					<div className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-3">
						<WorkspaceImageAssetSlot
							key={
								subjectAsset?.assetFingerprint ??
								subjectAsset?.previewUrl ??
								"subject-empty"
							}
							title="Subject"
							description="Resolved product image is the default subject"
							asset={subjectAsset}
							isUploading={isUploading}
							accentClassName="group-hover:bg-blue-500/10 group-hover:text-blue-400"
							uploadTitle="Upload subject reference"
							onFileChange={(e) => handleFileChange("subject", e)}
						/>
						<WorkspaceImageAssetSlot
							key={
								sceneAsset?.assetFingerprint ??
								sceneAsset?.previewUrl ??
								"scene-empty"
							}
							title="Scene"
							description="Upload an optional scene reference"
							asset={sceneAsset}
							isUploading={isUploading}
							accentClassName="group-hover:bg-purple-500/10 group-hover:text-purple-400"
							uploadTitle="Upload scene reference"
							onFileChange={(e) => handleFileChange("scene", e)}
						/>
						<WorkspaceImageAssetSlot
							key={
								styleAsset?.assetFingerprint ??
								styleAsset?.previewUrl ??
								"style-empty"
							}
							title="Style"
							description="Upload an optional style reference"
							asset={styleAsset}
							isUploading={isUploading}
							accentClassName="group-hover:bg-pink-500/10 group-hover:text-pink-400"
							uploadTitle="Upload style reference"
							onFileChange={(e) => handleFileChange("style", e)}
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
										Approved package loaded. Subject/reference defaults to the
										cached product image.
									</div>
								</div>
								<div
									className={`rounded-xl border px-3 py-3 text-[11px] ${isManualOverride ? "border-amber-500/30 bg-amber-500/10 text-amber-100" : "border-slate-800 bg-slate-950/40 text-slate-300"}`}
								>
									<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
										Manual Override
									</div>
									<div className="mt-1">
										Editing the prompt below overrides the package prompt for
										this run only.
									</div>
									{isManualOverride ? (
										<div className="mt-2 text-amber-100">
											Manual override active. Subject can still fall back to the
											cached product image.
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
						<textarea
							className="w-full h-40 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
							placeholder="What do you want to create?"
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
							isExecuting || isUploading || !manualPrompt || !subjectAsset
						}
						className="w-full py-4 rounded-2xl bg-gradient-to-r from-blue-600 to-purple-600 text-white font-bold text-sm shadow-xl shadow-blue-500/20 hover:scale-[1.02] active:scale-95 disabled:opacity-50 disabled:grayscale transition-all flex items-center justify-center gap-2"
					>
						{isUploading
							? "Uploading Assets..."
							: isExecuting
								? "Generating Images..."
								: "GENERATE IMAGES"}
						{!isExecuting && !isUploading && <ArrowRight size={18} />}
					</button>
				</div>
			</div>

			<div
				className={`${compact ? "space-y-6 text-slate-300" : "space-y-6 text-slate-300 xl:sticky xl:top-4"}`}
			>
				<section className="space-y-4">
					<h3 className="text-sm font-bold text-slate-500 uppercase tracking-widest">
						Flow Mirror Settings
					</h3>
					<div className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-6">
						<div className="space-y-3">
							<p className="text-xs font-bold text-slate-400">Aspect Ratio</p>
							<div className="grid grid-cols-5 gap-1.5">
								{["16:9", "4:3", "1:1", "3:4", "9:16"].map((ratio) => (
									<button
										type="button"
										key={ratio}
										onClick={() => setAspectRatio(ratio)}
										className={`py-2 rounded-lg text-[9px] font-bold border transition-all ${aspectRatio === ratio ? "bg-blue-600/20 border-blue-500 text-blue-400" : "bg-slate-950 border-slate-800 text-slate-500"}`}
									>
										{ratio}
									</button>
								))}
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
			</div>
		</div>
	);
}
