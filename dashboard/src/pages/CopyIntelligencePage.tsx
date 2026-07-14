import { useState } from "react";
import {
	runCopyIntelligenceDryRun,
	type CopyIntelligenceDryRunReport,
} from "../api/copyIntelligence";
import { Badge, HelperText, Section } from "../components/ui";

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
	const [sourcePath, setSourcePath] = useState("");
	const [report, setReport] = useState<CopyIntelligenceDryRunReport | null>(null);
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState("");

	const runDryRun = async () => {
		const trimmedPath = sourcePath.trim();
		if (!trimmedPath) {
			setError("Masukkan laluan workbook COPYWRITING HUB dahulu.");
			return;
		}
		setLoading(true);
		setError("");
		try {
			setReport(await runCopyIntelligenceDryRun(trimmedPath));
		} catch (cause) {
			setReport(null);
			setError(cause instanceof Error ? cause.message : "Dry-run gagal.");
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

			<Section step="1" title="COPYWRITING HUB source" helper="Dry-run reads the selected workbook only after you explicitly start it.">
				<label className="block text-xs font-semibold text-slate-300" htmlFor="copy-intelligence-source-path">
					COPYWRITING HUB workbook path
				</label>
				<div className="mt-2 flex flex-col gap-3 sm:flex-row">
					<input
						id="copy-intelligence-source-path"
						value={sourcePath}
						onChange={(event) => setSourcePath(event.target.value)}
						placeholder="C:\\path\\to\\workbook.xlsx"
						className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600"
					/>
					<button
						type="button"
						data-testid="run-copy-intelligence-dry-run"
						disabled={loading}
						onClick={() => void runDryRun()}
						className="rounded-lg border border-blue-400/40 bg-blue-500/15 px-4 py-2 text-xs font-bold uppercase tracking-wide text-blue-100 hover:bg-blue-500/25 disabled:opacity-50"
					>
						{loading ? "Running dry-run…" : "Run dry-run"}
					</button>
				</div>
				<HelperText>Nothing is seeded from this page. Seed execution requires separate owner authorization.</HelperText>
				{error && <p className="text-xs font-medium text-red-300" role="alert">{error}</p>}
			</Section>

			{report && (
				<Section title="Review summary" helper={`Source: ${report.source_workbook}`}>
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
		</div>
	);
}
