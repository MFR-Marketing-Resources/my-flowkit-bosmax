import { useEffect, useMemo, useState } from "react";
import {
	approveSelectedProductVisuals,
	fetchProductVisualReadiness,
	type ProductVisualReviewApprovalResponse,
} from "../../api/productVisualOnboarding";
import type { Product, ProductVisualReadiness } from "../../types";

type Props = {
	product: Product;
	onClose: () => void;
	onApproved?: (response: ProductVisualReviewApprovalResponse) => void;
	onOpenProduct?: (
		productId: string,
		opts?: { tab?: "EDIT" | "INTELLIGENCE" | "CREATIVE" | "VISUAL" },
	) => void;
};

type ReviewCohort =
	| "PENDING_VISUAL_REVIEW"
	| "SOURCE_REUPLOAD_REQUIRED"
	| "BROKEN_APPROVED_VISUAL"
	| "VISUAL_READY"
	| "OTHER";

const CHECKS = [
	["identity", "Exact product identity"],
	["labelLogo", "Label / logo"],
	["geometry", "Geometry / scale"],
	["isolation", "Product only / no unrelated objects"],
] as const;

function cohortFor(readiness: ProductVisualReadiness): ReviewCohort {
	if (readiness.official_visual_status === "INVALID") return "BROKEN_APPROVED_VISUAL";
	if (
		readiness.cutout_review_status === "PENDING_REVIEW" &&
		readiness.canonical_media_status !== "AVAILABLE"
	) {
		return "SOURCE_REUPLOAD_REQUIRED";
	}
	if (readiness.cutout_review_status === "PENDING_REVIEW") {
		return "PENDING_VISUAL_REVIEW";
	}
	if (
		readiness.exact_commerce_status === "EXACT_COMMERCE_CUTOUT_READY" ||
		(readiness.cutout_status === "APPROVED" && readiness.cutout_review_status === "APPROVED")
	) {
		return "VISUAL_READY";
	}
	return "OTHER";
}

function statusLabel(readiness: ProductVisualReadiness): string {
	const cohort = cohortFor(readiness);
	return {
		PENDING_VISUAL_REVIEW: "PENDING REVIEW",
		SOURCE_REUPLOAD_REQUIRED: "SOURCE REUPLOAD REQUIRED",
		BROKEN_APPROVED_VISUAL: "BROKEN APPROVED VISUAL",
		VISUAL_READY: "VISUAL READY",
		OTHER: String(readiness.exact_commerce_status || "VISUAL STATUS UNKNOWN").replace(/_/g, " "),
	}[cohort];
}

function Preview({
	label,
	src,
	alt,
	transparent = false,
}: {
	label: string;
	src?: string | null;
	alt: string;
	transparent?: boolean;
}) {
	return (
		<div className="min-w-0 max-w-full">
			<div className="mb-1 text-[9px] font-bold uppercase tracking-widest text-slate-500">{label}</div>
			<div
				className={`flex h-48 min-w-0 max-w-full items-center justify-center overflow-hidden rounded-lg border border-slate-700 ${transparent ? "bg-white" : "bg-slate-950"}`}
			>
				{src ? (
					<img
						src={src}
						alt={alt}
						loading="lazy"
						decoding="async"
						className="h-full w-full min-w-0 object-contain"
						onError={(event) => {
							event.currentTarget.style.display = "none";
						}}
					/>
				) : (
					<span className="px-3 text-center text-[9px] font-semibold uppercase tracking-widest text-slate-600">
						Not available
					</span>
				)}
			</div>
		</div>
	);
}

function EvidenceValue({ value }: { value?: string | null }) {
	return <span className="block min-w-0 break-all font-mono text-[9px] text-slate-300">{value || "—"}</span>;
}

