import { useCallback, useEffect, useMemo, useState } from "react";
import { deleteImageArtifact } from "../../api/imgFactory";
import {
	forgetGenerationJob,
	readGenerationJobs,
} from "../../utils/videoSessionResults";

export interface SessionResult {
	media_id: string;
	size_mb?: number | null;
	kind?: "image" | "video";
	/** Direct preview/download URL. When set, used instead of /api/flow/retrieved/{media_id} (e.g. composed posters). */
	url?: string;
	/** When false, hides Delete (non-flow-artifact results like posters). */
	deletable?: boolean;
}

interface ResultsSidebarProps {
	/** Results generated in THIS session only. Updates live as jobs finish — no manual refresh needed. */
	results: SessionResult[];
	/** Whether a generation is currently running (shows a placeholder). */
	generating?: boolean;
	/** Called after an artifact is deleted so the page can drop it from state. */
	onRemoved?: (mediaId: string) => void;
	title?: string;
	/** Library route to point at for historical results (image vs video lane). */
	libraryHref?: string;
	/** What this surface produces — drives the "Generating…" placeholder wording. Defaults to image. */
	mediaKind?: "image" | "video";
	/** Durable server-side correlation used to recover only this operator session. */
	staffId?: string | null;
	surfaceLane?: string | null;
	jobId?: string | null;
	requestId?: string | null;
}

/**
 * Persistent, docked results panel. Shows ONLY the artifacts produced in the
 * current session (prop-driven, so it auto-updates the moment a job finishes).
 * Older results and other sessions live in Image/Video Library + Results — this
 * panel links there rather than dumping the whole global store.
 */
