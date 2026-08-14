import {
	useCopyArchitectureV2Lane,
	type CopyArchitectureV2Execution,
	type CopyArchitectureV2Lane,
} from "../../api/copyArchitectureV2";

interface CopyArchitectureV2LaneCardProps {
	lane: CopyArchitectureV2Lane;
	productId?: string | null;
	/** Metadata returned by a prepared package, compile, or queue boundary. */
	execution?: CopyArchitectureV2Execution | null;
}
function record(value: unknown): Record<string, unknown> {
	return value && typeof value === "object" && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
}

function text(value: unknown, fallback = "Not selected") {
	if (typeof value === "number" && Number.isFinite(value)) return String(value);
	return typeof value === "string" && value.trim() ? value : fallback;
}

export default function CopyArchitectureV2LaneCard({
	lane,
	productId,
	execution,
}: CopyArchitectureV2LaneCardProps) {
	const { descriptor, status, loading, error } = useCopyArchitectureV2Lane(lane);
	const flags = status?.feature_flags;
	const binding = record(execution?.binding);
	const enabled = Boolean(flags?.enabled);
	const executionStatus = text(execution?.status, "NOT_RESOLVED");
	const ready = enabled && executionStatus === "READY";
	const copyFree = descriptor?.copy_policy === "NOT_REQUIRED";

	const readiness = error
		? "UNAVAILABLE — readiness not asserted"
		: loading
			? "CHECKING V2 CONTRACT"
			: !enabled
				? "V2 OFF — LEGACY COMPATIBLE"
				: ready
					? "READY"
					: "BLOCKED — V2 BINDING REQUIRED";
	const productionValid = error
		? "NOT ASSERTED"
		: !enabled
			? "NOT ASSERTED BY V2"
			: ready
				? "YES"
				: "NO";

	const blueprintId = text(
		execution?.blueprint_id ?? binding.blueprint_id,
		copyFree ? "N/A — copy-free lane" : "Not selected",
	);
	const revision = text(
		execution?.revision ?? binding.revision,
		copyFree ? "N/A" : "Not selected",
	);
	const formula = copyFree
		? "N/A — copy-free lane"
		: `${text(execution?.formula_id ?? binding.formula_id)} · ${text(execution?.formula_version ?? binding.formula_version)}`;
	const blocker = execution?.blocker ?? execution?.error ?? execution?.blockers;
	const blockers = Array.isArray(blocker)
		? blocker.map(String)
		: blocker
			? [String(blocker)]
			: enabled && !ready
				? [
					copyFree
						? "Copy-free adapter requires readiness, provenance and safety proof."
						: "Approved V2 blueprint, Product Truth, evidence and safety proof are required.",
				  ]
				: [];

	return (
		<section
			className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-3 text-[11px] text-slate-200"
			data-testid="copy-v2-lane-card"
			data-copy-v2-lane={lane}
			data-copy-v2-product={productId ?? ""}
		>
			<div className="flex flex-wrap items-center justify-between gap-2">
				<div>
					<div className="font-bold uppercase tracking-[0.16em] text-indigo-200">
						Copy Architecture V2 · {descriptor?.display_name ?? lane}
					</div>
					<div className="mt-1 text-[10px] text-slate-400">
						Universal adapter: {descriptor?.adapter ?? "loading"} · Product: {productId || "not selected"}
					</div>
				</div>
				<span
					className="rounded-full border border-indigo-400/30 bg-indigo-500/10 px-2 py-1 font-bold uppercase tracking-wider text-indigo-100"
					data-testid="copy-v2-policy"
				>
					{descriptor?.copy_policy === "NOT_REQUIRED"
						? "COPY_NOT_REQUIRED"
						: "COPY_REQUIRED"}
				</span>
			</div>

			<div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
				<div data-testid="copy-v2-readiness">
					<div className="text-[9px] uppercase tracking-widest text-slate-500">Readiness</div>
					<div className="font-semibold text-slate-100">{readiness}</div>
				</div>
				<div data-testid="copy-v2-production-valid">
					<div className="text-[9px] uppercase tracking-widest text-slate-500">Production-valid</div>
					<div className="font-semibold text-slate-100">{productionValid}</div>
				</div>
				<div data-testid="copy-v2-blueprint">
					<div className="text-[9px] uppercase tracking-widest text-slate-500">Blueprint / revision</div>
					<div className="font-semibold text-slate-100">{blueprintId} · r{revision}</div>
				</div>
				<div data-testid="copy-v2-formula">
					<div className="text-[9px] uppercase tracking-widest text-slate-500">Formula</div>
					<div className="font-semibold text-slate-100">{formula}</div>
				</div>
			</div>

			<div className="mt-3 grid gap-2 sm:grid-cols-3">
				<div data-testid="copy-v2-revalidation">
					<span className="text-slate-500">Revalidation:</span>{" "}
					{text(execution?.revalidation_action, enabled ? "REQUIRED before binding" : "Not asserted")}
				</div>
				<div data-testid="copy-v2-semantic-review">
					<span className="text-slate-500">Semantic review:</span>{" "}
					{text(execution?.semantic_review_action, enabled ? "REQUIRED before binding" : "Not asserted")}
				</div>
				<div data-testid="copy-v2-action-availability">
					<span className="text-slate-500">Action:</span>{" "}
					{ready
						? "Available — V2 binding proven"
						: enabled
						? "Blocked until V2 binding is proven"
						: "Legacy controls unchanged; V2 action not asserted"}
				</div>
			</div>

			{blockers.length ? (
				<div
					className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-amber-100"
					data-testid="copy-v2-blockers"
				>
					<div className="font-semibold">Blocker / error</div>
					<ul className="mt-1 list-disc space-y-0.5 pl-4">
						{blockers.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}
					</ul>
				</div>
			) : null}
		</section>
	);
}
