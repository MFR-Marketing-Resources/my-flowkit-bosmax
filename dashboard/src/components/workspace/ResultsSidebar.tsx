import { useCallback, useEffect, useState } from "react";
import {
	deleteImageArtifact,
	fetchImageArtifacts,
	type ImageArtifact,
} from "../../api/imgFactory";

interface ResultsSidebarProps {
	/** Artifact kind to display. Image generation is credit-free. */
	kind?: "image" | "video";
	/** Fires the page's generate/regenerate flow (kept on the page so it reuses page params + the confirm gate). */
	onRegenerate?: () => void;
	regenerateDisabled?: boolean;
	regenerating?: boolean;
	/** Change this value (e.g. the latest job media_id) to re-pull the gallery after a generation. */
	refreshSignal?: unknown;
	title?: string;
}

/**
 * Persistent, docked results panel. Shows generated artifacts for the current
 * lane with per-item download + delete, and an optional Regenerate button that
 * the page wires to its own credit-free generate flow. Reusable across every
 * generation page so "where do I see results" is always the same place.
 */
export default function ResultsSidebar({
	onRegenerate,
	regenerateDisabled = false,
	regenerating = false,
	refreshSignal,
	title = "Hasil (Results)",
}: ResultsSidebarProps) {
	const [artifacts, setArtifacts] = useState<ImageArtifact[]>([]);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [busyId, setBusyId] = useState<string | null>(null);

	const refresh = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			setArtifacts(await fetchImageArtifacts(30));
		} catch (err) {
			setError(err instanceof Error ? err.message : "Gagal muat hasil");
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void refresh();
	}, [refresh, refreshSignal]);

	const handleDelete = useCallback(async (mediaId: string) => {
		if (
			!window.confirm(
				"Padam imej ini? Creative Asset yang sudah disimpan tidak terjejas.",
			)
		)
			return;
		setBusyId(mediaId);
		try {
			await deleteImageArtifact(mediaId);
			setArtifacts((prev) => prev.filter((a) => a.media_id !== mediaId));
		} catch (err) {
			setError(err instanceof Error ? err.message : "Gagal padam imej");
		} finally {
			setBusyId(null);
		}
	}, []);

	return (
		<div className="w-full space-y-3 rounded-2xl border border-slate-800 bg-slate-950/70 p-3">
			<div className="flex items-center justify-between">
				<div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-300">
					{title}
				</div>
				<button
					type="button"
					onClick={() => void refresh()}
					className="rounded-lg border border-slate-700 px-2 py-1 text-[10px] text-slate-300 hover:bg-slate-800"
				>
					{loading ? "…" : "↻ Refresh"}
				</button>
			</div>

			<p className="text-[10px] text-slate-500">
				Imej PERCUMA (hanya video guna kredit). Hasil generate muncul di sini.
			</p>

			{onRegenerate ? (
				<button
					type="button"
					onClick={onRegenerate}
					disabled={regenerateDisabled}
					className="w-full rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-[11px] font-bold text-blue-200 hover:bg-blue-500/20 disabled:opacity-40"
				>
					{regenerating ? "Menjana…" : "🔄 Jana imej baru"}
				</button>
			) : null}

			{error ? (
				<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[10px] text-red-200">
					{error}
				</div>
			) : null}

			{artifacts.length === 0 && !loading ? (
				<div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 px-3 py-6 text-center text-[11px] text-slate-500">
					Belum ada hasil. Tekan Generate — hasil akan muncul di sini.
				</div>
			) : null}

			<div className="grid grid-cols-2 gap-2">
				{artifacts.map((a) => (
					<div
						key={a.media_id}
						className="space-y-1.5 rounded-xl border border-slate-800 bg-slate-950/60 p-1.5"
					>
						<a
							href={`/api/flow/retrieved/${a.media_id}`}
							target="_blank"
							rel="noopener noreferrer"
						>
							<img
								src={`/api/flow/retrieved/${encodeURIComponent(a.media_id)}`}
								alt={a.mode ?? "hasil imej"}
								loading="lazy"
								className="aspect-square w-full rounded-lg bg-black object-contain"
							/>
						</a>
						<div className="flex gap-1">
							<a
								href={`/api/flow/retrieved/${a.media_id}`}
								download={`${a.media_id}.jpg`}
								className="flex-1 rounded border border-slate-700 py-0.5 text-center text-[10px] text-slate-300 hover:bg-slate-800"
							>
								Simpan
							</a>
							<button
								type="button"
								onClick={() => void handleDelete(a.media_id)}
								disabled={busyId === a.media_id}
								aria-label={`Padam ${a.media_id}`}
								className="rounded border border-rose-500/40 px-2 py-0.5 text-[10px] text-rose-300 hover:bg-rose-500/10 disabled:opacity-40"
							>
								{busyId === a.media_id ? "…" : "Padam"}
							</button>
						</div>
					</div>
				))}
			</div>
		</div>
	);
}
