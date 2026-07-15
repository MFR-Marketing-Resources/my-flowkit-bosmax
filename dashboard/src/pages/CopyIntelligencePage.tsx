import { useEffect, useState } from "react";
import {
	approveCopyIntelligenceSeed,
	listCopyIntelligenceSeedLedger,
	promoteApprovedCopyIntelligenceSeed,
	rejectCopyIntelligenceSeed,
	runUploadedCopyIntelligenceDryRun,
	type CopyIntelligencePromoteResult,
	type CopyIntelligenceSeedLedgerResponse,
	type CopyIntelligenceSeedLedgerRow,
	uploadCopyIntelligenceWorkbook,
	type CopyIntelligenceDryRunReport,
	type CopyIntelligenceWorkbookUploadReport,
} from "../api/copyIntelligence";
import { Badge, HelperText, Section } from "../components/ui";

const APPROVE_PHRASE = "APPROVE COPY INTELLIGENCE";
const APPROVE_MEDIUM_PHRASE = "APPROVE MEDIUM CONFIDENCE COPY INTELLIGENCE";
const REJECT_PHRASE = "REJECT COPY INTELLIGENCE";
const MEDIUM_WARNING =
	"Warning: this row was matched by normalized product name, not a verified TikTok Product ID. Confirm product identity carefully before approval.";

