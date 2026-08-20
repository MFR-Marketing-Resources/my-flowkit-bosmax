import { AlertTriangle, ArrowLeft, CheckCircle2, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, HelperText, Section } from "../components/ui";
import {
	batchApproveCopyDrafts,
	fetchCopyReviewQueue,
	type CopyBatchApprovalResultV2,
	type CopyReviewQueueRowV2,
} from "../api/copyRegisterV2";

const INPUT_CLASS =
	"mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200";
const BATCH_APPROVAL_PHRASE = "APPROVE_COPY_DRAFTS_BATCH";

const CHECKLIST = [
	[
		"semantic",
		"readiness_validated",
		"I reviewed every authored stage against Product Truth.",
	],
	[
		"provenance",
		"provenance_validated",
		"Product Truth and evidence lineage match the selected product.",
	],
	[
		"safety",
		"safety_validated",
		"Allowed claims and warnings were reviewed; no unsafe claim was added.",
	],
	[
		"bridge",
		"bridge_validated",
		"Formula order and bridge continuity are coherent.",
	],
	[
		"duration",
		"duration_validated",
		"Word count and target-lane duration readiness were reviewed.",
	],
] as const;

type ChecklistKey = (typeof CHECKLIST)[number][0];
type ReadinessKey = (typeof CHECKLIST)[number][1];
type ReadinessState = Record<ReadinessKey, boolean>;

const EMPTY_READINESS: ReadinessState = {
	readiness_validated: false,
	provenance_validated: false,
	safety_validated: false,
	bridge_validated: false,
	duration_validated: false,
};

function errorMessage(error: unknown): string {
	const message = error instanceof Error ? error.message : "Copy review queue request failed.";
	const jsonStart = message.indexOf("{");
	if (jsonStart < 0) return message;
	try {
		const detail = JSON.parse(message.slice(jsonStart))?.detail;
		if (detail?.error && detail?.detail) return `${detail.error}: ${detail.detail}`;
	} catch {
		// Preserve the transport message when the response is not JSON.
	}
	return message;
}

function claimRiskRow(row: CopyReviewQueueRowV2): boolean {
	const status = (row.claim_safe_copy_status ?? "").toUpperCase();
	const risk = (row.claim_risk_level ?? "").toUpperCase();
	return risk === "HIGH" || status.includes("REVIEW_REQUIRED") || status === "CLAIM_BLOCKED";
}

function rowPreview(row: CopyReviewQueueRowV2): string {
	const stages = row.draft_preview?.stages ?? [];
	if (!stages.length) return "Draft text unavailable; open individual review.";
	return stages.map((stage) => stage.text).join(" ");
}

