import { ArrowLeft, CheckCircle2, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
	batchActivateCopyBlueprints,
	fetchCopyRegisterBlueprint,
	listCopyRegisterBlueprints,
	type CopyBlueprintV2Record,
	type CopyRegisterActivationStatusV2,
} from "../api/copyRegisterV2";
import { fetchProductDetail } from "../api/products";
import { Badge, HelperText, Section, TechnicalDetails } from "../components/ui";
import type { Product } from "../types";

const INPUT_CLASS =
	"mt-1 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200";
const ACTIVATION_CONFIRMATION_PHRASE = "ACTIVATE_COPY_AUTHORITY_BATCH";

type DetailState = "CURRENT" | "READY" | "STALE" | "DRAFT";

function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : "Copy Authority detail could not be loaded.";
}

function humanReason(blueprint: CopyBlueprintV2Record): string {
	const reason = blueprint.current_authority_reason ?? "COPY_V2_AUTHORITY_ATTENTION";
	if (reason === "COPY_V2_EVIDENCE_STALE" || reason === "COPY_V2_PRODUCT_TRUTH_STALE") {
		return "The approved copy no longer matches the current Product Truth / evidence lineage.";
	}
	if (reason === "COPY_V2_TAXONOMY_AUTHORITY_STALE") {
		return "The taxonomy authority changed after this copy was approved.";
	}
	if (reason === "EXPLICIT_HUMAN_APPROVAL_REQUIRED") {
		return "This draft remains reviewable until a human approves it.";
	}
	return reason.replaceAll("_", " ").toLowerCase();
}

function exactActivationIsCurrent(
	blueprint: CopyBlueprintV2Record,
	activation: CopyRegisterActivationStatusV2 | null,
): boolean {
	return Boolean(
		activation &&
		activation.active_blueprint_id === blueprint.blueprint_id &&
		activation.active_revision === blueprint.revision &&
		activation.active_lane_count >= activation.required_lane_count,
	);
}

function resolveDetailState(
	blueprint: CopyBlueprintV2Record,
	activation: CopyRegisterActivationStatusV2 | null,
): DetailState {
	if (blueprint.status === "DRAFT") return "DRAFT";
	if (exactActivationIsCurrent(blueprint, activation)) return "CURRENT";
	if (
		blueprint.status === "PRODUCTION_VALID" &&
		blueprint.current_authority_activation_allowed === true
	) {
		return "READY";
	}
	return "STALE";
}

function activationIsReady(blueprint: CopyBlueprintV2Record, activation: CopyRegisterActivationStatusV2 | null): boolean {
	return resolveDetailState(blueprint, activation) === "READY";
}

