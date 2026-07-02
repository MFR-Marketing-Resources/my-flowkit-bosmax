import { Download, RefreshCw, Timer } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

// LIBRARY — the single collection point for finished Google Flow results.
// Workspace pages are for WORK; results live here (video + image pages),
// retained 48 hours by the backend, then auto-deleted (file + record).

interface LibraryArtifact {
	media_id: string;
	job_id: string | null;
	mode: string | null;
	artifact_kind: "video" | "image";
	size_mb: number | null;
	model_used: string | null;
	duration_used: number | null;
	created_at: string;
	expires_at: string | null;
	expires_in_hours: number | null;
}

interface LibraryPageProps {
	kind: "video" | "image";
}

const MODE_FILTERS = ["ALL", "T2V", "F2V", "I2V", "IMG"] as const;

function expiryTone(hours: number | null): string {
	if (hours == null) return "text-slate-400";
	if (hours <= 6) return "text-red-300";
	if (hours <= 24) return "text-amber-300";
	return "text-emerald-300";
}

export default function LibraryPage({ kind }: LibraryPageProps) {
	const [artifacts, setArtifacts] = useState<LibraryArtifact[]>([]);
	const [modeFilter, setModeFilter] = useState<(typeof MODE_FILTERS)[number]>("ALL");
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const refresh = useCallback(async () => {
		setIsLoading(true);
		setError(null);
		try {
			const params = new URLSearchParams({ limit: "60", kind });
			if (modeFilter !== "ALL") params.set("mode", modeFilter);
			const response = await fetch(`/api/flow/artifacts?${params.toString()}`);
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			const data = await response.json();
			setArtifacts(Array.isArray(data.artifacts) ? data.artifacts : []);
		} catch (err) {
			setError(err instanceof Error ? err.message : "Failed to load library");
		} finally {
			setIsLoading(false);
		}
	}, [kind, modeFilter]);

	useEffect(() => {
		void refresh();
	}, [refresh]);

	const title = kind === "video" ? "Video Library" : "Image Library";

	return (
		<div className="space-y-4">
			<div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
				<div>
					<h1 className="text-lg font-bold tracking-wide text-slate-100">
						{kind === "video" ? "🎬" : "🖼"} {title}
					</h1>
					<p className="mt-1 text-xs text-slate-400">
						Semua hasil siap dari Google Flow terkumpul di sini. Setiap item
						disimpan <span className="font-semibold text-slate-200">48 jam</span>{" "}
						sebelum auto-delete — download apa yang anda mahu simpan.
					</p>
				</div>
				<div className="flex items-center gap-2">
					<select
						title="Filter by job mode"
						value={modeFilter}
						onChange={(e) =>
							setModeFilter(e.target.value as (typeof MODE_FILTERS)[number])
						}
						className="rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100"
					>
						{MODE_FILTERS.map((m) => (
							<option key={m} value={m}>
								{m === "ALL" ? "Semua mode" : m}
							</option>
						))}
					</select>
					<button
						type="button"
						onClick={() => void refresh()}
						className="flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:bg-slate-800"
					>
						<RefreshCw size={13} className={isLoading ? "animate-spin" : ""} />
						Refresh
					</button>
				</div>
			</div>

			{error && (
				<div className="rounded-2xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-200">
					{error}
				</div>
			)}

			{!error && artifacts.length === 0 && !isLoading && (
				<div className="rounded-2xl border border-slate-800 bg-slate-900/40 px-4 py-10 text-center text-sm text-slate-400">
					Tiada {kind === "video" ? "video" : "imej"} dalam tempoh simpanan 48
					jam. Hasil baharu akan muncul di sini secara automatik selepas job
					siap.
				</div>
			)}

			<div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
				{artifacts.map((item) => (
					<div
						key={item.media_id}
						className="group rounded-xl border border-slate-800 bg-slate-950/60 p-2 hover:border-slate-600"
					>
						<a
							href={`/api/flow/retrieved/${item.media_id}`}
							target="_blank"
							rel="noopener noreferrer"
						>
							{item.artifact_kind === "video" ? (
								<video
									src={`/api/flow/retrieved/${item.media_id}`}
									muted
									playsInline
									controls
									preload="metadata"
									className="aspect-[9/16] w-full rounded-lg bg-black object-contain"
								/>
							) : (
								<img
									src={`/api/flow/retrieved/${item.media_id}`}
									alt={item.mode ?? "artifact"}
									loading="lazy"
									className="aspect-[9/16] w-full rounded-lg bg-black object-contain"
								/>
							)}
						</a>
						<div className="mt-2 flex items-center justify-between text-[10px] text-slate-400">
							<span className="font-semibold text-slate-300">
								{item.mode ?? "?"}
								{item.duration_used ? ` · ${item.duration_used}s` : ""}
							</span>
							<span>{item.size_mb != null ? `${item.size_mb}MB` : ""}</span>
						</div>
						<div className="mt-1 flex items-center justify-between">
							<span
								className={`flex items-center gap-1 text-[10px] ${expiryTone(item.expires_in_hours)}`}
								title={item.expires_at ?? undefined}
							>
								<Timer size={11} />
								{item.expires_in_hours != null
									? `${item.expires_in_hours}j lagi`
									: "—"}
							</span>
							<a
								href={`/api/flow/retrieved/${item.media_id}`}
								download={`${item.media_id}.${item.artifact_kind === "video" ? "mp4" : "jpg"}`}
								className="flex items-center gap-1 rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-300 hover:bg-slate-800"
							>
								<Download size={11} />
								Save
							</a>
						</div>
						<div className="mt-1 text-[9px] text-slate-500">
							{item.created_at?.replace("T", " ").replace("Z", "")}
						</div>
					</div>
				))}
			</div>
		</div>
	);
}
