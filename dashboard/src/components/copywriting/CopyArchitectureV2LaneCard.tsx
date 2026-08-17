import { useEffect, useState } from "react";
import { ExternalLink } from "lucide-react";
import {
	useCopyArchitectureV2Lane,
	type CopyArchitectureV2Execution,
	type CopyArchitectureV2Lane,
} from "../../api/copyArchitectureV2";
import { fetchCopyBindingResolution } from "../../api/copyRegisterV2";
import { TechnicalDetails } from "../ui/TechnicalDetails";

interface CopyArchitectureV2LaneCardProps {
	lane: CopyArchitectureV2Lane;
	productId?: string | null;
	/** Metadata returned by a prepared package, compile, or queue boundary. */
	execution?: CopyArchitectureV2Execution | null;
	onReadyChange?: (ready: boolean) => void;
	compact?: boolean;
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
	compact: _compact = false,
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
			});
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

	// Human friendly status label
	const humanStatusLabel = copyFree
		? "Copy Not Required"
		: ready
			? "Copy Ready"
			: !enabled
				? "Maintenance Mode"
				: resolutionLoading || loading
					? "Checking Copy..."
					: "Copywriting Required";

	return (
		<section
			className="rounded-xl border border-slate-800 bg-slate-950/50 p-3.5 text-xs text-slate-200"
			data-testid="copy-v2-lane-card"
			data-copy-v2-lane={lane}
			data-copy-v2-product={productId ?? ""}
		>
			{/* Clean Human Surface */}
			<div className="flex flex-wrap items-center justify-between gap-2">
				<div className="flex items-center gap-2">
					<span
						className={`h-2 w-2 rounded-full ${
							ready || copyFree ? "bg-emerald-400" : "bg-amber-400"
						}`}
					/>
					<span className="font-semibold text-slate-200">
						{descriptor?.display_name || lane} Copy Authority
					</span>
				</div>

				<span
					className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
						ready || copyFree
							? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
							: "border border-amber-500/30 bg-amber-500/10 text-amber-300"
					}`}
				>
					{humanStatusLabel}
				</span>
			</div>

			{/* Approved Hook preview for normal operators */}
			{ready && !copyFree && approvedHook && approvedHook !== "Awaiting V2 binding" ? (
				<div className="mt-2.5 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-xs">
					<span className="text-[9px] font-bold uppercase tracking-wider text-emerald-400">
						Active Hook:
					</span>
					<p className="mt-0.5 text-slate-200 italic">"{approvedHook}"</p>
				</div>
			) : null}

			{/* Blocker alert if blocked */}
			{blockers.length && !ready && !copyFree ? (
				<div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-200">
					<span className="flex-1">{blockers[0]}</span>
					{productId ? (
						<a
							href={`/creative/copy-registry?product_id=${encodeURIComponent(productId)}`}
							target="_blank"
							rel="noreferrer"
							data-testid="p6-open-copy-register"
							className="inline-flex items-center gap-1 rounded bg-amber-600/90 px-2.5 py-1 text-[10px] font-bold text-white hover:bg-amber-500"
						>
							<span>Open Copy Register</span>
							<ExternalLink size={11} />
						</a>
					) : null}
				</div>
			) : null}

			{/* Technical details collapsed drawer for developer/test diagnostics */}
			<TechnicalDetails title="Technical details" className="mt-3">
				<div className="space-y-2">
					<div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2">
						<span className="text-slate-400">Policy</span>
						<span data-testid="copy-v2-policy" className="font-mono text-slate-200">
							{descriptor?.copy_policy === "NOT_REQUIRED"
								? "COPY_NOT_REQUIRED"
								: "COPY_REQUIRED"}
						</span>
					</div>

					<div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4 font-mono text-[11px]">
						<div data-testid="copy-v2-readiness">
							<div className="text-slate-500 text-[10px]">Readiness</div>
							<div className="text-slate-200">{readiness}</div>
						</div>
						<div data-testid="copy-v2-production-valid">
							<div className="text-slate-500 text-[10px]">Production-valid</div>
							<div className="text-slate-200">{productionValid}</div>
						</div>
						<div data-testid="copy-v2-blueprint">
							<div className="text-slate-500 text-[10px]">Blueprint / revision</div>
							<div className="text-slate-200">{blueprintId} · r{revision}</div>
						</div>
						<div data-testid="copy-v2-formula">
							<div className="text-slate-500 text-[10px]">Formula</div>
							<div className="text-slate-200">{formula}</div>
						</div>
					</div>

					<div data-testid="copy-v2-approved-hook" className="border-t border-slate-800 pt-2 text-[11px]">
						<span className="text-slate-500">Approved Hook: </span>
						<span className="text-slate-200">{approvedHook}</span>
					</div>

					<div className="grid gap-1 sm:grid-cols-3 border-t border-slate-800 pt-2 text-[10px]">
						<div data-testid="copy-v2-revalidation">
							<span className="text-slate-500">Revalidation: </span>
							<span>{text(effectiveExecution?.revalidation_action, enabled ? "REQUIRED before binding" : "Not asserted")}</span>
						</div>
						<div data-testid="copy-v2-semantic-review">
							<span className="text-slate-500">Semantic review: </span>
							<span>{text(effectiveExecution?.semantic_review_action, enabled ? "REQUIRED before binding" : "Not asserted")}</span>
						</div>
						<div data-testid="copy-v2-action-availability">
							<span className="text-slate-500">Action: </span>
							<span>{ready ? "Available — V2 binding proven" : "Blocked until V2 binding is proven"}</span>
						</div>
					</div>

					{blockers.length ? (
						<div data-testid="copy-v2-blockers" className="border-t border-slate-800 pt-2 text-[11px] text-amber-300">
							<div className="font-semibold text-slate-400">Blockers:</div>
							<ul className="list-disc pl-4 space-y-0.5">
								{blockers.map((b, i) => (
									<li key={i}>{b}</li>
								))}
							</ul>
						</div>
					) : null}
				</div>
			</TechnicalDetails>
		</section>
	);
}
