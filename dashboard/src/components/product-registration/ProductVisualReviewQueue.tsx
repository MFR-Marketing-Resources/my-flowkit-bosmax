import { useEffect, useMemo, useState } from "react";
import {
	approveSelectedProductVisuals,
	fetchProductVisualReviewQueue,
	type ProductVisualReviewApprovalResponse,
	type ProductVisualReviewQueueItem,
	type VisualReviewCohort,
} from "../../api/productVisualOnboarding";

type Props = {
	onOpenProduct?: (
		productId: string,
		opts?: { tab?: "EDIT" | "INTELLIGENCE" | "CREATIVE" | "VISUAL" },
	) => void;
	onCohortCountsChange?: (counts: Record<VisualReviewCohort, number>) => void;
};

const COHORTS: Array<{ key: VisualReviewCohort; label: string }> = [
	{ key: "PENDING_VISUAL_REVIEW", label: "Pending Visual Review" },
	{ key: "SOURCE_REUPLOAD_REQUIRED", label: "Source Re-upload Required" },
	{ key: "BROKEN_APPROVED_VISUAL", label: "Broken Approved Visual" },
];
const PAGE_SIZES = [25, 50];

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
		<div className="w-full min-w-0 max-w-full overflow-hidden">
			<div className="mb-1 text-[8px] font-bold uppercase tracking-widest text-slate-500">
				{label}
			</div>
			<div
				className={`flex h-44 w-full max-w-full items-center justify-center overflow-hidden rounded-lg border border-slate-700 sm:h-48 ${
					transparent ? "bg-white" : "bg-slate-950"
				}`}
			>
				{src ? (
					<img
						src={src}
						alt={alt}
						loading="lazy"
						decoding="async"
						className="h-full w-full object-contain"
						onError={(event) => {
							event.currentTarget.style.display = "none";
						}}
					/>
				) : (
					<span className="px-2 text-center text-[9px] font-semibold uppercase tracking-widest text-slate-600">
						Not available
					</span>
				)}
			</div>
		</div>
	);
}

function StatusPill({ value, tone = "muted" }: { value: string; tone?: "ok" | "warn" | "bad" | "muted" }) {
	const classes = {
		ok: "bg-emerald-500/15 text-emerald-300",
		warn: "bg-amber-500/15 text-amber-200",
		bad: "bg-red-500/15 text-red-300",
		muted: "bg-slate-700/40 text-slate-300",
	}[tone];
	return (
		<span className={`inline-flex max-w-full min-w-0 rounded px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-widest break-words ${classes}`}>
			{value.replace(/_/g, " ")}
		</span>
	);
}

function itemTone(item: ProductVisualReviewQueueItem): "ok" | "warn" | "bad" | "muted" {
	if (item.cohort === "PENDING_VISUAL_REVIEW") return "warn";
	if (item.cohort === "BROKEN_APPROVED_VISUAL") return "bad";
	return "muted";
}

