import { useCallback, useEffect, useState } from "react";
import {
	approveCopySet,
	generateAICopyCandidate,
	generateCopySet,
	listCopySetsForProduct,
} from "../../api/copySets";
import type { CopySet, CopySetStatus } from "../../types";

// Copy Selection & Compiler Binding Foundation V1 — operator surface to review,
// approve, and SELECT an approved Copy Set that binds into the deterministic
// final 9-section prompt compiler. This UI is backed by real /api/copy-sets
// endpoints; the selected copy_set_id is carried into the preview/final prompt
// request payload by the parent OperatorPage.

const STATUS_META: Record<
	CopySetStatus,
	{ label: string; className: string }
> = {
	DRAFT_COPY: {
		label: "DRAFT",
		className: "border-slate-500/40 bg-slate-500/10 text-slate-300",
	},
	COPY_REVIEW_REQUIRED: {
		label: "REVIEW REQUIRED",
		className: "border-amber-500/40 bg-amber-500/10 text-amber-200",
	},
	COPY_APPROVED: {
		label: "APPROVED",
		className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200",
	},
	COPY_REJECTED: {
		label: "REJECTED",
		className: "border-rose-500/40 bg-rose-500/10 text-rose-300",
	},
};

function StatusBadge({ status }: { status: CopySetStatus }) {
	const meta = STATUS_META[status] ?? STATUS_META.DRAFT_COPY;
	return (
		<span
			className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.15em] ${meta.className}`}
		>
			{meta.label}
		</span>
	);
}

export interface CopySelectionPanelProps {
	productId: string | null;
	productName?: string | null;
	selectedCopySetId: string | null;
	onSelect: (copySetId: string | null) => void;
	disabled?: boolean;
}

const PAGE_SIZE = 10;

export default function CopySelectionPanel({
	productId,
	productName,
	selectedCopySetId,
	onSelect,
	disabled = false,
}: CopySelectionPanelProps) {
	const [copySets, setCopySets] = useState<CopySet[]>([]);
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [busyId, setBusyId] = useState<string | null>(null);
	const [isGenerating, setIsGenerating] = useState(false);
	// AI Copy Assist V1 — generates candidate Copy Sets (review-required).
	const [isAiAssisting, setIsAiAssisting] = useState(false);
	const [aiNotes, setAiNotes] = useState("");
	const [aiNotice, setAiNotice] = useState<string | null>(null);

	// Angle filter & Pagination state
	const [selectedAngle, setSelectedAngle] = useState<string>("ALL");
	const [currentPage, setCurrentPage] = useState<number>(1);
	const [expandedIds, setExpandedIds] = useState<Record<string, boolean>>({});

	const load = useCallback(async () => {
		if (!productId) {
			setCopySets([]);
			return;
		}
		setIsLoading(true);
		setError(null);
		try {
			const response = await listCopySetsForProduct(productId);
			setCopySets(response.items ?? []);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Failed to load Copy Sets.");
		} finally {
			setIsLoading(false);
		}
	}, [productId]);

	useEffect(() => {
		void load();
	}, [load]);

	// Reset page & filter when product changes
	useEffect(() => {
		setSelectedAngle("ALL");
		setCurrentPage(1);
		setExpandedIds({});
	}, [productId]);

	// Fail-closed: if the currently selected Copy Set is gone or no longer
	// approved, clear the selection so an invalid id never reaches the compiler.
	useEffect(() => {
		if (!selectedCopySetId) return;
		const current = copySets.find(
			(cs) => cs.copy_set_id === selectedCopySetId,
		);
		if (!isLoading && (!current || current.status !== "COPY_APPROVED")) {
			onSelect(null);
		}
	}, [copySets, selectedCopySetId, isLoading, onSelect]);

	const handleGenerate = async () => {
		if (!productId) return;
		setIsGenerating(true);
		setError(null);
		try {
			await generateCopySet({ product_id: productId });
			await load();
		} catch (e) {
			setError(e instanceof Error ? e.message : "Failed to generate Copy Set.");
		} finally {
			setIsGenerating(false);
		}
	};

	const handleAiAssist = async () => {
		if (!productId) return;
		setIsAiAssisting(true);
		setError(null);
		setAiNotice(null);
		try {
			const res = await generateAICopyCandidate({
				product_id: productId,
				...(aiNotes.trim() ? { operator_notes: aiNotes.trim() } : {}),
			});
			await load();
			const created = res.candidates.filter((c) => c.created).length;
			const reused = res.candidates.length - created;
			setAiNotice(
				`AI-assisted draft — review required. ${created} new, ${reused} deduped. Not approved until you approve it.`,
			);
			setAiNotes("");
		} catch (e) {
			// Fail-closed provider states surface here (e.g.
			// AI_COPY_ASSIST_PROVIDER_NOT_CONFIGURED).
			setError(
				e instanceof Error ? e.message : "AI Copy Assist failed.",
			);
		} finally {
			setIsAiAssisting(false);
		}
	};

	const handleApprove = async (copySetId: string) => {
		setBusyId(copySetId);
		setError(null);
		try {
			await approveCopySet(copySetId, { approved_by: "operator" });
			await load();
		} catch (e) {
			setError(
				e instanceof Error
					? e.message
					: "Approval failed (copy may be unsafe or incomplete).",
			);
		} finally {
			setBusyId(null);
		}
	};

	const toggleExpand = (id: string) => {
		setExpandedIds((prev) => ({ ...prev, [id]: !prev[id] }));
	};

	const approvedCount = copySets.filter(
		(cs) => cs.status === "COPY_APPROVED",
	).length;

	// Extract unique strategy angles for filtering
	const uniqueAngles = Array.from(
		new Set(copySets.map((cs) => cs.angle).filter((a): a is string => Boolean(a?.trim()))),
	).sort();

	const filteredCopySets =
		selectedAngle === "ALL"
			? copySets
			: copySets.filter((cs) => cs.angle === selectedAngle);

	const totalPages = Math.max(1, Math.ceil(filteredCopySets.length / PAGE_SIZE));
	const safePage = Math.min(Math.max(1, currentPage), totalPages);

	const paginatedCopySets = filteredCopySets.slice(
		(safePage - 1) * PAGE_SIZE,
		safePage * PAGE_SIZE,
	);

	const selectedCopySet = selectedCopySetId
		? copySets.find((cs) => cs.copy_set_id === selectedCopySetId)
		: null;

	const isSelectedOnCurrentPage = selectedCopySetId
		? paginatedCopySets.some((cs) => cs.copy_set_id === selectedCopySetId)
		: false;

	if (!productId) {
		return (
			<div className="mb-6 rounded-2xl border border-slate-700/40 bg-slate-900/40 p-4">
				<div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
					Copy Selection
				</div>
				<div className="text-[11px] text-slate-400">
					Select a product to review and approve its Copy Sets.
				</div>
			</div>
		);
	}

	return (
		<div className="mb-6 rounded-2xl border border-fuchsia-500/20 bg-slate-900/40 p-4">
			<div className="mb-1 flex flex-wrap items-center justify-between gap-2">
				<div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-500">
					Copy Selection — {productName ?? productId}
				</div>
				<div className="flex items-center gap-2">
					<button
						type="button"
						onClick={() => void handleAiAssist()}
						disabled={disabled || isAiAssisting}
						title="Generate an AI-assisted draft candidate (review required — never auto-approved)"
						className="rounded-lg border border-violet-500/40 bg-violet-500/15 px-3 py-1.5 text-[11px] font-semibold text-violet-100 hover:bg-violet-500/25 disabled:opacity-50 transition-colors"
					>
						{isAiAssisting ? "AI Drafting…" : "AI Assist Draft Copy Set"}
					</button>
					<button
						type="button"
						onClick={() => void handleGenerate()}
						disabled={disabled || isGenerating}
						className="rounded-lg border border-fuchsia-500/40 bg-fuchsia-500/15 px-3 py-1.5 text-[11px] font-semibold text-fuchsia-100 hover:bg-fuchsia-500/25 disabled:opacity-50 transition-colors"
					>
						{isGenerating ? "Generating…" : "Generate Copy Set"}
					</button>
				</div>
			</div>

			{/* AI Copy Assist V1 — optional brief note; output is a review-required
			    candidate, never auto-approved and never bound until approved. */}
			<div className="mb-3 flex items-center gap-2">
				<input
					type="text"
					value={aiNotes}
					onChange={(e) => setAiNotes(e.target.value)}
					disabled={disabled || isAiAssisting}
					placeholder="Optional AI brief — desired angle / hook direction / notes"
					className="flex-1 rounded-lg border border-violet-500/30 bg-slate-950/60 px-3 py-1.5 text-[11px] text-slate-200 placeholder:text-slate-500 focus:border-violet-500/60 focus:outline-none disabled:opacity-50"
				/>
			</div>
			{aiNotice ? (
				<div className="mb-3 rounded-lg border border-violet-500/30 bg-violet-500/5 px-3 py-2 text-[11px] text-violet-200">
					{aiNotice}
				</div>
			) : null}

			{/* Deterministic-compiler note (mission H5) */}
			<div className="mb-3 rounded-lg border border-slate-700/40 bg-slate-950/50 px-3 py-2 text-[10px] leading-relaxed text-slate-400">
				Final 9-section prompt uses the deterministic BOSMAX compiler. AI copy
				assist is not used in this step — only the fields of an approved Copy
				Set are bound as copy intelligence.
			</div>

			{error ? (
				<div className="mb-3 rounded-lg border border-rose-500/30 bg-rose-500/5 px-3 py-2 text-[11px] text-rose-300">
					{error}
				</div>
			) : null}

			{/* Operator UX states (mission H) */}
			{isLoading ? (
				<div className="text-[11px] text-slate-400">Loading Copy Sets…</div>
			) : copySets.length === 0 ? (
				<div className="rounded-lg border border-slate-700/40 bg-slate-950/50 px-3 py-3 text-[11px] text-slate-400">
					No Copy Sets exist for this product yet. Copywriting is not controlled
					— press{" "}
					<span className="font-semibold text-fuchsia-200">
						Generate Copy Set
					</span>{" "}
					to create the first draft.
				</div>
			) : (
				<>
					{approvedCount === 0 ? (
						<div className="mb-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
							Copy Sets exist but none are approved. Review and approve a Copy
							Set before production-quality final prompt generation.
						</div>
					) : selectedCopySetId ? (
						<div className="mb-3 flex items-center justify-between rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-200">
							<span>
								Copy Set bound to final prompt generation:{" "}
								<strong className="font-mono text-emerald-100">
									{selectedCopySet?.hook ? `"${selectedCopySet.hook.slice(0, 45)}…"` : selectedCopySetId}
								</strong>
							</span>
							{!isSelectedOnCurrentPage ? (
								<button
									type="button"
									onClick={() => {
										setSelectedAngle("ALL");
										const idx = copySets.findIndex((cs) => cs.copy_set_id === selectedCopySetId);
										if (idx >= 0) {
											setCurrentPage(Math.floor(idx / PAGE_SIZE) + 1);
										}
									}}
									className="text-[10px] font-semibold text-emerald-300 underline hover:text-emerald-100"
								>
									Jump to selected
								</button>
							) : null}
						</div>
					) : (
						<div className="mb-3 rounded-lg border border-sky-500/30 bg-sky-500/5 px-3 py-2 text-[11px] text-sky-200">
							Select an approved Copy Set below to bind it into the final prompt.
						</div>
					)}

					{/* Angle Narrowing & Pagination Toolbar */}
					<div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950/80 px-3 py-2 text-[11px]">
						<div className="flex items-center gap-2">
							<span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
								Angle:
							</span>
							<select
								data-testid="copy-angle-filter"
								value={selectedAngle}
								onChange={(e) => {
									setSelectedAngle(e.target.value);
									setCurrentPage(1);
								}}
								className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-200 focus:border-fuchsia-500/60 focus:outline-none"
							>
								<option value="ALL">All Angles ({copySets.length})</option>
								{uniqueAngles.map((angle) => {
									const count = copySets.filter((cs) => cs.angle === angle).length;
									return (
										<option key={angle} value={angle}>
											{angle} ({count})
										</option>
									);
								})}
							</select>
						</div>

						<div className="flex items-center gap-3 text-slate-400">
							<span>
								Showing {filteredCopySets.length === 0 ? 0 : (safePage - 1) * PAGE_SIZE + 1}–
								{Math.min(safePage * PAGE_SIZE, filteredCopySets.length)} of {filteredCopySets.length}
							</span>
							{totalPages > 1 ? (
								<div className="flex items-center gap-1">
									<button
										type="button"
										onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
										disabled={safePage <= 1}
										className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] text-slate-300 hover:bg-slate-800 disabled:opacity-40"
									>
										Prev
									</button>
									<span className="px-1 text-[10px]">
										{safePage} / {totalPages}
									</span>
									<button
										type="button"
										onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
										disabled={safePage >= totalPages}
										className="rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] text-slate-300 hover:bg-slate-800 disabled:opacity-40"
									>
										Next
									</button>
								</div>
							) : null}
						</div>
					</div>

					<div className="space-y-2">
						{paginatedCopySets.map((cs) => {
							const isSelected = cs.copy_set_id === selectedCopySetId;
							const isApproved = cs.status === "COPY_APPROVED";
							const safety = cs.claim_review?.safety;
							const claimWarning =
								safety && safety.safe === false
									? (safety.violations ?? []).join(", ")
									: null;
							const isExpanded = Boolean(expandedIds[cs.copy_set_id] || isSelected);

							return (
								<div
									key={cs.copy_set_id}
									// RPA Round A: row keyed by the immutable copy_set_id, exposing
									// status + approval metadata + selected marker so a UI-click
									// operator can VERIFY it selected an approved set (read-only —
									// the RPA must never approve a Copy Set; see G0 amendment M7).
									data-testid="copy-set-row"
									data-copy-set-id={cs.copy_set_id}
									data-status={cs.status}
									data-approved={isApproved ? "true" : "false"}
									data-approved-by={cs.approved_by ?? ""}
									data-selected={isSelected ? "true" : "false"}
									className={`rounded-xl border px-3 py-2.5 transition-colors ${
										isSelected
											? "border-emerald-500/50 bg-emerald-500/5"
											: "border-slate-800 bg-slate-950/60"
									}`}
								>
									{/* Compact Header Row */}
									<div className="flex flex-wrap items-center justify-between gap-2">
										<div className="flex flex-wrap items-center gap-2">
											<StatusBadge status={cs.status} />
											{cs.angle ? (
												<span className="rounded bg-slate-800 px-2 py-0.5 text-[10px] font-medium text-slate-300">
													{cs.angle}
												</span>
											) : null}
											<span className="text-[10px] uppercase tracking-[0.15em] text-slate-500">
												{cs.platform} · {cs.language} · {cs.route_type}
											</span>
										</div>

										<div className="flex items-center gap-2">
											<button
												type="button"
												data-testid="toggle-copy-details"
												onClick={() => toggleExpand(cs.copy_set_id)}
												className="rounded border border-slate-700/60 bg-slate-900/60 px-2 py-1 text-[10px] text-slate-400 hover:text-slate-200 transition-colors"
											>
												{isExpanded ? "Hide details ▲" : "Details ▼"}
											</button>

											{isApproved ? (
												<button
													type="button"
													onClick={() =>
														onSelect(isSelected ? null : cs.copy_set_id)
													}
													disabled={disabled}
													className={`rounded-lg border px-3 py-1 text-[11px] font-semibold transition-colors disabled:opacity-50 ${
														isSelected
															? "border-emerald-500/50 bg-emerald-500/20 text-emerald-100 hover:bg-emerald-500/30"
															: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20"
													}`}
												>
													{isSelected ? "✓ Selected — Deselect" : "Select for Final Prompt"}
												</button>
											) : cs.status !== "COPY_REJECTED" ? (
												<button
													type="button"
													onClick={() => void handleApprove(cs.copy_set_id)}
													disabled={disabled || busyId === cs.copy_set_id}
													className="rounded-lg border border-slate-600/40 bg-slate-700/30 px-3 py-1 text-[11px] font-semibold text-slate-100 hover:bg-slate-700/50 disabled:opacity-50 transition-colors"
												>
													{busyId === cs.copy_set_id ? "Approving…" : "Approve Copy Set"}
												</button>
											) : (
												<span className="text-[10px] text-slate-500">
													Rejected — regenerate to reuse.
												</span>
											)}
										</div>
									</div>

									{/* Compact Hook Preview */}
									<div className="mt-1.5 text-[11px] font-medium text-slate-200">
										<span className="text-slate-500">Hook: </span>
										{cs.hook || "—"}
									</div>

									{/* Expandable Details Section */}
									{isExpanded ? (
										<div className="mt-2.5 space-y-1.5 border-t border-slate-800/80 pt-2 text-[11px] text-slate-300">
											{cs.subhook ? (
												<div>
													<span className="text-slate-500">Subhook: </span>
													{cs.subhook}
												</div>
											) : null}
											{cs.usp_set?.length ? (
												<div>
													<span className="text-slate-500">USP: </span>
													{cs.usp_set.join(" · ")}
												</div>
											) : null}
											{cs.cta ? (
												<div>
													<span className="text-slate-500">CTA: </span>
													{cs.cta}
												</div>
											) : null}

											{claimWarning ? (
												<div className="mt-2 rounded-lg border border-rose-500/30 bg-rose-500/5 px-2 py-1 text-[10px] text-rose-300">
													Claim review: {claimWarning}
												</div>
											) : null}

											{cs.approved_at ? (
												<div className="mt-1 text-[10px] text-emerald-400/80">
													Approved {cs.approved_at}
													{cs.approved_by ? ` · by ${cs.approved_by}` : ""}
												</div>
											) : null}
										</div>
									) : null}
								</div>
							);
						})}
					</div>
				</>
			)}
		</div>
	);
}

