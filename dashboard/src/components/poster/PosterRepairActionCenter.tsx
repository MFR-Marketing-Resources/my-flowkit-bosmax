import { ClipboardCopy } from "lucide-react";
import type { PosterRepairAction } from "../../types/posterReadiness";

interface PosterRepairActionCenterProps {
	actions: PosterRepairAction[];
	title?: string;
}

export default function PosterRepairActionCenter({
	actions,
	title = "Repair action center",
}: PosterRepairActionCenterProps) {
	if (actions.length === 0) {
		return (
			<section className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
				<p className="text-sm text-slate-400">No repair actions returned by the API.</p>
			</section>
		);
	}

	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5">
			<h3 className="text-sm font-bold uppercase tracking-[0.16em] text-slate-300">
				{title}
			</h3>
			<p className="mt-1 text-xs text-slate-500">
				Actions are informational in this PR — endpoints are not auto-executed.
			</p>
			<div className="mt-4 space-y-4">
				{actions.map((action) => (
					<RepairActionCard key={action.action_code} action={action} />
				))}
			</div>
		</section>
	);
}

function RepairActionCard({ action }: { action: PosterRepairAction }) {
	const endpoint =
		action.recommended_endpoint || action.recommended_future_endpoint || null;

	const copyPayload = [
		action.action_code,
		endpoint,
		action.notes,
	]
		.filter(Boolean)
		.join("\n");

	return (
		<article className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
			<div className="flex flex-wrap items-start justify-between gap-2">
				<div>
					<p className="text-sm font-semibold text-slate-100">{action.label}</p>
					<p className="font-mono text-[10px] text-slate-500">{action.action_code}</p>
				</div>
				<span className="rounded-full border border-slate-700 px-2 py-0.5 text-[9px] font-bold uppercase text-slate-400">
					{action.severity}
				</span>
			</div>

			<div className="mt-3 grid gap-2 text-xs text-slate-400 sm:grid-cols-2">
				<p>
					<span className="text-slate-500">Human approval:</span>{" "}
					{action.requires_human_approval ? "Yes" : "No"}
				</p>
				<p>
					<span className="text-slate-500">Auto-executable:</span>{" "}
					{action.auto_executable ? "Yes" : "No"}
				</p>
				<p>
					<span className="text-slate-500">Manual review:</span>{" "}
					{action.manual_review_required ? "Yes" : "No"}
				</p>
				<p>
					<span className="text-slate-500">Next check:</span> {action.next_check}
				</p>
			</div>

			{endpoint ? (
				<p className="mt-2 break-all font-mono text-[10px] text-blue-200/90">
					{endpoint}
				</p>
			) : null}

			{action.expected_status_after_success ? (
				<p className="mt-2 text-xs text-slate-300">
					<span className="text-slate-500">After success:</span>{" "}
					{action.expected_status_after_success}
				</p>
			) : null}
			{action.expected_status_if_no_other_blockers ? (
				<p className="text-xs text-slate-300">
					<span className="text-slate-500">If no other blockers:</span>{" "}
					{action.expected_status_if_no_other_blockers}
				</p>
			) : null}

			{action.notes ? (
				<p className="mt-2 text-xs text-slate-400">{action.notes}</p>
			) : null}

			<button
				type="button"
				disabled
				title="Repair execution is out of scope for this PR"
				className="mt-3 inline-flex cursor-not-allowed items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500"
			>
				View endpoint (no auto-run)
			</button>
			<button
				type="button"
				onClick={() => void navigator.clipboard?.writeText(copyPayload)}
				className="mt-2 ml-2 inline-flex items-center gap-1 rounded-lg border border-slate-700 px-3 py-2 text-[10px] font-semibold text-slate-300 hover:border-slate-500"
			>
				<ClipboardCopy size={12} /> Copy action
			</button>
		</article>
	);
}