import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
}

function sessionStartFor(kind: "image" | "video"): number {
	const key = `bosmax.results-session-started.${kind}`;
	try {
		const existing = Number(window.sessionStorage.getItem(key));
		if (Number.isFinite(existing) && existing > 0) return existing;
		const now = Date.now();
		window.sessionStorage.setItem(key, String(now));
		return now;
	} catch {
		return Date.now();
	}
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
}: ResultsSidebarProps) {
	const [busyId, setBusyId] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [recoveredResults, setRecoveredResults] = useState<SessionResult[]>([]);
	const sessionStartedAtRef = useRef<number>(sessionStartFor(mediaKind));
	const primaryIsVideoLibrary = libraryHref.startsWith("/library/videos");

	// A retrieval recovery may register the video after the original job poll has
	// already stopped. Discover only videos created while this sidebar is mounted:
	// historical clips stay in Video Library/Results, while an out-of-band recovery
	// still appears here without a page refresh or another paid generation.
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
				const response = await fetch("/api/flow/artifacts?limit=20&kind=video");
				const payload = response.ok ? await response.json() : { artifacts: [] };
				const sessionFloor = sessionStartedAtRef.current - 1000;
				const current = (Array.isArray(payload.artifacts) ? payload.artifacts : [])
					.filter((item: { media_id?: unknown; created_at?: unknown }) => {
						const createdAt = Date.parse(String(item.created_at ?? ""));
						return Boolean(item.media_id) && Number.isFinite(createdAt) && createdAt >= sessionFloor;
					})
					.map((item: { media_id: string; size_mb?: number | null }) => ({
						media_id: String(item.media_id),
						kind: "video" as const,
						size_mb: item.size_mb ?? null,
					}));

				const durableRecovered: SessionResult[] = [];
				for (const tracked of readGenerationJobs()) {
					if (String(tracked.mode || "").toUpperCase() === "IMG") continue;
					let jobResponse = await fetch(
						`/api/flow/generate-job/${encodeURIComponent(tracked.job_id)}`,
					);
					if (jobResponse.ok) {
						const job = await jobResponse.json();
						const status = String(job.status || "").toUpperCase();
						const mediaId = String(job.media_id || job.video_media_id || "").trim();
						if (mediaId && status === "DONE") {
							durableRecovered.push({
								media_id: mediaId,
								kind: "video",
								size_mb: job.size_mb ?? null,
							});
							forgetGenerationJob(tracked.job_id);
						} else if (["FAILED", "REJECTED", "GENERATED_BUT_UNRETRIEVED"].includes(status)) {
							forgetGenerationJob(tracked.job_id);
						}
						continue;
					}
					if (jobResponse.status !== 404) continue;
					// The process-local map may be gone after a restart. Query the
					// durable Results Hub by job id; this is read-only and contains
					// no regex extraction from telemetry text.
					jobResponse = await fetch(
						`/api/results/recover?job_id=${encodeURIComponent(tracked.job_id)}`,
					);
					if (!jobResponse.ok) continue;
					const durable = await jobResponse.json();
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
					if (Array.isArray(durable.results) && durable.results.length) {
						forgetGenerationJob(tracked.job_id);
					}
				}
				if (alive) setRecoveredResults([...current, ...durableRecovered]);
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
	}, [mediaKind]);

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
