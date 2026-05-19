import { useCallback, useEffect, useState } from "react";
import { getAPI, patchAPI, postAPI } from "../../api/client";
import type {
	BulkApproveResult,
	BulkClaimRisk,
	BulkCreateDraftsResult,
	BulkImageReadiness,
	BulkPromotionStatus,
	BulkQueuePage,
	BulkQueueStats,
	BulkRecomputeSelectedResult,
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
	const [actionMessage, setActionMessage] = useState<string | null>(null);
	const [actionError, setActionError] = useState<string | null>(null);
	const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
	const [recomputeSummary, setRecomputeSummary] =
		useState<BulkRecomputeSelectedResult | null>(null);

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

	return (
		<div className="space-y-5">
			{/* Stats Bar — Sync Queue is always visible; stats badges appear once loaded */}
			<div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
				<div className="flex items-center justify-between mb-3">
					<span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">
						Queue Stats
					</span>
					<button
						type="button"
						onClick={handleSync}
						disabled={syncing}
						className="px-3 py-1 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 text-white text-[10px] font-bold uppercase tracking-widest transition-all"
					>
						{syncing ? "Syncing…" : "Sync Queue"}
					</button>
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
											<div
												className="font-medium text-white truncate max-w-[240px]"
												title={row.raw_product_title}
											>
												{row.raw_product_title}
											</div>
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
