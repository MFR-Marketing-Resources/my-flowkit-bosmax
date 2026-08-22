import { ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState, type RefObject } from "react";
import { useSearchParams } from "react-router-dom";

import {
	batchActivateCopyBlueprints,
	fetchCopyActivationCandidates,
	type CopyActivationCandidateV2,
	type CopyBatchActivationResultV2,
} from "../../api/copyRegisterV2";
import { Badge, FormField, HelperText, Section } from "../ui";

const INPUT_CLASS =
	"mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200";

const ACTIVATION_CONFIRMATION_PHRASE = "ACTIVATE_COPY_AUTHORITY_BATCH";

function CopyActivationQueue({
	candidates,
	selectedIds,
	confirmationPhrase,
	ownerAuthorized,
	busy,
	error,
	results,
	confirmOpen,
	onToggle,
	onPhraseChange,
	onOwnerChange,
	onReview,
	onCancelReview,
	onConfirm,
	queueRef,
}: {
	candidates: CopyActivationCandidateV2[];
	selectedIds: string[];
	confirmationPhrase: string;
	ownerAuthorized: boolean;
	busy: boolean;
	error: string;
	results: CopyBatchActivationResultV2[];
	confirmOpen: boolean;
	onToggle: (blueprintId: string) => void;
	onPhraseChange: (value: string) => void;
	onOwnerChange: (value: boolean) => void;
	onReview: () => void;
	onCancelReview: () => void;
	onConfirm: () => void;
	queueRef: RefObject<HTMLDivElement | null>;
}) {
	const readyToReview =
		selectedIds.length > 0 &&
		confirmationPhrase === ACTIVATION_CONFIRMATION_PHRASE &&
		ownerAuthorized;
	return (
		<Section
			title="Copy authority activation report"
			helper="Review authority exceptions and activate current approved blueprints here. Copy Authority remains focused on copy work."
		>
			<div ref={queueRef} data-testid="activation-queue" className="space-y-4">
				{error ? (
					<p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-100" data-testid="activation-queue-error">
						{error}
					</p>
				) : null}
				<div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
					<span data-testid="activation-candidate-count">{candidates.length} PRODUCTION_VALID blueprint{candidates.length === 1 ? "" : "s"}</span>
					<span>Exact phrase + explicit owner authorization required</span>
				</div>
				<div className="space-y-2" data-testid="activation-candidate-list">
					{candidates.length === 0 ? (
						<p className="rounded-lg border border-dashed border-slate-800 px-3 py-4 text-xs text-slate-500">No PRODUCTION_VALID activation candidates are currently available.</p>
					) : candidates.map((candidate) => {
						const alreadyCurrent = candidate.current_authority_state === "CURRENT";
						const selectable = candidate.activatable && !alreadyCurrent;
						const disabledReason = alreadyCurrent
							? "Already CURRENT for all required lanes; rerun is an idempotent no-op."
							: candidate.blocked_reason || "Current authority is not activatable.";
						return (
							<label
								key={`${candidate.blueprint_id}:${candidate.revision}`}
								data-testid={`activation-candidate-${candidate.blueprint_id}`}
								className={`block rounded-lg border p-3 ${selectable ? "border-slate-800 bg-slate-950/60" : "border-amber-500/30 bg-amber-500/5"}`}
							>
								<div className="flex items-start gap-3">
									<input
										type="checkbox"
										data-testid={`activation-select-${candidate.blueprint_id}`}
										checked={selectedIds.includes(candidate.blueprint_id)}
										disabled={!selectable || busy}
										onChange={() => onToggle(candidate.blueprint_id)}
										className="mt-1"
									/>
									<div className="min-w-0 flex-1 text-xs">
										<div className="flex flex-wrap items-center gap-2">
											<span className="font-semibold text-slate-100">{candidate.product_name || candidate.product_id}</span>
											<Badge tone={alreadyCurrent ? "success" : selectable ? "info" : "warn"}>{candidate.current_authority_state}</Badge>
											<span className="font-mono text-[10px] text-slate-500">{candidate.blueprint_id} · rev {candidate.revision}</span>
										</div>
										<p className="mt-1 text-slate-400">{candidate.formula_id} · {candidate.required_lane_count} required lanes · {candidate.status}</p>
										{!selectable ? <HelperText tone="warn" className="mt-1">Disabled: {disabledReason}</HelperText> : null}
									</div>
								</div>
							</label>
						);
					})}
				</div>

				<div className="grid gap-3 rounded-lg border border-slate-800 bg-slate-950/50 p-3 md:grid-cols-2">
					<FormField label="Exact confirmation phrase" className="md:col-span-2">
						<input
							className={INPUT_CLASS}
							data-testid="activation-confirmation-phrase"
							value={confirmationPhrase}
							onChange={(event) => onPhraseChange(event.target.value)}
							placeholder={ACTIVATION_CONFIRMATION_PHRASE}
						/>
					</FormField>
					<label className="flex items-start gap-2 text-xs text-slate-300 md:col-span-2">
						<input
							type="checkbox"
							data-testid="activation-owner-authorization"
							checked={ownerAuthorized}
							onChange={(event) => onOwnerChange(event.target.checked)}
							className="mt-0.5"
						/>
						<span>I am the owner authorizing this copy-authority activation batch.</span>
					</label>
					<HelperText className="md:col-span-2">
						Selected: {selectedIds.length}. The batch is capped at 50 blueprints and rejects any stale, draft, or unapproved id before binding.
					</HelperText>
				</div>

				<button
					type="button"
					data-testid="activation-review-selection"
					disabled={busy || !readyToReview}
					onClick={onReview}
					className="rounded-xl border border-blue-500/40 bg-blue-600/20 px-4 py-2 text-xs font-bold uppercase text-blue-100 disabled:opacity-40"
				>
					Review selected activation
				</button>

				{results.length ? (
					<div className="space-y-2 rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3" data-testid="activation-results">
						<p className="text-xs font-semibold text-emerald-100">Activation results</p>
						{results.map((result) => (
							<div key={result.blueprint_id} className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-300">
								<span className="font-mono">{result.blueprint_id}</span>
								<span className={result.status === "FAILED" ? "text-rose-200" : "text-emerald-200"}>
									{result.status} · {result.lane_count} lanes{result.error_code ? ` · ${result.error_code}` : ""}
								</span>
							</div>
						))}
					</div>
				) : null}

				{confirmOpen ? (
					<div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4" data-testid="activation-confirm-overlay">
						<div className="w-full max-w-lg rounded-2xl border border-blue-500/40 bg-slate-900 p-6 shadow-2xl">
							<div className="flex items-center gap-2 text-blue-200"><ShieldCheck size={18} /><span className="text-[11px] font-bold uppercase tracking-[0.18em]">Owner-gated authority activation</span></div>
							<h2 className="mt-2 text-lg font-bold text-slate-100">Confirm binding selected copy authority?</h2>
							<ul className="mt-3 space-y-1.5 text-xs text-slate-300">
								<li>• Selected blueprints: <span className="font-semibold text-slate-100">{selectedIds.length}</span></li>
								<li>• This binds approved copy for the <span className="font-semibold text-slate-100">video and poster lanes</span>.</li>
								<li>• It does <span className="font-semibold text-slate-100">not</span> generate video or spend credits.</li>
								<li>• Existing authority receipts are not deleted; only the explicit pointer may be advanced.</li>
							</ul>
							<div className="mt-5 flex items-center justify-end gap-3">
								<button type="button" data-testid="activation-confirm-cancel" disabled={busy} onClick={onCancelReview} className="rounded-lg border border-slate-700 px-4 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800 disabled:opacity-40">Cancel</button>
								<button type="button" data-testid="activation-confirm-submit" disabled={busy} onClick={onConfirm} className="rounded-lg border border-blue-500/40 bg-blue-600/30 px-4 py-2 text-xs font-bold uppercase text-blue-100 hover:bg-blue-600/50 disabled:opacity-40">{busy ? "Activating…" : "Confirm bulk activation"}</button>
							</div>
						</div>
					</div>
				) : null}
			</div>
		</Section>
	);
}