export default function ProductVisualReviewQueue({ onOpenProduct, onCohortCountsChange }: Props) {
	const [cohort, setCohort] = useState<VisualReviewCohort>("PENDING_VISUAL_REVIEW");
	const [pageSize, setPageSize] = useState(25);
	const [offset, setOffset] = useState(0);
	const [queue, setQueue] = useState<Awaited<ReturnType<typeof fetchProductVisualReviewQueue>> | null>(null);
	const [selected, setSelected] = useState<Set<string>>(() => new Set());
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [confirmOpen, setConfirmOpen] = useState(false);
	const [reviewNote, setReviewNote] = useState("Owner visual recovery review");
	const [confirmIdentity, setConfirmIdentity] = useState(false);
	const [confirmLabelLogo, setConfirmLabelLogo] = useState(false);
	const [confirmGeometryScale, setConfirmGeometryScale] = useState(false);
	const [confirmProductIsolation, setConfirmProductIsolation] = useState(false);
	const [approval, setApproval] = useState<ProductVisualReviewApprovalResponse | null>(null);

	useEffect(() => {
		const controller = new AbortController();
		setLoading(true);
		setError(null);
		setSelected(new Set());
		setConfirmOpen(false);
		void fetchProductVisualReviewQueue(cohort, pageSize, offset, controller.signal)
			.then((result) => {
				if (!controller.signal.aborted) {
					setQueue(result);
					onCohortCountsChange?.(result.cohort_counts);
				}
			})
			.catch((reason: unknown) => {
				if (!controller.signal.aborted) {
					setQueue(null);
					setError(reason instanceof Error ? reason.message : "Visual review queue failed to load.");
				}
			})
			.finally(() => {
				if (!controller.signal.aborted) setLoading(false);
			});
		return () => controller.abort();
	}, [cohort, offset, pageSize, onCohortCountsChange]);

	const rows = queue?.items ?? [];
	const selectedRows = useMemo(
		() => rows.filter((item) => selected.has(item.product_id)),
		[rows, selected],
	);
	const canSelect = cohort === "PENDING_VISUAL_REVIEW";
	const hasPrevious = offset > 0;
	const hasNext = Boolean(queue?.has_pagination);
	const rangeStart = queue && queue.total_count > 0 ? offset + 1 : 0;
	const rangeEnd = queue ? Math.min(offset + rows.length, queue.total_count) : 0;

	function changeCohort(next: VisualReviewCohort) {
		setCohort(next);
		setOffset(0);
		setApproval(null);
	}

	function changePage(nextOffset: number) {
		setOffset(Math.max(0, nextOffset));
		setSelected(new Set());
		setApproval(null);
	}

	function toggleSelected(productId: string) {
		setSelected((current) => {
			const next = new Set(current);
			if (next.has(productId)) next.delete(productId);
			else next.add(productId);
			return next;
		});
	}

	async function confirmApproval() {
		if (!selectedRows.length) return;
		setLoading(true);
		setError(null);
		try {
			const result = await approveSelectedProductVisuals({
				items: selectedRows.map((item) => ({
					product_id: item.product_id,
					candidate_sha256: item.candidate_sha256 || "",
					candidate_media_id: item.candidate_media_id || "",
					expected_lock_updated_at: item.expected_lock_updated_at || "",
					candidate_source_kind: item.candidate_source_kind === "USER_UPLOAD" ? "USER_UPLOAD" : "AUTO_GENERATED",
				})),
				review_note: reviewNote,
				confirm_identity: confirmIdentity,
				confirm_label_logo: confirmLabelLogo,
				confirm_geometry_scale: confirmGeometryScale,
				confirm_product_isolation: confirmProductIsolation,
			});
			setApproval(result);
			setSelected(new Set());
			setConfirmOpen(false);
			setOffset(0);
			// The approved rows leave PENDING_VISUAL_REVIEW after the next read.
			const refreshed = await fetchProductVisualReviewQueue(cohort, pageSize, 0);
			setQueue(refreshed);
			onCohortCountsChange?.(refreshed.cohort_counts);
		} catch (reason: unknown) {
			setError(reason instanceof Error ? reason.message : "Selected visual approval failed.");
		} finally {
			setLoading(false);
		}
	}

	return (
		<section className="w-full min-w-0 max-w-full overflow-hidden rounded-2xl border border-amber-500/30 bg-slate-950/70 p-3 sm:p-4" data-testid="product-visual-review-queue">
			<div className="flex w-full min-w-0 flex-wrap items-start justify-between gap-3">
				<div className="min-w-0 flex-1">
					<div className="flex min-w-0 flex-wrap items-center gap-2">
						<h3 className="text-sm font-bold text-white">Owner Visual Review Queue</h3>
						<StatusPill value="OWNER GOVERNED" tone="warn" />
						<StatusPill value="PROVIDER SPEND 0" tone="ok" />
					</div>
					<p className="mt-1 max-w-3xl break-words text-[10px] leading-relaxed text-slate-400">
						Review the original source and prepared cutout side by side. Selection is explicit, page-scoped, candidate-bound, and never releases a product.
					</p>
				</div>
				{canSelect && (
					<button
						type="button"
						onClick={() => setConfirmOpen(true)}
						disabled={selectedRows.length === 0 || loading}
						className="max-w-full shrink-0 rounded-lg bg-emerald-600/90 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-white disabled:cursor-not-allowed disabled:opacity-40"
						data-testid="approve-selected-visuals"
					>
						Approve selected ({selectedRows.length})
					</button>
				)}
			</div>

			<div className="mt-4 grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-3" role="tablist" aria-label="Visual review cohorts">
				{COHORTS.map((entry) => {
					const active = cohort === entry.key;
					const count = queue?.cohort_counts?.[entry.key];
					return (
						<button
							key={entry.key}
							type="button"
							role="tab"
							aria-selected={active}
							onClick={() => changeCohort(entry.key)}
							className={`w-full min-w-0 max-w-full rounded-lg border px-3 py-2 text-left text-[9px] font-bold uppercase tracking-widest break-words transition-colors ${active ? "border-amber-400/60 bg-amber-500/15 text-amber-200" : "border-slate-800 bg-slate-900 text-slate-400 hover:text-white"}`}
							data-testid={`visual-review-cohort-${entry.key}`}
						>
							{entry.label} <span className="ml-1 font-mono">({count ?? "—"})</span>
						</button>
					);
				})}
			</div>

			<div className="mt-3 flex w-full min-w-0 flex-wrap items-center justify-between gap-2 text-[9px] text-slate-500" data-testid="visual-review-toolbar">
				<div className="min-w-0 break-words">
					{loading ? "Loading review projection…" : queue ? `Showing ${rangeStart}–${rangeEnd} of ${queue.total_count}` : "Review projection unavailable"}
					{canSelect && selectedRows.length > 0 ? ` · ${selectedRows.length} visible rows selected` : ""}
				</div>
				<label className="flex min-w-0 items-center gap-2 uppercase tracking-widest">
					Rows per page
					<select
						value={pageSize}
						onChange={(event) => {
							setPageSize(Number(event.target.value));
							setOffset(0);
						}}
						className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-slate-200"
						data-testid="visual-review-page-size"
					>
						{PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
					</select>
				</label>
			</div>

			{error && <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-[10px] text-red-300" role="alert">{error}</div>}
			{approval && (
				<div className={`mt-3 rounded-lg border px-3 py-2 text-[10px] ${approval.failed_count ? "border-amber-500/40 bg-amber-500/10 text-amber-200" : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"}`} data-testid="visual-review-approval-result">
					{approval.status === "COMPLETED" ? "Approval completed" : "Partial result — individual failures remain visible"}: {approval.approved_count} approved, {approval.already_approved_count} already approved, {approval.failed_count} failed.
					<div className="mt-2 grid gap-1">
						{approval.results.map((result) => <div key={result.product_id} className="font-mono">{result.product_id} · {result.status}{result.error_code ? ` · ${result.error_code}` : ""}</div>)}
					</div>
				</div>
			)}

			{!loading && queue && rows.length === 0 && (
				<div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60 p-6 text-center text-[10px] uppercase tracking-widest text-slate-500">No products in this review cohort.</div>
			)}

			<div className="mt-4 grid min-w-0 gap-3">
				{rows.map((item) => {
					const selectedRow = selected.has(item.product_id);
					const selectable = canSelect && item.actions.can_approve_selected;
					return (
						<article key={item.product_id} className={`w-full min-w-0 max-w-full overflow-hidden rounded-xl border p-3 ${selectedRow ? "border-emerald-400/60 bg-emerald-500/5" : "border-slate-800 bg-slate-900/50"}`} data-testid={`visual-review-row-${item.product_id}`}>
							<div className="flex w-full min-w-0 flex-wrap items-start justify-between gap-3">
								<div className="flex min-w-0 items-start gap-2">
									{selectable && (
										<input
											type="checkbox"
											checked={selectedRow}
											onChange={() => toggleSelected(item.product_id)}
											aria-label={`Select ${item.product_name}`}
											data-testid={`visual-review-select-${item.product_id}`}
											className="mt-1 h-4 w-4 accent-emerald-500"
										/>
									)}
									<div className="min-w-0 max-w-full">
										<div className="max-w-full truncate text-xs font-bold text-white" title={item.product_name}>{item.product_name}</div>
										<div className="mt-1 break-all font-mono text-[9px] text-slate-500">{item.product_id}</div>
									</div>
								</div>
								<div className="flex min-w-0 max-w-full flex-wrap items-center gap-1.5">
									<StatusPill value={item.candidate_status} tone={itemTone(item)} />
									<StatusPill value={`RELEASE ${item.release_status}`} tone="muted" />
								</div>
							</div>

							<div className="mt-3 grid min-w-0 grid-cols-1 gap-3 xl:grid-cols-2" data-testid={`visual-review-previews-${item.product_id}`}>
								<Preview label={`Original source · ${item.original_source_trust_status || "UNKNOWN"}`} src={item.original_source_url} alt={`${item.product_name} original source`} />
								<Preview label="Prepared cutout candidate" src={item.candidate_preview_url} alt={`${item.product_name} prepared cutout`} transparent />
							</div>

							<div className="mt-3 grid min-w-0 gap-2 text-[9px] text-slate-400 sm:grid-cols-2 xl:grid-cols-4">
								<div className="min-w-0 break-words"><span className="text-slate-600">PROVENANCE</span><br />{item.original_source_trust_status || "UNKNOWN"} · {Object.entries(item.original_source_provenance || {}).map(([key, value]) => <span key={key} className="mr-2 inline-block max-w-full break-words">{key}: {String(value)}</span>)}</div>
								<div className="min-w-0 break-words"><span className="text-slate-600">CANDIDATE STATUS</span><br />{item.review_status} · {item.cutout_status}<br />{item.candidate_source_kind || "UNKNOWN"}</div>
								<div className="min-w-0 break-words"><span className="text-slate-600">CURRENT SYSTEM VISUAL</span><br />{item.current_system_visual.label || item.current_system_visual.status || "Not selected"}<br />{item.readiness_impact.current_exact_commerce_status || "—"}</div>
								<div className="min-w-0 break-words"><span className="text-slate-600">BLOCKER / IMPACT</span><br />{item.blocker_state.join(", ") || "—"}<br />After approval: {item.readiness_impact.after_visual_approval_exact_commerce_status || "—"}</div>
			</div>

							<details className="mt-3 min-w-0 max-w-full rounded-lg border border-slate-800/80 bg-slate-950/50 px-3 py-2" data-testid={`visual-review-technical-${item.product_id}`}>
								<summary className="cursor-pointer select-none text-[9px] font-bold uppercase tracking-widest text-slate-500">Technical evidence</summary>
								<div className="mt-2 grid min-w-0 gap-2 text-[9px] text-slate-500 sm:grid-cols-2">
									<div className="min-w-0 break-words"><span className="text-slate-600">SOURCE PROVENANCE</span><br />{Object.entries(item.original_source_provenance || {}).map(([key, value]) => <span key={key} className="block min-w-0 break-words [overflow-wrap:anywhere]">{key}: {String(value)}</span>)}</div>
									<div className="min-w-0 break-words"><span className="text-slate-600">CANDIDATE MEDIA</span><br />Media ID: <span className="break-all font-mono text-slate-400">{item.candidate_media_id || "—"}</span><br />Candidate SHA: <span className="break-all font-mono text-slate-400">{item.candidate_sha256 || "—"}</span><br />Source SHA: <span className="break-all font-mono text-slate-400">{item.expected_source_sha256 || "—"}</span><br />Cutout SHA: <span className="break-all font-mono text-slate-400">{item.expected_cutout_sha256 || "—"}</span></div>
									<div className="min-w-0 break-words"><span className="text-slate-600">LOCK / HISTORY</span><br />Lock updated: <span className="break-all font-mono text-slate-400">{item.expected_lock_updated_at || "—"}</span><br />Historical evidence: {item.historical_evidence_count}</div>
									<div className="min-w-0 break-words"><span className="text-slate-600">CANONICAL BYTES</span><br />{item.missing_canonical_bytes.length ? item.missing_canonical_bytes.map((value) => <span key={value} className="block break-all font-mono text-amber-300">{value}</span>) : "No missing canonical bytes"}</div>
								</div>
							</details>

							<div className="mt-3 flex w-full min-w-0 flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-2">
								<div className="min-w-0 break-words text-[9px] text-slate-600">Auto-release: NO · Provider operations: {item.provider_operations}</div>
								<button
									type="button"
									onClick={() => onOpenProduct?.(item.product_id, { tab: "VISUAL" })}
									disabled={!onOpenProduct}
									className="max-w-full shrink-0 rounded-lg bg-slate-800 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-300 disabled:cursor-not-allowed disabled:opacity-40"
									data-testid={`visual-review-open-${item.product_id}`}
								>
									{item.cohort === "SOURCE_REUPLOAD_REQUIRED" ? "Upload / Re-authorize Source" : item.cohort === "BROKEN_APPROVED_VISUAL" ? "Open Recovery" : "Open Visual Detail"}
								</button>
							</div>
						</article>
					);
				})}
			</div>

			{(hasPrevious || hasNext) && (
				<div className="mt-4 flex items-center justify-between gap-2 border-t border-slate-800 pt-3">
					<button type="button" onClick={() => changePage(offset - pageSize)} disabled={!hasPrevious || loading} className="rounded-lg bg-slate-800 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-slate-300 disabled:opacity-40">Previous</button>
					<span className="text-[9px] uppercase tracking-widest text-slate-600">Selection resets when page changes</span>
					<button type="button" onClick={() => changePage(offset + pageSize)} disabled={!hasNext || loading} className="rounded-lg bg-slate-800 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-slate-300 disabled:opacity-40">Next</button>
				</div>
			)}

			{confirmOpen && (
				<div className="fixed inset-0 z-50 flex min-w-0 max-w-full items-center justify-center overflow-x-hidden bg-slate-950/80 p-3 sm:p-4" role="dialog" aria-modal="true" aria-labelledby="visual-review-confirm-title" data-testid="visual-review-confirmation">
					<div className="max-h-[90vh] w-full min-w-0 max-w-2xl overflow-x-hidden overflow-y-auto rounded-2xl border border-amber-500/40 bg-slate-900 p-4 shadow-2xl sm:p-5">
						<h4 id="visual-review-confirm-title" className="text-sm font-bold text-white">Approve selected official visuals</h4>
						<p className="mt-2 text-[10px] leading-relaxed text-amber-200">This promotes only the selected candidate bytes to official Product Truth visual authority. It does not release or publish any product.</p>
						<div className="mt-3 rounded-lg border border-slate-800 bg-slate-950/70 p-3 text-[10px] text-slate-300">
							<div className="font-bold uppercase tracking-widest text-slate-500">Exact selected products ({selectedRows.length})</div>
							<ul className="mt-2 min-w-0 space-y-1">{selectedRows.map((item) => <li key={item.product_id} className="min-w-0 break-words"><span className="font-semibold text-white">{item.product_name}</span> <span className="break-all font-mono text-slate-500">({item.product_id})</span></li>)}</ul>
						</div>
						<label className="mt-3 block text-[9px] font-bold uppercase tracking-widest text-slate-500">Batch review note<input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-normal normal-case tracking-normal text-white" /></label>
						<div className="mt-3 grid gap-2 text-[10px] text-slate-300 sm:grid-cols-2">
							<label><input type="checkbox" checked={confirmIdentity} onChange={(event) => setConfirmIdentity(event.target.checked)} className="mr-1 accent-emerald-500" /> Exact product identity</label>
							<label><input type="checkbox" checked={confirmLabelLogo} onChange={(event) => setConfirmLabelLogo(event.target.checked)} className="mr-1 accent-emerald-500" /> Label / logo</label>
							<label><input type="checkbox" checked={confirmGeometryScale} onChange={(event) => setConfirmGeometryScale(event.target.checked)} className="mr-1 accent-emerald-500" /> Geometry / scale</label>
							<label><input type="checkbox" checked={confirmProductIsolation} onChange={(event) => setConfirmProductIsolation(event.target.checked)} className="mr-1 accent-emerald-500" /> Product only / no unrelated objects</label>
						</div>
						<div className="mt-4 flex flex-wrap justify-end gap-2">
							<button type="button" onClick={() => setConfirmOpen(false)} className="rounded-lg bg-slate-800 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-slate-300">Cancel</button>
							<button type="button" onClick={() => void confirmApproval()} disabled={!reviewNote.trim() || !confirmIdentity || !confirmLabelLogo || !confirmGeometryScale || !confirmProductIsolation || loading} className="rounded-lg bg-emerald-600 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">Confirm approve selected</button>
						</div>
					</div>
				</div>
			)}
		</section>
	);
}
