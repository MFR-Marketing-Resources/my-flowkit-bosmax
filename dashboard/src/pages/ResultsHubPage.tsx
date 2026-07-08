import {
	Check,
	Clock,
	Copy,
	Download,
	FileText,
	Film,
	Image as ImageIcon,
	MessageSquare,
	RefreshCw,
	X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
	getResult,
	listResults,
	type ResultDetail,
	type ResultListItem,
} from "../api/results";
import SocialCopyPackagePanel from "../components/SocialCopyPackagePanel";

// RESULTS HUB — the single durable home for every finished generation. For each
// result the operator can: (1) preview + download the file (48h), (2) copy the
// exact prompt + settings to manually re-drive Google Flow if automation breaks
// (the record is durable — it outlives the file), and (3) author + copy the
// per-platform social captions (reusing SocialCopyPackagePanel). Two-pronged:
// manual-recovery archive + publish-ready deliverable.

const KIND_FILTERS = ["ALL", "video", "image"] as const;
type KindFilter = (typeof KIND_FILTERS)[number];

const KIND_LABEL: Record<KindFilter, string> = {
	ALL: "All",
	video: "Videos",
	image: "Images",
};

function expiryTone(hours: number | null): string {
	if (hours == null) return "text-slate-500";
	if (hours <= 6) return "text-red-300";
	if (hours <= 24) return "text-amber-300";
	return "text-emerald-300";
}

