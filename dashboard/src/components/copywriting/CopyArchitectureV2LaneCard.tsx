import { useEffect, useState } from "react";
import {
	useCopyArchitectureV2Lane,
	type CopyArchitectureV2Execution,
	type CopyArchitectureV2Lane,
} from "../../api/copyArchitectureV2";
import { fetchCopyBindingResolution } from "../../api/copyRegisterV2";

interface CopyArchitectureV2LaneCardProps {
	lane: CopyArchitectureV2Lane;
	productId?: string | null;
	/** Metadata returned by a prepared package, compile, or queue boundary. */
	execution?: CopyArchitectureV2Execution | null;
	onReadyChange?: (ready: boolean) => void;
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

function issueText(value: unknown): string | null {
	if (Array.isArray(value)) {
		const items = value.map(issueText).filter((item): item is string => Boolean(item));
		return items.length ? items.join("; ") : null;
	}
	if (typeof value === "string" && value.trim()) return value.trim();
	if (typeof value === "number" && Number.isFinite(value)) return String(value);
	if (value && typeof value === "object") {
		try {
			return JSON.stringify(value);
		} catch {
			return "Unserializable V2 error";
		}
	}
	return null;
}

function executionIssue(
	execution: CopyArchitectureV2Execution | null | undefined,
	prefix: string,
): string | null {
	if (!execution) return null;
	const explicit =
		issueText(execution.error_code) ??
		issueText(execution.error) ??
		issueText(execution.blocker) ??
		issueText(execution.blockers);
	if (explicit) return `${prefix}: ${explicit}`;
	const executionStatus = issueText(execution.status)?.toUpperCase();
	if (executionStatus && /STALE|ERROR|FAILED|BLOCKED|REJECTED|UNAVAILABLE/.test(executionStatus)) {
		return `${prefix} status: ${executionStatus}`;
	}
	return null;
}

function structuredResolutionError(reason: unknown): string {
	const raw = reason instanceof Error ? reason.message : issueText(reason) || "V2 binding resolution failed";
	const payloadText = raw.replace(/^API\s+\d+:\s*/i, "").trim();
	let payload: unknown;
	try {
		payload = JSON.parse(payloadText);
	} catch {
		return raw;
	}
	const root = record(payload);
	const detail = root.detail ?? payload;
	const detailRecord = record(detail);
	const code =
		issueText(detailRecord.error_code) ??
		issueText(detailRecord.error) ??
		issueText(root.error_code) ??
		issueText(root.error);
	const message =
		issueText(detailRecord.message) ??
		issueText(detailRecord.detail) ??
		issueText(root.message);
	const detailText = typeof detail === "string" ? detail : null;
	if (code && (message || detailText)) return `${code}: ${message || detailText}`;
	if (code) return code;
	if (message || detailText) return message || detailText || raw;
	return raw;
}

interface PersistedResolutionState {
	productId: string;
	lane: CopyArchitectureV2Lane;
	execution?: CopyArchitectureV2Execution;
	error?: string;
}

export default function CopyArchitectureV2LaneCard({
	lane,
	productId,
	execution,
	onReadyChange,
}: CopyArchitectureV2LaneCardProps) {
	const { descriptor, status, loading, error } = useCopyArchitectureV2Lane(lane);
	const [persistedResolution, setPersistedResolution] =
		useState<PersistedResolutionState | null>(null);

	useEffect(() => {
		if (!productId) return;
		let active = true;
		void fetchCopyBindingResolution(productId, lane)
			.then((response) => {
				if (active) setPersistedResolution({ productId, lane, execution: response });
			})
			.catch((reason: unknown) => {
				if (!active) return;
				setPersistedResolution({
					productId,
					lane,
					error: structuredResolutionError(reason),
				});
			})
		return () => {
			active = false;
		};
	}, [lane, productId]);

	const selectionResolution =
		persistedResolution &&
		persistedResolution.productId === productId &&
		persistedResolution.lane === lane
			? persistedResolution
			: null;
	const persistedExecution = selectionResolution?.execution ?? null;
	const resolutionError = selectionResolution?.error ?? null;
	const resolutionLoading = Boolean(productId && !selectionResolution);
	// A selected product always resolves readiness from the persisted V2
	// authority. A package/queue receipt remains useful for display while the
	// authority request is pending, but it cannot make the product READY.
	const canonicalExecution = productId ? persistedExecution : execution;
	const effectiveExecution = canonicalExecution ?? execution;
	const projection = record(effectiveExecution?.projection);
	const derivedCopy = record(projection.derived_copy);
	const flags = status?.feature_flags;
	const binding = record(effectiveExecution?.binding);
	const enabled = Boolean(flags?.enabled);
	const executionStatus = text(canonicalExecution?.status, "NOT_RESOLVED");
	const authorityReady = productId
		? Boolean(persistedExecution) && !resolutionLoading && !resolutionError && executionStatus === "READY"
		: executionStatus === "READY";
	const receiptIssue = productId ? executionIssue(execution ?? null, "WEP receipt") : null;
	const authorityIssue = executionIssue(
		canonicalExecution,
		productId ? "Persisted V2 resolution" : "V2 receipt",
	);
	const ready = enabled && authorityReady && !receiptIssue && !authorityIssue;
	const copyFree = descriptor?.copy_policy === "NOT_REQUIRED";

	useEffect(() => {
		onReadyChange?.(ready);
	}, [onReadyChange, ready]);

	const authorityChecking = Boolean(productId && !persistedExecution && !resolutionError);
	const readiness = error
		? "UNAVAILABLE — readiness not asserted"
		: resolutionError
			? "UNAVAILABLE — persisted V2 resolution failed"
		: loading || resolutionLoading || authorityChecking
			? "CHECKING V2 CONTRACT"
			: !enabled
				? "V2 MAINTENANCE MODE"
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
		effectiveExecution?.blueprint_id ?? binding.blueprint_id,
		copyFree ? "N/A — copy-free lane" : "Not selected",
	);
	const revision = text(
		effectiveExecution?.revision ?? binding.revision,
		copyFree ? "N/A" : "Not selected",
	);
	const formula = copyFree
		? "N/A — copy-free lane"
		: `${text(effectiveExecution?.formula_id ?? binding.formula_id)} · ${text(effectiveExecution?.formula_version ?? binding.formula_version)}`;
	const approvedHook = text(
		derivedCopy.hook,
		ready ? "Approved Hook not present in V2 projection" : "Awaiting V2 binding",
	);
	const explicitBlockers = [resolutionError, receiptIssue, authorityIssue].filter(
		(item): item is string => Boolean(item),
	);
	const blockers = explicitBlockers.length
		? explicitBlockers
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

