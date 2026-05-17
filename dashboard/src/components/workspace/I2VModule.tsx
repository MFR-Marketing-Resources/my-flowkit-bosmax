import { ArrowRight, Loader2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { handleAssetUpload } from "../../api/assets";
import type {
	Orientation,
	UploadedAsset,
	WorkspaceExecutePayload,
	WorkspaceExecutionPackage,
} from "../../types";

interface I2VModuleProps {
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
	};
}

export default function I2VModule({
	onExecute,
	isExecuting,
	compact = false,
	workspacePackage = null,
}: I2VModuleProps) {
	// --- States ---
	const [manualPrompt, setManualPrompt] = useState("");
	const [isManualOverride, setIsManualOverride] = useState(false);
	const [orientation, setOrientation] = useState<Orientation>("VERTICAL");
	const [model] = useState("Veo 3.1 - Pro");
	const [count, setCount] = useState(1);
	const [isUploading, setIsUploading] = useState(false);

	// Ingredients Assets
	const [subjectAsset, setSubjectAsset] = useState<UploadedAsset | null>(null);
	const [sceneAsset, setSceneAsset] = useState<UploadedAsset | null>(null);
	const [styleAsset, setStyleAsset] = useState<UploadedAsset | null>(null);

	useEffect(() => {
		if (!workspacePackage || workspacePackage.mode !== "I2V") return;
		setManualPrompt(workspacePackage.prompt_text);
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
			orientation,
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
			mode: "I2V",
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
						1. Visual Assets (Subject / Scene / Style)
					</h3>
					<div className="grid grid-cols-1 gap-4 min-[480px]:grid-cols-3">
						{/* Subject */}
						<div className="group relative aspect-[3/4] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-blue-500/50 transition-all cursor-pointer overflow-hidden">
							{subjectAsset ? (
								<img
									src={subjectAsset.previewUrl}
									className="w-full h-full object-cover animate-in fade-in duration-500"
									alt="Subject"
								/>
							) : (
								<>
									<div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-blue-500/10 group-hover:text-blue-400 transition-colors">
										{isUploading ? (
											<Loader2 size={20} className="animate-spin" />
										) : (
											<Upload size={20} />
										)}
									</div>
									<span className="text-[10px] font-bold text-slate-500 group-hover:text-slate-300 uppercase tracking-widest">
										Subject
									</span>
								</>
							)}
							{!isUploading && (
								<input
									type="file"
									accept="image/*"
									title="Upload subject reference"
									className="absolute inset-0 opacity-0 cursor-pointer"
									onChange={(e) => handleFileChange("subject", e)}
								/>
							)}
						</div>

						{/* Scene */}
						<div className="group relative aspect-[3/4] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-purple-500/50 transition-all cursor-pointer overflow-hidden">
							{sceneAsset ? (
								<img
									src={sceneAsset.previewUrl}
									className="w-full h-full object-cover animate-in fade-in duration-500"
									alt="Scene"
								/>
							) : (
								<>
									<div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-purple-500/10 group-hover:text-purple-400 transition-colors">
										<Upload size={20} />
									</div>
									<span className="text-[10px] font-bold text-slate-500 group-hover:text-slate-300 uppercase tracking-widest">
										Scene
									</span>
								</>
							)}
							{!isUploading && (
								<input
									type="file"
									accept="image/*"
									title="Upload scene reference"
									className="absolute inset-0 opacity-0 cursor-pointer"
									onChange={(e) => handleFileChange("scene", e)}
								/>
							)}
						</div>

						{/* Style */}
						<div className="group relative aspect-[3/4] rounded-2xl border-2 border-dashed border-slate-800 bg-slate-900/20 flex flex-col items-center justify-center gap-2 hover:border-pink-500/50 transition-all cursor-pointer overflow-hidden">
							{styleAsset ? (
								<img
									src={styleAsset.previewUrl}
									className="w-full h-full object-cover animate-in fade-in duration-500"
									alt="Style"
								/>
							) : (
								<>
									<div className="p-3 rounded-full bg-slate-800 text-slate-400 group-hover:bg-pink-500/10 group-hover:text-pink-400 transition-colors">
										<Upload size={20} />
									</div>
									<span className="text-[10px] font-bold text-slate-500 group-hover:text-slate-300 uppercase tracking-widest">
										Style
									</span>
								</>
							)}
							{!isUploading && (
								<input
									type="file"
									accept="image/*"
									title="Upload style reference"
									className="absolute inset-0 opacity-0 cursor-pointer"
									onChange={(e) => handleFileChange("style", e)}
								/>
							)}
						</div>
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
									? "Manual override active. Subject may still fall back to the cached product image."
									: "Approved package loaded. Subject uses the cached product image; Scene and Style remain optional uploads."}
							</div>
						) : null}
						<textarea
							className="w-full h-40 bg-slate-950 border border-slate-800 rounded-xl p-4 text-sm text-slate-300 font-mono focus:border-blue-500 outline-none transition-all resize-none"
							placeholder="Describe how to combine these ingredients..."
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
								? "Executing Ingredients Sequence..."
								: "START GENERATION"}
						{!isExecuting && !isUploading && <ArrowRight size={18} />}
					</button>
				</div>
			</div>

			<div
				className={`${compact ? "w-full" : "w-72 max-[1280px]:w-full"} flex-shrink-0 flex flex-col gap-6 overflow-y-auto pb-12 text-slate-300`}
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
										{o === "VERTICAL" ? "9:16" : "16:9"}
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
