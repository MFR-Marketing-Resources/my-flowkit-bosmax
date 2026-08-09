import { useEffect, useRef, useState, type ChangeEvent } from "react";
import {
	approveProductTruthLock,
	productTruthCutoutPreviewUrl,
} from "../../api/productTruthLock";
import {
	fetchProductVisualReadiness,
	prepareProductCutout,
	rejectProductCutout,
	rebuildProductCutout,
	uploadManualProductCutout,
	useOriginalProductFallback,
} from "../../api/productVisualOnboarding";
import type { ProductVisualReadiness } from "../../types";

interface Props {
	productId: string;
	productSourceUrl?: string | null;
	readiness?: ProductVisualReadiness;
	compact?: boolean;
	showApprovalForm?: boolean;
	onOpenReview?: () => void;
	onChanged?: (readiness: ProductVisualReadiness) => void;
}

const BADGE: Record<string, string> = {
	AVAILABLE: "bg-emerald-500/15 text-emerald-300",
	APPROVED: "bg-emerald-500/15 text-emerald-300",
	PENDING_REVIEW: "bg-amber-500/15 text-amber-300",
	PREPARING: "bg-sky-500/15 text-sky-300",
	PREPARATION_FAILED: "bg-red-500/15 text-red-300",
	BLOCKED: "bg-red-500/15 text-red-300",
	REJECTED: "bg-red-500/15 text-red-300",
	SUPERSEDED: "bg-slate-700/40 text-slate-400",
	VISUAL_GROUNDING_READY_FALLBACK: "bg-amber-500/15 text-amber-300",
	CUTOUT_REQUIRED: "bg-amber-500/15 text-amber-300",
	NOT_PREPARED: "bg-slate-700/40 text-slate-400",
};

const label = (value: string | undefined | null): string =>
	(value || "NOT_PREPARED").replace(/_/g, " ");

function Status({ name, value }: { name: string; value: string | undefined }) {
	return (
		<div className="min-w-0">
			<div className="mb-1 text-[8px] font-bold uppercase tracking-widest text-slate-500">
				{name}
			</div>
			<span
				className={`inline-flex max-w-full truncate rounded px-1.5 py-0.5 text-[9px] font-bold ${BADGE[value || ""] || "bg-slate-700/40 text-slate-400"}`}
			>
				{label(value)}
			</span>
		</div>
	);
}