export default function ProductVisualReviewDrawer({
	product,
	onClose,
	onApproved,
	onOpenProduct,
}: Props) {
	const [readiness, setReadiness] = useState<ProductVisualReadiness | null>(product.visual_readiness || null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [reviewNote, setReviewNote] = useState("Owner visual approval pilot");
	const [checks, setChecks] = useState<Record<(typeof CHECKS)[number][0], boolean>>({
		identity: false,
		labelLogo: false,
		geometry: false,
		isolation: false,
	});
	const [approving, setApproving] = useState(false);
	const [approval, setApproval] = useState<ProductVisualReviewApprovalResponse | null>(null);

	useEffect(() => {
		const controller = new AbortController();
		setLoading(true);
		setError(null);
		void fetchProductVisualReadiness(product.id)
			.then((next) => {
				if (!controller.signal.aborted) setReadiness(next);
			})
			.catch((reason: unknown) => {
				if (!controller.signal.aborted) {
					setError(reason instanceof Error ? reason.message : "Visual detail failed to load.");
				}
			})
			.finally(() => {
				if (!controller.signal.aborted) setLoading(false);
			});
		return () => controller.abort();
	}, [product.id]);

	const cohort = readiness ? cohortFor(readiness) : "OTHER";
	const candidatePreview = useMemo(() => {
		if (!readiness) return null;
		if (readiness.candidate_source_kind === "USER_UPLOAD") {
			return readiness.manual_cutout_preview_url || readiness.active_cutout_preview_url;
		}
		return readiness.auto_cutout_preview_url || readiness.active_cutout_preview_url;
	}, [readiness]);
	const allChecksComplete = Object.values(checks).every(Boolean);
	const canApprove = Boolean(
		readiness &&
		cohort === "PENDING_VISUAL_REVIEW" &&
		readiness.can_approve_cutout &&
		readiness.canonical_cutout_sha256 &&
		readiness.canonical_cutout_media_id &&
		readiness.visual_lock_updated_at &&
		allChecksComplete &&
		reviewNote.trim(),
	);

	async function approve() {
		if (!readiness || !canApprove) return;
		setApproving(true);
		setError(null);
		try {
			const result = await approveSelectedProductVisuals({
				items: [
					{
						product_id: product.id,
						candidate_sha256: readiness.canonical_cutout_sha256 || "",
						candidate_media_id: readiness.canonical_cutout_media_id || "",
						expected_lock_updated_at: readiness.visual_lock_updated_at || "",
						candidate_source_kind:
							readiness.candidate_source_kind === "USER_UPLOAD" ? "USER_UPLOAD" : "AUTO_GENERATED",
					},
				],
				review_note: reviewNote.trim(),
				confirm_identity: checks.identity,
				confirm_label_logo: checks.labelLogo,
				confirm_geometry_scale: checks.geometry,
				confirm_product_isolation: checks.isolation,
			});
			setApproval(result);
			if (result.all_succeeded) onApproved?.(result);
		} catch (reason: unknown) {
			setError(reason instanceof Error ? reason.message : "Visual approval failed.");
		} finally {
			setApproving(false);
		}
	}

	return (
		<div
			className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-950/75 p-3 sm:p-6"
			role="presentation"
			onMouseDown={(event) => {
				if (event.target === event.currentTarget) onClose();
			}}
		>
			<section
				className="my-auto flex max-h-[calc(100vh-1.5rem)] w-full min-w-0 max-w-3xl flex-col overflow-hidden rounded-2xl border border-violet-500/40 bg-slate-950 shadow-2xl sm:max-h-[calc(100vh-3rem)]"
				role="dialog"
				aria-modal="true"
				aria-labelledby="visual-review-drawer-title"
				data-testid="product-visual-review-drawer"
			>
				<header className="flex min-w-0 items-start justify-between gap-3 border-b border-slate-800 px-4 py-3 sm:px-5">
					<div className="min-w-0">
						<div className="text-[9px] font-bold uppercase tracking-widest text-violet-300">Smart Registration · Visual Review</div>
						<h2 id="visual-review-drawer-title" className="mt-1 truncate text-base font-bold text-white">
							{product.product_display_name || product.raw_product_title}
						</h2>
						<div className="mt-1 flex min-w-0 flex-wrap items-center gap-2 text-[9px] text-slate-500">
							<span className="rounded bg-slate-800 px-1.5 py-0.5 font-bold uppercase tracking-widest text-slate-300">OWNER GOVERNED</span>
							<span className="break-all font-mono">{product.id}</span>
						</div>
					</div>
					<button type="button" onClick={onClose} className="shrink-0 rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-800 hover:text-white" aria-label="Close visual review" data-testid="visual-review-close">
						✕
					</button>
				</header>

				<div className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden p-4 sm:p-5">
					{loading ? <div className="py-8 text-center text-xs text-slate-500">Loading visual authority…</div> : null}
					{error ? <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[10px] text-red-200" role="alert">{error}</div> : null}
					{readiness ? (
						<div className="min-w-0 space-y-4">
							<div className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-2" data-testid="visual-review-status">
								<div className="min-w-0">
									<div className="text-[9px] font-bold uppercase tracking-widest text-slate-500">Visual status</div>
									<div className="mt-1 break-words text-xs font-bold text-white">{statusLabel(readiness)}</div>
								</div>
								<div className="text-right text-[9px] text-slate-400">
									<div>Exact Commerce</div>
									<div className="mt-1 break-words font-mono text-slate-200">{readiness.exact_commerce_status || "—"}</div>
								</div>
							</div>

							<div className="grid min-w-0 grid-cols-1 gap-3 md:grid-cols-2" data-testid="visual-review-previews">
								<Preview
									label="Original Source"
									src={readiness.original_preview_url || readiness.original_display_url || product.image_url}
									alt={`${product.product_display_name} original source`}
								/>
								<Preview
									label="Prepared Cutout"
									src={candidatePreview}
									alt={`${product.product_display_name} prepared cutout`}
									transparent
								/>
							</div>

							{readiness.blockers?.length ? (
								<div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2" data-testid="visual-review-blockers">
									<div className="text-[9px] font-bold uppercase tracking-widest text-amber-300">Current blockers</div>
									<div className="mt-2 flex min-w-0 flex-wrap gap-1.5">
										{readiness.blockers.map((blocker) => <span key={blocker} className="max-w-full break-all rounded bg-amber-500/10 px-1.5 py-0.5 font-mono text-[9px] text-amber-100">{blocker}</span>)}
									</div>
								</div>
							) : null}

							{cohort === "PENDING_VISUAL_REVIEW" ? (
								<div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3" data-testid="visual-review-approval">
									<div className="text-[10px] font-bold uppercase tracking-widest text-emerald-200">Owner approval confirmation</div>
									<p className="mt-1 text-[10px] leading-relaxed text-slate-400">Approval is candidate-bound and fail-closed. It does not release the product or run a provider operation.</p>
									<div className="mt-3 grid min-w-0 gap-2 sm:grid-cols-2">
										{CHECKS.map(([key, label]) => (
											<label key={key} className="flex min-w-0 items-start gap-2 text-[10px] text-slate-200">
												<input type="checkbox" checked={checks[key]} onChange={(event) => setChecks((current) => ({ ...current, [key]: event.target.checked }))} aria-label={label} className="mt-0.5 accent-emerald-500" />
												<span className="min-w-0 break-words">{label}</span>
											</label>
										))}
									</div>
									<label className="mt-3 block text-[9px] font-bold uppercase tracking-widest text-slate-500">
										Audit note
										<textarea value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} rows={2} className="mt-1 block w-full min-w-0 resize-y rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs font-normal normal-case tracking-normal text-slate-200 outline-none focus:border-emerald-500" />
									</label>
									<div className="mt-3 flex flex-wrap items-center justify-end gap-2">
										<button type="button" onClick={onClose} className="rounded-lg border border-slate-700 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-slate-300 hover:bg-slate-800" data-testid="visual-review-cancel">Cancel</button>
										<button type="button" onClick={() => void approve()} disabled={!canApprove || approving} className="rounded-lg bg-emerald-600 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-white disabled:cursor-not-allowed disabled:opacity-40" data-testid="visual-review-approve">{approving ? "Approving…" : "Approve this visual"}</button>
									</div>
								</div>
							) : (
								<div className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-900/50 p-3">
									<div className="min-w-0 text-[10px] text-slate-400">This row remains governed by the existing Product Visual detail authority.</div>
									{onOpenProduct && (cohort === "SOURCE_REUPLOAD_REQUIRED" || cohort === "BROKEN_APPROVED_VISUAL") ? <button type="button" onClick={() => { onClose(); onOpenProduct(product.id, { tab: "VISUAL" }); }} className="shrink-0 rounded-lg border border-violet-500/40 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-violet-200 hover:bg-violet-500/10" data-testid="visual-review-detail-action">{cohort === "SOURCE_REUPLOAD_REQUIRED" ? "Open Re-upload" : "Open Recovery"}</button> : null}
								</div>
							)}

							<details className="min-w-0 max-w-full rounded-xl border border-slate-800 bg-slate-900/40" data-testid="visual-review-technical-evidence">
								<summary className="cursor-pointer px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-slate-400">Technical evidence</summary>
								<div className="grid min-w-0 gap-2 border-t border-slate-800 px-3 py-3 sm:grid-cols-2">
									<div><div className="text-[8px] uppercase tracking-widest text-slate-600">Candidate SHA</div><EvidenceValue value={readiness.canonical_cutout_sha256} /></div>
									<div><div className="text-[8px] uppercase tracking-widest text-slate-600">Candidate media ID</div><EvidenceValue value={readiness.canonical_cutout_media_id} /></div>
									<div><div className="text-[8px] uppercase tracking-widest text-slate-600">Expected lock/version</div><EvidenceValue value={readiness.visual_lock_updated_at} /></div>
									<div><div className="text-[8px] uppercase tracking-widest text-slate-600">Source SHA</div><EvidenceValue value={readiness.canonical_source_sha256} /></div>
									<div className="sm:col-span-2"><div className="text-[8px] uppercase tracking-widest text-slate-600">Candidate source kind</div><EvidenceValue value={readiness.candidate_source_kind} /></div>
								</div>
							</details>

							<div className="flex flex-wrap items-center justify-between gap-2 text-[9px] text-slate-500">
								<span>Provider operations: <strong className="text-emerald-300">0</strong></span>
								<span>Release mutation: <strong className="text-slate-300">none</strong></span>
							</div>
							{approval ? <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[10px] text-emerald-200" data-testid="visual-review-approval-result">{approval.status} · {approval.approved_count} approved</div> : null}
						</div>
					) : null}
				</div>
			</section>
		</div>
	);
}
