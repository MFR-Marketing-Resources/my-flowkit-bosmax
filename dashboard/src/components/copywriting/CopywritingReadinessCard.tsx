import type { CopywritingReadiness } from "../../api/copywritingReadiness";

const NEXT_ACTION_LABEL: Record<string, string> = {
	PREPARE_PRODUCT_FOR_COPYWRITING: "Prepare Product for Copywriting",
	GENERATE_AND_APPROVE_COPY_SET: "Generate & approve a Copy Set",
	COMPLETE_PRODUCT_INTELLIGENCE: "Complete Product Knowledge + Avatar",
	READY: "Copywriting ready",
	REVALIDATE_COPY_SET: "Open Copy Registry to revalidate",
	SEMANTIC_REVIEW_COPY_SET: "Open Copy Registry for semantic review",
	REVIEW_COPY_SET: "Open Copy Registry to review copy",
	REPAIR_OR_REPLACE_COPY_SET: "Open Copy Registry to repair or replace",
	REPLACE_COPY_SET: "Open Copy Registry to replace copy",
	BLOCKED: "Open Copy Registry to resolve blockers",
};

/**
 * Shared readiness card for generation surfaces. Renders nothing when copy is
 * not applicable (clean-frame image lanes). Shows a "Prepare Product for
 * Copywriting" (or Copy Registry) CTA when the product isn't copywriting-ready.
 */
export default function CopywritingReadinessCard({
	readiness,
	loading = false,
	onPrepare,
	onOpenCopyRegistry,
}: {
	readiness: CopywritingReadiness | null;
	loading?: boolean;
	onPrepare?: () => void;
	onOpenCopyRegistry?: () => void;
}) {
	if (loading && !readiness) {
		return (
			<p className="text-[11px] text-slate-500" data-testid="copywriting-readiness-loading">
				Checking copywriting readiness…
			</p>
		);
	}
	if (!readiness || readiness.copy_applicable === false) return null;

	const ready = readiness.ready_for_generation;
	const action = readiness.recommended_next_action;
	return (
		<section
			data-testid="copywriting-readiness-card"
			className={`rounded-2xl border p-4 ${
				ready
					? "border-emerald-500/30 bg-emerald-500/5"
					: "border-amber-500/40 bg-amber-500/5"
			}`}
		>
			<div className="flex flex-wrap items-center justify-between gap-2">
				<h3 className="text-[11px] font-bold uppercase tracking-[0.14em] text-slate-300">
					Copywriting readiness
				</h3>
				<span
					data-testid="readiness-badge"
					className={`text-[10px] font-bold uppercase ${
						ready ? "text-emerald-300" : "text-amber-300"
					}`}
				>
					{ready ? "READY" : "NOT READY"}
				</span>
			</div>
			<ul className="mt-2 grid gap-1 text-[11px] text-slate-400 md:grid-cols-2">
				<li>Approved snapshot: {readiness.has_approved_snapshot ? "✓" : "✗"}</li>
				<li>Product Knowledge: {readiness.product_knowledge_ready ? "✓" : "✗"}</li>
				<li>Customer Avatar: {readiness.customer_avatar_ready ? "✓" : "✗"}</li>
				<li data-testid="readiness-raw-approved-count">
					Approved records: {readiness.approved_copy_set_count}
				</li>
				<li data-testid="readiness-valid-approved-count">
					Production-valid approved:{" "}
					{readiness.valid_approved_copy_set_count ?? 0}
				</li>
				{readiness.copy_classification ? (
					<li data-testid="readiness-copy-classification">
						Copy class: {readiness.copy_classification}
					</li>
				) : null}
				<li>Recommended formula: {readiness.recommended_formula}</li>
				<li>
					Formula QA: {readiness.formula_validation_status} ·{" "}
					{readiness.sales_clarity_status}
				</li>
			</ul>
			{readiness.blocking_reasons.length ? (
				<p data-testid="readiness-blockers" className="mt-2 text-[11px] text-amber-200/90">
					Blocked: {readiness.blocking_reasons.join(", ")}
				</p>
			) : null}
			{!ready ? (
				<div className="mt-3 flex flex-wrap gap-2">
					{action === "PREPARE_PRODUCT_FOR_COPYWRITING" ||
					action === "COMPLETE_PRODUCT_INTELLIGENCE" ? (
						<button
							type="button"
							data-testid="readiness-prepare-cta"
							onClick={onPrepare}
							className="rounded-xl border border-emerald-500/40 bg-emerald-600/20 px-3 py-1.5 text-[11px] font-bold uppercase text-emerald-100"
						>
							{NEXT_ACTION_LABEL[action] ?? "Prepare Product for Copywriting"}
						</button>
					) : null}
					{action === "GENERATE_AND_APPROVE_COPY_SET" ? (
						<button
							type="button"
							data-testid="readiness-copy-registry-cta"
							onClick={onOpenCopyRegistry}
							className="rounded-xl border border-blue-500/40 bg-blue-600/20 px-3 py-1.5 text-[11px] font-bold uppercase text-blue-100"
						>
							Generate &amp; approve a Copy Set
						</button>
					) : null}
					{[
						"REVALIDATE_COPY_SET",
						"SEMANTIC_REVIEW_COPY_SET",
						"REVIEW_COPY_SET",
						"REPAIR_OR_REPLACE_COPY_SET",
						"REPLACE_COPY_SET",
						"BLOCKED",
					].includes(action) ? (
						<button
							type="button"
							data-testid="readiness-copy-registry-remediation-cta"
							onClick={onOpenCopyRegistry}
							className="rounded-xl border border-blue-500/40 bg-blue-600/20 px-3 py-1.5 text-[11px] font-bold uppercase text-blue-100"
						>
							{NEXT_ACTION_LABEL[action] ?? "Open Copy Registry"}
						</button>
					) : null}
				</div>
			) : null}
		</section>
	);
}
