import { useCallback, useEffect, useRef, useState } from "react";

import { deleteAPI, getAPI, postMultipartAPI } from "../../api/client";

// Operator-uploaded source media for a registration draft. ADDITIVE — entirely
// separate from the primary TikTok-extracted product image, which is untouched.

interface MediaItem {
	media_id: string;
	kind: "image" | "video";
	filename?: string | null;
	mime?: string | null;
	bytes?: number | null;
	ordinal?: number | null;
	status?: string | null;
}

interface MediaLimits {
	max_images: number;
	max_videos: number;
	image_max_bytes: number;
	video_max_bytes: number;
	image_types: string;
	video_types: string;
}

interface MediaListing {
	draft_id: string;
	images: MediaItem[];
	videos: MediaItem[];
	limits: MediaLimits;
}

function formatBytes(bytes?: number | null): string {
	if (!bytes || bytes <= 0) return "";
	const mb = bytes / (1024 * 1024);
	if (mb >= 1) return `${mb.toFixed(1)} MB`;
	return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function mediaBase(draftId: string): string {
	return `/api/product-registration/review-drafts/${encodeURIComponent(draftId)}/media`;
}

export default function DraftMediaSection({
	draftId,
	disabled = false,
}: {
	draftId: string;
	disabled?: boolean;
}) {
	const [images, setImages] = useState<MediaItem[]>([]);
	const [videos, setVideos] = useState<MediaItem[]>([]);
	const [limits, setLimits] = useState<MediaLimits | null>(null);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const imageInputRef = useRef<HTMLInputElement | null>(null);
	const videoInputRef = useRef<HTMLInputElement | null>(null);

	const applyListing = useCallback((listing: MediaListing) => {
		setImages(listing.images ?? []);
		setVideos(listing.videos ?? []);
		setLimits(listing.limits ?? null);
	}, []);

	useEffect(() => {
		let cancelled = false;
		setError("");
		getAPI<MediaListing>(mediaBase(draftId))
			.then((listing) => {
				if (!cancelled) applyListing(listing);
			})
			.catch((err) => {
				if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load media");
			});
		return () => {
			cancelled = true;
		};
	}, [draftId, applyListing]);

	const upload = useCallback(
		async (kind: "image" | "video", files: FileList | null) => {
			if (!files || files.length === 0) return;
			setBusy(true);
			setError("");
			try {
				const form = new FormData();
				form.append("kind", kind);
				Array.from(files).forEach((file) => form.append("files", file));
				const listing = await postMultipartAPI<MediaListing>(mediaBase(draftId), form);
				applyListing(listing);
			} catch (err) {
				setError(err instanceof Error ? err.message : `Failed to upload ${kind}`);
			} finally {
				setBusy(false);
				if (imageInputRef.current) imageInputRef.current.value = "";
				if (videoInputRef.current) videoInputRef.current.value = "";
			}
		},
		[draftId, applyListing],
	);

	const remove = useCallback(
		async (mediaId: string) => {
			setBusy(true);
			setError("");
			try {
				await deleteAPI(`${mediaBase(draftId)}/${encodeURIComponent(mediaId)}`);
				setImages((cur) => cur.filter((m) => m.media_id !== mediaId));
				setVideos((cur) => cur.filter((m) => m.media_id !== mediaId));
			} catch (err) {
				setError(err instanceof Error ? err.message : "Failed to remove media");
			} finally {
				setBusy(false);
			}
		},
		[draftId],
	);

	const fileUrl = (mediaId: string) =>
		`${mediaBase(draftId)}/${encodeURIComponent(mediaId)}/file`;

	const maxImages = limits?.max_images ?? 10;
	const maxVideos = limits?.max_videos ?? 3;
	const imageMax = limits ? Math.round(limits.image_max_bytes / (1024 * 1024)) : 5;
	const videoMax = limits ? Math.round(limits.video_max_bytes / (1024 * 1024)) : 50;
	const imageTypes = limits?.image_types ?? "JPG/PNG/WebP";
	const videoTypes = limits?.video_types ?? "MP4/MOV/WebM";
	const imagesFull = images.length >= maxImages;
	const videosFull = videos.length >= maxVideos;

	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4 space-y-4">
			<div className="flex items-center justify-between">
				<div className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-500">
					Product Media (operator uploads)
				</div>
				{busy ? (
					<span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-300">
						Working…
					</span>
				) : null}
			</div>
			<p className="text-[11px] leading-relaxed text-slate-500">
				Extra images and videos you upload yourself. Separate from the product image
				pulled from the TikTok link — that one stays as is.
			</p>
			{error ? (
				<p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-200">
					{error}
				</p>
			) : null}

			{/* Images */}
			<div className="space-y-2">
				<div className="flex flex-wrap items-center justify-between gap-2">
					<span className="text-[11px] font-semibold text-slate-300">
						Images{" "}
						<span className="text-slate-500">
							({images.length}/{maxImages})
						</span>
					</span>
					<span className="text-[10px] text-slate-500">
						Max {maxImages} · ≤ {imageMax} MB each · {imageTypes} · compress larger files
					</span>
				</div>
				{images.length > 0 ? (
					<div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
						{images.map((m) => (
							<div
								key={m.media_id}
								className="group relative overflow-hidden rounded-lg border border-slate-700 bg-slate-900"
							>
								<img
									src={fileUrl(m.media_id)}
									alt={m.filename || "product image"}
									className="h-20 w-full object-cover"
									loading="lazy"
								/>
								{!disabled ? (
									<button
										type="button"
										onClick={() => remove(m.media_id)}
										disabled={busy}
										aria-label={`Remove ${m.filename || "image"}`}
										className="absolute right-1 top-1 rounded bg-black/60 px-1.5 text-xs font-bold text-white opacity-0 transition-opacity hover:bg-rose-600 group-hover:opacity-100"
									>
										×
									</button>
								) : null}
								<div className="truncate px-1 py-0.5 text-[9px] text-slate-400">
									{formatBytes(m.bytes)}
								</div>
							</div>
						))}
					</div>
				) : null}
				{!disabled ? (
					<label
						className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-[11px] transition-colors ${
							imagesFull
								? "cursor-not-allowed border-slate-800 text-slate-600"
								: "border-slate-600 text-slate-300 hover:border-indigo-500/60 hover:text-indigo-200"
						}`}
					>
						<input
							ref={imageInputRef}
							type="file"
							accept="image/jpeg,image/png,image/webp"
							multiple
							disabled={busy || imagesFull}
							className="hidden"
							onChange={(e) => upload("image", e.target.files)}
						/>
						{imagesFull ? "Image limit reached" : "+ Add images"}
					</label>
				) : null}
			</div>

			{/* Videos */}
			<div className="space-y-2">
				<div className="flex flex-wrap items-center justify-between gap-2">
					<span className="text-[11px] font-semibold text-slate-300">
						Videos{" "}
						<span className="text-slate-500">
							({videos.length}/{maxVideos})
						</span>
					</span>
					<span className="text-[10px] text-slate-500">
						Max {maxVideos} · ≤ {videoMax} MB each · {videoTypes} · compress larger files
					</span>
				</div>
				{videos.length > 0 ? (
					<div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
						{videos.map((m) => (
							<div
								key={m.media_id}
								className="relative overflow-hidden rounded-lg border border-slate-700 bg-slate-900"
							>
								<video
									src={fileUrl(m.media_id)}
									controls
									preload="metadata"
									className="h-28 w-full bg-black object-contain"
								/>
								<div className="flex items-center justify-between gap-2 px-2 py-1">
									<span className="truncate text-[10px] text-slate-400">
										{m.filename || "video"} · {formatBytes(m.bytes)}
									</span>
									{!disabled ? (
										<button
											type="button"
											onClick={() => remove(m.media_id)}
											disabled={busy}
											className="shrink-0 rounded bg-slate-800 px-1.5 text-[10px] font-bold text-slate-300 hover:bg-rose-600 hover:text-white"
										>
											Remove
										</button>
									) : null}
								</div>
							</div>
						))}
					</div>
				) : null}
				{!disabled ? (
					<label
						className={`inline-flex cursor-pointer items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-[11px] transition-colors ${
							videosFull
								? "cursor-not-allowed border-slate-800 text-slate-600"
								: "border-slate-600 text-slate-300 hover:border-indigo-500/60 hover:text-indigo-200"
						}`}
					>
						<input
							ref={videoInputRef}
							type="file"
							accept="video/mp4,video/quicktime,video/webm"
							multiple
							disabled={busy || videosFull}
							className="hidden"
							onChange={(e) => upload("video", e.target.files)}
						/>
						{videosFull ? "Video limit reached" : "+ Add videos"}
					</label>
				) : null}
			</div>
		</div>
	);
}
