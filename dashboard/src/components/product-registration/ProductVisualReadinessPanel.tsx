import { useEffect, useRef, useState, type ChangeEvent } from "react";
import {
	approveProductTruthLock,
	productTruthCutoutPreviewUrl,
} from "../../api/productTruthLock";
import {
	fetchProductVisualReadiness,
	prepareProductCutout,
	rejectProductCutout,
	rebuildProductCutout,
	uploadManualProductCutout,
	useOriginalProductFallback,
	startCanvaCutout,
	recordCanvaPreflight,
	advanceCanvaStage,
	completeCanvaCutout,
	type CanvaCapabilityStatus,
	type CanvaMethod,
} from "../../api/productVisualOnboarding";
import type { CanvaCutoutWorkflow, ProductVisualReadiness } from "../../types";

interface Props {
	productId: string;
	productSourceUrl?: string | null;
	readiness?: ProductVisualReadiness;
	compact?: boolean;
	showApprovalForm?: boolean;
	onOpenReview?: () => void;
	onChanged?: (readiness: ProductVisualReadiness) => void;
}

const BADGE: Record<string, string> = {
	AVAILABLE: "bg-emerald-500/15 text-emerald-300",
	APPROVED: "bg-emerald-500/15 text-emerald-300",
	PENDING_REVIEW: "bg-amber-500/15 text-amber-300",
	PREPARING: "bg-sky-500/15 text-sky-300",
	PREPARATION_FAILED: "bg-red-500/15 text-red-300",
	BLOCKED: "bg-red-500/15 text-red-300",
	REJECTED: "bg-red-500/15 text-red-300",
	SUPERSEDED: "bg-slate-700/40 text-slate-400",
	VISUAL_GROUNDING_READY_FALLBACK: "bg-amber-500/15 text-amber-300",
	CUTOUT_REQUIRED: "bg-amber-500/15 text-amber-300",
	NOT_PREPARED: "bg-slate-700/40 text-slate-400",
};

const label = (value: string | undefined | null): string =>
	(value || "NOT_PREPARED").replace(/_/g, " ");

const CANVA_PREFLIGHT_FIELDS = [
	["login_status", "Canva login/session"],
	["magic_grab_status", "Magic Grab"],
	["background_remover_status", "Background Remover"],
	["magic_layers_status", "Magic Layers"],
	["transparent_export_status", "Transparent PNG export"],
] as const;
const CANVA_PREFLIGHT_OPTIONS: CanvaCapabilityStatus[] = ["UNKNOWN", "READY", "UNAVAILABLE", "PRO_REQUIRED", "USER_ACTION_REQUIRED"];
const CANVA_OPERATOR_STAGES = ["OPENING_CANVA", "MAGIC_GRAB", "BACKGROUND_REMOVER", "MAGIC_LAYERS", "CLEAN_CANVAS", "READY_TO_EXPORT", "EXPORTING", "PAUSED"] as const;

function Status({ name, value }: { name: string; value: string | undefined }) {
	return (
		<div className="min-w-0">
			<div className="mb-1 text-[8px] font-bold uppercase tracking-widest text-slate-500">
				{name}
			</div>
			<span
				className={`inline-flex max-w-full truncate rounded px-1.5 py-0.5 text-[9px] font-bold ${BADGE[value || ""] || "bg-slate-700/40 text-slate-400"}`}
			>
				{label(value)}
			</span>
		</div>
	);
}

