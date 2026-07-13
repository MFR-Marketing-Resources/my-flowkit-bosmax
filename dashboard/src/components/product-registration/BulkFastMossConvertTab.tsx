import { useCallback, useEffect, useState } from "react";
import { getAPI, patchAPI, postAPI } from "../../api/client";
import type {
	BulkApproveResult,
	BulkClaimRisk,
	BulkCreateDraftsResult,
	BulkDuplicateResolveResult,
	BulkImageReadiness,
	BulkPromotionStatus,
	BulkQueuePage,
	BulkQueueStats,
	BulkRecomputeSelectedResult,
	DuplicateReviewAction,
	FastmossBulkQueueRow,
} from "../../types";

const RISK_BADGE: Record<string, string> = {
	LOW: "bg-emerald-500/20 text-emerald-400",
	MEDIUM: "bg-amber-500/20 text-amber-400",
	HIGH: "bg-red-500/20 text-red-400",
	UNKNOWN: "bg-slate-500/20 text-slate-400",
};

const STATUS_BADGE: Record<string, string> = {
	PENDING_DRAFT: "bg-slate-500/20 text-slate-400",
	DRAFT_GENERATED: "bg-blue-500/20 text-blue-400",
	READY_FOR_APPROVAL: "bg-emerald-500/20 text-emerald-400",
	NEEDS_REVIEW: "bg-amber-500/20 text-amber-400",
	MISSING_REQUIRED_FIELD: "bg-orange-500/20 text-orange-400",
	CLAIM_RISK: "bg-red-500/20 text-red-400",
	IMAGE_MISSING: "bg-yellow-500/20 text-yellow-400",
	DUPLICATE_SUSPECTED: "bg-purple-500/20 text-purple-400",
	DUPLICATE_LINKED: "bg-cyan-500/20 text-cyan-300",
	APPROVED: "bg-teal-500/20 text-teal-400",
	REJECTED: "bg-slate-700/40 text-slate-500",
};

const ALL_STATUSES: BulkPromotionStatus[] = [
	"PENDING_DRAFT",
	"DRAFT_GENERATED",
	"READY_FOR_APPROVAL",
	"NEEDS_REVIEW",
	"MISSING_REQUIRED_FIELD",
	"CLAIM_RISK",
	"IMAGE_MISSING",
	"DUPLICATE_SUSPECTED",
	"DUPLICATE_LINKED",
	"APPROVED",
	"REJECTED",
];

const RECOMPUTE_ELIGIBLE_STATUSES: BulkPromotionStatus[] = [
	"MISSING_REQUIRED_FIELD",
	"PENDING_DRAFT",
];

const getErrorMessage = (error: unknown, fallback: string) => {
	if (error instanceof Error && error.message) {
		return error.message;
	}
	return fallback;
};

interface Props {
	onOpenDraft?: (draftId: string) => void;
}