function errorMessage(error: unknown): string {
	const message = error instanceof Error ? error.message : "Copy authority reporting request failed.";
	const jsonStart = message.indexOf("{");
	if (jsonStart < 0) return message;
	try {
		const payload = JSON.parse(message.slice(jsonStart));
		const detail = payload?.detail;
		if (detail?.error && detail?.detail) return `${detail.error}: ${detail.detail}`;
	} catch {
		// Preserve original transport error
	}
	return message;
}

export default function CopyAuthorityActivationReport() {
	const [searchParams] = useSearchParams();
	const targetBlueprintId = searchParams.get("blueprint_id");
	const [candidates, setCandidates] = useState<CopyActivationCandidateV2[]>([]);
	const [selectedIds, setSelectedIds] = useState<string[]>([]);
	const [confirmationPhrase, setConfirmationPhrase] = useState("");
	const [ownerAuthorized, setOwnerAuthorized] = useState(false);
	const [results, setResults] = useState<CopyBatchActivationResultV2[]>([]);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [success, setSuccess] = useState("");
	const [confirmOpen, setConfirmOpen] = useState(false);
	const queueRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		let cancelled = false;
		void fetchCopyActivationCandidates()
			.then((response) => {
				if (cancelled) return;
				const items = response.items ?? [];
				setCandidates(items);
				if (!targetBlueprintId) return;
				const target = items.find((item) => item.blueprint_id === targetBlueprintId);
				if (!target) {
					setError(`Blueprint ${targetBlueprintId} is not present in the current activation report.`);
					return;
				}
				if (target.activatable && target.current_authority_state !== "CURRENT") {
					setSelectedIds([targetBlueprintId]);
					setError("");
					return;
				}
				setError(target.blocked_reason || "This blueprint is not a current activation candidate.");
			})
			.catch((reason) => {
				if (!cancelled) setError(errorMessage(reason));
			});
		return () => {
			cancelled = true;
		};
	}, [targetBlueprintId]);

	const toggleSelection = (blueprintId: string) => {
		setSelectedIds((current) =>
			current.includes(blueprintId)
				? current.filter((item) => item !== blueprintId)
				: [...current, blueprintId],
		);
	};

	const handleBatchActivation = async () => {
		if (
			selectedIds.length === 0 ||
			confirmationPhrase !== ACTIVATION_CONFIRMATION_PHRASE ||
			!ownerAuthorized
		) return;
		setBusy(true);
		setError("");
		setSuccess("");
		try {
			const response = await batchActivateCopyBlueprints({
				blueprint_ids: selectedIds,
				confirmation_phrase: confirmationPhrase,
				owner_authorization: ownerAuthorized,
			});
			setResults(response.results ?? []);
			setSelectedIds([]);
			setSuccess(
				`Bulk activation complete: ${response.activated_count} blueprint${response.activated_count === 1 ? "" : "s"} bound; ${response.bound_lane_count} lane bindings written.`,
			);
			const refreshed = await fetchCopyActivationCandidates();
			setCandidates(refreshed.items ?? []);
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setBusy(false);
			setConfirmOpen(false);
		}
	};

	return (
		<div data-testid="copy-authority-activation-report">
			{success ? (
				<p
					className="mb-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100"
					data-testid="copy-authority-activation-success"
				>
					{success}
				</p>
			) : null}
			<CopyActivationQueue
				candidates={candidates}
				selectedIds={selectedIds}
				confirmationPhrase={confirmationPhrase}
				ownerAuthorized={ownerAuthorized}
				busy={busy}
				error={error}
				results={results}
				confirmOpen={confirmOpen}
				onToggle={toggleSelection}
				onPhraseChange={setConfirmationPhrase}
				onOwnerChange={setOwnerAuthorized}
				onReview={() => setConfirmOpen(true)}
				onCancelReview={() => setConfirmOpen(false)}
				onConfirm={() => void handleBatchActivation()}
				queueRef={queueRef}
			/>
		</div>
	);
}
