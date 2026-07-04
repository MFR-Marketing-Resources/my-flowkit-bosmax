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

	const approvedCount = copySets.filter(
		(cs) => cs.status === "COPY_APPROVED",
	).length;

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
			<div className="mb-1 flex items-center justify-between">
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
						<div className="mb-3 rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-[11px] text-emerald-200">
							Copy Set bound to final prompt generation.
						</div>
					) : (
						<div className="mb-3 rounded-lg border border-sky-500/30 bg-sky-500/5 px-3 py-2 text-[11px] text-sky-200">
							Select an approved Copy Set below to bind it into the final prompt.
						</div>
					)}

					<div className="space-y-3">
						{copySets.map((cs) => {
							const isSelected = cs.copy_set_id === selectedCopySetId;
							const isApproved = cs.status === "COPY_APPROVED";
							const safety = cs.claim_review?.safety;
							const claimWarning =
								safety && safety.safe === false
									? (safety.violations ?? []).join(", ")
									: null;
							return (
								<div
									key={cs.copy_set_id}
									className={`rounded-xl border px-3 py-3 ${
										isSelected
											? "border-emerald-500/50 bg-emerald-500/5"
											: "border-slate-800 bg-slate-950/60"
									}`}
								>
									<div className="mb-2 flex items-center justify-between gap-2">
										<div className="flex items-center gap-2">
											<StatusBadge status={cs.status} />
											<span className="text-[10px] uppercase tracking-[0.15em] text-slate-500">
												{cs.platform} · {cs.language} · {cs.route_type}
											</span>
										</div>
										<span className="font-mono text-[10px] text-slate-500">
											{cs.source || "—"}
										</span>
									</div>

									<div className="space-y-1 text-[11px] text-slate-300">
										{cs.angle ? (
											<div>
												<span className="text-slate-500">Angle: </span>
												{cs.angle}
											</div>
										) : null}
										{cs.hook ? (
											<div>
												<span className="text-slate-500">Hook: </span>
												{cs.hook}
											</div>
										) : null}
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
									</div>

									{claimWarning ? (
										<div className="mt-2 rounded-lg border border-rose-500/30 bg-rose-500/5 px-2 py-1 text-[10px] text-rose-300">
											Claim review: {claimWarning}
										</div>
									) : null}

									{cs.approved_at ? (
										<div className="mt-2 text-[10px] text-emerald-400/80">
											Approved {cs.approved_at}
											{cs.approved_by ? ` · by ${cs.approved_by}` : ""}
										</div>
									) : null}

									<div className="mt-3 flex flex-wrap items-center gap-2">
										{isApproved ? (
											<button
												type="button"
												onClick={() =>
													onSelect(isSelected ? null : cs.copy_set_id)
												}
												disabled={disabled}
												className={`rounded-lg border px-3 py-1.5 text-[11px] font-semibold transition-colors disabled:opacity-50 ${
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
												className="rounded-lg border border-slate-600/40 bg-slate-700/30 px-3 py-1.5 text-[11px] font-semibold text-slate-100 hover:bg-slate-700/50 disabled:opacity-50 transition-colors"
											>
												{busyId === cs.copy_set_id ? "Approving…" : "Approve Copy Set"}
											</button>
										) : (
											<span className="text-[10px] text-slate-500">
												Rejected — regenerate or edit to reuse.
											</span>
										)}
									</div>
								</div>
							);
						})}
					</div>
				</>
			)}
		</div>
	);
}
