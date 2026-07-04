import { AlertTriangle, CheckCircle2, RefreshCw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
	approveSocialCopyPackage,
	generateSocialCopyPackage,
	listSocialCopyPackages,
	type SocialCopyPackage,
	type SocialPlatform,
	SOCIAL_PLATFORMS,
	suggestSocialCopy,
	updateSocialCopyPackage,
} from "../api/socialCopyPackages";

// ─── Social Copy Package panel ───────────────────────────────
// Shared across all generator modes (T2V/F2V/HYBRID/I2V/IMG). Given a finished
// artifact (media_id) it lets the operator author, edit, and approve
// platform-specific caption/comment copy that Postiz Publish later prefills.
// BOSMAX never posts or does social OAuth here — this only persists copy.

const PLATFORM_LABEL: Record<SocialPlatform, string> = {
	tiktok: "TikTok",
	instagram: "Instagram",
	facebook: "Facebook",
	threads: "Threads",
	x: "X/Twitter",
};

const FIRST_COMMENT_LABEL: Record<SocialPlatform, string> = {
	tiktok: "Pinned comment",
	instagram: "First comment",
	facebook: "First comment",
	threads: "First reply",
	x: "First reply",
};

interface FormState {
	caption: string;
	firstComment: string;
	hashtags: string;
	cta: string;
	tone: string;
	language: string;
}

// Copy language options. Values are persisted as-is on the package's `language`
// column (default "ms"); labels are operator-facing.
const LANGUAGE_OPTIONS: { value: string; label: string }[] = [
	{ value: "ms", label: "Malay" },
	{ value: "ms-slang", label: "Malay slang" },
	{ value: "en", label: "English" },
	{ value: "mixed", label: "Mixed" },
];

const DEFAULT_LANGUAGE = "ms";

const EMPTY_FORM: FormState = {
	caption: "",
	firstComment: "",
	hashtags: "",
	cta: "",
	tone: "",
	language: DEFAULT_LANGUAGE,
};

function parseHashtags(raw: string): string[] {
	return raw
		.split(/[\s,]+/)
		.map((t) => t.trim())
		.filter(Boolean)
		.map((t) => (t.startsWith("#") ? t : `#${t}`));
}

function StatusDot({ pkg }: { pkg: SocialCopyPackage | undefined }) {
	if (!pkg)
		return <span className="h-2 w-2 rounded-full bg-slate-600" aria-hidden />;
	const color =
		pkg.compliance_status === "BLOCKED"
			? "bg-red-400"
			: pkg.status === "APPROVED"
				? "bg-emerald-400"
				: "bg-amber-400";
	return <span className={`h-2 w-2 rounded-full ${color}`} aria-hidden />;
}

