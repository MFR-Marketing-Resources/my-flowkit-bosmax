import { ExternalLink, Loader2, TriangleAlert, Upload } from "lucide-react";
import { useId, useState } from "react";
import type { UploadedAsset } from "../../types";

interface WorkspaceImageAssetSlotProps {
	title: string;
	description: string;
	asset: UploadedAsset | null;
	isUploading: boolean;
	accentClassName: string;
	uploadTitle: string;
	onFileChange: (event: React.ChangeEvent<HTMLInputElement>) => void;
	onPreviewStateChange?: (failed: boolean) => void;
	onImageClick?: (url: string) => void;
}

function previewSourceLabel(asset: UploadedAsset | null) {
	if (!asset) return "NONE";
	return asset.assetSource || "USER_UPLOAD";
}

function renderPreviewUrl(url: string | undefined) {
	if (!url) return "Unavailable";
	if (url.length <= 72) return url;
	return `${url.slice(0, 69)}...`;
}

export default function WorkspaceImageAssetSlot({
	title,
	description,
	asset,
	isUploading,
	accentClassName,
	uploadTitle,
	onFileChange,
	onPreviewStateChange,
	onImageClick,
}: WorkspaceImageAssetSlotProps) {
	const inputId = useId();
	const [previewFailed, setPreviewFailed] = useState(false);

	const hasPreview = Boolean(asset?.previewUrl) && !previewFailed;
	const showFallback = Boolean(asset) && (!asset?.previewUrl || previewFailed);
	const handlePreviewOpen = () => {
		if (asset?.previewUrl) {
			onImageClick?.(asset.previewUrl);
		}
	};

	return (
		<div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-3">
			<div className="relative aspect-video overflow-hidden rounded-2xl border border-dashed border-slate-800 bg-slate-900/20">
				{hasPreview ? (
					<>
						<img
							src={asset?.previewUrl}
							className={`h-full w-full object-cover animate-in fade-in duration-500 ${onImageClick ? "cursor-zoom-in" : ""}`}
							alt={title}
							onClick={handlePreviewOpen}
							onKeyDown={(event) => {
								if (!onImageClick) return;
								if (event.key === "Enter" || event.key === " ") {
									event.preventDefault();
									handlePreviewOpen();
								}
							}}
							onError={() => {
								setPreviewFailed(true);
								onPreviewStateChange?.(true);
							}}
							role={onImageClick ? "button" : undefined}
							tabIndex={onImageClick ? 0 : undefined}
						/>
						<div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-slate-950/90 to-transparent p-3">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-white">
								{title}
							</div>
							<div className="mt-1 text-[10px] text-slate-300">
								{asset?.label || description}
							</div>
							<div className="mt-1 text-[9px] uppercase tracking-[0.16em] text-slate-400">
								Source: {previewSourceLabel(asset)}
							</div>
						</div>
					</>
				) : showFallback ? (
					<div className="flex h-full flex-col justify-between gap-3 p-4">
						<div className="space-y-2">
							<div className="flex items-center gap-2 text-amber-300">
								<TriangleAlert size={16} />
								<span className="text-[10px] font-bold uppercase tracking-[0.18em]">
									Image preview failed
								</span>
							</div>
							<div className="text-xs text-slate-100">{title}</div>
							<div className="space-y-1 text-[11px] text-slate-300">
								<div>Asset source: {previewSourceLabel(asset)}</div>
								<div>Preview source: {renderPreviewUrl(asset?.previewUrl)}</div>
								{asset?.previewErrorDetail ? (
									<div className="text-amber-200">
										{asset.previewErrorDetail}
									</div>
								) : null}
								<div className="text-slate-400">
									Upload a manual replacement if this source is broken.
								</div>
							</div>
						</div>
						<div className="flex flex-wrap gap-2">
							{asset?.previewUrl ? (
								<a
									className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-100 hover:border-slate-500"
									href={asset.previewUrl}
									target="_blank"
									rel="noreferrer"
								>
									Open Preview <ExternalLink size={12} />
								</a>
							) : null}
							{asset?.downloadUrl ? (
								<a
									className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-100 hover:border-slate-500"
									href={asset.downloadUrl}
									target="_blank"
									rel="noreferrer"
								>
									Download <ExternalLink size={12} />
								</a>
							) : null}
						</div>
					</div>
				) : (
					<div className="flex h-full flex-col items-center justify-center gap-3 text-center">
						<div
							className={`rounded-full bg-slate-800 p-4 text-slate-400 transition-colors ${accentClassName}`}
						>
							{isUploading ? (
								<Loader2 className="animate-spin" size={24} />
							) : (
								<Upload size={24} />
							)}
						</div>
						<div>
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-300">
								{title}
							</div>
							<div className="mt-1 text-[10px] text-slate-500">
								{description}
							</div>
						</div>
					</div>
				)}
			</div>
			<div className="mt-3 flex items-center justify-between gap-3">
				<div className="text-[10px] text-slate-500">
					{asset
						? "Manual replacement remains available."
						: isUploading
							? "Uploading asset..."
							: "Click upload to replace or attach an image."}
				</div>
				<label
					htmlFor={inputId}
					className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-100 hover:border-slate-500"
				>
					<Upload size={12} />
					{asset ? "Replace image" : "Upload image"}
				</label>
				<input
					id={inputId}
					type="file"
					accept="image/*"
					title={uploadTitle}
					className="hidden"
					disabled={isUploading}
					onChange={onFileChange}
				/>
			</div>
		</div>
	);
}