export default function BulkFastMossConvertTab({ onOpenDraft }: Props) {
	const [stats, setStats] = useState<BulkQueueStats | null>(null);
	const [queue, setQueue] = useState<BulkQueuePage | null>(null);
	const [selected, setSelected] = useState<Set<string>>(new Set());
	const [selectedStatuses, setSelectedStatuses] = useState<
		Record<string, BulkPromotionStatus>
	>({});
	const [loading, setLoading] = useState(false);
	const [syncing, setSyncing] = useState(false);
	const [kalodataImporting, setKalodataImporting] = useState(false);
	const [applyingHub, setApplyingHub] = useState(false);
	const [actionMessage, setActionMessage] = useState<string | null>(null);
	const [actionError, setActionError] = useState<string | null>(null);
	const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
	const [rowLoading, setRowLoading] = useState<Record<string, boolean>>({});
	const [exporting, setExporting] = useState(false);
	const [importing, setImporting] = useState(false);
	const [importResult, setImportResult] = useState<{
		total: number;
		recomputed: number;
		skipped: number;
		failed: number;
	} | null>(null);
	const [recomputeSummary, setRecomputeSummary] =
		useState<BulkRecomputeSelectedResult | null>(null);
	const [duplicateReviewResult, setDuplicateReviewResult] =
		useState<BulkDuplicateResolveResult | null>(null);
	const [detailRow, setDetailRow] = useState<FastmossBulkQueueRow | null>(null);
	const [drawerResult, setDrawerResult] = useState<{
		type: "ok" | "error";
		msg: string;
	} | null>(null);

	// Filters
	const [filterStatus, setFilterStatus] = useState<string>("");
	const [filterRisk, setFilterRisk] = useState<string>("");
	const [filterImage, setFilterImage] = useState<string>("");
	const [filterCategory, setFilterCategory] = useState<string>("");
	const [filterQ, setFilterQ] = useState<string>("");
	const [page, setPage] = useState(1);
	const PAGE_SIZE = 50;

	// Approval modal
	const [showApproveModal, setShowApproveModal] = useState(false);
	const [approvePhrase, setApprovePhrase] = useState("");
	const [showRecomputeModal, setShowRecomputeModal] = useState(false);
	const [recomputePhrase, setRecomputePhrase] = useState("");
	const [reviewingDuplicate, setReviewingDuplicate] =
		useState<FastmossBulkQueueRow | null>(null);
	const [duplicateAction, setDuplicateAction] = useState<DuplicateReviewAction>(
		"LINK_TO_EXISTING_PRODUCT",
	);
	const [duplicateLinkProductId, setDuplicateLinkProductId] = useState("");
	const [duplicatePhrase, setDuplicatePhrase] = useState("");
	const [duplicateNote, setDuplicateNote] = useState("");

	const fetchStats = useCallback(async () => {
		try {
			const s = await getAPI<BulkQueueStats>("/api/fastmoss-bulk/queue/stats");
			setStats(s);
		} catch {
			/* non-fatal */
		}
	}, []);

	const fetchQueue = useCallback(async () => {
		setLoading(true);
		try {
			const params = new URLSearchParams();
			if (filterStatus) params.set("promotion_status", filterStatus);
			if (filterRisk) params.set("claim_risk_level", filterRisk);
			if (filterImage) params.set("image_readiness", filterImage);
			if (filterCategory) params.set("category", filterCategory);
			if (filterQ) params.set("q", filterQ);
			params.set("page", String(page));
			params.set("page_size", String(PAGE_SIZE));
			const data = await getAPI<BulkQueuePage>(
				`/api/fastmoss-bulk/queue?${params}`,
			);
			setQueue(data);
		} catch (e: unknown) {
			setActionError(getErrorMessage(e, "Failed to load queue"));
		} finally {
			setLoading(false);
		}
	}, [filterStatus, filterRisk, filterImage, filterCategory, filterQ, page]);

	useEffect(() => {
		fetchStats();
		fetchQueue();
	}, [fetchStats, fetchQueue]);

	useEffect(() => {
		if (!queue) return;
		setSelectedStatuses((prev) => {
			const next = { ...prev };
			queue.items.forEach((row) => {
				if (selected.has(row.reference_id)) {
					next[row.reference_id] = row.promotion_status;
				}
			});
			return next;
		});
	}, [queue, selected]);

	useEffect(() => {
		if (!detailRow || !queue) return;
		const fresh = queue.items.find(
			(row) => row.reference_id === detailRow.reference_id,
		);
		if (fresh) setDetailRow(fresh);
	}, [detailRow, queue]);

	const clearSelection = () => {
		setSelected(new Set());
		setSelectedStatuses({});
	};

	const handleSync = async () => {
		setSyncing(true);
		setActionMessage(null);
		setActionError(null);
		setRecomputeSummary(null);
		try {
			const r = await postAPI<{
				synced: number;
				skipped: number;
				errors: number;
			}>("/api/fastmoss-bulk/queue/sync", {});
			setActionMessage(
				`Sync complete — synced: ${r.synced}, skipped: ${r.skipped}, errors: ${r.errors}`,
			);
			await fetchStats();
			await fetchQueue();
		} catch (e: unknown) {
			setActionError(getErrorMessage(e, "Sync failed"));
		} finally {
			setSyncing(false);
		}
	};

	// Kalodata/External catalog staged import (additive, zero AI spend):
	// stages the Owner's merged workbook into the reference catalog, then the
	// normal Sync Queue / drafts / approval flow applies unchanged.
	const handleKalodataImport = async () => {
		setKalodataImporting(true);
		setActionMessage(null);
		setActionError(null);
		try {
			const report = await postAPI<{
				staged: number;
				parsed_merged: number;
				hub_matched: number;
				product_id_low_confidence: number;
				skipped_duplicate_in_file: number;
			}>("/api/kalodata/import", {});
			setActionMessage(
				`Kalodata import — parsed: ${report.parsed_merged}, staged: ${report.staged}, ` +
					`HUB matched: ${report.hub_matched}, duplicates: ${report.skipped_duplicate_in_file}, ` +
					`low-confidence IDs: ${report.product_id_low_confidence}. ` +
					`Press Sync Queue to load them.`,
			);
		} catch (e: unknown) {
			setActionError(getErrorMessage(e, "Kalodata import failed"));
		} finally {
			setKalodataImporting(false);
		}
	};

	const handleApplyHubEnrichment = async () => {
		setApplyingHub(true);
		setActionMessage(null);
		setActionError(null);
		try {
			const r = await postAPI<{
				total: number;
				recomputed: number;
				skipped: number;
				failed: number;
			}>("/api/kalodata/apply-hub-enrichment", {});
			setActionMessage(
				`HUB enrichment — total: ${r.total}, recomputed: ${r.recomputed}, ` +
					`skipped: ${r.skipped}, failed: ${r.failed}`,
			);
			await fetchStats();
			await fetchQueue();
		} catch (e: unknown) {
			setActionError(getErrorMessage(e, "HUB enrichment failed"));
		} finally {
			setApplyingHub(false);
		}
	};

	const handleExportMissing = async () => {
		setExporting(true);
		try {
			const response = await fetch("/api/fastmoss-bulk/queue/export-missing-csv");
			if (!response.ok) throw new Error(`Export failed: ${response.status}`);
			const blob = await response.blob();
			const url = URL.createObjectURL(blob);
			const link = document.createElement("a");
			link.href = url;
			link.download = "missing_required_field.csv";
			link.click();
			URL.revokeObjectURL(url);
		} catch (error: unknown) {
			setActionError(getErrorMessage(error, "Export failed"));
		} finally {
			setExporting(false);
		}
	};

	const handleImportCsv = async (file: File) => {
		setImporting(true);
		setImportResult(null);
		setActionMessage(null);
		setActionError(null);
		try {
			const text = await file.text();
			const lines = text.split(/\r?\n/).filter(Boolean);
			if (lines.length < 2) throw new Error("CSV has no data rows");
			const headers = lines[0]
				.split(",")
				.map((header) => header.trim().replace(/^"|"$/g, ""));
			const items = lines.slice(1).map((line) => {
				const values: string[] = [];
				let current = "";
				let inQuotes = false;
				for (let i = 0; i < line.length; i += 1) {
					const char = line[i];
					if (char === '"') {
						inQuotes = !inQuotes;
					} else if (char === "," && !inQuotes) {
						values.push(current);
						current = "";
					} else {
						current += char;
					}
				}
				values.push(current);
				return Object.fromEntries(
					headers.map((header, index) => [
						header,
						(values[index] ?? "").trim(),
					]),
				);
			});
			const result = await postAPI<{
				total: number;
				recomputed: number;
				skipped: number;
				failed: number;
			}>("/api/fastmoss-bulk/queue/import-enrichment", { items });
			setImportResult(result);
			setActionMessage(
				`Import complete — recomputed: ${result.recomputed}, skipped: ${result.skipped}, failed: ${result.failed}`,
			);
			await fetchStats();
			await fetchQueue();
		} catch (error: unknown) {
			setActionError(getErrorMessage(error, "Import failed"));
		} finally {
			setImporting(false);
		}
	};

	const handleGenerateSelected = async () => {
		if (!selected.size) return;
		setActionMessage(null);
		setActionError(null);
		setRecomputeSummary(null);
		setLoading(true);
		try {
			const r = await postAPI<BulkCreateDraftsResult>(
				"/api/fastmoss-bulk/queue/bulk-create-drafts",
				{
					reference_ids: Array.from(selected),
				},
			);
			const newErrors: Record<string, string> = {};
			r.results.forEach((row) => {
				if (row.status === "ERROR")
					newErrors[row.reference_id] = row.error || "UNKNOWN_ERROR";
			});
			setRowErrors((prev) => ({ ...prev, ...newErrors }));
			setActionMessage(`Drafts — created: ${r.success}, failed: ${r.failed}`);
			clearSelection();
			await fetchStats();
			await fetchQueue();
		} catch (e: unknown) {
			setActionError(getErrorMessage(e, "Bulk create failed"));
		} finally {
			setLoading(false);
		}
	};

	const handleApproveConfirm = async () => {
		if (approvePhrase !== "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH") {
			setActionError("Incorrect confirmation phrase");
			return;
		}
		setShowApproveModal(false);
		setActionMessage(null);
		setActionError(null);
		setRecomputeSummary(null);
		setLoading(true);
		try {
			const r = await postAPI<BulkApproveResult>(
				"/api/fastmoss-bulk/queue/bulk-approve-drafts",
				{
					reference_ids: Array.from(selected),
					confirmation_phrase: approvePhrase,
				},
			);
			const newErrors: Record<string, string> = {};
			r.results.forEach((row) => {
				if (row.outcome === "FAILED")
					newErrors[row.reference_id] = row.reason || "COMMIT_FAILED";
			});
			setRowErrors((prev) => ({ ...prev, ...newErrors }));
			setActionMessage(
				`Approved: ${r.approved}, skipped (not ready): ${r.skipped}, failed: ${r.failed}`,
			);
			clearSelection();
			setApprovePhrase("");
			await fetchStats();
			await fetchQueue();
		} catch (e: unknown) {
			setActionError(getErrorMessage(e, "Bulk approve failed"));
		} finally {
			setLoading(false);
		}
	};

	const handleRejectSelected = async () => {
		if (!selected.size) return;
		setActionMessage(null);
		setActionError(null);
		setRecomputeSummary(null);
		setLoading(true);
		try {
			await Promise.all(
				Array.from(selected).map((id) =>
					patchAPI(`/api/fastmoss-bulk/queue/${id}/status`, {
						promotion_status: "REJECTED",
					}),
				),
			);
			setActionMessage(`Rejected ${selected.size} rows`);
			clearSelection();
			await fetchStats();
			await fetchQueue();
		} catch (e: unknown) {
			setActionError(getErrorMessage(e, "Reject failed"));
		} finally {
			setLoading(false);
		}
	};

	const handleRecomputeConfirm = async () => {
		if (recomputePhrase !== "RECOMPUTE_ONLY_NO_APPROVAL") {
			setActionError("Incorrect recompute confirmation phrase");
			return;
		}
		setShowRecomputeModal(false);
		setActionMessage(null);
		setActionError(null);
		setLoading(true);
		try {
			const r = await postAPI<BulkRecomputeSelectedResult>(
				"/api/fastmoss-bulk/queue/recompute-selected",
				{
					reference_ids: Array.from(selected),
				},
			);
			const newErrors: Record<string, string> = {};
			r.results.forEach((row) => {
				if (row.error) newErrors[row.reference_id] = row.error;
			});
			setRowErrors((prev) => ({ ...prev, ...newErrors }));
			setRecomputeSummary(r);
			setActionMessage(
				`Recompute complete — recomputed: ${r.recomputed}, skipped: ${r.skipped}, failed: ${r.failed}`,
			);
			clearSelection();
			setRecomputePhrase("");
			await fetchStats();
			await fetchQueue();
		} catch (e: unknown) {
			setActionError(getErrorMessage(e, "Recompute failed"));
		} finally {
			setLoading(false);
		}
	};

	const toggleRow = (id: string, status: BulkPromotionStatus) => {
		setSelected((prev) => {
			const next = new Set(prev);
			next.has(id) ? next.delete(id) : next.add(id);
			return next;
		});
		setSelectedStatuses((prev) => {
			const next = { ...prev };
			if (selected.has(id)) {
				delete next[id];
			} else {
				next[id] = status;
			}
			return next;
		});
	};

	const toggleAll = () => {
		const rows = queue?.items || [];
		const ids = rows.map((r) => r.reference_id);
		if (ids.every((id) => selected.has(id))) {
			setSelected((prev) => {
				const next = new Set(prev);
				ids.forEach((id) => {
					next.delete(id);
				});
				return next;
			});
			setSelectedStatuses((prev) => {
				const next = { ...prev };
				ids.forEach((id) => {
					delete next[id];
				});
				return next;
			});
		} else {
			setSelected((prev) => {
				const next = new Set(prev);
				ids.forEach((id) => {
					next.add(id);
				});
				return next;
			});
			setSelectedStatuses((prev) => {
				const next = { ...prev };
				rows.forEach((row) => {
					next[row.reference_id] = row.promotion_status;
				});
				return next;
			});
		}
	};

	const clearFilters = () => {
		setFilterStatus("");
		setFilterRisk("");
		setFilterImage("");
		setFilterCategory("");
		setFilterQ("");
		setPage(1);
	};

	const totalPages = queue ? Math.ceil(queue.total / PAGE_SIZE) : 1;
	const allOnPageSelected = (queue?.items || []).every((r) =>
		selected.has(r.reference_id),
	);
	const recomputeEligibleSelectedCount = Array.from(selected).filter((id) =>
		RECOMPUTE_ELIGIBLE_STATUSES.includes(selectedStatuses[id]),
	).length;
	const duplicateConfirmDisabled =
		(duplicateAction === "LINK_TO_EXISTING_PRODUCT" &&
			duplicateLinkProductId.trim().length === 0) ||
		(duplicateAction === "MARK_FALSE_DUPLICATE" &&
			duplicatePhrase !== "CLEAR_DUPLICATE_FOR_REVIEW");

	const handleRecomputeRow = async (referenceId: string) => {
		setRowLoading((prev) => ({ ...prev, [referenceId]: true }));
		setActionMessage(null);
		setActionError(null);
		setDrawerResult(null);
		try {
			const result = await postAPI<BulkRecomputeSelectedResult>(
				"/api/fastmoss-bulk/queue/recompute-selected",
				{ reference_ids: [referenceId] },
			);
			const item = result.results?.[0];
			if (item?.error) {
				const msg = `Recompute failed: ${item.error}`;
				setActionError(msg);
				setDrawerResult({ type: "error", msg });
			} else {
				const previousStatus = item?.previous_status ?? "?";
				const nextStatus = item?.new_status ?? "?";
				const nextError = item?.new_error_message ?? null;
				let msg = `Recomputed: ${previousStatus} → ${nextStatus}`;
				if (nextStatus === previousStatus && nextError) {
					const missing = nextError.startsWith("MISSING:")
						? nextError.slice(8).split(",").join(", ")
						: nextError;
					msg += `. Still blocked — missing: ${missing}`;
				}
				setActionMessage(msg);
				setDrawerResult({
					type: nextStatus === previousStatus ? "error" : "ok",
					msg,
				});
			}
			await fetchStats();
			await fetchQueue();
		} catch (error: unknown) {
			const msg = getErrorMessage(error, "Recompute failed");
			setActionError(msg);
			setDrawerResult({ type: "error", msg });
		} finally {
			setRowLoading((prev) => ({ ...prev, [referenceId]: false }));
		}
	};

	const handleSingleApprove = async (referenceId: string) => {
		const confirmed = window.confirm(
			`Approve this row and promote to Product Truth?\n\n${referenceId.slice(0, 12)}…`,
		);
		if (!confirmed) return;
		setRowLoading((prev) => ({ ...prev, [referenceId]: true }));
		setActionMessage(null);
		setActionError(null);
		setDrawerResult(null);
		try {
			const result = await postAPI<BulkApproveResult>(
				"/api/fastmoss-bulk/queue/bulk-approve-drafts",
				{
					reference_ids: [referenceId],
					confirmation_phrase: "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH",
				},
			);
			const item = result.results?.[0];
			if (item?.outcome === "APPROVED") {
				const msg = "Approved → APPROVED";
				setActionMessage(msg);
				setDrawerResult({ type: "ok", msg });
			} else {
				const msg = `Approve skipped: ${item?.reason ?? "not ready"}`;
				setActionError(msg);
				setDrawerResult({ type: "error", msg });
			}
			await fetchStats();
			await fetchQueue();
		} catch (error: unknown) {
			const msg = getErrorMessage(error, "Approve failed");
			setActionError(msg);
			setDrawerResult({ type: "error", msg });
		} finally {
			setRowLoading((prev) => ({ ...prev, [referenceId]: false }));
		}
	};

	const handleRejectRow = async (row: FastmossBulkQueueRow) => {
		const confirmed = window.confirm(
			`Reject this product?\n\n"${row.raw_product_title.slice(0, 80)}"`,
		);
		if (!confirmed) return;
		setRowLoading((prev) => ({ ...prev, [row.reference_id]: true }));
		setActionMessage(null);
		setActionError(null);
		setDrawerResult(null);
		try {
			await patchAPI(`/api/fastmoss-bulk/queue/${row.reference_id}/status`, {
				promotion_status: "REJECTED",
			});
			const msg = `Rejected ${row.reference_id}`;
			setActionMessage(msg);
			setDrawerResult({ type: "ok", msg });
			await fetchStats();
			await fetchQueue();
			setDetailRow(null);
		} catch (error: unknown) {
			const msg = getErrorMessage(error, "Reject failed");
			setActionError(msg);
			setDrawerResult({ type: "error", msg });
		} finally {
			setRowLoading((prev) => ({ ...prev, [row.reference_id]: false }));
		}
	};

	const openDuplicateReview = (row: FastmossBulkQueueRow) => {
		setReviewingDuplicate(row);
		setDuplicateAction("LINK_TO_EXISTING_PRODUCT");
		setDuplicateLinkProductId(
			row.suspected_existing_product_id || row.linked_product_id || "",
		);
		setDuplicatePhrase("");
		setDuplicateNote(row.duplicate_resolution_note || "");
		setDuplicateReviewResult(null);
	};

	const handleDuplicateResolve = async () => {
		if (!reviewingDuplicate) return;
		setActionMessage(null);
		setActionError(null);
		setLoading(true);
		try {
			const result = await postAPI<BulkDuplicateResolveResult>(
				"/api/fastmoss-bulk/queue/duplicates/resolve",
				{
					reference_id: reviewingDuplicate.reference_id,
					action: duplicateAction,
					linked_product_id:
						duplicateAction === "LINK_TO_EXISTING_PRODUCT"
							? duplicateLinkProductId.trim()
							: null,
					confirmation_phrase:
						duplicateAction === "MARK_FALSE_DUPLICATE" ? duplicatePhrase : null,
					note: duplicateNote.trim() || null,
				},
			);
			setDuplicateReviewResult(result);
			setActionMessage(
				`Duplicate review updated — ${result.reference_id} -> ${result.new_status}`,
			);
			setReviewingDuplicate(null);
			await fetchStats();
			await fetchQueue();
		} catch (e: unknown) {
			setActionError(getErrorMessage(e, "Duplicate review failed"));
		} finally {
			setLoading(false);
		}
	};

	return (
		<div className="space-y-5">
			{/* Stats Bar — Sync Queue is always visible; stats badges appear once loaded */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
				<div className="flex items-center justify-between mb-3">
					<span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
						Queue Stats
					</span>
					<div className="flex items-center gap-2">
						<button
							type="button"
							onClick={handleKalodataImport}
							disabled={kalodataImporting}
							title="Stage the Kalodata/Fastmoss merged workbook into the reference catalog (no AI, no product writes)"
							className="px-3 py-1 rounded-lg bg-cyan-600/20 hover:bg-cyan-600/40 border border-cyan-600/30 disabled:opacity-40 text-cyan-300 text-[10px] font-bold uppercase tracking-widest transition-all"
						>
							{kalodataImporting ? "Importing…" : "Import Kalodata"}
						</button>
						<button
							type="button"
							onClick={handleApplyHubEnrichment}
							disabled={applyingHub}
							title="Apply staged COPYWRITING HUB data to queued Kalodata rows (recompute drafts)"
							className="px-3 py-1 rounded-lg bg-cyan-600/20 hover:bg-cyan-600/40 border border-cyan-600/30 disabled:opacity-40 text-cyan-300 text-[10px] font-bold uppercase tracking-widest transition-all"
						>
							{applyingHub ? "Applying…" : "Apply HUB Enrichment"}
						</button>
						<button
							type="button"
							onClick={handleExportMissing}
							disabled={exporting}
							title="Download CSV of all MISSING_REQUIRED_FIELD rows to enrich offline"
							className="px-3 py-1 rounded-lg bg-amber-600/20 hover:bg-amber-600/40 border border-amber-600/30 disabled:opacity-40 text-amber-300 text-[10px] font-bold uppercase tracking-widest transition-all"
						>
							{exporting ? "Exporting…" : "Export Missing"}
						</button>
						<label
							title="Upload an enriched CSV to recompute missing rows"
							className={`px-3 py-1 rounded-lg border cursor-pointer text-[10px] font-bold uppercase tracking-widest transition-all ${importing ? "bg-slate-800 text-slate-500 border-slate-700 cursor-not-allowed" : "bg-emerald-600/20 hover:bg-emerald-600/40 border-emerald-600/30 text-emerald-300"}`}
						>
							{importing ? "Importing…" : "Import Enriched"}
							<input
								type="file"
								accept=".csv"
								className="hidden"
								disabled={importing}
								onChange={(event) => {
									const file = event.target.files?.[0];
									if (file) {
										void handleImportCsv(file);
										event.target.value = "";
									}
								}}
							/>
						</label>
						<button
							type="button"
							onClick={handleSync}
							disabled={syncing}
							className="px-3 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white text-[10px] font-bold uppercase tracking-widest transition-all"
						>
							{syncing ? "Syncing…" : "Sync Queue"}
						</button>
					</div>
				</div>
				{stats ? (
					<div className="flex flex-wrap gap-2">
						{Object.entries(stats.by_status).map(([status, count]) => (
							<button
								type="button"
								key={status}
								onClick={() => {
									setFilterStatus(filterStatus === status ? "" : status);
									setPage(1);
								}}
								className={`px-2 py-0.5 rounded text-[9px] font-bold cursor-pointer transition-all ${STATUS_BADGE[status] || "bg-slate-700/40 text-slate-400"} ${filterStatus === status ? "ring-1 ring-white/20" : ""}`}
							>
								{status}: {count}
							</button>
						))}
						<span className="px-2 py-0.5 rounded text-[9px] font-bold bg-slate-700/30 text-slate-400">
							Total: {stats.total}
						</span>
					</div>
				) : (
					<p className="text-[10px] text-slate-600 italic">
						Click Sync Queue to load FastMoss reference rows into the conversion
						queue.
					</p>
				)}
			</div>

			{/* Action / Error Messages */}
			{actionMessage && (
				<div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-xs text-emerald-400">
					{actionMessage}
					<button
						type="button"
						onClick={() => setActionMessage(null)}
						className="ml-3 text-slate-500 hover:text-white"
					>
						✕
					</button>
				</div>
			)}
			{actionError && (
				<div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400">
					{actionError}
					<button
						type="button"
						onClick={() => setActionError(null)}
						className="ml-3 text-slate-500 hover:text-white"
					>
						✕
					</button>
				</div>
			)}
			{recomputeSummary && (
				<div className="rounded-2xl border border-indigo-500/30 bg-indigo-500/10 p-4 space-y-3">
					<div className="flex items-center justify-between gap-3">
						<div>
							<h3 className="text-sm font-bold text-indigo-200">
								Recompute Summary
							</h3>
							<p className="text-[11px] text-slate-300">
								Latest rules re-ran without approving products.
							</p>
						</div>
						<button
							type="button"
							onClick={() => setRecomputeSummary(null)}
							className="text-slate-500 hover:text-white text-xs"
						>
							✕
						</button>
					</div>
					<div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px] uppercase tracking-widest">
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							recomputed:{" "}
							<span className="text-white">{recomputeSummary.recomputed}</span>
						</div>
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							ready_for_approval:{" "}
							<span className="text-white">
								{recomputeSummary.ready_for_approval}
							</span>
						</div>
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							missing_required_field:{" "}
							<span className="text-white">
								{recomputeSummary.missing_required_field}
							</span>
						</div>
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							claim_risk:{" "}
							<span className="text-white">{recomputeSummary.claim_risk}</span>
						</div>
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							duplicate_suspected:{" "}
							<span className="text-white">
								{recomputeSummary.duplicate_suspected}
							</span>
						</div>
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							image_missing:{" "}
							<span className="text-white">
								{recomputeSummary.image_missing}
							</span>
						</div>
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							failed:{" "}
							<span className="text-white">{recomputeSummary.failed}</span>
						</div>
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							skipped:{" "}
							<span className="text-white">{recomputeSummary.skipped}</span>
						</div>
					</div>
				</div>
			)}
			{duplicateReviewResult && (
				<div className="rounded-2xl border border-cyan-500/30 bg-cyan-500/10 p-4 space-y-2">
					<div className="flex items-center justify-between gap-3">
						<div>
							<h3 className="text-sm font-bold text-cyan-200">
								Duplicate Review Result
							</h3>
							<p className="text-[11px] text-slate-300">
								{duplicateReviewResult.reference_id} →{" "}
								{duplicateReviewResult.new_status}
							</p>
						</div>
						<button
							type="button"
							onClick={() => setDuplicateReviewResult(null)}
							className="text-slate-500 hover:text-white text-xs"
						>
							✕
						</button>
					</div>
					<div className="grid gap-2 md:grid-cols-3 text-[10px] uppercase tracking-widest">
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							action:{" "}
							<span className="text-white">{duplicateReviewResult.action}</span>
						</div>
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							linked_product_id:{" "}
							<span className="text-white">
								{duplicateReviewResult.linked_product_id || "—"}
							</span>
						</div>
						<div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2 text-slate-300">
							content_generation_allowed:{" "}
							<span className="text-white">
								{duplicateReviewResult.content_generation_allowed
									? "true"
									: "false"}
							</span>
						</div>
					</div>
					<p className="text-[11px] text-slate-300">
						{duplicateReviewResult.message}
					</p>
				</div>
			)}
			{importResult && (
				<div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-xs text-emerald-300 flex gap-4 flex-wrap">
					<span>Import done:</span>
					<span>
						Recomputed <strong>{importResult.recomputed}</strong>
					</span>
					<span>
						Skipped <strong>{importResult.skipped}</strong>
					</span>
					<span>
						Failed <strong>{importResult.failed}</strong>
					</span>
					<button
						type="button"
						onClick={() => setImportResult(null)}
						className="ml-auto text-slate-500 hover:text-white"
					>
						✕
					</button>
				</div>
			)}

			{/* Filters */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
				<div className="flex flex-wrap gap-2 items-end">
					<div>
						<label
							htmlFor="bulk-fastmoss-filter-status"
							className="text-[9px] text-slate-500 uppercase tracking-widest block mb-1"
						>
							Status
						</label>
						<select
							id="bulk-fastmoss-filter-status"
							value={filterStatus}
							onChange={(e) => {
								setFilterStatus(e.target.value);
								setPage(1);
							}}
							className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1"
						>
							<option value="">All</option>
							{ALL_STATUSES.map((s) => (
								<option key={s} value={s}>
									{s}
								</option>
							))}
						</select>
					</div>
					<div>
						<label
							htmlFor="bulk-fastmoss-filter-risk"
							className="text-[9px] text-slate-500 uppercase tracking-widest block mb-1"
						>
							Risk
						</label>
						<select
							id="bulk-fastmoss-filter-risk"
							value={filterRisk}
							onChange={(e) => {
								setFilterRisk(e.target.value);
								setPage(1);
							}}
							className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1"
						>
							<option value="">All</option>
							{(["LOW", "MEDIUM", "HIGH", "UNKNOWN"] as BulkClaimRisk[]).map(
								(r) => (
									<option key={r} value={r}>
										{r}
									</option>
								),
							)}
						</select>
					</div>
					<div>
						<label
							htmlFor="bulk-fastmoss-filter-image"
							className="text-[9px] text-slate-500 uppercase tracking-widest block mb-1"
						>
							Image
						</label>
						<select
							id="bulk-fastmoss-filter-image"
							value={filterImage}
							onChange={(e) => {
								setFilterImage(e.target.value);
								setPage(1);
							}}
							className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1"
						>
							<option value="">All</option>
							{(["IMAGE_PRESENT", "IMAGE_MISSING"] as BulkImageReadiness[]).map(
								(v) => (
									<option key={v} value={v}>
										{v}
									</option>
								),
							)}
						</select>
					</div>
					<div>
						<label
							htmlFor="bulk-fastmoss-filter-category"
							className="text-[9px] text-slate-500 uppercase tracking-widest block mb-1"
						>
							Category
						</label>
						<input
							id="bulk-fastmoss-filter-category"
							type="text"
							value={filterCategory}
							onChange={(e) => {
								setFilterCategory(e.target.value);
								setPage(1);
							}}
							placeholder="category…"
							className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1 w-28"
						/>
					</div>
					<div>
						<label
							htmlFor="bulk-fastmoss-filter-search"
							className="text-[9px] text-slate-500 uppercase tracking-widest block mb-1"
						>
							Search
						</label>
						<input
							id="bulk-fastmoss-filter-search"
							type="text"
							value={filterQ}
							onChange={(e) => {
								setFilterQ(e.target.value);
								setPage(1);
							}}
							placeholder="product title…"
							className="bg-slate-800 border border-slate-700 rounded-lg text-xs text-slate-300 px-2 py-1 w-36"
						/>
					</div>
					<button
						type="button"
						onClick={clearFilters}
						className="px-2 py-1 rounded-lg bg-slate-700/50 text-slate-400 hover:text-white text-[10px] uppercase tracking-widest transition-all"
					>
						Clear
					</button>
				</div>
			</div>

			{/* Bulk Action Bar — always visible; buttons disabled until rows are selected */}
			<div
				className={`rounded-xl border px-4 py-3 flex items-center gap-3 flex-wrap ${selected.size > 0 ? "border-indigo-500/30 bg-indigo-500/10" : "border-slate-700/40 bg-slate-800/30"}`}
			>
				{selected.size > 0 ? (
					<span className="text-xs font-bold text-indigo-300">
						{selected.size} selected
					</span>
				) : (
					<span className="text-[10px] text-slate-500 italic">
						Select FastMoss rows to enable bulk actions.
					</span>
				)}
				<button
					type="button"
					onClick={handleGenerateSelected}
					disabled={loading || selected.size === 0}
					className="px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 disabled:text-slate-600 disabled:cursor-not-allowed text-white text-[10px] font-bold uppercase tracking-widest transition-all"
				>
					Generate Drafts
				</button>
				<button
					type="button"
					onClick={() => {
						setRecomputePhrase("");
						setShowRecomputeModal(true);
					}}
					disabled={
						loading ||
						selected.size === 0 ||
						recomputeEligibleSelectedCount === 0
					}
					className="px-3 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 disabled:cursor-not-allowed text-white text-[10px] font-bold uppercase tracking-widest transition-all"
				>
					Recompute Selected
				</button>
				<button
					type="button"
					onClick={() => {
						setApprovePhrase("");
						setShowApproveModal(true);
					}}
					disabled={loading || selected.size === 0}
					className="px-3 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 disabled:cursor-not-allowed text-white text-[10px] font-bold uppercase tracking-widest transition-all"
				>
					Approve Ready
				</button>
				<button
					type="button"
					onClick={handleRejectSelected}
					disabled={loading || selected.size === 0}
					className="px-3 py-1 rounded-lg bg-red-700/60 hover:bg-red-600/60 disabled:bg-slate-800 disabled:text-slate-600 disabled:cursor-not-allowed text-red-200 text-[10px] font-bold uppercase tracking-widest transition-all"
				>
					Reject
				</button>
				{selected.size > 0 && (
					<button
						type="button"
						onClick={clearSelection}
						className="ml-auto text-[9px] text-slate-500 hover:text-white uppercase tracking-widest"
					>
						Clear selection
					</button>
				)}
			</div>

			{/* Table */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/40 overflow-hidden">
				{loading ? (
					<div className="p-8 text-center text-slate-500 text-xs">Loading…</div>
				) : !queue || queue.items.length === 0 ? (
					<div className="p-8 text-center text-slate-500 text-xs">
						No queue rows found.{" "}
						{!stats?.total
							? 'Click "Sync Queue" to load reference rows.'
							: "Try adjusting filters."}
					</div>
				) : (
					<div className="overflow-x-auto">
						<table className="w-full text-xs text-slate-300">
							<thead>
								<tr className="border-b border-slate-800 bg-slate-900/80">
									<th className="px-3 py-2 w-8">
										<input
											type="checkbox"
											checked={allOnPageSelected}
											onChange={toggleAll}
											className="accent-indigo-500"
										/>
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest w-64">
										Product
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Category
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Risk
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Image
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Sold
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Comm%
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Status
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Draft
									</th>
									<th className="px-3 py-2 text-left font-semibold text-slate-400 text-[10px] uppercase tracking-widest">
										Actions
									</th>
								</tr>
							</thead>
							<tbody>
								{queue.items.map((row) => (
									<tr
										key={row.reference_id}
										className={`border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors ${
											selected.has(row.reference_id) ? "bg-indigo-500/5" : ""
										}`}
									>
										<td className="px-3 py-2">
											<input
												type="checkbox"
												checked={selected.has(row.reference_id)}
												onChange={() =>
													toggleRow(row.reference_id, row.promotion_status)
												}
												className="accent-indigo-500"
											/>
										</td>
										<td className="px-3 py-2 w-64">
											<button
												type="button"
												onClick={() => {
													setDetailRow(row);
													setDrawerResult(null);
												}}
												className="font-medium text-white hover:text-indigo-300 truncate max-w-[240px] text-left underline-offset-2 hover:underline transition-colors block"
												title="Click to review details"
											>
												{row.raw_product_title}
											</button>
											{rowErrors[row.reference_id] && (
												<div className="text-[9px] text-red-400 truncate max-w-[240px] mt-0.5">
													{rowErrors[row.reference_id]}
												</div>
											)}
											{row.error_message && !rowErrors[row.reference_id] && (
												<div className="text-[9px] text-orange-400 truncate max-w-[240px] mt-0.5">
													{row.error_message}
												</div>
											)}
											{row.promotion_status === "DUPLICATE_LINKED" &&
												row.linked_product_id && (
													<div className="mt-1 flex flex-col gap-0.5">
														<span className="inline-flex w-fit px-1.5 py-0.5 rounded text-[9px] font-bold bg-cyan-500/20 text-cyan-300">
															LINKED TO PRODUCT TRUTH
														</span>
														<span className="text-[9px] text-cyan-200 truncate max-w-[240px]">
															{row.linked_product_id} —{" "}
															{row.linked_product_title || "Existing Product"}
														</span>
														<span className="text-[9px] text-slate-400">
															Use linked Product Truth for content generation
														</span>
													</div>
												)}
										</td>
										<td className="px-3 py-2 text-slate-400 truncate max-w-[100px]">
											{row.category || "—"}
										</td>
										<td className="px-3 py-2">
											<span
												className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${RISK_BADGE[row.claim_risk_level] || "bg-slate-600/20 text-slate-400"}`}
											>
												{row.claim_risk_level}
											</span>
										</td>
										<td className="px-3 py-2">
											{row.image_readiness === "IMAGE_PRESENT" ? (
												row.image_url ? (
													<img
														src={row.image_url}
														alt=""
														className="w-8 h-8 rounded object-cover border border-slate-700"
														onError={(e) => {
															(e.target as HTMLImageElement).style.display =
																"none";
														}}
													/>
												) : (
													<span className="text-[9px] text-emerald-400 font-bold">
														✓
													</span>
												)
											) : (
												<span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-yellow-500/20 text-yellow-400">
													MISSING
												</span>
											)}
										</td>
										<td className="px-3 py-2 text-slate-400">
											{row.sold_count ?? "—"}
										</td>
										<td className="px-3 py-2 text-slate-400">
											{row.commission_rate ?? "—"}
										</td>
										<td className="px-3 py-2">
											<span
												className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${STATUS_BADGE[row.promotion_status] || "bg-slate-600/20 text-slate-400"}`}
											>
												{row.promotion_status.replace(/_/g, " ")}
											</span>
										</td>
										<td className="px-3 py-2">
											{row.draft_id ? (
												onOpenDraft ? (
													<button
														type="button"
														onClick={() => {
															if (row.draft_id) {
																onOpenDraft(row.draft_id);
															}
														}}
														className="text-[9px] font-bold text-indigo-400 hover:text-indigo-200 underline underline-offset-2 transition-colors"
													>
														{row.draft_id.slice(0, 14)}…
													</button>
												) : (
													<span className="text-[9px] text-slate-500 font-mono">
														{row.draft_id.slice(0, 12)}…
													</span>
												)
											) : (
												<span className="text-[9px] text-slate-600">—</span>
											)}
										</td>
										<td className="px-3 py-2">
											{rowLoading[row.reference_id] ? (
												<span className="text-[9px] text-slate-400 animate-pulse">
													…
												</span>
											) : row.promotion_status === "DUPLICATE_SUSPECTED" ? (
												<button
													type="button"
													onClick={() => openDuplicateReview(row)}
													className="px-2 py-1 rounded-lg bg-purple-600/20 hover:bg-purple-600/30 text-purple-200 text-[9px] font-bold uppercase tracking-widest transition-all"
												>
													Review Duplicate
												</button>
											) : row.promotion_status === "MISSING_REQUIRED_FIELD" ? (
												<button
													type="button"
													onClick={() => handleRecomputeRow(row.reference_id)}
													className="px-2 py-1 rounded-lg bg-indigo-600/20 hover:bg-indigo-600/40 text-indigo-300 text-[9px] font-bold uppercase tracking-widest transition-all"
												>
													↺ Recompute
												</button>
											) : row.promotion_status === "READY_FOR_APPROVAL" ? (
												<button
													type="button"
													onClick={() => handleSingleApprove(row.reference_id)}
													className="px-2 py-1 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/40 text-emerald-300 text-[9px] font-bold uppercase tracking-widest transition-all"
												>
													Approve ✓
												</button>
											) : row.promotion_status === "PENDING_DRAFT" ? (
												<button
													type="button"
													onClick={() => handleRecomputeRow(row.reference_id)}
													className="px-2 py-1 rounded-lg bg-slate-600/20 hover:bg-slate-600/40 text-slate-300 text-[9px] font-bold uppercase tracking-widest transition-all"
												>
													↺ Generate
												</button>
											) : row.promotion_status === "DUPLICATE_LINKED" ? (
												<span className="text-[9px] text-cyan-300 font-bold uppercase tracking-widest">
													Linked
												</span>
											) : (
												<span className="text-[9px] text-slate-600">—</span>
											)}
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>
				)}
			</div>

			{/* Pagination */}
			{queue && queue.total > PAGE_SIZE && (
				<div className="flex items-center justify-between px-1">
					<span className="text-[10px] text-slate-500">
						{queue.total} rows — page {page} of {totalPages}
					</span>
					<div className="flex gap-2">
						<button
							type="button"
							onClick={() => setPage((p) => Math.max(1, p - 1))}
							disabled={page <= 1}
							className="px-2 py-1 rounded-lg bg-slate-800 text-slate-400 hover:text-white disabled:opacity-40 text-[10px] uppercase tracking-widest"
						>
							‹ Prev
						</button>
						<button
							type="button"
							onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
							disabled={page >= totalPages}
							className="px-2 py-1 rounded-lg bg-slate-800 text-slate-400 hover:text-white disabled:opacity-40 text-[10px] uppercase tracking-widest"
						>
							Next ›
						</button>
					</div>
				</div>
			)}

			{detailRow && (
				<div className="fixed inset-0 z-50 flex justify-end">
					<div
						className="absolute inset-0 bg-black/60 backdrop-blur-sm"
						onClick={() => setDetailRow(null)}
					/>
					<div className="relative z-10 w-full max-w-xl h-full bg-[#0f1117] border-l border-slate-700/60 shadow-2xl flex flex-col overflow-hidden">
						<div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-slate-700/60 bg-slate-900/60">
							<div className="flex-1 min-w-0">
								<p className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-1">
									Product Detail
								</p>
								<h2 className="text-sm font-bold text-white leading-tight line-clamp-2">
									{detailRow.raw_product_title}
								</h2>
								<p className="text-[9px] text-slate-500 mt-1 font-mono break-all">
									{detailRow.reference_id}
								</p>
							</div>
							<button
								type="button"
								onClick={() => setDetailRow(null)}
								className="flex-shrink-0 text-slate-400 hover:text-white text-lg leading-none mt-0.5"
							>
								✕
							</button>
						</div>

						<div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
							<div className="flex flex-wrap gap-2">
								<span
									className={`px-2 py-1 rounded text-[10px] font-bold ${STATUS_BADGE[detailRow.promotion_status] || "bg-slate-600/20 text-slate-400"}`}
								>
									{detailRow.promotion_status.replace(/_/g, " ")}
								</span>
								<span
									className={`px-2 py-1 rounded text-[10px] font-bold ${RISK_BADGE[detailRow.claim_risk_level] || "bg-slate-600/20 text-slate-400"}`}
								>
									RISK: {detailRow.claim_risk_level}
								</span>
								{detailRow.image_readiness === "IMAGE_MISSING" && (
									<span className="px-2 py-1 rounded text-[10px] font-bold bg-yellow-500/20 text-yellow-400">
										IMAGE MISSING
									</span>
								)}
							</div>

							{detailRow.image_url && (
								<div>
									<p className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-2">
										Image
									</p>
									<img
										src={detailRow.image_url}
										alt=""
										className="w-24 h-24 rounded-lg object-cover border border-slate-700"
									/>
								</div>
							)}

							<div>
								<p className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-2">
									Product Info
								</p>
								<div className="grid grid-cols-2 gap-x-4 gap-y-2 text-[11px]">
									<div>
										<span className="text-slate-500">Category</span>
										<p className="text-white font-medium mt-0.5">
											{detailRow.category || "—"}
										</p>
									</div>
									<div>
										<span className="text-slate-500">Sold</span>
										<p className="text-white font-medium mt-0.5">
											{detailRow.sold_count?.toLocaleString() ?? "—"}
										</p>
									</div>
									<div>
										<span className="text-slate-500">Commission</span>
										<p className="text-white font-medium mt-0.5">
											{detailRow.commission_rate ?? "—"}
										</p>
									</div>
									<div>
										<span className="text-slate-500">Mapping Confidence</span>
										<p className="text-white font-medium mt-0.5">
											{detailRow.mapping_confidence != null
												? `${Math.round(detailRow.mapping_confidence * 100)}%`
												: "—"}
										</p>
									</div>
									<div>
										<span className="text-slate-500">Copy Route</span>
										<p className="text-white font-medium mt-0.5">
											{detailRow.copy_route || "—"}
										</p>
									</div>
									<div>
										<span className="text-slate-500">Draft ID</span>
										<p className="text-slate-400 font-mono text-[9px] mt-0.5 break-all">
											{detailRow.draft_id || "—"}
										</p>
									</div>
								</div>
							</div>

							{(detailRow.source_url || detailRow.tiktok_product_url) && (
								<div>
									<p className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-2">
										Source Links
									</p>
									<div className="space-y-1">
										{detailRow.source_url && (
											<a
												href={detailRow.source_url}
												target="_blank"
												rel="noreferrer"
												className="block text-[10px] text-indigo-400 hover:text-indigo-300 truncate underline-offset-2 hover:underline"
											>
												{detailRow.source_url}
											</a>
										)}
										{detailRow.tiktok_product_url && (
											<a
												href={detailRow.tiktok_product_url}
												target="_blank"
												rel="noreferrer"
												className="block text-[10px] text-pink-400 hover:text-pink-300 truncate underline-offset-2 hover:underline"
											>
												TikTok: {detailRow.tiktok_product_url}
											</a>
										)}
									</div>
								</div>
							)}

							{detailRow.claim_risk_level !== "LOW" &&
								detailRow.error_message && (
									<div>
										<p className="text-[9px] font-bold uppercase tracking-widest text-orange-500 mb-2">
											Claim Risk Detail
										</p>
										<div className="bg-orange-950/30 border border-orange-700/30 rounded-lg px-3 py-2">
											<p className="text-[10px] text-orange-300 break-words whitespace-pre-wrap">
												{detailRow.error_message}
											</p>
										</div>
									</div>
								)}

							{detailRow.error_message && detailRow.claim_risk_level === "LOW" && (
								<div>
									<p className="text-[9px] font-bold uppercase tracking-widest text-red-500 mb-2">
										Error / Missing Fields
									</p>
									<div className="bg-red-950/30 border border-red-700/30 rounded-lg px-3 py-2">
										<p className="text-[10px] text-red-300 break-words whitespace-pre-wrap">
											{detailRow.error_message}
										</p>
									</div>
								</div>
							)}

							{(detailRow.promotion_status === "DUPLICATE_SUSPECTED" ||
								detailRow.promotion_status === "DUPLICATE_LINKED") && (
								<div>
									<p className="text-[9px] font-bold uppercase tracking-widest text-purple-400 mb-2">
										Duplicate Match
									</p>
									<div className="bg-purple-950/30 border border-purple-700/30 rounded-lg px-3 py-2 space-y-1">
										{detailRow.suspected_existing_product_title && (
											<p className="text-[10px] text-purple-200">
												<span className="text-slate-500">Matches: </span>
												{detailRow.suspected_existing_product_title}
											</p>
										)}
										{detailRow.duplicate_match_reason && (
											<p className="text-[10px] text-purple-300 break-words">
												{detailRow.duplicate_match_reason}
											</p>
										)}
										{detailRow.linked_product_id && (
											<p className="text-[9px] text-cyan-300 font-mono break-all">
												Linked → {detailRow.linked_product_id}
											</p>
										)}
									</div>
								</div>
							)}

							{detailRow.committed_product_id && (
								<div>
									<p className="text-[9px] font-bold uppercase tracking-widest text-emerald-500 mb-2">
										Committed to Product Truth
									</p>
									<p className="text-[10px] text-emerald-300 font-mono break-all">
										{detailRow.committed_product_id}
									</p>
								</div>
							)}

							<div>
								<p className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-2">
									Timestamps
								</p>
								<div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[10px]">
									<div>
										<span className="text-slate-500">Created</span>
										<p className="text-slate-300 mt-0.5">
											{new Date(detailRow.created_at).toLocaleString()}
										</p>
									</div>
									<div>
										<span className="text-slate-500">Updated</span>
										<p className="text-slate-300 mt-0.5">
											{new Date(detailRow.updated_at).toLocaleString()}
										</p>
									</div>
								</div>
							</div>
						</div>

						<div className="flex-shrink-0 border-t border-slate-700/60 px-5 py-4 bg-slate-900/60 space-y-3">
							{drawerResult && (
								<div
									className={`rounded-lg px-3 py-2 text-[10px] font-medium leading-relaxed ${drawerResult.type === "ok" ? "bg-emerald-900/40 border border-emerald-700/40 text-emerald-300" : "bg-red-900/40 border border-red-700/40 text-red-300"}`}
								>
									{drawerResult.msg}
								</div>
							)}
							{rowErrors[detailRow.reference_id] && (
								<p className="text-[10px] text-red-400">
									{rowErrors[detailRow.reference_id]}
								</p>
							)}

							{detailRow.draft_id && onOpenDraft && (
								<button
									type="button"
									onClick={() => {
										onOpenDraft(detailRow.draft_id!);
										setDetailRow(null);
									}}
									className="w-full px-3 py-2 rounded-xl bg-indigo-600/20 hover:bg-indigo-600/40 border border-indigo-500/30 text-indigo-300 text-[10px] font-bold uppercase tracking-widest transition-all"
								>
									Open Draft Editor
								</button>
							)}

							<div className="flex flex-wrap gap-2">
								{detailRow.promotion_status === "MISSING_REQUIRED_FIELD" && (
									<button
										type="button"
										disabled={rowLoading[detailRow.reference_id]}
										onClick={() => handleRecomputeRow(detailRow.reference_id)}
										className="flex-1 px-3 py-2 rounded-xl bg-indigo-600/20 hover:bg-indigo-600/40 border border-indigo-500/30 text-indigo-300 text-[10px] font-bold uppercase tracking-widest disabled:opacity-40 transition-all"
									>
										{rowLoading[detailRow.reference_id] ? "…" : "Recompute"}
									</button>
								)}
								{detailRow.promotion_status === "PENDING_DRAFT" && (
									<button
										type="button"
										disabled={rowLoading[detailRow.reference_id]}
										onClick={() => handleRecomputeRow(detailRow.reference_id)}
										className="flex-1 px-3 py-2 rounded-xl bg-slate-600/20 hover:bg-slate-600/40 border border-slate-500/30 text-slate-300 text-[10px] font-bold uppercase tracking-widest disabled:opacity-40 transition-all"
									>
										{rowLoading[detailRow.reference_id]
											? "…"
											: "Generate Draft"}
									</button>
								)}
								{detailRow.promotion_status === "READY_FOR_APPROVAL" && (
									<button
										type="button"
										disabled={rowLoading[detailRow.reference_id]}
										onClick={() => handleSingleApprove(detailRow.reference_id)}
										className="flex-1 px-3 py-2 rounded-xl bg-emerald-600/20 hover:bg-emerald-600/40 border border-emerald-500/30 text-emerald-300 text-[10px] font-bold uppercase tracking-widest disabled:opacity-40 transition-all"
									>
										{rowLoading[detailRow.reference_id] ? "…" : "Approve"}
									</button>
								)}
								{detailRow.promotion_status === "DUPLICATE_SUSPECTED" && (
									<button
										type="button"
										onClick={() => {
											openDuplicateReview(detailRow);
											setDetailRow(null);
										}}
										className="flex-1 px-3 py-2 rounded-xl bg-purple-600/20 hover:bg-purple-600/40 border border-purple-500/30 text-purple-300 text-[10px] font-bold uppercase tracking-widest transition-all"
									>
										Review Duplicate
									</button>
								)}
								{!["APPROVED", "REJECTED", "DUPLICATE_LINKED"].includes(
									detailRow.promotion_status,
								) && (
									<button
										type="button"
										disabled={rowLoading[detailRow.reference_id]}
										onClick={() => handleRejectRow(detailRow)}
										className="px-3 py-2 rounded-xl bg-red-600/20 hover:bg-red-600/40 border border-red-500/30 text-red-400 text-[10px] font-bold uppercase tracking-widest disabled:opacity-40 transition-all"
									>
										Reject
									</button>
								)}
							</div>
						</div>
					</div>
				</div>
			)}

			{/* Duplicate Review Modal */}
			{reviewingDuplicate && (
				<div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
					<div className="rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl w-full max-w-5xl space-y-5">
						<div className="flex items-start justify-between gap-4">
							<div>
								<h3 className="text-lg font-bold text-white">
									Review Duplicate
								</h3>
								<p className="text-xs text-slate-400 mt-1">
									DUPLICATE_SUSPECTED rows cannot create new Product Truth
									automatically. Resolve the blocker or link to existing
									canonical truth.
								</p>
							</div>
							<button
								type="button"
								onClick={() => setReviewingDuplicate(null)}
								className="text-slate-500 hover:text-white text-xs"
							>
								✕
							</button>
						</div>

						<div className="grid gap-4 lg:grid-cols-2">
							<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-2">
								<h4 className="text-sm font-bold text-white">FastMoss Row</h4>
								<div className="text-xs text-slate-300 break-words">
									<strong className="text-white">Reference:</strong>{" "}
									{reviewingDuplicate.reference_id}
								</div>
								<div className="text-xs text-slate-300 break-words">
									<strong className="text-white">Title:</strong>{" "}
									{reviewingDuplicate.raw_product_title}
								</div>
								<div className="text-xs text-slate-300">
									<strong className="text-white">Category:</strong>{" "}
									{reviewingDuplicate.category || "—"}
								</div>
								<div className="text-xs text-slate-300 break-all">
									<strong className="text-white">Source URL:</strong>{" "}
									{reviewingDuplicate.source_url || "—"}
								</div>
								<div className="text-xs text-slate-300 break-all">
									<strong className="text-white">TikTok URL:</strong>{" "}
									{reviewingDuplicate.tiktok_product_url || "—"}
								</div>
								<div className="text-xs text-slate-300 break-all">
									<strong className="text-white">Image URL:</strong>{" "}
									{reviewingDuplicate.image_url || "—"}
								</div>
							</div>

							<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-2">
								<h4 className="text-sm font-bold text-white">
									Existing Product Candidate
								</h4>
								<div className="text-xs text-slate-300 break-words">
									<strong className="text-white">Product ID:</strong>{" "}
									{reviewingDuplicate.suspected_existing_product_id || "—"}
								</div>
								<div className="text-xs text-slate-300 break-words">
									<strong className="text-white">Title:</strong>{" "}
									{reviewingDuplicate.suspected_existing_product_title || "—"}
								</div>
								<div className="text-xs text-slate-300">
									<strong className="text-white">Source:</strong>{" "}
									{reviewingDuplicate.suspected_existing_product_source || "—"}
								</div>
								<div className="text-xs text-slate-300">
									<strong className="text-white">Mapping Source:</strong>{" "}
									{reviewingDuplicate.suspected_existing_product_mapping_source ||
										"—"}
								</div>
								<div className="text-xs text-slate-300">
									<strong className="text-white">Match Reason:</strong>{" "}
									{reviewingDuplicate.duplicate_match_reason || "—"}
								</div>
							</div>
						</div>

						<div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 space-y-4">
							<div className="flex flex-wrap gap-2">
								{(
									[
										"LINK_TO_EXISTING_PRODUCT",
										"MARK_FALSE_DUPLICATE",
										"KEEP_BLOCKED",
										"REJECT_REFERENCE",
									] as DuplicateReviewAction[]
								).map((action) => (
									<button
										key={action}
										type="button"
										onClick={() => setDuplicateAction(action)}
										className={`px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all ${
											duplicateAction === action
												? "bg-indigo-600 text-white"
												: "bg-slate-800 text-slate-400 hover:text-white"
										}`}
									>
										{action}
									</button>
								))}
							</div>

							{duplicateAction === "LINK_TO_EXISTING_PRODUCT" && (
								<div className="space-y-2">
									<label
										htmlFor="bulk-fastmoss-linked-product-id"
										className="text-[10px] text-slate-400 uppercase tracking-widest block"
									>
										Linked Product ID
									</label>
									<input
										id="bulk-fastmoss-linked-product-id"
										type="text"
										value={duplicateLinkProductId}
										onChange={(e) => setDuplicateLinkProductId(e.target.value)}
										placeholder="existing product id…"
										className="w-full bg-slate-800 border border-slate-700 focus:border-indigo-500 rounded-lg text-xs text-white px-3 py-2 outline-none"
									/>
								</div>
							)}

							{duplicateAction === "MARK_FALSE_DUPLICATE" && (
								<div className="space-y-2">
									<label
										htmlFor="bulk-fastmoss-clear-duplicate-phrase"
										className="text-[10px] text-slate-400 uppercase tracking-widest block"
									>
										Type the confirmation phrase exactly
									</label>
									<div className="text-[10px] font-mono text-indigo-300 bg-slate-800 rounded px-2 py-1">
										CLEAR_DUPLICATE_FOR_REVIEW
									</div>
									<input
										id="bulk-fastmoss-clear-duplicate-phrase"
										type="text"
										value={duplicatePhrase}
										onChange={(e) => setDuplicatePhrase(e.target.value)}
										placeholder="Type phrase here…"
										className="w-full bg-slate-800 border border-slate-700 focus:border-indigo-500 rounded-lg text-xs text-white px-3 py-2 outline-none"
									/>
								</div>
							)}

							<div className="space-y-2">
								<label
									htmlFor="bulk-fastmoss-duplicate-note"
									className="text-[10px] text-slate-400 uppercase tracking-widest block"
								>
									Review Note
								</label>
								<textarea
									id="bulk-fastmoss-duplicate-note"
									value={duplicateNote}
									onChange={(e) => setDuplicateNote(e.target.value)}
									rows={3}
									placeholder="optional operator note…"
									className="w-full bg-slate-800 border border-slate-700 focus:border-indigo-500 rounded-lg text-xs text-white px-3 py-2 outline-none"
								/>
							</div>
						</div>

						<div className="flex gap-3 justify-end">
							<button
								type="button"
								onClick={() => setReviewingDuplicate(null)}
								className="px-4 py-2 rounded-xl bg-slate-800 text-slate-400 hover:text-white text-xs font-bold uppercase tracking-widest transition-all"
							>
								Cancel
							</button>
							<button
								type="button"
								onClick={handleDuplicateResolve}
								disabled={duplicateConfirmDisabled}
								className="px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-bold uppercase tracking-widest transition-all"
							>
								Confirm Duplicate Resolution
							</button>
						</div>
					</div>
				</div>
			)}

			{/* Recompute Modal */}
			{showRecomputeModal && (
				<div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
					<div className="rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl w-full max-w-md space-y-5">
						<div>
							<h3 className="text-lg font-bold text-white">
								Recompute Selected Rows
							</h3>
							<p className="text-xs text-slate-400 mt-1">
								This will re-run smart mapping and classification using the
								latest rules. It will not approve products.
							</p>
						</div>

						<div className="rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-xs text-indigo-200">
							Eligible rows in this selection:{" "}
							<strong className="text-white">
								{recomputeEligibleSelectedCount}
							</strong>
							. CLAIM_RISK, DUPLICATE_SUSPECTED, APPROVED, and REJECTED rows are
							skipped.
						</div>

						<div>
							<label
								htmlFor="bulk-fastmoss-recompute-phrase"
								className="text-[10px] text-slate-400 uppercase tracking-widest block mb-2"
							>
								Type the confirmation phrase exactly:
							</label>
							<div className="text-[10px] font-mono text-indigo-300 bg-slate-800 rounded px-2 py-1 mb-2">
								RECOMPUTE_ONLY_NO_APPROVAL
							</div>
							<input
								id="bulk-fastmoss-recompute-phrase"
								type="text"
								value={recomputePhrase}
								onChange={(e) => setRecomputePhrase(e.target.value)}
								placeholder="Type phrase here…"
								className="w-full bg-slate-800 border border-slate-700 focus:border-indigo-500 rounded-lg text-xs text-white px-3 py-2 outline-none"
							/>
							{recomputePhrase &&
								recomputePhrase !== "RECOMPUTE_ONLY_NO_APPROVAL" && (
									<p className="text-[9px] text-red-400 mt-1">
										Phrase does not match
									</p>
								)}
						</div>

						<div className="flex gap-3 justify-end">
							<button
								type="button"
								onClick={() => {
									setShowRecomputeModal(false);
									setRecomputePhrase("");
								}}
								className="px-4 py-2 rounded-xl bg-slate-800 text-slate-400 hover:text-white text-xs font-bold uppercase tracking-widest transition-all"
							>
								Cancel
							</button>
							<button
								type="button"
								onClick={handleRecomputeConfirm}
								disabled={recomputePhrase !== "RECOMPUTE_ONLY_NO_APPROVAL"}
								className="px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-bold uppercase tracking-widest transition-all"
							>
								Confirm Recompute
							</button>
						</div>
					</div>
				</div>
			)}

			{/* Approve Modal */}
			{showApproveModal && (
				<div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
					<div className="rounded-2xl border border-slate-700 bg-slate-900 p-6 shadow-2xl w-full max-w-md space-y-5">
						<div>
							<h3 className="text-lg font-bold text-white">
								Confirm Bulk Approval
							</h3>
							<p className="text-xs text-slate-400 mt-1">
								This will commit all{" "}
								<strong className="text-white">READY_FOR_APPROVAL</strong> rows
								from your selection into canonical product truth. Non-ready rows
								will be skipped automatically.
							</p>
						</div>

						<div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
							<strong>Governance:</strong> Only LOW claim risk, image-present,
							complete rows will be committed. MEDIUM, HIGH, IMAGE_MISSING rows
							are automatically skipped.
						</div>

						<div>
							<label
								htmlFor="bulk-fastmoss-approve-phrase"
								className="text-[10px] text-slate-400 uppercase tracking-widest block mb-2"
							>
								Type the confirmation phrase exactly:
							</label>
							<div className="text-[10px] font-mono text-indigo-300 bg-slate-800 rounded px-2 py-1 mb-2">
								PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH
							</div>
							<input
								id="bulk-fastmoss-approve-phrase"
								type="text"
								value={approvePhrase}
								onChange={(e) => setApprovePhrase(e.target.value)}
								placeholder="Type phrase here…"
								className="w-full bg-slate-800 border border-slate-700 focus:border-indigo-500 rounded-lg text-xs text-white px-3 py-2 outline-none"
							/>
							{approvePhrase &&
								approvePhrase !== "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH" && (
									<p className="text-[9px] text-red-400 mt-1">
										Phrase does not match
									</p>
								)}
						</div>

						<div className="flex gap-3 justify-end">
							<button
								type="button"
								onClick={() => {
									setShowApproveModal(false);
									setApprovePhrase("");
								}}
								className="px-4 py-2 rounded-xl bg-slate-800 text-slate-400 hover:text-white text-xs font-bold uppercase tracking-widest transition-all"
							>
								Cancel
							</button>
							<button
								type="button"
								onClick={handleApproveConfirm}
								disabled={approvePhrase !== "PROMOTE_FASTMOSS_TO_PRODUCT_TRUTH"}
								className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-xs font-bold uppercase tracking-widest transition-all"
							>
								Confirm Promote
							</button>
						</div>
					</div>
				</div>
			)}
		</div>
	);
}
