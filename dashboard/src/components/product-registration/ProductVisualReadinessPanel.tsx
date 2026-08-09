import { useEffect, useState } from "react";
import {
	approveProductTruthLock,
	productTruthCutoutPreviewUrl,
} from "../../api/productTruthLock";
import {
	fetchProductVisualReadiness,
	prepareProductCutout,
	rebuildProductCutout,
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
	NOT_PREPARED: "bg-slate-700/40 text-slate-400",
};

const COMPACT_STATUS_LABEL: Record<string, string> = {
	AVAILABLE: "Available",
	MISSING: "Missing",
	APPROVED: "Approved",
	PENDING_REVIEW: "Review",
	PREPARING: "Preparing",
	PREPARATION_FAILED: "Failed",
	BLOCKED: "Blocked",
	NOT_PREPARED: "Not prepared",
	VISUAL_GROUNDING_READY: "Ready",
	VISUAL_GROUNDING_BLOCKED: "Blocked",
	EXACT_COMMERCE_CUTOUT_READY: "Ready",
	EXACT_COMMERCE_REVIEW_REQUIRED: "Review required",
	EXACT_COMMERCE_BLOCKED: "Blocked",
};

const label = (value: string | undefined | null): string =>
	(value || "NOT_PREPARED").replace(/_/g, " ");

const compactLabel = (value: string | undefined | null): string => {
	const normalized = value || "NOT_PREPARED";
	if (COMPACT_STATUS_LABEL[normalized]) return COMPACT_STATUS_LABEL[normalized];
	return normalized
		.replace(/_/g, " ")
		.toLowerCase()
		.replace(/(^|\s)\S/g, (character) => character.toUpperCase());
};