export default function ResultsSidebar({
	results,
	generating = false,
	onRemoved,
	title = "This session's results",
	libraryHref = "/library/images",
	mediaKind = "image",
	staffId = null,
	surfaceLane = null,
	jobId = null,
	requestId = null,
}: ResultsSidebarProps) {
	const [busyId, setBusyId] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [recoveredResults, setRecoveredResults] = useState<SessionResult[]>([]);
	const primaryIsVideoLibrary = libraryHref.startsWith("/library/videos");

	// Recover by durable job/request identity only. A mount timestamp plus a global
	// artifact scan can leak another surface or operator's concurrently-finished video.
	useEffect(() => {
		if (mediaKind !== "video") {
			setRecoveredResults([]);
			return;
		}
		let alive = true;
		let inFlight = false;
		const loadRecovered = async () => {
			if (!alive || inFlight || document.hidden) return;
			inFlight = true;
			try {
				const durableRecovered: SessionResult[] = [];
				const recover = async (identity: { jobId?: string | null; requestId?: string | null }) => {
					if (!identity.jobId && !identity.requestId) return false;
					const params = new URLSearchParams();
					if (identity.jobId) params.set("job_id", identity.jobId);
					if (identity.requestId) params.set("request_id", identity.requestId);
					if (staffId) params.set("staff_id", staffId);
					if (surfaceLane) params.set("surface_lane", surfaceLane);
					const response = await fetch(`/api/results/recover?${params.toString()}`);
					if (!response.ok) return false;
					const durable = await response.json();
					for (const result of Array.isArray(durable.results) ? durable.results : []) {
						const mediaId = String(result.media_id || "").trim();
						if (mediaId) {
							durableRecovered.push({
								media_id: mediaId,
								kind: "video",
								size_mb: result.size_mb ?? null,
								url: result.retrieved_url || undefined,
							});
						}
					}
					return Array.isArray(durable.results) && durable.results.length > 0;
				};

				await recover({ jobId, requestId });
				for (const tracked of readGenerationJobs()) {
					if (String(tracked.mode || "").toUpperCase() === "IMG") continue;
					// The durable Results Hub survives both page and backend restarts;
					// process-local generation maps are never used as result authority.
					if (await recover({
						jobId: tracked.job_id,
						requestId: tracked.request_id,
					})) {
						forgetGenerationJob(tracked.job_id);
					}
				}
				if (alive) setRecoveredResults(durableRecovered);
			} catch {
				// Best-effort discovery only; the normal prop-driven completion path remains primary.
			} finally {
				inFlight = false;
			}
		};
		void loadRecovered();
		const timer = window.setInterval(() => void loadRecovered(), 5000);
		const onVisibility = () => void loadRecovered();
		document.addEventListener("visibilitychange", onVisibility);
		return () => {
			alive = false;
			window.clearInterval(timer);
			document.removeEventListener("visibilitychange", onVisibility);
		};
	}, [jobId, mediaKind, requestId, staffId, surfaceLane]);

	const visibleResults = useMemo(() => {
		const seen = new Set<string>();
		return [...results, ...recoveredResults].filter((item) => {
			if (seen.has(item.media_id)) return false;
			seen.add(item.media_id);
			return true;
		});
	}, [results, recoveredResults]);

	const handleDelete = useCallback(
		async (mediaId: string) => {
			if (
				!window.confirm(
					"Delete this image? Saved Creative Assets are not affected.",
				)
			)
				return;
			setBusyId(mediaId);
			setError(null);
			try {
				await deleteImageArtifact(mediaId);
				setRecoveredResults((prev) => prev.filter((item) => item.media_id !== mediaId));
				onRemoved?.(mediaId);
			} catch (err) {
				setError(err instanceof Error ? err.message : "Failed to delete image");
			} finally {
				setBusyId(null);
			}
		},
		[onRemoved],
	);

	return (
		<div className="w-full space-y-3 rounded-2xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-300">
				{title}
			</div>
			<p className="text-[10px] text-slate-500">
				Results appear here automatically when ready — no need to refresh.
			</p>

			{error ? (
				<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[10px] text-red-200">
					{error}
				</div>
			) : null}

			{visibleResults.length === 0 && !generating ? (
				<div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 px-3 py-6 text-center text-[11px] text-slate-500">
					No results yet. Press{" "}
					<span className="text-slate-300">Generate</span> on the left —
					results appear here automatically.
				</div>
			) : (
				<div className="grid grid-cols-2 gap-2">
					{generating ? (
						<div className="col-span-2 flex items-center justify-center rounded-xl border border-dashed border-blue-500/30 bg-blue-500/5 px-3 py-4 text-[11px] text-blue-200">
							Generating {mediaKind === "video" ? "video" : "image"}… results will appear here.
						</div>
					) : null}
					{visibleResults.map((r) => (
						<div
							key={r.media_id}
							className="space-y-1.5 rounded-xl border border-slate-800 bg-slate-950/60 p-1.5"
						>
							{r.kind === "video" ? (
								<video
									src={r.url ?? `/api/flow/retrieved/${encodeURIComponent(r.media_id)}`}
									muted
									playsInline
									controls
									preload="metadata"
									className="aspect-[9/16] w-full rounded-lg bg-black object-contain"
								/>
							) : (
								<a
									href={r.url ?? `/api/flow/retrieved/${r.media_id}`}
									target="_blank"
									rel="noopener noreferrer"
								>
									<img
										src={r.url ?? `/api/flow/retrieved/${encodeURIComponent(r.media_id)}`}
										alt="generated result"
										loading="lazy"
										className="aspect-square w-full rounded-lg bg-black object-contain"
									/>
								</a>
							)}
							<div className="flex gap-1">
								<a
									href={r.url ?? `/api/flow/retrieved/${r.media_id}`}
									download={`${r.media_id}.${r.kind === "video" ? "mp4" : "jpg"}`}
									className="flex-1 rounded border border-slate-700 py-0.5 text-center text-[10px] text-slate-300 hover:bg-slate-800"
								>
									Save
								</a>
								{r.kind !== "video" && r.deletable !== false ? (
									<button
										type="button"
										onClick={() => void handleDelete(r.media_id)}
										disabled={busyId === r.media_id}
										aria-label={`Delete ${r.media_id}`}
										className="rounded border border-rose-500/40 px-2 py-0.5 text-[10px] text-rose-300 hover:bg-rose-500/10 disabled:opacity-40"
									>
										{busyId === r.media_id ? "…" : "Delete"}
									</button>
								) : null}
							</div>
						</div>
					))}
				</div>
			)}

			<div className="border-t border-slate-800 pt-2 text-[10px] text-slate-500">
				<div className="mb-1">Older results / other sessions:</div>
				<div className="flex flex-wrap gap-1.5">
					<a
						href={libraryHref}
						className="rounded border border-slate-700 px-2 py-0.5 text-slate-300 hover:bg-slate-800"
					>
						{primaryIsVideoLibrary ? "Video Library" : "Image Library"}
					</a>
					{!primaryIsVideoLibrary ? (
						<a
							href="/library/videos"
							className="rounded border border-slate-700 px-2 py-0.5 text-slate-300 hover:bg-slate-800"
						>
							Video Library
						</a>
					) : null}
					<a
						href="/results"
						className="rounded border border-slate-700 px-2 py-0.5 text-slate-300 hover:bg-slate-800"
					>
						Results
					</a>
				</div>
			</div>
		</div>
	);
}