			<div
				className="mt-3 rounded-lg border border-emerald-500/25 bg-emerald-500/5 px-3 py-2"
				data-testid="copy-v2-approved-hook"
			>
				<div className="text-[9px] font-bold uppercase tracking-widest text-emerald-300">
					Approved Copy V2 Hook
				</div>
				<div className="mt-1 text-[12px] text-slate-100">
					{approvedHook}
				</div>
				<div className="mt-1 text-[10px] text-slate-500">
					Read-only projection from the production V2 binding; Faceless Opening Strategy does not edit it.
				</div>
			</div>

			<div className="mt-3 grid gap-2 sm:grid-cols-3">
				<div data-testid="copy-v2-revalidation">
					<span className="text-slate-500">Revalidation:</span>{" "}
					{text(effectiveExecution?.revalidation_action, enabled ? "REQUIRED before binding" : "Not asserted")}
				</div>
				<div data-testid="copy-v2-semantic-review">
					<span className="text-slate-500">Semantic review:</span>{" "}
					{text(effectiveExecution?.semantic_review_action, enabled ? "REQUIRED before binding" : "Not asserted")}
				</div>
				<div data-testid="copy-v2-action-availability">
					<span className="text-slate-500">Action:</span>{" "}
					{ready
						? "Available — V2 binding proven"
						: enabled
						? "Blocked until V2 binding is proven"
						: "V2 maintenance mode; production action unavailable"}
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