export default function ProductVisualReadinessPanel({
	productId,
	productSourceUrl,
	readiness: initialReadiness,
	compact = false,
	showApprovalForm = false,
	onOpenReview,
	onChanged,
}: Props) {
	const [readiness, setReadiness] = useState<ProductVisualReadiness | undefined>(
		initialReadiness,
	);
	const [busy, setBusy] = useState<"prepare" | "rebuild" | "approve" | "upload" | "reject" | "fallback" | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [reviewedBy, setReviewedBy] = useState("");
	const [reviewNote, setReviewNote] = useState("");
	const [confirmIdentity, setConfirmIdentity] = useState(false);
	const [confirmLabelLogo, setConfirmLabelLogo] = useState(false);
	const [confirmGeometryScale, setConfirmGeometryScale] = useState(false);
	const fileInputRef = useRef<HTMLInputElement>(null);

	useEffect(() => {
		setReadiness(initialReadiness);
	}, [initialReadiness]);

	useEffect(() => {
		if (initialReadiness) return;
		let cancelled = false;
		void fetchProductVisualReadiness(productId)
			.then((next) => {
				if (!cancelled) setReadiness(next);
			})
			.catch((err: unknown) => {
				if (!cancelled) setError(err instanceof Error ? err.message : "Visual readiness unavailable");
			});
		return () => {
			cancelled = true;
		};
	}, [initialReadiness, productId]);

	async function refresh(action: "prepare" | "rebuild") {
		setBusy(action);
		setError(null);
		try {
			const next = action === "prepare"
				? await prepareProductCutout(productId)
				: await rebuildProductCutout(productId);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Visual preparation failed");
		} finally {
			setBusy(null);
		}
	}

	async function approve() {
		if (!reviewedBy.trim() || !reviewNote.trim() || !confirmIdentity || !confirmLabelLogo || !confirmGeometryScale) {
			setError("Explicit reviewer identity, note, and all three confirmations are required.");
			return;
		}
		setBusy("approve");
		setError(null);
		try {
			await approveProductTruthLock(productId, {
				reviewed_by: reviewedBy.trim(),
				review_note: reviewNote.trim(),
				confirm_identity: confirmIdentity,
				confirm_label_logo: confirmLabelLogo,
				confirm_geometry_scale: confirmGeometryScale,
			});
			const next = await fetchProductVisualReadiness(productId);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Approval failed");
		} finally {
			setBusy(null);
		}
	}

	async function uploadManual(event: ChangeEvent<HTMLInputElement>) {
		const file = event.target.files?.[0];
		event.target.value = "";
		if (!file) return;
		if (file.type !== "image/png" || !file.name.toLowerCase().endsWith(".png")) {
			setError("Manual cutout override requires a PNG file with image/png MIME type.");
			return;
		}
		setBusy("upload");
		setError(null);
		try {
			const next = await uploadManualProductCutout(productId, file, reviewedBy.trim() || "operator");
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Manual cutout upload failed");
		} finally {
			setBusy(null);
		}
	}

	async function reject() {
		const operator = reviewedBy.trim() || window.prompt("Reviewer identity")?.trim() || "";
		const reason = window.prompt("Why is this cutout rejected?")?.trim() || "";
		if (!operator || !reason) {
			setError("Reviewer identity and rejection reason are required.");
			return;
		}
		setBusy("reject");
		setError(null);
		try {
			const next = await rejectProductCutout(productId, operator, reason);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Cutout rejection failed");
		} finally {
			setBusy(null);
		}
	}

	async function fallback() {
		const operator = reviewedBy.trim() || window.prompt("Operator identity")?.trim() || "";
		const reason = window.prompt("Why use the original same-product fallback?")?.trim() || "";
		if (!operator || !reason) {
			setError("Operator identity and fallback reason are required.");
			return;
		}
		setBusy("fallback");
		setError(null);
		try {
			const next = await useOriginalProductFallback(productId, operator, reason);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Fallback selection failed");
		} finally {
			setBusy(null);
		}
	}

	if (!readiness) {
		return (
			<div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-[11px] text-slate-500">
				Loading product visual readiness…
			</div>
		);
	}

	return (
		<div className={`rounded-xl border border-slate-800 bg-slate-900/40 ${compact ? "p-2" : "p-5"}`} data-testid="product-visual-readiness">
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div>
					<h3 className={`${compact ? "text-[10px]" : "text-sm"} font-bold uppercase tracking-widest text-white`}>
						{compact ? "Visual" : "PRODUCT VISUAL READINESS"}
					</h3>
					{!compact && (
						<p className="mt-1 text-[11px] text-slate-500">
							Same-product evidence only. Deterministic preparation is review-only; Exact Commerce remains fail-closed until approved.
						</p>
					)}
				</div>
				{readiness.provider_operations === 0 && (
					<span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-widest text-emerald-300">
						No provider spend
					</span>
				)}
			</div>

			<div className={`mt-3 grid gap-2 ${compact ? "grid-cols-2" : "grid-cols-2 md:grid-cols-4"}`}>
				<Status name="Reference" value={readiness.canonical_media_status} />
				<Status name="Cutout" value={readiness.cutout_status} />
				<Status name="Visual Ready" value={readiness.visual_grounding_status} />
				<Status name="Exact Commerce" value={readiness.exact_commerce_status} />
			</div>

			{!compact && (
				<div className="mt-3 grid gap-2 md:grid-cols-3">
					<Status name="Auto Candidate" value={readiness.auto_cutout_status} />
					<Status name="Manual Candidate" value={readiness.manual_cutout_status} />
					<Status name="Active Source" value={readiness.active_visual_source} />
				</div>
			)}

			{!compact && (
				<div className="mt-4 grid gap-2 text-[10px] text-slate-400 md:grid-cols-2">
					<div>Source: <span className="text-slate-200">{label(readiness.visual_grounding_source)}</span></div>
					<div>Reference Pack: <span className="text-slate-200">{label(readiness.reference_pack_status)}</span></div>
					<div>Review: <span className="text-slate-200">{label(readiness.cutout_review_status)}</span></div>
					<div>Attempts: <span className="text-slate-200">{readiness.attempt_count ?? 0}</span></div>
					<div>History: <span className="text-slate-200">{readiness.cutout_history_count ?? 0} preserved candidate(s)</span></div>
				</div>
			)}

			{!compact && (
				<div className="mt-4 grid gap-3 md:grid-cols-3" data-testid="product-cutout-comparison">
					{[
						["Original", readiness.original_preview_url],
						["Auto candidate", readiness.auto_cutout_preview_url],
						["Manual candidate", readiness.manual_cutout_preview_url],
					].map(([name, src]) => (
						<div key={name} className="rounded-lg border border-slate-800 p-2">
							<div className="mb-2 text-[9px] font-bold uppercase tracking-widest text-slate-500">{name}</div>
							<div className="flex h-36 items-center justify-center rounded bg-white" style={{ backgroundImage: "linear-gradient(45deg,#d1d5db 25%,transparent 25%),linear-gradient(-45deg,#d1d5db 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#d1d5db 75%),linear-gradient(-45deg,transparent 75%,#d1d5db 75%)", backgroundSize: "16px 16px", backgroundPosition: "0 0,0 8px,8px -8px,-8px 0" }}>
								{src ? <img src={src} alt={`${name} cutout`} className="max-h-full max-w-full object-contain" /> : <span className="text-[10px] text-slate-500">Not available</span>}
							</div>
						</div>
					))}
				</div>
			)}

			{(readiness.blockers.length > 0 || readiness.warnings.length > 0) && !compact && (
				<div className="mt-3 space-y-1 text-[10px]">
					{[...readiness.blockers, ...readiness.warnings].slice(0, 4).map((item) => (
						<div key={item} className="text-amber-300">• {label(item)}</div>
					))}
				</div>
			)}

			<div className="mt-4 flex flex-wrap items-center gap-2">
				{readiness.can_upload_manual_cutout && (
					<>
						<input ref={fileInputRef} type="file" accept="image/png,.png" onChange={(event) => void uploadManual(event)} className="hidden" />
						<button type="button" onClick={() => fileInputRef.current?.click()} disabled={busy !== null} className="rounded-lg bg-fuchsia-600/80 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">
							{busy === "upload" ? "Uploading…" : readiness.manual_cutout_status === "NOT_UPLOADED" ? "Upload My Cutout" : "Replace Manual Cutout"}
						</button>
					</>
				)}
				{readiness.can_prepare_cutout && (
					<button type="button" onClick={() => void refresh("prepare")} disabled={busy !== null} className="rounded-lg bg-indigo-600/80 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">
						{busy === "prepare" ? "Preparing…" : "Prepare Auto Cutout"}
					</button>
				)}
				{readiness.can_rebuild_cutout && readiness.cutout_status !== "NOT_PREPARED" && (
					<button type="button" onClick={() => void refresh("rebuild")} disabled={busy !== null} className="rounded-lg bg-slate-700 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-200 disabled:opacity-40">
						{busy === "rebuild" ? "Rebuilding…" : "Rebuild Auto Cutout"}
					</button>
				)}
				{readiness.can_review_cutout && (
					<button type="button" onClick={onOpenReview} className="rounded-lg bg-amber-500/20 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-amber-200">
						Review
					</button>
				)}
				{productSourceUrl && readiness.can_open_source && (
					<a href={productSourceUrl} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()} className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-300">
						Open Source
					</a>
				)}
				{readiness.can_reject_cutout && (
					<button type="button" onClick={() => void reject()} disabled={busy !== null} className="rounded-lg bg-red-500/20 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-red-200 disabled:opacity-40">
						{busy === "reject" ? "Rejecting…" : "Reject Cutout"}
					</button>
				)}
				{readiness.can_use_original_fallback && (
					<button type="button" onClick={() => void fallback()} disabled={busy !== null} className="rounded-lg bg-amber-500/20 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-amber-200 disabled:opacity-40">
						{busy === "fallback" ? "Selecting…" : "Use Original Fallback"}
					</button>
				)}
				{readiness.active_cutout_preview_url && (
					<a href={readiness.active_cutout_preview_url} download className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-300">Download Active Cutout</a>
				)}
			</div>

			{showApprovalForm && readiness.can_review_cutout && (
				<div className="mt-5 border-t border-slate-800 pt-4" data-testid="product-visual-approval">
					<div className="mb-3 flex flex-wrap items-start gap-4">
						{readiness.cutout_preview_available && (
							<img src={readiness.active_cutout_preview_url || productTruthCutoutPreviewUrl(productId)} alt="Deterministic cutout candidate" className="h-32 w-32 rounded-lg border border-slate-700 bg-white object-contain" />
						)}
						<div className="flex-1 text-[10px] leading-relaxed text-amber-200">
							This candidate is not approved. Inspect identity, label/logo, geometry, scale, and source lineage before using the explicit approval gate.
						</div>
					</div>
					<div className="grid gap-2 md:grid-cols-2">
						<input value={reviewedBy} onChange={(event) => setReviewedBy(event.target.value)} placeholder="Reviewer identity" className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white" />
						<input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="Review note" className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white" />
					</div>
					<div className="mt-3 grid gap-2 text-[10px] text-slate-300 md:grid-cols-3">
						<label><input type="checkbox" checked={confirmIdentity} onChange={(event) => setConfirmIdentity(event.target.checked)} className="mr-1" /> Identity</label>
						<label><input type="checkbox" checked={confirmLabelLogo} onChange={(event) => setConfirmLabelLogo(event.target.checked)} className="mr-1" /> Label / logo</label>
						<label><input type="checkbox" checked={confirmGeometryScale} onChange={(event) => setConfirmGeometryScale(event.target.checked)} className="mr-1" /> Geometry / scale</label>
					</div>
					<button type="button" onClick={() => void approve()} disabled={busy !== null || !reviewedBy.trim() || !reviewNote.trim() || !confirmIdentity || !confirmLabelLogo || !confirmGeometryScale} className="mt-3 rounded-lg bg-emerald-600/80 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">
						{busy === "approve" ? "Approving…" : "Approve Exact Cutout"}
					</button>
				</div>
			)}

			{error && <div className="mt-3 text-[10px] text-red-300">{error}</div>}
		</div>
	);
}