function fmtDate(iso: string | null): string {
	if (!iso) return "—";
	const d = new Date(iso);
	return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

// ─── Copy-to-clipboard button ────────────────────────────────────────
function CopyButton({
	value,
	label = "Copy",
	disabled,
}: {
	value: string;
	label?: string;
	disabled?: boolean;
}) {
	const [copied, setCopied] = useState(false);
	const onCopy = async () => {
		try {
			await navigator.clipboard.writeText(value);
			setCopied(true);
			setTimeout(() => setCopied(false), 1500);
		} catch {
			setCopied(false);
		}
	};
	return (
		<button
			type="button"
			onClick={() => void onCopy()}
			disabled={disabled || !value}
			className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200 disabled:opacity-40"
		>
			{copied ? <Check size={11} /> : <Copy size={11} />}
			{copied ? "Copied" : label}
		</button>
	);
}

// ─── Caption status pill ─────────────────────────────────────────────
function CaptionPill({ summary }: { summary: { count: number; approved: number } }) {
	if (!summary || summary.count === 0)
		return (
			<span className="inline-flex items-center gap-1 rounded-full border border-slate-700 bg-slate-900/60 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-widest text-slate-500">
				<MessageSquare size={9} /> No caption
			</span>
		);
	const tone =
		summary.approved > 0
			? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
			: "border-amber-500/40 bg-amber-500/10 text-amber-300";
	return (
		<span
			className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9px] font-semibold uppercase tracking-widest ${tone}`}
		>
			<MessageSquare size={9} />
			{summary.approved > 0
				? `${summary.approved} approved`
				: `${summary.count} draft${summary.count > 1 ? "s" : ""}`}
		</span>
	);
}

// ─── Settings row ────────────────────────────────────────────────────
function SettingRow({ label, value }: { label: string; value: string | null }) {
	if (!value) return null;
	return (
		<div className="flex items-baseline gap-2 text-xs">
			<span className="w-24 flex-shrink-0 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
				{label}
			</span>
			<span className="text-slate-200">{value}</span>
		</div>
	);
}

// ─── Detail modal (3 sections) ───────────────────────────────────────
function ResultDetailModal({
	mediaId,
	onClose,
}: {
	mediaId: string;
	onClose: () => void;
}) {
	const [detail, setDetail] = useState<ResultDetail | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let alive = true;
		setLoading(true);
		setError(null);
		getResult(mediaId)
			.then((d) => {
				if (alive) setDetail(d);
			})
			.catch((e) => {
				if (alive) setError(String(e));
			})
			.finally(() => {
				if (alive) setLoading(false);
			});
		return () => {
			alive = false;
		};
	}, [mediaId]);

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			if (e.key === "Escape") onClose();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [onClose]);

	const snap = detail?.snapshot ?? null;
	const settingsBlob = useMemo(() => {
		if (!snap) return "";
		const lines = [
			snap.mode ? `Mode: ${snap.mode}` : "",
			snap.model_label ? `Model: ${snap.model_label}` : "",
			snap.aspect_ratio ? `Aspect: ${snap.aspect_ratio}` : "",
			snap.duration_s ? `Duration: ${snap.duration_s}s` : "",
			snap.count_setting ? `Count: ${snap.count_setting}` : "",
			snap.reference_media_ids.length
				? `References: ${snap.reference_media_ids.join(", ")}`
				: "",
			"",
			"Prompt:",
			snap.final_prompt_text,
		];
		return lines.filter((l) => l !== "").join("\n");
	}, [snap]);

	return (
		<div
			className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/80 p-4 backdrop-blur-sm"
			role="dialog"
			aria-modal="true"
		>
			{/* click-outside */}
			<button
				type="button"
				aria-label="Close"
				className="absolute inset-0 cursor-default"
				onClick={onClose}
			/>
			<div className="relative z-10 my-4 w-full max-w-2xl space-y-4 rounded-2xl border border-slate-800 bg-slate-950 p-5 shadow-2xl">
				<div className="flex items-start justify-between gap-3">
					<div className="min-w-0">
						<div className="text-sm font-semibold tracking-wide text-slate-100">
							{detail?.artifact_kind === "image" ? "🖼 Image" : "🎬 Video"} result
						</div>
						<div className="mt-0.5 truncate font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">
							media {mediaId}
						</div>
					</div>
					<button
						type="button"
						onClick={onClose}
						aria-label="Close detail"
						className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-slate-700 text-slate-400 hover:border-blue-400/50 hover:text-blue-200"
					>
						<X size={15} />
					</button>
				</div>

				{loading && (
					<div className="py-8 text-center text-xs text-slate-500">Loading…</div>
				)}
				{error && (
					<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200 break-all">
						{error}
					</div>
				)}

				{detail && !loading && (
					<div className="space-y-5">
						{/* SECTION 1 — Preview + Download */}
						<section className="space-y-2">
							<div className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
								1 · Preview &amp; Download
							</div>
							{detail.file_available && detail.retrieved_url ? (
								<>
									{detail.artifact_kind === "image" ? (
										<img
											src={detail.retrieved_url}
											alt="Generated result"
											className="max-h-80 rounded-xl border border-slate-800"
										/>
									) : (
										// biome-ignore lint/a11y/useMediaCaption: generated previews ship no caption track
										<video
											src={detail.retrieved_url}
											controls
											playsInline
											className="max-h-80 rounded-xl border border-slate-800"
										/>
									)}
									<div className="flex items-center gap-3">
										<a
											href={detail.retrieved_url}
											download={`${mediaId}.${detail.artifact_kind === "image" ? "jpg" : "mp4"}`}
											className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-[11px] font-semibold text-emerald-200 hover:bg-emerald-500/20"
										>
											<Download size={12} /> Download
										</a>
										{detail.size_mb != null && (
											<span className="text-[11px] text-slate-500">
												{detail.size_mb}MB
											</span>
										)}
										{detail.expires_in_hours != null && (
											<span
												className={`inline-flex items-center gap-1 text-[11px] ${expiryTone(detail.expires_in_hours)}`}
											>
												<Clock size={11} /> file luput dalam{" "}
												{detail.expires_in_hours}j
											</span>
										)}
									</div>
								</>
							) : (
								<div className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-3 text-[11px] text-slate-400">
									Fail sudah luput (retensi 48 jam) — tapi prompt, settings &amp;
									caption di bawah <span className="text-slate-200">kekal</span>{" "}
									untuk rujukan &amp; manual fallback.
								</div>
							)}
						</section>

						{/* SECTION 2 — Prompt & Settings (manual Flow fallback) */}
						<section className="space-y-2">
							<div className="flex items-center justify-between gap-2">
								<div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
									<FileText size={12} /> 2 · Prompt &amp; Settings
								</div>
								{snap && (
									<CopyButton value={settingsBlob} label="Copy all" />
								)}
							</div>
							{snap ? (
								<div className="space-y-3">
									<div className="space-y-1">
										<SettingRow label="Product" value={snap.product_name} />
										<SettingRow label="Mode" value={snap.mode} />
										<SettingRow label="Model" value={snap.model_label} />
										<SettingRow label="Aspect" value={snap.aspect_ratio} />
										<SettingRow
											label="Duration"
											value={snap.duration_s ? `${snap.duration_s}s` : null}
										/>
										<SettingRow
											label="Count"
											value={snap.count_setting ? String(snap.count_setting) : null}
										/>
										<SettingRow
											label="References"
											value={
												snap.reference_media_ids.length
													? snap.reference_media_ids.join(", ")
													: null
											}
										/>
									</div>
									<div className="space-y-1">
										<div className="flex items-center justify-between">
											<span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
												Prompt (fired to Flow)
											</span>
											<CopyButton
												value={snap.final_prompt_text}
												label="Copy prompt"
											/>
										</div>
										<textarea
											readOnly
											value={snap.final_prompt_text}
											rows={5}
											className="w-full resize-y rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-200"
										/>
									</div>
								</div>
							) : (
								<div className="rounded-lg border border-slate-800 bg-slate-900/50 px-3 py-3 text-[11px] text-slate-400">
									Tiada rekod prompt tersimpan untuk artifact ini (dijana sebelum
									Results Hub atau melalui lane langsung). Fail masih boleh
									dimuat turun di atas.
								</div>
							)}
						</section>

						{/* SECTION 3 — Captions (reuse SocialCopyPackagePanel) */}
						<section className="space-y-2">
							<div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">
								<MessageSquare size={12} /> 3 · Captions
							</div>
							<SocialCopyPackagePanel
								mediaId={mediaId}
								sourceMode={detail.mode ?? ""}
								productName={detail.product_name}
							/>
						</section>
					</div>
				)}
			</div>
		</div>
	);
}

// ─── Hub card ────────────────────────────────────────────────────────
function ResultCard({
	item,
	onOpen,
}: {
	item: ResultListItem;
	onOpen: () => void;
}) {
	return (
		<button
			type="button"
			onClick={onOpen}
			className="group flex flex-col gap-2 rounded-2xl border border-slate-800 bg-slate-950/70 p-3 text-left transition-colors hover:border-blue-400/40"
		>
			<div className="relative flex aspect-video items-center justify-center overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60">
				{item.file_available && item.retrieved_url ? (
					item.artifact_kind === "image" ? (
						<img
							src={item.retrieved_url}
							alt="Result preview"
							className="h-full w-full object-cover"
						/>
					) : (
						<Film size={26} className="text-slate-600 group-hover:text-blue-300" />
					)
				) : (
					<div className="flex flex-col items-center gap-1 text-slate-600">
						{item.artifact_kind === "image" ? (
							<ImageIcon size={22} />
						) : (
							<Film size={22} />
						)}
						<span className="text-[9px] uppercase tracking-widest">
							file expired
						</span>
					</div>
				)}
				<span className="absolute left-2 top-2 rounded border border-slate-700 bg-slate-950/80 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-widest text-slate-300">
					{item.mode ?? item.artifact_kind}
				</span>
			</div>
			<div className="min-w-0 space-y-1">
				<div className="truncate text-xs font-semibold text-slate-200">
					{item.product_name ?? "Untitled result"}
				</div>
				<div className="flex flex-wrap items-center gap-1.5">
					<CaptionPill summary={item.caption_summary} />
					{item.expires_in_hours != null && (
						<span
							className={`text-[9px] uppercase tracking-widest ${expiryTone(item.expires_in_hours)}`}
						>
							{item.expires_in_hours}j
						</span>
					)}
				</div>
				<div className="truncate text-[10px] text-slate-600">
					{item.model_label ?? "—"} · {fmtDate(item.created_at)}
				</div>
			</div>
		</button>
	);
}

// ─── Page ────────────────────────────────────────────────────────────
export default function ResultsHubPage() {
	const [items, setItems] = useState<ResultListItem[]>([]);
	const [kind, setKind] = useState<KindFilter>("ALL");
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [openMediaId, setOpenMediaId] = useState<string | null>(null);

	const refresh = useCallback(async () => {
		setLoading(true);
		setError(null);
		try {
			const resp = await listResults({
				kind: kind === "ALL" ? undefined : kind,
				limit: 60,
			});
			setItems(resp.results);
		} catch (e) {
			setError(String(e));
		} finally {
			setLoading(false);
		}
	}, [kind]);

	useEffect(() => {
		void refresh();
	}, [refresh]);

	return (
		<div className="mx-auto max-w-6xl p-4 md:p-8">
			<div className="mb-6 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
				<div>
					<h1 className="text-lg font-semibold tracking-wide text-slate-100">
						Results
					</h1>
					<p className="mt-1 max-w-2xl text-xs leading-relaxed text-slate-400">
						Tempat pengumpulan hasil generation. Setiap hasil: muat turun fail,
						salin prompt + settings untuk manual fallback Google Flow, dan bina
						caption per platform untuk copy-paste ke social media. Fail luput 48
						jam; rekod prompt &amp; caption kekal.
					</p>
				</div>
				<div className="flex items-center gap-2">
					<div className="flex overflow-hidden rounded-lg border border-slate-800">
						{KIND_FILTERS.map((k) => (
							<button
								type="button"
								key={k}
								onClick={() => setKind(k)}
								className={`px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] transition-colors ${
									kind === k
										? "bg-blue-600/20 text-blue-200"
										: "bg-slate-950 text-slate-400 hover:text-slate-200"
								}`}
							>
								{KIND_LABEL[k]}
							</button>
						))}
					</div>
					<button
						type="button"
						onClick={() => void refresh()}
						className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200"
					>
						<RefreshCw size={12} className={loading ? "animate-spin" : ""} />
						Refresh
					</button>
				</div>
			</div>

			{error && (
				<div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200 break-all">
					{error}
				</div>
			)}

			{!loading && items.length === 0 && !error && (
				<div className="rounded-2xl border border-slate-800 bg-slate-950/50 px-4 py-10 text-center text-sm text-slate-500">
					Belum ada hasil. Hasil generation baru akan muncul di sini secara
					automatik.
				</div>
			)}

			<div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
				{items.map((item) => (
					<ResultCard
						key={item.media_id}
						item={item}
						onOpen={() => setOpenMediaId(item.media_id)}
					/>
				))}
			</div>

			{openMediaId && (
				<ResultDetailModal
					mediaId={openMediaId}
					onClose={() => {
						setOpenMediaId(null);
						void refresh();
					}}
				/>
			)}
		</div>
	);
}