function SeedReviewModal({
	row,
	onClose,
	onReviewed,
}: {
	row: CopyIntelligenceSeedLedgerRow;
	onClose: () => void;
	onReviewed: () => void;
}) {
	const [reviewer, setReviewer] = useState("");
	const [note, setNote] = useState("");
	const [phrase, setPhrase] = useState("");
	const [submitting, setSubmitting] = useState(false);
	const [error, setError] = useState("");
	const isMedium = row.confidence === "MEDIUM";
	const approvePhrase = isMedium ? APPROVE_MEDIUM_PHRASE : APPROVE_PHRASE;

	const submit = async (action: "approve" | "reject") => {
		setSubmitting(true);
		setError("");
		try {
			const input = { reviewed_by: reviewer, review_note: note, confirmation_phrase: phrase };
			if (action === "approve") {
				await approveCopyIntelligenceSeed(row.seed_id, input);
			} else {
				await rejectCopyIntelligenceSeed(row.seed_id, input);
			}
			onReviewed();
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : "Review gagal.");
		} finally {
			setSubmitting(false);
		}
	};

	const field = (label: string, value: string | number | null | undefined) => (
		<div>
			<div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">{label}</div>
			<div className="text-sm text-slate-200">{value || "—"}</div>
		</div>
	);

	return (
		<div
			className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
			role="dialog"
			aria-modal="true"
			aria-label="Review copy intelligence seed"
			data-testid="copy-intelligence-review-modal"
		>
			<div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-slate-700 bg-slate-950 p-6 shadow-2xl">
				<div className="flex items-start justify-between gap-4">
					<h3 className="text-lg font-bold text-slate-100">Review seed · {row.confidence}</h3>
					<button type="button" onClick={onClose} className="text-slate-400 hover:text-slate-200" aria-label="Close review">✕</button>
				</div>

				<div className="mt-4 grid gap-3 sm:grid-cols-2">
					{field("Product / source", row.source_product_name)}
					{field("Target avatar", row.target_avatar)}
					{field("Pain point", row.pain_point)}
					{field("Emotion trigger", row.emotion_trigger)}
					{field("Dream outcome", row.dream_outcome)}
					{field("Ingredients / features", row.key_ingredients_features)}
					{field("Hook script", row.hook_script)}
					{field("CTA script", row.cta_script)}
					{field("Confidence", row.confidence)}
					{field("Match method", row.match_method)}
					{field("Workbook / sheet", `${row.source_workbook} · ${row.source_sheet}`)}
					{field("Source row", row.provenance.source_row || row.source_row)}
				</div>

				{isMedium && (
					<p className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs font-medium text-amber-100" role="alert" data-testid="medium-confidence-warning">
						{MEDIUM_WARNING}
					</p>
				)}

				<div className="mt-4 space-y-3">
					<label className="block text-xs font-semibold text-slate-300">Reviewer identity
						<input aria-label="Reviewer identity" value={reviewer} onChange={(e) => setReviewer(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" placeholder="Your name or id" />
					</label>
					<label className="block text-xs font-semibold text-slate-300">Review note (required)
						<textarea aria-label="Review note" value={note} onChange={(e) => setNote(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" rows={2} placeholder="Why is this decision correct?" />
					</label>
					<label className="block text-xs font-semibold text-slate-300">Confirmation phrase
						<input aria-label="Confirmation phrase" value={phrase} onChange={(e) => setPhrase(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" placeholder={approvePhrase} />
					</label>
					<p className="text-[11px] text-slate-500">
						Approve: type <span className="font-mono text-slate-300">{approvePhrase}</span> · Reject: type <span className="font-mono text-slate-300">{REJECT_PHRASE}</span>
					</p>
				</div>

				{error && <p className="mt-3 text-xs font-medium text-red-300" role="alert">Review error: {error}</p>}

				<div className="mt-5 flex flex-wrap justify-end gap-2">
					<button type="button" onClick={onClose} className="rounded-lg border border-slate-700 px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-300 hover:bg-slate-800">Cancel</button>
					<button type="button" data-testid="reject-seed" disabled={submitting} onClick={() => void submit("reject")} className="rounded-lg border border-red-400/40 bg-red-500/15 px-4 py-2 text-xs font-bold uppercase tracking-wide text-red-100 hover:bg-red-500/25 disabled:opacity-50">Reject</button>
					<button type="button" data-testid="approve-seed" disabled={submitting} onClick={() => void submit("approve")} className="rounded-lg border border-emerald-400/40 bg-emerald-500/15 px-4 py-2 text-xs font-bold uppercase tracking-wide text-emerald-100 hover:bg-emerald-500/25 disabled:opacity-50">Approve</button>
				</div>
			</div>
		</div>
	);
}

function CountCard({ label, value, tone }: { label: string; value: number; tone: "success" | "info" | "warn" | "danger" }) {
	return (
		<div className="rounded-xl border border-slate-800 bg-slate-950/50 p-4">
			<div className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">{label}</div>
			<div className="mt-2 flex items-baseline gap-2">
				<span className="text-2xl font-bold text-slate-100">{value}</span>
				<Badge tone={tone}>{tone === "warn" || tone === "danger" ? "Review" : "Review-only"}</Badge>
			</div>
		</div>
	);
}

export default function CopyIntelligencePage() {
	const [workbook, setWorkbook] = useState<File | null>(null);
	const [uploadedSource, setUploadedSource] = useState<CopyIntelligenceWorkbookUploadReport | null>(null);
	const [report, setReport] = useState<CopyIntelligenceDryRunReport | null>(null);
	const [loading, setLoading] = useState(false);
	const [ledger, setLedger] = useState<CopyIntelligenceSeedLedgerResponse | null>(null);
	const [ledgerConfidence, setLedgerConfidence] = useState("");
	const [ledgerStatus, setLedgerStatus] = useState("");
	const [ledgerSearch, setLedgerSearch] = useState("");
	const [uploadError, setUploadError] = useState("");
	const [ledgerError, setLedgerError] = useState("");
	const [ledgerLoading, setLedgerLoading] = useState(true);
	const [reviewRow, setReviewRow] = useState<CopyIntelligenceSeedLedgerRow | null>(null);
	const [refreshKey, setRefreshKey] = useState(0);
	const [promoting, setPromoting] = useState("");
	const [promoteResults, setPromoteResults] = useState<Record<string, CopyIntelligencePromoteResult>>({});
	const [promoteErrors, setPromoteErrors] = useState<Record<string, string>>({});

	const promoteSeed = async (seedId: string) => {
		setPromoting(seedId);
		setPromoteErrors((prev) => ({ ...prev, [seedId]: "" }));
		try {
			const result = await promoteApprovedCopyIntelligenceSeed(seedId);
			setPromoteResults((prev) => ({ ...prev, [seedId]: result }));
		} catch (cause) {
			setPromoteErrors((prev) => ({ ...prev, [seedId]: cause instanceof Error ? cause.message : "Promote gagal." }));
		} finally {
			setPromoting("");
		}
	};

	useEffect(() => {
		let active = true;
		setLedgerLoading(true);
		setLedgerError("");
		void listCopyIntelligenceSeedLedger({
			confidence: ledgerConfidence || undefined,
			status: ledgerStatus || undefined,
			search: ledgerSearch || undefined,
		}).then((response) => {
			if (active) setLedger(response);
		}).catch((cause) => {
			if (active) {
				setLedger(null);
				setLedgerError(cause instanceof Error ? cause.message : "Ledger tidak dapat dimuatkan.");
			}
		}).finally(() => {
			if (active) setLedgerLoading(false);
		});
		return () => { active = false; };
	}, [ledgerConfidence, ledgerSearch, ledgerStatus, refreshKey]);

	const runDryRun = async () => {
		if (!workbook) {
			setUploadError("Pilih fail .xlsx penuh Kalodata & Fastmoss dahulu.");
			return;
		}
		setLoading(true);
		setUploadError("");
		try {
			const uploaded = await uploadCopyIntelligenceWorkbook(workbook);
			setUploadedSource(uploaded);
			setReport(await runUploadedCopyIntelligenceDryRun(uploaded.source_id));
		} catch (cause) {
			setReport(null);
			setUploadError(cause instanceof Error ? cause.message : "Dry-run gagal.");
		} finally {
			setLoading(false);
		}
	};

	const safeRecords = (report?.matched_high_confidence ?? 0) + (report?.matched_medium_confidence ?? 0);
	const unsafeRecords = (report?.low_confidence_quarantined ?? 0) + (report?.unmatched ?? 0);

	return (
		<div className="mx-auto max-w-6xl space-y-5 p-5 md:p-8" data-testid="copy-intelligence-page">
			<div className="space-y-2">
				<h2 className="text-xl font-bold tracking-tight text-slate-100">Copy Intelligence / Customer Avatar</h2>
				<p className="max-w-3xl text-sm text-slate-400">
					Audit COPYWRITING HUB before any owner-authorized seed. This screen is review-only: it cannot approve copy, change Product Truth, or send material to generation.
				</p>
			</div>

			<Section step="1" title="Full workbook upload" helper="Upload then dry-run is explicit and review-only.">
				<p className="text-sm font-medium text-slate-200">Upload the full Kalodata & Fastmoss workbook</p>
				<HelperText>Do not create a COPYWRITING HUB-only workbook. Matching requires both COPYWRITING HUB and MERGED PRODUCTS.</HelperText>
				<label className="block text-xs font-semibold text-slate-300" htmlFor="copy-intelligence-workbook">
					Full workbook (.xlsx)
				</label>
				<div className="mt-2 flex flex-col gap-3 sm:flex-row">
					<input
						id="copy-intelligence-workbook"
						type="file"
						accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
						onChange={(event) => setWorkbook(event.target.files?.[0] ?? null)}
						className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600"
					/>
					<button
						type="button"
						data-testid="upload-copy-intelligence-workbook"
						disabled={loading}
						onClick={() => void runDryRun()}
						className="rounded-lg border border-blue-400/40 bg-blue-500/15 px-4 py-2 text-xs font-bold uppercase tracking-wide text-blue-100 hover:bg-blue-500/25 disabled:opacity-50"
					>
						{loading ? "Uploading and running…" : "Upload and run dry-run"}
					</button>
				</div>
				{workbook && <p className="text-xs text-slate-400">Selected: {workbook.name}</p>}
				{uploadedSource && <p className="text-xs text-slate-400">Stored source: {uploadedSource.original_filename} · fingerprint {uploadedSource.fingerprint}</p>}
				<HelperText>Nothing is seeded from this page. Seed execution requires separate owner authorization.</HelperText>
				{uploadError && <p className="text-xs font-medium text-red-300" role="alert">Upload and dry-run error: {uploadError}</p>}
			</Section>

			{report && (
				<Section title="Review summary" helper={`Source: ${uploadedSource?.original_filename ?? report.source_workbook}`}>
					<div className="flex flex-wrap gap-2">
						<Badge tone="info">NEEDS_REVIEW only</Badge>
						<Badge tone="success">No Product Truth mutation</Badge>
						<Badge tone="success">No approved Copy Set mutation</Badge>
						<Badge tone="warn">No automatic seed execution</Badge>
					</div>
					<div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="copy-intelligence-summary">
						<CountCard label="High confidence" value={report.matched_high_confidence} tone="success" />
						<CountCard label="Medium confidence" value={report.matched_medium_confidence} tone="info" />
						<CountCard label="Quarantined / low" value={report.low_confidence_quarantined} tone="warn" />
						<CountCard label="Unmatched" value={report.unmatched} tone="danger" />
					</div>
					<div className="grid gap-3 text-sm text-slate-300 md:grid-cols-2">
						<div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
							<div className="font-semibold text-emerald-100">{safeRecords} safe review records</div>
							<div className="mt-1 text-xs text-slate-400">HIGH and MEDIUM matches remain review records; this page does not persist them.</div>
						</div>
						<div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-4">
							<div className="font-semibold text-amber-100">{unsafeRecords} quarantined or low-confidence records</div>
							<div className="mt-1 text-xs text-slate-400">LOW, unmatched, ambiguous, and duplicate-target records are excluded from normal persistence.</div>
						</div>
					</div>
				</Section>
			)}

			<Section title="Seeded review ledger" helper="Persisted HIGH and MEDIUM records only. Viewing this ledger never seeds, approves, or routes copy.">
				<div className="grid gap-3 md:grid-cols-3">
					<label className="text-xs font-semibold text-slate-300">Ledger confidence
						<select aria-label="Ledger confidence" value={ledgerConfidence} onChange={(event) => setLedgerConfidence(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100">
							<option value="">All confidence</option><option value="HIGH">HIGH</option><option value="MEDIUM">MEDIUM</option>
						</select>
					</label>
					<label className="text-xs font-semibold text-slate-300">Ledger status
						<select aria-label="Ledger status" value={ledgerStatus} onChange={(event) => setLedgerStatus(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100">
							<option value="">All statuses</option><option value="NEEDS_REVIEW">NEEDS_REVIEW</option><option value="APPROVED">APPROVED</option><option value="REJECTED">REJECTED</option>
						</select>
					</label>
					<label className="text-xs font-semibold text-slate-300">Search ledger
						<input aria-label="Search ledger" value={ledgerSearch} onChange={(event) => setLedgerSearch(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" placeholder="Product, avatar, or hook" />
					</label>
				</div>
				{ledgerLoading ? (
					<p className="text-sm text-slate-400">Loading seeded review records…</p>
				) : ledgerError ? (
					<p className="text-sm font-medium text-red-300" role="alert">Unable to load ledger: {ledgerError}</p>
				) : ledger?.total === 0 ? (
					<p className="text-sm text-slate-400">No seeded review records yet</p>
				) : (
					<div className="overflow-x-auto" data-testid="copy-intelligence-seed-ledger">
						<p className="mb-3 text-xs text-slate-400">{ledger?.total ?? 0} persisted review records</p>
						<table className="min-w-[1400px] text-left text-xs text-slate-300">
							<thead className="border-b border-slate-700 text-[10px] uppercase tracking-wide text-slate-500"><tr><th>Source</th><th>Product</th><th>Avatar</th><th>Pain / emotion</th><th>Dream / features</th><th>Hook</th><th>CTA</th><th>Confidence</th><th>Match</th><th>Status</th><th>Provenance</th><th>Review</th></tr></thead>
							<tbody>{ledger?.items.map((row) => <tr key={row.seed_id} className="border-b border-slate-800 align-top"><td className="p-2">{row.source_row}</td><td className="p-2 font-medium text-slate-100">{row.source_product_name}</td><td className="p-2">{row.target_avatar || "—"}</td><td className="p-2">{row.pain_point || "—"}<br />{row.emotion_trigger || "—"}</td><td className="p-2">{row.dream_outcome || "—"}<br />{row.key_ingredients_features || "—"}</td><td className="p-2">{row.hook_script || "—"}</td><td className="p-2">{row.cta_script || "—"}</td><td className="p-2">{row.confidence}</td><td className="p-2">{row.match_method}</td><td className="p-2">{row.status}</td><td className="p-2">{row.source_workbook}<br />{row.source_sheet} · row {row.provenance.source_row || row.source_row}</td><td className="p-2">{row.status === "NEEDS_REVIEW" ? <button type="button" data-testid={`review-seed-${row.seed_id}`} onClick={() => setReviewRow(row)} className="rounded-md border border-blue-400/40 bg-blue-500/15 px-3 py-1 text-[10px] font-bold uppercase tracking-wide text-blue-100 hover:bg-blue-500/25">Review</button> : row.status === "APPROVED" ? <div className="space-y-1"><span className="block text-[10px] uppercase tracking-wide text-emerald-400">APPROVED</span>{promoteResults[row.seed_id] ? <span className="block text-[10px] text-slate-400" data-testid={`promote-result-${row.seed_id}`}>Draft {promoteResults[row.seed_id].draft_id.slice(0, 8)} · {promoteResults[row.seed_id].review_status}</span> : <button type="button" data-testid={`promote-seed-${row.seed_id}`} disabled={promoting === row.seed_id} onClick={() => void promoteSeed(row.seed_id)} className="rounded-md border border-emerald-400/40 bg-emerald-500/15 px-2 py-1 text-[10px] font-bold uppercase tracking-wide text-emerald-100 hover:bg-emerald-500/25 disabled:opacity-50">{promoting === row.seed_id ? "Creating…" : "Create review draft"}</button>}{promoteErrors[row.seed_id] && <span className="block text-[10px] text-red-300" role="alert">{promoteErrors[row.seed_id]}</span>}</div> : <span className="text-[10px] uppercase tracking-wide text-slate-500">{row.status}</span>}</td></tr>)}</tbody>
						</table>
					</div>
				)}
			</Section>

			{reviewRow && (
				<SeedReviewModal
					row={reviewRow}
					onClose={() => setReviewRow(null)}
					onReviewed={() => {
						setReviewRow(null);
						setRefreshKey((key) => key + 1);
					}}
				/>
			)}
		</div>
	);
}