export default function CopyReviewQueuePage() {
	const [items, setItems] = useState<CopyReviewQueueRowV2[]>([]);
	const [onlyClaimSafe, setOnlyClaimSafe] = useState(false);
	const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
	const [reviewer, setReviewer] = useState("");
	const [rationale, setRationale] = useState("");
	const [readiness, setReadiness] = useState<ReadinessState>(EMPTY_READINESS);
	const [confirmationPhrase, setConfirmationPhrase] = useState("");
	const [confirmOpen, setConfirmOpen] = useState(false);
	const [results, setResults] = useState<CopyBatchApprovalResultV2[]>([]);
	const [loading, setLoading] = useState(true);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [successMessage, setSuccessMessage] = useState("");

	const loadQueue = useCallback(async () => {
		setLoading(true);
		setError("");
		try {
			const response = await fetchCopyReviewQueue({ only_claim_safe: onlyClaimSafe });
			setItems(response.items ?? []);
			setSelectedIds((current) => {
				const available = new Set(
					(response.items ?? [])
						.filter((item) => item.batch_approvable)
						.map((item) => item.blueprint_id),
				);
				return new Set([...current].filter((id) => available.has(id)));
			});
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setLoading(false);
		}
	}, [onlyClaimSafe]);

	useEffect(() => {
		void loadQueue();
	}, [loadQueue]);

	const selectedCount = selectedIds.size;
	const allReadinessChecked = Object.values(readiness).every(Boolean);
	const canSubmit =
		selectedCount > 0 &&
		reviewer.trim().length > 0 &&
		rationale.trim().length > 0 &&
		allReadinessChecked &&
		confirmationPhrase === BATCH_APPROVAL_PHRASE &&
		!busy;

	const selectableCount = useMemo(
		() => items.filter((item) => item.batch_approvable).length,
		[items],
	);

	const toggleSelected = (row: CopyReviewQueueRowV2) => {
		if (!row.batch_approvable) return;
		setSelectedIds((current) => {
			const next = new Set(current);
			if (next.has(row.blueprint_id)) next.delete(row.blueprint_id);
			else next.add(row.blueprint_id);
			return next;
		});
	};

	const selectAllSafe = () => {
		setSelectedIds(
			new Set(items.filter((item) => item.batch_approvable).map((item) => item.blueprint_id)),
		);
	};

	const submitBatch = async () => {
		if (!canSubmit) return;
		setBusy(true);
		setError("");
		try {
			const response = await batchApproveCopyDrafts({
				blueprint_ids: [...selectedIds],
				reviewer: reviewer.trim(),
				rationale: rationale.trim(),
				readiness_proof: readiness,
				confirmation_phrase: confirmationPhrase,
			});
			setResults(response.results ?? []);
			setSelectedIds(new Set());
			setConfirmOpen(false);
			setSuccessMessage(
				`${response.approved_count} draft${response.approved_count === 1 ? "" : "s"} approved to PRODUCTION_VALID.`,
			);
			await loadQueue();
		} catch (reason) {
			setError(errorMessage(reason));
			setConfirmOpen(false);
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="mx-auto max-w-7xl space-y-6 p-4 md:p-8" data-testid="copy-review-queue-page">
			<header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-800 pb-5">
				<div>
					<div className="flex items-center gap-2 text-blue-300">
						<ShieldCheck size={20} />
						<span className="text-[10px] font-bold uppercase tracking-[0.2em]">Advanced</span>
					</div>
					<h1 className="mt-1 text-2xl font-bold text-slate-100">Copy Draft Review Queue</h1>
					<p className="mt-1 max-w-3xl text-xs text-slate-400">
						Review current, claim-safe V2 drafts across products and record one human attestation per selected blueprint.
					</p>
				</div>
				<Link
					to="/creative/copy-authority"
					className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800"
					data-testid="back-to-copy-authority"
				>
					<ArrowLeft size={14} /> Back to Copy Authority
				</Link>
			</header>

			{error ? <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100" data-testid="review-queue-error">{error}</p> : null}
			{successMessage ? <p className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100" data-testid="review-queue-success">{successMessage}</p> : null}

			<Section title="Drafts awaiting review" helper="Claim-risk or stale-truth drafts remain visible for individual review and cannot be selected here.">
				<div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-4">
					<label className="flex items-center gap-2 text-xs text-slate-300">
						<input
							type="checkbox"
							data-testid="queue-only-claim-safe"
							checked={onlyClaimSafe}
							onChange={(event) => setOnlyClaimSafe(event.target.checked)}
						/>
						Show only batch-approvable drafts
					</label>
					<div className="flex items-center gap-3 text-xs text-slate-400">
						<span data-testid="queue-count">{items.length} draft{items.length === 1 ? "" : "s"} · {selectableCount} selectable</span>
						<button type="button" data-testid="queue-select-all" onClick={selectAllSafe} disabled={loading || selectableCount === 0} className="rounded border border-slate-700 px-3 py-1.5 font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-40">Select all safe</button>
						<button type="button" data-testid="queue-refresh" onClick={() => void loadQueue()} disabled={loading || busy} className="rounded border border-slate-700 px-3 py-1.5 font-semibold text-slate-200 hover:bg-slate-800 disabled:opacity-40">Refresh</button>
					</div>
				</div>

				{loading ? <p className="py-8 text-sm text-slate-400">Loading cross-product drafts…</p> : null}
				{!loading && !items.length ? <p className="py-8 text-sm text-slate-400" data-testid="queue-empty">No DRAFT blueprints are waiting for review.</p> : null}
				{!loading && items.length ? (
					<div className="mt-4 overflow-x-auto">
						<table className="w-full min-w-[980px] text-left text-xs" data-testid="review-queue-table">
							<thead className="border-b border-slate-800 text-[10px] uppercase tracking-wider text-slate-500">
								<tr>
									<th className="px-3 py-3">Select</th>
									<th className="px-3 py-3">Product / draft</th>
									<th className="px-3 py-3">Formula</th>
									<th className="px-3 py-3">Claim safety</th>
									<th className="px-3 py-3">Product Truth</th>
									<th className="px-3 py-3">Batch state</th>
								</tr>
							</thead>
							<tbody className="divide-y divide-slate-800/80">
								{items.map((row) => {
									const risky = claimRiskRow(row);
									return (
										<tr key={`${row.blueprint_id}:${row.revision}`} data-testid={`queue-row-${row.blueprint_id}`} className={risky ? "bg-rose-500/5" : ""}>
											<td className="px-3 py-4 align-top">
												<input type="checkbox" data-testid={`queue-select-${row.blueprint_id}`} checked={selectedIds.has(row.blueprint_id)} disabled={!row.batch_approvable || busy} onChange={() => toggleSelected(row)} aria-label={`Select ${row.product_name}`} />
											</td>
											<td className="max-w-[360px] px-3 py-4 align-top">
												<p className="font-semibold text-slate-100">{row.product_name || row.product_id}</p>
												<p className="mt-1 font-mono text-[10px] text-slate-500">{row.blueprint_id} · rev {row.revision}</p>
												<p className="mt-2 text-slate-300">{row.draft_preview?.angle.definition || "Draft angle unavailable"}</p>
												<p className="mt-2 line-clamp-3 text-slate-500">{rowPreview(row)}</p>
												{row.individual_review_path ? <a href={row.individual_review_path} data-testid={`queue-individual-review-${row.blueprint_id}`} className="mt-2 inline-block font-semibold text-blue-300 hover:text-blue-200">Open individual review</a> : null}
											</td>
											<td className="px-3 py-4 align-top font-semibold text-blue-200">{row.formula_id}</td>
											<td className="px-3 py-4 align-top">
												<div className="flex flex-wrap items-center gap-2">
													<Badge tone={risky ? "warn" : "success"}>{row.claim_safe_copy_status || "CLAIM_SAFE"}</Badge>
													<span className={risky ? "font-semibold text-rose-200" : "text-slate-400"}>Risk: {row.claim_risk_level || "—"}</span>
												</div>
												{risky ? <p className="mt-2 flex items-start gap-1 text-[11px] text-rose-200"><AlertTriangle size={13} className="mt-0.5 shrink-0" />Individual review required</p> : null}
											</td>
											<td className="px-3 py-4 align-top">
												<Badge tone={row.truth_current ? "success" : "warn"}>{row.truth_current ? "CURRENT" : "STALE / BLOCKED"}</Badge>
												{row.draft_blocked_reason && !risky ? <p className="mt-2 text-[11px] text-amber-200">{row.draft_blocked_reason}</p> : null}
											</td>
											<td className="px-3 py-4 align-top">
												{row.batch_approvable ? <span className="font-semibold text-emerald-300">Selectable</span> : <span className="font-semibold text-amber-200">Blocked</span>}
												{row.draft_blocked_reason ? <p className="mt-2 max-w-[220px] text-[11px] text-slate-500">{row.draft_blocked_reason}</p> : null}
											</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					</div>
				) : null}
			</Section>

			<Section title="Batch human approval" helper="The same five readiness gates are recorded on every selected blueprint. This action never activates a blueprint or spends provider/Flow credits.">
				<div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
					<div>
						<label className="block text-xs font-semibold text-slate-300" htmlFor="batch-reviewer">Reviewer</label>
						<input id="batch-reviewer" className={INPUT_CLASS} data-testid="batch-reviewer-input" value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="Human reviewer name" />
						<label className="mt-4 block text-xs font-semibold text-slate-300" htmlFor="batch-rationale">Review rationale</label>
						<textarea id="batch-rationale" className={`${INPUT_CLASS} min-h-24`} data-testid="batch-rationale-input" value={rationale} onChange={(event) => setRationale(event.target.value)} placeholder="Why this batch was reviewed and approved" />
						<label className="mt-4 block text-xs font-semibold text-slate-300" htmlFor="batch-phrase">Confirmation phrase</label>
						<input id="batch-phrase" className={INPUT_CLASS} data-testid="batch-confirmation-phrase" value={confirmationPhrase} onChange={(event) => setConfirmationPhrase(event.target.value)} placeholder={BATCH_APPROVAL_PHRASE} />
						<HelperText className="mt-2">Type the exact phrase: <span className="font-mono text-slate-200">{BATCH_APPROVAL_PHRASE}</span></HelperText>
					</div>
					<div>
						<p className="text-xs font-semibold text-slate-300">Readiness checklist</p>
						<div className="mt-2 grid gap-2 text-xs text-slate-300 sm:grid-cols-2">
							{CHECKLIST.map(([key, readinessKey, label]) => (
								<label key={key} className="flex cursor-pointer items-start gap-2 rounded border border-slate-800 p-2" data-testid={`batch-check-row-${key}`}>
									<input type="checkbox" data-testid={`batch-approval-check-${key as ChecklistKey}`} checked={readiness[readinessKey]} onChange={(event) => setReadiness((current) => ({ ...current, [readinessKey]: event.target.checked }))} />
									<span>{label}</span>
								</label>
							))}
						</div>
						<div className="mt-4 flex flex-wrap items-center gap-3">
							<button type="button" data-testid="approve-selected-drafts" disabled={!canSubmit} onClick={() => setConfirmOpen(true)} className="rounded-xl border border-emerald-500/40 bg-emerald-600/20 px-4 py-2 text-xs font-bold uppercase text-emerald-100 disabled:opacity-40">Approve {selectedCount} draft{selectedCount === 1 ? "" : "s"}</button>
							<span className="text-xs text-slate-500">{selectedCount} selected</span>
						</div>
						{!canSubmit ? <HelperText tone="warn" className="mt-3">Approval requires selected safe drafts, reviewer, rationale, all 5 readiness checks, and the exact confirmation phrase.</HelperText> : null}
					</div>
				</div>
			</Section>

			{results.length ? (
				<Section title="Batch results" helper="Each blueprint has its own approval result and audit receipt.">
					<div className="space-y-2" data-testid="batch-results">
						{results.map((result) => (
							<div key={result.blueprint_id} data-testid={`batch-result-${result.blueprint_id}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2 text-xs">
								<span className="font-mono text-slate-300">{result.blueprint_id}</span>
								{result.status === "APPROVED" ? <span className="flex items-center gap-1 font-semibold text-emerald-300"><CheckCircle2 size={14} /> APPROVED · PRODUCTION_VALID</span> : <span className="text-rose-200">FAILED · {result.error_code || "UNKNOWN"}</span>}
							</div>
						))}
					</div>
				</Section>
			) : null}

			{confirmOpen ? (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4" data-testid="batch-confirm-overlay">
					<div className="w-full max-w-lg rounded-2xl border border-emerald-500/40 bg-slate-900 p-6 shadow-2xl">
						<div className="flex items-center gap-2 text-emerald-200"><ShieldCheck size={18} /><span className="text-[11px] font-bold uppercase tracking-[0.18em]">Confirm human batch approval</span></div>
						<h2 className="mt-2 text-lg font-bold text-slate-100">Approve {selectedCount} selected draft{selectedCount === 1 ? "" : "s"}?</h2>
						<p className="mt-3 text-xs leading-5 text-slate-300">This records the reviewer attestation on each blueprint and stops at PRODUCTION_VALID. No activation or provider call is performed.</p>
						<div className="mt-5 flex items-center justify-end gap-3">
							<button type="button" data-testid="batch-confirm-cancel" disabled={busy} onClick={() => setConfirmOpen(false)} className="rounded-lg border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-40">Cancel</button>
							<button type="button" data-testid="batch-confirm" disabled={busy || !canSubmit} onClick={() => void submitBatch()} className="rounded-lg border border-emerald-500/40 bg-emerald-600/30 px-4 py-2 text-xs font-bold uppercase text-emerald-100 hover:bg-emerald-600/50 disabled:opacity-40">{busy ? "Approving…" : "Confirm batch approval"}</button>
						</div>
					</div>
				</div>
			) : null}
		</div>
	);
}