export default function ProductVisualReadinessPanel({
	productId,
	productSourceUrl,
	readiness: initialReadiness,
	compact = false,
	showApprovalForm = false,
	onOpenReview,
	onChanged,
}: Props) {
	const [readiness, setReadiness] = useState<ProductVisualReadiness | undefined>(
		initialReadiness,
	);
	const [busy, setBusy] = useState<"prepare" | "rebuild" | "approve" | "upload" | "reject" | "fallback" | "canva" | "canva-preflight" | "canva-stage" | "canva-upload" | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [reviewedBy, setReviewedBy] = useState("");
	const [reviewNote, setReviewNote] = useState("");
	const [confirmIdentity, setConfirmIdentity] = useState(false);
	const [confirmLabelLogo, setConfirmLabelLogo] = useState(false);
	const [confirmGeometryScale, setConfirmGeometryScale] = useState(false);
	const fileInputRef = useRef<HTMLInputElement>(null);
	const canvaFileInputRef = useRef<HTMLInputElement>(null);
	const [canvaWorkflow, setCanvaWorkflow] = useState<CanvaCutoutWorkflow | undefined>(initialReadiness?.canva_cutout_workflow);
	const [canvaMethod, setCanvaMethod] = useState<CanvaMethod>("MAGIC_GRAB");
	const [canvaDesignId, setCanvaDesignId] = useState("");
	const [canvaDesignUrl, setCanvaDesignUrl] = useState("");
	const [canvaOperatorStage, setCanvaOperatorStage] = useState<(typeof CANVA_OPERATOR_STAGES)[number]>("OPENING_CANVA");
	const [canvaPreflight, setCanvaPreflight] = useState<Record<string, CanvaCapabilityStatus>>({
		login_status: "UNKNOWN",
		magic_grab_status: "UNKNOWN",
		background_remover_status: "UNKNOWN",
		magic_layers_status: "UNKNOWN",
		transparent_export_status: "UNKNOWN",
	});

	useEffect(() => {
		setReadiness(initialReadiness);
		setCanvaWorkflow(initialReadiness?.canva_cutout_workflow);
		if (initialReadiness?.canva_cutout_workflow) {
			const workflow = initialReadiness.canva_cutout_workflow;
			if (workflow.canva_method && workflow.canva_method !== "UNSELECTED") setCanvaMethod(workflow.canva_method as CanvaMethod);
			setCanvaDesignId(workflow.design_id || "");
			setCanvaDesignUrl(workflow.design_url || "");
			if (CANVA_OPERATOR_STAGES.includes(workflow.current_stage as (typeof CANVA_OPERATOR_STAGES)[number])) setCanvaOperatorStage(workflow.current_stage as (typeof CANVA_OPERATOR_STAGES)[number]);
			setCanvaPreflight((workflow.preflight || {}) as Record<string, CanvaCapabilityStatus>);
		}
	}, [initialReadiness]);

	useEffect(() => {
		if (initialReadiness) return;
		let cancelled = false;
		void fetchProductVisualReadiness(productId)
			.then((next) => {
				if (!cancelled) setReadiness(next);
			})
			.catch((err: unknown) => {
				if (!cancelled) setError(err instanceof Error ? err.message : "Visual readiness unavailable");
			});
		return () => {
			cancelled = true;
		};
	}, [initialReadiness, productId]);

	async function refresh(action: "prepare" | "rebuild") {
		setBusy(action);
		setError(null);
		try {
			const next = action === "prepare"
				? await prepareProductCutout(productId)
				: await rebuildProductCutout(productId);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Visual preparation failed");
		} finally {
			setBusy(null);
		}
	}

	async function approve() {
		if (!reviewedBy.trim() || !reviewNote.trim() || !confirmIdentity || !confirmLabelLogo || !confirmGeometryScale) {
			setError("Explicit reviewer identity, note, and all three confirmations are required.");
			return;
		}
		setBusy("approve");
		setError(null);
		try {
			await approveProductTruthLock(productId, {
				reviewed_by: reviewedBy.trim(),
				review_note: reviewNote.trim(),
				confirm_identity: confirmIdentity,
				confirm_label_logo: confirmLabelLogo,
				confirm_geometry_scale: confirmGeometryScale,
			});
			const next = await fetchProductVisualReadiness(productId);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Approval failed");
		} finally {
			setBusy(null);
		}
	}

	async function uploadManual(event: ChangeEvent<HTMLInputElement>) {
		const file = event.target.files?.[0];
		event.target.value = "";
		if (!file) return;
		if (file.type !== "image/png" || !file.name.toLowerCase().endsWith(".png")) {
			setError("Manual cutout override requires a PNG file with image/png MIME type.");
			return;
		}
		setBusy("upload");
		setError(null);
		try {
			const next = await uploadManualProductCutout(productId, file, reviewedBy.trim() || "operator");
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Manual cutout upload failed");
		} finally {
			setBusy(null);
		}
	}

	function applyCanvaEnvelope(envelope: { workflow: CanvaCutoutWorkflow; readiness: ProductVisualReadiness }) {
		setCanvaWorkflow(envelope.workflow);
		setReadiness(envelope.readiness);
		if (envelope.workflow.canva_method && envelope.workflow.canva_method !== "UNSELECTED") setCanvaMethod(envelope.workflow.canva_method as CanvaMethod);
		setCanvaDesignId(envelope.workflow.design_id || "");
		setCanvaDesignUrl(envelope.workflow.design_url || "");
		if (CANVA_OPERATOR_STAGES.includes(envelope.workflow.current_stage as (typeof CANVA_OPERATOR_STAGES)[number])) setCanvaOperatorStage(envelope.workflow.current_stage as (typeof CANVA_OPERATOR_STAGES)[number]);
		setCanvaPreflight((envelope.workflow.preflight || {}) as Record<string, CanvaCapabilityStatus>);
		onChanged?.(envelope.readiness);
	}

	async function saveCanvaStage() {
		setBusy("canva-stage");
		setError(null);
		try {
			applyCanvaEnvelope(await advanceCanvaStage(productId, {
				stage: canvaOperatorStage,
				canva_method: canvaMethod,
				design_id: canvaDesignId.trim() || undefined,
				design_url: canvaDesignUrl.trim() || undefined,
			}));
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Canva operator stage could not be saved");
		} finally {
			setBusy(null);
		}
	}

	async function startCanva() {
		setBusy("canva");
		setError(null);
		try {
			applyCanvaEnvelope(await startCanvaCutout(productId));
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Canva workflow could not start");
		} finally {
			setBusy(null);
		}
	}

	async function saveCanvaPreflight() {
		setBusy("canva-preflight");
		setError(null);
		try {
			applyCanvaEnvelope(await recordCanvaPreflight(productId, {
				canva_method: canvaMethod,
				design_id: canvaDesignId.trim() || undefined,
				design_url: canvaDesignUrl.trim() || undefined,
				login_status: canvaPreflight.login_status || "UNKNOWN",
				magic_grab_status: canvaPreflight.magic_grab_status || "UNKNOWN",
				background_remover_status: canvaPreflight.background_remover_status || "UNKNOWN",
				magic_layers_status: canvaPreflight.magic_layers_status || "UNKNOWN",
				transparent_export_status: canvaPreflight.transparent_export_status || "UNKNOWN",
			}));
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Canva preflight could not be saved");
		} finally {
			setBusy(null);
		}
	}

	async function uploadCanva(event: ChangeEvent<HTMLInputElement>) {
		const file = event.target.files?.[0];
		event.target.value = "";
		if (!file) return;
		if (file.type !== "image/png" || !file.name.toLowerCase().endsWith(".png")) {
			setError("Canva handoff requires an image/png transparent PNG export.");
			return;
		}
		setBusy("canva-upload");
		setError(null);
		try {
			applyCanvaEnvelope(await completeCanvaCutout(productId, file, {
				canva_method: canvaMethod,
				uploaded_by: reviewedBy.trim() || "operator",
				design_id: canvaDesignId.trim() || undefined,
				design_url: canvaDesignUrl.trim() || undefined,
			}));
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Canva PNG handoff failed");
		} finally {
			setBusy(null);
		}
	}

	async function reject() {
		const operator = reviewedBy.trim() || window.prompt("Reviewer identity")?.trim() || "";
		const reason = window.prompt("Why is this cutout rejected?")?.trim() || "";
		if (!operator || !reason) {
			setError("Reviewer identity and rejection reason are required.");
			return;
		}
		setBusy("reject");
		setError(null);
		try {
			const next = await rejectProductCutout(productId, operator, reason);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Cutout rejection failed");
		} finally {
			setBusy(null);
		}
	}

	async function fallback() {
		const operator = reviewedBy.trim() || window.prompt("Operator identity")?.trim() || "";
		const reason = window.prompt("Why use the original same-product fallback?")?.trim() || "";
		if (!operator || !reason) {
			setError("Operator identity and fallback reason are required.");
			return;
		}
		setBusy("fallback");
		setError(null);
		try {
			const next = await useOriginalProductFallback(productId, operator, reason);
			setReadiness(next);
			onChanged?.(next);
		} catch (err: unknown) {
			setError(err instanceof Error ? err.message : "Fallback selection failed");
		} finally {
			setBusy(null);
		}
	}

	if (!readiness) {
		return (
			<div className="rounded-xl border border-slate-800 bg-slate-900/40 p-3 text-[11px] text-slate-500">
				Loading product visual readiness…
			</div>
		);
	}
	const trustedSourceReason = readiness.canonical_media_status !== "AVAILABLE"
		? "Trusted same-product source must be prepared first."
		: "This action is unavailable in the current review state.";

	return (
		<div className={`min-w-0 max-w-full overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40 ${compact ? "p-2" : "p-5"}`} data-testid="product-visual-readiness">
			<div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
				<div className="min-w-0">
					<h3 className={`${compact ? "text-[10px]" : "text-sm"} font-bold uppercase tracking-widest text-white`}>
						{compact ? "Visual" : "PRODUCT VISUAL READINESS"}
					</h3>
					{!compact && (
						<p className="mt-1 text-[11px] text-slate-500">
							Same-product evidence only. Deterministic preparation is review-only; Exact Commerce remains fail-closed until approved.
						</p>
					)}
				</div>
				{readiness.provider_operations === 0 && (
					<span className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-[8px] font-bold uppercase tracking-widest text-emerald-300">
						No provider spend
					</span>
				)}
			</div>

			<div className={`mt-3 grid gap-2 ${compact ? "grid-cols-2" : "grid-cols-2 md:grid-cols-4"}`}>
				<Status name="Reference" value={readiness.canonical_media_status} />
				<Status name="Cutout" value={readiness.cutout_status} />
				<Status name="Visual Ready" value={readiness.visual_grounding_status} />
				<Status name="Exact Commerce" value={readiness.exact_commerce_status} />
			</div>

			{!compact && (
				<div className="mt-3 grid gap-2 md:grid-cols-3">
					<Status name="Auto Candidate" value={readiness.auto_cutout_status} />
					<Status name="Manual Candidate" value={readiness.manual_cutout_status} />
					<Status name="Active Source" value={readiness.active_visual_source} />
				</div>
			)}

			{!compact && (
				<div className="mt-4 grid gap-2 text-[10px] text-slate-400 md:grid-cols-2">
					<div>Source: <span className="text-slate-200">{label(readiness.visual_grounding_source)}</span></div>
					<div>Reference Pack: <span className="text-slate-200">{label(readiness.reference_pack_status)}</span></div>
					<div>Review: <span className="text-slate-200">{label(readiness.cutout_review_status)}</span></div>
					<div>Attempts: <span className="text-slate-200">{readiness.attempt_count ?? 0}</span></div>
					<div>History: <span className="text-slate-200">{readiness.cutout_history_count ?? 0} preserved candidate(s)</span></div>
				</div>
			)}

			{!compact && (
				<div className="mt-4 grid gap-3 md:grid-cols-3" data-testid="product-cutout-comparison">
					{[
						["Original source", readiness.original_preview_url],
						["Auto candidate", readiness.auto_cutout_preview_url],
						["Manual candidate", readiness.manual_cutout_preview_url],
					].map(([name, src]) => (
						<div key={name} className="rounded-lg border border-slate-800 p-2">
							<div className="mb-2 text-[9px] font-bold uppercase tracking-widest text-slate-500">{name}</div>
							<div className="flex h-36 items-center justify-center rounded bg-white" style={{ backgroundImage: "linear-gradient(45deg,#d1d5db 25%,transparent 25%),linear-gradient(-45deg,#d1d5db 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#d1d5db 75%),linear-gradient(-45deg,transparent 75%,#d1d5db 75%)", backgroundSize: "16px 16px", backgroundPosition: "0 0,0 8px,8px -8px,-8px 0" }}>
								{src ? <img src={src} alt={`${name} cutout`} className="max-h-full max-w-full object-contain" /> : <span className="text-[10px] text-slate-500">Not available</span>}
							</div>
						</div>
					))}
				</div>
			)}

			{(readiness.blockers.length > 0 || readiness.warnings.length > 0) && !compact && (
				<div className="mt-3 space-y-1 text-[10px]">
					{[...readiness.blockers, ...readiness.warnings].slice(0, 4).map((item) => (
						<div key={item} className="text-amber-300">• {label(item)}</div>
					))}
				</div>
			)}

			{!compact && (
				<div className="mt-4 grid gap-3 md:grid-cols-3" data-testid="product-cutout-control-lanes">
					<section className="rounded-lg border border-slate-800 p-3" aria-label="Original source controls">
						<h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-200">Original Source</h4>
						<p className="mt-2 text-[10px] text-slate-500">{readiness.canonical_media_status === "AVAILABLE" ? "Trusted same-product source is available." : trustedSourceReason}</p>
						<div className="mt-3 flex flex-wrap gap-2">
							{productSourceUrl && readiness.can_open_source && (
								<a href={productSourceUrl} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()} className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-300">Open Source</a>
							)}
							<button type="button" onClick={() => void fallback()} disabled={busy !== null || !readiness.can_use_original_fallback} title={!readiness.can_use_original_fallback ? trustedSourceReason : undefined} className="rounded-lg bg-amber-500/20 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-amber-200 disabled:opacity-40">
								{busy === "fallback" ? "Selecting…" : "Use Original Fallback"}
							</button>
						</div>
					</section>

					<section className="rounded-lg border border-slate-800 p-3" aria-label="Auto cutout controls">
						<h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-200">Auto Cutout</h4>
						<p className="mt-2 text-[10px] text-slate-500">{readiness.can_prepare_cutout ? "Local deterministic preparation is ready." : trustedSourceReason}</p>
						<div className="mt-3 flex flex-wrap gap-2">
							<button type="button" onClick={() => void refresh("prepare")} disabled={busy !== null || !readiness.can_prepare_cutout} title={!readiness.can_prepare_cutout ? trustedSourceReason : undefined} className="rounded-lg bg-indigo-600/80 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">
								{busy === "prepare" ? "Preparing…" : "Prepare Auto Cutout"}
							</button>
							{readiness.cutout_status !== "NOT_PREPARED" && (
								<button type="button" onClick={() => void refresh("rebuild")} disabled={busy !== null || !readiness.can_rebuild_cutout} className="rounded-lg bg-slate-700 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-200 disabled:opacity-40">{busy === "rebuild" ? "Rebuilding…" : "Rebuild Auto Cutout"}</button>
							)}
						</div>
					</section>

					<section className="rounded-lg border border-slate-800 p-3" aria-label="Manual and Canva cutout controls">
						<h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-200">Manual / Canva Cutout</h4>
						<p className="mt-2 text-[10px] text-slate-500">{readiness.can_upload_manual_cutout || readiness.can_start_canva_cutout ? "Governed manual lanes are ready." : trustedSourceReason}</p>
						<input ref={fileInputRef} type="file" accept="image/png,.png" onChange={(event) => void uploadManual(event)} className="hidden" />
						<div className="mt-3 flex flex-wrap gap-2">
							<button type="button" onClick={() => void startCanva()} disabled={busy !== null || !readiness.can_start_canva_cutout} title={!readiness.can_start_canva_cutout ? trustedSourceReason : undefined} className="rounded-lg bg-violet-600/90 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40" data-testid="canva-cutout-button">
						{busy === "canva" ? "Starting Canva…" : canvaWorkflow?.current_stage && canvaWorkflow.current_stage !== "NOT_STARTED" ? "Resume Canva Cutout" : "Canva Cutout"}
					</button>
							<button type="button" onClick={() => fileInputRef.current?.click()} disabled={busy !== null || !readiness.can_upload_manual_cutout} title={!readiness.can_upload_manual_cutout ? trustedSourceReason : undefined} className="rounded-lg bg-fuchsia-600/80 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">
							{busy === "upload" ? "Uploading…" : readiness.manual_cutout_status === "NOT_UPLOADED" ? "Upload My Cutout" : "Replace Manual Cutout"}
						</button>
						</div>
					</section>
				</div>
			)}

			<div className="mt-4 flex min-w-0 flex-wrap items-center gap-2">
				{readiness.can_review_cutout && (
					<button type="button" onClick={onOpenReview} className="rounded-lg bg-amber-500/20 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-amber-200">
						Review
					</button>
				)}
				{readiness.can_reject_cutout && (
					<button type="button" onClick={() => void reject()} disabled={busy !== null} className="rounded-lg bg-red-500/20 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-red-200 disabled:opacity-40">
						{busy === "reject" ? "Rejecting…" : "Reject Cutout"}
					</button>
				)}
				{readiness.active_cutout_preview_url && (
					<a href={readiness.active_cutout_preview_url} download className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-[9px] font-bold uppercase tracking-widest text-slate-300">Download Active Cutout</a>
				)}
			</div>

			{canvaWorkflow && canvaWorkflow.current_stage !== "NOT_STARTED" && (
				<div className="mt-4 min-w-0 rounded-lg border border-violet-500/30 bg-violet-500/5 p-3 text-[10px]" data-testid="canva-cutout-workflow">
					<div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
						<div className="min-w-0 break-words font-bold uppercase tracking-widest text-violet-200">Canva Cutout · {label(canvaWorkflow.current_stage)}</div>
						{canvaWorkflow.design_url && <a href={canvaWorkflow.design_url} target="_blank" rel="noreferrer" className="rounded bg-violet-500/20 px-2 py-1 font-bold uppercase tracking-widest text-violet-200">Open Canva Design</a>}
					</div>
					<p className="mt-2 break-words leading-relaxed text-slate-400">
						Canva editing is operator/browser-controller work. BOSMAX records source identity, verifies alpha, and sends the PNG into the existing manual review lane; it does not store Canva cookies or auto-approve.
					</p>
					<div className={`mt-3 grid min-w-0 gap-2 ${compact ? "grid-cols-1 sm:grid-cols-2" : "md:grid-cols-3"}`}>
						<label className="text-slate-400">Method
							<select value={canvaMethod} onChange={(event) => setCanvaMethod(event.target.value as CanvaMethod)} className="mt-1 min-w-0 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-slate-200">
								<option value="MAGIC_GRAB">Magic Grab</option>
								<option value="BACKGROUND_REMOVER">Background Remover</option>
								<option value="MAGIC_LAYERS">Magic Layers</option>
							</select>
						</label>
						<label className="text-slate-400">Design ID
							<input value={canvaDesignId} onChange={(event) => setCanvaDesignId(event.target.value)} placeholder="Optional" className="mt-1 min-w-0 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-slate-200" />
						</label>
						<label className="text-slate-400">Design URL
							<input value={canvaDesignUrl} onChange={(event) => setCanvaDesignUrl(event.target.value)} placeholder="https://www.canva.com/design/..." className="mt-1 min-w-0 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-slate-200" />
						</label>
					</div>
					<div className={`mt-3 grid min-w-0 gap-2 ${compact ? "grid-cols-1 sm:grid-cols-2" : "md:grid-cols-5"}`}>
						{CANVA_PREFLIGHT_FIELDS.map(([key, name]) => (
							<label key={key} className="text-slate-400">{name}
								<select value={canvaPreflight[key] || "UNKNOWN"} onChange={(event) => setCanvaPreflight((previous) => ({ ...previous, [key]: event.target.value as CanvaCapabilityStatus }))} className="mt-1 min-w-0 w-full rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-[9px] text-slate-200">
									{CANVA_PREFLIGHT_OPTIONS.map((option) => <option key={option} value={option}>{option.replace(/_/g, " ")}</option>)}
								</select>
							</label>
						))}
					</div>
					<div className="mt-3 flex flex-wrap items-center gap-2">
						<button type="button" onClick={() => void saveCanvaPreflight()} disabled={busy !== null} className="rounded bg-violet-600/80 px-2.5 py-1.5 font-bold uppercase tracking-widest text-white disabled:opacity-40">
							{busy === "canva-preflight" ? "Saving preflight…" : "Save Canva Preflight"}
						</button>
						<input ref={canvaFileInputRef} type="file" accept="image/png,.png" onChange={(event) => void uploadCanva(event)} className="hidden" />
						<button type="button" onClick={() => canvaFileInputRef.current?.click()} disabled={busy !== null || canvaWorkflow.current_stage === "CANVA_PRO_REQUIRED"} className="rounded bg-fuchsia-600/80 px-2.5 py-1.5 font-bold uppercase tracking-widest text-white disabled:opacity-40">
							{busy === "canva-upload" ? "Verifying PNG…" : "Upload Canva PNG → Manual Review"}
						</button>
						<label className="text-slate-400">Operator stage
							<select value={canvaOperatorStage} onChange={(event) => setCanvaOperatorStage(event.target.value as (typeof CANVA_OPERATOR_STAGES)[number])} className="ml-2 rounded border border-slate-700 bg-slate-800 px-2 py-1.5 text-[9px] text-slate-200">
								{CANVA_OPERATOR_STAGES.map((stage) => <option key={stage} value={stage}>{stage.replace(/_/g, " ")}</option>)}
							</select>
						</label>
						<button type="button" onClick={() => void saveCanvaStage()} disabled={busy !== null || canvaWorkflow.current_stage === "CANVA_PRO_REQUIRED"} className="rounded bg-slate-700 px-2.5 py-1.5 font-bold uppercase tracking-widest text-slate-200 disabled:opacity-40">
							{busy === "canva-stage" ? "Saving stage…" : "Record Operator Stage"}
						</button>
						<span className="text-slate-500">Alpha verified: <span className={canvaWorkflow.alpha_verified ? "text-emerald-300" : "text-amber-300"}>{canvaWorkflow.alpha_verified ? "YES" : "NO"}</span></span>
					</div>
					{canvaWorkflow.current_stage === "CANVA_PRO_REQUIRED" && <div className="mt-2 text-amber-300">CANVA_PRO_REQUIRED — no editing/export workflow is started until transparent PNG entitlement is available.</div>}
					{canvaWorkflow.last_error && <div className="mt-2 text-red-300">{canvaWorkflow.last_error_code ? `${canvaWorkflow.last_error_code}: ` : ""}{canvaWorkflow.last_error}</div>}
				</div>
			)}

			{showApprovalForm && readiness.can_review_cutout && (
				<div className="mt-5 border-t border-slate-800 pt-4" data-testid="product-visual-approval">
					<div className="mb-3 flex flex-wrap items-start gap-4">
						{readiness.cutout_preview_available && (
							<img src={readiness.active_cutout_preview_url || productTruthCutoutPreviewUrl(productId)} alt="Deterministic cutout candidate" className="h-32 w-32 rounded-lg border border-slate-700 bg-white object-contain" />
						)}
						<div className="flex-1 text-[10px] leading-relaxed text-amber-200">
							This candidate is not approved. Inspect identity, label/logo, geometry, scale, and source lineage. Approve Exact Cutout applies to the active candidate, including a Canva handoff, only after explicit human confirmation.
						</div>
					</div>
					<div className="grid gap-2 md:grid-cols-2">
						<input value={reviewedBy} onChange={(event) => setReviewedBy(event.target.value)} placeholder="Reviewer identity" className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white" />
						<input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="Review note" className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs text-white" />
					</div>
					<div className="mt-3 grid gap-2 text-[10px] text-slate-300 md:grid-cols-3">
						<label><input type="checkbox" checked={confirmIdentity} onChange={(event) => setConfirmIdentity(event.target.checked)} className="mr-1" /> Identity</label>
						<label><input type="checkbox" checked={confirmLabelLogo} onChange={(event) => setConfirmLabelLogo(event.target.checked)} className="mr-1" /> Label / logo</label>
						<label><input type="checkbox" checked={confirmGeometryScale} onChange={(event) => setConfirmGeometryScale(event.target.checked)} className="mr-1" /> Geometry / scale</label>
					</div>
					<button type="button" onClick={() => void approve()} disabled={busy !== null || !reviewedBy.trim() || !reviewNote.trim() || !confirmIdentity || !confirmLabelLogo || !confirmGeometryScale} className="mt-3 rounded-lg bg-emerald-600/80 px-3 py-2 text-[9px] font-bold uppercase tracking-widest text-white disabled:opacity-40">
						{busy === "approve" ? "Approving…" : "Approve Exact Cutout"}
					</button>
				</div>
			)}

			{error && <div className="mt-3 text-[10px] text-red-300">{error}</div>}
		</div>
	);
}