function Status({
	name,
	value,
	compact = false,
}: {
	name: string;
	value: string | undefined;
	compact?: boolean;
}) {
	const fullLabel = label(value);
	return (
		<div className={`${compact ? "min-w-0 rounded-lg border border-slate-800/80 bg-slate-950/30 p-1.5" : "min-w-0"}`}>
			<div className="mb-1 text-[8px] font-bold uppercase tracking-widest text-slate-500">
				{name}
			</div>
			<span
				title={compact ? fullLabel : undefined}
				className={`inline-flex max-w-full rounded ${compact ? "text-[8px]" : "text-[9px]"} font-bold ${
					compact
						? "min-h-6 w-full items-center justify-center whitespace-normal break-words px-1 py-1 text-center leading-tight"
						: "truncate px-1.5 py-0.5"
				} ${BADGE[value || ""] || "bg-slate-700/40 text-slate-400"}`}
			>
				{compact ? compactLabel(value) : fullLabel}
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
	const [busy, setBusy] = useState<"prepare" | "rebuild" | "approve" | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [reviewedBy, setReviewedBy] = useState("");
	const [reviewNote, setReviewNote] = useState("");
	const [confirmIdentity, setConfirmIdentity] = useState(false);
	const [confirmLabelLogo, setConfirmLabelLogo] = useState(false);
	const [confirmGeometryScale, setConfirmGeometryScale] = useState(false);

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

	if (!readiness) {
		return (
			<div className="w-full max-w-full overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-[11px] text-slate-500">
				Loading product visual readiness…
			</div>
		);
	}

	return (
		<div className={`rounded-xl border border-slate-800 bg-slate-900/40 ${compact ? "w-full max-w-full overflow-hidden p-2" : "p-5"}`} data-testid="product-visual-readiness">
			<div className="flex min-w-0 items-start justify-between gap-2">
				<div className="min-w-0">
					<h3 className={`${compact ? "text-[10px]" : "text-sm"} font-bold uppercase tracking-widest text-white`}>
						{compact ? "Visual" : "PRODUCT VISUAL READINESS"}
					</h3>
					{!compact && (
						<p className="mt-1 text-[11px] text-slate-500">
							Same-product evidence only. Deterministic preparation is review-only; Exact Commerce remains fail-closed until approved.
						</p>
					)}
				</div>
				{!compact && readiness.provider_operations === 0 && (
					<span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-widest text-emerald-300">
						No provider spend
					</span>
				)}
			</div>

			<div className={`mt-3 grid min-w-0 gap-2 ${compact ? "grid-cols-2" : "grid-cols-2 md:grid-cols-4"}`}>
				<Status compact={compact} name="Reference" value={readiness.canonical_media_status} />
				<Status compact={compact} name="Cutout" value={readiness.cutout_status} />
				<Status compact={compact} name="Visual Ready" value={readiness.visual_grounding_status} />
				<Status compact={compact} name="Exact Commerce" value={readiness.exact_commerce_status} />
			</div>

			{!compact && (
				<div className="mt-4 grid gap-2 text-[10px] text-slate-400 md:grid-cols-2">
					<div>Source: <span className="text-slate-200">{label(readiness.visual_grounding_source)}</span></div>
					<div>Reference Pack: <span className="text-slate-200">{label(readiness.reference_pack_status)}</span></div>
					<div>Review: <span className="text-slate-200">{label(readiness.cutout_review_status)}</span></div>
					<div>Attempts: <span className="text-slate-200">{readiness.attempt_count ?? 0}</span></div>
				</div>
			)}

			{(readiness.blockers.length > 0 || readiness.warnings.length > 0) && !compact && (
				<div className="mt-3 space-y-1 text-[10px]">
					{[...readiness.blockers, ...readiness.warnings].slice(0, 4).map((item) => (
						<div key={item} className="text-amber-300">• {label(item)}</div>
					))}
				</div>
			)}

			<div className={compact ? "mt-3 grid grid-cols-2 gap-1.5" : "mt-4 flex flex-wrap items-center gap-2"}>
				{readiness.can_prepare_cutout && (
					<button type="button" onClick={() => void refresh("prepare")} disabled={busy !== null} className={`${compact ? "min-w-0 w-full truncate px-2" : "px-2.5"} rounded-lg bg-indigo-600/80 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40`}>
						{busy === "prepare" ? "Preparing…" : "Prepare"}
					</button>
				)}
				{readiness.can_rebuild_cutout && readiness.cutout_status !== "NOT_PREPARED" && (
					<button type="button" onClick={() => void refresh("rebuild")} disabled={busy !== null} className={`${compact ? "min-w-0 w-full truncate px-2" : "px-2.5"} rounded-lg bg-slate-700 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-200 disabled:opacity-40`}>
						{busy === "rebuild" ? "Rebuilding…" : "Rebuild"}
					</button>
				)}
				{readiness.can_review_cutout && (
					<button type="button" onClick={onOpenReview} className={`${compact ? "min-w-0 w-full truncate px-2" : "px-2.5"} rounded-lg bg-amber-500/20 py-1.5 text-[9px] font-bold uppercase tracking-widest text-amber-200`}>
						Review
					</button>
				)}
				{productSourceUrl && readiness.can_open_source && (
					<a title={compact ? "Open source" : undefined} href={productSourceUrl} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()} className={`${compact ? "min-w-0 w-full truncate px-2" : "px-2.5"} rounded-lg bg-slate-800 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-300`}>
						{compact ? "Source" : "Open Source"}
					</a>
				)}
			</div>

			{showApprovalForm && readiness.can_review_cutout && (
				<div className="mt-5 border-t border-slate-800 pt-4" data-testid="product-visual-approval">
					<div className="mb-3 flex flex-wrap items-start gap-4">
						{readiness.cutout_preview_available && (
							<img src={productTruthCutoutPreviewUrl(productId)} alt="Deterministic cutout candidate" className="h-32 w-32 rounded-lg border border-slate-700 bg-white object-contain" />
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

			{error && <div className="mt-3 break-words text-[10px] text-red-300">{error}</div>}
		</div>
	);
}