export default function SocialCopyPackagePanel({
	mediaId,
	sourceMode,
	productName,
}: {
	mediaId: string;
	sourceMode: string;
	productName?: string | null;
}) {
	const [packages, setPackages] = useState<SocialCopyPackage[]>([]);
	const [platform, setPlatform] = useState<SocialPlatform>("tiktok");
	const [form, setForm] = useState<FormState>(EMPTY_FORM);
	const [busy, setBusy] = useState(false);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);

	const load = useCallback(async () => {
		setLoading(true);
		try {
			const resp = await listSocialCopyPackages({ artifact_media_id: mediaId });
			setPackages(resp.packages);
		} catch (e) {
			setError(String(e));
		} finally {
			setLoading(false);
		}
	}, [mediaId]);

	useEffect(() => {
		void load();
	}, [load]);

	const current = useMemo(
		() => packages.find((p) => p.platform === platform),
		[packages, platform],
	);

	// Seed the editor from the saved variant (or empty) when platform changes.
	useEffect(() => {
		if (current) {
			setForm({
				caption: current.caption,
				firstComment: current.first_comment,
				hashtags: (current.hashtags_json ?? []).join(" "),
				cta: current.call_to_action,
				tone: current.tone,
				language: current.language || DEFAULT_LANGUAGE,
			});
		} else {
			setForm(EMPTY_FORM);
		}
		setError(null);
	}, [current]);

	const handleSuggest = async () => {
		setBusy(true);
		setError(null);
		try {
			const s = await suggestSocialCopy(platform, {
				source_mode: sourceMode,
				product_name: productName ?? null,
			});
			setForm((prev) => ({
				caption: s.caption,
				firstComment: s.first_comment,
				hashtags: s.hashtags.join(" "),
				cta: s.call_to_action,
				tone: s.tone,
				language: prev.language,
			}));
		} catch (e) {
			setError(String(e));
		} finally {
			setBusy(false);
		}
	};

	const handleSave = async () => {
		setBusy(true);
		setError(null);
		try {
			if (current) {
				await updateSocialCopyPackage(current.package_id, {
					caption: form.caption,
					first_comment: form.firstComment,
					hashtags: parseHashtags(form.hashtags),
					call_to_action: form.cta,
					tone: form.tone,
					language: form.language,
				});
			} else {
				await generateSocialCopyPackage({
					artifact_media_id: mediaId,
					platform,
					source_mode: sourceMode,
					caption: form.caption,
					first_comment: form.firstComment,
					hashtags: parseHashtags(form.hashtags),
					call_to_action: form.cta,
					tone: form.tone,
					language: form.language,
				});
			}
			await load();
		} catch (e) {
			setError(String(e));
		} finally {
			setBusy(false);
		}
	};

	const handleApprove = async () => {
		if (!current) return;
		setBusy(true);
		setError(null);
		try {
			await approveSocialCopyPackage(current.package_id);
			await load();
		} catch (e) {
			setError(String(e));
		} finally {
			setBusy(false);
		}
	};

	const blocked = current?.compliance_status === "BLOCKED";
	const blockers = current?.blockers_json ?? [];
	const warnings = current?.warnings_json ?? [];

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4 space-y-4">
			<div className="flex items-center justify-between gap-3">
				<div className="text-xs font-bold uppercase tracking-[0.18em] text-slate-200">
					Social Copy Package
				</div>
				<button
					type="button"
					onClick={() => void load()}
					className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-300 hover:border-blue-400/50 hover:text-blue-200"
				>
					<RefreshCw size={12} className={loading ? "animate-spin" : ""} />
					Refresh
				</button>
			</div>
			<p className="text-[11px] leading-relaxed text-slate-400">
				Write platform-specific caption/comment copy for this artifact. It is
				claim-safe checked and, once approved, prefills Postiz Publish. Nothing
				is posted here.
			</p>

			{/* Platform tabs */}
			<div className="flex flex-wrap gap-1.5">
				{SOCIAL_PLATFORMS.map((p) => {
					const pkg = packages.find((x) => x.platform === p);
					const active = p === platform;
					return (
						<button
							type="button"
							key={p}
							onClick={() => setPlatform(p)}
							className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[11px] font-semibold transition-colors ${active ? "border-blue-400/70 bg-blue-500/10 text-blue-100" : "border-slate-800 bg-slate-900/50 text-slate-300 hover:border-slate-600"}`}
						>
							<StatusDot pkg={pkg} />
							{PLATFORM_LABEL[p]}
						</button>
					);
				})}
			</div>

			{/* Editor */}
			<div className="space-y-3">
				<div className="flex flex-wrap items-center gap-2">
					<span className="text-[10px] font-bold uppercase tracking-[0.16em] text-slate-500">
						{PLATFORM_LABEL[platform]} copy
					</span>
					{current && (
						<span
							className={`rounded border px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest ${current.status === "APPROVED" ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-slate-700 bg-slate-800 text-slate-400"}`}
						>
							{current.status}
						</span>
					)}
					<button
						type="button"
						onClick={() => void handleSuggest()}
						disabled={busy}
						className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-1.5 text-[10px] font-semibold text-blue-200 hover:bg-blue-500/20 disabled:opacity-40"
					>
						<Sparkles size={11} />
						Suggest copy
					</button>
				</div>

				<label className="block space-y-1">
					<span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
						Tone / style
					</span>
					<input
						type="text"
						value={form.tone}
						onChange={(e) => setForm({ ...form, tone: e.target.value })}
						placeholder="e.g. punchy, hook-driven"
						className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs text-slate-100 placeholder:text-slate-600"
					/>
				</label>

				<label className="block space-y-1">
					<span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
						Language
					</span>
					<select
						value={form.language}
						onChange={(e) => setForm({ ...form, language: e.target.value })}
						className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs text-slate-100"
					>
						{LANGUAGE_OPTIONS.map((opt) => (
							<option key={opt.value} value={opt.value}>
								{opt.label}
							</option>
						))}
					</select>
				</label>

				<label className="block space-y-1">
					<span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
						Caption
					</span>
					<textarea
						value={form.caption}
						onChange={(e) => setForm({ ...form, caption: e.target.value })}
						rows={3}
						placeholder="Platform caption…"
						className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-600"
					/>
				</label>

				<label className="block space-y-1">
					<span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
						{FIRST_COMMENT_LABEL[platform]}
					</span>
					<textarea
						value={form.firstComment}
						onChange={(e) => setForm({ ...form, firstComment: e.target.value })}
						rows={2}
						placeholder="Pinned / first comment (optional)…"
						className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-600"
					/>
				</label>

				<div className="grid grid-cols-1 gap-3 md:grid-cols-2">
					<label className="block space-y-1">
						<span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
							Hashtags
						</span>
						<input
							type="text"
							value={form.hashtags}
							onChange={(e) => setForm({ ...form, hashtags: e.target.value })}
							placeholder="#fyp #lifestyle"
							className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs text-slate-100 placeholder:text-slate-600"
						/>
					</label>
					<label className="block space-y-1">
						<span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
							Call to action (CTA)
						</span>
						<input
							type="text"
							value={form.cta}
							onChange={(e) => setForm({ ...form, cta: e.target.value })}
							placeholder="e.g. Tap keranjang kuning"
							className="w-full rounded-lg border border-slate-800 bg-slate-900 px-3 py-1.5 text-xs text-slate-100 placeholder:text-slate-600"
						/>
					</label>
				</div>

				{/* Compliance / claim-safe surface */}
				{blocked && (
					<div className="flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-2.5">
						<AlertTriangle size={13} className="mt-0.5 flex-shrink-0 text-red-300" />
						<div className="text-[11px] text-red-200">
							Claim-safe check blocked this copy — remove unsupported
							medical/guarantee claims before approving.
							<div className="mt-1 font-mono text-[10px] text-red-300/80">
								{blockers.join(" · ")}
							</div>
						</div>
					</div>
				)}
				{!blocked && warnings.length > 0 && (
					<div className="font-mono text-[10px] text-amber-300/80">
						warnings: {warnings.join(" · ")}
					</div>
				)}

				{error && (
					<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-200 break-all">
						{error}
					</div>
				)}

				<div className="flex flex-wrap items-center gap-2">
					<button
						type="button"
						onClick={() => void handleSave()}
						disabled={busy}
						className="inline-flex items-center gap-1.5 rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 py-2 text-[11px] font-semibold text-blue-200 hover:bg-blue-500/20 disabled:opacity-40"
					>
						{current ? "Save changes" : "Save copy package"}
					</button>
					<button
						type="button"
						onClick={() => void handleApprove()}
						disabled={busy || !current || blocked || current?.status === "APPROVED"}
						title={
							!current
								? "Save the copy package first"
								: blocked
									? "Fix claim-safe issues before approving"
									: ""
						}
						className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/50 bg-emerald-500/15 px-3 py-2 text-[11px] font-bold text-emerald-100 hover:bg-emerald-500/25 disabled:cursor-not-allowed disabled:opacity-40"
					>
						<CheckCircle2 size={12} />
						Approve
					</button>
					{current?.status === "APPROVED" && (
						<span className="text-[11px] text-emerald-300">
							Approved — will prefill Postiz for {PLATFORM_LABEL[platform]}.
						</span>
					)}
					{!current && (
						<span className="text-[11px] text-slate-500">
							Save first, then Approve to make it available in Postiz.
						</span>
					)}
				</div>
			</div>
		</section>
	);
}