export default function CopyAuthorityDetailPage() {
	const [searchParams] = useSearchParams();
	const productId = searchParams.get("product_id")?.trim() ?? "";
	const blueprintId = searchParams.get("blueprint_id")?.trim() ?? "";
	const revisionParam = searchParams.get("revision");
	const requestedRevision = revisionParam ? Number(revisionParam) : undefined;
	const [blueprint, setBlueprint] = useState<CopyBlueprintV2Record | null>(null);
	const [product, setProduct] = useState<Product | null>(null);
	const [activation, setActivation] = useState<CopyRegisterActivationStatusV2 | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");
	const [activationOpen, setActivationOpen] = useState(false);
	const [confirmationPhrase, setConfirmationPhrase] = useState("");
	const [ownerAuthorization, setOwnerAuthorization] = useState(false);
	const [busy, setBusy] = useState(false);
	const [success, setSuccess] = useState("");

	const loadDetail = useCallback(async () => {
		if (!productId || !blueprintId) {
			setError("An exact product_id and blueprint_id are required for Authority Detail.");
			setLoading(false);
			return;
		}
		setLoading(true);
		setError("");
		try {
			const [loadedBlueprint, productResponse, productBlueprints] = await Promise.all([
				fetchCopyRegisterBlueprint(
					blueprintId,
					Number.isFinite(requestedRevision) && requestedRevision ? requestedRevision : undefined,
				),
				fetchProductDetail(productId),
				listCopyRegisterBlueprints(productId),
			]);
			if (loadedBlueprint.product_id !== productId || loadedBlueprint.blueprint_id !== blueprintId) {
				throw new Error("The requested blueprint does not belong to the requested product.");
			}
			setBlueprint(loadedBlueprint);
			setProduct(productResponse);
			setActivation(productBlueprints.activation ?? null);
		} catch (reason) {
			setError(errorMessage(reason));
		} finally {
			setLoading(false);
		}
	}, [blueprintId, productId, requestedRevision]);

	useEffect(() => {
		void loadDetail();
	}, [loadDetail]);

	const detailState = useMemo(
		() => (blueprint ? resolveDetailState(blueprint, activation) : null),
		[activation, blueprint],
	);
	const canActivate = Boolean(blueprint && detailState && activationIsReady(blueprint, activation));

	const submitActivation = async () => {
		if (!blueprint || !canActivate || confirmationPhrase !== ACTIVATION_CONFIRMATION_PHRASE || !ownerAuthorization) return;
		setBusy(true);
		setError("");
		try {
			const response = await batchActivateCopyBlueprints({
				blueprint_ids: [blueprint.blueprint_id],
				confirmation_phrase: confirmationPhrase,
				owner_authorization: ownerAuthorization,
			});
			const result = response.results?.[0];
			if (!result?.activated && result?.status !== "ALREADY_ACTIVE") {
				throw new Error(result?.error_detail || result?.error_code || "The exact blueprint could not be activated.");
			}
			setActivationOpen(false);
			setConfirmationPhrase("");
			setOwnerAuthorization(false);
			setSuccess("This exact prepared copy is CURRENT for the governed standard lanes.");
			await loadDetail();
		} catch (reason) {
			setError(errorMessage(reason));
			setActivationOpen(false);
		} finally {
			setBusy(false);
		}
	};

	return (
		<div className="mx-auto max-w-5xl space-y-6 p-4 md:p-8" data-testid="copy-authority-detail-page">
			<header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-800 pb-5">
				<div>
					<div className="flex items-center gap-2 text-blue-300">
						<ShieldCheck size={20} />
						<span className="text-[10px] font-bold uppercase tracking-[0.2em]">Deep-link-only V2 inspection</span>
					</div>
					<h1 className="mt-1 text-2xl font-bold text-slate-100">V2 Authority Detail</h1>
					<p className="mt-1 max-w-3xl text-xs text-slate-400">Inspect one exact governed blueprint. Normal copy creation and cross-product governance live elsewhere.</p>
				</div>
				<Link to="/creative/storyboard-landbank-v3" className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-300 hover:bg-slate-800" data-testid="authority-back-to-landbank">
					<ArrowLeft size={14} /> Back to Copywriting Landbank
				</Link>
			</header>

			{loading ? <p className="rounded-xl border border-dashed border-slate-700 p-6 text-sm text-slate-400">Loading the exact blueprint…</p> : null}
			{error ? <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100" data-testid="authority-detail-error">{error}</p> : null}
			{success ? <p className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100" data-testid="authority-detail-success">{success}</p> : null}

			{blueprint ? (
				<>
					<Section title="Exact governed blueprint" helper="Immutable V2 inspection; no alternate blueprint is substituted.">
						<div className="grid gap-3 sm:grid-cols-2">
							<div><div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Product</div><div className="mt-1 text-sm font-semibold text-slate-100">{product ? product.product_display_name : productId}</div><div className="font-mono text-[10px] text-slate-500">{productId}</div></div>
							<div data-testid="authority-blueprint-id"><div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Blueprint / revision</div><div className="mt-1 font-mono text-sm text-slate-100">{blueprint.blueprint_id} · revision {blueprint.revision}</div><div className="mt-1 text-[10px] text-slate-500">Status: {blueprint.status}</div></div>
							<div><div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Formula</div><div className="mt-1 text-sm font-semibold text-slate-100">{blueprint.formula_id} · {blueprint.formula_version}</div></div>
							<div><div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Angle</div><div className="mt-1 text-sm text-slate-200">{blueprint.angle.definition}</div></div>
						</div>

						<div className="mt-4 flex flex-wrap items-center gap-2">
							<Badge tone={detailState === "CURRENT" ? "success" : detailState === "READY" ? "info" : detailState === "DRAFT" ? "warn" : "danger"}>{detailState}</Badge>
							{detailState === "CURRENT" ? <span data-testid="authority-state-current" className="text-[10px] font-semibold text-emerald-200">CURRENT</span> : null}
							{detailState === "READY" ? <span data-testid="authority-state-ready" className="text-[10px] font-semibold text-blue-200">READY</span> : null}
							{detailState === "STALE" ? <span data-testid="authority-state-stale" className="text-[10px] font-semibold text-amber-200">STALE · {humanReason(blueprint)}</span> : null}
							{detailState === "DRAFT" ? <span data-testid="authority-state-draft" className="text-[10px] font-semibold text-amber-200">DRAFT</span> : null}
							{activation ? <span className="text-[10px] text-slate-500">{activation.active_lane_count}/{activation.required_lane_count} required lanes currently bound</span> : null}
						</div>
					</Section>

					<Section title="Immutable formula stages" helper="Exact authored text is displayed in formula order; authoring and regeneration remain in the canonical workflow.">
						<div className="space-y-3">
							{[...blueprint.stages].sort((left, right) => left.order - right.order).map((stage) => (
								<div key={`${stage.stage_key}:${stage.order}`} className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
									<div className="flex flex-wrap items-center justify-between gap-2"><span className="text-[10px] font-bold uppercase tracking-wide text-blue-200">{stage.order + 1}. {stage.formula_stage_key}</span><span className="text-[10px] text-slate-500">{stage.semantic_role}</span></div>
									<p className="mt-2 text-sm leading-6 text-slate-200">{stage.authored_text}</p>
								</div>
							))}
						</div>
					</Section>

					{detailState === "CURRENT" ? <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4"><div className="flex items-center gap-2 text-sm font-semibold text-emerald-100"><CheckCircle2 size={16} /> This exact blueprint is already CURRENT.</div><HelperText className="mt-1">No redundant approval or activation work is offered.</HelperText></div> : null}
					{detailState === "READY" ? <Section title="Exact activation handoff" helper="Activation binds only this exact prepared blueprint to the required lanes. Owner authorization and the governed phrase remain mandatory."><button type="button" onClick={() => setActivationOpen(true)} disabled={busy} className="rounded-lg bg-emerald-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid="authority-activate-button">Activate this exact prepared copy</button></Section> : null}
					{detailState === "STALE" ? <Section title="Replacement required" helper="This exact item is diagnostic only; replace it through the canonical Copywriting Landbank."><p className="text-sm text-amber-100">{humanReason(blueprint)}</p><Link to={`/creative/storyboard-landbank-v3?product_id=${encodeURIComponent(productId)}`} className="mt-3 inline-flex rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs font-bold text-amber-100" data-testid="authority-open-landbank">Create Replacement in Copywriting Landbank</Link></Section> : null}
					{detailState === "DRAFT" ? <Section title="Human review required" helper="Draft approval belongs to the cross-product governance surface."><p className="text-sm text-amber-100">{humanReason(blueprint)}</p><Link to={`/creative/copy-review-queue?product_id=${encodeURIComponent(productId)}`} className="mt-3 inline-flex rounded-lg border border-amber-400/40 bg-amber-500/10 px-3 py-2 text-xs font-bold text-amber-100" data-testid="authority-open-governance">Open Copy Governance Queue</Link></Section> : null}

					<TechnicalDetails className="mt-4" testId="authority-technical-details" title="Technical details">
						<div className="grid gap-1 font-mono text-[10px] text-slate-500"><div>Product Truth fingerprint: {blueprint.current_authority_fingerprint ?? "—"}</div><div>Blueprint fingerprint: {blueprint.blueprint_authority_fingerprint ?? "—"}</div><div>Authority reason: {blueprint.current_authority_reason ?? "—"}</div><div>Validation mismatches: {JSON.stringify(blueprint.current_authority_mismatches ?? [])}</div></div>
					</TechnicalDetails>
				</>
			) : null}

			{activationOpen && blueprint ? (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" data-testid="authority-activation-confirm">
					<div className="w-full max-w-lg rounded-2xl border border-emerald-500/30 bg-slate-950 p-6">
						<h2 className="text-lg font-bold text-slate-100">Activate this exact prepared copy?</h2>
						<HelperText className="mt-1">This binds blueprint {blueprint.blueprint_id}, revision {blueprint.revision}; it does not generate or approve copy.</HelperText>
						<label className="mt-4 block text-xs font-semibold text-slate-300">Confirmation phrase<input className={INPUT_CLASS} value={confirmationPhrase} onChange={(event) => setConfirmationPhrase(event.target.value)} data-testid="authority-activation-phrase" /></label>
						<label className="mt-3 flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={ownerAuthorization} onChange={(event) => setOwnerAuthorization(event.target.checked)} data-testid="authority-activation-owner" /> I authorize this exact activation.</label>
						<div className="mt-5 flex justify-end gap-2"><button type="button" onClick={() => setActivationOpen(false)} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300">Cancel</button><button type="button" onClick={() => void submitActivation()} disabled={busy || confirmationPhrase !== ACTIVATION_CONFIRMATION_PHRASE || !ownerAuthorization} className="rounded-lg bg-emerald-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-40" data-testid="authority-activation-confirm-submit">{busy ? "Activating…" : "Confirm activation"}</button></div>
					</div>
				</div>
			) : null}
		</div>
	);
}
